"""Cross-sectional IC / ICIR / t-tests."""

from __future__ import annotations

from math import sqrt

import numpy as np
import polars as pl
from scipy import stats  # type: ignore[import-untyped]

from quantagent.quant.evaluation.types import ICSummary
from quantagent.shared.errors import QuantAgentError


class EvaluationError(QuantAgentError):
    """Invalid evaluation panel or parameters."""


def cross_sectional_spearman(x: pl.Series, y: pl.Series) -> float | None:
    """Spearman rank correlation; ``None`` if fewer than 3 finite pairs."""
    pairs = pl.DataFrame({"x": x, "y": y}).drop_nulls()
    if pairs.height < 3:
        return None
    xv = pairs["x"].to_numpy()
    yv = pairs["y"].to_numpy()
    if np.nanstd(xv) < 1e-15 or np.nanstd(yv) < 1e-15:
        return None
    corr, _ = stats.spearmanr(xv, yv)
    if corr is None or np.isnan(corr):
        return None
    return float(corr)


def daily_ic_series(
    panel: pl.DataFrame,
    *,
    factor_col: str,
    return_col: str,
    date_col: str = "trade_date",
    min_names: int = 3,
) -> pl.DataFrame:
    """Return ``trade_date, ic`` for each cross-section with enough names."""
    for c in (factor_col, return_col, date_col):
        if c not in panel.columns:
            raise EvaluationError(f"panel missing column: {c}")

    rows: list[dict[str, object]] = []
    for (td,), g in panel.group_by(date_col, maintain_order=True):
        clean = g.select([factor_col, return_col]).drop_nulls()
        if clean.height < min_names:
            continue
        ic = cross_sectional_spearman(clean[factor_col], clean[return_col])
        if ic is None:
            continue
        rows.append({date_col: td, "ic": ic})

    if not rows:
        return pl.DataFrame(schema={date_col: pl.Date, "ic": pl.Float64})
    return pl.DataFrame(rows).sort(date_col)


def summarize_ic(ics: pl.Series | list[float]) -> ICSummary:
    """Mean / std / ICIR / t / p / positive ratio over an IC series."""
    if isinstance(ics, pl.Series):
        vals = [float(v) for v in ics.drop_nulls().to_list()]
    else:
        vals = [float(v) for v in ics if v is not None and not np.isnan(v)]

    n = len(vals)
    if n == 0:
        return ICSummary(
            ic_mean=0.0,
            ic_std=0.0,
            icir=0.0,
            ic_t_stat=0.0,
            ic_p_value=1.0,
            ic_positive_ratio=0.0,
            n_periods=0,
        )

    arr = np.asarray(vals, dtype=float)
    mean = float(arr.mean())
    std = float(arr.std(ddof=1)) if n > 1 else 0.0
    icir = mean / std if std > 1e-15 else 0.0
    if n > 1 and std > 1e-15:
        t_stat = mean / (std / sqrt(n))
        # two-sided t test vs 0
        p_value = float(2.0 * stats.t.sf(abs(t_stat), df=n - 1))
    else:
        t_stat = 0.0
        p_value = 1.0
    pos_ratio = float(np.mean(arr > 0.0))

    return ICSummary(
        ic_mean=mean,
        ic_std=std,
        icir=float(icir),
        ic_t_stat=float(t_stat),
        ic_p_value=p_value,
        ic_positive_ratio=pos_ratio,
        n_periods=n,
    )


def ic_by_year(ic_frame: pl.DataFrame, *, date_col: str = "trade_date") -> dict[int, float]:
    """Mean IC per calendar year."""
    if ic_frame.is_empty() or "ic" not in ic_frame.columns:
        return {}
    framed = ic_frame.with_columns(pl.col(date_col).dt.year().alias("_year"))
    out: dict[int, float] = {}
    for (year,), g in framed.group_by("_year", maintain_order=True):
        vals = g["ic"].drop_nulls()
        if vals.len() == 0:
            continue
        out[int(year)] = float(vals.mean())  # type: ignore[arg-type]
    return out


def ic_by_regime(
    panel: pl.DataFrame,
    ic_frame: pl.DataFrame,
    *,
    return_col: str,
    date_col: str = "trade_date",
) -> dict[str, float]:
    """Split IC into up/down regimes by equal-weight cross-section return sign."""
    if ic_frame.is_empty() or panel.is_empty():
        return {"up": 0.0, "down": 0.0}

    mkt = (
        panel.group_by(date_col, maintain_order=True)
        .agg(pl.col(return_col).mean().alias("_mkt"))
        .drop_nulls()
    )
    joined = ic_frame.join(mkt, on=date_col, how="inner")
    if joined.is_empty():
        return {"up": 0.0, "down": 0.0}

    up = joined.filter(pl.col("_mkt") >= 0)["ic"]
    down = joined.filter(pl.col("_mkt") < 0)["ic"]
    return {
        "up": float(up.mean()) if up.len() else 0.0,  # type: ignore[arg-type]
        "down": float(down.mean()) if down.len() else 0.0,  # type: ignore[arg-type]
    }
