"""IndustryAgent / ThemeAgent — SectorView producers (deterministic skeleton)."""

from __future__ import annotations

from typing import Literal

from quantagent.agents._heuristic import evidence, point, risk, score_from_return
from quantagent.agents.base import AgentContext
from quantagent.agents.schemas.views import (
    SectorDimensions,
    SectorView,
    StockCandidate,
    ThemeLifecycle,
)
from quantagent.agents.tools.research_facts import SectorSeed
from quantagent.agents.validation import require_evidence, validate_model
from quantagent.shared.errors import AgentError


def _sector_dimensions(seed: SectorSeed, score: float) -> SectorDimensions:
    from quantagent.agents._heuristic import dim

    mom = score_from_return(seed.ret_20d)
    day = score_from_return(seed.ret_1d)
    return SectorDimensions(
        fundamental=dim(0.5, "骨架：基本面待接财务汇总工具"),
        valuation=dim(0.5, "骨架：估值待接估值分位工具"),
        momentum=dim(mom, f"ret_20d={seed.ret_20d:+.2%}", ["ev-sector-ret"]),
        flow=dim(0.5, "骨架：资金流待接"),
        news_sentiment=dim(day, f"ret_1d={seed.ret_1d:+.2%}", ["ev-sector-ret"]),
        macro_fit=dim(score, "与粗筛动量对齐的占位分", ["ev-sector-ret"]),
    )


def _build_sector_view(
    ctx: AgentContext,
    *,
    seed: SectorSeed,
    sector_type: Literal["industry", "theme"],
    horizon: Literal["1w", "1m", "3m", "6m"],
    lifecycle: ThemeLifecycle | None = None,
) -> SectorView:
    score = score_from_return(0.6 * seed.ret_20d + 0.4 * seed.ret_1d)
    conf = 0.45 if abs(seed.ret_20d) < 0.02 else 0.6
    ev = [
        evidence(
            "ev-sector-ret",
            kind="sector",
            ref_id=f"sector:{seed.code}:{ctx.as_of.isoformat()}",
            excerpt=f"{seed.code} ret_1d={seed.ret_1d:+.4f} ret_20d={seed.ret_20d:+.4f}",
            as_of=ctx.as_of,
        ),
        evidence(
            "ev-sector-meta",
            kind="quality",
            ref_id=f"sector-meta:{seed.code}:{ctx.run_id}",
            excerpt=f"type={sector_type} name={seed.name}",
            as_of=ctx.as_of,
        ),
    ]
    candidates = [
        StockCandidate(
            symbol=c.symbol,
            name=c.name,
            role=c.role,
            preliminary_score=c.preliminary_score,
            reason=f"粗筛候选，板块 {seed.code}",
        )
        for c in seed.candidates[:10]
    ]
    bull = point(
        f"{seed.name} 近端动量 {seed.ret_1d:+.2%} / 20日 {seed.ret_20d:+.2%}",
        "moderate" if seed.ret_1d >= 0 else "weak",
        ["ev-sector-ret"],
    )
    bear = point(
        f"{seed.name} 存在动量回撤与政策/估值不确定性（骨架占位）",
        "moderate",
        ["ev-sector-meta"],
    )
    view = SectorView(
        as_of=ctx.as_of,
        sector_type=sector_type,
        sector_code=seed.code,
        sector_name=seed.name,
        score=score,
        confidence=conf,
        horizon=horizon,
        thesis=(
            f"数据显示 {seed.name}（{seed.code}）近端收益 "
            f"{seed.ret_1d:+.2%}，20 日 {seed.ret_20d:+.2%}。"
            "骨架阶段论点仅基于粗筛动量，待接财务与新闻工具。"
        )[:800],
        dimensions=_sector_dimensions(seed, score),
        bull_points=[bull],
        bear_points=[bear],
        key_uncertainties=["骨架未接基本面与资金流，置信度受限"],
        candidates=candidates,
        risks=[risk(f"{seed.name} 短期波动与流动性风险")],
        theme_lifecycle=lifecycle,
        evidence=ev,
    )
    require_evidence(view.evidence, min_count=2)
    return validate_model(view)  # type: ignore[return-value]


class IndustryAgent:
    name = "industry"
    tier = "medium"

    def __init__(self, seed: SectorSeed, *, force_fail: bool = False) -> None:
        self._seed = seed
        self._force_fail = force_fail

    async def run(self, ctx: AgentContext) -> SectorView:
        if self._force_fail:
            raise AgentError(f"industry agent forced failure: {self._seed.code}")
        return _build_sector_view(
            ctx,
            seed=self._seed,
            sector_type="industry",
            horizon="3m",
        )


class ThemeAgent:
    name = "theme"
    tier = "medium"

    def __init__(self, seed: SectorSeed, *, force_fail: bool = False) -> None:
        self._seed = seed
        self._force_fail = force_fail

    async def run(self, ctx: AgentContext) -> SectorView:
        if self._force_fail:
            raise AgentError(f"theme agent forced failure: {self._seed.code}")
        # Skeleton lifecycle: strong short-term momentum → acceleration, else emerging.
        stage: Literal["emerging", "acceleration", "peak", "declining", "dormant"]
        if self._seed.ret_1d >= 0.03 and self._seed.ret_20d >= 0.05:
            stage = "acceleration"
            days = 10
        elif self._seed.ret_20d <= -0.05:
            stage = "declining"
            days = 20
        else:
            stage = "emerging"
            days = 5
        lifecycle = ThemeLifecycle(
            stage=stage,
            days_since_activation=days,
            evidence=f"ret_1d={self._seed.ret_1d:+.2%} ret_20d={self._seed.ret_20d:+.2%}",
        )
        return _build_sector_view(
            ctx,
            seed=self._seed,
            sector_type="theme",
            horizon="1m",
            lifecycle=lifecycle,
        )
