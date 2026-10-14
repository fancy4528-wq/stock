"""Cross-sectional factor transforms: MAD winsorize → neutralize → rank_pct.

See docs/07-quant-engine.md §2.3.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import polars as pl

from quantagent.quant.features.base import FactorInput, entity_col


@dataclass(frozen=True)
class TransformConfig:
    """Controls the L1 cross-section preprocess applied before IC tests."""

    enabled: bool = True
    mad_n: float = 3.0
    neutralize_industry: bool = True
    neutralize_mktcap: bool = True
    rank: bool = True


DEFAULT_TRANSFORM = TransformConfig()


def winsorize_mad(s: pl.Series, n: float = 3.0) -> pl.Series:
    """MAD winsorize; more robust than σ-clip for skewed A-share factors."""
    if s.len() == 0:
        return s
    vals = s.cast(pl.Float64, strict=False)
    med = vals.median()
    if med is None:
        return vals
    mad = (vals - float(med)).abs().median()
    if mad is None or float(mad) == 0.0:
        return vals
    half = float(n) * 1.4826 * float(mad)
    lo, hi = float(med) - half, float(med) + half
    return vals.clip(lo, hi)


def rank_pct(s: pl.Series) -> pl.Series:
    """Cross-section percentile rank in ``[0, 1]`` (average ties).

    NaN is treated as null (Polars ranks NaN as a real value and would otherwise
    assign every missing residual the same percentile — collapsing factor corr).
    """
    vals = s.cast(pl.Float64, strict=False).fill_nan(None)
    n = int(vals.len() - vals.null_count())
    if n <= 1:
        return pl.Series(vals.name, [None] * vals.len(), dtype=pl.Float64)
    ranks = vals.rank(method="average")
    return ((ranks - 1.0) / float(n - 1)).alias(vals.name or "")


def neutralize(
    factor: pl.Series,
    industry: pl.Series | None = None,
    log_mktcap: pl.Series | None = None,
) -> pl.Series:
    """OLS residual of factor on industry dummies and/or log market cap.

    Invalid rows (non-finite factor / missing industry / missing mktcap) are
    **null**, not NaN — see :func:`rank_pct`.
    """
    y = factor.cast(pl.Float64, strict=False).to_numpy().astype(float, copy=False)
    n = len(y)
    if n == 0:
        return factor.cast(pl.Float64, strict=False)

    valid = np.isfinite(y)

    if industry is not None:
        ind = industry.to_list()
        ind_arr = np.array([("" if v is None else str(v)) for v in ind], dtype=object)
        ind_ok = np.array([v != "" for v in ind_arr], dtype=bool)
        valid &= ind_ok
    else:
        ind_arr = None

    if log_mktcap is not None:
        mc = log_mktcap.cast(pl.Float64, strict=False).to_numpy().astype(float, copy=False)
        valid &= np.isfinite(mc)
    else:
        mc = None

    if int(valid.sum()) < 3:
        return pl.Series(
            factor.name,
            [float(y[i]) if valid[i] else None for i in range(n)],
            dtype=pl.Float64,
        )

    yv = y[valid]
    design: list[np.ndarray] = [np.ones(yv.shape[0], dtype=float)]

    if ind_arr is not None:
        cats = sorted({str(v) for v in ind_arr[valid]})
        # Drop first category to avoid dummy trap with the intercept.
        for cat in cats[1:]:
            design.append((ind_arr[valid] == cat).astype(float))

    if mc is not None:
        design.append(mc[valid].astype(float, copy=False))

    resid_valid: np.ndarray
    if len(design) == 1:
        # Intercept-only → demean.
        resid_valid = yv - float(yv.mean())
    else:
        x = np.column_stack(design)
        coef, *_ = np.linalg.lstsq(x, yv, rcond=None)
        resid_valid = yv - x @ coef

    out_list: list[float | None] = [None] * n
    idx = np.flatnonzero(valid)
    for j, i in enumerate(idx):
        out_list[int(i)] = float(resid_valid[j])
    return pl.Series(factor.name, out_list, dtype=pl.Float64)


def estimate_log_mktcap(panel: pl.DataFrame) -> pl.Series:
    """``log(market_cap)`` with fallback ``log(close * volume / turnover_rate)``."""
    n = panel.height
    if "market_cap" in panel.columns:
        mc = panel["market_cap"].cast(pl.Float64, strict=False)
        if int(mc.null_count()) < n:
            return mc.log().alias("log_mktcap")
    if "circ_market_cap" in panel.columns:
        cmc = panel["circ_market_cap"].cast(pl.Float64, strict=False)
        if int(cmc.null_count()) < n:
            return cmc.log().alias("log_mktcap")

    need = {"close", "volume", "turnover_rate"}
    if not need.issubset(panel.columns):
        return pl.Series("log_mktcap", [None] * n, dtype=pl.Float64)

    prox = (
        pl.when(
            pl.col("turnover_rate").is_not_null()
            & (pl.col("turnover_rate") > 0)
            & pl.col("close").is_not_null()
            & pl.col("volume").is_not_null()
            & (pl.col("volume") > 0)
        )
        .then((pl.col("close") * pl.col("volume") / pl.col("turnover_rate")).log())
        .otherwise(None)
        .alias("log_mktcap")
    )
    return panel.select(prox).to_series()


def attach_cs_covariates(panel: pl.DataFrame, data: FactorInput) -> pl.DataFrame:
    """Join industry codes and attach ``log_mktcap`` for neutralization."""
    out = panel
    ent = entity_col(out)

    if data.industry is not None and not data.industry.is_empty():
        ind = data.industry
        if "level" in ind.columns:
            leveled = ind.filter(pl.col("level") == 1)
            if not leveled.is_empty():
                ind = leveled
        join_key = ent if ent in ind.columns else (
            "security_id" if "security_id" in ind.columns else "symbol"
        )
        cols = [join_key, "industry_code"]
        cols = [c for c in cols if c in ind.columns]
        if "industry_code" in cols and join_key in cols:
            slim = ind.select(cols).unique(subset=[join_key], keep="first")
            if join_key != ent and join_key in out.columns:
                # already aligned key name
                pass
            if "industry_code" in out.columns:
                out = out.drop("industry_code")
            # Map industry onto panel entity key.
            if join_key == ent:
                out = out.join(slim, on=ent, how="left")
            elif "security_id" in out.columns and join_key == "security_id":
                out = out.join(slim, on="security_id", how="left")
            elif "symbol" in out.columns and join_key == "symbol":
                out = out.join(slim, on="symbol", how="left")

    if data.valuations is not None and not data.valuations.is_empty():
        val = data.valuations
        val_ent = entity_col(val)
        add_cols = [
            c
            for c in ("market_cap", "circ_market_cap")
            if c in val.columns and c not in out.columns
        ]
        if add_cols and "trade_date" in val.columns and val_ent in out.columns:
            out = out.join(
                val.select([val_ent, "trade_date", *add_cols]),
                on=[val_ent, "trade_date"],
                how="left",
            )

    if "log_mktcap" in out.columns:
        out = out.drop("log_mktcap")
    out = out.with_columns(estimate_log_mktcap(out))
    return out


def transform_cross_section(
    panel: pl.DataFrame,
    factor_cols: list[str],
    *,
    date_col: str = "trade_date",
    industry_col: str = "industry_code",
    mktcap_col: str = "log_mktcap",
    config: TransformConfig = DEFAULT_TRANSFORM,
) -> pl.DataFrame:
    """Apply MAD → neutralize → rank_pct per ``trade_date`` for each factor."""
    if not config.enabled:
        return panel

    cols = [c for c in factor_cols if c in panel.columns]
    if not cols:
        return panel

    use_industry = (
        config.neutralize_industry
        and industry_col in panel.columns
        and int(panel[industry_col].null_count()) < panel.height
    )
    use_mktcap = (
        config.neutralize_mktcap
        and mktcap_col in panel.columns
        and int(panel[mktcap_col].null_count()) < panel.height
    )

    def _one_date(df: pl.DataFrame) -> pl.DataFrame:
        out = df
        ind = out[industry_col] if use_industry else None
        mc = out[mktcap_col] if use_mktcap else None
        for col in cols:
            s = winsorize_mad(out[col], n=config.mad_n)
            if use_industry or use_mktcap:
                s = neutralize(s, industry=ind, log_mktcap=mc)
            if config.rank:
                s = rank_pct(s)
            out = out.with_columns(s.alias(col))
        return out

    return (
        panel.group_by(date_col, maintain_order=True)
        .map_groups(_one_date)
        .sort([entity_col(panel), date_col])
    )


def transform_meta(panel: pl.DataFrame, config: TransformConfig) -> dict[str, object]:
    """Small dict for report notes / FactorInput.meta."""
    has_ind = "industry_code" in panel.columns and int(
        panel["industry_code"].null_count()
    ) < panel.height
    has_mc = "log_mktcap" in panel.columns and int(panel["log_mktcap"].null_count()) < panel.height
    return {
        "transform": config.enabled,
        "mad_n": config.mad_n,
        "neutralize_industry": bool(config.neutralize_industry and has_ind),
        "neutralize_mktcap": bool(config.neutralize_mktcap and has_mc),
        "rank_pct": config.rank,
    }
