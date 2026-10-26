# Portfolio backtest: `l2_equal_topn`

> period 2024-01-02 → 2024-01-11 | top_n=1 | code_version=`dev` | param_search_count=0
> Matching: **未校准 — 撮合假设未验证**

## 1. 防偏差检查

- 见 `make test-sentinel`（本报告未重跑）
- 见 `make check-survivorship`（本报告未重跑）
- ✅ 涨跌停约束已接入（本窗涨跌停相关拒单 1 次；总拒单 7）
- ✅ T+1 约束已接入（本窗 t1 相关拒单 0 次）
- ✅ 成本模型含佣金/印花税/过户费/滑点（`MarketConfig.estimate_fees` + fixed_bps）

## 2. 风险

| Metric | Value |
|---|---|
| Max Drawdown | -3.22% |
| Calmar | 32.136 |
| Volatility (ann.) | +28.92% |
| Sortino | —（未算） |

## 3. 收益

| Metric | Value |
|---|---|
| Total return | +1.77% |
| CAGR | +103.62% |
| Sharpe (rf=2%) | 2.236 |
| End NAV | 1,017,675.83（初始 1,000,000.00） |
| Trading days | 8 |

## 4. 稳定性

- 分年度: 2024 +1.77%
- 盈利年份: 1/1（无年份序列时为 0/0）
- 最差月份: —（未算）

## 5. 成本与容量

| Metric | Value |
|---|---|
| Total fees | 5,104.17 |
| 成本 / |总收益| | +28.88% |
| 年换手率 | —（未算） |
| 单笔占成交量 | —（未算） |
| 估计容量 | —（未算） |

### 拒单原因

| Reason | Count |
|---|---:|
| `volume_limit` | 5 |
| `insufficient cash` | 1 |
| `limit_up_cannot_buy` | 1 |

## 6. 对照组

| Control | Value |
|---|---|
| Buy&Hold | —（未跑） |
| 等权池 | —（未跑） |
| 最强单因子 | —（未跑） |
| L2 等权多因子 | —（本策略） |
| 本策略 | +1.77% |
| 随机选股 95 分位 | —（未跑） |

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
- matching assumptions unverified

---
*Template: docs/08-backtest-eval.md §9.2. Section 7 is mandatory;*
*uncalibrated conclusions must keep 「撮合假设未验证」.*
