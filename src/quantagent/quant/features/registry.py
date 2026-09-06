"""MVP factor registry (8 factors per docs/11-mvp.md §6)."""

from __future__ import annotations

from quantagent.quant.features.base import Factor
from quantagent.quant.features.liquidity import AmihudIlliq20d, Turnover20d, TurnoverRatio5_60
from quantagent.quant.features.momentum import Mom20d, Mom60d, Rev5d
from quantagent.quant.features.value import EpTtm
from quantagent.quant.features.volatility import Vol20d

MVP_FACTORS: dict[str, Factor] = {
    f.code: f
    for f in (
        Mom20d(),
        Mom60d(),
        Rev5d(),
        Vol20d(),
        Turnover20d(),
        TurnoverRatio5_60(),
        EpTtm(),
        AmihudIlliq20d(),
    )
}

MVP_FACTOR_CODES: tuple[str, ...] = tuple(MVP_FACTORS.keys())


def get_factor(code: str) -> Factor:
    try:
        return MVP_FACTORS[code]
    except KeyError as exc:
        known = ", ".join(MVP_FACTOR_CODES)
        raise KeyError(f"unknown factor {code!r}; known: {known}") from exc
