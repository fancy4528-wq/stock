# 08 — 回测与评估

## 1. 为什么自建回测引擎

A 股的三条规则必须是引擎的一等公民，不能是补丁：

| 规则 | 影响 |
|---|---|
| T+1 | 当日买入不可卖出，需独立跟踪 `sellable_qty` |
| 涨跌停不可成交 | 涨停买不进、跌停卖不出。**这是最大的回测陷阱** |
| 停牌 | 无法交易，但持仓需要估值 |

第二条尤其关键：动量策略最想买的往往正是涨停的股票。不模拟这一点，回测收益会系统性高估，且幅度常常超过滑点影响。

**规则随时间变化，回测必须按 `trade_date` 取当日生效的规则（已核实）**：2023 年全面注册制改革改了新股规则——旧核准制主板新股首日 +44%/-36%、前 5 日有限制；现行注册制主板/科创板/创业板前 5 日**不设涨跌幅**。`_can_fill` 判断 `is_limit_up` 时依赖的涨跌幅参数必须来自**该交易日**的规则版本，不能用当前规则套历史数据。否则跨改革点回测会系统性错判新股成交可行性。规则版本随市场配置一起 PIT 化（见 [05-market-config](05-market-config.md) 的 `price_limit`），`MarketConfig.as_of(trade_date)` 返回当日规则。

## 2. 回测引擎设计

### 2.1 与实时流程共享代码

```python
# 回测和实时用同一份 Stage 3-5 代码，区别只在数据源和 Broker
async def run_one_day(as_of: date, ctx: RunContext) -> DayResult:
    panel   = ctx.repo.get_panel(as_of=as_of)          # 回测: 历史; 实时: 当日
    factors = FactorLibrary.compute(panel)             # 同一份
    preds   = ctx.model.predict(factors, as_of=as_of)  # 同一份
    scores  = SignalFusion.fuse(preds, ctx.views)      # 同一份
    target  = PortfolioEngine.build(scores, ctx.state) # 同一份
    result  = RiskEngine.check(target, ctx.state)      # 同一份
    fills   = await ctx.broker.execute(result, as_of)  # 回测: Simulated; 实时: 真实
    return ctx.state.apply(fills)
```

任何 `if backtest:` 分支都是 bug 温床。唯一允许的差异是注入的依赖。

### 2.2 撮合逻辑（核心）

```python
class SimulatedBroker(BrokerAdapter):
    """回测撮合。所有市场约束在此实现。"""

    def _can_fill(
        self, order: Order, bar: PriceBar, cfg: MarketConfig, state: PortfolioState
    ) -> FillDecision:
        # ① 停牌
        if bar.is_suspended:
            return FillDecision.reject("suspended")

        # ② 涨跌停
        if order.side == "buy" and bar.is_limit_up:
            return FillDecision.reject("limit_up_cannot_buy")
        if order.side == "sell" and bar.is_limit_down:
            return FillDecision.reject("limit_down_cannot_sell")

        # ③ T+1 可卖数量
        if order.side == "sell" and not cfg.same_day_sell_allowed:
            if order.quantity > state.sellable_qty(order.security_id):
                return FillDecision.partial(state.sellable_qty(order.security_id))

        # ④ 成交量约束（不能吃掉超过当日量的 X%）
        max_qty = bar.volume * cfg.slippage.max_volume_share
        if order.quantity > max_qty:
            return FillDecision.partial(max_qty, reason="volume_limit")

        # ⑤ 限价单价格可达性
        if order.order_type == "limit":
            if order.side == "buy" and order.limit_price < bar.low:
                return FillDecision.reject("limit_price_not_reached")
            if order.side == "sell" and order.limit_price > bar.high:
                return FillDecision.reject("limit_price_not_reached")

        return FillDecision.full()
```

### 2.3 成交价格假设

| 假设 | 说明 |
|---|---|
| 决策时点 | T 日收盘后 |
| 成交时点 | **T+1 开盘** |
| 成交价 | T+1 开盘价 × (1 ± 滑点) |
| 禁止 | 用 T 日收盘价成交（未来函数） |
| 禁止 | 用 T+1 收盘价成交（乐观假设，隐含日内择时能力） |

用 T+1 开盘价是保守且现实的假设。若要更保守，可用 T+1 的 VWAP 或开盘后 30 分钟均价。

### 2.3a 撮合规则是假设，不是事实 —— 必须被校准

**这一节是本文档最重要的免责声明。**

2.2 和 2.3 节的撮合逻辑全部是**推断**，而**本文档全部评估结论都建立在它们之上**：

| 假设 | 依据 | 被真实撮合验证过 |
|---|---|---|
| 涨停价不可买入 | 常识推断 | **否** |
| 跌停价不可卖出 | 常识推断 | **否** |
| 停牌期间订单被拒 | 常识推断 | **否** |
| 单笔不超过当日成交量 X% | 经验取值 | **否** |
| T+1 开盘价成交 | 保守假设 | **否** |
| 集合竞价成交价与优先级 | 规则文档 | **否** |
| 部分成交剩余处理 | 自行设计 | **否** |
| 滑点模型的量级 | 经验取值 | **否** |

单元测试只能验证**代码符合我的假设**，无法验证**假设符合现实**。

所以回测报告里的每一个数字都应理解为"在这组假设成立的前提下"。校准方案见 [10-execution](10-execution.md) 3.4 节与 [ADR-0012](adr/0012-cn-simulated-trading.md)：

```
同一组订单 ──┬──▶ SimulatedBroker   → fills_sim
             └──▶ 券商模拟环境       → fills_real
                        ↓
        若某项假设错误 → 修正 SimulatedBroker
                       → ★ 重跑全部历史回测
                       → 若结论翻转，此前评估全部无效
```

**校准应尽早做。** 越晚发现假设错误，需要推翻的结论越多。这也是为什么 P7b-1（模拟环境验证）设计成可与 P2-P6 并行。

**回测报告模板中必须声明**：本次回测所依据的撮合假设是否已被校准，校准日期与偏差量级。未校准的回测结论应标注"撮合假设未验证"。

### 2.4 成本模型

```python
def calc_cost(fill: Fill, cfg: MarketConfig) -> CostBreakdown:
    amount = fill.quantity * fill.price
    commission = max(amount * cfg.fees.commission_rate, cfg.fees.commission_min)
    stamp = amount * (cfg.fees.stamp_duty_sell if fill.side == "sell" else 0)
    transfer = amount * cfg.fees.transfer_fee_rate
    return CostBreakdown(commission=commission, tax=stamp, other=transfer)
```

滑点模型三选一（配置决定）：

| 模型 | 公式 | 适用 |
|---|---|---|
| `fixed_bps` | `price × (1 ± bps/10000)` | 简单，首版用 |
| `volume_share` | 滑点随订单占当日成交量比例递增 | 更现实 |
| `spread_based` | 基于买卖价差 | 需要盘口数据 |

A 股首版建议 `fixed_bps = 10`（比美股保守），因为流动性差异大。

### 2.5 基准与再平衡

| 配置 | 默认 |
|---|---|
| 基准 | 沪深300（`000300.SH`）/ 美股 SPY |
| 再平衡频率 | 周频（每周一）或月频，日频换手过高 |
| 再平衡触发 | 定期 + 偏离阈值（权重偏离目标 > 5% 时触发） |
| 现金处理 | 现金不计息（保守） |
| 分红处理 | 现金分红计入现金，不自动再投 |

## 3. 防偏差清单

回测的价值完全取决于这些偏差是否被消除。**每一项都要有对应的自动化检查。**

### 3.1 未来函数（Look-ahead Bias）

| 检查 | 手段 |
|---|---|
| 数据取用不超过 as_of | Repository 层运行时断言 |
| 财务数据用 `announced_at` 过滤 | SQL 函数强制 |
| 行业/成分股按时点查 | 区间表 + PIT 函数 |
| 复权因子 PIT | `adjust_factor.announced_at` |
| 模型预测日晚于训练结束日 | `validate_prediction` |
| Agent 证据不来自未来 | `check_evidence_pit` |
| RAG 检索 PIT 过滤 | `search_chunks_as_of` |
| **年报 chunk 用披露日非报告期末** | `document_chunk.visible_at` 校验 |
| **知识文档未生效则不可见** | `expires_at` 双向过滤 |
| **thesis chunk 用结果确认时间** | `visible_at = as_of + 20 交易日` |
| 标签用 T+1 开盘价 | 标签构造函数 |
| **哨兵测试** | 见 3.4 |

知识层的三条容易被忽略：

| 陷阱 | 错误后果 |
|---|---|
| 年报 `visible_at` 设为报告期末 | 回测中 2026-01 就能读到 2025 年报（实际 04 月才披露） |
| 知识文档无 `expires_at` | 回测 2018 年时检索到 2024 年监管规则 |
| thesis chunk 用 `as_of_date` | Agent 读到"这个判断后来错了" —— 直接的未来函数 |

第三条最危险：thesis 片段的内容**包含结果**，而结果在写下 thesis 的当时不可知。详见 [17-knowledge-base](17-knowledge-base.md) 5.2 节。

### 3.2 生存者偏差（Survivorship Bias）

| 检查 | 手段 |
|---|---|
| 退市股票保留在库 | `security.delist_date`，禁止 DELETE |
| 股票池按时点快照 | `universe_snapshot`，禁用当前成分回溯 |
| 退市股票的退市损失计入 | 退市日按最后价格清仓（或按实际退市规则） |
| ST 股票不被事后剔除 | 只按时点 ST 状态过滤 |

自动检查：

```python
def test_universe_contains_delisted():
    """2018 年的股票池必须包含之后退市的股票。"""
    u2018 = repo.get_universe(as_of=date(2018, 1, 1), name="csi300")
    delisted = repo.get_delisted_between(date(2018, 1, 1), date(2025, 1, 1))
    assert set(u2018) & set(delisted), "股票池不含任何后来退市的股票，可疑"
```

### 3.3 其他偏差

| 偏差 | 表现 | 防范 |
|---|---|---|
| **选择偏差** | 只回测自己熟悉的股票 | 股票池按规则生成，不手选 |
| **过拟合** | 调参后回测变好 | `param_search_count` + 封存期 |
| **数据窥探** | 反复用同一测试集 | Walk-forward + 封存期一次性 |
| **流动性幻觉** | 假设能买入低流动性股票 | 成交量约束 + 流动性过滤 |
| **成本低估** | 忽略滑点或印花税 | 完整成本模型 + 保守滑点 |
| **复权错误** | 用后复权价算历史收益 | 存未复权价 + PIT 因子 |
| **重述偏差** | 用修订后的财务数据 | `revision` + `announced_at` |
| **时区错误** | 跨市场时间戳混乱 | 统一 UTC 存储 + 市场时区配置 |

### 3.4 未来函数哨兵测试

这是检测未来函数最有效的手段，P0 就要实现。

```python
def test_no_lookahead_sentinel():
    """向未来注入荒谬数据，历史回测结果不应改变。"""
    baseline = run_backtest(start="2023-01-01", end="2023-06-30")

    with inject_fake_data(after=date(2023, 7, 1), price_multiplier=100):
        polluted = run_backtest(start="2023-01-01", end="2023-06-30")

    assert baseline.metrics == polluted.metrics, (
        "未来数据影响了历史回测 → 存在未来函数"
    )
```

变体：同时污染财务数据、新闻、因子值，逐一定位泄漏点。

## 4. 评估指标

### 4.1 指标全表

```python
class BacktestMetrics(BaseModel):
    # 收益
    total_return: float
    cagr: float
    excess_return: float              # 相对基准
    alpha: float
    beta: float

    # 风险
    volatility: float
    downside_volatility: float
    max_drawdown: float
    max_drawdown_duration_days: int
    var_95: float
    cvar_95: float

    # 风险调整
    sharpe: float
    sortino: float
    calmar: float                     # CAGR / MaxDD
    information_ratio: float          # 超额收益 / 跟踪误差

    # 交易
    win_rate: float
    profit_factor: float
    avg_win: float
    avg_loss: float
    payoff_ratio: float
    turnover_annual: float
    total_cost_pct: float             # 成本占总收益的比例
    n_trades: int

    # 稳定性
    monthly_win_rate: float
    worst_month: float
    best_month: float
    return_by_year: dict[int, float]
    return_by_regime: dict[str, float]

    # 容量
    avg_position_vs_volume: float
    capacity_estimate: float | None   # 估计的策略容量（资金规模上限）
```

### 4.2 报告优先顺序

**不要以收益率为首要指标。** 报告应按此顺序展示：

1. **是否通过防偏差检查**（不通过则后面数字无意义）
2. Max Drawdown 与 Calmar
3. Sharpe / Sortino
4. 分年度收益一致性
5. 成本占收益比例
6. 换手率与容量
7. 最后才是总收益

理由：`+50% / MDD -45%` 远不如 `+25% / MDD -10%`。而如果成本占了收益的 60%，说明策略在成本敏感区间，实盘会失效。

### 4.3 对照组必须齐全

每次回测报告必须同时给出：

| 对照 | 目的 |
|---|---|
| Buy & Hold 基准 | 最基础参照 |
| 等权股票池 | 剔除选股能力后的表现 |
| 单最强因子 | 复杂度是否值得 |
| L2 等权多因子 | 模型是否优于线性组合 |
| 随机选股（100 次蒙特卡洛） | 结果是否在随机分布之外 |

最后一项很重要：如果策略收益落在随机选股分布的 80% 分位内，说明没有显著能力。

## 5. Shadow Portfolio

### 5.1 为什么它是最重要的交付物

回测是"如果历史重演"，Shadow Portfolio 是"从今天开始真的会怎样"。它能验证回测无法验证的东西：

| 只有 Shadow 能验证的 | 说明 |
|---|---|
| Agent 层的真实价值 | LLM 输出无法回测（无法重放历史调用） |
| 数据管道的实时可靠性 | 回测用的是清洗好的历史数据 |
| 决策的时效性 | 数据延迟、流程耗时的真实影响 |
| 无过拟合的样本外表现 | 未来数据不可能被窥探 |

### 5.2 硬性要求

| 要求 | 实现 |
|---|---|
| **自动记录** | 每日定时任务，无需人工触发 |
| **不可事后修改** | `decision_journal` append-only 触发器 |
| **完整成本模拟** | 与回测同一份成本模型 |
| **完整约束模拟** | T+1、涨跌停、停牌、流动性 |
| **记录未执行原因** | 涨停买不进也要记录（这是真实的机会损失） |
| **多组合并行** | 见 5.3 |

### 5.3 并行多组合设计

同时跑多个 shadow 组合，用于对比：

| 组合 | 信号来源 | 目的 |
|---|---|---|
| `shadow_baseline` | 等权池 | 参照 |
| `shadow_quant` | 仅量化模型 | Quant 的独立价值 |
| `shadow_agent` | 仅 Agent 评分 | **Agent 的独立价值** |
| `shadow_fused` | Fusion 综合 | 融合是否优于单独 |
| `shadow_fused_norisk` | Fusion 但不过风控 | 风控的成本与价值 |

第三个组合是关键：它直接回答"Agent 层有没有用"。第五个回答"风控让我损失了多少收益、避免了多少回撤"。

### 5.4 启动时机

**P1 完成后立即启动，不等策略成熟。**

理由：Shadow Portfolio 需要真实时间积累，是唯一无法靠加班压缩的环节。用粗糙策略跑 6 个月，比用完美策略跑 1 个月有价值。

```
P1 完成 ──▶ Shadow 启动 ──▶ 持续积累 ──────────────────▶
              (策略可以边跑边改，但要记录版本变更)
```

策略变更时不重置 Shadow，而是记录 `strategy_version` 变更点，分段评估。

## 6. Agent 层的评估难题

### 6.1 问题

Agent 输出无法回测：
- 无法重放历史 LLM 调用（成本高、结果不确定）
- 即使能重放，LLM 的训练数据可能已包含"未来"信息（知识截止日期之后的历史，模型可能知道结果）

第二点尤其严重：让 2024 年训练的模型分析 2023 年的新闻，它可能"记得"后来发生了什么。

### 6.2 解决方案

| 方案 | 做法 | 局限 |
|---|---|---|
| **前向记录（主要）** | Shadow Portfolio 实时积累 | 慢，需 6 个月起 |
| 小样本人工回测 | 抽 20-30 个历史时点，人工检查 Agent 输出是否合理 | 主观，样本少 |
| 剔除结果信息测试 | 只给 Agent 财报数字不给新闻，看 IC 变化 | 间接 |
| 知识截止日之后的时段 | 用模型知识截止日之后的历史做回测 | 时段有限 |

结论：**Agent 层主要靠前向验证。这是必须接受的现实，也是 Shadow 要尽早启动的根本原因。**

### 6.3 Agent 评估指标

```python
class AgentEvalResult(BaseModel):
    agent_name: str
    period: tuple[date, date]
    n_outputs: int

    # 工程质量
    schema_pass_rate: float
    evidence_coverage: float
    untraceable_figure_rate: float
    pit_violations: int
    avg_retries: float
    avg_cost_usd: float

    # 预测能力（★ 核心）
    score_ic_5d: float                # score 与 5 日超额收益的秩相关
    score_ic_20d: float
    score_ic_t_stat: float
    ranking_ic: float                 # 排序 IC

    # 校准
    confidence_calibration: dict[str, float]  # 分 confidence 档的准确率
    calibration_slope: float                  # 理想为 1.0

    # 分条件表现（★ 自我认知的基础）
    ic_by_regime: dict[str, float]
    ic_by_sector: dict[str, float]
    ic_by_volatility: dict[str, float]
    ic_near_earnings: float
    ic_high_news_volume: float
```

### 6.4 Confidence 校准检验

```python
def check_calibration(views: list[AgentView], outcomes: list[Outcome]) -> dict:
    """高 confidence 的判断准确率应该更高。若不然，confidence 无意义。"""
    buckets = {"0.0-0.5": [], "0.5-0.7": [], "0.7-0.85": [], "0.85-1.0": []}
    for v, o in zip(views, outcomes):
        buckets[bucket_of(v.confidence)].append(o.hit_5d)
    return {k: mean(v) for k, v in buckets.items() if v}
```

期望结果：准确率随 confidence 档单调上升。若不单调，说明 Agent 的 confidence 只是语言自信度，应在 Fusion 中忽略该字段。

### 6.5 必须接受的可能结论

**Agent 层的 IC 可能接近 0。**

如果测出这个结果，不要通过调 prompt 反复尝试直到 IC 变正（这是在过拟合）。诚实的结论是：

> Agent 层不产生 alpha，但产生解释力与风险识别能力。

此时的正确做法：
- 把 Agent 的权重在 Fusion 中降到很低或置零
- 保留 Agent 用于生成研究报告、识别 red flag、解释市场
- 把 alpha 的期望放在 Quant 层

这不是失败。一个知道自己哪部分无效的系统，比一个不知道的系统强得多。

## 7. 归因分析

### 7.1 收益分解

```
总收益
├── 市场收益（beta × 基准收益）
└── 超额收益（alpha）
    ├── 板块配置贡献
    ├── 个股选择贡献
    ├── 择时贡献
    └── 交易成本（负）
```

### 7.2 信号贡献归因

```python
def attribute_by_signal(journal: list[Decision], outcomes: list[Outcome]) -> dict:
    """各信号源对最终收益的贡献。
    方法：对每个信号，计算「只用该信号的组合」收益，与实际组合对比。"""
```

这回答了关键问题：Fusion 里的 5 个信号，哪些真的在贡献，哪些只是噪声。

### 7.3 信号相关性检查

Fusion 等权的陷阱在于信号高度相关。必须定期检查：

```python
def check_signal_independence(journal: list[Decision]) -> pl.DataFrame:
    """计算各信号的相关矩阵与单独 IC。
    相关性 > 0.7 的信号应合并，否则实际权重被放大。"""
```

技术面、量化因子、板块动量三者本质都从价格衍生，等权相加实际给了价格动量 60% 权重。这个检查在 P4 必须做。

## 8. 决策日志分析

### 8.1 核心查询

```sql
-- 分市场状态的准确率
SELECT
    dj.market_regime,
    count(*) AS n,
    avg(CASE WHEN do.hit_5d THEN 1.0 ELSE 0.0 END) AS accuracy_5d,
    avg(do.excess_ret_5d) AS avg_excess_5d,
    corr(dj.fused_score, do.excess_ret_5d) AS score_corr
FROM decision_journal dj
JOIN decision_outcome do USING (decision_id)
WHERE dj.as_of_date > current_date - interval '180 days'
GROUP BY dj.market_regime
ORDER BY n DESC;
```

```sql
-- 哪些条件下判断最差
SELECT
    CASE
        WHEN dj.signal_components->>'news_volume' > '10' THEN 'high_news'
        WHEN (dj.prediction->>'expected_vol')::numeric > 0.4 THEN 'high_vol'
        ELSE 'normal'
    END AS condition,
    count(*) AS n,
    avg(CASE WHEN do.hit_5d THEN 1.0 ELSE 0.0 END) AS accuracy
FROM decision_journal dj
JOIN decision_outcome do USING (decision_id)
GROUP BY 1;
```

### 8.2 自我评估报告

每月自动生成，包含：

| 章节 | 内容 |
|---|---|
| 整体表现 | 各 shadow 组合的收益与风险 |
| 信号有效性 | 各信号 IC 及趋势 |
| 因子健康度 | 因子衰减监控 |
| Agent 质量 | 工程指标 + IC |
| 分条件准确率 | 按 regime / 波动率 / 事件 |
| 失效告警 | 哪些信号/因子近期失效 |
| 成本分析 | 交易成本、LLM 成本 |

这份报告是系统"知道自己什么时候可信"的载体。

## 9. 回测执行规范

### 9.1 每次回测必须记录

```python
class BacktestRecord(BaseModel):
    backtest_id: int
    name: str
    strategy_version: str
    code_version: str              # git commit
    market_config_hash: str
    risk_config_hash: str
    universe_code: str
    period: tuple[date, date]
    params: dict

    # ★ 过拟合追踪
    param_search_count: int        # 该策略累计尝试的参数组合数
    used_holdout: bool

    metrics: BacktestMetrics
    bias_checks: dict[str, bool]   # 各项防偏差检查结果
```

`param_search_count` 累计到两位数时，回测结果的可信度已大幅下降，报告中应显式警告。

### 9.2 回测报告模板

```
=== 回测报告 ===
策略: momentum_v2        期间: 2018-01-01 ~ 2024-12-31
代码版本: a3f8c21         参数搜索次数: 7  ⚠️

[1] 防偏差检查
  ✅ 未来函数哨兵测试
  ✅ 生存者偏差（池含 23 支后退市股票）
  ✅ 涨跌停约束已生效（拒单 412 次）
  ✅ T+1 约束已生效
  ✅ 成本模型完整
  ⚠️  参数搜索 7 次，结果可信度下降

[2] 风险
  Max Drawdown      -14.2%    (基准 -32.1%)
  MDD 持续天数        87
  Calmar             1.31
  Sortino            1.45

[3] 收益
  CAGR              18.6%     (基准 5.2%)
  超额收益          13.4%
  Alpha              0.112     t=2.31
  Beta               0.87

[4] 稳定性
  分年度: 2018 -8.2% | 2019 +31% | ... | 2024 +12%
  盈利年份: 5/7
  最差月份: -9.1%

[5] 成本与容量
  年换手率          186%
  成本/总收益        23%      ⚠️ 偏高
  单笔占成交量       1.2%
  估计容量          ~2000 万

[6] 对照组
  Buy&Hold           5.2%
  等权池            8.1%
  最强单因子         11.3%
  L2 等权多因子      15.1%
  本策略            18.6%
  随机选股 95 分位   12.8%   ✅ 超出随机范围

[7] 撮合假设状态                    ★ 必须声明
  校准状态          未校准   ⚠️ 结论依赖未验证的撮合假设
  校准日期          —
  成交价 MAE        —
  涨跌停行为        未验证
  # 校准后示例:
  # 校准状态        已校准（2027-03-15, qmt_sim, 216 笔）
  # 成交价 MAE      0.31%
  # 涨跌停行为      一致
  # 未覆盖场景      停牌订单（无机会）
```

**第 7 节不可省略。** 未校准的回测结论必须标注"撮合假设未验证"，否则会让人误以为这些数字比实际更可靠。

## 10. 验收清单

Gate 4（P4）：

- [ ] 未来函数哨兵测试通过
- [ ] 股票池含历史退市股票
- [ ] 涨跌停约束生效且有拒单统计
- [ ] T+1 约束生效
- [ ] 成本模型含佣金/印花税/过户费/滑点
- [ ] 成交量约束生效
- [ ] 回测与实时共享 Stage 3-5 代码
- [ ] 全部对照组结果齐备（含蒙特卡洛随机选股）
- [ ] 分年度收益一致性可接受
- [ ] `param_search_count` 已记录且未失控
- [ ] 封存期未被提前使用
- [ ] Shadow Portfolio 已运行 ≥3 个月
- [ ] 5 个并行 shadow 组合均有记录
- [ ] Agent IC 已测出（无论正负）
- [ ] Confidence 校准已检验
- [ ] **回测报告含撮合假设状态声明（第 7 节）**

Gate 7b（A 股实盘前，见 [10-execution](10-execution.md)）：

- [ ] 撮合假设校准完成（≥200 笔订单，含涨跌停 ≥5 次）
- [ ] 校准偏差已记录成报告
- [ ] 若假设有错，`SimulatedBroker` 已修正
- [ ] 修正后全部历史回测已重跑，结论变化已评估
- [ ] 全部回测报告的第 7 节已更新为"已校准"
- [ ] 信号相关矩阵已计算
- [ ] 首份月度自我评估报告已生成
