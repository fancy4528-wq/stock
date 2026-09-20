"""Stage 4a: pure-quant shortlist (no LLM)."""

from __future__ import annotations

from pydantic import BaseModel, Field

from quantagent.agents.tools.research_facts import ResearchFacts, SectorSeed


class Shortlist(BaseModel):
    industries: list[str] = Field(default_factory=list)
    themes: list[str] = Field(default_factory=list)
    industry_seeds: list[SectorSeed] = Field(default_factory=list)
    theme_seeds: list[SectorSeed] = Field(default_factory=list)


def screen_shortlist(
    facts: ResearchFacts,
    *,
    max_industries: int = 5,
    max_themes: int = 3,
) -> Shortlist:
    """Rank sectors by |ret_20d| then ret_1d; truncate to Top-N / Top-M."""

    def _rank(seeds: list[SectorSeed], limit: int) -> list[SectorSeed]:
        ordered = sorted(
            seeds,
            key=lambda s: (abs(s.ret_20d), s.ret_1d),
            reverse=True,
        )
        return ordered[: max(0, limit)]

    industries = _rank(facts.industries, max_industries)
    themes = _rank(facts.themes, max_themes)
    return Shortlist(
        industries=[s.code for s in industries],
        themes=[s.code for s in themes],
        industry_seeds=industries,
        theme_seeds=themes,
    )
