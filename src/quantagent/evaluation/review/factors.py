"""Factor decay status from a recent IC and the frozen historical IC."""

from __future__ import annotations

from quantagent.evaluation.review.types import FactorHealth
from quantagent.evaluation.shadow.quant_signals import CSI300_L2_IC_MEANS_5Y

# docs/07 §3.3: |recent| < 50% of |hist|, or a sign flip, marks weakening.
_DECAY_RATIO_FLOOR = 0.5


def assess_factor(
    factor: str,
    *,
    hist_ic: float | None,
    recent_ic: float | None,
) -> FactorHealth:
    """Compare one factor. A missing recent IC is unknown, not failed."""
    if hist_ic is None or recent_ic is None or abs(hist_ic) <= 1e-12:
        return FactorHealth(
            factor=factor,
            hist_ic=hist_ic,
            recent_ic=recent_ic,
            decay_ratio=None,
            status="unknown",
        )
    ratio = recent_ic / hist_ic
    sign_flip = recent_ic * hist_ic < 0
    weakened = sign_flip or abs(recent_ic) < _DECAY_RATIO_FLOOR * abs(hist_ic)
    return FactorHealth(
        factor=factor,
        hist_ic=hist_ic,
        recent_ic=recent_ic,
        decay_ratio=ratio,
        status="weakening" if weakened else "healthy",
    )


def assess_admitted_factors(
    recent_ic: dict[str, float] | None = None,
    *,
    historical: dict[str, float] | None = None,
) -> list[FactorHealth]:
    """Frozen CSI300 5y admission ICs, with an optional recent window.

    Factors present only in ``recent_ic`` are appended after the frozen list.
    """
    hist = dict(CSI300_L2_IC_MEANS_5Y if historical is None else historical)
    recent = dict(recent_ic or {})
    names = list(hist)
    names.extend(name for name in recent if name not in hist)
    return [
        assess_factor(name, hist_ic=hist.get(name), recent_ic=recent.get(name))
        for name in names
    ]
