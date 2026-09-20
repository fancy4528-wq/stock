"""StockAgent — StockView producer (deterministic skeleton)."""

from __future__ import annotations

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

        rag_excerpt = ""
        if self._tools is not None and "search_knowledge" in self._tools.names():
            try:
                hits = self._tools.call(
                    "search_knowledge",
                    {
                        "query": f"{seed.symbol} {seed.name} 风险 管理层",
                        "top_k": 3,
                    },
                    ctx,
                )
                if hits:
                    rag_excerpt = str(hits[0].get("doc_ref", ""))[:80]
            except Exception:  # noqa: BLE001
                rag_excerpt = ""

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
                excerpt=(f"name={seed.name}" + (f" rag={rag_excerpt}" if rag_excerpt else ""))[
                    :400
                ],
                as_of=ctx.as_of,
            ),
        ]

        dims = StockDimensions(
            fundamental=dim(0.5, "骨架：财务待接 get_financials"),
            valuation=dim(0.5, "骨架：估值待接"),
            growth=dim(0.5, "骨架：成长待接"),
            quality=dim(0.5, "骨架：质量待接"),
            momentum=dim(
                score_from_return(seed.ret_20d),
                f"ret_20d={seed.ret_20d:+.2%}",
                ["ev-stock-ret"],
            ),
            news=dim(0.5, "骨架：新闻面待接" + (f"；RAG:{rag_excerpt}" if rag_excerpt else "")),
            sector_fit=dim(
                seed.preliminary_score,
                f"板块 {seed.sector_code} 粗筛分",
                ["ev-stock-sector"],
            ),
        )

        view = StockView(
            as_of=ctx.as_of,
            symbol=seed.symbol,
            name=seed.name,
            score=score,
            confidence=conf,
            horizon="1m",
            thesis=(
                f"数据显示 {seed.name}（{seed.symbol}）20 日收益 "
                f"{seed.ret_20d:+.2%}，所属板块 {seed.sector_code}。"
                "骨架论点仅基于动量与粗筛分，待接财务/公告工具。"
            )[:800],
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
                    "骨架阶段缺少财务与公告校验，存在未识别 red flag 风险",
                    "moderate",
                    ["ev-stock-meta"],
                )
            ],
            catalysts=[],
            red_flags=[],
            financial_health=FinancialHealth(
                revenue_trend="flat",
                margin_trend="stable",
                cash_conversion="adequate",
                leverage="moderate",
                notes="骨架占位：未读取财务报表",
            ),
            risks=[risk(f"{seed.symbol} 信息不足导致误判")],
            evidence=ev,
        )
        require_evidence(view.evidence, min_count=3)
        return validate_model(view)  # type: ignore[return-value]
