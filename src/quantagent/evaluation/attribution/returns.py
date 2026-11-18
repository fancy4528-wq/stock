"""Return decomposition: market / sector / stock / timing / cost (docs/08 §7.1)."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date

from quantagent.evaluation.attribution.types import ReturnDecomposition
from quantagent.execution.broker.simulated import PriceBar

# Unknown / missing industry bucket for Brinson when a name has no map entry.
_UNKNOWN_SECTOR = "_unknown"


def daily_stock_returns_from_bars(
    bars: Sequence[PriceBar] | Mapping[date, Sequence[PriceBar]],
) -> dict[date, dict[str, float]]:
    """Close-to-close returns keyed by the later session date."""
    by_date: dict[date, dict[str, float]] = {}
    if isinstance(bars, Mapping):
        for day, rows in bars.items():
            by_date[day] = {b.symbol: float(b.close) for b in rows}
    else:
        for bar in bars:
            by_date.setdefault(bar.trade_date, {})[bar.symbol] = float(bar.close)

    sessions = sorted(by_date)
    out: dict[date, dict[str, float]] = {}
    for i in range(1, len(sessions)):
        prev, cur = sessions[i - 1], sessions[i]
        prev_px = by_date[prev]
        cur_px = by_date[cur]
        day_rets: dict[str, float] = {}
        for sym, px in cur_px.items():
            base = prev_px.get(sym)
            if base is None or base <= 0 or px <= 0:
                continue
            day_rets[sym] = px / base - 1.0
        out[cur] = day_rets
    return out


def daily_returns_from_equity(equity: Sequence[float]) -> list[float]:
    """Length ``len(equity) - 1`` simple returns."""
    rets: list[float] = []
    for i in range(1, len(equity)):
        prev = equity[i - 1]
        if prev and prev > 0:
            rets.append(float(equity[i]) / float(prev) - 1.0)
        else:
            rets.append(0.0)
    return rets


def align_benchmark_returns(
    dates: Sequence[date],
    benchmark_dates: Sequence[date],
    benchmark_equity: Sequence[float],
) -> list[float]:
    """Map a benchmark equity curve onto portfolio session returns (day 1..n-1)."""
    if len(benchmark_dates) != len(benchmark_equity):
        raise ValueError("benchmark dates/equity length mismatch")
    by_day = {d: float(v) for d, v in zip(benchmark_dates, benchmark_equity, strict=True)}
    out: list[float] = []
    for i in range(1, len(dates)):
        prev_nav = by_day.get(dates[i - 1])
        cur_nav = by_day.get(dates[i])
        if prev_nav is None or cur_nav is None or prev_nav <= 0:
            out.append(0.0)
        else:
            out.append(cur_nav / prev_nav - 1.0)
    return out


def _ols_beta(y: Sequence[float], x: Sequence[float]) -> float:
    if len(y) != len(x) or len(y) < 2:
        return 1.0
    mean_x = sum(x) / len(x)
    mean_y = sum(y) / len(y)
    var_x = sum((xi - mean_x) ** 2 for xi in x)
    if var_x <= 1e-18:
        return 1.0
    cov = sum((xi - mean_x) * (yi - mean_y) for xi, yi in zip(x, y, strict=True))
    return cov / var_x


def _sector_weights(
    weights: Mapping[str, float],
    industry: Mapping[str, str],
) -> dict[str, float]:
    """Normalize invested weights to sector weights that sum to 1."""
    invested = {s: w for s, w in weights.items() if w > 0}
    total = sum(invested.values())
    if total <= 1e-15:
        return {}
    sectors: dict[str, float] = {}
    for sym, w in invested.items():
        sec = industry.get(sym) or _UNKNOWN_SECTOR
        sectors[sec] = sectors.get(sec, 0.0) + w / total
    return sectors


def _sector_returns(
    weights: Mapping[str, float],
    stock_rets: Mapping[str, float],
    industry: Mapping[str, str],
) -> dict[str, float]:
    """Portfolio (or basket) return inside each sector."""
    buckets: dict[str, list[tuple[float, float]]] = {}
    for sym, w in weights.items():
        if w <= 0:
            continue
        r = stock_rets.get(sym)
        if r is None:
            continue
        sec = industry.get(sym) or _UNKNOWN_SECTOR
        buckets.setdefault(sec, []).append((w, r))
    out: dict[str, float] = {}
    for sec, pairs in buckets.items():
        tw = sum(w for w, _ in pairs)
        if tw <= 1e-15:
            continue
        out[sec] = sum(w * r for w, r in pairs) / tw
    return out


def _brinson_fachler(
    w_p: Mapping[str, float],
    w_b: Mapping[str, float],
    r_p: Mapping[str, float],
    r_b: Mapping[str, float],
    r_b_total: float,
) -> tuple[float, float]:
    """Return (allocation, selection+interaction) for one day."""
    sectors = set(w_p) | set(w_b) | set(r_p) | set(r_b)
    alloc = 0.0
    select = 0.0
    for sec in sectors:
        wp = float(w_p.get(sec, 0.0))
        wb = float(w_b.get(sec, 0.0))
        rp = float(r_p.get(sec, r_b.get(sec, r_b_total)))
        rb = float(r_b.get(sec, r_b_total))
        alloc += (wp - wb) * (rb - r_b_total)
        select += wb * (rp - rb) + (wp - wb) * (rp - rb)
    return alloc, select


def _benchmark_sector_basket(
    stock_rets: Mapping[str, float],
    industry: Mapping[str, str],
) -> tuple[dict[str, float], dict[str, float], float]:
    """Equal-weight all names with a return that day → sector weights & returns."""
    if not stock_rets:
        return {}, {}, 0.0
    n = len(stock_rets)
    ew = {sym: 1.0 / n for sym in stock_rets}
    w_b = _sector_weights(ew, industry)
    r_b = _sector_returns(ew, stock_rets, industry)
    r_total = sum(stock_rets.values()) / n
    return w_b, r_b, r_total


def decompose_returns(
    *,
    dates: Sequence[date],
    equity: Sequence[float],
    weights_history: Sequence[Mapping[str, float]],
    cash_weights: Sequence[float],
    daily_fees: Sequence[float],
    benchmark_returns: Sequence[float],
    stock_returns: Mapping[date, Mapping[str, float]] | None = None,
    industry_map: Mapping[str, str] | None = None,
    initial_nav: float | None = None,
) -> ReturnDecomposition:
    """Decompose portfolio total return (docs/08 §7.1).

    ``benchmark_returns[i]`` is the benchmark return from ``dates[i]`` to
    ``dates[i+1]`` (length ``len(dates)-1``). Weights / cash / fees are
    end-of-day snapshots aligned with ``dates``; day ``t`` uses weights from
    ``t-1`` and fees booked on day ``t``.
    """
    n = len(dates)
    if n < 2 or len(equity) != n:
        return ReturnDecomposition(
            total_return=0.0,
            note="需要至少两个交易日的净值曲线才能归因",
        )
    if len(weights_history) != n or len(cash_weights) != n or len(daily_fees) != n:
        return ReturnDecomposition(
            total_return=float(equity[-1] / equity[0] - 1.0) if equity[0] else 0.0,
            note="weights/cash/fees 与 dates 长度不一致，跳过分解",
        )
    if len(benchmark_returns) != n - 1:
        return ReturnDecomposition(
            total_return=float(equity[-1] / equity[0] - 1.0) if equity[0] else 0.0,
            note=(
                f"benchmark_returns 长度应为 {n - 1}，"
                f"实际 {len(benchmark_returns)}，跳过分解"
            ),
        )

    port_rets = daily_returns_from_equity(equity)
    total = float(equity[-1] / equity[0] - 1.0) if equity[0] else 0.0
    beta = _ols_beta(port_rets, list(benchmark_returns))
    # Compounded benchmark over the same window (from daily).
    bench_nav = 1.0
    for r in benchmark_returns:
        bench_nav *= 1.0 + float(r)
    bench_total = bench_nav - 1.0

    industry = dict(industry_map or {})
    stock_by_day = stock_returns or {}
    has_industry = bool(industry)
    has_stocks = bool(stock_by_day)

    sum_market = 0.0
    sum_timing = 0.0
    sum_sector = 0.0
    sum_stock = 0.0
    sum_cost = 0.0

    for i in range(1, n):
        r_b = float(benchmark_returns[i - 1])
        prev_equity = float(equity[i - 1])
        exposure = max(0.0, min(1.0, 1.0 - float(cash_weights[i - 1])))
        fee = float(daily_fees[i])
        fee_ret = (fee / prev_equity) if prev_equity > 1e-12 else 0.0

        sum_market += beta * r_b
        sum_timing += (exposure - 1.0) * r_b
        sum_cost += -fee_ret

        if has_stocks and exposure > 1e-12:
            day = dates[i]
            srets = stock_by_day.get(day, {})
            w_prev = weights_history[i - 1]
            w_p_sec = _sector_weights(w_prev, industry) if has_industry else {}
            r_p_sec = (
                _sector_returns(w_prev, srets, industry) if has_industry else {}
            )
            w_b_sec, r_b_sec, r_b_basket = _benchmark_sector_basket(srets, industry)
            if has_industry and w_p_sec and w_b_sec:
                alloc, selec = _brinson_fachler(
                    w_p_sec, w_b_sec, r_p_sec, r_b_sec, r_b_basket
                )
                sum_sector += exposure * alloc
                sum_stock += exposure * selec
            elif srets and w_prev:
                # No industry map: treat whole book as one "stock selection" vs EW basket.
                port_r = 0.0
                tw = 0.0
                for sym, w in w_prev.items():
                    if w <= 0 or sym not in srets:
                        continue
                    port_r += w * srets[sym]
                    tw += w
                if tw > 1e-15:
                    port_r /= tw
                    basket = sum(srets.values()) / len(srets)
                    sum_stock += exposure * (port_r - basket)

    residual = total - (sum_market + sum_sector + sum_stock + sum_timing + sum_cost)
    notes: list[str] = []
    if not has_industry:
        notes.append("无行业映射：板块配置为 0，个股选择用相对等权篮子")
    if not has_stocks:
        notes.append("无个股日收益：板块/个股贡献为 0")
    if initial_nav is not None and initial_nav > 0:
        fee_share = sum(float(f) for f in daily_fees) / initial_nav
        notes.append(f"费用合计/初始净值={fee_share:.2%}")
    notes.append(
        f"β={beta:.3f}；日贡献算术加总，residual 吸收复利与模型误差"
    )

    return ReturnDecomposition(
        total_return=total,
        market=sum_market,
        sector_allocation=sum_sector,
        stock_selection=sum_stock,
        timing=sum_timing,
        cost=sum_cost,
        residual=residual,
        beta=beta,
        benchmark_return=bench_total,
        n_days=n,
        note="；".join(notes),
    )
