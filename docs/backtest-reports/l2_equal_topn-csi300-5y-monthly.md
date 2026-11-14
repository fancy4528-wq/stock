# Portfolio backtest: `l2_equal_topn`

> period 2021-10-14 → 2026-10-13 | top_n=15 | rebalance=monthly (n=60) | code_version=`dev` | param_search_count=0
> Matching: **未校准 — 撮合假设未验证**

## 1. 防偏差检查

- 见 `make test-sentinel`（本报告未重跑）
- 见 `make check-survivorship`（本报告未重跑）
- ✅ 涨跌停约束已接入（本窗涨跌停相关拒单 3 次；总拒单 5）
- ✅ T+1 约束已接入（本窗 t1 相关拒单 0 次）
- ✅ 成本模型含佣金/印花税/过户费/滑点（`MarketConfig.estimate_fees` + fixed_bps）

## 2. 风险

| Metric | Value |
|---|---|
| Max Drawdown | -12.85% |
| MDD 持续天数 | 280 |
| Calmar | 0.371 |
| Volatility (ann.) | +11.15% |
| Sortino | 0.449 |

## 3. 收益

| Metric | Value |
|---|---|
| Total return | +26.24% |
| CAGR | +4.77% |
| Sharpe (rf=2%) | 0.312 |
| End NAV | 1,262,411.30（初始 1,000,000.00） |
| Trading days | 1211 |

## 4. 稳定性

- 分年度: 2021 +0.37% | 2022 -1.14% | 2023 +4.81% | 2024 +15.21% | 2025 +7.01% | 2026 -1.95%
- 盈利年份: 4/6（无年份序列时为 0/0）
- 最差月份: -4.55%

## 5. 成本与容量

| Metric | Value |
|---|---|
| Total fees | 29,915.92 |
| 成本 / |总收益| | +11.40% |
| 年换手率 | +350.63% |
| 单笔占成交量 | +0.02% |
| 估计容量 | 2.32 亿 |

容量按平均净值放大到平均单笔成交量占比等于 `max_volume_share`。换手率为单边、按平均净值年化。

### 拒单原因

| Reason | Count |
|---|---:|
| `limit_up_cannot_buy` | 3 |
| `suspended` | 2 |

## 6. 对照组

| Control | Value |
|---|---|
| Buy&Hold | -12.98% |
| 等权池 | -15.79% (n=50) |
| 最强单因子 | -12.46% (`max_ret_20d`) |
| L2 等权多因子 | +26.24% |
| 本策略 | +26.24% |
| 随机选股 95 分位 | +11.50%   ✅ 超出随机范围 |

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
- rebalance=monthly (n=60)
- max_turnover=portfolio_config
- matching assumptions unverified
- frozen CSI300_L2_IC_MEANS_5Y (sign align only; same as shadow_quant)
- scores filtered to csi300 membership @ signal day
- lookback_days=250 for factor warm-up
- equal pool n=50 (shadow_baseline-aligned)
- best single=`max_ret_20d` by L1 |ICIR| leader among admitted
- MC trials=100 seed=42 p50=-6.82% p80=+3.15% p95=+11.50%

---
*Template: docs/08-backtest-eval.md §9.2. Section 7 is mandatory;*
*uncalibrated conclusions must keep 「撮合假设未验证」.*
