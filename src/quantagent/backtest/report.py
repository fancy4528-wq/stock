"""Portfolio backtest markdown report (docs/08-backtest-eval.md §9.2).

Section 7 (matching assumptions) is mandatory. Uncalibrated runs must say
「撮合假设未验证」.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from quantagent.backtest.portfolio import PortfolioBacktestResult

MatchingStatus = Literal["unverified", "calibrated"]


class MatchingAssumptionStatus(BaseModel):
    """§9.2 section [7] — never omit from a Gate 4 report."""

    status: MatchingStatus = "unverified"
    calibrated_at: date | None = None
    venue: str | None = None
    n_orders: int | None = None
    price_mae: float | None = None
    limit_behavior: str = "未验证"
    uncovered: list[str] = Field(default_factory=list)
    disclaimer: str = "撮合假设未验证"


class BiasCheckInputs(BaseModel):
    """Optional overrides for §9.2 section [1]."""

    pit_sentinel: str = "见 `make test-sentinel`（本报告未重跑）"
    survivorship: str = "见 `make check-survivorship`（本报告未重跑）"
    cost_model_complete: bool = True
    param_search_count: int = 0
    code_version: str = "dev"


def count_unfilled_reasons(unfilled: list[Any]) -> dict[str, int]:
    """Histogram of reject reasons from ``UnfilledRecord`` or plain dicts."""
    counts: dict[str, int] = {}
    for item in unfilled:
        if isinstance(item, dict):
            reason = str(item.get("reason", "unknown"))
        elif hasattr(item, "reason"):
            reason = str(item.reason)
        else:
            reason = "unknown"
        counts[reason] = counts.get(reason, 0) + 1
    return dict(sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])))


def _pct(x: float | None) -> str:
    if x is None:
        return "—"
    return f"{x:+.2%}"


def _num(x: float | None, digits: int = 3) -> str:
    if x is None:
        return "—"
    return f"{x:.{digits}f}"


def _reject_line(stats: dict[str, int], *keys: str) -> int:
    return sum(stats.get(k, 0) for k in keys)


def render_portfolio_backtest_report(
    result: PortfolioBacktestResult,
    *,
    matching: MatchingAssumptionStatus | None = None,
    bias: BiasCheckInputs | None = None,
    controls: dict[str, str] | None = None,
) -> str:
    """Render Gate 4 §9.2 portfolio backtest markdown."""
    matching = matching or MatchingAssumptionStatus()
    bias = bias or BiasCheckInputs()
    controls = controls or {}

    reject = result.reject_stats
    n_limit = _reject_line(
        reject,
        "limit_up_cannot_buy",
        "limit_down_cannot_sell",
        "limit_price_not_reached",
    )
    n_t1 = _reject_line(reject, "t1_not_sellable", "t1_clip")
    cost_ok = "✅" if bias.cost_model_complete else "❌"
    param_warn = ""
    if bias.param_search_count > 5:
        param_warn = f"\n- ⚠️ 参数搜索 {bias.param_search_count} 次，结果可信度下降"

    if matching.status == "calibrated":
        cal_status = (
            f"已校准（{matching.calibrated_at}, {matching.venue or '?'}, "
            f"{matching.n_orders or '?'} 笔）"
        )
        disclaimer_banner = "Matching: **已校准**"
    else:
        cal_status = "未校准   ⚠️ 结论依赖未验证的撮合假设"
        disclaimer_banner = f"Matching: **未校准 — {matching.disclaimer}**"

    reject_rows = (
        "\n".join(f"| `{k}` | {v} |" for k, v in reject.items())
        if reject
        else "| （无） | 0 |"
    )
    yearly = result.yearly_returns
    yearly_txt = (
        " | ".join(f"{y} {_pct(r)}" for y, r in sorted(yearly.items()))
        if yearly
        else "—"
    )
    profit_years = sum(1 for r in yearly.values() if r > 0)
    n_years = len(yearly)

    control_rows = {
        "Buy&Hold": controls.get("buy_and_hold", "—（未跑）"),
        "等权池": controls.get("equal_weight_pool", "—（未跑）"),
        "最强单因子": controls.get("best_single_factor", "—（未跑）"),
        "L2 等权多因子": controls.get("l2_equal", "—（本策略）"),
        "本策略": _pct(result.total_return),
        "随机选股 95 分位": controls.get("random_p95", "—（未跑）"),
    }
    control_md = "\n".join(f"| {k} | {v} |" for k, v in control_rows.items())

    mae = "—" if matching.price_mae is None else f"{matching.price_mae:.2%}"
    uncovered = ", ".join(matching.uncovered) if matching.uncovered else "—"
    notes = "\n".join(f"- {n}" for n in result.notes) or "- （无）"

    meta_line = (
        f"> period {result.start.isoformat()} → {result.end.isoformat()} "
        f"| top_n={result.top_n} | code_version=`{bias.code_version}` "
        f"| param_search_count={bias.param_search_count}"
    )
    cost_line = (
        f"- {cost_ok} 成本模型含佣金/印花税/过户费/滑点"
        f"（`MarketConfig.estimate_fees` + fixed_bps）{param_warn}"
    )
    return f"""# Portfolio backtest: `{result.strategy}`

{meta_line}
> {disclaimer_banner}

## 1. 防偏差检查

- {bias.pit_sentinel}
- {bias.survivorship}
- ✅ 涨跌停约束已接入（本窗涨跌停相关拒单 {n_limit} 次；总拒单 {result.n_unfilled}）
- ✅ T+1 约束已接入（本窗 t1 相关拒单 {n_t1} 次）
{cost_line}

## 2. 风险

| Metric | Value |
|---|---|
| Max Drawdown | {_pct(result.max_drawdown)} |
| Calmar | {_num(result.calmar)} |
| Volatility (ann.) | {_pct(result.volatility) if result.volatility is not None else "—"} |
| Sortino | —（未算） |

## 3. 收益

| Metric | Value |
|---|---|
| Total return | {_pct(result.total_return)} |
| CAGR | {_pct(result.cagr) if result.cagr is not None else "—"} |
| Sharpe (rf=2%) | {_num(result.sharpe)} |
| End NAV | {result.end_nav:,.2f}（初始 {result.initial_nav:,.2f}） |
| Trading days | {result.n_days} |

## 4. 稳定性

- 分年度: {yearly_txt}
- 盈利年份: {profit_years}/{n_years}（无年份序列时为 0/0）
- 最差月份: —（未算）

## 5. 成本与容量

| Metric | Value |
|---|---|
| Total fees | {result.total_fees:,.2f} |
| 成本 / |总收益| | {_pct(result.cost_to_pnl) if result.cost_to_pnl is not None else "—"} |
| 年换手率 | —（未算） |
| 单笔占成交量 | —（未算） |
| 估计容量 | —（未算） |

### 拒单原因

| Reason | Count |
|---|---:|
{reject_rows}

## 6. 对照组

| Control | Value |
|---|---|
{control_md}

## 7. 撮合假设状态

| Field | Value |
|---|---|
| 校准状态 | {cal_status} |
| 校准日期 | {matching.calibrated_at or "—"} |
| 成交价 MAE | {mae} |
| 涨跌停行为 | {matching.limit_behavior} |
| 未覆盖场景 | {uncovered} |
| 声明 | **{matching.disclaimer}** |

## Notes

{notes}

---
*Template: docs/08-backtest-eval.md §9.2. Section 7 is mandatory;*
*uncalibrated conclusions must keep 「撮合假设未验证」.*
"""


def write_portfolio_backtest_report(
    result: PortfolioBacktestResult,
    path: Path | str,
    *,
    matching: MatchingAssumptionStatus | None = None,
    bias: BiasCheckInputs | None = None,
    controls: dict[str, str] | None = None,
) -> Path:
    """Write markdown report; create parent dirs as needed."""
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        render_portfolio_backtest_report(
            result, matching=matching, bias=bias, controls=controls
        ),
        encoding="utf-8",
    )
    return out
