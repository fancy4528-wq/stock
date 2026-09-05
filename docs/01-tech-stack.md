# 01 — 技术选型

## 0. 选型原则

1. **单机可跑** — 不引入需要集群的组件
2. **同类只选一个** — 不同时用两个消息队列、两个 ORM
3. **可替换** — 外部依赖走适配器接口，不在业务代码里直接调 SDK
4. **成熟优先** — 不用小众库，除非无替代
5. **能删掉** — 每个依赖都要能回答"如果去掉它，损失什么"

## 1. 语言与运行时

| 项 | 选择 | 版本 | 理由 |
|---|---|---|---|
| 语言 | Python | 3.11+ | 量化生态唯一现实选择；3.11 起性能改善明显 |
| 包管理 | uv | latest | 比 pip/poetry 快一个量级，锁文件可靠 |
| 类型检查 | mypy | strict 模式 | 数据管道类型错误极易静默传播 |
| 格式化/Lint | ruff | latest | 替代 black + isort + flake8 |
| 前端 | TypeScript + React | - | 仅 P2 之后需要，先用 CLI/静态 HTML |

**被否决：**
- **Rust/Go 写核心** — 量化库生态缺失，收益不抵成本
- **Poetry** — 依赖解析慢，uv 已成熟
- **Conda** — 环境臃肿，与 Docker 重叠

## 2. 数据存储

### 2.1 选型

| 用途 | 选择 | 理由 |
|---|---|---|
| 关系型 + 时序 + 向量 | **PostgreSQL 16 + TimescaleDB + pgvector** | 单库三用，避免跨库一致性问题 |
| 缓存 / 队列 / 锁 | **Redis 7** | 轻量，够用 |
| 本地分析 | **DuckDB** | 读 Parquet 做因子回测极快，作为 PG 的分析侧补充 |
| 原始文件归档 | **Parquet + 本地文件系统** | 原始响应留档，可重放 |

### 2.2 为什么单 PostgreSQL

草案建议 PostgreSQL + pgvector + TimescaleDB + Redis 四件套，方向对，但要明确 **TimescaleDB 和 pgvector 都是 PG 扩展，不是独立数据库**。所以实际只有两个进程：PG 和 Redis。

这很重要，因为：
- 财务数据（关系型）和行情（时序）需要 JOIN，跨库会很痛
- 单机场景下 PG 的时序性能足够（日线数据量极小）
- 事务一致性天然保证

### 2.3 数据量估算

| 数据 | 规模 | 存储估算 |
|---|---|---|
| A 股全市场日线 10 年 | ~5000 股 × 2500 天 | ~1.5 GB |
| MVP 池日线 10 年 | 50 股 × 2500 天 | ~15 MB |
| 财务数据（含修订版本） | ~5000 股 × 40 期 × 3 版本 | ~500 MB |
| 新闻/公告全文 | 每日 ~2000 条 × 1 年 | ~5 GB |
| 新闻向量 (1024 维 float32) | 70 万条 | ~3 GB |
| 因子值 | 50 因子 × 5000 股 × 2500 天 | ~5 GB |

结论：**单机 PG，预留 50 GB 磁盘足够跑到 P5。**

**被否决：**
- **ClickHouse** — 适合 tick 级和 TB 级，我们的量级用不上，运维成本不值
- **InfluxDB** — 不支持关系型 JOIN，财务数据无处安放
- **独立向量库（Milvus/Qdrant）** — 70 万条向量 pgvector 完全够；HNSW 索引已支持
- **MongoDB** — 金融数据强 schema，文档库反而增加校验负担

### 2.4 DuckDB 的定位

不是主存储，而是**分析加速层**：

```
PostgreSQL (真相来源)
     ↓ 定期导出
Parquet 文件 (因子面板)
     ↓
DuckDB (回测时的高速读取)
```

理由：因子回测需要反复全表扫描，PG 的行存不适合。DuckDB 读 Parquet 做列式聚合比 PG 快 10-100 倍，且零运维。

## 3. Agent 框架

### 3.1 选择：不用现成框架，自建薄编排层

| 项 | 选择 |
|---|---|
| LLM 调用 | 官方 SDK + 自建统一封装 |
| 结构化输出 | **Pydantic + 强制 JSON Schema** |
| 工具调用 | 原生 function calling |
| 编排 | 自建，基于 Python asyncio |
| 追踪 | 自建 `agent_trace` 表 + 可选 Langfuse |

### 3.2 为什么不用 LangChain / LangGraph / CrewAI

这是一个有争议的决定，理由：

| 问题 | 说明 |
|---|---|
| 抽象泄漏 | 出错时要读框架源码才知道发生了什么 |
| 版本不稳 | LangChain 的 API 频繁破坏性变更 |
| 我们的编排很简单 | Chief → Sector → Stock 是固定 DAG，不需要复杂图执行引擎 |
| 追踪需求特殊 | 我们要把每次调用关联到数据版本和 evidence ID，框架的 tracing 不匹配 |
| Token 成本可控性 | 需要精确控制每个 prompt 的内容，框架的自动组装是黑盒 |

自建的核心只需要三样东西，代码量不大：

```python
# 1. 统一 LLM 客户端（带重试、计量、缓存）
class LLMClient:
    async def complete(self, messages, tools=None, schema=None) -> LLMResponse: ...

# 2. Agent 基类（工具注册 + 结构化输出 + trace）
class Agent[TOutput: BaseModel]:
    tools: list[Tool]
    output_schema: type[TOutput]
    async def run(self, ctx: AgentContext) -> TOutput: ...

# 3. 编排器（并发控制 + 依赖顺序 + 预算控制）
class Orchestrator:
    async def run_stage(self, agents: list[Agent], budget: TokenBudget) -> list[Any]: ...
```

**保留的退路**：如果后期编排复杂度真的上升（需要动态图、循环、人工介入节点），再引入 LangGraph，届时只需替换 Orchestrator。

### 3.3 LLM 模型分层

Token 成本是真实约束，必须分层。

| 档位 | 用途 | 上下文需求 | 调用频率 |
|---|---|---|---|
| 小模型 | 新闻去重、实体识别、粗筛分类 | 短 | 极高（每日千次） |
| 中模型 | 板块分析、事件影响判断 | 中 | 中（每日数十次） |
| 大模型 | Chief 决策汇总、thesis 生成 | 长 | 低（每日数次） |

具体模型不写死在文档里（迭代太快），通过配置指定：

```yaml
# config/llm.yaml
tiers:
  small:
    provider: "..."
    model: "..."
    max_tokens: 2048
  medium:
    provider: "..."
    model: "..."
  large:
    provider: "..."
    model: "..."

budget:
  daily_usd_limit: 5.0
  per_run_usd_limit: 1.0
  on_exceed: "abort"   # abort | downgrade | warn
```

**中文场景注意**：A 股新闻/公告是中文，需评估各模型的中文金融文本处理质量，尤其是数字提取的准确性。这一项要在 P1 做实测对比，不能靠假设。

### 3.4 Embedding

| 项 | 选择 | 理由 |
|---|---|---|
| 中文 embedding | BGE-M3 或 bge-large-zh（本地） | 新闻量大，API 调用成本高；本地模型质量已足够 |
| 部署 | sentence-transformers + ONNX | CPU 可跑，无需 GPU |
| 维度 | 1024 | pgvector HNSW 索引友好 |

**被否决**：全部走 OpenAI embedding API — 每日 2000 条新闻 × 长文本，成本不划算，且中文表现不必然优于专门的中文模型。

**Embedding 是少数可以完全本地化的环节，没有理由付费。** 入库多少都不花钱，只有"检索结果进 prompt"才花钱。所以成本控制的着力点是 `top_k`（默认 3-5）和片段长度（≤800 字），不是入库量。见 [17-knowledge-base](17-knowledge-base.md) 7.4 节。

**入库范围的边界**：只放年报 MD&A、风险因素、公告全文这类无法结构化的长文本。不放金融教科书、投资流派材料、制度规则全文（见 [ADR-0011](adr/0011-no-general-finance-kb.md)）。财务数字走 `financial_report` 表，产业链走 `supply_chain` 表——**能结构化的不进向量库**。

## 4. 量化计算

| 用途 | 选择 | 理由 |
|---|---|---|
| 数据框 | **Polars** 为主，pandas 为辅 | Polars 快且内存效率高；部分库仅接受 pandas，边界处转换 |
| 数值 | NumPy | 无替代 |
| 因子计算 | 自建 | 因子逻辑是核心资产，不外包 |
| ML 模型 | **LightGBM** → XGBoost | 表格数据金标准，训练快，可解释性好 |
| 特征工程 | 自建 + ta-lib（可选） | ta-lib 装起来麻烦，指标自己写更可控 |
| 统计检验 | scipy + statsmodels | IC 显著性、t 检验 |
| 回测引擎 | **自建** | 见下 |

### 4.1 为什么自建回测引擎

| 候选 | 否决理由 |
|---|---|
| **backtrader** | 事件驱动设计对日频截面策略过重；社区活跃度下降 |
| **vectorbt** | 向量化很快，但对 A 股涨跌停/停牌/T+1 的处理需要大量 hack |
| **zipline** | 已停止维护，美股假设深度耦合 |
| **Qlib** | 强大且专门针对 A 股，但框架侵入性强，要按它的数据格式和工作流组织整个项目 |

自建的核心理由：**A 股的三条规则（T+1、涨跌停不可成交、停牌）必须是回测引擎的一等公民，而不是补丁。** 这三条对回测结果的影响远大于滑点，任何通用框架都需要深度改造。

我们的回测需求其实很窄：
- 日频截面选股
- 目标权重再平衡
- 真实成本 + 撮合约束

这个范围自建代码量可控（~1000 行），换来的是完全可控和可审计。

**保留的用法**：Qlib 的**因子表达式库**和部分**评估指标实现**可以参考或选择性引用，但不接受它的框架约束。

## 5. 服务与调度

| 用途 | 选择 | 理由 |
|---|---|---|
| API 框架 | FastAPI | 类型友好，与 Pydantic 天然配合 |
| 任务调度 | **APScheduler**（P0-P2）→ **Prefect**（P3+） | 早期简单够用；后期需要重试/依赖/回填时再升级 |
| 异步任务 | asyncio + Redis 队列（自建薄封装） | 不引入 Celery |
| 容器 | Docker Compose | 单机足够 |
| 配置 | Pydantic Settings + YAML | 类型校验的配置 |
| 日志 | structlog（JSON 结构化） | 决策日志需要可查询 |
| 测试 | pytest + hypothesis | hypothesis 用于因子计算的属性测试 |

**被否决：**
- **Airflow** — 单机个人项目严重过重
- **Celery** — 我们的任务是 IO 密集的定时批处理，asyncio + Redis 足够
- **Dagster** — 数据资产概念很契合，但学习成本高，留作 Prefect 的备选

### 5.1 为什么调度器要分两阶段

P0-P2 的任务是简单定时（每日收盘后拉数据、生成报告），APScheduler 一个装饰器解决。

P3 之后会出现真正的调度需求：
- 因子计算依赖行情入库完成
- 历史数据回填需要断点续传
- 失败任务需要选择性重跑

那时再引入 Prefect。提前引入是过度设计。

## 6. 券商接入

| 市场 | 阶段 | 选择 | 状态 |
|---|---|---|---|
| 美股 | Paper | **Alpaca** (alpaca-py) | P6 |
| 美股 | 实盘 | Alpaca 或 IBKR (ib_insync) | P7a |
| A 股 | 实盘 | QMT (xtquant) 或 PTrade | P7b，待权限 |
| 全部 | 模拟 | **自建 SimulatedBroker** | P0 起即有 |

关键约定：**所有券商走 `BrokerAdapter` 接口，业务代码不见任何券商 SDK。** 详见 [10-execution](10-execution.md)。

`SimulatedBroker` 从 P0 就实现，用于：
- 回测撮合
- Shadow Portfolio
- 单元测试
- A 股阶段的"虚拟执行"

这样 P6 接 Alpaca 时，只是新增一个 Adapter 实现，上层零改动。

## 7. 数据源库

| 库 | 用途 | 备注 |
|---|---|---|
| **akshare** | A 股行情/财务/板块/资金流 | 免费，接口多但稳定性一般，需重试与校验 |
| **tushare** | A 股数据（备份源 + 交叉校验） | 积分制，部分接口需积分 |
| baostock | A 股备份源 | 免费，历史数据质量好 |
| alpaca-py | 美股行情 + 交易 | P6 起 |
| 自建 collector | 新闻/公告 RSS 与网页 | 遵守 robots.txt 与频率限制 |

**双源交叉校验是硬要求**：单一数据源必然有错。见 [04-data-sources](04-data-sources.md) 的校验规则。

## 8. 前端

| 阶段 | 方案 |
|---|---|
| P0-P1 | CLI 输出 + Markdown 日报文件 |
| P2-P4 | 静态 HTML 报告（Jinja2 模板 + Plotly） |
| P5+ | FastAPI + React（仅在确有交互需求时） |

不要早做前端。P1 阶段一份格式良好的 Markdown 日报比半成品 Dashboard 有用得多。

## 9. 完整依赖清单（P0）

```toml
[project]
requires-python = ">=3.11"
dependencies = [
    # 数据
    "polars==1.17.1",
    "pandas==2.2.3",
    "numpy==2.2.0",
    "pyarrow==18.1.0",
    "duckdb==1.1.3",

    # 数据库
    "psycopg[binary,pool]==3.2.3",
    "sqlalchemy==2.0.36",
    "alembic==1.14.0",
    "redis==5.2.1",

    # 数据源
    "akshare==1.15.30",
    "tushare==1.4.6",

    # 配置与校验
    "pydantic==2.10.3",
    "pydantic-settings==2.7.0",
    "pyyaml==6.0.2",

    # 服务
    "fastapi==0.115.6",
    "uvicorn[standard]==0.34.0",
    "apscheduler==3.11.0",
    "httpx==0.28.1",
    "tenacity==9.0.0",

    # 日志
    "structlog==24.4.0",

    # 量化
    "scipy==1.14.1",
    "statsmodels==0.14.4",
    "lightgbm==4.5.0",
    "scikit-learn==1.6.0",
]

[dependency-groups]
dev = [
    "pytest==8.3.4",
    "pytest-asyncio==0.25.0",
    "pytest-cov==6.0.0",
    "hypothesis==6.122.3",
    "mypy==1.13.0",
    "ruff==0.8.4",
]
```

版本号是撰写时的参考值，实际执行 `uv add` 时会解析到当时可用版本。**约定：所有依赖锁定精确版本，不用范围。**

P1 之后新增（LLM 相关）依赖单独在对应阶段确定，因为模型 SDK 迭代快。

## 10. 基础设施定义

```yaml
# docker-compose.yml
services:
  postgres:
    image: timescale/timescaledb-ha:pg16
    environment:
      POSTGRES_DB: quantagent
      POSTGRES_USER: quantagent
      POSTGRES_PASSWORD: ${PG_PASSWORD:?required}
    ports:
      - "127.0.0.1:5432:5432"     # 仅本机可访问
    volumes:
      - pgdata:/home/postgres/pgdata
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U quantagent"]
      interval: 10s
      timeout: 5s
      retries: 5

  redis:
    image: redis:7-alpine
    command: redis-server --appendonly yes --requirepass ${REDIS_PASSWORD:?required}
    ports:
      - "127.0.0.1:6379:6379"     # 仅本机可访问
    volumes:
      - redisdata:/data

volumes:
  pgdata:
  redisdata:
```

安全约定：
- 端口绑定 `127.0.0.1`，不暴露到局域网
- 密码从环境变量读取，无默认值（`:?required` 缺失即启动失败）
- `.env` 加入 `.gitignore`，提供 `.env.example`

`timescaledb-ha` 镜像同时包含 TimescaleDB 和 pgvector，省去单独安装。

## 11. 选型决策汇总

| # | 决策 | 主要理由 | ADR |
|---|---|---|---|
| 1 | Python 3.11+ | 生态唯一选择 | - |
| 2 | 单 PostgreSQL（TimescaleDB + pgvector） | 避免跨库 JOIN 与一致性问题 | [ADR-0002](adr/0002-single-postgres.md) |
| 3 | 自建 Agent 编排，不用 LangChain | 抽象泄漏、版本不稳、需求简单 | [ADR-0003](adr/0003-no-agent-framework.md) |
| 4 | 自建回测引擎 | A 股规则需为一等公民 | [ADR-0004](adr/0004-custom-backtest.md) |
| 5 | Polars 为主 | 性能与内存 | - |
| 6 | LightGBM 起步，不上深度学习 | 需要 baseline 对照 | [ADR-0005](adr/0005-model-progression.md) |
| 7 | 本地 embedding | 成本 + 中文质量 | - |
| 8 | APScheduler → Prefect 两阶段 | 避免过早引入复杂度 | - |
| 9 | BrokerAdapter 抽象 + SimulatedBroker 先行 | 多市场可移植 | [ADR-0006](adr/0006-broker-abstraction.md) |
