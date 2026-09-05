# 15 — 持仓监控与推送

## 1. 需求与定位

### 1.1 新增的能力

原有设计是**盘后批处理**：每日收盘后跑一次，产出日报与建议清单。

现在增加**盘中监控**：持续监控持仓与市场消息，在判断持仓需要调整时主动推送。

```
原有  15:00 收盘 ──▶ 16:00 数据 ──▶ 17:00 研究 ──▶ 18:00 日报（被动查看）
新增  09:30-15:00 持续监控 ──▶ 触发条件满足 ──▶ 推送（主动告知）
```

### 1.2 核心约束

| 约束 | 说明 |
|---|---|
| **成本** | 不能每条新闻都调 LLM。必须三级漏斗过滤 |
| **不打扰** | 推送太多等于没有推送。每日推送有硬上限 |
| **不越界** | 推送是建议，不是指令。A 股阶段用户自行操作 |
| **可执行** | 推送必须在用户能操作的时段内到达 |
| **可追溯** | 每条推送关联到触发规则与证据 |

### 1.3 与既有架构的关系

监控层不是新的决策系统，而是**既有能力的事件驱动触发**：

```
持仓 + 实时数据
      ↓
  Monitor（规则层，零 LLM 成本）
      ↓ 触发
  既有的 Agent / Quant / Risk 能力（按需局部调用）
      ↓
  Notifier（推送）
```

关键设计：**监控层自己不做判断，只负责"什么时候该看一眼"。** 判断仍由既有组件完成。

## 2. 三级漏斗（成本控制核心）

这是整个监控系统能否成立的关键。

```
┌────────────────────────────────────────────────────────────┐
│ L1  规则层（零 LLM 成本）                                   │
│     价格触发 / 风控阈值 / 公告类型 / 关键词匹配             │
│     处理量：全部（每分钟数百次检查）                        │
│     通过率：~1%                                             │
└──────────────────────┬─────────────────────────────────────┘
                       ▼
┌────────────────────────────────────────────────────────────┐
│ L2  小模型层（低成本）                                      │
│     相关性判断 / 事件分类 / 影响方向初判                    │
│     处理量：L1 通过项（每日 ~50 条）                        │
│     通过率：~20%                                            │
└──────────────────────┬─────────────────────────────────────┘
                       ▼
┌────────────────────────────────────────────────────────────┐
│ L3  大模型层（高成本）                                      │
│     深度分析 / 生成建议 / 关联持仓影响                      │
│     处理量：L2 通过项（每日 ~5-10 次）                      │
└────────────────────────────────────────────────────────────┘
```

### 2.1 为什么必须三级

假设每日 2000 条新闻，直接用中模型逐条分析：
- 2000 次调用 × 长上下文 = 成本不可接受

三级漏斗后：
- L1 规则过滤：2000 → 50（零成本）
- L2 小模型：50 次短调用
- L3 大模型：5-10 次

成本降低两个数量级。

### 2.2 L1 规则层设计

L1 必须**完全不调 LLM**。所有判断基于结构化数据与关键词。

```python
class L1Filter:
    """零成本过滤。只做机械匹配，不做理解。"""

    def check_news(self, news: News, holdings: set[str]) -> L1Result:
        # ① 实体匹配：新闻是否提及持仓标的
        mentioned = self._match_entities(news, holdings)
        if not mentioned:
            # ② 行业匹配：是否提及持仓所属行业
            mentioned = self._match_industries(news, holdings)
        if not mentioned:
            return L1Result.drop("no_holding_relevance")

        # ③ 关键词强度：是否含高影响关键词
        severity = self._keyword_severity(news.title)
        if severity == "none":
            return L1Result.drop("low_severity_keywords")

        return L1Result.pass_to_l2(mentioned, severity)
```

实体匹配靠**预建的别名词典**，不靠 LLM：

```python
# 预建映射：公司简称、全称、常用别称、产品名 → symbol
ENTITY_ALIASES = {
    "600519.SH": ["贵州茅台", "茅台", "贵州茅台酒"],
    # 由 security 表 + 人工补充 + 定期从新闻中挖掘
}
```

关键词分级表（人工维护，可迭代）：

| 级别 | 关键词示例 |
|---|---|
| `critical` | 立案调查、退市风险、被查封、大股东减持、业绩预亏、暂停上市、董事长辞职 |
| `high` | 业绩预告、重大合同、收购、增发、解禁、评级下调、停产 |
| `medium` | 高管变动、股权激励、投资者关系活动、机构调研 |
| `none` | 其余 |

### 2.3 L2 小模型层设计

L2 的任务是**判断相关性与影响方向**，输出极简。

```python
class L2Triage(BaseModel):
    """小模型输出。字段刻意极少，控制输出 token。"""
    is_relevant: bool
    affected_symbols: list[str]      # 从候选中选择，不自由生成
    direction: Literal["positive", "negative", "neutral"]
    urgency: Literal["immediate", "today", "this_week", "low"]
    needs_deep_analysis: bool        # ★ 是否升级到 L3
```

Prompt 设计要点（省 token）：

```
判断以下新闻是否影响给定持仓。只输出 JSON，不解释。

持仓: 600519.SH(贵州茅台), 000858.SZ(五粮液)
新闻标题: {title}
新闻摘要: {summary_200chars}     ← ★ 不放全文

输出: {"is_relevant":bool,"affected_symbols":[],"direction":"","urgency":"","needs_deep_analysis":bool}
```

关键节省手段：
- **只放标题 + 200 字摘要**，不放全文
- 持仓列表只放代码 + 简称，不放财务数据
- 要求"只输出 JSON，不解释"→ 输出 token 从数百降到数十
- **批处理**：一次调用处理 5-10 条新闻（见 4.3）

### 2.4 L3 大模型层设计

L3 才做深度分析，且**复用既有的 StockAgent**，不新建 Agent。

```python
async def l3_deep_analysis(
    trigger: Trigger, holdings: PortfolioState, ctx: AgentContext
) -> AlertProposal:
    # 复用既有 StockAgent，但限定范围
    view = await StockAgent(trigger.symbol).run(
        ctx.with_focus(trigger)         # 注入触发上下文，聚焦分析
    )
    # 复用既有 RiskEngine 判断当前持仓是否需要调整
    current = holdings.weight(trigger.symbol)
    suggested = PortfolioEngine.reweight_single(view, holdings)
    risk = RiskEngine.check(suggested, holdings, as_of=ctx.as_of)
    return AlertProposal(view=view, risk=risk, ...)
```

**不新建 Agent 的理由**：既有 `StockAgent` 已有完整工具集与 red flag 识别能力。新建 Agent 意味着新 prompt、新测试、新评估，且能力重复。

## 3. 触发器设计

### 3.1 触发器分类

| 类别 | 是否需要 LLM | 检查频率 |
|---|---|---|
| A. 价格触发 | ❌ 纯规则 | 每 1-5 分钟 |
| B. 风控触发 | ❌ 纯规则 | 每 5 分钟 |
| C. 公告触发 | L1 规则 → 可能 L2/L3 | 实时（公告发布时） |
| D. 新闻触发 | L1 → L2 → 可能 L3 | 每 5 分钟批处理 |
| E. 定期触发 | 复用盘后流程 | 每日一次 |

### 3.2 A. 价格触发（零成本，最重要）

```yaml
# config/monitor/price_triggers.yaml
triggers:
  - code: "PX_STOP_LOSS"
    condition: "holding_return <= user.exit_policy.stop_loss.threshold"
    severity: "critical"
    message: "{name} 浮亏达 {return:.1%}，触及你设定的止损线 {threshold:.0%}"
    cooldown_hours: 24

  - code: "PX_TRAILING_STOP"
    condition: "user.exit_policy.stop_loss.type == 'trailing' and
                drawdown_from_entry_high >= user.exit_policy.stop_loss.trail_pct"
    severity: "critical"
    message: "{name} 自持仓高点回撤 {drawdown_from_entry_high:.1%}，触及移动止损 {trail_pct:.0%}"
    cooldown_hours: 24

  - code: "PX_TAKE_PROFIT"
    condition: "holding_return >= user.exit_policy.take_profit.next_stage_gain"
    severity: "high"
    message: "{name} 浮盈 {return:.1%}，达到你设定的第 {stage} 档止盈（建议减 {reduce:.0%}）"
    cooldown_hours: 24

  - code: "PX_TARGET_PRICE"
    condition: "user.exit_policy.take_profit.type == 'target_price' and
                last_price >= watchlist.target_price"
    severity: "high"
    message: "{name} 触及你设定的目标价 {target_price}"
    cooldown_hours: 24

  - code: "PX_LIMIT_UP"
    condition: "is_limit_up and holding_weight > 0"
    severity: "medium"
    message: "{name} 涨停。若计划卖出，注意封板可能打开"
    cooldown_hours: 4

  - code: "PX_LIMIT_DOWN"
    condition: "is_limit_down and holding_weight > 0"
    severity: "critical"
    message: "{name} 跌停，当前无法卖出"
    cooldown_hours: 4

  - code: "PX_SUSPENDED"
    condition: "is_suspended and holding_weight > 0"
    severity: "critical"
    message: "{name} 停牌"
    cooldown_hours: 24

  - code: "PX_BREAK_MA60"
    condition: "close < ma60 and prev_close >= prev_ma60"
    severity: "medium"
    message: "{name} 跌破 60 日线"
    cooldown_hours: 72

  - code: "PX_VOL_SPIKE"
    condition: "volume_ratio_5d > 3.0 and abs(pct_change) > 0.05"
    severity: "high"
    message: "{name} 放量异动，成交量为 5 日均量 {volume_ratio_5d:.1f} 倍"
    cooldown_hours: 6

  - code: "PX_DRAWDOWN_FROM_HIGH"
    condition: "drawdown_from_entry_high >= 0.12"
    severity: "high"
    message: "{name} 自建仓后高点回撤 {drawdown_from_entry_high:.1%}"
    cooldown_hours: 24
```

这类触发器覆盖了监控需求的大部分，且**完全零 LLM 成本**。

**止盈止损阈值来自用户配置**（`config/user/exit_policy_cn.yaml`，见 [09-portfolio-risk](09-portfolio-risk.md) 4.2a），不是硬编码。同一套触发器代码，不同用户读各自的阈值。三点：

- `PX_STOP_LOSS` / `PX_TRAILING_STOP` 互斥：由用户的 `stop_loss.type` 决定用哪个
- `PX_TAKE_PROFIT` 的 `next_stage_gain` 是分批止盈里下一个未触发的档位，触发一档后指向下一档
- 这些是**提醒，不自动卖出**（A 股阶段）。触及后进入次日执行清单或盘中推送，由用户确认
- 系统底线 `DD_005`（个股浮亏 -25% 强制减仓）独立于用户配置，见 B 类风控触发

```yaml
- code: "RISK_SECTOR_CONCENTRATION"
  condition: "max_industry_weight > 0.23"      # 阈值 25%，提前告警
  severity: "high"
  message: "{industry} 行业权重达 {weight:.1%}，接近上限 25%"

- code: "RISK_PORTFOLIO_DRAWDOWN"
  condition: "portfolio_drawdown >= 0.10"
  severity: "critical"
  message: "组合回撤 {drawdown:.1%}，回撤保护线 15%"

- code: "RISK_DAILY_LOSS"
  condition: "daily_pnl_pct <= -0.025"
  severity: "critical"
  message: "今日组合亏损 {daily_pnl_pct:.1%}"

- code: "RISK_SINGLE_WEIGHT"
  condition: "max_single_weight > 0.095"
  severity: "medium"
  message: "{name} 权重 {weight:.1%} 接近单股上限"

- code: "RISK_CASH_LOW"
  condition: "cash_ratio < 0.05"
  severity: "medium"
  message: "现金比例 {cash_ratio:.1%}，低于建议下限 10%"
```

### 3.4 C. 公告触发（L1 规则强）

交易所公告是结构化的，有类型字段，可以纯规则判断：

```python
CRITICAL_ANNOUNCEMENT_TYPES = {
    "立案调查", "退市风险警示", "停牌", "重大资产重组",
    "业绩预告-预亏", "业绩预告-下修", "控股股东变更",
    "违规担保", "债务违约", "审计意见-非标",
}

HIGH_TYPES = {
    "业绩预告-预增", "重大合同", "增发", "回购", "股权激励",
    "股东减持", "股东增持", "分红",
}

def check_announcement(ann: Announcement, holdings: set[str]) -> Trigger | None:
    if ann.symbol not in holdings:
        return None
    if ann.type in CRITICAL_ANNOUNCEMENT_TYPES:
        return Trigger(severity="critical", needs_l3=True)    # 升级深度分析
    if ann.type in HIGH_TYPES:
        return Trigger(severity="high", needs_l2=True)        # 先小模型判断
    return None
```

**持仓股的关键公告是最有价值的推送场景**，且成本极低（公告类型是结构化字段）。

### 3.5 D. 新闻触发（完整三级漏斗）

见第 2 节。要点：批处理 + 只用标题摘要 + 极简输出。

### 3.6 E. 定期触发

复用盘后流程，产出每日复盘推送（摘要版日报）。

## 4. Token 节约的具体手段

### 4.1 手段汇总

| # | 手段 | 节省幅度 | 实现阶段 |
|---|---|---|---|
| 1 | L1 规则前置过滤 | ~99% | P2a |
| 2 | 只传标题 + 摘要，不传全文 | ~80% | P2a |
| 3 | 批处理（多条新闻一次调用） | ~40% | P2a |
| 4 | 强制极简输出 schema | ~70% 输出 token | P2a |
| 5 | 结果缓存（相同新闻不重复分析） | 视重复率 | P2a |
| 6 | Prompt 缓存（固定前缀复用） | ~30-50% 输入 | P2b |
| 7 | 本地小模型做 L2 | ~100%（L2 部分） | P2b |
| 8 | 冷却期抑制重复触发 | 视场景 | P2a |
| 9 | 每日预算硬限制 + 降级 | 上限保障 | P2a |
| 10 | 持仓聚焦（只分析持仓相关） | ~90% | P2a |

### 4.2 手段 2：上下文最小化

```python
# ❌ 浪费：传全文
prompt = f"新闻内容：{news.body}"          # 可能 2000+ token

# ✅ 节省：传标题 + 截断摘要
prompt = f"标题：{news.title}\n摘要：{news.body[:200]}"   # ~100 token
```

L2 阶段只需判断相关性和方向，标题往往就够。只在升级到 L3 时才读全文。

### 4.3 手段 3：批处理

```python
# ❌ 逐条调用：50 条新闻 = 50 次调用 = 50 份系统 prompt 开销
for news in candidates:
    result = await llm.complete(build_prompt(news))

# ✅ 批处理：50 条 = 5 次调用（每次 10 条）
for batch in chunked(candidates, 10):
    results = await llm.complete(build_batch_prompt(batch))
```

批处理 prompt：

```
持仓: 600519.SH(茅台), 000858.SZ(五粮液), 000001.SZ(平安银行)

判断下列各条新闻是否影响持仓。按序号输出 JSON 数组，不解释。

1. {title_1}
2. {title_2}
...
10. {title_10}

输出格式: [{"i":1,"rel":false},{"i":2,"rel":true,"sym":["600519.SH"],"dir":"neg","urg":"today","deep":true},...]
```

注意输出用**缩写字段名**（`rel` 而非 `is_relevant`）。在批量场景下这能显著减少输出 token。解析时映射回完整字段。

**批处理的代价**：单条判断质量可能略降。需在 P2 实测对比。若质量下降明显，减小批大小（如 5 条）。

### 4.4 手段 5：结果缓存

```python
class AnalysisCache:
    """按内容哈希缓存分析结果。新闻常被多源重复报道。"""

    async def get_or_analyze(self, news: News, analyzer: Callable) -> L2Triage:
        key = f"l2:{news.content_hash}:{self._holdings_hash()}"
        if cached := await self._redis.get(key):
            self._metrics.cache_hit()
            return L2Triage.model_validate_json(cached)
        result = await analyzer(news)
        await self._redis.set(key, result.model_dump_json(), ex=86400)
        return result
```

缓存 key 含持仓哈希：持仓变化时缓存失效（因为相关性判断依赖持仓）。

新闻去重（`news_cluster`）在 L1 之前完成，缓存是第二层保障。

### 4.5 手段 6：Prompt 缓存

多数 LLM 提供商支持 prompt 缓存（固定前缀命中缓存后计费更低）。要点：

```python
# 把固定内容放前面，变化内容放后面
prompt = (
    SYSTEM_INSTRUCTIONS        # 固定，可缓存
    + HOLDINGS_CONTEXT          # 每日变化一次，可缓存
    + KEYWORD_REFERENCE         # 固定，可缓存
    + f"\n待判断新闻：{news}"    # 每次变化
)
```

具体缓存机制与折扣比例因提供商而异，需在 P2 实测。

### 4.6 手段 7：本地小模型

L2 的任务（相关性 + 方向分类）足够简单，可用本地小模型（如 Qwen 系列小尺寸模型）完成，成本降为零（仅算力）。

评估方法：用 API 小模型跑 500 条建立基线，本地模型对比准确率。若差距 < 5%，切换到本地。

### 4.7 手段 8：冷却期与抑制

```python
class SuppressionPolicy(BaseModel):
    # 同一触发器同一标的的冷却期
    cooldown_hours: dict[str, int]

    # 同一标的的推送总上限
    max_alerts_per_symbol_per_day: int = 3

    # 全局上限
    max_alerts_per_day: int = 10
    max_critical_per_day: int = 5

    # 静默时段（用户不希望被打扰）
    quiet_hours: list[tuple[time, time]] = [(time(22, 0), time(8, 0))]

    # 非交易时段是否推送
    notify_outside_session: bool = True   # critical 仍推，其他排队
```

冷却期不仅省 token，更重要的是**防止推送疲劳**。同一只股票一天推 5 次，用户会关掉通知。

### 4.8 手段 9：预算硬限制与降级

```python
class MonitorBudget(BaseModel):
    daily_usd_limit: float = 1.0          # 监控专用预算，与盘后流程分开
    l3_max_calls_per_day: int = 10        # L3 调用次数硬上限

    on_exceed: Literal["l1_only", "abort"] = "l1_only"
```

`on_exceed = l1_only`：预算耗尽后降级为纯规则监控。价格触发和风控触发仍然工作（它们不花钱），只是不再做新闻深度分析。

**这个降级设计很重要**：即使 LLM 预算用完，最关键的监控（止损、跌停、停牌、风控）依然有效。

### 4.9 成本核算

必须实测并记录到 `docs/cost-log.md`：

```markdown
## 监控层成本实测（2026-xx-xx ~ 2026-xx-xx，30 天）

| 层 | 日均处理量 | 日均调用 | 日均 token | 日均成本 |
|---|---|---|---|---|
| L1 规则 | 2,140 条 | 0 | 0 | $0 |
| L2 小模型 | 47 条 | 5 次（批） | 6.2k in / 0.4k out | $0.008 |
| L3 大模型 | 6 次 | 6 次 | 42k in / 3.1k out | $0.14 |
| 合计 | — | 11 | — | **$0.15/日** |

缓存命中率: 23%
批处理平均批大小: 9.4
L1 通过率: 2.2%
L2 升级率: 12.8%
推送数: 3.2 条/日
单条推送成本: $0.047
```

`单条推送成本`是最有意义的指标：它回答"每次提醒值不值这个钱"。

## 5. 推送设计

### 5.1 分级

| 级别 | 触发条件 | 推送时机 | 渠道 |
|---|---|---|---|
| `critical` | 止损线、跌停、停牌、立案调查、组合回撤超阈值 | 立即（含静默时段） | 全渠道 + 声音 |
| `high` | 放量异动、重要公告、风控接近上限 | 交易时段内立即，否则次日开盘前 | 主渠道 |
| `medium` | 技术位破位、权重偏离 | 汇总，每日 2 次（11:30 / 14:45） | 主渠道 |
| `info` | 每日复盘、周报 | 定时（18:00） | 主渠道 |

`14:45` 这个时间点是刻意的：A 股 15:00 收盘，留 15 分钟给用户操作。

### 5.2 推送内容规范

```python
class Alert(BaseModel):
    alert_id: str
    created_at: datetime
    severity: Literal["critical", "high", "medium", "info"]

    # 标题必须一眼看懂
    title: str = Field(max_length=60)

    # 正文：触发原因 + 当前状态 + 建议
    trigger_reason: str = Field(max_length=200)
    current_state: str = Field(max_length=200)
    suggestion: str | None = Field(max_length=300)

    # 关联信息
    symbols: list[str]
    trigger_codes: list[str]
    evidence_refs: list[str]

    # ★ 成本与来源透明
    analysis_level: Literal["L1", "L2", "L3"]
    cost_usd: float

    # 用户反馈（用于评估推送质量）
    feedback: Literal["useful", "not_useful", "ignored"] | None = None
```

推送样例（critical）：

```
🔴 贵州茅台 浮亏 8.2%，接近止损线

触发: PX_STOP_LOSS（止损线 -8%）
当前: 持仓 6.2%，成本 1680.00，现价 1542.20
      今日 -3.1%，近 5 日 -6.8%

建议: 止损线已触及。若无新增负面信息，考虑
      减仓至 3% 以内。跌破 1520 建议清仓。

依据: 无新增公告；行业板块今日 -1.2%（个股弱于板块）
分析级别: L1（规则触发，未调用 LLM）
```

样例（L3 深度分析）：

```
🟠 五粮液 业绩预告下修，需评估持仓

触发: ANN_CRITICAL（业绩预告-下修）
当前: 持仓 4.8%，浮盈 +2.1%

分析: 公司预告全年净利润同比下降 5%-10%，低于
      此前市场预期的持平。主因二季度渠道去库存
      导致发货放缓。管理层称三季度已恢复。

      需注意: 白酒板块内茅台、泸州老窖尚未预告，
      若同步下修则属行业性问题；若仅本公司则可能
      是份额流失。

建议: 暂不新增，等待同业预告确认是否为行业问题。
      若同业稳健而本公司独跌，考虑减仓至 2%。

依据: 公告 2026-08-31-0042；同业对比数据
分析级别: L3  成本: $0.031
```

注意最后一行**显式披露分析成本**。这让用户能判断系统是否在浪费钱。

### 5.3 推送渠道

| 渠道 | 用途 | 优先级 |
|---|---|---|
| **Telegram Bot** | 主渠道，支持富文本与按钮 | 1 |
| **ntfy / Bark** | 轻量推送，自托管友好 | 2 |
| 企业微信 / 钉钉机器人 | 国内网络更稳 | 2 |
| 邮件 | 日报、周报 | 3 |
| 本地桌面通知 | 开发调试 | 4 |

实现走适配器（与 BrokerAdapter 同思路）：

```python
class NotifierAdapter(ABC):
    @abstractmethod
    async def send(self, alert: Alert) -> DeliveryResult: ...

    @abstractmethod
    def supports_interactive(self) -> bool: ...   # 是否支持反馈按钮
```

### 5.4 反馈闭环

推送带反馈按钮（Telegram inline keyboard）：

```
[👍 有用]  [👎 没用]  [🔇 静音此规则 24h]
```

反馈数据用于：

| 用途 | 方法 |
|---|---|
| 评估触发器质量 | 各 `trigger_code` 的有用率 |
| 淘汰噪声规则 | 有用率 < 20% 的规则考虑关闭或提高阈值 |
| 校准 L2/L3 判断 | 对比 LLM 判断与用户反馈 |
| 控制成本 | 无用推送的成本是纯浪费，需量化 |

```sql
CREATE TABLE alert (
    alert_id      TEXT PRIMARY KEY,
    created_at    TIMESTAMPTZ NOT NULL,
    severity      TEXT NOT NULL,
    title         TEXT NOT NULL,
    body          JSONB NOT NULL,
    symbols       TEXT[] NOT NULL,
    trigger_codes TEXT[] NOT NULL,
    evidence_refs TEXT[],
    analysis_level TEXT NOT NULL,
    cost_usd      NUMERIC(12,6) NOT NULL DEFAULT 0,
    -- 投递
    channels      TEXT[] NOT NULL,
    delivered_at  TIMESTAMPTZ,
    delivery_error TEXT,
    -- 反馈
    feedback      TEXT,
    feedback_at   TIMESTAMPTZ,
    -- 关联
    run_id        TEXT REFERENCES agent_run(run_id)
);

CREATE INDEX idx_alert_created ON alert (created_at DESC);
CREATE INDEX idx_alert_trigger ON alert USING gin (trigger_codes);

-- 触发器质量统计
CREATE VIEW v_trigger_quality AS
SELECT
    unnest(trigger_codes) AS trigger_code,
    count(*) AS n_alerts,
    sum(cost_usd) AS total_cost,
    avg(CASE WHEN feedback = 'useful' THEN 1.0
             WHEN feedback = 'not_useful' THEN 0.0 END) AS useful_rate,
    count(feedback) AS n_feedback
FROM alert
WHERE created_at > now() - interval '90 days'
GROUP BY 1
ORDER BY n_alerts DESC;
```

## 6. 持仓数据来源

### 6.1 A 股阶段（无 API）

用户手动维护持仓。方案：

| 方案 | 说明 |
|---|---|
| **CSV / YAML 手动维护** | 最简单，首版用 |
| 券商对账单导入 | 定期导入，减少手工 |
| CLI 快速录入 | `qa position add 600519.SH 300 1680` |
| Telegram Bot 交互录入 | 通过对话更新持仓 |

```yaml
# data/positions/my_cn.yaml
account: "manual_cn"
base_currency: CNY
cash: 45000
as_of: "2026-08-31"
positions:
  - symbol: "600519.SH"
    quantity: 300
    avg_cost: 1680.00
    entry_date: "2026-07-15"
  - symbol: "000858.SZ"
    quantity: 800
    avg_cost: 142.50
    entry_date: "2026-08-02"
```

**持仓数据陈旧是主要风险**。缓解：
- 每日推送中显示"持仓数据更新于 X 天前"
- 超过 5 个交易日未更新则提醒
- 重要推送前校验持仓时效性

### 6.2 美股阶段（有 API）

从 `BrokerAdapter.get_positions()` 实时获取，无需手工维护。这是接 API 的实际收益之一。

### 6.3 空仓用户的监控行为（P5，冷启动之后）

冷启动推荐（[09-portfolio-risk](09-portfolio-risk.md) 第 8 节）引入第三种状态：**已推荐但未执行**。监控必须能处理这种情况，否则空仓用户完全收不到推送。

#### 三种状态的触发器可用性

| 触发器类型 | 实际持仓 | 已推荐未执行 | 关注列表 |
|---|---|---|---|
| `PX_STOP_LOSS`（止损） | ✅ | ❌ 无 `avg_cost` | ❌ |
| `PX_TAKE_PROFIT`（止盈） | ✅ | ❌ | ❌ |
| `PX_DRAWDOWN_FROM_HIGH` | ✅ | ❌ 无 `entry_high` | ❌ |
| `PX_LIMIT_UP/DOWN` | ✅ | ✅ | ✅ |
| `PX_SUSPENDED` | ✅ | ✅ | ✅ |
| `PX_VOL_SPIKE` | ✅ | ✅ | ✅ |
| `RISK_*`（组合类） | ✅ | ❌ 无实际组合 | ❌ |
| `CRITICAL_ANNOUNCEMENT` | ✅ | ✅ | ✅ |

**成本相关的触发器对未执行的推荐无意义**——没有成本就没有止损线。这不是缺陷，是定义问题。

#### 空仓用户特有的触发器

```yaml
# config/monitor/recommendation_triggers.yaml
- code: "REC_EXPIRED"
  condition: "now() > recommendation.expires_at"
  severity: "info"
  message: "建仓建议已过期（生成于 {days_ago} 天前），需重新评估"

- code: "REC_SCORE_DROPPED"
  condition: "current_score < recommendation.min_score_cfg"
  severity: "medium"
  message: "{name} 分数已跌破入选门槛（{old_score:.2f} → {new_score:.2f}），建议不再买入"

- code: "REC_PRICE_DEVIATED"
  condition: "abs(last / rec.ref_price - 1) > 0.05"
  severity: "medium"
  message: "{name} 现价已偏离推荐参考价 {deviation:.1%}，委托价区间需重算"

- code: "REC_EXCLUDED_NOW"
  condition: "security now matches EXCLUSION_RULES"
  severity: "high"
  message: "{name} 已触发排除规则（{rule}），从建仓清单移除"

- code: "REC_TRANCHE_DUE"
  condition: "scale_in_tranche.planned_date == today"
  severity: "info"
  message: "第 {tranche_no} 批建仓计划日到（占计划 {ratio:.0%}），执行前请复核分数"

- code: "REC_ENTRY_WINDOW"
  condition: "last <= rec.limit_price_low and not is_limit_down"
  severity: "medium"
  message: "{name} 回落至委托价区间下沿 {price}，建仓时机"

# 空仓期间的市场状态变化
- code: "REC_NO_POSITION_STANCE_CHANGE"
  condition: "prev_action == 'no_position' and current_stance improved"
  severity: "medium"
  message: "市场状态由 {old_stance} 转为 {new_stance}，候选池已有标的达到门槛，可重新评估建仓"

# 建仓进行中、stance 转好 → 建议在 investable 上限内追加
- code: "REC_STANCE_UP"
  condition: "scale_in in progress and current_stance > stance_at_last_tranche"
  severity: "medium"
  message: "市场状态由 {old_stance} 转为 {new_stance}，建仓期留出的现金可在你设定的投入额（{investable}）内追加，追加上限 {headroom}"

# 投入额调整建议 —— ★ 默认关闭，需用户显式开启（见 09 文档第 11 节 / ADR-0015）
# 开启后必须双向：机会质量高提示可加码，低则提示可减码
- code: "INVESTABLE_ADJUST"
  enabled: false                 # ★ 默认关闭，与实盘开关同级
  condition: "user.opt_in_investable_push and opportunity_quality crosses band"
  severity: "info"
  cooldown_days: 14              # 长冷却，强制冷静
  message: "机会质量信号 {oq:.2f}（{direction}）。可评估是否调整投入额。当前估值分位 {val_pct:.0%}，距高点 {from_high:.0%}。这不是让你立即行动，建议隔几日再决定。"
```

全部为**零 LLM 成本**（A 类价格 + 规则判断），符合第 6 条原则。

#### `INVESTABLE_ADJUST` 是全系统最敏感的触发器

它建议的不是"买哪只"，而是"你该往股市放多少本金"。四条铁律（详见 [ADR-0015](../adr/0015-investable-adjustment.md)）：

- **默认关闭**，用户显式开启（配置里 `enabled: false`）
- **双向**：机会质量高提示可加码，低则提示可减码——只推一个方向就是助推追高
- 触发是**机会质量**（高分且便宜的标的占比），**不含近期涨幅**——涨幅高恰恰该谨慎
- **绝不给具体金额**，只给市场位置这一个客观维度

用户主动问"现在适合提高投入吗"走**被动响应**（默认可用），系统给带完整反面信息的评估，见 09 文档 11.4。被动与主动的区别：被动是用户发起、系统提供依据；主动是系统在催——所以后者默认关。

#### `REC_NO_POSITION_STANCE_CHANGE` 与 `REC_STANCE_UP` 的分工

两个都响应"市场转好"，但针对的用户状态不同：

| 触发器 | 用户状态 | 建议 |
|---|---|---|
| `REC_NO_POSITION_STANCE_CHANGE` | 上次"暂不建仓" | 重新评估是否建仓 |
| `REC_STANCE_UP` | 正在分批建仓 | 在 `investable` 上限内追加（原 defensive 留的现金） |

`REC_STANCE_UP` 有一条**硬边界必须在文案里说清**：追加只动用 `investable` 内因 stance 留出的现金，**绝不触碰未投入资金**。message 里的 `{headroom}` = `investable × new_exposure − 已投入`，让用户看到追加上限。这对应 [09-portfolio-risk](09-portfolio-risk.md) 8.4 的 `increase_exposure`。

#### 抑制策略的差异

| 项 | 有持仓用户 | 空仓/待执行用户 |
|---|---|---|
| 每日上限 | 10 条 | **3 条** |
| `REC_TRANCHE_DUE` 冷却期 | — | 仅计划日推送一次 |
| `REC_ENTRY_WINDOW` 冷却期 | — | 24 小时 |
| 静默时段 | 22:00-08:00 | 同 |

**空仓用户的推送上限更低**：没有持仓就没有紧迫性，高频推送只会制造焦虑并催促交易——这与系统定位相悖。

#### 一条明确的禁止

```python
# ❌ 禁止：把推荐标的当作持仓来监控
def build_monitor_state_wrong(account_id: int) -> PortfolioState:
    positions = repo.get_manual_positions(account_id)
    positions += repo.get_recommendation_items(account_id)   # ★ 错
    return PortfolioState(positions=positions)
```

理由：会导致 `RISK_PORTFOLIO_DRAWDOWN` 等组合类触发器基于虚构的持仓计算，产生假告警。同时会污染 `v_recommendation_quality` 的执行率统计。

```python
def test_recommendation_not_treated_as_position():
    """推荐标的不得进入 PortfolioState.positions。"""
```

## 7. 实时数据获取

### 7.1 盘中数据的现实约束

| 数据 | 可得性 | 延迟 |
|---|---|---|
| A 股实时行情（akshare 快照接口） | 可得 | 秒到分钟级，具体需实测 |
| A 股逐笔/盘口 | 免费源有限 | — |
| 交易所公告 | 官网列表页轮询 | 分钟级 |
| 财联社快讯 | 可得 | 分钟级 |

**明确不追求低延迟**：定位是中低频监控，分钟级延迟完全够用。如果某个信号需要秒级响应才有价值，那不在本系统能力范围内（见 00 文档的非目标）。

### 7.2 轮询策略

```yaml
# config/monitor/schedule.yaml
polling:
  price_snapshot:
    interval_seconds: 180              # 3 分钟
    sessions_only: true
    symbols: "holdings + watchlist"    # 只拉需要的，不拉全市场

  announcements:
    interval_seconds: 300
    sessions_only: false               # 盘后也有公告

  news:
    interval_seconds: 300
    batch_process: true                # 累积后批量处理

  risk_check:
    interval_seconds: 300
    sessions_only: true
```

**只拉持仓 + 关注列表的行情**，不拉全市场。这大幅降低数据源压力和处理量。

### 7.3 与盘后流程的关系

| 流程 | 时间 | 范围 | 目的 |
|---|---|---|---|
| 盘中监控 | 09:30-15:00 | 持仓 + 关注列表 | 发现需要立即处理的情况 |
| 盘后批处理 | 15:30-18:00 | 全股票池 | 完整研究与调仓建议 |

两者互补：监控是"救火"，盘后是"规划"。监控不做全市场扫描（成本不允许），盘后不做实时响应。

## 8. 架构位置

监控层在架构中的位置：

```
┌─────────────────────────────────────────────────────────┐
│ L6  Presentation    CLI / 日报 / ★ Notifier             │
├─────────────────────────────────────────────────────────┤
│ L5  Evaluation      Journal / Shadow / ★ Alert 质量评估 │
├─────────────────────────────────────────────────────────┤
│ ★ L4.5 Monitor      Trigger 引擎 / 三级漏斗 / 抑制策略  │
│                     依赖 L1-L3，不含新决策逻辑           │
├─────────────────────────────────────────────────────────┤
│ L4  Execution       ...                                  │
│ L3  Decision        ... （监控复用 RiskEngine）          │
│ L2  Intelligence    ... （监控复用 StockAgent）          │
│ L1  Data Access     ... （监控复用 Repository）          │
│ L0  Data Foundation ... （新增实时快照 Collector）       │
└─────────────────────────────────────────────────────────┘
```

依赖约束：

```python
# monitor 可以依赖 decision / agents / core
# 但 decision / agents 不得依赖 monitor
FORBIDDEN += [
    ("decision", ["monitor"]),
    ("agents", ["monitor"]),
    ("quant", ["monitor"]),
]
```

## 9. 目录结构增补

```
src/quantagent/
├── monitor/                        # ★ 新增
│   ├── triggers/
│   │   ├── base.py                 # Trigger 协议
│   │   ├── price.py                # A 类：价格触发
│   │   ├── risk.py                 # B 类：风控触发
│   │   ├── announcement.py         # C 类：公告触发
│   │   ├── news.py                 # D 类：新闻触发
│   │   └── registry.py
│   ├── funnel/
│   │   ├── l1_rules.py             # ★ 零成本规则层
│   │   ├── l2_triage.py            # 小模型分诊
│   │   ├── l3_analysis.py          # 复用 StockAgent
│   │   ├── entity_matcher.py       # 别名词典匹配
│   │   └── keywords.py             # 关键词分级表
│   ├── suppression.py              # 冷却期与上限
│   ├── budget.py                   # 监控专用预算
│   ├── cache.py                    # 结果缓存
│   └── engine.py                   # 监控主循环
│
├── notify/                         # ★ 新增
│   ├── base.py                     # NotifierAdapter
│   ├── telegram.py
│   ├── ntfy.py
│   ├── wecom.py
│   ├── email.py
│   ├── formatter.py                # Alert → 各渠道格式
│   └── feedback.py                 # 反馈收集
│
├── positions/                      # ★ 新增
│   ├── manual.py                   # YAML/CSV 持仓维护
│   ├── importer.py                 # 对账单导入
│   └── staleness.py                # 时效性检查
```

配置增补：

```
config/monitor/
├── price_triggers.yaml
├── risk_triggers.yaml
├── announcement_types.yaml
├── keywords.yaml                   # 关键词分级
├── entity_aliases.yaml             # 实体别名（可自动生成 + 人工补充）
├── suppression.yaml
├── budget.yaml
└── schedule.yaml

config/notify/
├── channels.yaml
└── templates/
```

## 10. 实施阶段

监控功能拆成两个子阶段，插入 P2 之后。

### P2a — 规则监控（1-2 周，零 LLM 成本）

| 内容 |
|---|
| 持仓手动维护（YAML + CLI） |
| 实时行情快照 Collector（仅持仓 + 关注列表） |
| A 类价格触发器全套 |
| B 类风控触发器全套 |
| C 类公告触发（纯规则，按公告类型） |
| 抑制策略（冷却期、每日上限、静默时段） |
| Telegram Notifier + 反馈按钮 |
| `alert` 表与质量统计视图 |

**关键**：P2a **完全不调 LLM**。先验证触发器是否有用、推送频率是否合适、用户是否会看。

如果 P2a 的推送有用率低于 40%，说明触发器设计有问题，此时加 LLM 只会放大问题。

### P2b — 智能分诊（2-3 周）

| 内容 |
|---|
| 实体别名词典构建 |
| 关键词分级表 |
| L1 新闻过滤 |
| L2 小模型分诊（批处理 + 极简输出） |
| L3 深度分析（复用 StockAgent） |
| 结果缓存 |
| 监控预算与降级 |
| 成本实测与记录 |
| 本地小模型评估（可选） |

## 11. Gate 2a / 2b

### Gate 2a — 规则监控

| 条件 | 阈值 |
|---|---|
| 触发器全部有单元测试 | 100% |
| 连续 20 交易日无漏报（人工抽检关键事件） | — |
| 日均推送数 | 2-8 条（过少无用，过多疲劳） |
| 推送有用率（用户反馈） | > 40% |
| 静默时段被正确遵守 | 有测试 |
| 冷却期生效 | 有测试 |
| 持仓陈旧提醒生效 | 有测试 |
| **LLM 成本** | **$0** |
| 推送投递成功率 | > 99% |

### Gate 2b — 智能分诊

| 条件 | 阈值 |
|---|---|
| L1 通过率 | < 5%（否则过滤不足） |
| L2 升级到 L3 率 | < 25% |
| L3 日均调用 | ≤ 10 次 |
| **监控层日均成本** | **< $0.30** |
| 单条推送成本 | < $0.10 |
| 缓存命中率 | > 15% |
| L2 判断准确率（人工抽检 200 条） | > 85% |
| 推送有用率 | > 50%（应高于 P2a） |
| 预算耗尽时正确降级为 L1 | 有测试 |
| 批处理未显著降低判断质量 | 对比测试 |

**注意 Gate 2b 要求推送有用率高于 P2a。** 如果加了 LLM 反而没提升，说明 LLM 层没有产生价值，应该回退到纯规则监控（省钱）。

## 12. 与既有原则的一致性

监控功能不破坏任何既有原则：

| 原则 | 监控层如何遵守 |
|---|---|
| Risk Engine 不可被 LLM 覆盖 | 监控复用 RiskEngine，不新建判定逻辑 |
| 所有查询走 `as_of(t)` | 监控用 `as_of=today`，同一接口 |
| LLM 不得直接下单 | 监控只推送，不执行 |
| 实盘开关默认关闭 | 监控不涉及执行 |
| 决策可追溯 | `alert` 表记录 trigger_codes + evidence_refs + cost |

新增一条原则：

**6. 监控的规则层必须零 LLM 成本，且在 LLM 预算耗尽时仍能工作。** 最关键的监控（止损、跌停、停牌、组合回撤）不依赖 LLM。
