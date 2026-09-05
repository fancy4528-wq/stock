# QuantAgent — AI 投资研究与交易系统

一个以 A 股研究为起点、可移植到美股实盘的多 Agent 投资研究系统。

## 一句话定位

**LLM 负责研究什么、如何解释、如何协调；Quant 负责算出来是什么；Risk Engine 负责能不能买、买多少；Execution 负责如何下单。**

系统有两条工作流：**盘后批处理**产出研究日报与调仓建议（空仓用户则是分批建仓推荐）；**盘中监控**在持仓需要调整时主动推送。

## 当前状态

| 项 | 状态 |
|---|---|
| 阶段 | 文档设计期（Pre-P0） |
| 首发市场 | A 股（研究 + 建议，不接交易 API） |
| 目标市场 | 美股（Paper → 实盘）、A 股（权限达成后接入） |
| 代码 | 未开始 |

## 文档导航

### 先读这三份

1. [00-overview](docs/00-overview.md) — 项目定位、目标与非目标、成功标准
2. [11-mvp](docs/11-mvp.md) — MVP 到底做什么、不做什么、怎么算完成
3. [12-roadmap](docs/12-roadmap.md) — 阶段划分与准入 Gate

### 设计文档

| 文档 | 内容 |
|---|---|
| [01-tech-stack](docs/01-tech-stack.md) | 技术选型与理由，含被否决的方案 |
| [02-architecture](docs/02-architecture.md) | 分层架构、模块边界、关键数据流与时序 |
| [03-data-model](docs/03-data-model.md) | Point-in-Time 数据模型与完整 DDL |
| [04-data-sources](docs/04-data-sources.md) | 数据源清单、采集调度、质量校验规则 |
| [05-market-config](docs/05-market-config.md) | 多市场配置规范，A 股 / 美股差异矩阵 |
| [06-agent-design](docs/06-agent-design.md) | Agent 角色定义、工具契约、输出 Schema |
| [07-quant-engine](docs/07-quant-engine.md) | 因子库、模型演进路径、预测目标定义 |
| [08-backtest-eval](docs/08-backtest-eval.md) | 回测引擎规范、防偏差清单、Shadow Portfolio |
| [09-portfolio-risk](docs/09-portfolio-risk.md) | 组合构建方法与风控规则全表 |
| [10-execution](docs/10-execution.md) | BrokerAdapter 抽象、订单生命周期、对账 |
| [13-repo-layout](docs/13-repo-layout.md) | 目录结构、命名与工程约定 |
| [14-risk-register](docs/14-risk-register.md) | 风险登记册与缓解措施 |
| [15-monitoring-alerts](docs/15-monitoring-alerts.md) | 持仓监控、触发器、三级漏斗、推送 |
| [16-token-economics](docs/16-token-economics.md) | Token 成本控制与预算执行 |
| [17-knowledge-base](docs/17-knowledge-base.md) | 知识库准入标准、RAG 的 PIT 约束 |

### 架构决策记录

[docs/adr/](docs/adr/) — 记录"为什么这样选"，避免半年后重复讨论。

### 参考资料

- [architecture-draft](docs/architecture-draft.md) — 初版架构草案（外部输入，已格式化）
- [review](docs/review.md) — 对草案的评审意见

## 六条不可协商的原则

这六条如果被破坏，项目就失去意义。任何 PR 违反其中之一都应被拒绝。

1. **Risk Engine 的判定不可被 LLM 覆盖。** 风控是确定性代码，不是 prompt。
2. **所有历史数据查询必须走 `as_of(t)` 接口。** 禁止在研究/回测代码中直接查询最新值。
3. **LLM 不得直接调用下单接口。** 路径固定为 Proposal → Risk → Execution。
4. **实盘开关默认关闭，且需独立配置 + 显式确认。** 默认 dry-run。
5. **每个决策必须可追溯到证据与数据版本。** 无法追溯的决策视为无效。
6. **监控的规则层必须零 LLM 成本，且在预算耗尽时仍能工作。** 止损、跌停、停牌、组合回撤告警不依赖 LLM。

## 快速上手（P0 完成后可用）

```bash
# 启动基础设施
docker compose up -d

# 初始化数据库
make db-init

# 拉取 MVP 股票池数据
make ingest-universe

# 跑基准回测
make backtest-baseline
```

## 许可与免责

本项目为个人研究用途。系统输出不构成投资建议。使用者自行承担全部投资风险。
