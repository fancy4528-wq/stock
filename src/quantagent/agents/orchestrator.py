"""Orchestrator: Stage 4a screen → concurrent sector/macro → stocks → Chief.

Thin asyncio DAG per ADR-0003 (no LangChain). Failure policy from docs/06.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable, Sequence
from datetime import date
from typing import TypeVar, cast

from pydantic import BaseModel

from quantagent.agents.base import AgentContext
from quantagent.agents.chief.agent import ChiefAgent
from quantagent.agents.llm.budget import DegradationNote, TokenBudget
from quantagent.agents.macro.agent import MacroAgent, neutral_macro_view
from quantagent.agents.schemas.views import MacroView, MarketBrief, SectorView, StockView
from quantagent.agents.screener import Shortlist, screen_shortlist
from quantagent.agents.sector.industry import IndustryAgent, ThemeAgent
from quantagent.agents.stock.agent import StockAgent
from quantagent.agents.tools.dispatch import ToolRegistry
from quantagent.agents.tools.research_facts import ResearchFacts, StockSeed
from quantagent.shared.errors import BudgetDegrade, BudgetExceeded

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)


class OrchestratorResult(BaseModel):
    brief: MarketBrief | None = None
    aborted: bool = False
    abort_reason: str | None = None
    degradations: list[DegradationNote] = []
    skipped_sectors: list[str] = []
    skipped_stocks: list[str] = []
    shortlist: Shortlist | None = None


class Orchestrator:
    """Daily research DAG with concurrency limits and explicit degradation."""

    def __init__(
        self,
        *,
        max_concurrency: int = 5,
        max_stocks: int = 30,
        max_industries: int = 5,
        max_themes: int = 3,
        budget: TokenBudget | None = None,
        tools: ToolRegistry | None = None,
        stock_limit_on_degrade: int = 10,
    ) -> None:
        self.max_concurrency = max_concurrency
        self.max_stocks = max_stocks
        self.max_industries = max_industries
        self.max_themes = max_themes
        self.budget = budget
        self.tools = tools
        self.stock_limit_on_degrade = stock_limit_on_degrade
        self.degradations: list[DegradationNote] = []

    async def run_daily(
        self,
        as_of: date,
        market: str,
        facts: ResearchFacts,
        *,
        run_id: str | None = None,
    ) -> OrchestratorResult:
        rid = run_id or f"{as_of:%Y%m%d}-{market.lower()}-daily"
        ctx = AgentContext(
            as_of=as_of,
            market=market,
            run_id=rid,
            token_budget_usd=float(self.budget.config.allocations.get("daily_research", 0.8))
            if self.budget is not None
            else 1.0,
        )
        result = OrchestratorResult(degradations=list(self.degradations))

        # Stage 4a — pure quant
        shortlist = screen_shortlist(
            facts,
            max_industries=self.max_industries,
            max_themes=self.max_themes,
        )
        result.shortlist = shortlist

        # Stage 4b — macro + sectors concurrently
        macro, sectors, skipped_sectors = await self._run_macro_and_sectors(
            ctx, facts, shortlist
        )
        result.skipped_sectors = skipped_sectors

        candidates = self._merge_candidates(sectors, facts, limit=self.max_stocks)
        budget_note: str | None = None
        if self.budget is not None:
            remaining = self.budget.remaining("daily_research")
            if remaining <= 0:
                candidates = candidates[: self.stock_limit_on_degrade]
                budget_note = (
                    f"daily_research budget exhausted; "
                    f"stock agents capped at {len(candidates)}"
                )
                note = DegradationNote(
                    allocation="daily_research",
                    action="reduce_stock_agents",
                    reason="remaining budget <= 0 before stock stage",
                    impact=budget_note,
                )
                self.degradations.append(note)
                result.degradations.append(note)

        ctx2 = ctx.model_copy(
            update={
                "upstream": {
                    "macro": macro,
                    "sectors": sectors,
                    "skipped_sectors": skipped_sectors,
                    "budget_note": budget_note,
                    "news_count": facts.news_count,
                    "events_count": facts.events_count,
                }
            }
        )
        stocks, skipped_stocks = await self._run_stocks(candidates, ctx2)
        result.skipped_stocks = skipped_stocks

        ctx3 = ctx2.model_copy(
            update={
                "upstream": {
                    **ctx2.upstream,
                    "stocks": stocks,
                    "skipped_stocks": skipped_stocks,
                }
            }
        )

        brief = await self._run_chief(ctx3)
        if brief is None:
            result.aborted = True
            result.abort_reason = "ChiefAgent failed after retry"
            return result
        result.brief = brief
        result.degradations = list(self.degradations)
        return result

    async def _run_macro_and_sectors(
        self,
        ctx: AgentContext,
        facts: ResearchFacts,
        shortlist: Shortlist,
    ) -> tuple[MacroView, list[SectorView], list[str]]:
        macro_agent = MacroAgent(facts, tools=self.tools)
        industry_agents = [IndustryAgent(s) for s in shortlist.industry_seeds]
        theme_agents = [ThemeAgent(s) for s in shortlist.theme_seeds]

        macro_task = self._run_with_retry(macro_agent.run, ctx, retries=1)
        sector_runs: list[tuple[str, Awaitable[SectorView]]] = []
        for ind in industry_agents:
            sector_runs.append((ind._seed.code, ind.run(ctx)))  # noqa: SLF001
        for th in theme_agents:
            sector_runs.append((th._seed.code, th.run(ctx)))  # noqa: SLF001

        gathered = await asyncio.gather(
            macro_task,
            *[t for _, t in sector_runs],
            return_exceptions=True,
        )
        macro_result = gathered[0]
        sector_results = list(gathered[1:])

        if isinstance(macro_result, BaseException):
            logger.warning("MacroAgent failed: %s", macro_result)
            macro = neutral_macro_view(ctx, reason=str(macro_result))
            self.degradations.append(
                DegradationNote(
                    allocation="daily_research",
                    action="neutral_macro",
                    reason=str(macro_result),
                    impact="regime forced to neutral",
                )
            )
        else:
            macro = cast(MacroView, macro_result)

        sectors: list[SectorView] = []
        skipped: list[str] = []
        for (code, _), item in zip(sector_runs, sector_results, strict=True):
            if isinstance(item, BaseException):
                logger.warning("SectorAgent %s failed: %s", code, item)
                skipped.append(code)
                continue
            sectors.append(cast(SectorView, item))
        return macro, sectors, skipped

    async def _run_stocks(
        self,
        seeds: list[StockSeed],
        ctx: AgentContext,
    ) -> tuple[list[StockView], list[str]]:
        agents = [StockAgent(s, tools=self.tools) for s in seeds]
        return await self._run_bounded(agents, ctx)

    async def _run_bounded(
        self,
        agents: Sequence[StockAgent],
        ctx: AgentContext,
    ) -> tuple[list[StockView], list[str]]:
        sem = asyncio.Semaphore(self.max_concurrency)
        skipped: list[str] = []
        views: list[StockView] = []

        async def _one(agent: StockAgent) -> StockView | None:
            async with sem:
                try:
                    return await agent.run(ctx)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("StockAgent %s failed: %s", agent._seed.symbol, exc)  # noqa: SLF001
                    skipped.append(agent._seed.symbol)  # noqa: SLF001
                    return None

        results = await asyncio.gather(*[_one(a) for a in agents])
        for item in results:
            if item is not None:
                views.append(item)
        return views, skipped

    async def _run_chief(self, ctx: AgentContext) -> MarketBrief | None:
        agent = ChiefAgent()
        try:
            return await self._run_with_retry(agent.run, ctx, retries=1)
        except Exception as exc:  # noqa: BLE001
            logger.error("ChiefAgent aborted: %s", exc)
            return None

    async def _run_with_retry(
        self,
        fn: Callable[[AgentContext], Awaitable[T]],
        ctx: AgentContext,
        *,
        retries: int,
    ) -> T:
        last: BaseException | None = None
        for attempt in range(retries + 1):
            try:
                return await fn(ctx)
            except (BudgetExceeded, BudgetDegrade):
                raise
            except Exception as exc:  # noqa: BLE001
                last = exc
                logger.warning("agent retry %s/%s: %s", attempt + 1, retries + 1, exc)
        assert last is not None
        raise last

    def _merge_candidates(
        self,
        sectors: list[SectorView],
        facts: ResearchFacts,
        *,
        limit: int,
    ) -> list[StockSeed]:
        by_symbol: dict[str, StockSeed] = {}
        for sec in sectors:
            for cand in sec.candidates:
                if cand.symbol in by_symbol:
                    prev = by_symbol[cand.symbol]
                    if cand.preliminary_score > prev.preliminary_score:
                        by_symbol[cand.symbol] = StockSeed(
                            symbol=cand.symbol,
                            name=cand.name,
                            sector_code=sec.sector_code,
                            ret_20d=prev.ret_20d,
                            preliminary_score=cand.preliminary_score,
                        )
                    continue
                ret = 0.0
                for s in facts.stocks:
                    if s.symbol == cand.symbol:
                        ret = s.ret_20d
                        break
                by_symbol[cand.symbol] = StockSeed(
                    symbol=cand.symbol,
                    name=cand.name,
                    sector_code=sec.sector_code,
                    ret_20d=ret,
                    preliminary_score=cand.preliminary_score,
                )
        # Also include explicit stock seeds not already present
        for s in facts.stocks:
            by_symbol.setdefault(s.symbol, s)

        ordered = sorted(
            by_symbol.values(),
            key=lambda s: s.preliminary_score,
            reverse=True,
        )
        return ordered[: max(0, limit)]


async def run_research_smoke(
    facts: ResearchFacts,
    *,
    tools: ToolRegistry | None = None,
    max_stocks: int = 10,
) -> OrchestratorResult:
    """Convenience entry for CLI / tests."""
    orch = Orchestrator(tools=tools, max_stocks=max_stocks)
    return await orch.run_daily(facts.as_of, facts.market, facts)
