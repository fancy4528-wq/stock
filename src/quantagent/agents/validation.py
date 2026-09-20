"""Agent output validation helpers (Gate 2: evidence + PIT + figure traceability)."""

from __future__ import annotations

import json
import math
import re
from collections.abc import Iterable, Sequence
from datetime import date
from typing import Any, Literal

from pydantic import BaseModel

from quantagent.agents.base import AgentContext, Evidence
from quantagent.agents.schemas.views import MarketBrief, SectorView, StockView
from quantagent.agents.trace import AgentTrace
from quantagent.shared.errors import EvidenceMissingError, SchemaValidationError

CheckLevel = Literal["FATAL", "WARN", "INFO"]

# Prose / claim fields — numbers here must be traceable (not structural scores).
_CLAIM_KEYS = frozenset(
    {
        "thesis",
        "note",
        "point",
        "reason",
        "market_summary",
        "regime_note",
        "regime_drivers",
        "one_liner",
        "rationale",
        "description",
        "risk",
        "flag",
        "watch_reason",
        "trigger",
        "data_quality_note",
        "notes",
    }
)

_NUM_RE = re.compile(
    r"(?<![A-Za-z_])(?P<sign>[-+]?)(?P<body>\d[\d,]*(?:\.\d+)?)(?P<pct>%?)(?![A-Za-z_])"
)
# "20日" / "20 日" are lookback labels, not market figures.
_DAY_LABEL_RE = re.compile(r"\d+\s*日")


class CheckResult(BaseModel):
    name: str
    passed: bool
    level: CheckLevel = "WARN"
    detail: str = ""


class ValidationResult(BaseModel):
    agent_name: str
    checks: list[CheckResult] = []
    untraceable_figures: list[float] = []
    untraceable_figure_count: int = 0

    @property
    def ok(self) -> bool:
        return not self.has_fatal

    @property
    def has_fatal(self) -> bool:
        return any(not c.passed and c.level == "FATAL" for c in self.checks)

    @property
    def has_warn(self) -> bool:
        return any(not c.passed and c.level == "WARN" for c in self.checks)

    def fatal_details(self) -> str:
        parts = [
            f"{c.name}: {c.detail}"
            for c in self.checks
            if not c.passed and c.level == "FATAL"
        ]
        return "; ".join(parts) or "validation failed"


def require_evidence(evidence: Sequence[Evidence], *, min_count: int = 1) -> None:
    if len(evidence) < min_count:
        raise EvidenceMissingError(
            f"expected at least {min_count} evidence items, got {len(evidence)}"
        )


def validate_model(model: BaseModel) -> BaseModel:
    """Re-validate a model instance (catches hand-built invalid objects)."""
    try:
        return model.__class__.model_validate(model.model_dump())
    except Exception as exc:  # noqa: BLE001 — wrap as SchemaValidationError
        raise SchemaValidationError(str(exc)) from exc


def extract_floats(text: str) -> list[float]:
    """Extract numeric values; ``12%`` → ``0.12`` and also keep ``12.0``."""
    cleaned = _DAY_LABEL_RE.sub("", text)
    out: list[float] = []
    for match in _NUM_RE.finditer(cleaned):
        raw = match.group("body").replace(",", "")
        try:
            value = float(raw)
        except ValueError:
            continue
        if match.group("sign") == "-":
            value = -value
        if match.group("pct"):
            out.append(value / 100.0)
            out.append(value)  # allow either form in the pool / claims
        else:
            out.append(value)
    return out


def _expand_derived(pool: set[float]) -> set[float]:
    """Allow simple sum/diff of pool numbers (e.g. breadth = up - down)."""
    expanded = set(pool)
    nums = [n for n in pool if abs(n) < 1e9]
    # Cap pairwise expansion for large tool payloads.
    if len(nums) > 40:
        nums = nums[:40]
    for i, a in enumerate(nums):
        for b in nums[i + 1 :]:
            expanded.add(a - b)
            expanded.add(b - a)
            expanded.add(a + b)
    return expanded


def _walk_claim_strings(node: Any, *, key: str | None = None) -> list[str]:
    """Collect prose claim strings; skip ``evidence: list[Evidence]`` (source pool)."""
    texts: list[str] = []
    if isinstance(node, dict):
        for k, v in node.items():
            # Top-level Evidence list is the source pool, not a claim surface.
            if k == "evidence" and isinstance(v, list):
                continue
            # ThemeLifecycle.evidence is free-text under the same key.
            if k == "evidence" and isinstance(v, str) and v.strip():
                texts.append(v)
                continue
            texts.extend(_walk_claim_strings(v, key=str(k)))
        return texts
    if isinstance(node, list):
        for item in node:
            texts.extend(_walk_claim_strings(item, key=key))
        return texts
    if key is not None and key in _CLAIM_KEYS and isinstance(node, str) and node.strip():
        texts.append(node)
    return texts


def _collect_evidence(output: BaseModel) -> list[Evidence]:
    raw = getattr(output, "evidence", None)
    if not isinstance(raw, list):
        return []
    return [e for e in raw if isinstance(e, Evidence)]


def _collect_evidence_refs(node: Any) -> list[str]:
    refs: list[str] = []
    if isinstance(node, dict):
        for k, v in node.items():
            if k == "evidence_refs" and isinstance(v, list):
                refs.extend(str(x) for x in v)
            else:
                refs.extend(_collect_evidence_refs(v))
    elif isinstance(node, list):
        for item in node:
            refs.extend(_collect_evidence_refs(item))
    return refs


def check_evidence_not_empty(output: BaseModel, *, min_count: int = 1) -> CheckResult:
    evidence = _collect_evidence(output)
    ok = len(evidence) >= min_count
    return CheckResult(
        name="evidence_not_empty",
        passed=ok,
        level="FATAL",
        detail="" if ok else f"expected >={min_count} evidence, got {len(evidence)}",
    )


def check_evidence_ids_exist(output: BaseModel) -> CheckResult:
    """Every ``evidence_refs`` entry must resolve to an ``evidence_id`` on the output."""
    evidence = _collect_evidence(output)
    known = {e.evidence_id for e in evidence}
    dumped = output.model_dump(mode="json")
    refs = _collect_evidence_refs(dumped)
    missing = sorted({r for r in refs if r not in known})
    ok = not missing
    return CheckResult(
        name="evidence_ids_exist",
        passed=ok,
        level="FATAL",
        detail="" if ok else f"dangling evidence_refs: {missing}",
    )


def check_evidence_pit(output: BaseModel, as_of: date) -> CheckResult:
    """Evidence ``as_of`` must not be after the agent context ``as_of`` (lookahead)."""
    future = [
        e.evidence_id
        for e in _collect_evidence(output)
        if e.as_of > as_of
    ]
    ok = not future
    return CheckResult(
        name="evidence_pit",
        passed=ok,
        level="FATAL",
        detail="" if ok else f"lookahead evidence: {future} (as_of={as_of.isoformat()})",
    )


def check_bear_points_present(output: BaseModel) -> CheckResult:
    if not isinstance(output, (SectorView, StockView)):
        return CheckResult(name="bear_points_present", passed=True, level="INFO")
    ok = len(output.bear_points) >= 1
    return CheckResult(
        name="bear_points_present",
        passed=ok,
        level="FATAL",
        detail="" if ok else "bear_points missing",
    )


def check_scores_in_range(output: BaseModel) -> CheckResult:
    """Defense in depth; Pydantic already enforces most score bounds."""
    try:
        validate_model(output)
    except SchemaValidationError as exc:
        return CheckResult(
            name="scores_in_range",
            passed=False,
            level="FATAL",
            detail=str(exc),
        )
    return CheckResult(name="scores_in_range", passed=True, level="INFO")


def check_symbols_valid(
    output: BaseModel,
    *,
    allowed_symbols: set[str] | None,
) -> CheckResult:
    if not allowed_symbols:
        return CheckResult(
            name="symbols_valid",
            passed=True,
            level="INFO",
            detail="skipped (no universe provided)",
        )
    mentioned: set[str] = set()
    if isinstance(output, StockView):
        mentioned.add(output.symbol)
    elif isinstance(output, SectorView):
        mentioned.update(c.symbol for c in output.candidates)
    elif isinstance(output, MarketBrief):
        mentioned.update(s.symbol for s in output.stock_ranking)
        for w in output.watchlist:
            if w.symbol:
                mentioned.add(w.symbol)
    bad = sorted(s for s in mentioned if s not in allowed_symbols)
    ok = not bad
    return CheckResult(
        name="symbols_valid",
        passed=ok,
        level="WARN",
        detail="" if ok else f"symbols outside universe: {bad}",
    )


def _json_dump(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, default=str)
    except TypeError:
        return str(value)


def _pool_numbers(trace: AgentTrace, evidence: Sequence[Evidence]) -> set[float]:
    pool: set[float] = set()
    for call in trace.tool_calls:
        if call.result is not None:
            pool.update(extract_floats(_json_dump(call.result)))
        if call.args:
            pool.update(extract_floats(_json_dump(call.args)))
    for _name, blob in trace.context_blobs:
        pool.update(extract_floats(_json_dump(blob)))
    for ev in evidence:
        if ev.excerpt:
            pool.update(extract_floats(ev.excerpt))
        pool.update(extract_floats(ev.ref_id))
    pool = {n for n in pool if not _is_year_like(n)}
    return _expand_derived(pool)


def _is_year_like(n: float) -> bool:
    if abs(n - round(n)) > 1e-9:
        return False
    return 1990 <= int(round(n)) <= 2100


def _figure_matches(claim: float, pool: Iterable[float]) -> bool:
    for t in pool:
        if math.isclose(claim, t, rel_tol=0.02, abs_tol=1e-6):
            return True
        if math.isclose(claim, t * 100.0, rel_tol=0.02, abs_tol=1e-4):
            return True
        if math.isclose(claim * 100.0, t, rel_tol=0.02, abs_tol=1e-4):
            return True
    return False


def collect_untraceable_figures(
    output: BaseModel, trace: AgentTrace
) -> list[float]:
    evidence = _collect_evidence(output)
    pool = _pool_numbers(trace, evidence)
    dumped = output.model_dump(mode="json")
    seen: set[float] = set()
    unmatched: list[float] = []
    for text in _walk_claim_strings(dumped):
        for n in extract_floats(text):
            if _is_year_like(n):
                continue
            key = round(n, 6)
            if key in seen:
                continue
            seen.add(key)
            if not _figure_matches(n, pool):
                unmatched.append(n)
    return unmatched


def check_figures_traceable(output: BaseModel, trace: AgentTrace) -> CheckResult:
    """Claim-field numbers must appear in tools / seeded context / evidence excerpts.

    WARN (not FATAL): derived ratios may be legitimate; Gate 2 monitors the rate.
    """
    unmatched = collect_untraceable_figures(output, trace)
    ok = not unmatched
    detail = ""
    if unmatched:
        preview = ", ".join(f"{n:g}" for n in unmatched[:8])
        detail = f"Untraceable figures ({len(unmatched)}): {preview}"
    return CheckResult(
        name="figures_traceable",
        passed=ok,
        level="WARN",
        detail=detail,
    )


def validate_agent_output(
    output: BaseModel,
    ctx: AgentContext,
    trace: AgentTrace,
    *,
    agent_name: str | None = None,
    allowed_symbols: set[str] | None = None,
    min_evidence: int = 1,
) -> ValidationResult:
    """Run Gate 2 layered checks. FATAL → ``has_fatal``; figures are WARN-only."""
    name = agent_name or trace.agent_name
    unmatched = collect_untraceable_figures(output, trace)
    detail = ""
    if unmatched:
        preview = ", ".join(f"{n:g}" for n in unmatched[:8])
        detail = f"Untraceable figures ({len(unmatched)}): {preview}"
    fig = CheckResult(
        name="figures_traceable",
        passed=not unmatched,
        level="WARN",
        detail=detail,
    )
    checks = [
        check_evidence_not_empty(output, min_count=min_evidence),
        check_evidence_ids_exist(output),
        check_evidence_pit(output, ctx.as_of),
        check_scores_in_range(output),
        check_bear_points_present(output),
        check_symbols_valid(output, allowed_symbols=allowed_symbols),
        fig,
    ]
    return ValidationResult(
        agent_name=name,
        checks=checks,
        untraceable_figures=unmatched,
        untraceable_figure_count=len(unmatched),
    )
