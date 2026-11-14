"""Per-rebalance turnover cap (docs/09 §3.3 step ⑦)."""

from __future__ import annotations

from collections.abc import Mapping


def one_way_turnover(
    target: Mapping[str, float],
    current: Mapping[str, float],
) -> float:
    """One-way turnover = ½ Σ |w_target − w_current|."""
    keys = set(target) | set(current)
    return 0.5 * sum(abs(float(target.get(k, 0.0)) - float(current.get(k, 0.0))) for k in keys)


def limit_turnover(
    target: Mapping[str, float],
    current: Mapping[str, float],
    max_turnover: float,
) -> dict[str, float]:
    """Blend ``current`` toward ``target`` so one-way turnover ≤ ``max_turnover``.

    Priority when the unconstrained move is over the cap (docs/09 §3.3):
    full exits → reduces → new entries → adds. Within each bucket, larger
    |Δw| runs first. Missing keys are treated as weight 0.
    """
    if max_turnover < 0:
        raise ValueError("max_turnover must be >= 0")

    tgt = {k: float(v) for k, v in target.items() if abs(float(v)) > 1e-15}
    cur = {k: float(v) for k, v in current.items() if abs(float(v)) > 1e-15}
    keys = set(tgt) | set(cur)
    if not keys:
        return {}

    deltas = {k: tgt.get(k, 0.0) - cur.get(k, 0.0) for k in keys}
    if one_way_turnover(tgt, cur) <= max_turnover + 1e-12:
        return dict(tgt)

    result = dict(cur)
    budget = float(max_turnover)

    exits: list[tuple[str, float]] = []
    reduces: list[tuple[str, float]] = []
    entries: list[tuple[str, float]] = []
    adds: list[tuple[str, float]] = []
    for k, delta in deltas.items():
        c = cur.get(k, 0.0)
        t = tgt.get(k, 0.0)
        if delta < -1e-15:
            (exits if t <= 1e-15 else reduces).append((k, delta))
        elif delta > 1e-15:
            (entries if c <= 1e-15 else adds).append((k, delta))

    for bucket in (exits, reduces, entries, adds):
        bucket.sort(key=lambda item: abs(item[1]), reverse=True)
        budget = _apply_moves(result, bucket, budget)

    return {k: v for k, v in result.items() if abs(v) > 1e-15}


def _apply_moves(
    weights: dict[str, float],
    moves: list[tuple[str, float]],
    budget: float,
) -> float:
    """Spend one-way budget on ``moves``; mutate ``weights`` in place."""
    for symbol, desired in moves:
        if budget <= 1e-15:
            break
        need = 0.5 * abs(desired)
        if need <= 1e-15:
            continue
        take = min(need, budget)
        executed = desired * (take / need)
        new_w = weights.get(symbol, 0.0) + executed
        if abs(new_w) <= 1e-15:
            weights.pop(symbol, None)
        else:
            weights[symbol] = new_w
        budget -= take
    return budget
