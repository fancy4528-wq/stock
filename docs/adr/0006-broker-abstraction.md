# ADR-0006: BrokerAdapter 抽象与 SimulatedBroker 先行

- 状态: 已接受
- 日期: 2026-08-31
- 相关: [10-execution](../10-execution.md), [05-market-config](../05-market-config.md)

## 背景

系统要经历多个执行阶段：

```
P0-P5  A 股，无交易 API（研究 + 建议）
P6     美股 Paper（Alpaca）
P7a    美股实盘
P7b    A 股实盘（QMT，待权限）
```

四个阶段的券商接口完全不同。且 A 股阶段根本没有 API 可接。

## 决策

**定义 `BrokerAdapter` 抽象接口，业务代码只依赖抽象。`SimulatedBroker` 从 P0 就实现。**

```python
class BrokerAdapter(ABC):
    market: str
    is_live: bool

    async def get_account(self) -> AccountInfo: ...
    async def get_positions(self) -> list[BrokerPosition]: ...
    async def place_order(self, req: OrderRequest) -> OrderAck: ...
    async def cancel_order(self, client_order_id: str) -> CancelAck: ...
    async def get_order(self, client_order_id: str) -> BrokerOrderState: ...
    async def is_market_open(self) -> bool: ...
    def capabilities(self) -> BrokerCapabilities: ...   # ★ 能力声明
```

实现：

| Adapter | 阶段 |
|---|---|
| `SimulatedBroker` | **P0** |
| `AlpacaAdapter` | P6 |
| `IBKRAdapter` | P7（备选） |
| `QMTAdapter` | P7b-1（模拟）/ P7b-2（实盘） |

## 理由

**SimulatedBroker 不是临时替代品，而是长期核心组件。** 它有四个用途：

| 用途 | 说明 |
|---|---|
| 回测撮合 | 含 T+1、涨跌停、停牌、成交量约束 |
| Shadow Portfolio | A 股阶段的实际执行器 |
| 单元测试 | 所有执行层测试的基础 |
| 故障注入 | 模拟超时、部分成交、拒单，测试异常路径 |

所以它必须在 P0 就有，且要做得完整。

**但它的撮合规则是假设，不是事实。** `SimulatedBroker` 里的涨停不可买入、成交量上限、集合竞价优先级都是推断，从未被真实撮合验证。这是它作为"长期核心组件"的代价——**全部回测结论都建立在这些假设上**。校准方案见 [ADR-0012](0012-cn-simulated-trading.md)。

**`capabilities()` 而非 `if broker == "xxx"`。** 不同券商能力不同（碎股支持、订单类型、幂等性）。通过能力查询适配，而非硬编码券商判断。这样新增券商不需要改上层代码。

**幂等性必须在本地保证。** 券商原生幂等性不可依赖。设计上：
- `client_order_id` 确定性生成（重跑得到相同 ID）
- 数据库唯一约束
- Redis 短期锁防并发
- 超时不重试，标记 `unknown` 后查询确认

**`is_live` 标记显式化。** 实盘与模拟的区别必须在类型层面可见，配合三重开关（配置文件 + 环境变量 + 会话确认）。

## 被否决的方案

| 方案 | 否决理由 |
|---|---|
| A 股阶段不做执行层，P6 再建 | Shadow Portfolio 需要撮合逻辑；回测也需要。等于必须做 |
| 直接依赖 Alpaca SDK，后期再抽象 | 后期抽象要改遍所有调用点；且 A 股阶段无 Alpaca |
| 用 `if market == "CN"` 分支处理差异 | 加市场要改代码；且逻辑散落各处 |
| 每个券商一套独立的执行流程 | 重复代码，风控和订单管理逻辑会分叉 |
| SimulatedBroker 只做简单撮合，回测另写一套 | 两套撮合逻辑会不一致，回测与 Shadow 结果无法对比 |

## 后果

**正面**：
- 换券商只需新增 Adapter，上层零改动
- A 股阶段的 Shadow Portfolio 与后续实盘走同一条路径
- 故障注入使异常路径可测
- 回测与 Shadow 用同一撮合逻辑，结果可对比
- 幂等保护统一实现，不依赖各券商差异

**负面**：
- P0 就要设计完整接口（需要预见 P6/P7 的需求）
- 抽象可能不完全贴合某个具体券商（需 `capabilities` 兜底）
- `SimulatedBroker` 要实现完整的市场约束，工作量不小

**已知的适配挑战**：QMT 可能需要 Windows 环境运行，与 Docker 部署冲突。方案是把 `QMTAdapter` 做成独立服务，主系统通过 HTTP/gRPC 调用。这不影响抽象层设计。

## 接口设计的取舍

选择了**较小的接口面**：只有 7 个方法，不包含流式行情订阅、复杂订单类型（冰山单、算法单）、期权链查询。

理由：我们的策略是日频、市价/限价单、股票 only。加入用不到的接口会增加实现负担。若将来需要，可扩展。

## 复审条件

- 若需要盘中实时行情推送 → 需扩展接口（订阅机制）
- 若需要复杂订单类型 → 扩展 `OrderRequest`
- 若某券商能力差异无法用 `capabilities` 表达 → 重新审视抽象
