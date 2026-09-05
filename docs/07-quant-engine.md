# 07 — 量化引擎

## 1. 设计原则

### 1.1 因子计算必须是纯函数

```python
# ✅ 纯函数：输入 DataFrame，输出 DataFrame
def momentum_20d(prices: pl.DataFrame) -> pl.DataFrame:
    return prices.with_columns(
        (pl.col("close") / pl.col("close").shift(20) - 1)
        .over("security_id")
        .alias("mom_20d")
    )

# ❌ 禁止：函数内部查数据库
def momentum_20d(symbols: list[str], date: date) -> pl.DataFrame:
    prices = db.query(...)     # 无法单元测试，无法保证 PIT
```

理由：纯函数可以用构造数据测试，可以保证不引入未来函数（数据由调用方按 PIT 提供），可以在回测和实时中共用。

### 1.2 因子必须版本化

因子公式改了就是新因子。旧因子值不删除，新因子用新 `code_version`。

理由：如果因子定义静默变化，历史回测结果就无法复现，也无法判断策略衰减是因为市场变了还是因子改了。

### 1.3 不预测价格，预测分布

预测目标见第 4 节。核心：输出概率和期望，不输出点估计价格。

## 2. 因子库

### 2.1 因子分类与清单

#### 动量类

| 因子 | 定义 | 备注 |
|---|---|---|
| `mom_5d` | 5 日收益率 | 短期，A 股常呈反转 |
| `mom_20d` | 20 日收益率 | |
| `mom_60d` | 60 日收益率 | |
| `mom_120d` | 120 日收益率 | |
| `mom_20d_ex1w` | 剔除最近 5 日的 20 日动量 | 剔除短期反转干扰 |
| `rel_str_sector` | 相对所属行业的超额收益 | |
| `rel_str_market` | 相对市场基准的超额收益 | |
| `dist_from_high_252d` | 距 252 日最高价的距离 | 新高突破逻辑 |
| `dist_from_low_252d` | 距 252 日最低价的距离 | |
| `ma_cross_5_20` | 5 日与 20 日均线关系 | |
| `trend_slope_60d` | 60 日线性回归斜率（标准化） | |
| `trend_r2_60d` | 上述回归的 R²，衡量趋势质量 | 高 R² = 趋势平滑 |

#### 反转类（A 股重点）

| 因子 | 定义 | 备注 |
|---|---|---|
| `rev_1d` | 前 1 日收益率的负值 | |
| `rev_5d` | 前 5 日收益率的负值 | A 股短期反转显著 |
| `rev_overnight` | 隔夜收益率 | |
| `rev_intraday` | 日内收益率 | 隔夜/日内分解 |
| `max_ret_20d` | 20 日内单日最大涨幅 | 彩票效应，通常负向 |

#### 波动率类

| 因子 | 定义 | 备注 |
|---|---|---|
| `vol_20d` | 20 日收益率标准差 | |
| `vol_60d` | 60 日 | |
| `vol_ratio_20_60` | 短期/长期波动率比 | 波动率放大信号 |
| `downside_vol_60d` | 下行波动率 | |
| `max_dd_60d` | 60 日最大回撤 | |
| `beta_252d` | 对基准的 beta | |
| `idio_vol_252d` | 剔除市场后的残差波动 | |
| `skew_60d` | 收益率偏度 | |
| `kurt_60d` | 峰度 | |

#### 成交量与流动性类

| 因子 | 定义 | 备注 |
|---|---|---|
| `turnover_20d` | 20 日平均换手率 | A 股换手率因子有效性较强 |
| `turnover_ratio_5_60` | 换手率短长期比 | 关注度突变 |
| `amount_20d` | 20 日平均成交额 | 也用于流动性过滤 |
| `volume_trend_20d` | 成交量趋势 | |
| `amihud_illiq_20d` | Amihud 非流动性指标 | \|收益\| / 成交额 |
| `vol_price_corr_20d` | 量价相关性 | |

#### 资金流类（A 股特色）

| 因子 | 定义 | 备注 |
|---|---|---|
| `main_flow_5d` | 5 日主力净流入 / 流通市值 | |
| `main_flow_20d` | 20 日 | |
| `large_order_ratio_20d` | 大单占比 | |
| `northbound_chg_20d` | 北向持股变化 | 数据可得性需确认 |
| `flow_momentum` | 资金流的动量 | |

#### 价值类

| 因子 | 定义 | 备注 |
|---|---|---|
| `ep_ttm` | 1 / PE_TTM（盈利收益率） | 用倒数避免 PE 为负时的处理问题 |
| `bp` | 1 / PB | |
| `sp_ttm` | 1 / PS_TTM | |
| `cfp_ttm` | 经营现金流 / 市值 | |
| `dividend_yield` | 股息率 | |
| `ep_pct_5y` | EP 的 5 年历史分位 | 相对自身历史的估值水平 |
| `pb_pct_sector` | PB 在所属行业的分位 | 相对同业 |
| `ev_ebitda` | 企业价值倍数 | |

#### 质量类

| 因子 | 定义 | 备注 |
|---|---|---|
| `roe_ttm` | 净资产收益率 | |
| `roa_ttm` | 总资产收益率 | |
| `roic_ttm` | 投入资本回报率 | |
| `gross_margin` | 毛利率 | |
| `net_margin` | 净利率 | |
| `margin_stability_3y` | 毛利率 3 年标准差（负向） | 稳定性 |
| `ocf_to_profit` | 经营现金流 / 净利润 | ★ 盈利质量核心指标 |
| `accruals` | 应计项目 / 总资产（负向） | 盈余管理信号 |
| `debt_to_asset` | 资产负债率 | |
| `interest_coverage` | 利息保障倍数 | |
| `asset_turnover` | 资产周转率 | |
| `goodwill_to_asset` | 商誉占比（负向） | A 股商誉减值风险 |

#### 成长类

| 因子 | 定义 | 备注 |
|---|---|---|
| `revenue_yoy` | 营收同比 | |
| `revenue_yoy_ttm` | TTM 营收同比 | |
| `profit_yoy` | 净利润同比 | |
| `profit_yoy_deducted` | 扣非净利润同比 | 更真实 |
| `revenue_growth_3y_cagr` | 3 年营收复合增速 | |
| `growth_acceleration` | 增速的二阶变化 | 加速/减速 |
| `growth_stability` | 增速的历史稳定性 | |

#### 财报事件类

| 因子 | 定义 | 备注 |
|---|---|---|
| `days_since_report` | 距最近财报的交易日数 | 用于避开财报窗口 |
| `days_to_next_report` | 距下次财报（预估） | |
| `earnings_surprise` | 实际 vs 一致预期（若有预期数据） | 数据可得性待确认 |
| `revision_flag` | 最近财报是否为重述版本 | 风险信号 |

#### 新闻/事件类（来自 Agent 层，独立标记）

| 因子 | 定义 | 备注 |
|---|---|---|
| `news_count_5d` | 5 日新闻数量 | 关注度代理 |
| `news_count_zscore` | 新闻数量的异常度 | 突发关注 |
| `event_impact_5d` | 5 日事件影响加权和 | 来自 `event` 表 |
| `announcement_count_20d` | 公告数量 | |
| `negative_event_flag` | 是否有负面事件 | |

**重要**：新闻类因子来自 LLM 抽取，其可靠性与价格类因子不同级。必须单独评估 IC，不能直接混入。

### 2.2 因子实现规范

```python
from typing import Protocol
import polars as pl

class Factor(Protocol):
    code: str
    name: str
    category: str
    version: str
    lookback_days: int              # 需要的历史长度
    required_columns: list[str]     # 依赖的输入列

    def compute(self, data: FactorInput) -> pl.Series:
        """纯函数。输入已按 PIT 准备好的面板数据，输出因子值。"""
        ...

class FactorInput(BaseModel):
    """因子计算的输入契约。所有数据已按 as_of 过滤。"""
    prices: pl.DataFrame          # security_id, trade_date, ohlcv, ...
    financials: pl.DataFrame | None = None
    valuations: pl.DataFrame | None = None
    money_flow: pl.DataFrame | None = None
    events: pl.DataFrame | None = None
    industry: pl.DataFrame | None = None
    as_of: date
```

### 2.3 因子处理流程

```
原始因子值
    ↓
① 异常值处理（MAD 去极值）
    ↓
② 缺失值处理
    ↓
③ 中性化（可选：行业、市值）
    ↓
④ 标准化（截面 zscore 或 rank）
    ↓
最终因子值
```

**① 去极值**

```python
def winsorize_mad(s: pl.Series, n: float = 3.0) -> pl.Series:
    """MAD 法去极值。比标准差法更稳健。"""
    med = s.median()
    mad = (s - med).abs().median()
    upper, lower = med + n * 1.4826 * mad, med - n * 1.4826 * mad
    return s.clip(lower, upper)
```

**② 缺失值**

| 情形 | 处理 |
|---|---|
| 财务数据缺失（未披露） | 保持 NaN，不填充。LightGBM 原生支持缺失值 |
| 价格数据缺失（停牌） | 前值填充，但标记 `is_stale` |
| 因子无法计算（历史不足） | NaN，且该股当日不进入选股池 |

**禁止用截面均值填充财务缺失值**。这会让缺失变成"平均水平"，掩盖信息（很多时候缺失本身就是信号）。

**③ 中性化**

```python
def neutralize(
    factor: pl.Series,
    industry_dummies: pl.DataFrame,
    log_mktcap: pl.Series,
) -> pl.Series:
    """对行业和市值做横截面回归，取残差。"""
    X = pl.concat([industry_dummies, log_mktcap.to_frame()], how="horizontal")
    return residual_of_ols(factor, X)
```

是否中性化取决于因子用途：
- 单因子测试：中性化后更能看出因子本身的效果
- 入模型：可以不中性化，让模型自己学（但要同时提供行业和市值特征）

**④ 标准化**

优先用 `rank_pct`（截面分位）而非 zscore。理由：分位对分布形态不敏感，A 股很多因子分布严重偏斜。

## 3. 因子评估

### 3.1 单因子测试流程

在因子入库前必须通过测试。

```python
class FactorTestResult(BaseModel):
    factor_code: str
    period: tuple[date, date]

    # IC 分析
    ic_mean: float                 # IC 均值
    ic_std: float
    icir: float                    # IC 均值 / IC 标准差
    ic_t_stat: float
    ic_p_value: float
    ic_positive_ratio: float       # IC > 0 的期数占比

    # 分层测试
    quantile_returns: list[float]  # 各分位组的平均收益
    monotonicity: float            # 单调性指标
    long_short_return: float       # 多空组合收益
    long_short_sharpe: float

    # 稳定性
    ic_decay: list[float]          # IC 随预测期衰减
    ic_by_year: dict[int, float]   # 分年度 IC
    ic_by_regime: dict[str, float] # 分市场状态 IC

    # 换手与容量
    autocorrelation: float         # 因子自相关（决定换手率）
    turnover_estimate: float

    # 与已有因子的关系
    correlations: dict[str, float] # 与其他因子的相关性
```

### 3.2 准入标准

| 指标 | 门槛 | 说明 |
|---|---|---|
| `ic_mean` 绝对值 | ≥ 0.02 | 低于此值实用价值有限 |
| `ic_t_stat` 绝对值 | ≥ 2.0 | 统计显著 |
| `ic_positive_ratio` | ≥ 0.55 或 ≤ 0.45 | 方向一致性 |
| `icir` 绝对值 | ≥ 0.3 | 稳定性 |
| 分层单调性 | 明显 | 分位组收益应大致单调 |
| 与已有因子相关性 | < 0.7 | 高相关的因子不重复入库 |
| 分年度一致性 | 至少 60% 年份同向 | 避免只在某段时间有效 |

### 3.3 因子衰减监控

因子会失效。需要持续监控：

```sql
-- 每月计算各因子近期 IC，与历史对比
CREATE TABLE factor_monitor (
    factor_id     INT NOT NULL REFERENCES factor_def(factor_id),
    period_end    DATE NOT NULL,
    window_months INT NOT NULL,
    ic_mean       NUMERIC(10,6),
    ic_t_stat     NUMERIC(10,6),
    -- 与历史基准对比
    hist_ic_mean  NUMERIC(10,6),
    decay_ratio   NUMERIC(10,6),      -- 近期 IC / 历史 IC
    status        TEXT NOT NULL,      -- 'healthy'|'weakening'|'failed'
    PRIMARY KEY (factor_id, period_end, window_months)
);
```

告警规则：近 6 个月 IC 的绝对值 < 历史 IC 绝对值的 50%，或符号反转 → 标记 `weakening`。

## 4. 预测目标

### 4.1 为什么不预测价格

预测"明天收盘价 193.28"的问题：
- 无法评估好坏（差 1% 算准还是不准？）
- 无法用于决策（知道点估计不知道分布，无法算风险）
- 精度虚假（价格是随机游走为主，点预测的精度是幻觉）

### 4.2 预测目标定义

```python
class PredictionTarget(BaseModel):
    """一次预测的完整输出。"""
    symbol: str
    as_of_date: date
    model_id: int

    horizons: dict[str, HorizonPrediction]

class HorizonPrediction(BaseModel):
    horizon: Literal["1d", "5d", "20d"]

    # 主要目标：方向概率
    prob_up: float = Field(ge=0, le=1, description="超额收益 > 0 的概率")

    # 次要目标：期望值
    expected_excess_return: float = Field(description="相对基准的期望超额收益")

    # 分布信息
    expected_vol: float
    quantiles: dict[str, float]      # {"p10": -0.05, "p50": 0.01, "p90": 0.08}

    # 校准信息
    confidence: float = Field(description="模型对此预测的置信度")
```

### 4.3 标签定义（关键细节）

标签定义的细节决定模型学什么。

```python
def make_label(
    prices: pl.DataFrame,
    horizon: int,
    benchmark: pl.DataFrame,
    *,
    label_type: str = "excess_binary",
) -> pl.Series:
    """
    ★ 关键约定：
    1. 用超额收益而非绝对收益 —— 否则模型学的是"市场会不会涨"
    2. 用 T+1 开盘价买入、T+1+h 开盘价卖出 —— 反映真实可执行性
    3. 涨停/停牌日不可买入 → 该样本标签置 NaN，排除
    4. 退市股票在退市前的样本保留（避免生存者偏差）
    """
    ...
```

**为什么用超额收益**：如果标签是绝对收益，模型会把"市场整体上涨的时段"学成特征，实际上是在预测大盘。用超额收益（相对基准或相对行业）才能学到选股能力。

**为什么用开盘价而非收盘价**：决策在 T 日收盘后做，最早能在 T+1 开盘执行。用 T 日收盘价计算收益是典型的未来函数。

**为什么排除涨停日样本**：如果 T+1 开盘涨停，实际买不进。把这些样本留在训练集里，模型会学到"买涨停股赚钱"，而这在实盘不可执行。

### 4.4 三个预测期的用途

| Horizon | 用途 | 特点 |
|---|---|---|
| 1d | 执行时机参考 | 噪声大，IC 低，主要用于择时微调 |
| 5d | 主要决策依据 | 平衡信噪比与换手率 |
| 20d | 持仓期判断 | IC 通常更高，但换手率低 |

首版以 5d 为主决策依据。

## 5. 模型演进

### 5.1 强制顺序

**必须按此顺序，每一级都要有完整评估结果，才允许进入下一级。**

| Level | 模型 | 目的 | 准入条件 |
|---|---|---|---|
| L0 | Buy & Hold 基准 | 建立参照 | — |
| L0 | 等权池 / 市值加权 | 建立参照 | — |
| L1 | 单因子排序 | 验证数据管道与回测正确性 | L0 完成 |
| L2 | 多因子线性组合（等权 / IC 加权） | 建立可解释基线 | L1 有 ≥5 个通过测试的因子 |
| L3 | Logistic Regression / Ridge | 引入统计学习 | L2 结果可复现 |
| L4 | **LightGBM** | 主力模型 | L3 完成，L4 样本外必须优于 L2 |
| L5 | XGBoost / CatBoost 对比 | 模型选择 | L4 稳定 |
| L6 | 集成（多模型 blend） | 提升稳定性 | L5 完成 |
| L7 | LSTM / Transformer | 探索 | **L6 完成且有明确假设说明为何序列模型会更好** |

### 5.2 为什么严格要求顺序

如果直接上 LightGBM 并得到不错的回测，你无法回答：
- 这个效果来自模型，还是仅仅来自某一个强因子？
- 相比简单的等权组合，复杂度换来了多少提升？
- 回测好是因为模型好，还是因为管道里有 bug（未来函数）？

**L1 单因子测试的真正价值不是找到有效因子，而是验证整套管道正确。** 如果单因子回测的结果与单因子 IC 分析不一致，说明回测引擎有问题。

### 5.3 L7 的门槛

深度学习模型必须回答：**你假设序列中有什么结构是 GBDT 学不到的？**

如果答不出来（只是"想试试"），就不做。理由：
- 参数量大，过拟合风险高，且难以察觉
- 训练成本高，迭代慢
- 可解释性差，出问题难排查
- 在表格类金融数据上，GBDT 通常不输给深度模型

## 6. 模型训练规范

### 6.1 Walk-Forward 切分

```
时间轴 ──────────────────────────────────────────────────▶

第1轮  [═══ Train ═══][Val][Test]
第2轮       [═══ Train ═══][Val][Test]
第3轮            [═══ Train ═══][Val][Test]
...
封存期                                        [══ Holdout ══]
                                              ★ 只在最终验证时用一次
```

```python
class WalkForwardConfig(BaseModel):
    train_months: int = 36
    val_months: int = 6
    test_months: int = 6
    step_months: int = 6
    embargo_days: int = 10        # ★ 训练与验证间的隔离期
    holdout_start: date           # 封存期起始，配置后不可更改
```

**embargo（隔离期）的必要性**：如果预测期是 20 日，训练集最后一天的标签需要用到之后 20 日的数据。若验证集紧接训练集，就会有标签泄漏。隔离期必须 ≥ 最长预测期。

### 6.2 封存期规则

```python
class HoldoutGuard:
    """封存期访问控制。"""

    def __init__(self, holdout_start: date, log_path: Path):
        self.holdout_start = holdout_start
        self.log_path = log_path

    def check_access(self, end_date: date, purpose: str) -> None:
        if end_date >= self.holdout_start:
            uses = self._read_log()
            if len(uses) >= 1:
                raise HoldoutViolation(
                    f"封存期已使用过 {len(uses)} 次:\n"
                    + "\n".join(f"  {u.date} - {u.purpose}" for u in uses)
                    + "\n再次使用将使封存期失去意义。"
                )
            self._log_use(purpose)
```

这不是技术限制（可以绕过），而是**给自己设的障碍**。看到这个异常时会被强制提醒：你正在消耗最后的客观性。

### 6.3 防过拟合措施

| 措施 | 说明 |
|---|---|
| 参数搜索次数记录 | 每次调参写入 `backtest_run.param_search_count`，累计值越大结果越不可信 |
| 限制超参搜索空间 | LightGBM 只调 5-6 个关键参数，不做大规模网格搜索 |
| 特征数量控制 | 特征数 << 样本数；避免上百个高度相关的特征 |
| 早停基于验证集 | 不基于测试集 |
| 多轮 walk-forward 一致性 | 各轮结果差异大 = 不稳定 = 可能过拟合 |
| 简单模型对照 | 复杂模型必须显著优于 L2 等权组合才有意义 |
| 参数敏感性检查 | 参数微调导致结果剧变 = 过拟合信号 |

### 6.4 特征重要性与稳定性

```python
class ModelDiagnostics(BaseModel):
    feature_importance: dict[str, float]
    importance_stability: float      # 各 walk-forward 轮次间重要性的相关性
    shap_summary: dict[str, float] | None

    # 稳定性检查
    prediction_correlation_across_folds: float
    performance_variance_across_folds: float
```

`importance_stability` 是重要诊断：如果每轮训练出来的重要特征完全不同，说明模型在拟合噪声。

## 7. 目录结构

```
quant/
├── features/
│   ├── __init__.py
│   ├── base.py                # Factor 协议、FactorInput
│   ├── registry.py            # 因子注册表
│   ├── momentum.py
│   ├── reversal.py
│   ├── volatility.py
│   ├── volume.py
│   ├── flow.py
│   ├── value.py
│   ├── quality.py
│   ├── growth.py
│   ├── event.py
│   └── transform.py           # 去极值/中性化/标准化
│
├── models/
│   ├── base.py                # Model 协议
│   ├── baseline.py            # L0/L1/L2
│   ├── linear.py              # L3
│   ├── gbdt.py                # L4/L5
│   ├── ensemble.py            # L6
│   ├── registry.py            # 模型版本管理
│   └── diagnostics.py
│
├── labels/
│   ├── __init__.py
│   └── targets.py             # 标签构造（含涨停排除逻辑）
│
├── training/
│   ├── walk_forward.py
│   ├── holdout_guard.py
│   └── trainer.py
│
├── evaluation/
│   ├── ic.py                  # IC / ICIR / t 检验
│   ├── quantile.py            # 分层测试
│   ├── decay.py               # IC 衰减
│   └── report.py              # 因子测试报告生成
│
└── store/
    ├── feature_store.py       # Parquet + DuckDB
    └── panel.py               # 面板数据构造
```

## 8. Feature Store

### 8.1 存储布局

```
data/features/
├── cn/
│   ├── panel/
│   │   ├── year=2020/part-0.parquet
│   │   ├── year=2021/part-0.parquet
│   │   └── ...
│   └── meta/
│       └── factor_versions.json
└── us/
    └── ...
```

按年分区，列式存储。每个 Parquet 包含：`security_id, trade_date, factor_1, factor_2, ...` 及 `code_version`。

### 8.2 读取（DuckDB 加速）

```python
class FeatureStore:
    def load_panel(
        self,
        market: str,
        factors: list[str],
        start: date,
        end: date,
        *,
        as_of: date,          # 用于校验，确保不读超过 as_of 的数据
    ) -> pl.DataFrame:
        assert end <= as_of, f"Cannot load features beyond as_of={as_of}"
        cols = ", ".join(["security_id", "trade_date", *factors])
        return duckdb.sql(f"""
            SELECT {cols}
            FROM read_parquet('data/features/{market}/panel/**/*.parquet')
            WHERE trade_date BETWEEN '{start}' AND '{end}'
        """).pl()
```

### 8.3 增量更新

```python
async def update_features(as_of: date, market: str) -> None:
    """每日增量计算。只算新的一天，不重算历史。"""
    lookback = max(f.lookback_days for f in registry.all())
    data = await repo.get_panel(
        start=calendar.prev_trading_day(as_of, lookback),
        end=as_of,
        as_of=as_of,                        # ★ PIT
    )
    values = {f.code: f.compute(data) for f in registry.all()}
    store.append(as_of, values, market)
```

**重算触发条件**：因子代码变更时必须全量重算（新 `code_version`），不能混用不同版本的因子值。

## 9. Quant 与 Agent 的接口

Agent 通过工具读取 Quant 输出，但 Quant 不依赖 Agent。

```python
def get_quant_signals(symbols: list[str], *, as_of: date) -> ToolResult:
    """给 Agent 的量化信号工具。"""
    preds = repo.get_predictions(symbols, as_of=as_of, horizon="5d")
    factors = store.load_snapshot(symbols, as_of=as_of, factors=KEY_FACTORS)
    return ToolResult(
        data=[
            {
                "symbol": s,
                "prob_up_5d": p.prob_up,
                "expected_excess_5d": p.expected_excess_return,
                "expected_vol": p.expected_vol,
                # 因子分位，便于 Agent 理解
                "momentum_pct": f["mom_20d_rank"],
                "value_pct": f["ep_ttm_rank"],
                "quality_pct": f["roe_ttm_rank"],
                "model_id": p.model_id,          # 溯源
            }
            ...
        ],
        units={"prob_up_5d": "probability", "expected_excess_5d": "decimal_return"},
        note="prob_up 为超额收益为正的概率，非绝对收益",
    )
```

注意 `note` 字段：明确告知 Agent 这是超额收益概率，避免它误读为绝对涨跌概率。

**唯一的例外方向**：新闻/事件类因子来自 Agent 层（NewsExtractor 的输出）。这是有意为之的单点耦合，且这类因子必须单独标记和评估。

## 10. 验收清单

L1 阶段（P3 Gate）：

- [ ] 至少 20 个因子实现且通过单元测试
- [ ] 每个因子有完整的 `FactorTestResult`
- [ ] 至少 5 个因子达到准入标准
- [ ] 因子相关矩阵已计算，无冗余因子入库
- [ ] 因子计算为纯函数，不含数据库访问
- [ ] 标签构造正确排除涨停/停牌样本
- [ ] Walk-forward 切分含 embargo
- [ ] 封存期已定义且访问受控
- [ ] L2（等权多因子）结果作为基线记录
- [ ] L4（LightGBM）样本外 IC 显著优于 L2
- [ ] 模型诊断报告含特征重要性稳定性
- [ ] `param_search_count` 已记录
- [ ] Feature Store 增量更新正常，因子版本一致
