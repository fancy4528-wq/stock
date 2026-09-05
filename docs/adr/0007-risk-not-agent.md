# ADR-0007: 风控是确定性代码，不做成 Agent

- 状态: 已接受
- 日期: 2026-08-31
- 相关: [09-portfolio-risk](../09-portfolio-risk.md), [02-architecture](../02-architecture.md)

## 背景

原始架构草案中列了一个 `Risk Agent`，与 `Macro Agent`、`Sector Agent` 并列。

同时草案也写了"不要让 LLM 判断风险限制"。这两处存在矛盾。

需要明确：风控到底是 Agent 还是代码。

## 决策

**风控是确定性代码，不做成 Agent。架构中不存在 Risk Agent。**

明确分工：

| 职责 | 承担者 |
|---|---|
| 风险的**识别与解释** | Agent（`StockView.risks`、`RedFlag`、`ChiefAgent` 的不确定性说明） |
| 风险的**判定与执行** | `RiskEngine`（纯规则代码） |

`RiskEngine` 的硬性约束：

```python
class RiskEngine:
    def check(
        self, target: dict[str, float], state: PortfolioState, *, as_of: date,
    ) -> RiskResult:
        """★ 签名中无任何 override / force / bypass 参数"""
```

| 约束 | 说明 |
|---|---|
| 纯函数 | 相同输入必得相同输出 |
| 无网络、无 LLM、无随机数 | 完全确定性 |
| 无 override 参数 | 架构上禁止绕过（有测试保障） |
| 失败保守 | 检查过程异常 → REJECT，不是 APPROVE |
| 全量记录 | 所有触发的规则都落库，即使最终 APPROVE |
| 配置哈希 | 记录 `rule_config_hash` 保证可复现 |
| 不依赖 `agents` 模块 | 有架构测试强制 |

## 理由

**LLM 有幻觉，不能让它决定"这次可以突破风控"。**

风控的价值恰恰在于它不可被说服。如果一个 LLM 能被 prompt 说服放宽限制，那它就不是风控。

**风控必须可回测。** 回测需要精确重放历史决策。LLM 调用不确定（同一输入不同输出），且无法重放历史调用。含 LLM 的风控无法回测。

**风控必须可测试。** 每条规则要有单元测试，还要有属性测试（"输出永不违反 hard 规则"）。这只有确定性代码才可能。

**风控必须可审计。** 出问题时要能回答"为什么这笔单被放过了"。规则代码 + 配置哈希可以精确回答；LLM 的推理过程无法作为审计依据。

**"MODIFY" 不需要智能。** 草案的 Risk Agent 可能是想让它智能地调整仓位。但削减逻辑（clip 到上限、按比例缩放）是简单确定的，不需要 LLM。

## 被否决的方案

| 方案 | 否决理由 |
|---|---|
| Risk Agent 做最终判定 | 无法回测、无法测试、可被幻觉影响 |
| Risk Agent 做建议，代码做判定 | 建议无实际作用（判定不参考它），纯增成本 |
| 风控规则由 LLM 动态生成 | 规则必须稳定可审计，动态生成不可接受 |
| 允许 LLM 在特定情况下 override | 一旦有例外通道，就会被逐渐扩大使用 |
| 用 LLM 解释风控拒绝原因 | 可以做（在报告层），但不在 RiskEngine 内部 |

最后一项需要澄清：**用 LLM 把 `violations` 翻译成人类可读的解释是合理的**，但这发生在 reporting 层，且不影响判定结果。

## 后果

**正面**：
- 风控可完全回测与测试
- 审计链清晰
- 不可被说服
- 相同输入必得相同输出（可复现）

**负面**：
- 规则必须人工维护（无法"学习"）
- 无法处理规则未覆盖的新情况（但这正是想要的保守性）
- 需要写大量测试（09 文档要求 95% 覆盖率）

**必须接受的代价**：风控会拒绝一些实际上没问题的交易。这是刻意的取舍——宁可错过机会，不可失控。

## 配套的架构约束

```python
# tests/test_architecture.py
FORBIDDEN = [
    ("decision.risk", ["agents"]),   # ★ 风控不得依赖 Agent 模块
]

def test_risk_engine_has_no_override_param():
    sig = inspect.signature(RiskEngine.check)
    forbidden = {"force", "override", "bypass", "skip", "ignore_risk"}
    assert not (set(sig.parameters) & forbidden)

def test_risk_engine_deterministic():
    assert engine.check(t, s, as_of=d) == engine.check(t, s, as_of=d)
```

这些测试是架构约束的自动化保障，防止将来有人"临时"加个 override 参数。

## 复审条件

**此决策不设复审条件。** 这是项目五条不可协商原则之一。

若确实需要调整某条风控规则的阈值，改配置文件（`config/risk/*.yaml`）即可，不需要改变"风控是代码"这一架构决策。
