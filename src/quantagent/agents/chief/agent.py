"""ChiefAgent — aggregate upstream views into MarketBrief."""

from __future__ import annotations

from typing import Any, Literal

from quantagent.agents._heuristic import evidence
from quantagent.agents.base import AgentContext, Evidence
from quantagent.agents.llm.structured import ResearchLlmBundle, complete_research_model
from quantagent.agents.schemas.views import (
    AllocationStance,
    ChiefRefinePatch,
    Disagreement,
    InputsSummary,
    MacroView,
    MarketBrief,
    RankedSector,
    RankedStock,
    SectorView,
    StockView,
    WatchItem,
)
from quantagent.agents.validation import require_evidence, validate_model
from quantagent.shared.errors import AgentError


class ChiefAgent:
    name = "chief"
    tier = "large"

    def __init__(
        self,
        *,
        llm: ResearchLlmBundle | None = None,
        force_fail: bool = False,
    ) -> None:
        self._llm = llm
        self._force_fail = force_fail

    async def run(self, ctx: AgentContext) -> MarketBrief:
        if self._force_fail:
            raise AgentError("chief agent forced failure")

        heuristic = self._build_heuristic(ctx)
        if self._llm is None or not self._llm.enabled():
            return heuristic

        # LLM only emits prose fields; rankings/evidence stay on the heuristic.
        # Hard cap output — large essays / full MarketBrief rewrites truncate.
        patch = await complete_research_model(
            self._llm,
            agent=self.name,
            tier=self.tier,
            prompt_name="chief",
            user_payload={"scaffold": _compact_scaffold(heuristic)},
            run_id=ctx.run_id,
            model_cls=ChiefRefinePatch,
            repair_hint="retry",
            max_tokens_out=1024,
            user_prefix=(
                "在 scaffold 基础上 refinement 叙事字段"
                "（market_summary≤600 / regime_note≤300 / allocation_stance / "
                "disagreements / key_uncertainties / watchlist）；"
                "不要输出 ranking、evidence、as_of、run_id、regime、inputs_summary；"
                "allocation_stance 只给方向不给权重；字符串遵守 max_length；"
                "仅输出精简 ChiefRefinePatch JSON，示例："
                '{"market_summary":"…","regime_note":"…",'
                '"allocation_stance":{"equity_stance":"cautious","rationale":"…",'
                '"preferred_sectors":["801080"],"avoid_sectors":[]},'
                '"disagreements":[],"key_uncertainties":["…"],'
                '"watchlist":[{"sector_code":"801080","reason":"…","trigger":"…"}]}：\n'
            ),
        )
        if patch is None:
            return heuristic
        brief = heuristic.model_copy(
            update={
                "market_summary": patch.market_summary,
                "regime_note": patch.regime_note,
                "allocation_stance": patch.allocation_stance,
                "disagreements": patch.disagreements,
                "key_uncertainties": patch.key_uncertainties,
                "watchlist": patch.watchlist,
            }
        )
        require_evidence(brief.evidence, min_count=1)
        return validate_model(brief)  # type: ignore[return-value]

    def _build_heuristic(self, ctx: AgentContext) -> MarketBrief:
        macro = ctx.upstream.get("macro")
        sectors_raw = ctx.upstream.get("sectors")
        stocks_raw = ctx.upstream.get("stocks")
        if not isinstance(macro, MacroView):
            raise AgentError("ChiefAgent requires upstream macro: MacroView")
        sectors: list[SectorView] = list(sectors_raw) if isinstance(sectors_raw, list) else []
        stocks: list[StockView] = list(stocks_raw) if isinstance(stocks_raw, list) else []
        if not sectors:
            raise AgentError("ChiefAgent requires at least one SectorView")

        sector_ranking = [
            RankedSector(
                rank=i + 1,
                sector_code=s.sector_code,
                sector_name=s.sector_name,
                sector_type=s.sector_type,
                score=s.score,
                confidence=s.confidence,
                one_liner=s.thesis[:120],
                change_from_prev="new",
            )
            for i, s in enumerate(sorted(sectors, key=lambda x: x.score, reverse=True))
        ]

        stock_ranking: list[RankedStock] = []
        for i, stk in enumerate(sorted(stocks, key=lambda x: x.score, reverse=True)):
            hint: Literal["strong_candidate", "candidate", "watch", "avoid"]
            if stk.score >= 0.65:
                hint = "strong_candidate"
            elif stk.score >= 0.5:
                hint = "candidate"
            elif stk.score >= 0.35:
                hint = "watch"
            else:
                hint = "avoid"
            stock_ranking.append(
                RankedStock(
                    rank=i + 1,
                    symbol=stk.symbol,
                    name=stk.name,
                    sector_code=next(
                        (
                            sec.sector_code
                            for sec in sectors
                            if any(c.symbol == stk.symbol for c in sec.candidates)
                        ),
                        "UNKNOWN",
                    ),
                    score=stk.score,
                    confidence=stk.confidence,
                    action_hint=hint,
                    one_liner=stk.thesis[:120],
                )
            )

        equity_stance: Literal["aggressive", "moderate", "defensive", "cautious"]
        if macro.regime == "risk_off":
            equity_stance = "defensive"
        elif macro.regime == "risk_on":
            equity_stance = "moderate"
        else:
            equity_stance = "cautious"

        preferred = [r.sector_code for r in sector_ranking[:3]]
        avoid = [r.sector_code for r in sector_ranking[-1:]] if len(sector_ranking) > 1 else []

        quality_bits: list[str] = []
        if macro.degraded:
            quality_bits.append(macro.degrade_reason or "macro degraded")
        skipped_sectors = [str(x) for x in list(ctx.upstream.get("skipped_sectors") or [])]
        skipped_stocks = [str(x) for x in list(ctx.upstream.get("skipped_stocks") or [])]
        if skipped_sectors:
            quality_bits.append(f"skipped sectors: {','.join(skipped_sectors)}")
        if skipped_stocks:
            quality_bits.append(f"skipped stocks: {','.join(skipped_stocks)}")
        budget_note = ctx.upstream.get("budget_note")
        if isinstance(budget_note, str) and budget_note:
            quality_bits.append(budget_note)

        disagreements: list[Disagreement] = []
        if stocks and sectors:
            top_sec = sector_ranking[0]
            top_stk = stock_ranking[0] if stock_ranking else None
            if top_stk and top_stk.sector_code != top_sec.sector_code:
                disagreements.append(
                    Disagreement(
                        subject="板块与个股排序不完全一致",
                        positions=[
                            f"Top sector {top_sec.sector_code}",
                            f"Top stock {top_stk.symbol}@{top_stk.sector_code}",
                        ],
                        resolution="保留双方排序，由 Fusion/人工复核",
                    )
                )

        ev: list[Evidence] = [
            evidence(
                "ev-chief-macro",
                kind="quality",
                ref_id=f"macro:{macro.regime}",
                excerpt=(
                    f"regime={macro.regime} conf={macro.regime_confidence:.2f} "
                    f"sectors={len(sectors)} stocks={len(stocks)}"
                ),
                as_of=ctx.as_of,
            ),
            *macro.evidence[:2],
        ]
        for sec in sectors[:3]:
            ev.extend(sec.evidence[:1])
        for stk in stocks[:3]:
            ev.extend(stk.evidence[:1])

        # Deduplicate by evidence_id while preserving order
        seen: set[str] = set()
        deduped: list[Evidence] = []
        for item in ev:
            if item.evidence_id in seen:
                continue
            seen.add(item.evidence_id)
            deduped.append(item)

        summary = (
            f"数据显示 regime={macro.regime}（conf={macro.regime_confidence:.2f}）；"
            f"研究板块 {len(sectors)} 个、个股 {len(stocks)} 个。"
            f"领先板块：{sector_ranking[0].sector_name}（{sector_ranking[0].score:.2f}）。"
        )[:600]

        brief = MarketBrief(
            as_of=ctx.as_of,
            run_id=ctx.run_id,
            market_summary=summary,
            regime=macro.regime,
            regime_note=("；".join(macro.regime_drivers))[:300],
            sector_ranking=sector_ranking,
            stock_ranking=stock_ranking,
            allocation_stance=AllocationStance(
                equity_stance=equity_stance,
                rationale=f"由宏观 regime={macro.regime} 映射的方向性建议（非仓位）"[:300],
                preferred_sectors=preferred,
                avoid_sectors=avoid,
            ),
            disagreements=disagreements,
            key_uncertainties=[
                "骨架阶段多数维度为占位，置信度受限",
                *macro.regime_drivers[:1],
            ],
            watchlist=[
                WatchItem(
                    sector_code=sector_ranking[0].sector_code,
                    reason="当日领先板块",
                    trigger="score 位居短名单首位",
                )
            ],
            inputs_summary=InputsSummary(
                data_as_of=ctx.as_of,
                data_quality_note=("；".join(quality_bits)[:400] if quality_bits else None),
                sector_count=len(sectors),
                stock_count=len(stocks),
                skipped_sectors=skipped_sectors,
                skipped_stocks=skipped_stocks,
                news_count=int(ctx.upstream.get("news_count") or 0),
                events_count=int(ctx.upstream.get("events_count") or 0),
            ),
            evidence=deduped,
        )
        require_evidence(brief.evidence, min_count=1)
        return validate_model(brief)  # type: ignore[return-value]


def _compact_scaffold(brief: MarketBrief) -> dict[str, Any]:
    """Prompt payload without evidence / full ids — rankings as compact rows."""
    return {
        "regime": brief.regime,
        "market_summary": brief.market_summary,
        "regime_note": brief.regime_note,
        "allocation_stance": brief.allocation_stance.model_dump(mode="json"),
        "sector_ranking": [
            {
                "rank": r.rank,
                "sector_code": r.sector_code,
                "sector_name": r.sector_name,
                "score": r.score,
                "one_liner": r.one_liner,
            }
            for r in brief.sector_ranking
        ],
        "stock_ranking": [
            {
                "rank": r.rank,
                "symbol": r.symbol,
                "name": r.name,
                "sector_code": r.sector_code,
                "score": r.score,
                "action_hint": r.action_hint,
                "one_liner": r.one_liner,
            }
            for r in brief.stock_ranking
        ],
        "disagreements": [d.model_dump(mode="json") for d in brief.disagreements],
        "key_uncertainties": list(brief.key_uncertainties),
        "watchlist": [w.model_dump(mode="json") for w in brief.watchlist],
        "data_quality_note": brief.inputs_summary.data_quality_note,
        "sector_count": brief.inputs_summary.sector_count,
        "stock_count": brief.inputs_summary.stock_count,
    }
