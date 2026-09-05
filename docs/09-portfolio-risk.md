# 09 — 组合构建与风控

## 1. 职责边界

```
Agent 输出 score          →  "这个标的看起来怎样"
SignalFusion              →  "综合各方看法，最终分数是多少"
PortfolioEngine           →  "应该配多少"
RiskEngine                →  "允不允许，要不要削减"
```

**四层都不含 LLM。** 输入是结构化分数，输出是确定性权重。相同输入必须得到相同输出。

## 2. Signal Fusion

### 2.1 输入信号

| 信号 | 来源 | 范围 | 可靠性 |
|---|---|---|---|
| `quant` | Quant 模型 `prob_up_5d` | 0-1 | 可回测验证 |
| `sector` | IndustryAgent / ThemeAgent score | 0-1 | 前向验证中 |
| `stock` | StockAgent score | 0-1 | 前向验证中 |
| `macro_fit` | MacroAgent 的板块影响 | -1~1 → 归一化 | 前向验证中 |
| `news` | 事件影响加权和 | -1~1 → 归一化 | 前向验证中 |

### 2.2 首版：等权（但要知道陷阱）

```python
DEFAULT_WEIGHTS = {
    "quant": 0.20, "sector": 0.20, "stock": 0.20,
    "macro_fit": 0.20, "news": 0.20,
}
```

**陷阱**：这五个信号并非独立。`quant` 的因子里有动量，`sector` 的评分里有板块动量，`stock` 的评分里也参考了价格走势。等权相加可能实际给了价格动量 50%+ 的权重。

应对：
1. `fused_signal.components` 落库，保留各信号原值
2. P4 计算信号相关矩阵，相关性 > 0.7 的合并
3. 相关性检查结果决定是否调整权重

### 2.3 演进路径

| 阶段 | 方法 |
|---|---|
| P3 | 等权 |
| P4 | 基于相关性去冗余，按历史 IC 加权 |
| P5 | 分市场状态的动态权重（regime-dependent） |
| 后续 | 若 Agent IC 证实为 0，将其权重置零，保留解释用途 |

```python
class FusionConfig(BaseModel):
    version: str
    weights: dict[str, float]
    normalize: Literal["zscore", "rank", "minmax"] = "rank"
    missing_signal_policy: Literal["renormalize", "neutral", "exclude"] = "renormalize"
    regime_overrides: dict[str, dict[str, float]] = {}
```

`missing_signal_policy = renormalize`：某信号缺失时（如新闻源故障），剩余权重重新归一化，而不是用中性值 0.5 填充。理由：填充会稀释有效信号。

### 2.4 实现

```python
class SignalFusion:
    def fuse(
        self, signals: dict[str, dict[str, float]], cfg: FusionConfig,
        regime: str | None = None,
    ) -> dict[str, FusedScore]:
        weights = cfg.regime_overrides.get(regime, cfg.weights)
        result = {}
        for symbol in self._all_symbols(signals):
            avail = {k: v[symbol] for k, v in signals.items() if symbol in v}
            if not avail:
                continue
            w = self._renormalize({k: weights[k] for k in avail})
            score = sum(avail[k] * w[k] for k in avail)
            result[symbol] = FusedScore(
                final_score=score,
                components=avail,        # ★ 保留原值供归因
                weights_used=w,
                missing=set(weights) - set(avail),
            )
        return result
```

## 3. Portfolio Engine

### 3.1 Signal ≠ Position

`A 0.91 / B 0.87 / C 0.85` 不意味着各 33%。需要考虑波动率、相关性、流动性、现有持仓。

### 3.2 构建流程

```
FusedScore
    ↓ ① 筛选（硬性排除）
候选池
    ↓ ② 排序取 Top N
入选标的
    ↓ ③ 初始权重（分数加权 / 等权 / 风险平价）
原始权重
    ↓ ④ 波动率调整
调整后权重
    ↓ ⑤ 相关性去冗余
去冗余权重
    ↓ ⑥ 总仓位缩放（regime 决定）
目标权重
    ↓ ⑦ 换手约束（与现有持仓对比）
最终目标权重  →  RiskEngine
```

### 3.3 各步骤规范

**① 筛选（在组合构建前，不在风控）**

```python
EXCLUSION_RULES = [
    "is_suspended",                    # 停牌
    "is_st",                           # ST
    "days_since_ipo < 60",             # 新股
    "avg_amount_20d < min_liquidity",  # 流动性不足
    "in_blacklist",                    # 人工黑名单
    "days_to_earnings <= 3",           # 财报窗口（不新建仓）
    "score is null",                   # 无有效信号
    "board not in user.tradable_boards",  # ★ 用户未开通该板块权限（见 3.3a）
]
```

这些是**组合层筛选**，与风控层的检查不同：组合层是"不考虑"，风控层是"最后拦截"。两层都要有（纵深防御）。

### 3.3a 板块交易权限（eligibility）

A 股部分板块有**开户资金门槛与交易经验要求**，这是硬约束——不是偏好，是"根本下不了单"。

| 板块 | 资金（20 日日均） | 经验 | 风险等级 | 其他 |
|---|---|---|---|---|
| 主板 `main` | 无 | 无 | 基础匹配 | 开户即得 |
| 创业板 `gem` | 10 万 | 24 个月 | C4+ | 知识测评 + 风险揭示书 |
| 科创板 `star` | 50 万 | 24 个月 | C4+ | 知识测评 80 分 + 风险揭示书 |
| 北交所 `bse` | 50 万 | 24 个月 | C4+ | 知识测评 + 风险揭示书 |

> 已核实 2026-09-03，详见 [05-market-config](05-market-config.md) 2.3。资金看申请前 20 日日均资产。

**这个约束比资金量约束更彻底**：资金量约束是"买不满一手"，板块权限是"一股都买不了"。二者是同一类问题（可执行性）的两个维度：

| 维度 | 约束 | 处理 |
|---|---|---|
| 资金量 | 买不起一手 | `EXCLUSION_RULES_COLD_START`（8.3） |
| 板块权限 | 开不了权限 | `EXCLUSION_RULES` 的 `tradable_boards` |

#### 为什么必须是用户声明式配置

A 股阶段无交易 API，系统**无法自动知道用户开通了哪些板块**。所以只能由用户显式声明，且**默认最保守**（仅主板）——默认全开会推荐无法执行的标的，默认全关又过度保守。

```yaml
# config/user/eligibility_cn.yaml
tradable_boards: [main]          # ★ 默认仅主板；star/gem/bse 需用户显式加入
# 加入时 CLI/文档提示对应门槛，提醒"请确认已在券商开通"
```

对应配置对象：

```python
class UserEligibility(BaseModel):
    market: str
    tradable_boards: list[str] = ["main"]     # 默认最保守

    def can_trade(self, board: str) -> bool:
        return board in self.tradable_boards
```

#### 三个行为约定

| 场景 | 行为 |
|---|---|
| **建仓推荐** | 未开通板块的标的**排除**，不出现在清单里 |
| **研究报告** | **保留**这些板块的分析（有信息价值，且用户可能之后开通） |
| **被排除的标的** | 像"因资金量排除"一样**展示**："开通科创板后你还可以考虑：xxx" |

第三条的价值：让用户知道**开通权限能解锁什么**，而不是默默过滤掉。这与 8.3 展示"因资金量排除的标的"是同一设计意图——**排除必须可见**。

研究与推荐的分野是关键：ChiefAgent 的市场分析可以覆盖科创板龙头（它影响整个市场判断），但落到"给你的建仓清单"时必须按 eligibility 过滤。二者用同一份分数，不同的过滤器。

**③ 初始权重方案**

| 方案 | 公式 | 特点 |
|---|---|---|
| 等权 | `1/N` | 最稳健，首版推荐 |
| 分数加权 | `score_i / Σscore` | 集中于高分标的 |
| 分数排序加权 | 按排名线性递减 | 减轻分数噪声影响 |
| 风险平价 | `(1/σ_i) / Σ(1/σ_j)` | 风险均衡 |

**首版用等权。** 理由：分数的绝对值不可靠（Agent score 尤其），排序信息比数值信息可靠。等权只用到"入选/不入选"这一个决策。

**④ 波动率调整**

```python
def vol_adjust(weights: dict[str, float], vols: dict[str, float],
               target_vol: float = 0.20) -> dict[str, float]:
    """按目标波动率缩放。高波动标的降权。"""
    inv_vol = {s: min(target_vol / vols[s], 2.0) for s in weights}   # 上限 2x
    return normalize({s: weights[s] * inv_vol[s] for s in weights})
```

**⑤ 相关性去冗余**

```python
def decorrelate(weights: dict[str, float], corr: pl.DataFrame,
                threshold: float = 0.8) -> dict[str, float]:
    """高相关标的视为一个 cluster，cluster 总权重受限。
    避免「买了 5 只同涨同跌的股票」的假分散。"""
```

A 股尤其需要这一步：同一概念板块内的股票相关性极高，看似 10 个持仓实际是 1 个赌注。

**⑥ 总仓位缩放**

```python
STANCE_TO_EXPOSURE = {
    "aggressive": 0.90, "moderate": 0.70,
    "defensive": 0.50, "cautious": 0.30,
}
```

由 `ChiefAgent.allocation_stance` 映射（注意：Agent 给的是方向词，不是数字；数字由此表决定，这是刻意的边界）。

**⑦ 换手约束**

```python
def limit_turnover(target: dict[str, float], current: dict[str, float],
                   max_turnover: float) -> dict[str, float]:
    """若目标换手超限，按调整幅度优先级部分执行。
    优先执行：卖出（降风险）> 减仓 > 新建仓 > 加仓。"""
```

### 3.4 配置

```yaml
# config/portfolio/cn.yaml
selection:
  top_n: 15
  min_score: 0.55                # 低于此分数不入选，宁可空仓

weighting:
  method: "equal"                # equal | score | rank | risk_parity
  vol_adjust: true
  target_vol: 0.20
  vol_cap_multiplier: 2.0

decorrelation:
  enabled: true
  corr_threshold: 0.80
  max_cluster_weight: 0.35

exposure:
  stance_map:
    aggressive: 0.90
    moderate: 0.70
    defensive: 0.50
    cautious: 0.30
  min_cash: 0.10

rebalance:
  frequency: "weekly"            # daily | weekly | monthly
  day_of_week: 1                 # 周一
  drift_threshold: 0.05          # 偏离超 5% 触发临时再平衡
  max_turnover_per_rebalance: 0.30
```

`min_score` 的意义：允许空仓。如果所有标的分数都低，正确的动作是不买，而不是买"相对最好的"。

## 4. Risk Engine

### 4.1 不可协商的设计

| 约定 | 说明 |
|---|---|
| **纯函数** | 无网络、无 LLM、无随机数、无 IO（配置在构造时注入） |
| **无 override 参数** | 接口签名里根本没有 `force` / `bypass` / `skip_check` |
| **全量记录** | 所有触发的规则都记录，即使最终 APPROVE |
| **配置哈希** | 每次检查记录 `rule_config_hash`，保证可复现 |
| **失败保守** | 任何检查异常 → REJECT，不是 APPROVE |

最后一条很重要：如果风控检查过程中出错（比如查不到某标的的流动性数据），默认动作必须是拒绝，不是放行。

### 4.2 完整规则表

#### 仓位类（hard）

| 规则码 | 检查 | A 股默认 | 美股默认 | 动作 |
|---|---|---|---|---|
| `POS_001` | 单标的权重上限 | 10% | 8% | clip |
| `POS_002` | 单行业权重上限 | 25% | 25% | clip 按比例 |
| `POS_003` | 单概念板块权重上限 | 20% | — | clip |
| `POS_004` | Top5 集中度上限 | 40% | 40% | clip |
| `POS_005` | 最少持仓数 | 5 | 8 | reject（分散不足） |
| `POS_006` | 最多持仓数 | 20 | 25 | 截断低分 |
| `POS_007` | 总股票仓位上限 | 90% | 90% | 按比例缩放 |
| `POS_008` | 最低现金 | 10% | 10% | 按比例缩放 |
| `POS_009` | 高相关 cluster 权重上限 | 35% | 35% | clip |
| `POS_010` | 单权重不得为负（无做空） | — | 允许负 | reject |

#### 流动性类（hard）

| 规则码 | 检查 | A 股默认 | 动作 |
|---|---|---|---|
| `LIQ_001` | 20 日均成交额下限 | 5000 万 | reject 该标的 |
| `LIQ_002` | 持仓市值 / 20 日均量 上限 | 3% | clip |
| `LIQ_003` | 单笔订单 / 当日成交量 上限 | 5% | 拆单或 clip |
| `LIQ_004` | 预估清仓天数上限 | 3 天 | clip |

#### 交易可行性类（hard，A 股特有）

| 规则码 | 检查 | 动作 |
|---|---|---|
| `EXE_001` | 停牌不可交易 | reject 该标的 |
| `EXE_002` | 涨停不可买入 | reject 买单 |
| `EXE_003` | 跌停不可卖出 | reject 卖单，记录机会损失 |
| `EXE_004` | T+1：卖出量 ≤ `sellable_qty` | clip |
| `EXE_005` | 买入需整手（100 股） | 向下取整 |
| `EXE_006` | 现金充足性（含费用） | clip |
| `EXE_007` | 不得同日反向交易同一标的 | reject 后到的 |

#### 排除类（hard）

| 规则码 | 检查 | 动作 |
|---|---|---|
| `EXC_001` | ST / *ST | reject |
| `EXC_002` | 退市风险警示 | reject |
| `EXC_003` | 上市不足 60 日 | reject 买入 |
| `EXC_004` | 财报前 3 日 | reject 新建仓（可持有） |
| `EXC_005` | 人工黑名单 | reject |
| `EXC_006` | 数据质量标记 suspect | reject（宁可不买） |
| `EXC_007` | 无有效价格（超过 3 日无更新） | reject |

#### 回撤与损失类（hard，触发后强制，★ 不可被用户关闭）

| 规则码 | 检查 | 默认 | 动作 |
|---|---|---|---|
| `DD_001` | 单日组合亏损 | -3% | 当日停止新建仓 |
| `DD_002` | 累计回撤 | -15% | 总仓位减半 |
| `DD_003` | 累计回撤 | -25% | 清仓并停止，需人工重启 |
| `DD_004` | 连续亏损天数 | 5 天 | 降低总仓位 30% |
| `DD_005` | 单标的浮亏（**系统底线**） | -25% | 强制减仓 50% |

`DD_003` 是 kill switch 的一部分：触发后系统进入 halted 状态，必须人工检查并显式重启。

**这一类是系统底线，不是用户的止损策略。** 用户可配置的个股止盈止损见 4.2a——两者的区别很重要：

| | 回撤类 hard 规则（本表） | 个股止盈止损策略（4.2a） |
|---|---|---|
| 目的 | 防止系统性崩坏 | 用户的进出场纪律 |
| 可否用户关闭 | ❌ 不可 | ✅ 可，阈值可自定义 |
| 层级 | 组合 + 极端个股兜底 | 单标的 |
| 阈值 | 固定（保守） | 用户设定 |

`DD_005` 从 -20% 上调到 -25% 并去掉"可配置关闭"——它现在是**纯兜底**（防止某只票跌到深渊还不动），日常止损交给用户的 4.2a 策略。避免了原来 -8% 提醒、-20% 强制减仓之间的策略真空。

#### 换手类（soft，超限告警但不阻断）

| 规则码 | 检查 | 默认 |
|---|---|---|
| `TO_001` | 单次再平衡换手 | 30% |
| `TO_002` | 月度累计换手 | 200% |
| `TO_003` | 单标的持有期下限 | 5 交易日 |

#### 一致性类（hard）

| 规则码 | 检查 | 动作 |
|---|---|---|
| `CON_001` | 权重和 ≤ 1.0（含现金） | reject |
| `CON_002` | 目标权重与持仓可达（现金够） | clip |
| `CON_003` | 无重复标的 | reject |
| `CON_004` | 所有标的在当日股票池内 | reject 池外标的 |
| `CON_005` | 本地持仓与券商一致（实盘） | reject 全部，触发对账 |

#### 美股特有

| 规则码 | 检查 | 说明 |
|---|---|---|
| `US_001` | PDT 规则：账户 < $25k 时 5 日内日内交易 ≤3 次 | 阻断超限的日内交易 |
| `US_002` | 最低股价 $5 | 排除仙股 |
| `US_003` | 不交易 OTC / 粉单 | — |

### 4.2a 个股止盈止损策略（用户可配置）

回撤类 hard 规则是系统底线；**个股的日常止盈止损是用户的纪律，阈值应开放给用户自定义**。理由：止损线因人而异——风险承受度、持仓成本、税费敏感度、投资期限都不同，固定 -8% 对谁都不合适。

#### 配置

```yaml
# config/user/exit_policy_cn.yaml
stop_loss:
  enabled: true
  type: "fixed"                # fixed | trailing | atr
  threshold: -0.10             # ★ 用户自定义，相对成本的浮亏
  # trailing 时：
  # type: "trailing"
  # trail_pct: 0.15            # 自持仓后最高点回撤 15%

take_profit:
  enabled: true
  type: "staged"               # none | fixed | staged | target_price
  stages:                      # ★ 分批止盈，用户自定义
    - { gain: 0.20, reduce: 0.33 }   # 涨 20% 减 1/3
    - { gain: 0.50, reduce: 0.50 }   # 再涨到 50% 减一半
  # type: "target_price" 时读取 watchlist.target_price

# 安全边界（系统对用户配置的约束，防止误设）
bounds:
  stop_loss_min: -0.30         # 止损不得比 -30% 更松（否则等于没止损）
  stop_loss_max: -0.03         # 也不得比 -3% 更紧（否则频繁触发）
```

#### 四种止损类型

| type | 说明 | 适用 |
|---|---|---|
| `fixed` | 相对成本的固定百分比 | 简单，多数用户 |
| `trailing` | 自持仓后最高点回撤百分比（移动止损） | 让利润奔跑 |
| `atr` | N × ATR 动态止损 | 适应个股波动率 |
| 关闭 | `enabled: false` | 长线持有者 |

#### 三条硬约定

1. **系统对用户阈值做边界校验**（`bounds`）。用户可以设 -10% 或 -20%，但不能设 -80%（等于没止损）或 -1%（噪声触发）。越界时拒绝配置并提示,不静默纠正。

2. **止盈止损产出的是建议，不自动卖出**（A 股阶段）。与"LLM 不得直接下单"同源——见第 5 节。触及阈值时进入次日执行清单 / 盘中推送，由用户确认。美股接 API 后可选自动执行（见 10-execution）。

3. **策略参数进决策日志**。每次触发记录当时的 `exit_policy` 快照，否则无法复盘"当时为什么建议卖"。

4. **停牌 / 涨跌停时止损可能无法执行**（已核实规则的直接后果）。新股上市前 5 日临时停牌（±30%/±60% 各停 10 分钟），以及个股停牌、跌停封板，都会让"触及止损阈值→卖出"落空——想卖也卖不掉。系统必须：
   - 触发止损建议时**同时检查可交易性**（停牌/跌停），若不可交易，推送改为"止损已触发但当前无法成交（停牌/跌停），已封板"的**风险告警**而非"建议卖出"
   - 不在新股前 5 日无涨跌幅期间对该标的套用固定百分比止损（波动可达 ±60%，固定阈值会被瞬间击穿且无法成交）
   - 这条对应 `EXE_001`（停牌 reject）在 exit 侧的镜像，见 [10-execution](10-execution.md)

#### 与 hard 规则的关系

```
用户止损 -10%   ──触及──▶  建议卖出（可确认/可忽略）
                              │ 用户忽略，继续跌
DD_005 -25%    ──触及──▶  强制减仓 50%（兜底，不可忽略）
```

用户可以把止损设得比 -25% 更宽甚至关闭，但 **`DD_005` 永远兜底**——这是用户配置无法突破的地板。


### 4.3 实现

```python
class RiskEngine:
    def __init__(self, cfg: RiskConfig, market_cfg: MarketConfig):
        self._cfg = cfg
        self._market = market_cfg
        self._rules = self._build_rules()      # 顺序敏感
        self._config_hash = hash_config(cfg, market_cfg)

    def check(
        self, target: dict[str, float], state: PortfolioState, *, as_of: date,
    ) -> RiskResult:
        """★ 无 override 参数。签名里没有任何绕过途径。"""
        violations: list[RiskViolation] = []
        weights = dict(target)

        try:
            for rule in self._rules:
                outcome = rule.apply(weights, state, self._cfg, self._market, as_of)
                violations.extend(outcome.violations)
                if outcome.action == "reject_all":
                    return RiskResult(
                        decision=REJECT, original_target=target,
                        final_target={}, violations=violations,
                        config_hash=self._config_hash,
                    )
                weights = outcome.weights
        except Exception as e:
            # ★ 失败保守：异常 → 拒绝
            return RiskResult(
                decision=REJECT, original_target=target, final_target={},
                violations=[*violations, RiskViolation(
                    rule_code="ENGINE_ERROR", severity="hard", detail=str(e),
                )],
                config_hash=self._config_hash,
            )

        decision = APPROVE if weights == target else MODIFY
        return RiskResult(
            decision=decision, original_target=target, final_target=weights,
            violations=violations, config_hash=self._config_hash,
        )
```

### 4.4 规则执行顺序

顺序影响结果，必须固定并测试：

```
1. 一致性检查（CON_*）        —— 输入合法性
2. 排除类（EXC_*）            —— 剔除不可投标的
3. 交易可行性（EXE_001-003）  —— 剔除不可交易
4. 流动性（LIQ_*）            —— 剔除/削减流动性不足
5. 回撤保护（DD_*）           —— 可能直接限制总仓位
6. 仓位限制（POS_*）          —— 削减超限权重
7. 交易可行性（EXE_004-007）  —— 取整、现金校验
8. 换手（TO_*）               —— 软约束，告警
9. 最终一致性复检             —— 削减后仍需满足所有 hard 规则
```

第 9 步必须有：削减操作可能引入新的违规（如削减后持仓数不足 5）。

### 4.5 Kill Switch

```python
class KillSwitch:
    """独立于 RiskEngine 的紧急停止。可手动触发或自动触发。"""

    def is_halted(self) -> bool:
        return self._redis.get("system:halted") == b"1"

    def halt(self, reason: str, triggered_by: str) -> None:
        self._redis.set("system:halted", b"1")
        self._log_halt(reason, triggered_by)
        self._notify(reason)

    def resume(self, operator: str, confirmation: str) -> None:
        """必须人工显式恢复，且需要输入确认串。"""
        if confirmation != "I HAVE REVIEWED THE HALT REASON":
            raise ValueError("Confirmation string mismatch")
        self._redis.delete("system:halted")
        self._log_resume(operator)
```

自动触发条件：`DD_003`（回撤 25%）、对账不一致、连续下单失败、数据质量 FATAL。

检查点：Execution 层每次下单前检查 `is_halted()`。

## 5. 组合状态

```python
class PortfolioState(BaseModel):
    account_id: int
    as_of: date

    cash: float
    positions: dict[str, Position]
    total_value: float

    # A 股 T+1 支持
    def sellable_qty(self, symbol: str) -> float: ...

    # 回撤跟踪
    peak_value: float
    current_drawdown: float
    consecutive_loss_days: int

    # 换手跟踪
    turnover_mtd: float
    day_trades_5d: int              # 美股 PDT

    # 状态
    is_halted: bool
    halt_reason: str | None
```

## 6. A 股阶段的输出：人工执行清单

不接交易 API 时，最终产物是可执行的清单。

```markdown
# 执行清单 2026-09-01（基于 08-31 收盘数据）

⚠️ 本清单由系统生成，不构成投资建议。执行前请自行复核。

### 卖出（优先执行）

| 代码 | 名称 | 当前 | 目标 | 卖出股数 | 委托价区间 | 理由 |
|---|---|---|---|---|---|---|
| 600xxx | XX | 6.2% | 0% | 3,400 | 12.80-13.10 | 量化信号转负；行业景气度下行 |

### 买入

| 代码 | 名称 | 当前 | 目标 | 买入股数 | 委托价区间 | 理由 |
|---|---|---|---|---|---|---|
| 000xxx | YY | 0% | 5.0% | 1,200 | 41.20-42.00 | 板块排名第2；财报超预期 |

### 未执行项（记录用）

| 代码 | 原计划 | 未执行原因 |
|---|---|---|
| 300xxx | 买入 4% | 昨日涨停，预计难以买入 |

### 风控提示

- 触发规则：POS_002（电子行业达 24.8%，接近 25% 上限）
- 当前回撤：-6.2%（阈值 -15%）
- 本月累计换手：87%（上限 200%）

### 今日盘中告警回顾

| 时间 | 级别 | 内容 |
|---|---|---|
| 10:23 | high | 600xxx 放量异动（量为 5 日均量 3.2 倍） |
| 14:45 | medium | 电子行业权重达 23.1%，接近上限 |

### 数据说明

- 数据截止：2026-08-31 15:00
- 数据质量：正常
- 降级项：无
- LLM 成本：$0.58（预算 $0.80）
```

约定：
- 委托价区间基于次日预估波动，非精确预测
- 未执行项必须记录（Shadow Portfolio 需要知道机会损失）
- 数据降级必须在清单中声明
- 盘中告警回顾与执行清单关联（同一持仓的两条信息流）
- LLM 成本显式披露

## 7. 盘中监控对风控的复用

监控层**不实现独立的风控逻辑**，而是复用本文档定义的规则。

### 7.1 复用方式

| 监控场景 | 复用什么 |
|---|---|
| B 类风控触发器 | 用相同的阈值配置，但设**预警线**（略低于硬限制） |
| L3 深度分析后的调仓建议 | 调用 `RiskEngine.check()` 验证建议合法性 |
| 推送中的风控提示 | 读取 `risk_audit.violations` |

预警线设计：

```yaml
# config/monitor/risk_triggers.yaml
# 阈值取自 config/risk/cn.yaml，但设为提前告警
- code: "RISK_SECTOR_CONCENTRATION"
  condition: "max_industry_weight > 0.23"   # 硬限制 0.25，提前 2% 告警
  severity: "high"

- code: "RISK_PORTFOLIO_DRAWDOWN"
  condition: "portfolio_drawdown >= 0.10"   # 硬限制 0.15，提前告警
  severity: "critical"
```

**约定：预警线必须从硬限制推导，不独立配置。** 否则两处阈值会不一致。

```python
class MonitorRiskThresholds:
    """从风控配置推导预警线，避免阈值分叉。"""

    def __init__(self, risk_cfg: RiskConfig, margin: float = 0.08):
        self.sector_warn = risk_cfg.position_limits.max_industry_weight * (1 - margin)
        self.drawdown_warn = risk_cfg.drawdown_limits.max_drawdown * 0.67
        # ...
```

### 7.2 监控不做的事

| 不做 | 原因 |
|---|---|
| 自动执行止损 | 推送是建议，执行由用户或 Execution 层负责 |
| 修改风控阈值 | 阈值只在 `config/risk/*.yaml` 定义 |
| 绕过 RiskEngine 给出调仓建议 | L3 的建议必须过 RiskEngine 验证 |
| 独立实现风险计算 | 复用 `PortfolioState` 的现有指标 |

### 7.3 依赖方向

```
monitor  ──依赖──▶  decision.risk        ✅
decision.risk  ──依赖──▶  monitor        ❌ 禁止（有架构测试）
```

见 [13-repo-layout](13-repo-layout.md) 2.2 节的 `FORBIDDEN` 列表。

## 8. 冷启动：给空仓用户的建仓推荐

### 8.1 能力已存在，缺的是命名与暴露

回看 3.2 节的构建流程：**①-⑥ 完全不参考现有持仓**，只有 ⑦ 才引入 `current`。

```
①-⑥ 输出  = "如果从零开始，我会持有什么"   ← 冷启动组合
⑦ 输出     = "从当前持仓出发，今天调什么"    ← 调仓建议
```

所以冷启动不需要新 Agent、新模型、新信号。与"不新建 MonitorAgent"（[ADR-0009](adr/0009-monitor-three-tier-funnel.md)）同源：管道已经算出来了。

```python
def build_cold_start(
    scores: dict[str, FusedScore],
    investable_capital: Decimal,          # ★ 用户愿意投入的金额，非账户总额
    cfg: PortfolioConfig,
    market_cfg: MarketConfig,
    eligibility: UserEligibility = UserEligibility(),
) -> ColdStartPlan:
    """从零构建组合。等价于 build_portfolio(current={}) 但多了三件事：
    1. 资金量约束（整手可执行性，基于 investable_capital）
    2. 分批建仓计划
    3. 允许输出「不建仓」

    ★ investable_capital 是唯一资金输入：top_n、整手取整、单票上限
      全部基于它。不存在「按总资金算组合再打折」——那会破坏整手可行性。
    """
```

**为什么是"可投入资金"而不是"账户总额"**：用户可能只想先投一部分试水。此时必须用**可投入的那部分**重算组合，而不是按总额算完再按比例缩小。原因见 8.3 末尾。

### 8.2 持有理由 ≠ 买入理由

**这一点必须写清楚，否则实现时会图省事出错。**

假设 shadow portfolio 持有某股，成本 10 元，现价 15 元。对已持仓者是"继续持有"，但这不等于对新用户是"现在买入"：

| 混入持有决策的因素 | 对新建仓是否适用 |
|---|---|
| 换手成本（卖出要付费） | **不适用**（本来就没持有） |
| 印花税/资本利得考虑 | **不适用** |
| "不想卖"的路径惯性 | **不适用** |
| 当前价位的剩余空间 | ★ `min_score` 不覆盖这一点 |

**结论：冷启动必须重跑 ①-⑥，不能读取 `shadow_cn` 的当前持仓。**

```python
# ❌ 错误实现
def build_cold_start_wrong(account_id: int) -> list[Position]:
    return repo.get_positions(account_id)      # 直接复制现有组合

# ✅ 正确实现
def build_cold_start(scores, capital, cfg, market_cfg) -> ColdStartPlan:
    candidates = apply_exclusions(scores, cfg)          # ①
    candidates = apply_executability(candidates, capital, market_cfg)  # ★ 新增
    selected   = rank_and_select(candidates, cfg)       # ②
    ...
```

有测试保障：

```python
def test_cold_start_not_copy_of_current_holdings():
    """冷启动结果不应等于当前持仓的机械复制。"""
```

### 8.3 资金量约束 —— A 股整手的现实

`top_n: 15` 不能是常量。A 股买入最小 100 股（科创板 200 股，已核实 2026-09-03），小资金无法执行 15 个等权持仓。

反算单票可买的最高股价：

```
P_max = investable_capital × max_single_weight / min_lot_buy
```

（下表用"资金"指代 `investable_capital`——用户实际投入的部分，非账户总额）

| 资金 | 单票上限 10% | P_max（主板） | 实际可行持仓数 |
|---|---|---|---|
| 5 万 | 5,000 元 | 50 元/股 | 8-10 |
| 10 万 | 10,000 元 | 100 元/股 | 12-15 |
| 20 万 | 20,000 元 | 200 元/股 | 15-20 |
| 50 万 | 50,000 元 | 500 元/股 | 15-25 |

资金 5 万时买一手 100 元的股票就是 20% 权重——**直接违反单票上限，会被 RiskEngine 拒掉**。若不在组合层提前排除，用户会收到一份大部分标的无法执行的清单。

#### 新增排除规则（组合层）

```python
EXCLUSION_RULES_COLD_START = EXCLUSION_RULES + [
    # ★ 可执行性：一手的金额已超过单票权重上限
    "last_price * min_lot_buy > capital * max_single_weight",
    # ★ 板块权限：用户未开通（已在 EXCLUSION_RULES，此处强调冷启动同样适用）
    # "board not in user.tradable_boards"
]
```

排除有两个不同来源，输出时要**分别标注原因**，不能混为"已过滤"：

| 排除码 | 原因 | 用户可采取的行动 |
|---|---|---|
| `CAPITAL_LOT` | 一手金额超单票上限 | 增加资金 |
| `BOARD_NOT_ELIGIBLE` | 未开通该板块权限 | 去券商开通（附门槛提示） |

#### top_n 由资金量推导

```python
def derive_top_n(investable_capital: Decimal, candidates: list[Candidate],
                 cfg: PortfolioConfig, market_cfg: MarketConfig) -> int:
    """可行持仓数上限 = 有多少标的能在权重约束内买到至少一手。
    ★ 基于 investable_capital（用户可投入部分），非账户总额。"""
    max_single = investable_capital * Decimal(str(cfg.risk.max_single_weight))
    affordable = [
        c for c in candidates
        if c.last_price * market_cfg.min_lot_buy(c.board) <= max_single
    ]
    return min(cfg.selection.top_n, len(affordable), _capital_tier(investable_capital))

def _capital_tier(investable_capital: Decimal) -> int:
    """资金分档的建议持仓数上限。持仓过多会导致每票金额过小、成本占比高。"""
    if investable_capital < 30_000:   return 5
    if investable_capital < 100_000:  return 10
    if investable_capital < 300_000:  return 15
    return 20
```

低于 3 万时建议持仓数 ≤5：**不是因为分散不好，而是因为再分散下去每票买不到一手，或佣金最低 5 元会吃掉收益**（单笔 3000 元时佣金占 0.17%，是标准佣金率的数倍）。

#### 整手取整与残差

```python
def to_lots(
    target_weights: dict[str, Decimal],
    prices: dict[str, Decimal],
    investable_capital: Decimal,          # ★ 可投入资金，非账户总额
    market_cfg: MarketConfig,
) -> tuple[dict[str, int], Decimal]:
    """目标权重 → 实际股数（整手），返回 (股数, 剩余现金)。

    取整规则：向下取整（宁可少买，不可超配）。
    残差处理：剩余现金保留，不强行凑单。
    """
```

三条约定：

| 约定 | 理由 |
|---|---|
| **向下取整** | 向上取整可能突破单票上限或总仓位上限 |
| **残差保留为现金** | 强行凑单会扭曲权重；且 `min_cash: 0.10` 本来就要留现金 |
| **取整后重新校验风控** | 取整会改变实际权重，必须再过一次 RiskEngine |
| **按板块递增单位取整** | 主板/创业板按 100 股整数倍；科创板 200 股起、之后 1 股递增；北交所 100 股起、之后 1 股递增。取整用 `market_cfg.lot_increment_by_board`，不是一律 100（已核实 2026-09-03） |

科创板/北交所可 1 股递增，意味着它们的取整残差远小于主板——但**买入下限仍是 200/100 股**，`derive_top_n` 的"买得起一手"判断仍按下限算。

小资金下取整误差占比大，必须在输出中显式展示实际权重 vs 目标权重的偏差。

#### 用户投入偏好：用可投入资金重算，不按总额打折

用户可能不想一次投入全部资金。例如账户 10 万，只想先投 3 万试水。此时有两种做法，**只有一种是对的**：

| 做法 | 问题 |
|---|---|
| ❌ 按 10 万算组合，再整体缩到 30% | 某票在 10 万里是 8%（8000 元），缩到 30% 后仅 2400 元，**可能连一手都买不起** |
| ✅ 直接用 3 万算组合 | 整手约束从头基于真实可用资金，`derive_top_n` 保证每票买得起一手 |

**打折会破坏整手可行性**：`derive_top_n` 的可执行性校验是用全额资金做的，做完再打折等于校验作废。所以：

```yaml
# config/user/deployment_cn.yaml
capital_total: 100000        # 账户总额（仅供展示"投入比例"）
investable: 30000            # ★ 冷启动的唯一资金输入
# 也可用比例表达：
# max_deployment: 0.30       # investable = capital_total × max_deployment
```

三条约定：

| 约定 | 理由 |
|---|---|
| `investable_capital` 是 `derive_top_n`/整手/单票上限的唯一基准 | 保证清单每一项都真实可执行 |
| 未投入部分是用户的现金决策，不计入组合权重 | 它不是"现金仓位"，是"还没进场的钱" |
| `min_cash` 仍在 `investable` 内部生效 | 3 万里仍留 10% 现金缓冲，与总额无关 |

**注意区分三种"现金"**（容易混淆）：

| 现金 | 含义 | 由谁决定 |
|---|---|---|
| 未投入资金（10 万里的 7 万） | 用户还没决定进场的钱 | 用户 `investable` |
| exposure 留出的现金（stance） | 市场判断该留多少 | 系统 ⑥ 步 |
| `min_cash: 0.10` | 风控底线缓冲 | 风控配置 |

三者叠加：`investable=3万` → stance defensive 只投 50% → 再留 min_cash 10%，最终实际买入约 1.35 万。输出必须把这三层拆开展示，否则用户看不懂"我说投 3 万，怎么只买了 1.35 万"。

调仓每天只动边际，而**冷启动一次性决定全部仓位的成本基础**。若那天恰好是局部高点，之后很长时间都在解套。

更麻烦的是它污染归因：无法区分"策略不行"和"建仓时点不好"。

```yaml
# config/portfolio/cn.yaml 新增
cold_start:
  scale_in:
    enabled: true
    tranches: 4                    # 分 4 批
    interval_days: 5               # 每批间隔 5 个交易日
    first_tranche_ratio: 0.40      # 首批稍重，避免拖太久
    # 剩余 0.60 均分给后 3 批，各 0.20

  # 分批期间的中止条件
  abort_conditions:
    score_below_min: true          # 分数跌破 min_score → 停止后续加仓
    excluded_by_rules: true        # 触发排除规则（如 ST、停牌）→ 停止
    portfolio_drawdown: 0.08       # 组合回撤超 8% → 暂停全部加仓，重新评估

  expires_after_days: 3            # 推荐清单有效期
```

**分批期间标的失效的处理**（这是容易漏掉的分支，完整的 `ScaleInDecision` 定义见下）：

| 情况 | 动作 |
|---|---|
| 分数跌破 `min_score` | `abort_remaining` — 停止后续加仓，**不卖出已建仓部分** |
| 触发排除规则（ST/停牌） | `abort_remaining` |
| 涨停买不进 | `skip_this_tranche` — 顺延到下一批 |
| 组合回撤超阈值 | 全部 `abort_remaining`，重新走冷启动 |
| **stance 转好（如 defensive→moderate）** | `increase_exposure` — 在 `investable` 上限内追加，见下 |

**不卖出已建仓部分**是刻意的：卖出决策应走正常的调仓流程和风控，不由建仓计划决定。否则会出现"建仓计划自带止损逻辑"这种职责混乱。

#### 分批的资金边界（必须严格）

分批建仓分的是**已决定投入的部分**，两条不可越界：

| 边界 | 规则 |
|---|---|
| **未投入资金永不自动触碰** | `investable=3万` 时，剩余 7 万是用户明确"先不投"的钱。追加它必须由用户显式发起新推荐，建仓计划无权动用 |
| **stance 留出的现金可在 `investable` 内追加** | stance defensive 只投 50%，留的现金仍在 3 万内，后续可随市场转好投入 |

违反第一条是严重的信任问题——"我说投 3 万，系统偷偷把剩下 7 万也投了"。

#### stance 转好时的追加（时机由系统判断，不需用户盯盘）

系统每日重算 stance（⑥ 步）。若建仓期间 stance 上升，原本因 defensive 留出的现金应能投入——但**上限永远是 `investable`**。

```python
class ScaleInDecision(BaseModel):
    action: Literal[
        "proceed",           # 按原计划执行本批
        "skip_this_tranche", # 涨停等，顺延
        "abort_remaining",   # 停止后续（不卖出）
        "replace",           # 标的替换
        "increase_exposure", # ★ stance 转好，在 investable 内追加
    ]
    reason: str
    target_exposure: Decimal | None = None   # increase 时的新目标仓位
```

三条约定：

| 约定 | 理由 |
|---|---|
| 追加上限 = `investable × new_stance_exposure`，且永不超过 `investable` | 用户投入意愿是硬边界 |
| 每批记录当时的 stance 到 `scale_in_tranche` | exposure 逐批可能不同，归因需要 |
| 追加是**推荐/建议**，进执行清单由用户确认 | 与"不自动下单"一致 |

**为什么时机由系统推荐**：让用户盯盘判断"市场是不是转好了"违背系统定位——盘后批处理本就每天算 stance，把"stance 转好"变成一个推送信号（见 [15-monitoring-alerts](15-monitoring-alerts.md) 的 `REC_STANCE_UP` 触发器）比让用户自己看更可靠，也零 LLM 成本。

**不对称是刻意的**：stance 转差走 `abort_remaining`（停止加仓），stance 转好走 `increase_exposure`（可追加）。两个方向都响应市场，但都不卖出已建仓部分——卖出永远走正常调仓与风控。

### 8.5 允许输出"不建仓"

`min_score: 0.55` 的设计本就允许空仓（见 3.4 节）。冷启动时这会产生一个必须支持的输出：

```markdown
# 建仓建议 2026-09-01

### 结论：暂不建仓

候选池中无标的达到入选门槛（min_score = 0.55）。
当前最高分：0.51（600xxx）

### 依据
- 池内 50 支标的，达到 0.55 的：0 支
- 市场状态：ChiefAgent 判定 defensive
- 因子表现：动量因子近 20 日 IC = -0.03

### 建议
保持现金。下次评估：2026-09-08（或分数变化触发提前评估）
```

**这是一个正确答案，不是系统故障。** 但用户问"我该买什么"得到"什么都别买"，很容易被当成系统没用。所以文案上必须：

| 要求 | 理由 |
|---|---|
| 说明"暂不建仓"是有信息量的结论 | 避免被当成故障 |
| 给出最高分与门槛的距离 | 让用户知道差多少 |
| 说明下次评估时点 | 避免用户以为要一直等 |
| 展示依据（因子/市场状态） | 可追溯，符合原则 5 |

### 8.6 推荐 ≠ 实际持仓

冷启动引入第三种持仓状态：

| 状态 | 表 | 含义 |
|---|---|---|
| 用户实际持有 | `manual_position` | 真实持仓 |
| 系统假设持有 | shadow portfolio | 归因基准 |
| **已推荐未执行** | `recommendation` | ★ 新增 |

三个具体问题：

| 情况 | 必须如何处理 |
|---|---|
| 推荐 15 只，用户只买 3 只 | 记录执行率，归因**用 shadow 不用用户实际持仓** |
| 推荐后未买，股价涨了 | 记入 shadow（系统对了），不记入用户 PnL |
| 监控需要 `avg_cost` / `entry_high` | 未执行的推荐没有这些字段，触发器需降级 |

**R-21（建议模式自欺）在这里会放大**：用户会记住"系统推荐的那只涨了"，忘记"我没买"和"另外 12 只没涨"。

缓解手段是纯工程的（与 R-21 一致）：`recommendation` 表 append-only，执行率与全部推荐的结果分布强制展示。数据结构见 [03-data-model](03-data-model.md) 2.12 节。

### 8.7 输出格式

```markdown
# 建仓建议 2026-09-01（基于 08-31 收盘数据）

⚠️ 本清单由系统生成，不构成投资建议。执行前请自行复核。

### 参数
- 账户总额：100,000 元
- 本次投入：100,000 元（投入比例 100%）      ← 用户可只投一部分，见下例
- 建议持仓数：12（受资金量与整手约束）
- 目标总仓位：70%（stance = moderate）
- 建仓方式：分 4 批，每批间隔 5 个交易日

### 第 1 批（本次执行，占计划 40%）

| 代码 | 名称 | 目标权重 | 本批股数 | 金额 | 委托价区间 | 入选理由 |
|---|---|---|---|---|---|---|
| 600xxx | XX | 5.8% | 200 | 2,320 | 11.40-11.80 | 板块排名 2；ep_ttm 分位 12% |

小计：本批 28,000 元（28%），剩余现金 72,000 元

### 后续批次计划

| 批次 | 预计日期 | 占比 | 说明 |
|---|---|---|---|
| 2 | 2026-09-08 | 20% | 执行前重新校验分数 |
| 3 | 2026-09-15 | 20% | |
| 4 | 2026-09-22 | 20% | |

### 权重偏差（整手取整导致）

| 代码 | 目标 | 实际 | 偏差 |
|---|---|---|---|
| 600xxx | 5.83% | 5.80% | -0.03% |

剩余未配置现金：1,240 元（1.2%）——整手取整残差，不强行凑单

### 因资金量排除的标的

| 代码 | 名称 | 分数 | 排除原因 |
|---|---|---|---|
| 688xxx | ZZ | 0.71 | 一手 200 股 × 168 元 = 33,600 元 > 单票上限 10,000 元 |

★ 这些标的分数不低，但当前资金量无法在权重约束内买入

### 资金拆解（当用户只投一部分时必须展示）

假设用户账户 10 万，只想先投 3 万：

| 层次 | 金额 | 说明 |
|---|---|---|
| 账户总额 | 100,000 | 仅供参考 |
| **本次投入** `investable` | 30,000 | ★ 组合基于此计算 |
| stance 留出（defensive 50%） | −15,000 | 市场判断该留的现金 |
| min_cash 缓冲（10%） | −3,000 | 风控底线 |
| **实际买入股票** | ≈12,000 | 分 4 批 |
| 未投入（观望） | 70,000 | 用户的现金决策，不在组合内 |

**这一拆解不可省略**——否则用户会困惑"我说投 3 万，怎么最后只买了 1.2 万"。三种现金（未投入 / stance 留存 / min_cash）性质不同，必须分开说明。

### 系统历史成绩（必须展示）

| 指标 | 值 |
|---|---|
| Shadow Portfolio 运行时长 | 8 个月 |
| 累计收益 vs 沪深300 | +6.2% vs +1.8% |
| 对照组：等权池 | +3.1% |
| 对照组：随机选股 95 分位 | +7.4% ⚠️ 未超出随机范围 |
| 过往建仓推荐次数 | 5 次 |
| 其中 20 日跑赢基准 | 3 次 |

### 数据说明
- 数据截止：2026-08-31 15:00
- 清单有效期：至 2026-09-03（过期需重新生成）
- LLM 成本：$0.42
```

**"系统历史成绩"章节不可省略。** 见 8.8。

### 8.8 定性风险：这是最接近"荐股"的功能

日报是研究，"给空仓用户的 12 只建仓清单"在观感上非常接近投资建议。这会显著加剧 R-24（误当赚钱工具，评级中概率/**致命**）。

免责声明不够，需要设计上的约束：

| 强制要求 | 作用 |
|---|---|
| 展示对照组表现（含随机选股分位） | 让用户看到系统是否真的超出随机 |
| 展示 shadow portfolio 实际历史成绩 | 不是回测数字，是真实前向记录 |
| 展示过往推荐的结果分布（不只是好的） | 对抗选择性记忆 |
| 若随机选股 95 分位超过本策略，**必须显著标注** | 诚实优先于好看 |
| 分批建仓作为默认 | 降低单次时点风险 |

目标是让用户看到的不是一份清单，而是**一份带成绩记录的清单**。

### 8.9 为什么放 P5，不能更早

**冷启动决定全部仓位，调仓只影响边际。所以它需要更完整的风控，不是更少。**

| 前置能力 | 阶段 | 缺了会怎样 |
|---|---|---|
| 相关性去冗余 | **P5** | 推荐 12 只同板块股票，看似分散实为一个赌注 |
| 波动率调整 | **P5** | 高波动标的权重过高 |
| 总仓位管理（stance） | **P5** | 不知道该买七成还是三成 |
| 全部 hard 风控规则 | **P5** | 推荐可能违反行业集中度等约束 |
| Shadow 历史成绩 | P4（3 个月观察） | 无成绩可展示，无法对抗 R-24 |

A 股同概念板块内相关性极高，第一条不是理论风险。若在 P1（8 个因子、无去冗余）就做冷启动，很可能推出一篮子高相关标的。

另外 P1 MVP 的 Agent 明确"禁止给买卖建议"（见 [11-mvp](11-mvp.md)），冷启动推荐属于买卖建议。

## 9. 测试要求

风控是最需要测试的模块。

```python
# 每条规则一个测试
def test_pos_001_single_weight_cap():
    target = {"A": 0.25, "B": 0.75}
    result = engine.check(target, empty_state, as_of=d)
    assert result.decision == MODIFY
    assert result.final_target["B"] <= 0.10
    assert any(v.rule_code == "POS_001" for v in result.violations)

# 属性测试：输出永不违反 hard 规则
@given(target=weight_dicts(), state=portfolio_states())
def test_output_never_violates_hard_rules(target, state):
    result = engine.check(target, state, as_of=d)
    if result.decision != REJECT:
        assert all_hard_rules_satisfied(result.final_target, state, cfg)

# 确定性测试
def test_deterministic():
    r1 = engine.check(target, state, as_of=d)
    r2 = engine.check(target, state, as_of=d)
    assert r1 == r2

# 无绕过途径
def test_no_bypass_parameter():
    sig = inspect.signature(RiskEngine.check)
    forbidden = {"force", "override", "bypass", "skip", "ignore_risk"}
    assert not (set(sig.parameters) & forbidden)
```

最后一个测试是架构约束的自动化保障：防止将来有人"临时"加个 override 参数。

### 9.1 冷启动的测试

```python
# 不是现有持仓的机械复制
def test_cold_start_not_copy_of_current_holdings():
    """冷启动必须重跑 ①-⑥，不能读 shadow 持仓。"""
    plan = build_cold_start(scores, capital, cfg, market_cfg)
    assert plan.weights != {p.symbol: p.weight for p in shadow_positions}

# 资金量约束生效
@pytest.mark.parametrize("capital,expected_max_n", [
    (20_000, 5), (50_000, 10), (200_000, 15), (1_000_000, 20),
])
def test_top_n_derived_from_capital(capital, expected_max_n):
    plan = build_cold_start(scores, Decimal(capital), cfg, market_cfg)
    assert len(plan.items) <= expected_max_n

# 买不起的标的被排除，且排除原因可见
def test_unaffordable_excluded_with_reason():
    """一手金额 > 单票上限的标的应被排除并记录原因。"""
    plan = build_cold_start(scores, Decimal(30_000), cfg, market_cfg)
    assert all(
        i.last_price * market_cfg.min_lot_buy(i.board) <= 30_000 * 0.10
        for i in plan.items
    )
    assert len(plan.excluded_by_capital) > 0          # 原因必须记录

# 整手取整向下，不超配
def test_lot_rounding_never_overshoots():
    lots, cash = to_lots(weights, prices, capital, market_cfg)
    for sym, n in lots.items():
        actual_w = n * prices[sym] / capital
        assert actual_w <= weights[sym] + Decimal("0.0001")

# 取整后重新过风控
def test_risk_recheck_after_rounding():
    """取整改变实际权重，必须再过一次 RiskEngine。"""

# 允许输出不建仓
def test_can_recommend_no_position():
    low = {s: FusedScore(score=0.40) for s in symbols}
    plan = build_cold_start(low, capital, cfg, market_cfg)
    assert plan.action == "no_position"
    assert plan.highest_score == 0.40          # 必须告知差多少
    assert plan.next_review_date is not None

# 分批中标的失效
def test_scale_in_aborts_when_score_drops():
    """分数跌破 min_score → abort_remaining，但不卖出已建仓部分。"""
    d = evaluate_tranche(plan, tranche=2, scores=degraded_scores)
    assert d.action == "abort_remaining"
    assert "sell" not in d.action              # ★ 建仓计划不含卖出逻辑

def test_scale_in_skips_on_limit_up():
    d = evaluate_tranche(plan, tranche=2, scores=scores, limit_up={"600xxx"})
    assert d.action == "skip_this_tranche"

# stance 转好 → 在 investable 内追加，绝不触碰未投入资金
def test_scale_in_increase_capped_by_investable():
    """stance defensive→moderate，追加上限是 investable，非账户总额。"""
    plan = build_cold_start(scores, investable=Decimal(30_000), cfg, market_cfg)
    d = evaluate_tranche(plan, tranche=2, scores=scores, stance="moderate")
    assert d.action == "increase_exposure"
    # 追加后累计投入不超过 investable
    assert plan.deployed_after(d) <= Decimal(30_000)

def test_scale_in_never_touches_uninvested_capital():
    """无论 stance 多好，未投入资金（investable 之外）永不被建仓计划动用。"""
    plan = build_cold_start(scores, investable=Decimal(30_000), cfg, market_cfg)
    d = evaluate_tranche(plan, tranche=2, scores=scores, stance="aggressive")
    assert plan.deployed_after(d) <= Decimal(30_000)   # 不会去动那 7 万

def test_tranche_records_stance_snapshot():
    """每批记录当时 stance，供归因。"""
    d = evaluate_tranche(plan, tranche=2, scores=scores, stance="moderate")
    assert d.stance_at_tranche == "moderate"

# 输出必须含历史成绩
def test_recommendation_includes_track_record():
    md = render_cold_start(plan)
    assert "随机选股" in md            # 对照组必须展示
    assert "Shadow Portfolio" in md

# 推荐过期
def test_recommendation_expires():
    assert plan.expires_at == plan.created_at + timedelta(days=3)

# 板块权限：未开通的板块被排除
def test_cold_start_respects_eligibility():
    """默认仅主板时，科创板/创业板标的不进入推荐。"""
    elig = UserEligibility(tradable_boards=["main"])
    plan = build_cold_start(scores, capital, cfg, market_cfg, eligibility=elig)
    assert all(i.board == "main" for i in plan.items)
    # 被排除的高分科创板标的必须记录且原因可辨
    assert any(e.exclusion_code == "BOARD_NOT_ELIGIBLE" for e in plan.excluded)

def test_eligibility_default_is_main_only():
    """未提供配置时默认最保守。"""
    assert UserEligibility().tradable_boards == ["main"]

# 板块递增单位：科创板 200 起 1 股递增，北交所 100 起 1 股递增
def test_lot_increment_by_board():
    lots, _ = to_lots({"688xxx": Decimal("0.1")}, {"688xxx": Decimal(50)},
                      Decimal(30_000), market_cfg)
    # 科创板可 200 股起、1 股递增，不必是 100 的倍数
    assert lots["688xxx"] >= 200
    # 主板必须是 100 的整数倍
    lots2, _ = to_lots({"600xxx": Decimal("0.1")}, {"600xxx": Decimal(30)},
                       Decimal(30_000), market_cfg)
    assert lots2["600xxx"] % 100 == 0

def test_star_min_buy_is_200():
    """科创板买入下限 200 股，derive_top_n 按此判断买得起一手。"""
    assert market_cfg.min_lot_buy("star") == 200

def test_research_keeps_all_boards_recommendation_filters():
    """研究分析覆盖全部板块，仅建仓推荐按 eligibility 过滤。"""
    assert "688xxx" in research_report.covered_symbols      # 科创板出现在研究
    assert "688xxx" not in [i.symbol for i in plan.items]   # 但不在推荐清单

# 部分投入：用可投入资金重算，不按总额打折
def test_partial_deployment_recomputes_not_scales():
    """投 3 万应基于 3 万重算，而非按 10 万算完打折。"""
    full = build_cold_start(scores, Decimal(100_000), cfg, market_cfg)
    partial = build_cold_start(scores, Decimal(30_000), cfg, market_cfg)
    # 不是简单缩放：持仓数可能更少，标的构成可能不同
    assert not _is_scaled_copy(partial, full, ratio=0.3)

def test_partial_deployment_all_items_affordable():
    """基于可投入资金重算后，每个标的都买得起至少一手。"""
    plan = build_cold_start(scores, Decimal(30_000), cfg, market_cfg)
    for i in plan.items:
        lot_value = i.ref_price * market_cfg.min_lot_buy(i.board)
        assert lot_value <= Decimal(30_000) * cfg.risk.max_single_weight

def test_uninvested_capital_not_in_weights():
    """未投入部分不计入组合权重（它不是现金仓位）。"""
    plan = build_cold_start(scores, Decimal(30_000), cfg, market_cfg)
    # 权重基于 30000，不是 100000
    assert abs(sum(i.target_weight for i in plan.items)
               + plan.stance_cash_weight + plan.min_cash_weight - 1.0) < 1e-6
```

### 9.2 止盈止损的测试

```python
# 阈值来自用户配置
def test_stop_loss_uses_user_threshold():
    policy = ExitPolicy(stop_loss={"threshold": -0.10})
    sig = evaluate_exit(position, last_price, policy)
    assert sig is None if position.ret > -0.10 else sig.kind == "stop_loss"

# 边界校验：越界拒绝
@pytest.mark.parametrize("bad", [-0.80, -0.01, 0.05])
def test_exit_policy_rejects_out_of_bounds(bad):
    with pytest.raises(ConfigValidationError):
        ExitPolicy(stop_loss={"threshold": bad}).validate()

# DD_005 兜底不可被用户配置突破
def test_dd005_floor_survives_user_config():
    """即使用户关闭止损，个股浮亏 -25% 仍强制减仓。"""
    policy = ExitPolicy(stop_loss={"enabled": False})
    state = state_with_position_down(0.30)      # 某票浮亏 30%
    result = engine.check(target, state, as_of=d)
    assert any(v.rule_code == "DD_005" for v in result.violations)

# 止盈止损是建议不自动卖（A 股阶段）
def test_exit_signal_is_advice_not_order():
    sig = evaluate_exit(position, last_price, policy)
    assert sig.suggested_action in {"sell_all", "reduce_33", "reduce_50"}
    # 不产生订单，只进执行清单/推送

# 分批止盈按档推进
def test_staged_take_profit_advances():
    policy = ExitPolicy(take_profit={"type": "staged",
        "stages": [{"gain": 0.20, "reduce": 0.33}, {"gain": 0.50, "reduce": 0.50}]})
    assert evaluate_exit(pos_up(0.22), price, policy).suggested_action == "reduce_33"

# 触发时快照策略
def test_exit_signal_snapshots_policy():
    sig = evaluate_exit(position, last_price, policy)
    assert sig.policy_snapshot["stop_loss"]["threshold"] == policy.stop_loss.threshold
```

## 10. 验收清单

Gate 5（P5）：

- [ ] 全部 hard 规则实现且每条有单元测试
- [ ] 属性测试覆盖：输出永不违反 hard 规则
- [ ] `check()` 签名无任何 override 参数（有测试保障）
- [ ] 异常时默认 REJECT（有测试）
- [ ] 规则执行顺序固定且有测试
- [ ] 削减后复检生效
- [ ] 所有 violation 落库，含 APPROVE 情形
- [ ] `rule_config_hash` 记录
- [ ] Kill Switch 可手动/自动触发，恢复需确认串
- [ ] T+1 `sellable_qty` 逻辑正确（有测试）
- [ ] 涨跌停拒单有统计
- [ ] 人工执行清单模板可生成
- [ ] `shadow_fused_norisk` 组合运行中（量化风控的成本与价值）

冷启动推荐（P5，见第 8 节）：

- [ ] `build_cold_start` 重跑 ①-⑥，非复制现有持仓（有测试）
- [ ] `top_n` 由资金量推导（有参数化测试）
- [ ] 可执行性排除规则生效，排除原因在输出中可见
- [ ] 整手取整向下，残差保留为现金（有测试）
- [ ] 取整后重新过 RiskEngine（有测试）
- [ ] 分批建仓默认开启，中止条件全部实现
- [ ] 分批中止**不触发卖出**（有测试）
- [ ] 分批追加只在 `investable` 内，**绝不触碰未投入资金**（有测试）
- [ ] stance 转好时 `increase_exposure`，时机由系统推荐（有测试）
- [ ] 每批记录 `stance_at_tranche` 快照
- [ ] 支持输出"暂不建仓"，含最高分与下次评估时点
- [ ] 输出强制含对照组与 shadow 历史成绩
- [ ] 若随机选股 95 分位超过本策略，显著标注
- [ ] `recommendation` 表 append-only，执行率可查
- [ ] 推荐有 `expires_at`，过期需重新生成

板块权限与止盈止损（P5，见 3.3a / 4.2a）：

- [ ] `eligibility` 默认仅主板，未开通板块被排除（有测试）
- [ ] 板块排除在输出中按 `BOARD_NOT_ELIGIBLE` 展示，附门槛提示
- [ ] 研究分析保留全部板块，仅推荐过滤（有测试）
- [ ] `recommendation.tradable_boards` 记录
- [ ] 止盈止损阈值用户可配（fixed/trailing/atr/staged）
- [ ] 用户阈值越界被边界校验拒绝（有测试）
- [ ] `DD_005` 兜底不可被用户配置突破（有测试）
- [ ] 止盈止损产出建议不自动卖出（A 股阶段，有测试）
- [ ] `exit_signal.policy_snapshot` 触发时快照（有测试）

## 11. 投入额调整建议（investable 的增减）

**这是整个系统最敏感的功能——它不是"买哪只"，而是"你该往股市放多少本金"。** 独立成节并单独立 [ADR-0015](adr/0015-investable-adjustment.md)，因为"系统能否建议用户增加本金投入"是需要慎重记录的架构决策。

### 11.1 两种模式，风险等级不同

| 模式 | 默认 | 谁发起 | 风险 |
|---|---|---|---|
| **被动响应** | ✅ 开启 | 用户问"现在适合提高投入吗" | 低（用户主动） |
| **主动推送** | ❌ 关闭 | 系统在机会质量高/低时推送 | 高（系统在催/劝） |

被动响应默认可用；主动推送必须用户像开实盘一样显式开启。

### 11.2 为什么主动推送默认关闭

两个严重风险：

**顺周期助推。** "系统觉得形势好"往往对应市场已涨了一段——**估值更高、风险更大的时候**建议多投钱。散户亏损很大一部分正是"行情好时加仓，回调时割肉"。系统主动推这个，会**系统性放大用户的顺周期行为**。这是本功能最大的危险。

**利益冲突观感。** "建议你多投钱"在观感上接近诱导交易，把系统从"研究工具"往"劝你多投入的东西"推。

### 11.3 若开启主动推送，六条强制约束

| # | 约束 | 理由 |
|---|---|---|
| 1 | 默认关闭，显式开启 | 与实盘开关同级 |
| 2 | **双向**：既提示可加码，也提示可减码/留更多现金 | 只推一个方向就是助推追高 |
| 3 | 触发条件是**机会质量**不是**涨幅** | "便宜的好标的多"而非"最近涨得好" |
| 4 | 强制展示反面信息 | 当前估值分位、距高点位置、信号出现后 60 日表现分布（含亏损情形） |
| 5 | 长冷却期 + 明确"不必立即行动" | 强制冷静，对抗冲动 |
| 6 | **绝不给具体金额** | 只说"可评估是否调整投入"，不说"建议加投 5 万" |

第 3 条是关键。触发信号定义为：

```python
def opportunity_quality(scores, valuations, cfg) -> float:
    """机会质量 = 高分标的的数量 × 其估值便宜程度。
    ★ 不含任何近期涨幅项 —— 涨幅高恰恰是该谨慎的信号。"""
    high_score = [s for s in scores if s.fused >= cfg.min_score]
    cheap = [s for s in high_score if valuations[s.symbol].pct_rank < 0.40]
    return len(cheap) / len(scores)
```

### 11.4 被动响应：用户发起的投入评估

用户问"现在适合提高投入吗"，系统给一份**带完整反面信息的评估**，而非一个"该/不该"的结论：

```markdown
# 投入额评估 2026-09-01

你当前投入：3 万 / 账户 10 万（30%）

### 当前市场位置（必须先看这个）
- 沪深300 估值分位：68%（偏高）
- 距近一年高点：-4%
- 机会质量信号：0.22（中性；高分且便宜的标的占比）

### 若提高投入，历史参照
- 类似信号（估值分位 60-70%）出现后 60 日：
  - 上涨概率 52%，中位收益 +1.8%
  - **下跌超 10% 的概率 18%**

### 结论
当前估值偏高，不是明显的加码窗口。若你出于自身现金规划想提高投入，
建议分批而非一次性。系统不对"该投多少本金"给建议——这取决于你的
风险承受度与资金安排，超出系统能力范围。
```

**最后一句是刻意的**：投入多少本金取决于用户的整体财务状况（收入稳定性、其他资产、负债、风险承受度），这些系统一概不知道，所以**不给具体投入金额建议**，只给市场位置这一个维度的客观信息。

### 11.5 边界：与 `REC_STANCE_UP` 的区别

必须分清（容易混淆）：

| | `REC_STANCE_UP`（8.4） | 本节投入额调整 |
|---|---|---|
| 动的钱 | `investable` 内留的现金 | **`investable` 本身**（会动到未投入资金） |
| 谁的钱 | 用户已承诺投入的 | 用户明确"先不投"的 |
| 默认 | 开启 | 被动开、主动关 |

`REC_STANCE_UP` 是执行既定承诺；本节是**建议用户改变承诺**。后者敏感得多。

### 11.6 验收清单（P5）

- [ ] 被动响应默认开启，主动推送默认关闭
- [ ] 主动推送开启需独立配置项（与实盘开关同级）
- [ ] 主动推送为**双向**（加码/减码都触发），有测试
- [ ] 触发信号基于机会质量，**不含近期涨幅项**（代码审查 + 测试）
- [ ] 输出强制含估值分位、距高点、历史表现分布（含亏损）
- [ ] **绝不输出具体投入金额**（有测试）
- [ ] 被动响应明确声明"投入多少本金超出系统能力范围"
