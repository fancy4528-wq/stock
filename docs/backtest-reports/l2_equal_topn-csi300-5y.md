# Portfolio backtest: `l2_equal_topn`

> period 2021-10-14 → 2026-10-13 | top_n=15 | rebalance=weekly (n=255) | code_version=`dev` | param_search_count=0
> Matching: **未校准 — 撮合假设未验证**

## 1. 防偏差检查

- 见 `make test-sentinel`（本报告未重跑）
- 见 `make check-survivorship`（本报告未重跑）
- ✅ 涨跌停约束已接入（本窗涨跌停相关拒单 5 次；总拒单 51）
- ✅ T+1 约束已接入（本窗 t1 相关拒单 0 次）
- ✅ 成本模型含佣金/印花税/过户费/滑点（`MarketConfig.estimate_fees` + fixed_bps）

## 2. 风险

| Metric | Value |
|---|---|
| Max Drawdown | -24.66% |
| Calmar | -0.045 |
| Volatility (ann.) | +16.34% |
| Sortino | —（未算） |

## 3. 收益

| Metric | Value |
|---|---|
| Total return | -5.41% |
| CAGR | -1.11% |
| Sharpe (rf=2%) | -0.111 |
| End NAV | 945,945.64（初始 1,000,000.00） |
| Trading days | 1211 |

## 4. 稳定性

- 分年度: 2021 -2.20% | 2022 -15.14% | 2023 +2.58% | 2024 +12.47% | 2025 +10.56% | 2026 -10.23%
- 盈利年份: 3/6（无年份序列时为 0/0）
- 最差月份: —（未算）

## 5. 成本与容量

| Metric | Value |
|---|---|
| Total fees | 99,971.79 |
| 成本 / |总收益| | +184.95% |
| 年换手率 | —（未算） |
| 单笔占成交量 | —（未算） |
| 估计容量 | —（未算） |

### 拒单原因

| Reason | Count |
|---|---:|
| `insufficient cash` | 30 |
| `no_bar` | 13 |
| `limit_up_cannot_buy` | 4 |
| `suspended` | 3 |
| `limit_down_cannot_sell` | 1 |

## 6. 对照组

| Control | Value |
|---|---|
| Buy&Hold | -12.98% |
| 等权池 | -18.11% (n=50) |
| 最强单因子 | -29.82% (`max_ret_20d`) |
| L2 等权多因子 | -5.41% |
| 本策略 | -5.41% |
| 随机选股 95 分位 | -53.09%   ✅ 超出随机范围 |

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
- matching assumptions unverified
- frozen CSI300_L2_IC_MEANS_5Y (sign align only; same as shadow_quant)
- scores filtered to csi300 membership @ signal day
- lookback_days=250 for factor warm-up
- equal pool n=50 (shadow_baseline-aligned)
- best single=`max_ret_20d` by L1 |ICIR| leader among admitted
- MC trials=100 seed=42 p50=-62.08% p80=-56.48% p95=-53.09%

---
*Template: docs/08-backtest-eval.md §9.2. Section 7 is mandatory;*
*uncalibrated conclusions must keep 「撮合假设未验证」.*
