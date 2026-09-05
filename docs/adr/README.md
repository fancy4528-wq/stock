# 架构决策记录（ADR）

## 目的

记录"为什么这样选"，包括被否决的方案及原因。避免半年后重复讨论已经决定的问题。

## 格式

```markdown
# ADR-NNNN: 标题

- 状态: 提议 | 已接受 | 已废弃 | 被 ADR-XXXX 取代
- 日期: YYYY-MM-DD
- 相关: docs/xx-yyy.md

## 背景
什么问题需要决策，约束条件是什么。

## 决策
选择了什么。

## 理由
为什么这样选。

## 被否决的方案
| 方案 | 否决理由 |

## 后果
正面 / 负面 / 需要接受的代价。

## 复审条件
什么情况下应重新考虑这个决策。
```

## 约定

- ADR 一旦"已接受"就不再修改。需变更时新建 ADR 并标注 supersedes。
- 编号连续，不复用。
- 以下变更必须先写 ADR：数据模型 PIT 机制、分层依赖、新增外部依赖、风控规则增删、模型演进路径偏离。

## 索引

| # | 标题 | 状态 |
|---|---|---|
| [0001](0001-pit-data-model.md) | 采用 Point-in-Time 数据模型 | 已接受 |
| [0002](0002-single-postgres.md) | 使用单一 PostgreSQL 而非多数据库 | 已接受 |
| [0003](0003-no-agent-framework.md) | 不使用 LangChain 等 Agent 框架 | 已接受 |
| [0004](0004-custom-backtest.md) | 自建回测引擎 | 已接受 |
| [0005](0005-model-progression.md) | 强制模型演进顺序 | 已接受 |
| [0006](0006-broker-abstraction.md) | BrokerAdapter 抽象与 SimulatedBroker 先行 | 已接受 |
| [0007](0007-risk-not-agent.md) | 风控是确定性代码，不做成 Agent | 已接受 |
| [0008](0008-cn-first-us-later.md) | A 股先行，美股后移植 | 已接受 |
| [0009](0009-monitor-three-tier-funnel.md) | 监控采用三级漏斗，规则层零 LLM 成本 | 已接受 |
| [0010](0010-budget-allocation.md) | 分项预算与调用前拦截 | 已接受 |
| [0011](0011-no-general-finance-kb.md) | 不建通用金融知识库，只沉淀自有判断历史 | 已接受 |
| [0012](0012-cn-simulated-trading.md) | A 股模拟盘的取舍与撮合假设校准 | 已接受 |
| [0013](0013-cold-start-portfolio.md) | 冷启动建仓推荐：复用组合管道，强制分批与成绩单 | 已接受 |
| [0014](0014-user-configurable-exit-policy.md) | 止盈止损：用户可配阈值 + 系统兜底地板 | 已接受 |
| [0015](0015-investable-adjustment.md) | 投入额调整建议：被动响应默认开，主动推送默认关 | 已接受 |
