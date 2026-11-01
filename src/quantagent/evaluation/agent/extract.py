"""Pull raw score and confidence off research outputs.

Shadow ranking blends in a small confidence tie-break. IC and calibration
use the raw fields so confidence is not double-counted inside the score.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from quantagent.agents.schemas.views import MarketBrief, RankedStock, StockView
from quantagent.evaluation.agent.types import AgentScorePoint


def _clamp_confidence(value: float) -> float:
    return min(1.0, max(0.0, float(value)))


def _usable_score(value: float) -> bool:
    score = float(value)
    return score == score and score not in (float("inf"), float("-inf"))


def points_from_ranking(rows: Sequence[RankedStock]) -> list[AgentScorePoint]:
    """Last row wins when a symbol appears twice."""
    by_symbol: dict[str, AgentScorePoint] = {}
    for row in rows:
        if not _usable_score(row.score):
            continue
        by_symbol[row.symbol] = AgentScorePoint(
            symbol=row.symbol,
            score=float(row.score),
            confidence=_clamp_confidence(row.confidence),
        )
    return list(by_symbol.values())


def points_from_brief(brief: MarketBrief | None) -> list[AgentScorePoint]:
    if brief is None:
        return []
    return points_from_ranking(brief.stock_ranking)


def points_from_stock_views(views: Sequence[StockView]) -> list[AgentScorePoint]:
    by_symbol: dict[str, AgentScorePoint] = {}
    for view in views:
        if not _usable_score(view.score):
            continue
        by_symbol[view.symbol] = AgentScorePoint(
            symbol=view.symbol,
            score=float(view.score),
            confidence=_clamp_confidence(view.confidence),
            horizon=view.horizon,
        )
    return list(by_symbol.values())


def points_from_score_map(
    scores: Mapping[str, float],
    confidences: Mapping[str, float] | None = None,
    *,
    default_confidence: float = 0.5,
) -> list[AgentScorePoint]:
    """Build points when only a score map is available (synthetic pipeline)."""
    confidences = confidences or {}
    out: list[AgentScorePoint] = []
    for symbol, score in scores.items():
        if not _usable_score(score):
            continue
        raw_conf = confidences.get(symbol, default_confidence)
        out.append(
            AgentScorePoint(
                symbol=symbol,
                score=float(score),
                confidence=_clamp_confidence(raw_conf),
            )
        )
    return out
