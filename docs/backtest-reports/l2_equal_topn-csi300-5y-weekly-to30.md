# Portfolio backtest: `l2_equal_topn`

> period 2021-10-14 → 2026-10-13 | top_n=15 | rebalance=weekly (n=255) | code_version=`dev` | param_search_count=0
> Matching: **未校准 — 撮合假设未验证**

## 1. 防偏差检查

- 见 `make test-sentinel`（本报告未重跑）
- 见 `make check-survivorship`（本报告未重跑）
- ✅ 涨跌停约束已接入（本窗涨跌停相关拒单 2 次；总拒单 9）
- ✅ T+1 约束已接入（本窗 t1 相关拒单 0 次）
- ✅ 成本模型含佣金/印花税/过户费/滑点（`MarketConfig.estimate_fees` + fixed_bps）

## 2. 风险

| Metric | Value |
|---|---|
| Max Drawdown | -24.20% |
| MDD 持续天数 | 934 |
| Calmar | -0.074 |
| Volatility (ann.) | +15.36% |
| Sortino | -0.239 |

## 3. 收益

| Metric | Value |
|---|---|
| Total return | -8.61% |
| CAGR | -1.79% |
| Sharpe (rf=2%) | -0.175 |
| End NAV | 913,871.97（初始 1,000,000.00） |
| Trading days | 1211 |

## 4. 稳定性

- 分年度: 2021 -1.63% | 2022 -17.73% | 2023 +1.68% | 2024 +8.13% | 2025 +13.28% | 2026 -9.18%
- 盈利年份: 3/6（无年份序列时为 0/0）
- 最差月份: -9.57%

## 5. 成本与容量

| Metric | Value |
|---|---|
| Total fees | 88,518.28 |
| 成本 / |总收益| | +102.78% |
| 年换手率 | +1231.39% |
| 单笔占成交量 | +0.02% |
| 估计容量 | 2.83 亿 |

容量按平均净值放大到平均单笔成交量占比等于 `max_volume_share`。换手率为单边、按平均净值年化。

### 拒单原因

| Reason | Count |
|---|---:|
| `insufficient cash` | 5 |
| `suspended` | 2 |
| `limit_down_cannot_sell` | 1 |
| `limit_up_cannot_buy` | 1 |

## 6. 对照组

| Control | Value |
|---|---|
| Buy&Hold | -12.98% |
| 等权池 | -18.42% (n=50) |
| 最强单因子 | -18.46% (`max_ret_20d`) |
| L2 等权多因子 | -8.61% |
| 本策略 | -8.61% |
| 随机选股 95 分位 | -12.71%   ✅ 超出随机范围 |

## 7. 撮合假设状态

| Field | Value |
|---|---|
| 校准状态 | 未校准   ⚠️ 结论依赖未验证的撮合假设 |
| 校准日期 | — |
| 成交价 MAE | — |
| 涨跌停行为 | 未验证 |
| 未覆盖场景 | — |
| 声明 | **撮合假设未验证** |

## Notes

- signal at close, fill at next open
- rebalance=weekly (n=255)
- max_turnover=portfolio_config
- matching assumptions unverified
- frozen CSI300_L2_IC_MEANS_5Y (sign align only; same as shadow_quant)
- scores filtered to csi300 membership @ signal day
- lookback_days=250 for factor warm-up
- equal pool n=50 (shadow_baseline-aligned)
- best single=`max_ret_20d` by L1 |ICIR| leader among admitted
- MC trials=100 seed=42 p50=-28.13% p80=-22.28% p95=-12.71%

---
*Template: docs/08-backtest-eval.md §9.2. Section 7 is mandatory;*
*uncalibrated conclusions must keep 「撮合假设未验证」.*
