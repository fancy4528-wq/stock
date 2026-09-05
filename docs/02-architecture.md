# 02 — 系统架构

## 1. 分层总览

```
┌─────────────────────────────────────────────────────────────────┐
│  L6  Presentation      CLI / Markdown 日报 / Notifier /          │
│                        (后期) Web UI                             │
├─────────────────────────────────────────────────────────────────┤
│  L5  Evaluation        Decision Journal / Shadow Portfolio /     │
│                        归因分析 / Agent 自评 / Alert 质量评估     │
├─────────────────────────────────────────────────────────────────┤
│  L4.5 Monitor          Trigger 引擎 / 三级漏斗 / 抑制策略 /       │
│                        监控预算  ★ 不含新决策逻辑，复用 L1-L3     │
├─────────────────────────────────────────────────────────────────┤
│  L4  Execution         Order Manager / BrokerAdapter / 对账      │
├─────────────────────────────────────────────────────────────────┤
│  L3  Decision          Signal Fusion → Portfolio → Risk Engine   │
│                        ★ Risk 拥有否决权，不可被 LLM 覆盖         │
├─────────────────────────────────────────────────────────────────┤
│  L2  Intelligence      Agent 层（Chief/Macro/Industry/Theme/     │
│                        Stock）+ Quant Engine（因子/模型/预测）    │
├─────────────────────────────────────────────────────────────────┤
│  L1  Data Access       ★ as_of(t) PIT 接口 / Agent Tools /       │
│                        Repository 层                             │
├─────────────────────────────────────────────────────────────────┤
│  L0  Data Foundation   Collector（含实时快照）/ Normalizer /      │
│                        Validator / PostgreSQL / Redis / Parquet   │
└─────────────────────────────────────────────────────────────────┘

     横切关注：Config / Logging / Tracing / TokenBudget（分项预算）
```

### 1.1 依赖方向

**严格单向：上层依赖下层，下层不知道上层存在。**

```
L6 → L5 → L4.5 → L4 → L3 → L2 → L1 → L0
```

违反此规则的典型错误：
- ❌ Collector 里调用 Agent 判断"这条新闻重不重要"
- ❌ Risk Engine 里调 LLM 问"这次能不能放宽"
- ❌ 因子计算函数里直接连数据库
- ❌ Monitor 层自己实现风控判定（应复用 RiskEngine）
- ❌ Agent 或 Decision 层依赖 Monitor

### 1.2 三条硬边界

```
       ┌──────────────────────────────────┐
       │  边界 A：LLM 与数据之间           │
       │  LLM 只能通过 Tool 访问数据       │
       │  Tool 强制注入 as_of(t)          │
       └──────────────────────────────────┘

       ┌──────────────────────────────────┐
       │  边界 B：LLM 与执行之间           │
       │  LLM 只能产出 Proposal            │
       │  Proposal 必须过 Risk 才能到 Broker│
       └──────────────────────────────────┘

       ┌──────────────────────────────────┐
       │  边界 C：监控的规则层与 LLM 之间   │
       │  L1 规则层零 LLM 成本             │
       │  预算耗尽时 L1 仍完整工作          │
       └──────────────────────────────────┘
```

边界 C 保证：即使 LLM 预算用完，止损、跌停、停牌、组合回撤等关键监控依然有效。

## 2. 模块清单与职责

### L0 — Data Foundation

| 模块 | 职责 | 明确不做 |
|---|---|---|
| `Collector` | 从外部源拉原始数据，原样归档为 Parquet | 不做清洗、不做判断 |
| `Normalizer` | 原始数据 → 标准 schema，单位统一，代码统一 | 不做业务计算 |
| `Validator` | 质量校验，异常标记与告警 | 不自动修数据（除明确规则） |
| `Loader` | 写入 PostgreSQL，处理 PIT 版本 | 不覆盖历史版本 |

**关键设计：原始数据必须归档。**

```
data/raw/{source}/{dataset}/{date}/{timestamp}.parquet
```

理由：数据源接口会变、会出错、会下线。归档原始响应意味着任何时候都能重放 normalize 逻辑，而不需要重新拉取（很多历史数据拉不回来）。

### L1 — Data Access

| 模块 | 职责 |
|---|---|
| `PITRepository` | 唯一的历史数据出口，所有方法强制 `as_of` 参数 |
| `UniverseService` | 股票池的时点快照查询 |
| `AgentTools` | 包装 Repository 为 LLM function calling 契约 |
| `FeatureStore` | 因子值读写，Parquet + DuckDB 加速 |

**这一层是防止未来函数的唯一防线。** 设计要点见 [03-data-model](03-data-model.md) 第 4 节。

### L2 — Intelligence

分两个互不依赖的子系统。

**Agent 子系统**

| Agent | 输入 | 输出 |
|---|---|---|
| `MacroAgent` | 宏观指标、政策新闻 | `MacroView`（regime + 板块影响） |
| `IndustryAgent` | 申万行业数据、产业链新闻 | `SectorView`（评分 + thesis） |
| `ThemeAgent` | 概念板块、资金流、题材热度 | `SectorView` |
| `StockAgent` | 个股财务、新闻、公告 | `StockView` |
| `ChiefAgent` | 上述所有 View | `MarketBrief`（排序 + 决策上下文） |

**Quant 子系统**

| 模块 | 职责 |
|---|---|
| `FactorLibrary` | 因子计算，纯函数，输入 DataFrame 输出 DataFrame |
| `ModelRegistry` | 模型训练/加载/版本管理 |
| `Predictor` | 输出概率预测（1D/5D/20D prob_up + expected return） |

**两个子系统的关系**：Agent 可以通过 `run_quant_model()` 工具读取 Quant 的输出，但 Quant 完全不依赖 Agent。这保证 Quant 部分可以独立回测。

### L3 — Decision

| 模块 | 职责 | 是否含 LLM |
|---|---|---|
| `SignalFusion` | 多信号 → 单一分数 | ❌ 纯计算 |
| `PortfolioEngine` | 分数 → 目标权重 | ❌ 纯计算 |
| `RiskEngine` | 目标权重 → APPROVE/MODIFY/REJECT | ❌ 纯规则 |

**这一层完全没有 LLM。** 输入是结构化的 score，输出是确定性的权重。相同输入必须得到相同输出（可测试、可回测、可审计）。

### L4 — Execution

| 模块 | 职责 |
|---|---|
| `OrderManager` | 目标权重 → 订单列表，状态机管理 |
| `BrokerAdapter` | 券商抽象接口 |
| `Reconciler` | 本地仓位 vs 券商仓位对账 |

### L4.5 — Monitor（盘中监控）

| 模块 | 职责 | 明确不做 |
|---|---|---|
| `TriggerRegistry` | 触发器注册与执行 | 不做投资判断 |
| `L1Filter` | 零成本规则过滤（实体匹配、关键词） | 不调 LLM |
| `L2Triage` | 小模型分诊（相关性、方向） | 不做深度分析 |
| `L3Analysis` | 复用 `StockAgent` 做深度分析 | 不新建 Agent |
| `SuppressionPolicy` | 冷却期、每日上限、静默时段 | — |
| `MonitorBudget` | 监控专用预算与降级 | — |

**关键设计**：Monitor 层自己不做判断，只负责"什么时候该看一眼"。判断复用既有的 `StockAgent`、`RiskEngine`、`PortfolioEngine`。

详见 [15-monitoring-alerts](15-monitoring-alerts.md)。

### L5 — Evaluation

| 模块 | 职责 |
|---|---|
| `DecisionJournal` | 决策全量落库，append-only |
| `ShadowPortfolio` | 模拟持仓与 PnL 跟踪 |
| `Attribution` | 收益归因到信号/板块/个股 |
| `AgentEvaluator` | Agent 输出的 IC 检验与分条件准确率 |
| `AlertEvaluator` | 推送质量评估：各 trigger 的有用率与单位成本 |
| `CostTracker` | LLM 成本归因与单位价值指标 |

## 3. 核心数据流

### 3.1 每日主流程（时序）

```
时间轴（A 股，北京时间）

15:00  收盘
  │
15:30  ┌─ Stage 1: 数据采集 ────────────────────────┐
       │  行情 Collector    → 日线 OHLCV            │
       │  资金流 Collector  → 主力净流入等          │
       │  公告 Collector    → 交易所公告            │
       │  新闻 Collector    → 财联社/东财（全天增量）│
       │  财务 Collector    → 若有新财报            │
       └────────────────┬───────────────────────────┘
                        ▼
16:00  ┌─ Stage 2: 数据处理 ───────────────────────┐
       │  Normalize → Validate → Load              │
       │  ★ Gate: 完整性校验不通过则中止后续       │
       └────────────────┬──────────────────────────┘
                        ▼
16:30  ┌─ Stage 3: 因子与预测 ─────────────────────┐
       │  FactorLibrary.compute(date)              │
       │  Predictor.predict(date) → prob_up 等     │
       └────────────────┬──────────────────────────┘
                        ▼
17:00  ┌─ Stage 4: Agent 研究（两阶段） ───────────┐
       │                                            │
       │  4a  粗筛（小模型 + 量化）                 │
       │      全市场 → 板块评分 → Top N 板块        │
       │                                            │
       │  4b  精研（中/大模型，并发）               │
       │      MacroAgent ─┐                        │
       │      IndustryAgent × N ─┤ 并发             │
       │      ThemeAgent × M ─┘                     │
       │            ▼                               │
       │      StockAgent × K（Top 板块内的候选股）   │
       │            ▼                               │
       │      ChiefAgent 汇总 → MarketBrief         │
       └────────────────┬──────────────────────────┘
                        ▼
18:00  ┌─ Stage 5: 决策（无 LLM） ─────────────────┐
       │  SignalFusion → 综合分数                   │
       │  PortfolioEngine                           │
       │    ①-⑥ 从零构建 → 冷启动组合  ★ P5        │
       │    ⑦ 换手约束（引入现有持仓）→ 调仓目标    │
       │  RiskEngine → 校验/修正/拒绝               │
       └────────────────┬──────────────────────────┘
                        ▼
18:15  ┌─ Stage 6: 输出与记录 ─────────────────────┐
       │  Markdown 日报生成                         │
       │  DecisionJournal 落库                      │
       │  ShadowPortfolio 更新                      │
       │  A 股阶段：人工执行清单                    │
       │    · 有持仓 → 调仓清单（⑦ 的输出）         │
       │    · 空仓   → 建仓推荐（①-⑥ + 分批计划）  │
       │  美股阶段：Order Proposal → Execution      │
       └───────────────────────────────────────────┘
```

**①-⑥ 与 ⑦ 的分界是冷启动能力的来源**：前六步不参考现有持仓，输出本身就是"如果从零开始会持有什么"。所以冷启动无需新 Agent、新模型。见 [09-portfolio-risk](09-portfolio-risk.md) 第 8 节。

### 3.2 盘中监控流程（新增）

```
时间轴（A 股，北京时间）

09:25  ┌─ 开盘前 ────────────────────────────────────┐
       │  持仓时效性检查（超 5 日未更新则提醒）        │
       │  隔夜公告扫描（L1 规则）                     │
       │  昨日 high 级告警补发                        │
       └────────────────┬────────────────────────────┘
                        ▼
09:30 ─┬───────────── 交易时段循环 ─────────────────┐
       │                                             │
       │  每 3 分钟：行情快照（仅持仓+关注列表）      │
       │      ↓                                      │
       │  A 类价格触发器（零 LLM）                    │
       │      · 止损/止盈线                           │
       │      · 涨跌停/停牌                           │
       │      · 放量异动                              │
       │      · 技术位破位                            │
       │                                             │
       │  每 5 分钟：风控检查（零 LLM）                │
       │      · 行业集中度                            │
       │      · 组合回撤/当日亏损                     │
       │      · 单股权重/现金比例                     │
       │                                             │
       │  每 5 分钟：公告扫描                          │
       │      ↓ L1 按公告类型判断                     │
       │      critical 类型 ──▶ 升级 L3               │
       │      high 类型 ─────▶ 升级 L2                │
       │                                             │
       │  每 5 分钟：新闻批处理                        │
       │      ↓ L1 实体匹配 + 关键词（零 LLM）        │
       │      通过率 ~1%                              │
       │      ↓ L2 小模型批量分诊（10 条/次）         │
       │      升级率 ~20%                             │
       │      ↓ L3 复用 StockAgent 深度分析           │
       │      每日 ≤10 次                             │
       │                                             │
       │  触发后：抑制策略过滤                         │
       │      · 冷却期检查                            │
       │      · 单标的/全局每日上限                   │
       │      · 静默时段（critical 除外）             │
       │      ↓                                      │
       │  Notifier 推送 → alert 表落库                │
       │                                             │
15:00 ─┴─────────────────────────────────────────────┘
                        ▼
15:30  转入盘后批处理流程（见 3.1）
```

关键设计要点：

| 要点 | 说明 |
|---|---|
| 只监控持仓 + 关注列表 | 不做全市场盘中扫描（成本不允许） |
| A/B 类触发器完全零 LLM | 预算耗尽时最关键的监控仍工作 |
| medium 级告警汇总推送 | 11:30 / 14:45 两次，避免碎片打扰 |
| 14:45 是刻意时点 | 15:00 收盘，留 15 分钟给用户操作 |
| L3 复用 StockAgent | 不新建 Agent，避免能力重复与评估负担 |

### 3.3 Stage 4 的两阶段筛选（成本控制核心）

```
全市场 ~5000 支 / 31 个申万一级行业 / ~300 概念板块
        │
        │  Stage 4a — 量化粗筛（零 LLM 成本）
        │  · 板块动量、资金流、估值分位
        │  · 剔除 ST/停牌/流动性不足
        ▼
Top 5 行业 + Top 3 概念
        │
        │  Stage 4b — LLM 精研
        │  · 每个板块 1 次中模型调用
        │  · 每个板块取 Top 5 个股 → StockAgent
        ▼
~8 板块 + ~30 个股
        │
        │  ChiefAgent 汇总（1 次大模型调用）
        ▼
MarketBrief
```

成本估算（每日，盘后流程）：

| 调用 | 次数 | 模型档 | 预算分项 |
|---|---|---|---|
| 新闻分类/去重 | ~200（批处理后 ~20 次调用） | 小 | `news_extraction` |
| MacroAgent | 1 | 中 | `daily_research` |
| IndustryAgent | 5 | 中 | `daily_research` |
| ThemeAgent | 3 | 中 | `daily_research` |
| StockAgent | ~30 | 中 | `daily_research` |
| ChiefAgent | 1 | 大 | `daily_research` |

盘中监控成本（三级漏斗后）：

| 层 | 日均处理量 | 日均调用 | 模型档 |
|---|---|---|---|
| L1 规则 | ~2000 条 | **0** | — |
| L2 分诊 | ~50 条 | ~5 次（批） | 小 |
| L3 分析 | ~6 次 | 6 次 | 大 |

必须在 P1/P2 实测真实成本并写入 `docs/cost-log.md`。

**预算超限时的降级顺序**（分项独立，互不挪用）：
1. `daily_research` 超限 → 减少 StockAgent 数量（30 → 10 → 0）
2. `monitoring` 超限 → 降为 L1 纯规则（关键监控仍有效）
3. `news_extraction` 超限 → 只抽取持仓相关新闻

详见 [16-token-economics](16-token-economics.md)。

### 3.3 回测流程（与实时流程共享代码）

```
for t in trading_days:
    # ★ 关键：所有取数走 as_of(t)
    data = repo.get_panel(as_of=t)

    factors = FactorLibrary.compute(data)          # 与实时同一份代码
    preds   = model.predict(factors)               # 使用 t 之前训练的模型版本
    scores  = SignalFusion.fuse(preds, ...)        # 与实时同一份代码
    target  = PortfolioEngine.build(scores)        # 与实时同一份代码
    result  = RiskEngine.check(target, state)      # 与实时同一份代码
    fills   = SimulatedBroker.execute(result, t)   # 含 T+1/涨跌停/停牌/成本
    state   = state.apply(fills)
```

**设计要求：Stage 3-5 的代码在回测和实时中必须是同一份。** 任何"回测专用逻辑"都是 bug 温床。区别只在于数据来源（历史 vs 当日）和 Broker 实现（Simulated vs 真实）。

Agent 层在回测中的处理是个难题（无法重放历史 LLM 调用，且成本高）。方案见 [08-backtest-eval](08-backtest-eval.md) 第 6 节：Agent 信号采用**前向记录**而非回测，这也是 Shadow Portfolio 必须尽早启动的原因。

## 4. 关键接口契约

### 4.1 PIT 数据接口

```python
from datetime import date
from typing import Protocol
import polars as pl

class PITRepository(Protocol):
    """所有历史数据查询的唯一入口。as_of 参数强制且无默认值。"""

    def get_prices(
        self,
        symbols: list[str],
        start: date,
        end: date,
        *,
        as_of: date,          # 强制关键字参数，无默认值
        adjust: str = "qfq",  # 前复权
    ) -> pl.DataFrame: ...

    def get_financials(
        self,
        symbols: list[str],
        *,
        as_of: date,
        periods: int = 8,
    ) -> pl.DataFrame:
        """只返回 announced_at <= as_of 的最新修订版本。"""
        ...

    def get_universe(self, *, as_of: date, name: str) -> list[str]:
        """时点股票池快照，含当时的成分，不含之后才纳入的。"""
        ...

    def get_industry(self, symbols: list[str], *, as_of: date) -> pl.DataFrame:
        """时点行业归属。行业分类会调整，必须按时点查。"""
        ...

    def get_news(
        self,
        *,
        as_of: date,
        lookback_days: int = 7,
        symbols: list[str] | None = None,
        sectors: list[str] | None = None,
    ) -> pl.DataFrame: ...
```

强制约定：
- `as_of` 是 keyword-only 且无默认值 → 忘记传会直接 TypeError
- 返回的 DataFrame 必须带 `data_version` 列用于追溯
- 禁止在 Repository 之外写 SQL

### 4.2 Agent 契约

```python
from pydantic import BaseModel, Field
from typing import Protocol

class AgentContext(BaseModel):
    """Agent 运行上下文。as_of 贯穿全链路。"""
    as_of: date
    market: str                    # "CN" | "US"
    run_id: str                    # 用于 trace 关联
    token_budget: TokenBudget
    upstream: dict[str, BaseModel] = {}   # 上游 Agent 输出

class Evidence(BaseModel):
    """证据引用。所有判断必须挂 evidence。"""
    kind: str                      # "news" | "financial" | "factor" | "price"
    ref_id: str                    # 数据库主键或新闻 ID
    excerpt: str | None = None     # 原文摘录（限长）
    as_of: date                    # 该证据的可见时点

class Agent[TOut: BaseModel](Protocol):
    name: str
    tier: str                      # "small" | "medium" | "large"
    tools: list[Tool]
    output_schema: type[TOut]

    async def run(self, ctx: AgentContext) -> TOut: ...
```

强制约定：
- 输出必须是 Pydantic 模型，不接受自由文本
- 所有 score 字段带 `confidence`
- 所有判断字段关联 `list[Evidence]`，空 evidence 视为无效输出
- 每次调用写入 `agent_trace` 表（prompt hash、token 数、耗时、工具调用序列）

### 4.3 Risk Engine 契约

```python
from enum import Enum

class RiskDecision(str, Enum):
    APPROVE = "approve"
    MODIFY  = "modify"
    REJECT  = "reject"

class RiskResult(BaseModel):
    decision: RiskDecision
    original_target: dict[str, float]      # symbol -> weight
    final_target: dict[str, float]
    violations: list[RiskViolation]        # 触发的规则
    audit_id: str

class RiskEngine(Protocol):
    def check(
        self,
        target: dict[str, float],
        state: PortfolioState,
        market_config: MarketConfig,
        *,
        as_of: date,
    ) -> RiskResult: ...
```

强制约定：
- **纯函数**，相同输入必得相同输出
- 无网络调用、无 LLM 调用、无随机数
- 所有 violation 必须记录，即使最终 APPROVE
- 无 `force`、`override`、`bypass` 之类的参数（架构上禁止绕过）

### 4.4 Broker 契约

见 [10-execution](10-execution.md)。

## 5. 配置与环境

### 5.1 配置分层

```
config/
├── base.yaml              # 全局默认
├── markets/
│   ├── cn.yaml            # A 股规则
│   └── us.yaml            # 美股规则
├── llm.yaml               # 模型分层与预算
├── risk/
│   ├── cn.yaml            # A 股风控参数
│   └── us.yaml
├── universe/
│   ├── mvp_cn.yaml        # MVP 股票池定义
│   └── ...
└── envs/
    ├── dev.yaml
    └── prod.yaml
```

加载顺序：`base` → `market` → `env` → 环境变量覆盖。

### 5.2 禁止硬编码清单

以下内容出现在代码里即视为 bug：

| 类别 | 必须来自配置 |
|---|---|
| 涨跌停幅度 | `market_config.price_limit` |
| 结算周期 | `market_config.settlement` |
| 交易时段 | `market_config.sessions` |
| 手续费率 | `market_config.fees` |
| 最小交易单位 | `market_config.min_lot` |
| 风控阈值 | `risk_config.*` |
| 股票池 | `universe_config` |
| 模型名 | `llm_config.tiers` |

CI 应加一条检查：在 `quant/`、`portfolio/`、`risk/`、`execution/` 中出现 `0.10`、`100`、`T+1` 等疑似市场常量的字面量时告警。

## 6. 可观测性

### 6.1 三类记录

| 类型 | 存储 | 用途 |
|---|---|---|
| 应用日志 | structlog JSON → 文件 | 排障 |
| Agent trace | `agent_trace` 表 | 复现推理过程、成本分析 |
| Decision journal | `decision_journal` 表 | 事后归因、自我评估 |

### 6.2 run_id 贯穿

每次日常运行生成一个 `run_id`（如 `20260831-cn-daily`），所有日志、trace、决策记录都带上它。这样可以：

```sql
-- 完整重建某天的决策过程
SELECT * FROM agent_trace WHERE run_id = '20260831-cn-daily' ORDER BY seq;
SELECT * FROM decision_journal WHERE run_id = '20260831-cn-daily';
```

### 6.3 必须告警的情况

| 情况 | 级别 |
|---|---|
| 数据完整性校验失败 | 严重，中止流程 |
| 双源数据差异超阈值 | 严重 |
| Token 预算超限 | 严重，按分项降级或中止 |
| Risk Engine REJECT | 警告，记录 |
| Agent 输出 schema 校验失败 | 警告，重试一次后跳过 |
| 对账不一致 | 严重（实盘阶段） |
| 单日回撤超阈值 | 严重（实盘阶段），触发 kill switch |
| 持仓数据超 5 交易日未更新 | 警告，推送提醒 |
| 推送投递失败 | 警告，换备用渠道重试 |
| 单日推送数超上限 | 信息，记录（抑制策略已生效） |
| L1 通过率异常升高（> 10%） | 警告，可能是关键词或实体词典问题 |
| 触发器有用率 < 20% | 信息，月度评估时考虑关闭该规则 |

## 7. 架构演进路径

### 7.1 各阶段的架构完整度

| 阶段 | L0 | L1 | L2-Quant | L2-Agent | L3 | L4 | L4.5 Monitor | L5 |
|---|---|---|---|---|---|---|---|---|
| P0 | ✅ | ✅ | 骨架 | - | - | Simulated | - | - |
| P1 | ✅ | ✅ | 基础因子 | 单 Agent | - | Simulated | - | Shadow 启动 |
| P2 | ✅ | ✅ | 基础因子 | ✅ 全套 | - | Simulated | - | ✅ |
| P2a | ✅ | ✅ | 基础因子 | ✅ | - | Simulated | **规则层（零成本）** | + Alert 评估 |
| P2b | ✅ | ✅ | 基础因子 | ✅ | - | Simulated | **三级漏斗完整** | ✅ |
| P3 | ✅ | ✅ | ✅ 模型 | ✅ | 简版 Fusion | Simulated | ✅ | ✅ |
| P4 | ✅ | ✅ | ✅ | ✅ | ✅ | Simulated | ✅ | ✅ 归因 |
| P5 | ✅ | ✅ | ✅ | ✅ | ✅ Risk 完整 | Simulated | ✅ | ✅ |
| P6 | ✅ | ✅ | ✅ | ✅ | ✅ | + Alpaca | ✅ | ✅ |
| P7 | ✅ | ✅ | ✅ | ✅ | ✅ | + 实盘 | ✅ | ✅ |

### 7.2 多市场扩展点

从 P0 起就要留好的扩展点（不是等 P6 再改）：

```python
# 所有市场相关逻辑通过 MarketConfig 注入
class MarketConfig(BaseModel):
    market: str
    timezone: str
    sessions: list[tuple[time, time]]
    settlement: str                       # "T+0" | "T+1" | "T+2"
    price_limit: PriceLimitConfig | None
    min_lot: int
    short_selling: bool
    fees: FeeConfig
    industry_taxonomy: str
    calendar_source: str
```

代码中的每个市场敏感点都必须是 `if market_config.xxx` 而不是 `if market == "CN"`。前者可以通过加配置支持新市场，后者需要改代码。

## 8. 架构决策速查

| 决策 | 结论 |
|---|---|
| 数据访问是否统一入口 | 是，`PITRepository` 唯一 |
| Agent 能否直接读数据库 | 否，必须通过 Tool |
| Agent 能否算仓位 | 否 |
| Agent 能否修改风控参数 | 否 |
| Risk 能否被绕过 | 否，接口不提供 override |
| 回测与实时是否共享代码 | 是，Stage 3-5 必须同一份 |
| 是否支持多市场 | 是，配置驱动，非分支判断 |
| Quant 是否依赖 Agent | 否，单向依赖（Agent 可读 Quant） |
| 原始数据是否归档 | 是，Parquet 留档可重放 |
| Monitor 是否含新决策逻辑 | 否，复用 StockAgent / RiskEngine |
| Monitor 规则层是否调 LLM | 否，L1 零成本 |
| 预算耗尽时监控是否失效 | 否，降级为 L1 但关键告警仍工作 |
| 盘中是否做全市场扫描 | 否，仅持仓 + 关注列表 |
| 推送是否触发自动交易 | 否，推送仅是建议 |
| 预算是否可跨分项挪用 | 否，各分项独立 |
| 成本检查在调用前还是后 | 前，事后统计无法拦截 |
