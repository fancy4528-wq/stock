"""SignalFusion: weighted multi-signal scores (no LLM)."""

from __future__ import annotations

from quantagent.decision.fusion.types import FusionConfig, FusedScore


def _rank_normalize(values: dict[str, float]) -> dict[str, float]:
    if not values:
        return {}
    ranked = sorted(values.items(), key=lambda x: x[1])
    n = len(ranked)
    if n == 1:
        return {ranked[0][0]: 0.5}
    return {sym: i / (n - 1) for i, (sym, _) in enumerate(ranked)}


def _minmax_normalize(values: dict[str, float]) -> dict[str, float]:
    if not values:
        return {}
    lo = min(values.values())
    hi = max(values.values())
    if hi <= lo:
        return {s: 0.5 for s in values}
    return {s: (v - lo) / (hi - lo) for s, v in values.items()}


def _zscore_normalize(values: dict[str, float]) -> dict[str, float]:
    if not values:
        return {}
    n = len(values)
    mean = sum(values.values()) / n
    var = sum((v - mean) ** 2 for v in values.values()) / n
    std = var**0.5
    if std <= 1e-12:
        return {s: 0.0 for s in values}
    return {s: (v - mean) / std for s, v in values.items()}


def _normalize(
    values: dict[str, float], method: str
) -> dict[str, float]:
    if method == "rank":
        return _rank_normalize(values)
    if method == "minmax":
        return _minmax_normalize(values)
    if method == "zscore":
        return _zscore_normalize(values)
    raise ValueError(f"unknown normalize method: {method}")


def _renormalize(weights: dict[str, float]) -> dict[str, float]:
    total = sum(weights.values())
    if total <= 0:
        return {}
    return {k: v / total for k, v in weights.items()}


class SignalFusion:
    """Combine per-signal cross-sections into one score per symbol."""

    def fuse(
        self,
        signals: dict[str, dict[str, float]],
        cfg: FusionConfig | None = None,
        regime: str | None = None,
    ) -> dict[str, FusedScore]:
        cfg = cfg or FusionConfig()
        base_weights = cfg.regime_overrides.get(regime, cfg.weights) if regime else cfg.weights
        normalized: dict[str, dict[str, float]] = {}
        for name, cross in signals.items():
            if name not in base_weights or not cross:
                continue
            normalized[name] = _normalize(cross, cfg.normalize)

        symbols = sorted({s for cross in normalized.values() for s in cross})
        result: dict[str, FusedScore] = {}
        for symbol in symbols:
            avail = {k: cross[symbol] for k, cross in normalized.items() if symbol in cross}
            if not avail:
                continue
            if cfg.missing_signal_policy == "exclude" and set(avail) != set(base_weights):
                continue
            if cfg.missing_signal_policy == "neutral":
                filled = {k: avail.get(k, 0.5) for k in base_weights}
                w = _renormalize({k: base_weights[k] for k in filled})
                score = sum(filled[k] * w[k] for k in filled)
                result[symbol] = FusedScore(
                    final_score=score,
                    components=filled,
                    weights_used=w,
                    missing=sorted(set(base_weights) - set(avail)),
                )
                continue
            # renormalize (default)
            w = _renormalize({k: base_weights[k] for k in avail})
            score = sum(avail[k] * w[k] for k in avail)
            result[symbol] = FusedScore(
                final_score=score,
                components=avail,
                weights_used=w,
                missing=sorted(set(base_weights) - set(avail)),
            )
        return result
