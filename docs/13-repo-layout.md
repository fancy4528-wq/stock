# 13 — 仓库结构与工程约定

## 1. 目录结构

```
quantagent/
├── README.md
├── pyproject.toml
├── uv.lock
├── Makefile
├── docker-compose.yml
├── .env.example                    # 不含真实凭据
├── .gitignore
├── alembic.ini
│
├── docs/                           # 设计文档（本目录）
│   ├── 00-overview.md ... 14-risk-register.md
│   ├── adr/                        # 架构决策记录
│   ├── factor-reports/             # 因子测试报告
│   ├── phase-log.md
│   ├── data-access-log.md
│   ├── cost-log.md
│   └── baseline-results.md
│
├── config/
│   ├── base.yaml
│   ├── markets/{cn,us}.yaml
│   ├── risk/{cn,us}.yaml
│   ├── portfolio/{cn,us}.yaml       # 含 cold_start.scale_in 配置
│   ├── execution/{cn_shadow,us_paper}.yaml
│   ├── universe/mvp_cn.yaml
│   ├── user/                       # ★ P5: 用户声明式配置
│   │   ├── eligibility_cn.yaml     # 可交易板块，默认仅 main
│   │   ├── deployment_cn.yaml      # 投入资金/比例（investable）+ 主动推送开关（默认关）
│   │   └── exit_policy_cn.yaml     # 止盈止损阈值，用户可配
│   ├── llm.yaml                    # 模型分层 + 分项预算
│   ├── monitor/                    # ★ P2a
│   │   ├── price_triggers.yaml
│   │   ├── risk_triggers.yaml
│   │   ├── recommendation_triggers.yaml  # P5: 空仓/待执行用户
│   │   ├── announcement_types.yaml
│   │   ├── keywords.yaml           # 关键词分级
│   │   ├── entity_aliases.yaml     # 实体别名
│   │   ├── suppression.yaml
│   │   ├── budget.yaml
│   │   └── schedule.yaml
│   ├── notify/
│   │   ├── channels.yaml
│   │   └── templates/
│   ├── mappings/industry_sw_gics.yaml
│   └── envs/{dev,prod}.yaml
│   # live_enabled.yaml 不入库，本地手动创建
│
├── migrations/
│   └── versions/
│
├── prompts/                        # Prompt 版本化资产
│   ├── _common/
│   │   ├── constraints.md          # 通用约束（固定前缀，可缓存）
│   │   └── glossary.md             # K1 本项目口径（≤500 token）
│   ├── reporter/v1.md
│   ├── news_extractor/v1.md
│   ├── macro/v1.md
│   ├── industry/v1.md
│   ├── theme/v1.md
│   ├── stock/v1.md
│   ├── chief/v1.md
│   └── l2_triage/v1.md             # P2b 批处理分诊
│
├── knowledge/                      # 人工维护的知识资产（P4+）
│   └── lessons/                    # K4，上限 50 条
│       ├── L-0001.yaml
│       └── ...
│   # ★ 不放金融教科书 / 投资流派材料，见 ADR-0011
│
├── src/quantagent/                 # ★ src layout
│   │
│   ├── shared/                     # L-1: 横切
│   │   ├── config/                 # Pydantic Settings 加载
│   │   ├── logging/                # structlog 配置
│   │   ├── types/                  # 通用类型、枚举
│   │   ├── errors.py               # 异常层次
│   │   └── utils/
│   │
│   ├── data/                       # L0: 数据地基
│   │   ├── collectors/
│   │   │   ├── base.py
│   │   │   ├── akshare/
│   │   │   ├── baostock/
│   │   │   ├── tushare/
│   │   │   ├── news/
│   │   │   └── alpaca/             # P6
│   │   ├── normalizers/
│   │   │   ├── symbol.py           # 代码归一化
│   │   │   ├── units.py            # 单位统一
│   │   │   └── {price,financial,news}.py
│   │   ├── validators/
│   │   │   ├── rules/              # 按 dataset 分文件
│   │   │   └── engine.py
│   │   ├── loaders/
│   │   └── archive/                # Parquet 归档
│   │
│   ├── core/                       # L1: 数据访问
│   │   ├── repository/
│   │   │   ├── pit.py              # ★ PITRepository
│   │   │   ├── universe.py
│   │   │   └── sql/                # SQL 函数定义
│   │   ├── calendar/
│   │   ├── market/                 # MarketConfig 加载与校验
│   │   └── assertions.py           # assert_no_lookahead 等
│   │
│   ├── quant/                      # L2: 量化
│   │   ├── features/
│   │   ├── labels/
│   │   ├── models/
│   │   ├── training/
│   │   ├── evaluation/
│   │   └── store/
│   │
│   ├── agents/                     # L2: Agent
│   │   ├── base.py                 # Agent 协议
│   │   ├── llm/                    # LLMClient、分层、计量
│   │   ├── tools/                  # 工具实现与注册
│   │   ├── orchestrator.py
│   │   ├── validation.py           # 输出校验
│   │   ├── reporter/               # P1
│   │   ├── news_extractor/         # P2
│   │   ├── macro/
│   │   ├── sector/                 # industry + theme
│   │   ├── stock/
│   │   └── chief/
│   │
│   ├── knowledge/                  # L2: 知识层
│   │   ├── ingestion/
│   │   │   ├── documents.py        # K2: 年报/研报/公告切片（P2）
│   │   │   ├── thesis.py           # K3: decision_journal → chunk（P4）
│   │   │   └── lessons.py          # K4: YAML → chunk（P4+）
│   │   ├── embedding/
│   │   │   ├── local.py            # bge-m3 本地推理（零 API 成本）
│   │   │   └── cache.py
│   │   ├── retrieval/              # PIT 过滤的 RAG
│   │   │   ├── search.py           # search_chunks_as_of（唯一入口）
│   │   │   ├── history.py          # search_own_history（P4）
│   │   │   └── rerank.py           # 可选，P4+
│   │   └── curation/
│   │       ├── validate.py         # K4 准入标准校验
│   │       └── expire.py           # 过期条目清理
│   │
│   ├── decision/                   # L3: 决策
│   │   ├── fusion/
│   │   ├── portfolio/
│   │   │   ├── engine.py           # ①-⑦ 构建流程
│   │   │   ├── weighting.py
│   │   │   ├── decorrelate.py
│   │   │   ├── cold_start.py       # ★ P5: ①-⑥ + 资金量约束
│   │   │   ├── eligibility.py      # P5: 板块权限过滤
│   │   │   ├── exit_policy.py      # P5: 止盈止损策略（fixed/trailing/atr/staged）
│   │   │   ├── lots.py             # 整手取整（向下，残差留现金）
│   │   │   └── scale_in.py         # 分批建仓计划与批次决策
│   │   └── risk/
│   │       ├── engine.py
│   │       ├── rules/              # 每类规则一文件
│   │       └── killswitch.py
│   │
│   ├── execution/                  # L4: 执行
│   │   ├── broker/
│   │   │   ├── base.py             # BrokerAdapter
│   │   │   ├── simulated.py        # ★ P0 就要有
│   │   │   ├── alpaca.py           # P6
│   │   │   └── qmt.py              # P7b
│   │   ├── orders/
│   │   │   ├── manager.py
│   │   │   ├── idempotency.py
│   │   │   └── state_machine.py
│   │   ├── reconciliation/
│   │   └── guards.py               # LiveTradingGuard
│   │
│   ├── monitor/                    # L4.5: 盘中监控（P2a/P2b）
│   │   ├── triggers/
│   │   │   ├── base.py             # Trigger 协议
│   │   │   ├── price.py            # A 类：价格触发（零 LLM）
│   │   │   ├── risk.py             # B 类：风控触发（零 LLM）
│   │   │   ├── announcement.py     # C 类：公告触发
│   │   │   ├── news.py             # D 类：新闻触发
│   │   │   └── registry.py
│   │   ├── funnel/
│   │   │   ├── l1_rules.py         # ★ 零成本规则层
│   │   │   ├── l2_triage.py        # 小模型分诊（批处理）
│   │   │   ├── l3_analysis.py      # 复用 StockAgent
│   │   │   ├── entity_matcher.py   # 别名词典匹配
│   │   │   └── keywords.py         # 关键词分级
│   │   ├── suppression.py          # 冷却期与上限
│   │   ├── budget.py               # 监控专用预算
│   │   ├── cache.py                # 结果缓存
│   │   └── engine.py               # 监控主循环
│   │
│   ├── notify/                     # L6: 推送（P2a）
│   │   ├── base.py                 # NotifierAdapter
│   │   ├── telegram.py
│   │   ├── ntfy.py
│   │   ├── wecom.py
│   │   ├── email.py
│   │   ├── formatter.py            # Alert → 各渠道格式
│   │   └── feedback.py             # 反馈收集
│   │
│   ├── positions/                  # 持仓维护（P2a）
│   │   ├── manual.py               # YAML/CSV
│   │   ├── importer.py             # 对账单导入
│   │   ├── staleness.py            # 时效性检查
│   │   └── recommendation.py       # P5: 推荐记录与执行率跟踪
│   │
│   ├── evaluation/                 # L5: 评估
│   │   ├── journal/
│   │   ├── shadow/
│   │   ├── attribution/
│   │   ├── agent_eval/
│   │   ├── alert_eval/             # 推送质量评估（P2a）
│   │   ├── cost_tracker/           # LLM 成本归因
│   │   └── reports/
│   │
│   ├── backtest/
│   │   ├── engine.py
│   │   ├── metrics.py
│   │   ├── bias_checks.py          # 防偏差检查
│   │   └── sentinel.py             # 未来函数哨兵
│   │
│   ├── reporting/                  # L6: 输出
│   │   ├── daily.py
│   │   ├── execution_list.py       # A 股人工清单
│   │   └── templates/              # Jinja2
│   │
│   ├── scheduler/
│   │   ├── jobs/
│   │   └── app.py
│   │
│   └── cli/                        # 命令行入口
│       └── main.py
│
├── tests/
│   ├── conftest.py
│   ├── fixtures/                   # 测试数据
│   ├── unit/                       # 镜像 src 结构
│   ├── integration/
│   ├── property/                   # hypothesis 测试
│   ├── calibration/                # ★ 撮合假设校准（P7b-1）
│   │   ├── test_matching_assumptions.py
│   │   └── reports/                # MatchingCalibration 记录，append-only
│   └── e2e/
│
├── scripts/
│   ├── backfill.py
│   ├── replay.py
│   ├── lint_pit.py                 # PIT 静态检查
│   └── calibrate_matching.py       # 向模拟环境与 SimulatedBroker 同时下单并对比
│
└── data/                           # 运行时数据（gitignore）
    ├── raw/                        # 原始归档
    ├── features/                   # Parquet 面板
    └── artifacts/                  # 模型文件
```

## 2. 分层依赖约束

### 2.1 允许的依赖方向

```
cli / scheduler / reporting / notify
        ↓
    evaluation
        ↓
     monitor
        ↓
    execution
        ↓
     decision
        ↓
  quant  |  agents  |  knowledge
        ↓
       core
        ↓
       data
        ↓
      shared
```

### 2.2 自动化检查

```python
# tests/test_architecture.py
LAYER_ORDER = [
    "shared", "data", "core",
    "quant", "agents", "knowledge",
    "decision", "execution", "monitor",
    "evaluation", "backtest",
    "notify", "reporting", "scheduler", "cli",
]

FORBIDDEN = [
    # 下层不能依赖上层
    ("data",      ["core", "quant", "agents", "decision", "execution", "monitor"]),
    ("core",      ["quant", "agents", "decision", "execution", "monitor"]),
    ("quant",     ["agents", "decision", "execution", "monitor"]),  # ★ Quant 不依赖 Agent
    ("agents",    ["decision", "execution", "monitor"]),
    ("decision",  ["execution", "evaluation", "monitor"]),
    # 风控不能依赖 LLM
    ("decision.risk", ["agents"]),
    # ★ 监控的规则层不能依赖 LLM（保证零成本 + 预算耗尽仍工作）
    ("monitor.triggers.price",   ["agents", "monitor.funnel.l2_triage",
                                  "monitor.funnel.l3_analysis"]),
    ("monitor.triggers.risk",    ["agents", "monitor.funnel.l2_triage",
                                  "monitor.funnel.l3_analysis"]),
    ("monitor.funnel.l1_rules",  ["agents"]),
]

def test_no_forbidden_imports():
    for module, forbidden in FORBIDDEN:
        for imported in get_imports(f"src/quantagent/{module}"):
            assert not any(imported.startswith(f) for f in forbidden), (
                f"{module} 不应依赖 {imported}"
            )
```

关键约束：
- `quant` 不依赖 `agents`（保证量化部分可独立回测）
- `decision.risk` 不依赖 `agents`（保证风控无 LLM）
- `data` 不依赖任何上层（Collector 里不能调 Agent）
- **`monitor.triggers.price` / `.risk` / `funnel.l1_rules` 不依赖 `agents`**（保证零 LLM 成本）
- `agents` / `decision` / `quant` 不依赖 `monitor`（监控是消费方）

## 3. 命名约定

### 3.1 通用

| 类型 | 约定 | 示例 |
|---|---|---|
| 模块/包 | `snake_case` | `pit_repository.py` |
| 类 | `PascalCase` | `PITRepository` |
| 函数/变量 | `snake_case` | `get_prices_as_of` |
| 常量 | `UPPER_SNAKE` | `MAX_SECTOR_EXPOSURE` |
| 私有 | 前缀 `_` | `_resolve_symbol` |
| 类型别名 | `PascalCase` | `Symbol = str` |

### 3.2 领域约定

| 概念 | 约定 | 说明 |
|---|---|---|
| 股票代码 | `symbol`，格式 `600519.SH` | 不用 `code` / `ticker` / `stock_id` |
| 数据库主键 | `security_id` | 内部使用，外部接口用 `symbol` |
| 时点参数 | `as_of` | 统一命名，keyword-only |
| 日期 | `trade_date` / `period_end` / `announced_at` | 明确语义，不用泛化的 `date` |
| 权重 | `weight`（0-1 小数） | 不用百分数 |
| 收益率 | `ret`（0.01 = 1%） | 不用百分数 |
| 数量 | `quantity`（股数） | 不用 `size` / `amount` |
| 金额 | `amount`（货币单位） | 与 `quantity` 严格区分 |
| 评分 | `score`（0-1） | 统一范围 |

**`amount` vs `quantity` 混用是金融代码最常见的 bug 来源。** 必须严格区分：`quantity` 是股数，`amount` 是金额。

### 3.3 数据库

| 类型 | 约定 |
|---|---|
| 表名 | 单数 `snake_case`：`price_daily` 而非 `prices` |
| 主键 | `{table}_id` |
| 外键 | 与被引用主键同名 |
| 时间戳 | `_at` 后缀（`announced_at`） |
| 日期 | `_date` 后缀（`trade_date`） |
| 布尔 | `is_` / `has_` 前缀 |
| 枚举 | PostgreSQL ENUM，不用 varchar + check |

## 4. 编码约定

### 4.1 强制类型注解

```toml
# pyproject.toml
[tool.mypy]
strict = true
warn_return_any = true
disallow_untyped_defs = true
disallow_any_generics = true
plugins = ["pydantic.mypy"]
```

金融数据管道中类型错误会静默传播（如把百分数当小数），strict 模式是必要的。

### 4.2 关键参数用 keyword-only

```python
# ✅ as_of 必须显式传，忘记会 TypeError
def get_prices(symbols: list[str], *, as_of: date) -> pl.DataFrame: ...

# ❌ 容易漏传或位置错误
def get_prices(symbols: list[str], as_of: date = None): ...
```

适用于：`as_of`、`market`、任何影响正确性的参数。

### 4.3 Pydantic 用于所有边界

| 边界 | 用途 |
|---|---|
| 配置加载 | `BaseSettings` |
| Agent 输出 | `BaseModel` + JSON Schema |
| 工具参数 | `BaseModel` |
| API 请求/响应 | `BaseModel` |
| 数据契约 | `BaseModel` |

内部计算用 Polars DataFrame（性能），跨模块边界用 Pydantic（校验）。

### 4.4 异常层次

```python
class QuantAgentError(Exception): ...

# 数据层
class DataError(QuantAgentError): ...
class DataQualityError(DataError): ...
class LookaheadError(DataError): ...          # ★ 未来函数
class SourceUnavailableError(DataError): ...

# Agent 层
class AgentError(QuantAgentError): ...
class SchemaValidationError(AgentError): ...
class BudgetExceeded(AgentError): ...
class EvidenceMissingError(AgentError): ...

# 决策层
class RiskError(QuantAgentError): ...
class RiskRejection(RiskError): ...

# 执行层
class ExecutionError(QuantAgentError): ...
class OrderStateUnknown(ExecutionError): ...  # ★ 超时后状态不明
class DuplicateOrderInFlight(ExecutionError): ...
class SystemHalted(ExecutionError): ...

# 研究纪律
class HoldoutViolation(QuantAgentError): ...  # ★ 封存期违规
```

`LookaheadError` 和 `HoldoutViolation` 是刻意设为独立异常的——它们代表研究纪律违规，不应被泛化的 `except Exception` 吞掉。

### 4.5 禁止事项

| 禁止 | 原因 |
|---|---|
| 业务代码写 SQL | 绕过 PIT 保护 |
| `except:` 裸捕获 | 会吞掉 `LookaheadError` |
| 硬编码市场常量 | 阻碍多市场 |
| 硬编码风控阈值 | 应来自配置 |
| 在因子函数内查库 | 破坏纯函数性 |
| `from x import *` | 依赖不明确 |
| 可变默认参数 | Python 陷阱 |
| `float` 表示金额（关键计算） | 精度问题，用 `Decimal` |
| 提交 `.env` / 凭据 | 安全 |
| 修改已用于生产的 prompt 版本 | 破坏可复现性 |

### 4.6 金额精度

```python
from decimal import Decimal

# ✅ 涉及资金结算的计算用 Decimal
def calc_commission(amount: Decimal, rate: Decimal, minimum: Decimal) -> Decimal:
    return max(amount * rate, minimum).quantize(Decimal("0.01"))

# float 可用于：因子值、评分、统计指标
# Decimal 必须用于：价格、金额、佣金、持仓市值
```

## 5. 测试约定

### 5.1 分层

| 类型 | 目录 | 要求 |
|---|---|---|
| 单元测试 | `tests/unit/` | 无外部依赖，用构造数据 |
| 集成测试 | `tests/integration/` | 用测试数据库 |
| 属性测试 | `tests/property/` | hypothesis，用于因子和风控 |
| E2E | `tests/e2e/` | 完整流程，用固定历史数据 |
| 架构测试 | `tests/test_architecture.py` | 依赖方向、命名约定 |

### 5.2 覆盖率要求

| 模块 | 最低覆盖率 |
|---|---|
| `decision/risk/` | 95%（风控最关键） |
| `monitor/triggers/` | 95%（漏报即失去价值） |
| `core/repository/` | 90%（PIT 保护） |
| `execution/` | 90%（真金白银） |
| `monitor/funnel/l1_rules.py` | 90%（过滤错误影响成本） |
| `monitor/suppression.py` | 90%（防推送疲劳） |
| `quant/features/` | 85% |
| `data/normalizers/` | 85%（代码归一化易错） |
| 其他 | 70% |

### 5.3 必须有的特殊测试

```python
# ① 未来函数哨兵
def test_no_lookahead_sentinel(): ...

# ② 生存者偏差
def test_universe_contains_delisted(): ...

# ③ 风控无绕过途径
def test_risk_engine_has_no_override_param(): ...

# ④ 风控确定性
def test_risk_engine_deterministic(): ...

# ⑤ 风控属性测试
@given(...)
def test_output_never_violates_hard_rules(): ...

# ⑥ 幂等性
def test_duplicate_order_id_returns_existing(): ...

# ⑦ 架构依赖
def test_no_forbidden_imports(): ...

# ⑧ 无硬编码市场常量
def test_no_hardcoded_market_constants(): ...

# ⑨ 因子纯函数性
def test_factors_have_no_db_access(): ...

# ⑩ 实盘默认关闭
def test_live_trading_disabled_by_default(): ...

# ⑪ ★ 监控规则层零 LLM 依赖
def test_l1_and_price_triggers_have_no_llm_calls():
    """静态检查：这些模块不得 import agents 或 llm 客户端。"""

# ⑫ ★ 预算耗尽时关键监控仍工作
def test_monitor_works_without_budget():
    budget = MonitorBudget(daily_usd_limit=0.0)     # 预算为零
    engine = MonitorEngine(budget=budget)
    alerts = engine.run(state_with_stop_loss_breach)
    assert any(a.trigger_codes == ["PX_STOP_LOSS"] for a in alerts)
    assert all(a.cost_usd == 0 for a in alerts)

# ⑬ ★ 预算检查在调用前
def test_budget_checked_before_call():
    """预算不足时不应发生实际 LLM 调用。"""
    with pytest.raises(BudgetExceeded):
        await agent.run(ctx_with_exhausted_budget)
    assert mock_llm.call_count == 0                  # ★ 关键断言

# ⑭ 抑制策略生效
def test_cooldown_suppresses_duplicate_alerts(): ...
def test_daily_alert_limit_enforced(): ...
def test_quiet_hours_respected_except_critical(): ...

# ⑮ 输出 token 上限设置
def test_all_llm_calls_have_max_tokens_out(): ...
```

### 5.4 测试数据

```
tests/fixtures/
├── cn/
│   ├── prices_10stocks_2023.parquet    # 固定的小样本
│   ├── financials_with_revisions.parquet  # 含修订版本
│   ├── delisted_stocks.parquet         # 含退市股
│   └── limit_up_cases.parquet          # 涨跌停场景
└── expected/
    └── baseline_metrics.json           # 基线结果快照
```

`baseline_metrics.json` 用于回归测试：重构后回测结果不应改变。

## 6. Makefile

```makefile
.PHONY: help install db-init db-migrate ingest features backtest report test lint

help:           ## 显示帮助
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'

install:        ## 安装依赖
	uv sync --all-groups

up:             ## 启动基础设施
	docker compose up -d
	@echo "等待数据库就绪..."
	@until docker compose exec -T postgres pg_isready -U quantagent; do sleep 1; done

db-init:        ## 初始化数据库
	uv run alembic upgrade head
	uv run python -m quantagent.cli init-reference-data

db-migrate:     ## 生成迁移
	uv run alembic revision --autogenerate -m "$(MSG)"

ingest-universe: ## 拉取 MVP 股票池数据
	uv run python -m quantagent.cli ingest --universe mvp_cn_50 --start 2015-01-01

ingest-daily:   ## 每日增量采集
	uv run python -m quantagent.cli ingest --daily

features:       ## 计算因子
	uv run python -m quantagent.cli features --market CN

backtest-baseline: ## 跑基准回测
	uv run python -m quantagent.cli backtest --strategy buy_and_hold

backtest:       ## 跑指定策略回测
	uv run python -m quantagent.cli backtest --strategy $(STRATEGY)

report:         ## 生成日报
	uv run python -m quantagent.cli report --market CN

monitor:        ## 启动盘中监控（前台）
	uv run python -m quantagent.cli monitor --market CN

monitor-once:   ## 单次监控检查（调试用）
	uv run python -m quantagent.cli monitor --once --market CN

position-show:  ## 显示当前持仓
	uv run python -m quantagent.cli position show

position-add:   ## 添加持仓 SYMBOL=xxx QTY=n COST=n
	uv run python -m quantagent.cli position add $(SYMBOL) $(QTY) $(COST)

cold-start:     ## 生成建仓推荐 CAPITAL=100000（P5）
	uv run python -m quantagent.cli cold-start --capital $(CAPITAL) --market CN

rec-status:     ## 查看当前推荐与分批执行进度
	uv run python -m quantagent.cli recommendation status

rec-quality:    ## 推荐质量与执行率统计
	uv run python -m quantagent.cli recommendation quality --days 180

cost-report:    ## LLM 成本报告
	uv run python -m quantagent.cli cost --days 30

alert-quality:  ## 推送质量统计
	uv run python -m quantagent.cli alert-quality --days 90

calibrate:      ## 撮合假设校准（需券商模拟环境，P7b-1）
	uv run python scripts/calibrate_matching.py --broker qmt_sim --n-orders 200

calibrate-report: ## 查看最近一次校准报告
	uv run python scripts/calibrate_matching.py --report-only

shadow:         ## 更新 shadow portfolio
	uv run python -m quantagent.cli shadow --update

test:           ## 跑全部测试
	uv run pytest -v --cov=src/quantagent --cov-report=term-missing

test-fast:      ## 只跑单元测试
	uv run pytest tests/unit -v

test-sentinel:  ## 跑未来函数哨兵测试
	uv run pytest tests/e2e/test_sentinel.py -v

lint:           ## 检查
	uv run ruff check src tests
	uv run ruff format --check src tests
	uv run mypy src
	uv run python scripts/lint_pit.py

fix:            ## 自动修复
	uv run ruff check --fix src tests
	uv run ruff format src tests

ci:             ## CI 全流程
	make lint
	make test
	make test-sentinel
```

## 7. Git 约定

### 7.1 分支

| 分支 | 用途 |
|---|---|
| `main` | 稳定，Gate 通过后合并 |
| `dev` | 开发主线 |
| `feat/xxx` | 功能 |
| `fix/xxx` | 修复 |

### 7.2 Commit 格式

```
<type>(<scope>): <subject>

[body]

[footer]
```

type: `feat` / `fix` / `docs` / `refactor` / `test` / `chore` / `perf`

scope: 模块名，如 `data`, `quant`, `risk`, `execution`

示例：
```
feat(data): 添加 akshare 财务数据 collector

- 支持季报/年报采集
- 原始响应归档为 Parquet
- 修订版本产生新 revision 而非覆盖

Refs: docs/03-data-model.md#2.5
```

### 7.3 需要 ADR 的变更

以下变更必须先写 ADR：
- 数据模型的 PIT 机制变更
- 分层依赖关系变更
- 新增外部依赖（数据源、库）
- 风控规则的增删
- 模型演进路径的偏离

### 7.4 .gitignore 关键项

```
.env
config/live_enabled.yaml
data/
*.parquet
*.db
__pycache__/
.venv/
.pytest_cache/
.mypy_cache/
data/artifacts/
```

## 8. CI 检查项

```yaml
# 概念性描述，实际 CI 配置视平台
checks:
  - ruff check + format
  - mypy strict
  - pytest unit (fast)
  - pytest integration
  - pytest property
  - test_architecture (依赖方向)
  - lint_pit.py (PIT 静态检查)
  - test_sentinel (未来函数)
  - 覆盖率门槛检查
  - 无硬编码市场常量检查
  - 无凭据泄漏检查（gitleaks 类工具）
```

## 9. 配置与凭据

### 9.1 分层加载

```
base.yaml → markets/{market}.yaml → envs/{env}.yaml → 环境变量
```

### 9.2 凭据规则

| 规则 |
|---|
| 只从环境变量读 |
| `.env` 本地文件，gitignore |
| 提供 `.env.example`（无真实值） |
| 日志中脱敏（只记录 key 名不记录值） |
| `config/live_enabled.yaml` 不入库 |

```python
class Credentials(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    tushare_token: SecretStr | None = None
    alpaca_key_id: SecretStr | None = None
    alpaca_secret: SecretStr | None = None
    llm_api_key: SecretStr | None = None
```

用 `SecretStr` 防止意外打印到日志。

## 10. 文档约定

| 约定 |
|---|
| 架构变更先改文档再改代码 |
| 文档中的阈值必须与代码常量一致 |
| 未核实的外部事实标注"需核实" |
| 过时内容标注 `[已废弃 YYYY-MM-DD]` 而非删除 |
| 代码中引用文档：`Refs: docs/03-data-model.md#2.5` |
| ADR 一旦接受不修改，需变更则新建 ADR 并标注 supersedes |
