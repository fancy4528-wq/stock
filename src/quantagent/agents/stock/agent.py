"""StockAgent — StockView producer (heuristic + optional DB tools)."""

from __future__ import annotations

from typing import Any, Literal

from quantagent.agents._heuristic import dim, evidence, point, risk, score_from_return
from quantagent.agents.base import AgentContext
from quantagent.agents.schemas.views import (
    FinancialHealth,
    StockDimensions,
    StockView,
)
from quantagent.agents.tools.dispatch import ToolRegistry
from quantagent.agents.tools.research_facts import StockSeed
from quantagent.agents.validation import require_evidence, validate_model
from quantagent.shared.errors import AgentError


def _tool_call(
    tools: ToolRegistry | None,
    name: str,
    args: dict[str, Any],
    ctx: AgentContext,
) -> Any | None:
    if tools is None or name not in tools.names():
        return None
    try:
        return tools.call(name, args, ctx)
    except Exception:  # noqa: BLE001
        return None


def _health_from_rows(
    fin_rows: list[dict[str, Any]],
    ind_rows: list[dict[str, Any]],
) -> FinancialHealth:
    if not fin_rows and not ind_rows:
        return FinancialHealth(
            revenue_trend="flat",
            margin_trend="stable",
            cash_conversion="adequate",
            leverage="moderate",
            notes="未读取到财务报表/指标",
        )

    rev_trend: Literal["accelerating", "growing", "flat", "declining"] = "flat"
    margin_trend: Literal["expanding", "stable", "compressing"] = "stable"
    cash: Literal["strong", "adequate", "weak"] = "adequate"
    leverage: Literal["low", "moderate", "high", "concerning"] = "moderate"
    notes_parts: list[str] = []

    if len(fin_rows) >= 2:
        r0 = fin_rows[0].get("revenue")
        r1 = fin_rows[1].get("revenue")
        try:
            if r0 is not None and r1 is not None and float(r1) > 0:
                g = float(r0) / float(r1) - 1.0
                if g >= 0.15:
                    rev_trend = "accelerating"
                elif g >= 0.02:
                    rev_trend = "growing"
                elif g <= -0.05:
                    rev_trend = "declining"
                notes_parts.append(f"revenue_qoq≈{g:+.1%}")
        except (TypeError, ValueError):
            pass

    if ind_rows:
        latest = ind_rows[0]
        yoy = latest.get("revenue_yoy")
        gm = latest.get("gross_margin")
        debt = latest.get("debt_to_asset")
        ocf = latest.get("ocf_to_profit")
        try:
            if yoy is not None:
                y = float(yoy)
                if y >= 0.2:
                    rev_trend = "accelerating"
                elif y >= 0.05:
                    rev_trend = "growing"
                elif y <= -0.05:
                    rev_trend = "declining"
                notes_parts.append(f"revenue_yoy={y:+.1%}")
        except (TypeError, ValueError):
            pass
        try:
            prev_gm = ind_rows[1].get("gross_margin") if len(ind_rows) >= 2 else None
            if gm is not None and prev_gm is not None:
                d = float(gm) - float(prev_gm)
                if d >= 0.01:
                    margin_trend = "expanding"
                elif d <= -0.01:
                    margin_trend = "compressing"
        except (TypeError, ValueError):
            pass
        try:
            if debt is not None:
                d = float(debt)
                if d >= 0.7:
                    leverage = "concerning"
                elif d >= 0.5:
                    leverage = "high"
                elif d <= 0.3:
                    leverage = "low"
                notes_parts.append(f"debt_to_asset={d:.2f}")
        except (TypeError, ValueError):
            pass
        try:
            if ocf is not None:
                o = float(ocf)
                if o >= 1.0:
                    cash = "strong"
                elif o < 0.5:
                    cash = "weak"
                notes_parts.append(f"ocf_to_profit={o:.2f}")
        except (TypeError, ValueError):
            pass

    return FinancialHealth(
        revenue_trend=rev_trend,
        margin_trend=margin_trend,
        cash_conversion=cash,
        leverage=leverage,
        notes=("；".join(notes_parts) or "已读财务工具")[:300],
    )


class StockAgent:
    name = "stock"
    tier = "medium"

    def __init__(
        self,
        seed: StockSeed,
        *,
        tools: ToolRegistry | None = None,
        force_fail: bool = False,
    ) -> None:
        self._seed = seed
        self._tools = tools
        self._force_fail = force_fail

    async def run(self, ctx: AgentContext) -> StockView:
        if self._force_fail:
            raise AgentError(f"stock agent forced failure: {self._seed.symbol}")
        seed = self._seed
        score = score_from_return(seed.ret_20d, center=seed.preliminary_score)
        conf = min(0.7, 0.4 + abs(seed.ret_20d) * 2.0)

        fin = _tool_call(
            self._tools, "get_financials", {"symbol": seed.symbol, "periods": 4}, ctx
        )
        ind = _tool_call(
            self._tools,
            "get_financial_indicators",
            {"symbol": seed.symbol, "periods": 4},
            ctx,
        )
        val = _tool_call(
            self._tools, "get_valuation", {"symbol": seed.symbol, "lookback_years": 2}, ctx
        )
        events = _tool_call(
            self._tools,
            "get_stock_events",
            {"symbol": seed.symbol, "lookback_days": 14, "limit": 10},
            ctx,
        )
        hits = _tool_call(
            self._tools,
            "search_knowledge",
            {"query": f"{seed.symbol} {seed.name} 风险 管理层", "top_k": 3},
            ctx,
        )

        fin_rows = list((fin or {}).get("rows") or []) if isinstance(fin, dict) else []
        ind_rows = list((ind or {}).get("rows") or []) if isinstance(ind, dict) else []
        val_latest = (
            list((val or {}).get("latest") or []) if isinstance(val, dict) else []
        )
        event_rows = (
            list((events or {}).get("rows") or []) if isinstance(events, dict) else []
        )
        rag_excerpt = ""
        if hits and isinstance(hits, list) and hits:
            rag_excerpt = str(hits[0].get("doc_ref", ""))[:80]

        health = _health_from_rows(fin_rows, ind_rows)
        if fin_rows or ind_rows:
            conf = min(0.85, conf + 0.1)

        fund_note = health.notes if (fin_rows or ind_rows) else "财务工具无数据或未注册"
        val_note = "估值工具无数据或未注册"
        val_score = 0.5
        if val_latest:
            pe = val_latest[0].get("pe_ttm")
            pb = val_latest[0].get("pb")
            try:
                pe_f = float(pe) if pe is not None else None
                pb_f = float(pb) if pb is not None else None
                bits = []
                if pe_f is not None:
                    bits.append(f"PE_TTM={pe_f:.1f}")
                    # crude: very high PE → lower valuation score
                    if pe_f > 60:
                        val_score = 0.3
                    elif pe_f < 15:
                        val_score = 0.65
                    else:
                        val_score = 0.5
                if pb_f is not None:
                    bits.append(f"PB={pb_f:.2f}")
                val_note = "；".join(bits) if bits else val_note
            except (TypeError, ValueError):
                pass

        news_note = f"近端事件 {len(event_rows)} 条"
        if rag_excerpt:
            news_note += f"；RAG:{rag_excerpt}"
        news_score = 0.55 if event_rows else 0.45

        ev = [
            evidence(
                "ev-stock-ret",
                kind="price",
                ref_id=f"price:{seed.symbol}:{ctx.as_of.isoformat()}",
                excerpt=f"{seed.symbol} ret_20d={seed.ret_20d:+.4f}",
                as_of=ctx.as_of,
            ),
            evidence(
                "ev-stock-sector",
                kind="sector",
                ref_id=f"sector:{seed.sector_code}",
                excerpt=f"sector={seed.sector_code} prelim={seed.preliminary_score:.2f}",
                as_of=ctx.as_of,
            ),
            evidence(
                "ev-stock-meta",
                kind="quality",
                ref_id=f"stock-meta:{seed.symbol}:{ctx.run_id}",
                excerpt=(
                    f"name={seed.name}; fin_rows={len(fin_rows)}; "
                    f"events={len(event_rows)}; {fund_note}"
                )[:400],
                as_of=ctx.as_of,
            ),
        ]
        if fin_rows or ind_rows:
            ev.append(
                evidence(
                    "ev-stock-fin",
                    kind="financial",
                    ref_id=f"financial:{seed.symbol}",
                    excerpt=fund_note[:400],
                    as_of=ctx.as_of,
                )
            )

        dims = StockDimensions(
            fundamental=dim(
                0.55 if rev_ok(health) else 0.45,
                fund_note,
                ["ev-stock-fin"] if (fin_rows or ind_rows) else ["ev-stock-meta"],
            ),
            valuation=dim(
                val_score,
                val_note,
                ["ev-stock-meta"],
            ),
            growth=dim(
                0.6
                if health.revenue_trend in {"accelerating", "growing"}
                else 0.4
                if health.revenue_trend == "declining"
                else 0.5,
                f"revenue_trend={health.revenue_trend}",
                ["ev-stock-fin"] if (fin_rows or ind_rows) else ["ev-stock-meta"],
            ),
            quality=dim(
                0.6
                if health.cash_conversion == "strong"
                else 0.4
                if health.cash_conversion == "weak"
                else 0.5,
                f"cash={health.cash_conversion} lev={health.leverage}",
                ["ev-stock-fin"] if (fin_rows or ind_rows) else ["ev-stock-meta"],
            ),
            momentum=dim(
                score_from_return(seed.ret_20d),
                f"ret_20d={seed.ret_20d:+.2%}",
                ["ev-stock-ret"],
            ),
            news=dim(news_score, news_note, ["ev-stock-meta"]),
            sector_fit=dim(
                seed.preliminary_score,
                f"板块 {seed.sector_code} 粗筛分",
                ["ev-stock-sector"],
            ),
        )

        thesis_bits = [
            f"数据显示 {seed.name}（{seed.symbol}）20 日收益 {seed.ret_20d:+.2%}",
            f"所属板块 {seed.sector_code}",
        ]
        if fin_rows or ind_rows:
            thesis_bits.append(f"财务：{health.notes}")
        if val_latest:
            thesis_bits.append(f"估值：{val_note}")
        if event_rows:
            thesis_bits.append(f"近端结构化事件 {len(event_rows)} 条")

        view = StockView(
            as_of=ctx.as_of,
            symbol=seed.symbol,
            name=seed.name,
            score=score,
            confidence=conf,
            horizon="1m",
            thesis=("；".join(thesis_bits))[:800],
            dimensions=dims,
            bull_points=[
                point(
                    f"20 日动量 {seed.ret_20d:+.2%}",
                    "moderate" if seed.ret_20d >= 0 else "weak",
                    ["ev-stock-ret"],
                )
            ],
            bear_points=[
                point(
                    (
                        "财务杠杆/现金流需持续跟踪"
                        if (fin_rows or ind_rows)
                        else "缺少财务与公告校验，存在未识别 red flag 风险"
                    ),
                    "moderate",
                    ["ev-stock-fin"] if (fin_rows or ind_rows) else ["ev-stock-meta"],
                )
            ],
            catalysts=[],
            red_flags=[],
            financial_health=health,
            risks=[risk(f"{seed.symbol} 信息不足或财务滞后导致误判")],
            evidence=ev,
        )
        require_evidence(view.evidence, min_count=3)
        return validate_model(view)  # type: ignore[return-value]


def rev_ok(health: FinancialHealth) -> bool:
    return health.revenue_trend in {"accelerating", "growing"}
