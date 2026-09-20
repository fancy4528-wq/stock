"""Default ResearchFacts fixture for research-smoke / unit tests."""

from __future__ import annotations

from datetime import date

from quantagent.agents.tools.research_facts import (
    CandidateSeed,
    ResearchFacts,
    SectorSeed,
    StockSeed,
)


def sample_research_facts(as_of: date | None = None) -> ResearchFacts:
    day = as_of or date(2026, 9, 12)
    return ResearchFacts(
        as_of=day,
        market="CN",
        index_return_1d=0.008,
        n_up=2100,
        n_down=1800,
        total_amount=9.5e11,
        macro_note="skeleton sample: mild risk-on breadth",
        news_count=12,
        events_count=4,
        industries=[
            SectorSeed(
                code="801080",
                name="电子",
                ret_1d=0.021,
                ret_20d=0.065,
                candidates=[
                    CandidateSeed(
                        symbol="002415.SZ",
                        name="海康威视",
                        role="龙头",
                        preliminary_score=0.72,
                    ),
                    CandidateSeed(
                        symbol="603501.SH",
                        name="韦尔股份",
                        role="弹性标的",
                        preliminary_score=0.61,
                    ),
                ],
            ),
            SectorSeed(
                code="801750",
                name="计算机",
                ret_1d=0.012,
                ret_20d=0.04,
                candidates=[
                    CandidateSeed(
                        symbol="002230.SZ",
                        name="科大讯飞",
                        role="龙头",
                        preliminary_score=0.58,
                    ),
                ],
            ),
            SectorSeed(
                code="801780",
                name="银行",
                ret_1d=-0.004,
                ret_20d=-0.01,
                candidates=[
                    CandidateSeed(
                        symbol="601398.SH",
                        name="工商银行",
                        role="防御",
                        preliminary_score=0.42,
                    ),
                ],
            ),
        ],
        themes=[
            SectorSeed(
                code="BK0493",
                name="人工智能",
                ret_1d=0.035,
                ret_20d=0.08,
                candidates=[
                    CandidateSeed(
                        symbol="002230.SZ",
                        name="科大讯飞",
                        role="题材龙头",
                        preliminary_score=0.7,
                    ),
                ],
            ),
            SectorSeed(
                code="BK0884",
                name="华为概念",
                ret_1d=0.01,
                ret_20d=0.02,
                candidates=[],
            ),
        ],
        stocks=[
            StockSeed(
                symbol="002415.SZ",
                name="海康威视",
                sector_code="801080",
                ret_20d=0.05,
                preliminary_score=0.72,
            ),
            StockSeed(
                symbol="603501.SH",
                name="韦尔股份",
                sector_code="801080",
                ret_20d=0.09,
                preliminary_score=0.61,
            ),
            StockSeed(
                symbol="002230.SZ",
                name="科大讯飞",
                sector_code="801750",
                ret_20d=0.07,
                preliminary_score=0.7,
            ),
            StockSeed(
                symbol="601398.SH",
                name="工商银行",
                sector_code="801780",
                ret_20d=-0.02,
                preliminary_score=0.42,
            ),
        ],
    )
