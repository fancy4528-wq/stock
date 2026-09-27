"""L2 small-model triage — batch relevance / direction (P2b).

L1 remains zero-LLM. This module may call ``agents.llm`` under the
``monitoring`` budget allocation. On NullLLM / budget ``l1_only`` / errors,
callers get a deterministic fallback (heuristic or L1 passthrough).
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from quantagent.agents.llm.budget import TokenBudget
from quantagent.agents.llm.call import complete_with_budget
from quantagent.agents.llm.client import LLMClient
from quantagent.agents.llm.factory import build_llm_client, build_token_budget
from quantagent.agents.llm.prompts import load_prompt
from quantagent.agents.llm.structured import llm_enabled
from quantagent.monitor.cache import (
    AnalysisCache,
    L2CachedTriage,
    holdings_hash,
    resolve_content_hash,
)
from quantagent.monitor.types import TriggerHit
from quantagent.shared.errors import (
    BudgetDegrade,
    BudgetExceeded,
    BudgetSkip,
    SchemaValidationError,
)

logger = logging.getLogger(__name__)

Direction = Literal["pos", "neg", "neu", ""]
Urgency = Literal["immediate", "today", "this_week", "low", ""]
L2Mode = Literal["llm", "heuristic", "l1_passthrough", "cache"]

DEFAULT_BATCH_SIZE = 10
SUMMARY_CHARS = 200
_FENCE_RE = re.compile(r"```(?:json)?\s*([\s\S]*?)```", re.IGNORECASE)
_DIR_ALIASES = {
    "positive": "pos",
    "pos": "pos",
    "negative": "neg",
    "neg": "neg",
    "neutral": "neu",
    "neu": "neu",
}


class L2Triage(BaseModel):
    """Program-consumed triage row — abbreviated fields, no reasoning."""

    i: int = Field(ge=1)
    rel: bool
    sym: list[str] = Field(default_factory=list)
    dir: Direction = ""
    urg: Urgency = ""
    deep: bool = False

    @field_validator("dir", mode="before")
    @classmethod
    def _norm_dir(cls, value: object) -> str:
        if value is None or value == "":
            return ""
        key = str(value).strip().lower()
        return _DIR_ALIASES.get(key, key if key in ("pos", "neg", "neu") else "")

    @field_validator("urg", mode="before")
    @classmethod
    def _norm_urg(cls, value: object) -> str:
        if value is None or value == "":
            return ""
        key = str(value).strip().lower()
        if key in ("immediate", "today", "this_week", "low"):
            return key
        return ""

    @field_validator("sym", mode="before")
    @classmethod
    def _norm_sym(cls, value: object) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            return [value] if value else []
        if isinstance(value, list):
            return [str(x) for x in value if x]
        return []


@dataclass(frozen=True)
class L2Candidate:
    """One L1-passed news item ready for L2."""

    title: str
    summary: str = ""
    candidate_symbols: list[str] = field(default_factory=list)
    uid: str = ""
    l1_severity: str = "medium"
    content_hash: str = ""


@dataclass
class L2Stats:
    candidates: int = 0
    batches: int = 0
    relevant: int = 0
    dropped: int = 0
    deep: int = 0
    cost_usd: float = 0.0
    mode: L2Mode = "heuristic"
    note: str = ""
    cache_hits: int = 0
    cache_misses: int = 0


def chunked(items: Sequence[Any], size: int) -> list[list[Any]]:
    n = max(1, int(size))
    return [list(items[i : i + n]) for i in range(0, len(items), n)]


def build_holdings_line(name_by_symbol: dict[str, str]) -> str:
    parts = [
        f"{sym}({name})" if name else sym
        for sym, name in sorted(name_by_symbol.items())
    ]
    return ", ".join(parts)


def build_batch_user_prompt(
    batch: Sequence[L2Candidate],
    *,
    name_by_symbol: dict[str, str],
    start_index: int = 1,
) -> str:
    holdings = build_holdings_line(name_by_symbol)
    lines = [
        f"持仓: {holdings}",
        "",
        "判断下列各条新闻是否影响持仓。按序号输出 JSON 数组，不解释。",
        "",
    ]
    for offset, item in enumerate(batch):
        idx = start_index + offset
        summary = (item.summary or "")[:SUMMARY_CHARS]
        cand = ",".join(item.candidate_symbols) if item.candidate_symbols else "-"
        lines.append(f"{idx}. 标题: {item.title}")
        if summary:
            lines.append(f"   摘要: {summary}")
        lines.append(f"   候选: {cand}")
    lines.append("")
    lines.append(
        '输出格式: [{"i":1,"rel":false},'
        '{"i":2,"rel":true,"sym":["600519.SH"],"dir":"neg","urg":"today","deep":true}]'
    )
    return "\n".join(lines)


def extract_json_array(text: str) -> list[Any]:
    raw = (text or "").strip()
    if not raw:
        raise SchemaValidationError("empty LLM response")
    m = _FENCE_RE.search(raw)
    if m:
        raw = m.group(1).strip()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        start = raw.find("[")
        end = raw.rfind("]")
        if start < 0 or end <= start:
            raise SchemaValidationError("LLM response is not a JSON array") from None
        try:
            data = json.loads(raw[start : end + 1])
        except json.JSONDecodeError as exc:
            raise SchemaValidationError(f"JSON array parse failed: {exc}") from exc
    if not isinstance(data, list):
        raise SchemaValidationError("LLM JSON root must be an array")
    return data


def parse_batch_response(
    text: str,
    *,
    batch_size: int,
    start_index: int = 1,
    allowed_symbols: set[str] | None = None,
) -> list[L2Triage]:
    rows = extract_json_array(text)
    by_i: dict[int, L2Triage] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        try:
            item = L2Triage.model_validate(row)
        except Exception:  # noqa: BLE001 — skip malformed rows
            continue
        if allowed_symbols is not None and item.sym:
            item = item.model_copy(
                update={"sym": [s for s in item.sym if s in allowed_symbols]}
            )
        by_i[item.i] = item

    out: list[L2Triage] = []
    for offset in range(batch_size):
        idx = start_index + offset
        if idx in by_i:
            out.append(by_i[idx])
        else:
            # Missing row → treat as not relevant (fail closed for push noise)
            out.append(L2Triage(i=idx, rel=False))
    return out


def heuristic_triage(candidate: L2Candidate, *, index: int) -> L2Triage:
    """Deterministic fallback when LLM is unavailable."""
    sev = (candidate.l1_severity or "medium").lower()
    if sev == "critical":
        return L2Triage(
            i=index,
            rel=True,
            sym=list(candidate.candidate_symbols),
            dir="neg",
            urg="immediate",
            deep=True,
        )
    if sev == "high":
        return L2Triage(
            i=index,
            rel=True,
            sym=list(candidate.candidate_symbols),
            dir="neu",
            urg="today",
            deep=False,
        )
    return L2Triage(
        i=index,
        rel=True,
        sym=list(candidate.candidate_symbols),
        dir="neu",
        urg="this_week",
        deep=False,
    )


async def triage_batch(
    candidates: Sequence[L2Candidate],
    *,
    name_by_symbol: dict[str, str],
    llm: LLMClient | None = None,
    budget: TokenBudget | None = None,
    batch_size: int = DEFAULT_BATCH_SIZE,
    tier: str = "small",
) -> tuple[list[L2Triage], L2Stats]:
    """Triage L1 candidates in batches. Returns one L2Triage per candidate (aligned)."""
    stats = L2Stats(candidates=len(candidates))
    if not candidates:
        return [], stats

    client = llm if llm is not None else build_llm_client(tier=tier)
    tok = budget if budget is not None else build_token_budget()

    if not llm_enabled(client):
        results = [
            heuristic_triage(c, index=i + 1) for i, c in enumerate(candidates)
        ]
        stats.mode = "heuristic"
        stats.note = "null_llm"
        _fill_stats(stats, results)
        return results, stats

    system = load_prompt("l2_triage")
    allowed = set(name_by_symbol) | {
        s for c in candidates for s in c.candidate_symbols
    }
    results: list[L2Triage] = []
    batches = chunked(list(candidates), batch_size)
    stats.batches = len(batches)
    stats.mode = "llm"
    start = 1

    for batch in batches:
        user = build_batch_user_prompt(
            batch, name_by_symbol=name_by_symbol, start_index=start
        )
        try:
            resp, _ = await complete_with_budget(
                client,
                tok,
                allocation="monitoring",
                tier=tier,
                system=system,
                user=user,
            )
            stats.cost_usd += float(resp.cost_usd or 0.0)
            parsed = parse_batch_response(
                resp.text,
                batch_size=len(batch),
                start_index=start,
                allowed_symbols=allowed,
            )
            results.extend(parsed)
        except BudgetSkip as exc:
            # monitoring on_exceed = l1_only → stop LLM, keep remaining as passthrough signal
            logger.info("L2 budget skip: %s", exc)
            stats.mode = "l1_passthrough"
            stats.note = str(exc)[:200]
            # Pad already-parsed + mark rest via empty sentinel handled by refine
            while len(results) < len(candidates):
                results.append(L2Triage(i=len(results) + 1, rel=True, deep=False))
            break
        except (BudgetExceeded, BudgetDegrade) as exc:
            logger.info("L2 budget block: %s", exc)
            stats.mode = "l1_passthrough"
            stats.note = str(exc)[:200]
            while len(results) < len(candidates):
                results.append(L2Triage(i=len(results) + 1, rel=True, deep=False))
            break
        except Exception as exc:  # noqa: BLE001
            logger.warning("L2 batch failed, heuristic for batch: %s", exc)
            if not stats.note:
                stats.note = f"llm_error:{type(exc).__name__}"
            for offset, cand in enumerate(batch):
                results.append(heuristic_triage(cand, index=start + offset))
            if stats.mode == "llm":
                stats.mode = "heuristic"
        start += len(batch)

    # Align length
    if len(results) < len(candidates):
        for i in range(len(results), len(candidates)):
            results.append(heuristic_triage(candidates[i], index=i + 1))
    results = results[: len(candidates)]
    _fill_stats(stats, results)
    return results, stats


def _fill_stats(stats: L2Stats, results: Sequence[L2Triage]) -> None:
    stats.relevant = sum(1 for r in results if r.rel)
    stats.dropped = sum(1 for r in results if not r.rel)
    stats.deep = sum(1 for r in results if r.rel and r.deep)


def candidate_from_hit(hit: TriggerHit) -> L2Candidate:
    ev = hit.evidence or {}
    syms = ev.get("mentioned_symbols") or ([hit.symbol] if hit.symbol else [])
    title = str(ev.get("title") or hit.message or "")
    summary = str(ev.get("summary") or "")[:SUMMARY_CHARS]
    explicit = ev.get("content_hash")
    return L2Candidate(
        title=title,
        summary=summary,
        candidate_symbols=[str(s) for s in syms if s],
        uid=hit.code.split("/", 1)[-1] if "/" in hit.code else hit.code,
        l1_severity=str(ev.get("l1_severity") or hit.severity or "medium"),
        content_hash=resolve_content_hash(
            explicit=str(explicit) if explicit else None,
            title=title,
            summary=summary,
        ),
    )


def _cached_to_triage(cached: L2CachedTriage, *, index: int) -> L2Triage:
    return L2Triage(
        i=index,
        rel=cached.rel,
        sym=list(cached.sym),
        dir=cached.dir or "",
        urg=cached.urg or "",
        deep=cached.deep,
    )


def _triage_to_cached(row: L2Triage) -> L2CachedTriage:
    return L2CachedTriage(
        rel=row.rel,
        sym=list(row.sym),
        dir=row.dir or "",
        urg=row.urg or "",
        deep=row.deep,
    )


def _apply_l2_rows(
    hits: Sequence[TriggerHit],
    triage: Sequence[L2Triage],
    *,
    mode: L2Mode,
    cost_usd: float,
    from_cache_idx: set[int] | None = None,
) -> tuple[list[TriggerHit], int, int]:
    """Drop rel=false; enrich keepers. Returns (out, relevant, dropped)."""
    cached = from_cache_idx or set()
    # Attribute LLM cost only to non-cache relevant rows
    billable = sum(
        1 for i, r in enumerate(triage) if r.rel and i not in cached
    )
    per_cost = (cost_usd / max(1, billable)) if billable else 0.0
    out: list[TriggerHit] = []
    for i, (hit, row) in enumerate(zip(hits, triage, strict=True)):
        if not row.rel:
            continue
        primary = row.sym[0] if row.sym else hit.symbol
        from_cache = i in cached
        row_mode: L2Mode = "cache" if from_cache else mode
        evidence = dict(hit.evidence or {})
        evidence.update(
            {
                "l2_rel": row.rel,
                "l2_sym": list(row.sym),
                "l2_dir": row.dir,
                "l2_urg": row.urg,
                "l2_deep": row.deep,
                "l2_mode": row_mode,
                "l2_cache_hit": from_cache,
                "needs_deep_analysis": row.deep,
            }
        )
        out.append(
            hit.model_copy(
                update={
                    "symbol": primary,
                    "analysis_level": "L2",
                    "cost_usd": float(hit.cost_usd or 0.0)
                    + (0.0 if from_cache else per_cost),
                    "evidence": evidence,
                }
            )
        )
    return out, len(out), len(hits) - len(out)


async def refine_news_hits_with_l2(
    hits: Sequence[TriggerHit],
    *,
    name_by_symbol: dict[str, str],
    llm: LLMClient | None = None,
    budget: TokenBudget | None = None,
    batch_size: int = DEFAULT_BATCH_SIZE,
    enabled: bool = True,
    cache: AnalysisCache | None = None,
) -> tuple[list[TriggerHit], L2Stats]:
    """Filter / enrich L1 news TriggerHits via L2.

    - ``enabled=False`` → L1 passthrough
    - NullLLM → heuristic (still marks analysis_level=L2); not written to cache
    - Budget ``l1_only`` → L1 passthrough (analysis_level stays L1)
    - LLM success → drop ``rel=false``; keep relevant with L2 evidence; cache store
    - Cache hit (same content_hash + holdings_hash) → skip LLM
    """
    stats = L2Stats(candidates=len(hits))
    if not hits:
        return [], stats
    if not enabled:
        stats.mode = "l1_passthrough"
        stats.note = "disabled"
        stats.relevant = len(hits)
        return list(hits), stats

    candidates = [candidate_from_hit(h) for h in hits]
    h_hash = holdings_hash(name_by_symbol.keys())

    triage: list[L2Triage | None] = [None] * len(hits)
    from_cache_idx: set[int] = set()
    miss_indices: list[int] = []
    miss_candidates: list[L2Candidate] = []

    if cache is not None:
        for i, cand in enumerate(candidates):
            cached = cache.get_l2(cand.content_hash, h_hash) if cand.content_hash else None
            if cached is not None:
                triage[i] = _cached_to_triage(cached, index=i + 1)
                from_cache_idx.add(i)
            else:
                miss_indices.append(i)
                miss_candidates.append(cand)
        stats.cache_hits = len(from_cache_idx)
        stats.cache_misses = len(miss_indices)
    else:
        miss_indices = list(range(len(hits)))
        miss_candidates = list(candidates)
        stats.cache_misses = len(hits)

    if not miss_indices:
        filled = [t for t in triage if t is not None]
        stats.mode = "cache"
        stats.note = "all_cache"
        stats.cost_usd = 0.0
        out, rel, dropped = _apply_l2_rows(
            hits, filled, mode="cache", cost_usd=0.0, from_cache_idx=from_cache_idx
        )
        stats.relevant = rel
        stats.dropped = dropped
        return out, stats

    miss_triage, miss_stats = await triage_batch(
        miss_candidates,
        name_by_symbol=name_by_symbol,
        llm=llm,
        budget=budget,
        batch_size=batch_size,
    )
    stats.batches = miss_stats.batches
    stats.cost_usd = miss_stats.cost_usd
    stats.mode = miss_stats.mode
    stats.note = miss_stats.note
    if stats.cache_hits and stats.mode != "l1_passthrough":
        suffix = f"cache_hits={stats.cache_hits}"
        stats.note = f"{stats.note};{suffix}" if stats.note else suffix

    if miss_stats.mode == "l1_passthrough":
        # Budget exhausted: keep rule-layer alerts, do not blend cache rows
        stats.relevant = len(hits)
        stats.dropped = 0
        return list(hits), stats

    for idx, row in zip(miss_indices, miss_triage, strict=True):
        triage[idx] = row.model_copy(update={"i": idx + 1})

    # Persist only real LLM judgements (not heuristic / passthrough)
    if cache is not None and miss_stats.mode == "llm":
        for hit_i, row in zip(miss_indices, miss_triage, strict=True):
            ch = candidates[hit_i].content_hash
            if ch:
                cache.set_l2(ch, h_hash, _triage_to_cached(row))

    filled = [
        t if t is not None else L2Triage(i=i + 1, rel=False) for i, t in enumerate(triage)
    ]
    out, rel, dropped = _apply_l2_rows(
        hits,
        filled,
        mode=stats.mode,
        cost_usd=stats.cost_usd,
        from_cache_idx=from_cache_idx,
    )
    stats.relevant = rel
    stats.dropped = dropped
    return out, stats


__all__ = [
    "DEFAULT_BATCH_SIZE",
    "L2Candidate",
    "L2Stats",
    "L2Triage",
    "build_batch_user_prompt",
    "candidate_from_hit",
    "chunked",
    "extract_json_array",
    "heuristic_triage",
    "parse_batch_response",
    "refine_news_hits_with_l2",
    "triage_batch",
]
