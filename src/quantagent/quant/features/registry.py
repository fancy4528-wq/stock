"""Factor registry — MVP (P1) plus P3 price/volume expansion batch."""

from __future__ import annotations

from quantagent.quant.features.base import Factor
from quantagent.quant.features.liquidity import (
    AmihudIlliq20d,
    Amount20d,
    Turnover20d,
    TurnoverRatio5_60,
    VolPriceCorr20d,
    VolumeTrend20d,
)
from quantagent.quant.features.momentum import (
    DistFromHigh252d,
    DistFromLow252d,
    MaCross5_20,
    Mom5d,
    Mom20d,
    Mom20dEx1w,
    Mom60d,
    Mom120d,
    RelStrMarket,
    TrendR260d,
    TrendSlope60d,
)
from quantagent.quant.features.reversal import (
    MaxRet20d,
    Rev1d,
    Rev5d,
    RevIntraday,
    RevOvernight,
)
from quantagent.quant.features.value import Bp, EpTtm, SpTtm
from quantagent.quant.features.volatility import (
    Beta252d,
    DownsideVol60d,
    Kurt60d,
    MaxDd60d,
    Skew60d,
    Vol20d,
    Vol60d,
    VolRatio20_60,
)


def _index(*factors: Factor) -> dict[str, Factor]:
    return {f.code: f for f in factors}


# P1 baseline (docs/11-mvp.md §6) — kept stable for Shadow / daily report.
MVP_FACTORS: dict[str, Factor] = _index(
    Mom20d(),
    Mom60d(),
    Rev5d(),
    Vol20d(),
    Turnover20d(),
    TurnoverRatio5_60(),
    EpTtm(),
    AmihudIlliq20d(),
)

# P3 first expansion: OHLCV + simple valuation multiples (docs/07-quant-engine.md §2.1).
# Skips money-flow / quality / growth / news / sector-relative until data feeds exist.
P3_BATCH_FACTORS: dict[str, Factor] = _index(
    Mom5d(),
    Mom120d(),
    Mom20dEx1w(),
    DistFromHigh252d(),
    DistFromLow252d(),
    MaCross5_20(),
    TrendSlope60d(),
    TrendR260d(),
    RelStrMarket(),
    Rev1d(),
    RevOvernight(),
    RevIntraday(),
    MaxRet20d(),
    Vol60d(),
    VolRatio20_60(),
    DownsideVol60d(),
    MaxDd60d(),
    Skew60d(),
    Kurt60d(),
    Beta252d(),
    Amount20d(),
    VolumeTrend20d(),
    VolPriceCorr20d(),
    Bp(),
    SpTtm(),
)

ALL_FACTORS: dict[str, Factor] = {**MVP_FACTORS, **P3_BATCH_FACTORS}

MVP_FACTOR_CODES: tuple[str, ...] = tuple(MVP_FACTORS.keys())
P3_BATCH_CODES: tuple[str, ...] = tuple(P3_BATCH_FACTORS.keys())
ALL_FACTOR_CODES: tuple[str, ...] = tuple(ALL_FACTORS.keys())

# Codes that need only OHLCV (+ optional pe/pb/ps on the price panel) for synthetic L1.
L1_SYNTHETIC_CODES: tuple[str, ...] = ALL_FACTOR_CODES


def get_factor(code: str) -> Factor:
    try:
        return ALL_FACTORS[code]
    except KeyError as exc:
        known = ", ".join(ALL_FACTOR_CODES)
        raise KeyError(f"unknown factor {code!r}; known: {known}") from exc


def list_factors(*, category: str | None = None) -> list[Factor]:
    factors = list(ALL_FACTORS.values())
    if category is not None:
        factors = [f for f in factors if f.category == category]
    return sorted(factors, key=lambda f: (f.category, f.code))
