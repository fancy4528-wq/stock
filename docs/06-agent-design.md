# 06 — Agent 设计

## 1. 设计原则

### 1.1 Agent 的能力边界

| 允许 | 禁止 |
|---|---|
| 通过 Tool 读数据 | 直接连数据库 / 写 SQL |
| 输出评分与论点 | 计算仓位 |
| 标注风险 | 判定风控是否通过 |
| 引用证据 | 引用未提供给它的数据 |
| 调用量化模型读结果 | 训练模型 / 修改模型参数 |
| 生成结构化 JSON | 输出自由格式文本作为最终产物 |

### 1.2 三条硬约束

**① 输出必须是结构化 Schema**

自由文本无法被下游消费、无法自动评估、无法回归测试。所有 Agent 输出必须通过 Pydantic 校验。

**② 每个判断必须挂 Evidence**

无证据的判断视为无效输出。Evidence 必须是可追溯的数据库引用（news_id、factor 值、财务行），不是 Agent 自己编的话。

**③ Tool 强制注入 as_of**

Agent 不能选择查询时点。`as_of` 由框架从 `AgentContext` 注入，Agent 的 tool schema 里根本没有这个参数。这样 Agent 无法（也无需）关心 PIT，架构上杜绝未来函数。

```python
# Agent 看到的 tool schema（无 as_of）
{
  "name": "get_prices",
  "parameters": {
    "symbols": {"type": "array"},
    "lookback_days": {"type": "integer"}
  }
}

# 框架实际执行（注入 as_of）
def _dispatch(tool_name, args, ctx: AgentContext):
    return TOOLS[tool_name](**args, as_of=ctx.as_of)   # ★ 框架注入
```

### 1.3 为什么工具受限比 prompt 约束更可靠

Prompt 里写"请不要臆测数据"，模型有时会遵守有时不会。但如果它只有 8 个工具、每个工具返回结构化数据，它能说的话就被限定在数据范围内。

**约束能力比约束意图更有效。**

## 2. Agent 清单

### 2.1 总览

| Agent | 数量 | 模型档 | 输入 | 输出 | 预算分项 |
|---|---|---|---|---|---|
| `NewsExtractor` | 批处理 | 小 | 新闻原文 | `EventExtraction` | `news_extraction` |
| `L2Triage` | 批处理 | 小 | 标题+摘要 | `L2Triage`（极简） | `monitoring` |
| `MacroAgent` | 1 | 中 | 宏观指标、政策 | `MacroView` | `daily_research` |
| `IndustryAgent` | Top N（默认5） | 中 | 行业数据、产业链 | `SectorView` | `daily_research` |
| `ThemeAgent` | Top M（默认3） | 中 | 概念板块、资金流 | `SectorView` | `daily_research` |
| `StockAgent` | Top K（默认30） | 中 | 个股全维度 | `StockView` | `daily_research` |
| `ChiefAgent` | 1 | 大 | 上述全部 | `MarketBrief` | `daily_research` |

注意：**没有 RiskAgent。** 草案中列了 Risk Agent，但风控是确定性规则，做成 Agent 是设计错误。风险的"解释"由 ChiefAgent 承担，风险的"判定"由 RiskEngine 承担。见 [ADR-0007](adr/0007-risk-not-agent.md)。

**也没有 MonitorAgent。** 盘中监控的 L3 深度分析直接复用 `StockAgent`（注入触发上下文聚焦分析），不新建 Agent。理由：`StockAgent` 已有完整工具集与 red flag 识别能力，新建意味着新 prompt、新测试、新评估，且能力重复。见 [15-monitoring-alerts](15-monitoring-alerts.md) 2.4 节。

### 2.2 NewsExtractor（新闻事件抽取）

不是对话式 Agent，是批处理抽取器。用小模型，量大。

```python
class EventExtraction(BaseModel):
    """从单条新闻抽取结构化事件。"""

    is_relevant: bool = Field(description="是否与股票投资相关")
    event_type: Literal[
        "earnings", "guidance", "policy", "regulation",
        "product", "contract", "mna", "management",
        "capacity", "price_change", "litigation",
        "shareholding", "rating", "macro", "other",
    ]
    summary: str = Field(max_length=200, description="一句话概括，不加评论")

    # 实体
    primary_symbols: list[str] = Field(
        default_factory=list, description="事件直接主体，必须是标准代码"
    )
    related_symbols: list[RelatedEntity] = Field(default_factory=list)
    industries: list[str] = Field(default_factory=list)
    themes: list[str] = Field(default_factory=list)

    # 影响判断
    direction: Literal["positive", "negative", "neutral", "unclear"]
    magnitude: Literal["minor", "moderate", "major"]
    horizon: Literal["immediate", "short", "medium", "long"]
    confidence: float = Field(ge=0, le=1)

    # 关键数字（若有）
    figures: list[Figure] = Field(default_factory=list)

class RelatedEntity(BaseModel):
    symbol: str
    relation: Literal["supplier", "customer", "competitor", "peer", "parent", "subsidiary"]
    direction: Literal["positive", "negative", "neutral"]

class Figure(BaseModel):
    """新闻中的关键数字，用于校验和量化。"""
    label: str          # '营收' | '中标金额' | '产能'
    value: float
    unit: str
    period: str | None
```

**关键设计：抽取而非评价。**

`summary` 要求"不加评论"。原因：如果让小模型写分析，会得到大量看似合理的废话。抽取结构化字段则可以校验（比如 `figures` 里的数字能与原文对照）。

**数字提取的准确性必须实测。** 中文金融文本里"营收 12.3 亿元，同比增长 15%"这类表述，模型可能提取错单位或混淆同比/环比。P1 阶段必须人工抽检 100 条，统计准确率，写入 `docs/extraction-eval.md`。

工具：无（纯文本输入输出）。

### 2.3 MacroAgent

```python
class MacroView(BaseModel):
    as_of: date

    # 市场状态判断
    regime: Literal["risk_on", "risk_off", "neutral", "transition"]
    regime_confidence: float = Field(ge=0, le=1)
    regime_drivers: list[str] = Field(
        min_length=1, description="判断依据，每条需有对应 evidence"
    )

    # 关键宏观维度
    liquidity: DimensionView          # 流动性
    growth: DimensionView             # 增长
    inflation: DimensionView          # 通胀
    policy: DimensionView             # 政策
    external: DimensionView           # 外部环境

    # 板块影响
    sector_impacts: list[SectorImpact] = Field(
        description="仅列出有明确判断的行业，不要求覆盖全部"
    )

    # 需关注的事件
    upcoming_events: list[UpcomingEvent]

    evidence: list[Evidence] = Field(min_length=1)

class DimensionView(BaseModel):
    direction: Literal["improving", "deteriorating", "stable", "unclear"]
    score: float = Field(ge=-1, le=1)
    note: str = Field(max_length=200)
    evidence_refs: list[str]

class SectorImpact(BaseModel):
    industry_code: str
    impact: float = Field(ge=-1, le=1)
    reason: str = Field(max_length=150)
    confidence: float = Field(ge=0, le=1)

class UpcomingEvent(BaseModel):
    expected_date: date | None
    description: str
    watch_reason: str
```

工具：

| 工具 | 说明 |
|---|---|
| `get_macro_series(series_ids, lookback_months)` | 宏观时间序列，PIT |
| `get_policy_news(lookback_days, limit)` | 政策类新闻/文件 |
| `get_market_breadth(lookback_days)` | 涨跌家数、成交额、换手率等 |
| `get_index_prices(index_codes, lookback_days)` | 主要指数走势 |
| `get_northbound_flow(lookback_days)` | 北向资金（A 股） |
| `search_knowledge(query, top_k=5)` | 文档检索（PIT 过滤，见 17-knowledge-base） |

### 2.4 IndustryAgent（行业板块）

```python
class SectorView(BaseModel):
    as_of: date
    sector_type: Literal["industry", "theme"]
    sector_code: str
    sector_name: str

    # 核心输出
    score: float = Field(ge=0, le=1, description="综合吸引力，0.5 为中性")
    confidence: float = Field(ge=0, le=1)
    horizon: Literal["1w", "1m", "3m", "6m"]

    thesis: str = Field(max_length=800, description="核心论点，需可被证据支撑")

    # 分维度评分（供 Fusion 使用）
    dimensions: SectorDimensions

    # 正反两面
    bull_points: list[ArgumentPoint] = Field(min_length=1)
    bear_points: list[ArgumentPoint] = Field(min_length=1, description="必须有，不允许空")
    key_uncertainties: list[str]

    # 候选个股
    candidates: list[StockCandidate] = Field(max_length=10)

    # 风险
    risks: list[RiskNote]

    evidence: list[Evidence] = Field(min_length=2)

class SectorDimensions(BaseModel):
    fundamental: DimScore      # 景气度、盈利趋势
    valuation: DimScore        # 估值分位
    momentum: DimScore         # 价格动量
    flow: DimScore             # 资金流向
    news_sentiment: DimScore   # 新闻面
    macro_fit: DimScore        # 与宏观环境契合度

class DimScore(BaseModel):
    score: float = Field(ge=0, le=1)
    note: str = Field(max_length=150)
    evidence_refs: list[str] = Field(default_factory=list)

class ArgumentPoint(BaseModel):
    point: str = Field(max_length=200)
    strength: Literal["weak", "moderate", "strong"]
    evidence_refs: list[str] = Field(min_length=1, description="不允许无证据的论点")

class StockCandidate(BaseModel):
    symbol: str
    name: str
    role: str = Field(description="在该板块中的定位，如'龙头'/'弹性标的'")
    preliminary_score: float = Field(ge=0, le=1)
    reason: str = Field(max_length=150)

class RiskNote(BaseModel):
    risk: str
    severity: Literal["low", "medium", "high"]
    probability: Literal["low", "medium", "high"]
    monitorable: bool = Field(description="是否有可观测的前兆指标")
```

**强制 `bear_points` 非空**是刻意设计。LLM 有明显的迎合倾向，被问"分析半导体板块"时容易只给看多理由。强制列出反面论点能显著改善输出质量。

工具：

| 工具 | 说明 |
|---|---|
| `get_sector_prices(sector_code, lookback_days)` | 板块指数走势 |
| `get_sector_constituents(sector_code)` | 成分股（PIT） |
| `get_sector_fundamentals(sector_code)` | 板块财务汇总（营收增速、毛利率等） |
| `get_sector_valuation(sector_code, lookback_years)` | 估值及历史分位 |
| `get_sector_flow(sector_code, lookback_days)` | 板块资金流 |
| `get_sector_news(sector_code, lookback_days, limit)` | 板块相关新闻/事件 |
| `get_supply_chain(sector_code)` | 上下游关系（结构化表，非 RAG） |
| `get_quant_signals(symbols)` | 量化模型输出 |
| `search_knowledge(query, top_k=5)` | 文档检索（PIT 过滤） |
| `compare_sectors(sector_codes, metrics)` | 横向对比 |

### 2.5 ThemeAgent（概念板块）

复用 `SectorView` schema，但 prompt 与工具侧重不同。

差异：

| 维度 | IndustryAgent | ThemeAgent |
|---|---|---|
| 核心问题 | 这个行业的景气度和估值如何 | 这个题材的资金关注度和持续性如何 |
| 重视 | 财务、产能、供需 | 资金流、涨停家数、龙虎榜、题材新鲜度 |
| 时间尺度 | 1-6 个月 | 1 周-1 个月 |
| 特有工具 | `get_supply_chain` | `get_theme_heat`、`get_limit_up_stats`、`get_dragon_tiger` |
| 特有风险 | 景气度反转 | 题材退潮、炒作破裂 |

`ThemeAgent` 的 prompt 必须明确要求评估**题材生命周期阶段**：

```python
class ThemeLifecycle(BaseModel):
    stage: Literal["emerging", "acceleration", "peak", "declining", "dormant"]
    days_since_activation: int
    evidence: str
```

理由：概念板块的核心风险是入场时机在"peak"之后。让 Agent 显式判断阶段，比让它给一个模糊的 score 更有用。

### 2.6 StockAgent

```python
class StockView(BaseModel):
    as_of: date
    symbol: str
    name: str

    score: float = Field(ge=0, le=1)
    confidence: float = Field(ge=0, le=1)
    horizon: Literal["1w", "1m", "3m", "6m"]

    thesis: str = Field(max_length=800)

    dimensions: StockDimensions
    bull_points: list[ArgumentPoint] = Field(min_length=1)
    bear_points: list[ArgumentPoint] = Field(min_length=1)

    # 关键观察点
    catalysts: list[Catalyst]
    red_flags: list[RedFlag]

    # 财务健康度（结构化，便于校验）
    financial_health: FinancialHealth

    risks: list[RiskNote]
    evidence: list[Evidence] = Field(min_length=3)

class StockDimensions(BaseModel):
    fundamental: DimScore
    valuation: DimScore
    growth: DimScore
    quality: DimScore          # 盈利质量、现金流
    momentum: DimScore
    news: DimScore
    sector_fit: DimScore       # 与所属板块的关系（龙头/跟随/落后）

class Catalyst(BaseModel):
    description: str
    expected_timing: str
    impact: Literal["low", "medium", "high"]
    probability: Literal["low", "medium", "high"]

class RedFlag(BaseModel):
    flag: str
    category: Literal[
        "accounting", "governance", "liquidity",
        "concentration", "regulatory", "competitive",
    ]
    severity: Literal["watch", "concern", "serious"]
    evidence_refs: list[str] = Field(min_length=1)

class FinancialHealth(BaseModel):
    """结构化财务判断，数值来自工具，不允许 Agent 自己算。"""
    revenue_trend: Literal["accelerating", "growing", "flat", "declining"]
    margin_trend: Literal["expanding", "stable", "compressing"]
    cash_conversion: Literal["strong", "adequate", "weak"]
    leverage: Literal["low", "moderate", "high", "concerning"]
    notes: str = Field(max_length=300)
```

`RedFlag` 是刻意加入的。系统的价值不只在于找到好股票，也在于**避开有问题的股票**。会计异常、大股东减持、商誉过高这类信号，LLM 读公告的能力恰好适合捕捉。

工具：

| 工具 | 说明 |
|---|---|
| `get_stock_prices(symbol, lookback_days)` | 价格走势 |
| `get_financials(symbol, periods)` | 财务报表（PIT，含修订标记） |
| `get_financial_indicators(symbol, periods)` | 财务指标 |
| `get_valuation(symbol, lookback_years)` | 估值及分位 |
| `get_stock_news(symbol, lookback_days, limit)` | 个股新闻/公告 |
| `get_announcements(symbol, lookback_days, types)` | 法定公告（可按类型筛选） |
| `get_peers(symbol, n)` | 同业可比公司 |
| `compare_peers(symbols, metrics)` | 同业对比 |
| `get_quant_signals(symbol)` | 量化预测 |
| `get_shareholding_changes(symbol, lookback_days)` | 股东增减持 |
| `get_money_flow(symbol, lookback_days)` | 资金流 |
| `search_knowledge(query, top_k)` | 知识库 |

### 2.7 ChiefAgent

```python
class MarketBrief(BaseModel):
    as_of: date
    run_id: str

    # 市场总览
    market_summary: str = Field(max_length=600)
    regime: Literal["risk_on", "risk_off", "neutral", "transition"]
    regime_note: str

    # 板块排序（核心输出）
    sector_ranking: list[RankedSector] = Field(min_length=3)

    # 个股排序
    stock_ranking: list[RankedStock]

    # 配置建议（★ 不是仓位，是方向性建议）
    allocation_stance: AllocationStance

    # 分歧与不确定性
    disagreements: list[Disagreement]
    key_uncertainties: list[str] = Field(min_length=1)

    # 观察清单
    watchlist: list[WatchItem]

    # 元信息
    inputs_summary: InputsSummary
    evidence: list[Evidence]

class RankedSector(BaseModel):
    rank: int
    sector_code: str
    sector_name: str
    sector_type: Literal["industry", "theme"]
    score: float
    confidence: float
    one_liner: str = Field(max_length=120)
    change_from_prev: Literal["up", "down", "unchanged", "new"]

class RankedStock(BaseModel):
    rank: int
    symbol: str
    name: str
    sector_code: str
    score: float
    confidence: float
    action_hint: Literal["strong_candidate", "candidate", "watch", "avoid"]
    one_liner: str = Field(max_length=120)

class AllocationStance(BaseModel):
    """方向性建议，不是具体权重。权重由 PortfolioEngine 算。"""
    equity_stance: Literal["aggressive", "moderate", "defensive", "cautious"]
    rationale: str = Field(max_length=300)
    preferred_sectors: list[str]
    avoid_sectors: list[str]

class Disagreement(BaseModel):
    """不同信号源的冲突。★ 这是重要输出，不要隐藏分歧。"""
    subject: str
    positions: list[str] = Field(description="各方观点")
    resolution: str = Field(description="如何处理这个分歧")

class InputsSummary(BaseModel):
    macro_view_id: int | None
    sector_view_ids: list[int]
    stock_view_ids: list[int]
    news_count: int
    events_count: int
    data_as_of: date
    data_quality_note: str | None = Field(
        description="若有数据缺失或降级，必须在此说明"
    )
```

`Disagreement` 字段是重要设计。当量化模型看多而新闻面看空时，系统不应该给出一个平滑掉分歧的分数，而应该把冲突显式呈现。这对使用者判断可信度至关重要。

`AllocationStance` 明确只给方向不给权重，防止 Agent 越界。

工具：ChiefAgent 主要消费上游 View，工具较少：

| 工具 | 说明 |
|---|---|
| `get_prev_brief(days_back)` | 历史 brief，用于判断变化 |
| `get_portfolio_state()` | 当前持仓（只读） |
| `get_market_breadth(lookback_days)` | 市场广度 |
| `get_decision_performance(lookback_days)` | 近期决策表现（自我校准） |

`get_decision_performance` 是有意加的：让 ChiefAgent 知道自己最近的判断准确率，有助于调整 confidence。但要注意这可能引入过度反应，需在 P2 实测效果。

## 3. 编排

### 3.1 执行 DAG

```
                    ┌──────────────────┐
                    │  Stage 4a 粗筛    │
                    │  (纯量化，无 LLM)  │
                    └────────┬─────────┘
                             │  Top 5 行业 + Top 3 概念
                             ▼
        ┌────────────────────────────────────────┐
        │            Stage 4b 并发                │
        │                                         │
        │  MacroAgent      IndustryAgent × 5      │
        │      │            ThemeAgent × 3        │
        │      │                  │               │
        └──────┼──────────────────┼───────────────┘
               │                  │
               │      候选股去重取 Top 30
               │                  ▼
               │        ┌─────────────────┐
               │        │ StockAgent × 30 │  (并发，限流)
               │        └────────┬────────┘
               │                 │
               └────────┬────────┘
                        ▼
               ┌─────────────────┐
               │   ChiefAgent    │
               └─────────────────┘
```

### 3.2 Orchestrator

```python
class Orchestrator:
    def __init__(
        self,
        llm: LLMClient,
        budget: TokenBudget,
        max_concurrency: int = 5,
    ): ...

    async def run_daily(self, as_of: date, market: str) -> MarketBrief:
        run_id = f"{as_of:%Y%m%d}-{market.lower()}-daily"
        ctx = AgentContext(as_of=as_of, market=market, run_id=run_id,
                           token_budget=self.budget)

        # Stage 4a: 纯量化粗筛
        shortlist = await self.screener.screen(as_of, market)

        # Stage 4b: 并发研究
        macro_task = self._run(MacroAgent(), ctx)
        sector_tasks = [
            self._run(IndustryAgent(code), ctx) for code in shortlist.industries
        ] + [
            self._run(ThemeAgent(code), ctx) for code in shortlist.themes
        ]

        macro, *sectors = await asyncio.gather(macro_task, *sector_tasks)

        # 候选股汇总去重
        candidates = self._merge_candidates(sectors, limit=30)

        # 并发个股研究（限流）
        ctx2 = ctx.model_copy(update={"upstream": {"macro": macro, "sectors": sectors}})
        stocks = await self._run_bounded(
            [StockAgent(s) for s in candidates], ctx2, limit=self.max_concurrency
        )

        # 汇总
        ctx3 = ctx2.model_copy(update={"upstream": {**ctx2.upstream, "stocks": stocks}})
        return await self._run(ChiefAgent(), ctx3)
```

### 3.3 失败处理

| 失败 | 处理 |
|---|---|
| 单个 SectorAgent 失败 | 记录，跳过该板块，继续（降级） |
| 单个 StockAgent 失败 | 记录，跳过该股，继续 |
| MacroAgent 失败 | 重试 1 次；仍失败则用中性 regime 继续，标记降级 |
| ChiefAgent 失败 | 重试 1 次；仍失败则中止，不产出 brief |
| Schema 校验失败 | 重试 1 次（附加错误提示）；仍失败则丢弃该输出 |
| Token 预算超限 | 立即中止，已完成部分落库，标记 `aborted` |
| Tool 调用失败 | 返回错误信息给 Agent，允许它调整策略 |

降级必须**显式记录在输出中**（`InputsSummary.data_quality_note`），不能静默降级。使用者需要知道今天的报告是不完整的。

### 3.4 Token 预算控制

```python
class TokenBudget(BaseModel):
    # 分项预算，互不挪用
    allocations: dict[str, float]          # 'daily_research'|'monitoring'|...
    spent: dict[str, float] = {}
    on_exceed: dict[str, str] = {}         # 各分项的降级动作

    def check_and_reserve(
        self, allocation: str, est_tokens_in: int, est_tokens_out: int, tier: str
    ) -> BudgetReservation:
        """★ 调用前估算并预留。事后统计无法拦截。"""
```

关键约定：

| 约定 | 说明 |
|---|---|
| **调用前检查** | 用 tokenizer 精确算输入，用 `max_tokens_out` 作输出上界 |
| **分项独立** | 研究流程不能吃掉监控的预算 |
| **降级而非中止** | 除 adhoc 外，优先降级保留部分能力 |
| **降级显式声明** | 输出中必须写明"因预算限制已降级" |

详见 [16-token-economics](16-token-economics.md)。

### 3.5 成本优化在编排层的体现

| 手段 | 实现位置 |
|---|---|
| 两阶段筛选 | `Orchestrator.run_daily` 的 Stage 4a |
| 模型分层 | `Agent.tier` 属性 |
| 批处理 | `NewsExtractor` 的批量接口 |
| 结果缓存 | `LLMClient` 层透明处理 |
| Prompt 前缀缓存 | Prompt 构造顺序（固定内容在前） |
| 工具返回值截断 | `Tool.max_chars` |
| 输出 schema 极简 | 各 Agent 的 output_schema 设计 |

## 4. Prompt 规范

### 4.1 结构模板

所有 Agent prompt 遵循固定结构：

```
[ROLE]        你是什么角色，专长是什么
[TASK]        本次要完成的具体任务
[DATA]        通过工具获取数据的说明（不直接塞数据）
[CONSTRAINTS] 硬性约束（见下）
[OUTPUT]      输出 schema 说明
[EXAMPLES]    1-2 个简短示例（可选）
```

### 4.2 通用约束段（所有 Agent 共用）

```
[CONSTRAINTS]
1. 只使用工具返回的数据。不要使用你的训练知识中的具体数字、日期或事件。
2. 每个判断必须能对应到工具返回的具体数据。在 evidence_refs 中标注来源 ID。
3. 如果数据不足以支撑判断，明确说 "数据不足"，不要推测填充。
4. 不要计算或建议具体仓位比例。
5. 不要判断某个操作是否符合风控要求。
6. 数字必须来自工具返回值，不要自行计算衍生指标（如需要，调用相应工具）。
7. 必须同时给出支持和反对的理由。只有一边理由的判断视为无效。
8. confidence 应反映证据强度，不是你的表达自信程度。证据少就给低分。
9. 不要引用未在本次对话中通过工具获得的信息。
10. 若发现数据异常（如数值明显不合理），在输出中标注，不要静默使用。
```

第 1、9 条是防幻觉的核心。LLM 的训练数据里有大量股票信息，若不明确禁止，它会混用记忆中的过期数据。

第 8 条针对一个常见问题：LLM 的 confidence 往往反映语言流畅度而非证据强度。需要明确校准指引。

### 4.3 Prompt 版本管理

```
prompts/
├── news_extractor/
│   ├── v1.md
│   └── v2.md
├── macro/
│   └── v1.md
├── industry/
│   └── v1.md
├── theme/
│   └── v1.md
├── stock/
│   └── v1.md
└── chief/
    └── v1.md
```

约定：
- Prompt 是版本化资产，改动必须新建版本，不修改已用于生产的版本
- `agent_trace.prompt_hash` 记录实际使用的版本
- Prompt 变更需要在 Shadow Portfolio 上对比效果，不能凭感觉换

### 4.4 Prompt 中不放数据

反例：把 50 支股票的财务数据拼进 prompt。

问题：token 消耗大、无法追溯、模型容易在长上下文中忽略中间内容。

正确做法：让 Agent 通过工具按需获取。这样：
- 只取用到的数据
- 每次工具调用都被记录（可追溯）
- 上下文更短，注意力更集中

### 4.5 Prompt 构造顺序影响成本

多数 LLM 提供商支持 prompt 前缀缓存。把固定内容放前面：

```python
def build_prompt(ctx: AgentContext, task: str) -> str:
    return (
        SYSTEM_INSTRUCTIONS      # 固定，全天不变       → 可缓存
        + COMMON_CONSTRAINTS     # 固定（4.2 节的约束）  → 可缓存
        + TOOL_DESCRIPTIONS      # 固定                 → 可缓存
        + ctx.market_context()   # 每日变一次           → 可缓存
        + f"\n任务：{task}"       # 每次变              → 不缓存
    )
```

具体折扣与最小缓存长度因提供商而异，需在 P2 实测并记入 `cost-log.md`。

### 4.6 输出 Schema 的成本考量

**输出 token 通常比输入贵，且容易被忽略。**

| 场景 | Schema 设计 |
|---|---|
| 输出给人看（thesis、L3 分析） | 完整字段名 + 允许 reasoning |
| 输出仅给程序消费（L2 分诊、分类） | 缩写字段名 + **无 reasoning 字段** |
| 批处理场景 | 极简缩写，程序侧映射回完整字段 |

```python
# 给人看：完整
class SectorView(BaseModel):
    thesis: str
    bull_points: list[ArgumentPoint]      # 含理由

# 给程序：极简（L2 分诊）
class L2Triage(BaseModel):
    rel: bool                             # is_relevant
    sym: list[str] = []                   # affected_symbols
    dir: str = ""                          # direction
    deep: bool = False                     # needs_deep_analysis
    # ★ 无 reasoning 字段。判断错了由 L3 纠正，不值得花 token 写理由
```

所有 Agent 必须设置 `max_tokens_out`（有测试保障）。

## 5. 工具实现规范

### 5.1 工具契约

```python
class Tool(BaseModel):
    name: str
    description: str                # 给 LLM 看，需清晰说明用途和返回内容
    params_schema: type[BaseModel]  # 参数校验
    handler: Callable

    # 框架自动注入，不在 params_schema 中暴露
    inject_as_of: bool = True

    # 成本控制
    max_rows: int = 100             # 返回行数上限
    max_chars: int = 8000           # 返回字符数上限
```

### 5.2 返回值规范

| 要求 | 说明 |
|---|---|
| 结构化 | 返回 JSON，不返回自然语言描述 |
| 带 ID | 每行数据带可引用的 ID（供 evidence 使用） |
| 截断标记 | 若结果被截断，明确标注 `truncated: true` 和总数 |
| 空结果明确 | 无数据返回 `{"data": [], "note": "no data found"}`，不返回错误 |
| 单位标注 | 数值字段带单位说明 |
| 不预处理 | 不替 Agent 做判断或汇总（除非工具本身就是汇总工具） |

```python
class ToolResult(BaseModel):
    data: list[dict]
    total_count: int
    truncated: bool
    as_of: date
    units: dict[str, str] = {}
    note: str | None = None
```

### 5.3 工具的 description 写法

Description 直接影响 Agent 是否会正确使用工具。

```python
# ❌ 太简略
description="获取股票价格"

# ✅ 说明清楚
description=(
    "获取指定股票的历史日线数据（前复权）。"
    "返回字段：date, open, high, low, close, volume, amount, "
    "pct_change(涨跌幅,小数), is_limit_up(是否涨停), is_suspended(是否停牌)。"
    "lookback_days 最大 250。"
    "注意：涨停日通常难以买入，停牌日无法交易。"
)
```

最后一句很重要：把领域约束写进 description，Agent 才会在分析中考虑这些因素。

## 6. Agent 输出校验

### 6.1 分层校验

```python
async def validate_agent_output(
    output: BaseModel, ctx: AgentContext, trace: AgentTrace
) -> ValidationResult:
    checks = [
        # L1 Schema（Pydantic 已做）
        # L2 证据存在性
        check_evidence_not_empty(output),
        check_evidence_ids_exist(output),        # 引用的 ID 真实存在于库中
        check_evidence_pit(output, ctx.as_of),   # ★ 证据不来自未来
        # L3 内容一致性
        check_scores_in_range(output),
        check_bear_points_present(output),
        check_symbols_valid(output, ctx),        # 提及的代码存在且在池内
        # L4 数字可信性
        check_figures_traceable(output, trace),  # 输出的数字能在工具返回中找到
    ]
    ...
```

### 6.2 `check_figures_traceable` 详解

这是防幻觉最有效的检查：从 Agent 输出的文本中提取所有数字，检查它们是否出现在本次的工具返回值中。

```python
def check_figures_traceable(output: BaseModel, trace: AgentTrace) -> CheckResult:
    """Agent 输出中的数字必须能在工具返回中找到（允许合理的四舍五入）。"""
    output_numbers = extract_numbers(output.model_dump_json())
    tool_numbers = set()
    for call in trace.tool_calls:
        tool_numbers |= extract_numbers(json.dumps(call.result))

    unmatched = [
        n for n in output_numbers
        if not any(math.isclose(n, t, rel_tol=0.02) for t in tool_numbers)
    ]
    if unmatched:
        return CheckResult(
            passed=False,
            level="WARN",
            detail=f"Untraceable figures: {unmatched}",
        )
```

不设为 FATAL 是因为会有合理的派生计算（如 Agent 算了一个比率）。但持续的 untraceable 数字是幻觉信号，需要监控其比率。

### 6.3 幻觉率监控

```sql
-- 每周统计各 Agent 的幻觉指标
SELECT
    agent_name,
    count(*) AS total,
    avg((output->>'untraceable_figure_count')::int) AS avg_untraceable,
    sum(CASE WHEN NOT schema_valid THEN 1 ELSE 0 END)::float / count(*) AS schema_fail_rate,
    avg(retry_count) AS avg_retries
FROM agent_trace
WHERE created_at > now() - interval '7 days'
GROUP BY agent_name;
```

Gate 2 的验收标准之一：`schema_fail_rate < 5%`，`avg_untraceable < 1`。

## 7. 知识注入边界

完整设计见 [17-knowledge-base](17-knowledge-base.md)，此处只列 Agent 侧需遵守的约束。

### 7.1 不给 Agent 灌输通用金融知识

| 不注入 | 理由 |
|---|---|
| PE/ROE/RSI 等概念定义 | 预训练已可靠掌握，花 token 换零增益 |
| 投资流派与方法论 | **制造系统性偏见**，破坏 Agent 与量化信号的独立性 |
| 教科书策略 | 已被套利掉；只会让 Agent 更自信地给出无 alpha 结论 |
| A 股制度规则全文 | 精确性要求高，RAG 不可靠 → 配置化 |

第二条最关键。若知识库含大量价值投资材料，`StockAgent` 会倾向在所有股票上找低估理由——该结论来自被灌输的先验，不来自当期数据。而 Fusion 层假设 Agent 观点与量化信号独立。见 [ADR-0011](adr/0011-no-general-finance-kb.md)。

这与"风控不做成 Agent"（[ADR-0007](adr/0007-risk-not-agent.md)）同源：**该由确定性逻辑决定的事，不交给 LLM 的先验。**

### 7.2 四条注入途径

| 途径 | 成本 | 用于 |
|---|---|---|
| B. 配置/代码 | **零** | 涨跌停幅度、T+1、风控阈值 |
| C. 工具按需取 | 低 | 财务数字、成分股、上下游关系 |
| D. RAG 检索 | 中 | 年报 MD&A、风险因素、公告全文 |
| A. Prompt 常驻 | 高 | 本项目口径（≤500 token） |

**规则参与计算，不参与推理。** Agent 不需要"知道"涨跌停是 10%，它只需看到 `is_limit_up = true` 这个算好的字段。

### 7.3 结构化优先

**能结构化的不放向量库。**

| 数据 | 存法 |
|---|---|
| 成分股、财务数字、行业归属 | 关系表 + 工具精确查询 |
| 上下游关系 | 关系表（`supply_chain`） |
| 年报 MD&A、风险因素、公告全文 | 向量库 |

向量检索是模糊匹配，对精确事实不可靠。让 Agent 靠向量检索找"贵州茅台 2024 年营收"是错误设计。

```sql
-- 产业链用关系表，不用向量
CREATE TABLE supply_chain (
    upstream_id     BIGINT REFERENCES industry(industry_id),
    downstream_id   BIGINT REFERENCES industry(industry_id),
    relation_type   TEXT NOT NULL,      -- 'material'|'component'|'service'
    strength        NUMERIC(4,3),
    note            TEXT,
    source          TEXT NOT NULL,      -- 来源可追溯
    updated_at      TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (upstream_id, downstream_id, relation_type)
);
```

### 7.4 RAG 的 PIT 要求

检索必须双向时效过滤：

```python
def search_knowledge(query: str, top_k: int = 5, *, as_of: date) -> ToolResult:
    emb = embed(query)                       # 本地 bge-m3，零 API 成本
    rows = conn.execute(
        "SELECT * FROM search_chunks_as_of(%s, %s, %s)",
        (emb, eod(as_of), top_k),
    )
```

```sql
WHERE visible_at <= :as_of                            -- 不读未来文档
  AND (expires_at IS NULL OR expires_at > :as_of)     -- 不读未生效规则
```

两个隐蔽陷阱：

| 陷阱 | 说明 |
|---|---|
| 年报 `visible_at` | 应为**披露日**而非报告期末。2025 年报 2026-04 才可见 |
| 知识过期 | 2024 年监管规则不适用于 2018 年案例 —— 靠 `expires_at` 防 |

这类错误很隐蔽，因为向量检索的结果不直观。靠未来函数哨兵测试兜底。

### 7.5 自有判断历史（P4）

真正有价值的知识资产是**自己过往的判断与结果**——LLM 不可能知道，通用知识库也不会有。

```python
def search_own_history(
    security_id: int | None,
    query: str,
    as_of: datetime,              # ★ 必填，无默认值
    top_k: int = 3,               # ★ 默认小
    only_wrong: bool = False,
) -> list[HistoricalThesis]:
    """检索自己过往对该标的的判断与结果。来源 v_thesis_with_outcome。"""
```

P4 才做，因为需要足够的历史 thesis + 结果回填 + 归因分析。

**用途边界**：

| 可以 | 不可以 |
|---|---|
| 提示"上次的关键假设是否仍成立" | 直接沿用上次结论 |
| 提示"该公司指引历史偏乐观" | 替代当期数据分析 |

风险是**锚定效应**：看到"三个月前我看多"可能倾向维持看多。Prompt 需明确约束，并在 P4 做 A/B 测试——若只提升一致性未提升准确率，说明是锚定而非学习，应关闭。

## 8. Agent 评估

Agent 输出好不好，不能靠读起来顺不顺。需要量化评估，详见 [08-backtest-eval](08-backtest-eval.md) 第 7 节。核心指标：

| 指标 | 含义 | 目标 |
|---|---|---|
| Schema 通过率 | 结构化输出成功率 | > 95% |
| Evidence 覆盖率 | 有证据的判断占比 | 100% |
| Untraceable 数字率 | 无法追溯的数字比例 | < 5% |
| PIT 违规数 | 引用未来证据的次数 | 0 |
| 输出 IC | score 与后续实际收益的秩相关 | > 0（这是最难达到的） |
| Confidence 校准 | 高 confidence 组的准确率是否更高 | 单调正相关 |
| 板块排序 IC | 板块 ranking 与后续板块收益的相关性 | > 0 |

**最后三项是真正的考验。** 前四项是工程质量，后三项才回答"这个 Agent 有没有用"。

要做好心理准备：**Agent 层的输出 IC 可能接近 0**。这不代表项目失败——Agent 提供的解释性和红旗识别本身有价值。但必须诚实地测出来，而不是假定它有效。
