# 05 — 多市场配置

## 1. 为什么配置驱动

系统要先做 A 股、后移植美股。如果市场规则散落在代码里，移植时就要改遍全项目。

**约定：代码中不出现任何市场判断分支，所有差异通过 `MarketConfig` 注入。**

```python
# ❌ 禁止
if market == "CN":
    limit = 0.10
elif market == "US":
    limit = None

# ✅ 要求
limit = cfg.price_limit.for_security(sec, as_of)
```

前者加市场要改代码，后者加市场只需加配置文件。

## 2. A 股 vs 美股差异矩阵

| 维度 | A 股 | 美股 | 对系统的影响 |
|---|---|---|---|
| **交易时段** | 09:30-11:30, 13:00-15:00 | 09:30-16:00（连续） | 分钟线切片、盘中任务调度 |
| **午间休市** | 有 | 无 | 分钟线不连续，指标计算需注意 |
| **盘前盘后** | 无（集合竞价除外） | 有（04:00-09:30, 16:00-20:00） | 美股需决定是否使用 |
| **结算** | T+1（当日买入次日可卖） | T+1 结算但**当日可卖** | ★ 回测撮合逻辑根本差异 |
| **涨跌停** | 主板 ±10%、创业板/科创板 ±20%、ST ±5%、新股首日特殊 | 无（仅有熔断机制） | ★ 回测成交可行性判断 |
| **停牌** | 频繁（重大事项、股价异动） | 较少 | 需处理停牌期间的持仓估值 |
| **最小单位** | 买入 100 股整手（科创板 200，需核实），卖出可零股 | 1 股，部分券商支持碎股 | 仓位取整逻辑；★ 决定小资金可行持仓数 |
| **做空** | 个人融券基本不可得 | 可做空 | 组合构建是否允许负权重 |
| **T+0** | 不可（同日买卖同一标的） | 可（受 PDT 规则限制） | 换手率上限 |
| **PDT 规则** | 无 | 账户 < 2.5 万美元时，5 日内日内交易 ≤3 次 | 美股小资金需注意 |
| **交易费用** | 佣金（万2.5左右，最低5元）+ 卖出印花税 0.1% + 过户费 | 多数券商零佣金；SEC 费 + FINRA TAF | 成本模型差异 |
| **税** | 卖出印花税 0.1%（单边） | 无交易税（有资本利得税，不在回测范围） | — |
| **货币** | CNY | USD | 多币种账户处理 |
| **行业分类** | 申万（31 一级）/ 中信 | GICS（11 sector） | 分类映射 |
| **概念板块** | 极重要（东财/同花顺口径） | 相对次要 | ★ A 股需 ThemeAgent |
| **投资者结构** | 散户占比高 | 机构主导 | ★ 因子有效性差异 |
| **常见异象** | 反转效应、小市值效应、题材炒作 | 动量效应、质量因子 | ★ 策略不可直接移植 |
| **财报频率** | 季报（Q1/H1/Q3/年报） | 季报（10-Q/10-K） | 财务日历不同 |
| **财报语言** | 中文 | 英文 | LLM 与 embedding 选择 |
| **数据可得性** | 资金流、龙虎榜等特色数据 | 期权链、机构持仓 13F | 因子来源不同 |

### 2.1 三个最关键的差异

**① T+1 与当日可卖**

A 股当日买入的股票次日才能卖。这不只是回测细节，它改变策略空间：
- 无法当日纠错
- 隔夜风险强制承担
- `position.sellable_qty` 必须独立跟踪

**② 涨跌停不可成交**

这是 A 股回测最大的陷阱。涨停时买不进、跌停时卖不出，而策略最想买的往往正是涨停的股票。

不模拟这一点，回测收益会**系统性高估**，且幅度可能远超滑点影响。动量策略尤其严重。

**③ 因子有效性不可跨市场假定**

A 股散户主导、情绪驱动，短期反转效应明显；美股机构主导，动量更持续。同一个因子在两个市场可能符号相反。

结论：**移植是工程框架移植，策略必须重新验证。** 见 [08-backtest-eval](08-backtest-eval.md)。

### 2.2 整手约束对组合构建的影响（易被忽略）

A 股买入 100 股整手看起来是小细节，但它**决定了小资金用户能持有多少标的**。

```
单票可买最高股价 = capital × max_single_weight / min_lot_buy
```

| 资金 | 单票上限 10% | 主板（100 股） | 科创板（200 股） |
|---|---|---|---|
| 5 万 | 5,000 元 | ≤ 50 元/股 | ≤ 25 元/股 |
| 10 万 | 10,000 元 | ≤ 100 元/股 | ≤ 50 元/股 |
| 20 万 | 20,000 元 | ≤ 200 元/股 | ≤ 100 元/股 |

资金 5 万买一手 100 元的主板股票就是 20% 权重——**违反单票上限，会被 RiskEngine 拒掉**。

三个连带影响：

| 影响 | 说明 |
|---|---|
| `top_n` 不能是常量 | 必须由资金量推导，见 [09-portfolio-risk](09-portfolio-risk.md) 8.3 |
| 组合层需可执行性筛选 | 一手金额超上限的标的应提前排除 |
| 佣金最低 5 元形成隐性下限 | 单笔 3,000 元时佣金占 0.17%，是标准费率数倍 |

美股无此问题（1 股起，部分券商支持碎股），这是 A 股特有的组合构建约束。

### 2.3 板块交易权限门槛（A 股特有）

比整手更硬的约束：**部分板块开户就有资金与经验门槛**。整手是"买不满一手"，权限是"一股都买不了"。

| 板块 | 资金门槛（20 日日均） | 交易经验 | 风险等级 | 其他 |
|---|---|---|---|---|
| 主板 `main` | 无 | 无 | 基础匹配 | 开户即得 |
| 创业板 `gem` | 10 万 | 24 个月 | C4 及以上 | 知识测评 + 签风险揭示书 |
| 科创板 `star` | 50 万 | 24 个月 | C4 及以上 | 知识测评 **80 分** + 签风险揭示书 |
| 北交所 `bse` | 50 万 | 24 个月 | C4 及以上 | 知识测评 + 签风险揭示书 |

> **已核实（2026-09-03）**。资金门槛看的是**申请前 20 个交易日的日均资产**（含股票/基金/现金/理财，不含融资借入），不是某天存够即可。科创板知识测评需 80 分。这些是 `eligibility` 门槛提示文案的依据，也说明为什么默认最保守——多数散户账户开不了创业板以上。

系统在 A 股阶段无交易 API，**无法自动探知用户开通了哪些板块**，所以做成用户声明式配置，默认最保守（仅主板）：

```yaml
# config/user/eligibility_cn.yaml
market: CN
tradable_boards: [main]      # ★ 默认仅主板；star/gem/bse 需用户显式加入
```

两个关键行为（详见 [09-portfolio-risk](09-portfolio-risk.md) 3.3a）：

- **研究分析保留全部板块**（科创板龙头影响市场判断）
- **建仓推荐按 eligibility 过滤**，被排除的标的仍展示，提示"开通后可解锁"

这属于市场配置与用户配置的交叉：板块门槛规则是市场属性，用户开通状态是用户属性。

## 3. 配置文件规范

### 3.1 Schema 定义

```python
from datetime import time
from typing import Literal
from pydantic import BaseModel, Field

class Session(BaseModel):
    start: time
    end: time

class PriceLimitRule(BaseModel):
    """涨跌停规则。按条件匹配，取第一个命中的。"""
    condition: str          # 'board==star' | 'is_st' | 'days_since_ipo<=1' | 'default'
    limit_up: float | None  # None 表示无限制
    limit_down: float | None

class PriceLimitConfig(BaseModel):
    enabled: bool
    rules: list[PriceLimitRule]

    def for_security(self, sec: SecurityMeta, as_of: date) -> tuple[float | None, float | None]:
        if not self.enabled:
            return None, None
        for rule in self.rules:
            if self._match(rule.condition, sec, as_of):
                return rule.limit_up, rule.limit_down
        raise ConfigError("No matching price limit rule")

class FeeConfig(BaseModel):
    commission_rate: float = 0.0
    commission_min: float = 0.0
    commission_max: float | None = None
    stamp_duty_buy: float = 0.0
    stamp_duty_sell: float = 0.0
    transfer_fee_rate: float = 0.0
    regulatory_fee_sell: float = 0.0       # 美股 SEC fee
    other_fee_per_share: float = 0.0       # 美股 FINRA TAF

class SlippageConfig(BaseModel):
    model: Literal["fixed_bps", "volume_share", "spread_based"]
    fixed_bps: float = 5.0
    max_volume_share: float = 0.05         # 单笔不超过当日成交量的比例

class MarketConfig(BaseModel):
    market: Literal["CN", "US", "HK"]
    name: str
    timezone: str
    currency: str

    sessions: list[Session]
    has_pre_market: bool = False
    has_post_market: bool = False

    settlement: Literal["T+0", "T+1", "T+2"]
    same_day_sell_allowed: bool            # ★ 与 settlement 独立
    allow_day_trade: bool

    price_limit: PriceLimitConfig
    min_lot_buy: int                       # 默认值（主板）
    min_lot_buy_by_board: dict[str, int]    # ★ 按板块覆盖
    min_lot_sell: int
    allow_fractional: bool

    short_selling_allowed: bool
    margin_allowed: bool

    fees: FeeConfig
    slippage: SlippageConfig

    industry_taxonomy: str
    has_theme_sectors: bool

    calendar_source: str
    benchmark_symbol: str
```

### 3.2 A 股配置

```yaml
# config/markets/cn.yaml
market: CN
name: "中国 A 股"
timezone: "Asia/Shanghai"
currency: "CNY"

sessions:
  - { start: "09:30", end: "11:30" }
  - { start: "13:00", end: "15:00" }
has_pre_market: false
has_post_market: false

settlement: "T+1"
same_day_sell_allowed: false       # ★ 当日买入不可卖
allow_day_trade: false

price_limit:
  enabled: true
  # ★ 现行为全面注册制规则（2023 改革后）。历史回测跨改革点需区分时段，见下方注释。
  rules:
    # 顺序敏感：先匹配特殊情形
    # 注册制：主板/科创板/创业板 新股上市前 5 日均不设涨跌幅
    - condition: "days_since_ipo <= 5 and board in ['main','star','gem']"
      limit_up: null                # 前 5 日无涨跌幅限制
      limit_down: null
      intraday_halt:                # 盘中临时停牌（前 5 日无涨跌幅期间）
        - threshold_from_open: 0.30 # 较开盘价 ±30% 停牌 10 分钟
          duration_min: 10
        - threshold_from_open: 0.60 # 较开盘价 ±60% 再停牌 10 分钟
          duration_min: 10
        resume_if_cross: "14:57"    # 停牌跨越 14:57 于当日 14:57 复牌
    # 北交所：仅上市首日不设涨跌幅，次日起 ±30%
    - condition: "days_since_ipo == 0 and board == 'bse'"
      limit_up: null
      limit_down: null
    - condition: "is_st"
      limit_up: 0.05
      limit_down: -0.05
    - condition: "board in ['star','gem']"
      limit_up: 0.20
      limit_down: -0.20
    - condition: "board == 'bse'"
      limit_up: 0.30
      limit_down: -0.30
    - condition: "default"
      limit_up: 0.10
      limit_down: -0.10

  # 有效申报价格范围（上交所主板新股，废单校验用）
  valid_price_band:
    - condition: "days_since_ipo <= 5 and board == 'main'"
      continuous_auction: { high: 1.44, low: 0.64 }   # 相对发行价
      closing_call_1455_1500: { high: 1.20, low: 0.80 } # 相对当日开盘价

min_lot_buy: 100
min_lot_buy_by_board:              # ★ 按板块覆盖，影响冷启动可执行性（已核实 2026-09-03）
  main: 100                        # 主板：最小 100 股，按 100 股整数倍递增
  gem: 100                         # 创业板：最小 100 股，按 100 股整数倍递增
  star: 200                        # 科创板：最小 200 股，之后按 1 股递增（可 201/202…）
  bse: 100                         # 北交所：最小 100 股，之后按 1 股递增（可 101/102…）
lot_increment_by_board:            # ★ 递增单位（科创板/北交所与主板不同）
  main: 100
  gem: 100
  star: 1                          # 200 股以上可 1 股递增
  bse: 1                           # 100 股以上可 1 股递增
min_lot_sell: 1                    # 卖出可零股
odd_lot_sell_all_at_once: true     # ★ 零股（不足一手）必须一次性全部卖出，不能分批
allow_fractional: false

short_selling_allowed: false
margin_allowed: false

fees:
  commission_rate: 0.00025         # 万2.5，按实际券商调整
  commission_min: 5.0
  stamp_duty_buy: 0.0
  stamp_duty_sell: 0.001           # 卖出印花税 0.1%
  transfer_fee_rate: 0.00001       # 过户费

slippage:
  model: "volume_share"
  fixed_bps: 10.0                  # A 股流动性差异大，给更保守值
  max_volume_share: 0.03

industry_taxonomy: "sw_2021"
has_theme_sectors: true            # ★ A 股概念板块重要

calendar_source: "akshare"
benchmark_symbol: "000300.SH"      # 沪深300
```

> **新股涨跌幅规则已核实（2026-09-03，现行注册制）**：主板/科创板/创业板新股上市**前 5 日均不设涨跌幅**（第 6 日起主板 ±10%、科创板/创业板 ±20%）；北交所仅首日不设、次日起 ±30%。前 5 日设盘中临时停牌（±30%/±60% 各停 10 分钟）。
>
> **两个工程含义**：
> 1. **回测跨注册制改革点（2023）必须区分时段**：旧核准制主板新股首日 +44%/-36% 且前 5 日有限制，现行前 5 日无限制。用错规则会系统性错估新股成交可行性。回测引擎按 `trade_date` 选规则版本，见 [08-backtest-eval](08-backtest-eval.md)。
> 2. **停牌导致止盈止损可能无法执行**：新股前 5 日临时停牌期间无法交易，用户配置的止损/止盈信号会落空。exit_policy 与执行层需处理停牌分支，见 [09-portfolio-risk](09-portfolio-risk.md) 4.2a、[10-execution](10-execution.md)。
> 3. **新股前 5 日波动极大（可能翻倍/腰斩）**：冷启动不建议在上市前 5 日参与，可作为 `derive_top_n` 的一个排除条件。

### 3.3 美股配置

```yaml
# config/markets/us.yaml
market: US
name: "US Equities"
timezone: "America/New_York"
currency: "USD"

sessions:
  - { start: "09:30", end: "16:00" }
has_pre_market: true
has_post_market: true

settlement: "T+1"
same_day_sell_allowed: true        # ★ 与 A 股的关键差异
allow_day_trade: true

price_limit:
  enabled: false
  rules:
    - condition: "default"
      limit_up: null
      limit_down: null

min_lot_buy: 1
min_lot_sell: 1
allow_fractional: true             # Alpaca 支持碎股

short_selling_allowed: true
margin_allowed: false              # 首版禁用杠杆

fees:
  commission_rate: 0.0             # Alpaca 零佣金
  commission_min: 0.0
  stamp_duty_sell: 0.0
  regulatory_fee_sell: 0.0000278   # SEC fee，费率会调整，需定期核实
  other_fee_per_share: 0.000166    # FINRA TAF，有上限

slippage:
  model: "spread_based"
  fixed_bps: 3.0                   # 美股流动性好
  max_volume_share: 0.05

industry_taxonomy: "gics"
has_theme_sectors: false

calendar_source: "alpaca"
benchmark_symbol: "SPY"
```

### 3.4 风控配置（按市场分离）

```yaml
# config/risk/cn.yaml
position_limits:
  max_single_weight: 0.10          # 单股上限 10%
  max_industry_weight: 0.25        # 单行业上限 25%
  max_theme_weight: 0.20           # 单概念上限 20%
  min_positions: 5                 # 最少持仓数（分散化）
  max_positions: 20
  max_total_equity: 0.90           # 最大股票仓位 90%
  min_cash: 0.10

liquidity_limits:
  min_avg_amount_20d: 50000000     # 20 日均成交额 ≥ 5000 万
  max_position_vs_volume: 0.03     # 持仓不超过 20 日均量的 3%
  max_order_vs_volume: 0.05        # 单笔不超过当日量的 5%

exclusions:
  exclude_st: true
  exclude_suspended: true
  exclude_delisting_risk: true
  exclude_days_since_ipo: 60       # 上市不足 60 日不买
  exclude_before_earnings_days: 3  # 财报前 3 日不新建仓
  blacklist_file: "config/risk/blacklist_cn.txt"

drawdown_limits:
  max_daily_loss: 0.03             # 单日亏损 3% 触发保护
  max_drawdown: 0.15               # 最大回撤 15% 触发降仓
  drawdown_action: "reduce_50pct"  # 或 "halt"

turnover_limits:
  max_daily_turnover: 0.20         # 单日换手上限 20%
  max_monthly_turnover: 2.0

concentration:
  max_top5_weight: 0.40
  max_correlation_cluster: 0.35    # 高相关组合上限
```

```yaml
# config/risk/us.yaml
position_limits:
  max_single_weight: 0.08
  max_sector_weight: 0.25
  min_positions: 8
  max_positions: 25
  max_total_equity: 0.90
  min_cash: 0.10

liquidity_limits:
  min_avg_dollar_volume_20d: 20000000
  max_position_vs_volume: 0.02
  max_order_vs_volume: 0.03

exclusions:
  exclude_penny_stocks: true
  min_price: 5.0
  exclude_before_earnings_days: 2
  blacklist_file: "config/risk/blacklist_us.txt"

drawdown_limits:
  max_daily_loss: 0.03
  max_drawdown: 0.15
  drawdown_action: "reduce_50pct"

pdt_protection:                    # ★ 美股特有
  enabled: true
  account_value_threshold: 25000
  max_day_trades_per_5d: 3

turnover_limits:
  max_daily_turnover: 0.25
  max_monthly_turnover: 3.0
```

## 4. 行业分类映射

移植时需要在申万和 GICS 之间建立对应，用于跨市场比较。

```yaml
# config/mappings/industry_sw_gics.yaml
# 注意：这是粗粒度近似映射，仅用于跨市场对比展示，
# 不用于因子计算或风控分组（分组必须用本市场原生分类）。
mappings:
  - sw_l1: "电子"
    gics_sector: "Information Technology"
    gics_industry_group: "Semiconductors & Semiconductor Equipment"
    confidence: "high"
  - sw_l1: "计算机"
    gics_sector: "Information Technology"
    gics_industry_group: "Software & Services"
    confidence: "high"
  - sw_l1: "食品饮料"
    gics_sector: "Consumer Staples"
    confidence: "high"
  - sw_l1: "银行"
    gics_sector: "Financials"
    confidence: "high"
  - sw_l1: "电力设备"
    gics_sector: "Industrials"
    note: "含新能源，与 GICS 分类差异较大"
    confidence: "low"
  - sw_l1: "国防军工"
    gics_sector: "Industrials"
    gics_industry_group: "Capital Goods"
    confidence: "medium"
```

**重要约定**：风控的行业集中度检查必须用**本市场原生分类**。用映射后的分类做风控会引入错误分组。映射只用于展示层的跨市场对比。

## 5. 交易日历

### 5.1 需求

| 场景 | 需要什么 |
|---|---|
| 调度 | 今天是否开市 |
| 回测 | 区间内的交易日序列 |
| 因子 | N 个交易日前是哪天 |
| T+1 | 下一个交易日 |
| 财报 | 距下次财报的交易日数 |

### 5.2 实现

```python
class TradingCalendar:
    def __init__(self, market: str, repo: PITRepository): ...

    def is_trading_day(self, d: date) -> bool: ...
    def next_trading_day(self, d: date, n: int = 1) -> date: ...
    def prev_trading_day(self, d: date, n: int = 1) -> date: ...
    def trading_days(self, start: date, end: date) -> list[date]: ...
    def count_trading_days(self, start: date, end: date) -> int: ...
    def is_session_open(self, ts: datetime) -> bool: ...
```

日历数据必须提前加载（至少到次年年底），且双源校验一致。A 股节假日安排每年国务院公布，需要每年更新。

### 5.3 A 股日历特殊情况

| 情况 | 处理 |
|---|---|
| 春节等长假 | 日历数据必须准确，跨假期收益率计算注意 |
| 调休（周末上班但股市不开） | 以交易所公告为准，不按工作日推断 |
| 临时休市 | 极少但存在，需支持手动覆盖 |

## 6. 多币种处理

P6 之后会同时有 CNY 和 USD 账户。

约定：
- 每个 `account` 有 `base_currency`，账户内不混币
- 不做跨币种组合优化（不同市场是独立组合）
- 汇率仅用于展示层的总资产折算
- 汇率数据独立表，也需 PIT

```sql
CREATE TABLE fx_rate (
    pair          TEXT NOT NULL,      -- 'USDCNY'
    quote_date    DATE NOT NULL,
    rate          NUMERIC(18,8) NOT NULL,
    source        TEXT NOT NULL,
    PRIMARY KEY (pair, quote_date)
);
```

不做跨市场组合优化的理由：需要处理汇率风险、时区错配、相关性估计困难，收益不抵复杂度。两个市场当作两个独立策略跑。

## 7. 新市场接入清单

将来若加港股或其他市场，按此清单执行：

- [ ] 创建 `config/markets/{code}.yaml`
- [ ] 创建 `config/risk/{code}.yaml`
- [ ] 实现该市场的 Collector（行情、财务、日历）
- [ ] 实现代码归一化规则 + 单元测试
- [ ] 导入交易日历（至少 10 年历史 + 未来 1 年）
- [ ] 建立行业分类体系记录
- [ ] 实现 `BrokerAdapter`（或先用 Simulated）
- [ ] 定义股票池
- [ ] 补充成本模型参数（佣金、税费）
- [ ] 跑通 Buy & Hold 基准回测
- [ ] **重新验证所有因子的有效性**（不假定可移植）
- [ ] 更新 `config/mappings/` 行业映射
- [ ] 回归测试：新增市场不影响既有市场结果

最后一项容易忽略但很重要：加市场时的重构可能悄悄改变 A 股的回测结果。必须有基线结果快照做对比。

## 8. 配置校验

配置错误比代码错误更危险（不会报错，只会算错）。

```python
class MarketConfigValidator:
    """加载时校验，不通过则拒绝启动。"""

    def validate(self, cfg: MarketConfig) -> None:
        # 时段不重叠且有序
        self._check_sessions(cfg.sessions)
        # 涨跌停规则必须有 default 兜底
        assert any(r.condition == "default" for r in cfg.price_limit.rules)
        # T+1 与 same_day_sell 的组合合法性
        if cfg.settlement == "T+1" and cfg.same_day_sell_allowed:
            logger.warning(
                "settlement=T+1 但允许当日卖出（美股模式），确认这是预期行为"
            )
        # 费率合理范围
        assert 0 <= cfg.fees.commission_rate < 0.01
        # 时区有效
        ZoneInfo(cfg.timezone)
```

启动时打印配置摘要与哈希，写入 `agent_run.config_hash`，保证决策可复现。
