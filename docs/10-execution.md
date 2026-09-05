# 10 — 执行层

## 1. 设计目标

| 目标 | 说明 |
|---|---|
| 券商可替换 | 业务代码不出现任何券商 SDK |
| 幂等 | 网络重试不产生重复订单 |
| 可对账 | 本地状态与券商状态可比对 |
| 默认安全 | 实盘开关默认关闭，需独立配置 + 显式确认 |
| 异常可测 | 所有失败路径有测试覆盖 |

## 2. BrokerAdapter 抽象

### 2.1 接口定义

```python
from abc import ABC, abstractmethod

class BrokerAdapter(ABC):
    """所有券商实现此接口。业务代码只依赖此抽象。"""

    market: str
    is_live: bool          # ★ 实盘标记

    # ── 账户 ──
    @abstractmethod
    async def get_account(self) -> AccountInfo: ...

    @abstractmethod
    async def get_positions(self) -> list[BrokerPosition]: ...

    # ── 订单 ──
    @abstractmethod
    async def place_order(self, req: OrderRequest) -> OrderAck:
        """必须幂等：相同 client_order_id 重复调用不产生新订单。"""

    @abstractmethod
    async def cancel_order(self, client_order_id: str) -> CancelAck: ...

    @abstractmethod
    async def get_order(self, client_order_id: str) -> BrokerOrderState: ...

    @abstractmethod
    async def list_orders(self, *, since: datetime | None = None
                          ) -> list[BrokerOrderState]: ...

    # ── 市场状态 ──
    @abstractmethod
    async def is_market_open(self) -> bool: ...

    # ── 能力声明 ──
    @abstractmethod
    def capabilities(self) -> BrokerCapabilities: ...
```

### 2.2 数据契约

```python
class OrderRequest(BaseModel):
    client_order_id: str = Field(description="★ 幂等键，由本地生成")
    symbol: str
    side: Literal["buy", "sell"]
    quantity: float
    order_type: Literal["market", "limit"]
    limit_price: float | None = None
    time_in_force: Literal["day", "gtc", "ioc"] = "day"

class OrderAck(BaseModel):
    client_order_id: str
    broker_order_id: str | None
    accepted: bool
    reject_reason: str | None = None
    is_duplicate: bool = False       # ★ 幂等命中标记

class BrokerCapabilities(BaseModel):
    """能力声明。上层据此调整行为，而非 if broker == 'xxx'。"""
    supports_limit_order: bool
    supports_fractional: bool
    supports_short: bool
    supports_cancel: bool
    supports_partial_fill: bool
    min_order_value: float | None
    max_order_value: float | None
    idempotent_place_order: bool     # 券商原生是否幂等
```

`capabilities()` 的作用：QMT 与 Alpaca 能力不同（如碎股支持），上层通过能力查询适配，而不是硬编码券商判断。

### 2.3 幂等实现

券商原生幂等性不可依赖，本地必须自己保证。

```python
class IdempotencyGuard:
    """下单前登记，防止重复提交。"""

    async def place_once(
        self, req: OrderRequest, place_fn: Callable
    ) -> OrderAck:
        # ① 本地 DB 唯一约束（client_order_id UNIQUE）
        existing = await self._db.get_order(req.client_order_id)
        if existing:
            return OrderAck(
                client_order_id=req.client_order_id,
                broker_order_id=existing.broker_order_id,
                accepted=existing.status != "rejected",
                is_duplicate=True,
            )

        # ② Redis 短期锁（防并发）
        lock_key = f"order:lock:{req.client_order_id}"
        if not await self._redis.set(lock_key, b"1", nx=True, ex=60):
            raise DuplicateOrderInFlight(req.client_order_id)

        # ③ 先落库（状态 submitting）再发送
        await self._db.insert_order(req, status="submitting")
        try:
            ack = await place_fn(req)
            await self._db.update_order(req.client_order_id, ack)
            return ack
        except TimeoutError:
            # ★ 超时不等于失败，订单可能已到券商
            await self._db.update_order(req.client_order_id, status="unknown")
            raise OrderStateUnknown(req.client_order_id)
```

**超时处理是最容易出错的地方。** 下单超时后不能重试（可能已成交），必须标记 `unknown` 并通过查询订单状态确认。

### 2.4 client_order_id 生成

```python
def make_client_order_id(run_id: str, symbol: str, side: str, seq: int) -> str:
    """确定性生成，同一决策重跑得到相同 ID → 天然幂等。"""
    return f"{run_id}-{symbol.replace('.', '')}-{side[0].upper()}-{seq:03d}"
    # 例: 20260901-cn-daily-600519SH-B-001
```

确定性生成的好处：如果流程崩溃后重跑，生成的 ID 相同，幂等检查会命中，不会重复下单。

## 3. 实现清单

| Adapter | 市场 | 阶段 | 说明 |
|---|---|---|---|
| `SimulatedBroker` | 全部 | **P0** | 回测撮合 + Shadow Portfolio |
| `AlpacaAdapter` | 美股 | P6 | Paper → 实盘 |
| `IBKRAdapter` | 美股/港股 | P7（备选） | ib_insync |
| `QMTAdapter` | A 股 | P7b-1 模拟 / P7b-2 实盘 | xtquant |

### 3.0 "模拟盘"的三种含义 —— 不要混为一谈

| | 免费模拟炒股 | `SimulatedBroker`（自建） | 券商模拟交易环境 |
|---|---|---|---|
| 例子 | 同花顺/东财模拟炒股 | 本项目组件 | QMT / PTrade 模拟 |
| 有 API | **否**（只能手工点） | 是（自己的） | **是**（与实盘同接口） |
| 撮合真实度 | 低（多数报价即成交） | 取决于我的假设 | 接近实盘 |
| 验证券商 API 交互 | 否 | **否** | **是** |
| 验证撮合假设 | 否 | 否（它就是假设本身） | **是** |
| 对本项目价值 | **几乎没有** | 核心组件 | P7b 前必须 |

**免费模拟炒股不但没用，还有害。** 撮合过松会让你以为涨停能买进、大单没有滑点，产生虚假信心。而它无 API，验证不了程序化链路——这恰恰是唯一需要验证的东西。

**`SimulatedBroker` 已覆盖了除券商 API 之外的全部链路**（见 [ADR-0008](adr/0008-cn-first-us-later.md)：A 股阶段的 Shadow Portfolio 本质上就是 Paper Trading）。它甚至比免费模拟盘更严格——强制检查涨跌停不可成交、T+1、停牌，并记录未执行项。

剩下没验证的只有两件事，都只能靠券商模拟环境：

| 未验证项 | 为什么自建模拟器做不到 |
|---|---|
| 券商 API 交互 | 订单状态机、拒单码、部分成交、撤单竞态、断线重连、对账差异 —— **你只能模拟你以为的行为** |
| 撮合假设本身 | `SimulatedBroker` 就是假设的实现，用它验证自己是循环论证 |

详见 3.4 节和 [ADR-0012](adr/0012-cn-simulated-trading.md)。

### 3.1 SimulatedBroker 从 P0 就要有

它不是"临时替代品"，而是长期核心组件：

| 用途 | 说明 |
|---|---|
| 回测撮合 | 含 T+1、涨跌停、停牌、成交量约束 |
| Shadow Portfolio | A 股阶段的主要执行器 |
| 单元测试 | 所有执行层测试的基础 |
| 异常注入 | 模拟超时、部分成交、拒单 |

```python
class SimulatedBroker(BrokerAdapter):
    is_live = False

    def __init__(
        self,
        market_cfg: MarketConfig,
        repo: PITRepository,
        *,
        fault_injection: FaultConfig | None = None,   # ★ 异常注入
    ): ...

class FaultConfig(BaseModel):
    """故障注入配置，用于测试异常路径。"""
    timeout_rate: float = 0.0
    reject_rate: float = 0.0
    partial_fill_rate: float = 0.0
    duplicate_ack_rate: float = 0.0
    stale_position_rate: float = 0.0
```

### 3.2 AlpacaAdapter 要点

| 项 | 说明 |
|---|---|
| Paper / Live 用不同 base URL | 配置区分，`is_live` 标记必须正确 |
| 幂等 | Alpaca 支持 `client_order_id`，但本地仍需 guard |
| 碎股 | `capabilities.supports_fractional = True` |
| 数据档位 | 免费档为 IEX 数据，与全市场价格有差异，需记录 |
| PDT | 账户 < $25k 有日内交易限制，风控层处理 |

### 3.3 QMTAdapter 要点（待权限）

| 项 | 说明 |
|---|---|
| 非 REST | 需运行 QMT 客户端，Python 通过 xtquant 连接 |
| 部署约束 | 通常需 Windows 环境，与 Docker 部署不兼容 → 可能需要独立进程 + IPC |
| 幂等 | 需自行确认 xtquant 的重复提交行为 |
| 权限门槛 | 需券商开通量化交易权限，门槛因券商而异，**需逐家咨询确认** |
| **模拟环境门槛** | ★ **需核实**：模拟交易环境的准入是否低于实盘量化权限 |
| 合规 | 程序化交易需事前报告，具体要求以监管文件和券商要求为准 |

架构预留：QMT 若必须在 Windows 运行，则 `QMTAdapter` 作为独立服务，主系统通过 HTTP/gRPC 调用。这不影响抽象层设计。

**`QMTAdapter` 是整个项目工程风险最高的组件**：Windows 进程约束、IPC 通信、公开文档少、xtquant 行为需自行摸索。因此它**必须先在模拟环境跑熟**，见 P7b-1。

#### 若模拟环境门槛较低，路线可显著改善

这一项待核实，但影响很大：

```
现状假设（模拟与实盘同门槛）：
  P0-P5 研究 → P6 美股 Paper → P7b QMTAdapter 首次上线即接实盘  ⚠️ 风险集中

若模拟环境门槛较低：
  P0-P5 研究 ─┬─ P6 美股 Paper → P7b-2 实盘
              └─(并行) QMT 模拟环境验证 QMTAdapter
                        ↑ 等权限达成时，是"已验证组件接实盘"而非"新代码接实盘"
```

**这是把工程风险从关键路径上挪走的机会。** 值得优先向券商核实。

### 3.4 撮合假设校准 —— 最容易被忽略的一环

`SimulatedBroker` 里有一批**假设**，而回测和 Shadow Portfolio 的全部结论都建立在它们之上：

| 假设 | 依据 | 是否被真实撮合验证过 |
|---|---|---|
| 涨停价不可买入 | 常识推断 | **否** |
| 跌停价不可卖出 | 常识推断 | **否** |
| 停牌期间订单被拒 | 常识推断 | **否** |
| 成交量上限（单笔不超过当日成交量 X%） | 经验取值 | **否** |
| 集合竞价的成交价与优先级 | 规则文档 | **否** |
| 部分成交的剩余处理 | 自行设计 | **否** |
| 市价单的实际成交价范围 | 滑点模型假设 | **否** |
| **新股有效申报价格范围外→废单** | 交易所规则（已核实） | **否** |
| **零股（不足一手）必须一次性全部卖出，不可分批** | 交易所规则（已核实） | **否** |

**单元测试只能验证代码符合我的假设，无法验证假设符合现实。**

这是 R-04 的残余风险。唯一的解法是拿真实撮合结果做对比。

#### 校准方法

```
同一组订单
    ├──▶ SimulatedBroker        → fills_sim
    └──▶ 券商模拟交易环境        → fills_real
                                      ↓
                              逐项对比，记录偏差
```

```python
# tests/calibration/test_matching_assumptions.py
class MatchingCalibration(BaseModel):
    """撮合假设校准记录。每次校准产出一条，append-only。"""
    calibrated_at: date
    broker: str                       # 'qmt_sim' | 'ptrade_sim'
    n_orders: int

    # 逐项假设的验证结果
    limit_up_rejected: bool | None     # None = 未覆盖该场景
    limit_down_rejected: bool | None
    suspended_rejected: bool | None

    # 数值偏差
    fill_price_mae: float              # 成交价平均绝对误差
    fill_qty_match_rate: float         # 成交量一致率
    partial_fill_behavior_match: bool

    # 未覆盖的场景（诚实记录）
    uncovered_scenarios: list[str]
    notes: str
```

#### 校准的最低要求

| 项 | 要求 |
|---|---|
| 订单样本 | ≥ 200 笔，覆盖买/卖、限价/市价 |
| 涨跌停场景 | ≥ 5 次真实涨跌停订单尝试 |
| 停牌场景 | ≥ 1 次（可能需等待时机） |
| 新股前 5 日无涨跌幅 + 临时停牌 | ≥ 1 次（若参与新股，需验证停牌/废单行为） |
| 有效申报价格范围（主板新股 144%/64%、尾盘 120%/80%） | 至少构造 1 次越界申报，确认废单 |
| 时段覆盖 | 集合竞价、连续竞价、尾盘 |
| 成交价偏差 | MAE 记录并写入报告，**不设通过门槛**（目的是知道偏差多大，不是让它变小） |

**为什么不设门槛**：如果偏差大，正确动作是**修正 `SimulatedBroker` 的假设**，然后重跑历史回测看结论是否改变。设个门槛然后调参数去满足它，等于把校准变成过拟合。

#### 校准结果的处理

```
偏差小（成交价 MAE < 0.5%，涨跌停行为一致）
    → 记录，继续
偏差大（某项假设完全错误）
    → 修正 SimulatedBroker
    → ★ 重跑全部历史回测
    → 对比结论是否改变
    → 若结论翻转，说明此前的全部评估无效
```

最后一条是这件事真正的价值：**它可能推翻已有结论。** 越晚做，需要推翻的越多。

#### 何时做

| 时机 | 说明 |
|---|---|
| 一旦模拟环境可得 | 不必等到 P7b。越早越好 |
| P7b 前 | **必须完成**，是 Gate 7b 的硬条件 |
| 每次修改撮合逻辑后 | 回归校准 |

**这个测试很便宜，价值很高。** 它是唯一能证伪撮合假设的手段。

## 4. 订单生命周期

### 4.1 状态机

```
                  ┌──────────┐
                  │ proposed │  ← PortfolioEngine 产出
                  └────┬─────┘
                       │ RiskEngine.check()
            ┌──────────┴──────────┐
            ▼                     ▼
   ┌────────────────┐    ┌───────────────┐
   │ risk_approved  │    │ risk_rejected │ (终态)
   └───────┬────────┘    └───────────────┘
           │ 检查 kill switch / 实盘开关
           ▼
   ┌───────────────┐
   │  submitting   │  ← 已落库，未确认
   └───────┬───────┘
           │ place_order()
     ┌─────┼─────────┬──────────┐
     ▼     ▼         ▼          ▼
┌─────────┐ ┌──────┐ ┌────────┐ ┌─────────┐
│submitted│ │unknown│ │rejected│ │duplicate│
└────┬────┘ └───┬──┘ └────────┘ └─────────┘
     │          │ 查询确认
     │          └──────┐
     ▼                 ▼
┌─────────┐      (回到 submitted / rejected)
│ partial │
└────┬────┘
     ▼
┌─────────┐  ┌───────────┐  ┌─────────┐
│ filled  │  │ cancelled │  │ expired │  (终态)
└─────────┘  └───────────┘  └─────────┘
```

`unknown` 状态是关键设计：网络超时后订单状态不明，必须通过查询确认，不能假设失败。

### 4.2 状态转移约束

```python
VALID_TRANSITIONS = {
    "proposed":      {"risk_approved", "risk_rejected"},
    "risk_approved": {"submitting"},
    "submitting":    {"submitted", "rejected", "unknown", "duplicate"},
    "unknown":       {"submitted", "partial", "filled", "rejected", "cancelled"},
    "submitted":     {"partial", "filled", "cancelled", "expired", "rejected"},
    "partial":       {"filled", "cancelled", "expired"},
    # 终态无出边
    "filled": set(), "cancelled": set(), "expired": set(),
    "rejected": set(), "risk_rejected": set(), "duplicate": set(),
}

def transition(order: Order, new_status: str) -> None:
    if new_status not in VALID_TRANSITIONS[order.status]:
        raise InvalidTransition(f"{order.status} → {new_status}")
```

非法转移抛异常而非静默忽略。状态机违规通常意味着并发 bug。

## 5. 实盘安全机制

### 5.1 三重开关

实盘必须同时满足三个条件才能下真单：

```python
class LiveTradingGuard:
    def assert_can_trade_live(self) -> None:
        # ① 配置文件独立开关（不在主配置里）
        if not self._live_cfg_exists():
            raise LiveTradingDisabled("config/live_enabled.yaml 不存在")

        # ② 环境变量
        if os.getenv("QUANTAGENT_LIVE") != "1":
            raise LiveTradingDisabled("QUANTAGENT_LIVE != 1")

        # ③ 启动时的显式确认（记录到审计日志）
        if not self._confirmation_valid():
            raise LiveTradingDisabled("未完成本次会话的实盘确认")

        # ④ Kill switch 未触发
        if self._kill_switch.is_halted():
            raise SystemHalted(self._kill_switch.reason())
```

设计理由：单一开关容易误开。三个独立机制（文件 + 环境变量 + 会话确认）使误触发概率极低。

### 5.2 dry-run 默认

```python
class ExecutionConfig(BaseModel):
    mode: Literal["dry_run", "paper", "live"] = "dry_run"   # ★ 默认
    require_human_approval: bool = True                      # ★ 默认
    max_order_value: float                                   # 单笔上限
    max_daily_order_count: int
    max_daily_notional: float                                # 单日总金额上限
```

`dry_run` 模式：完整走流程但不调用券商，只记录"本应下什么单"。用于验证流程正确性。

### 5.3 人工确认闸门（P7 初期）

```python
async def submit_with_approval(orders: list[OrderRequest]) -> None:
    """P7 初期：所有实盘订单需人工确认。"""
    print(format_order_summary(orders))
    print(f"\n总金额: {total(orders):,.2f}  笔数: {len(orders)}")
    confirm = input("输入 'CONFIRM' 执行，其他任意键取消: ")
    if confirm != "CONFIRM":
        await log_rejection("human_declined", orders)
        return
    await execute(orders)
```

自动化程度提升路径：

```
P7 初期  全部人工确认
   ↓  连续 1 个月无异常
P7 中期  小额自动 + 大额人工确认
   ↓  连续 3 个月无异常
P7 后期  全自动 + 异常告警
```

## 6. 对账（Reconciliation）

### 6.1 为什么必须有

本地状态与券商状态会不一致：网络中断、部分成交未回报、券商侧手动操作、分红送股导致的份额变化。

不对账的后果：基于错误的持仓做决策，可能超买或卖出不存在的股票。

### 6.2 对账流程

```python
class Reconciler:
    async def reconcile(self, account_id: int, as_of: date) -> ReconResult:
        local  = await self._db.get_positions(account_id, as_of)
        broker = await self._broker.get_positions()

        diffs = []
        for sym in set(local) | set(broker):
            l, b = local.get(sym), broker.get(sym)
            if l is None:
                diffs.append(Diff(sym, "missing_local", None, b.qty))
            elif b is None:
                diffs.append(Diff(sym, "missing_broker", l.qty, None))
            elif abs(l.qty - b.qty) > TOLERANCE:
                diffs.append(Diff(sym, "qty_mismatch", l.qty, b.qty))

        # 现金
        if abs(local_cash - broker_cash) > CASH_TOLERANCE:
            diffs.append(Diff("CASH", "cash_mismatch", local_cash, broker_cash))

        result = ReconResult(
            status="matched" if not diffs else "mismatch", diffs=diffs
        )
        await self._persist(result)

        if diffs:
            # ★ 不一致时停止交易，需人工处理
            await self._kill_switch.halt(
                reason=f"对账不一致: {len(diffs)} 项", triggered_by="reconciler"
            )
        return result
```

### 6.3 对账时机

| 时机 | 说明 |
|---|---|
| 每日开盘前 | 确认隔夜状态一致 |
| 每日收盘后 | 确认当日交易全部反映 |
| 每次下单前 | 快速检查（仅关键标的） |
| 异常后 | 超时、断连恢复后强制对账 |

### 6.4 差异处理原则

| 差异 | 处理 |
|---|---|
| 券商多、本地无 | 以券商为准，补记本地，查明来源 |
| 本地多、券商无 | 以券商为准，检查是否有未回报的成交 |
| 数量不一致 | 以券商为准，查订单流水定位 |
| 现金不一致 | 检查费用计算、分红、利息 |

**统一原则：券商是真相来源（source of truth）。** 本地记录只是副本。

## 7. 异常路径清单

P6 Gate 要求全部覆盖测试。

| # | 异常 | 期望行为 |
|---|---|---|
| 1 | 下单超时 | 标记 `unknown`，查询确认，不重试 |
| 2 | 下单被拒 | 记录原因，不重试，继续其他订单 |
| 3 | 重复提交同一 client_order_id | 幂等返回原订单，不新建 |
| 4 | 部分成交 | 正确更新持仓，剩余可撤单 |
| 5 | 部分成交后收盘 | 订单转 `expired`，持仓按已成交计 |
| 6 | 市场未开盘时下单 | 拒绝或排队（按 capabilities） |
| 7 | 券商连接断开 | 重连，重连后强制对账 |
| 8 | 券商返回未知订单状态 | 标记 `unknown`，人工介入 |
| 9 | 持仓不一致 | 触发 kill switch，停止交易 |
| 10 | 现金不足 | 下单前校验拦截；若券商拒绝则记录 |
| 11 | 标的停牌/退市 | 下单前拦截 |
| 12 | 涨跌停无法成交（A 股） | 记录未执行原因 |
| 13 | 撤单失败（已成交） | 查询确认最终状态 |
| 14 | 同一标的重复下单 | 幂等 + 一致性检查拦截 |
| 15 | Kill switch 触发时有在途订单 | 尝试撤单，记录结果 |
| 16 | 数据源故障导致无价格 | 拒绝下单 |
| 17 | 券商 API 限频 | 退避重试，不丢单 |
| 18 | 时钟偏差 | 用券商时间为准做时段判断 |
| 19 | 分红/送股导致份额变化 | 对账识别，更新本地 |
| 20 | 流程中途崩溃 | 重启后按 `client_order_id` 幂等恢复 |

### 7.1 故障注入测试

```python
@pytest.mark.parametrize("fault", [
    FaultConfig(timeout_rate=1.0),
    FaultConfig(reject_rate=1.0),
    FaultConfig(partial_fill_rate=1.0),
    FaultConfig(duplicate_ack_rate=1.0),
])
async def test_execution_survives_faults(fault):
    broker = SimulatedBroker(cfg, repo, fault_injection=fault)
    result = await OrderManager(broker).execute(orders)
    # 关键断言：无论何种故障，本地状态必须自洽
    assert_state_consistent(result)
    assert no_duplicate_orders(result)
```

## 8. OrderManager

```python
class OrderManager:
    async def execute(
        self, risk_result: RiskResult, state: PortfolioState, *, as_of: date,
    ) -> ExecutionResult:
        if risk_result.decision == REJECT:
            return ExecutionResult.rejected(risk_result)

        self._live_guard.assert_can_trade_live() if self._cfg.mode == "live" else None

        # 目标权重 → 订单
        orders = self._diff_to_orders(risk_result.final_target, state, as_of)

        # 排序：先卖后买（释放现金）
        orders.sort(key=lambda o: 0 if o.side == "sell" else 1)

        # 逐笔提交（幂等保护）
        results = []
        for o in orders:
            if self._kill_switch.is_halted():
                break
            results.append(await self._submit_one(o))

        return ExecutionResult(orders=results, ...)
```

**先卖后买**是必要的：卖出释放现金后才有资金买入。A 股 T+1 下，卖出资金当日可用于买入（T+0 资金可用），但要确认券商规则。

## 9. 配置

```yaml
# config/execution/cn_shadow.yaml
mode: "dry_run"
broker: "simulated"
account_code: "shadow_cn"
require_human_approval: false     # shadow 不需要
limits:
  max_order_value: 100000
  max_daily_order_count: 20
  max_daily_notional: 500000
```

```yaml
# config/execution/us_paper.yaml
mode: "paper"
broker: "alpaca"
account_code: "paper_us"
require_human_approval: false
credentials_env_prefix: "ALPACA_PAPER"
limits:
  max_order_value: 5000
  max_daily_order_count: 30
  max_daily_notional: 50000
```

```yaml
# config/live_enabled.yaml   ← ★ 此文件存在才允许实盘
# 且需 QUANTAGENT_LIVE=1 环境变量 + 会话确认
enabled_accounts:
  - "live_us"
max_total_notional_per_day: 20000
require_human_approval: true      # 实盘初期必须 true
```

凭据管理：只从环境变量读，不入配置文件，`.env` 加入 `.gitignore`。

## 10. 验收清单

Gate 5（P6 前）：

- [ ] `BrokerAdapter` 抽象定义完成
- [ ] `SimulatedBroker` 实现含全部 A 股约束
- [ ] 故障注入配置可用
- [ ] 幂等保护：本地 DB 唯一约束 + Redis 锁
- [ ] `client_order_id` 确定性生成
- [ ] 状态机转移校验生效
- [ ] 20 项异常路径全部有测试
- [ ] 对账逻辑实现，不一致触发 halt

Gate 6（P7a 前，美股实盘）：

- [ ] `AlpacaAdapter` 通过全部异常测试
- [ ] Paper trading 连续运行 1 个月无状态不一致
- [ ] 三重实盘开关生效（有测试验证默认关闭）
- [ ] 人工确认闸门可用
- [ ] Kill switch 可自动/手动触发
- [ ] 审计日志完整（每笔订单可追溯到决策）
- [ ] 凭据不出现在代码/配置/日志中

Gate 7b（P7b-2 前，A 股实盘）：

与 Gate 6 对称——**A 股规则比美股复杂，不应有更松的准入。**

- [ ] `QMTAdapter` 在**券商模拟环境**连续运行 ≥ 1 个月
- [ ] 20 项异常路径在真实 API 上验证（非 mock）
- [ ] Windows 进程 + IPC 架构稳定性验证（含进程重启恢复）
- [ ] xtquant 幂等行为已确认并有对应保护
- [ ] **撮合假设校准完成**（≥200 笔订单，见 3.4 节）
- [ ] 校准偏差已记录；若假设有错，`SimulatedBroker` 已修正且历史回测已重跑
- [ ] 对账在真实 API 上跑通
- [ ] 券商量化权限已开通
- [ ] 程序化交易报告已完成
- [ ] 三重实盘开关 + 人工确认闸门（同 Gate 6）
