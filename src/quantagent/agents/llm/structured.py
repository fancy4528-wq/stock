"""Budget-aware structured JSON completion for research Agents.

Null / missing key → caller keeps heuristic. Budget degrade retries once on a
smaller tier; skip / exceeded / parse failure → ``None`` (heuristic fallback).
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any, TypeVar

from pydantic import BaseModel

from quantagent.agents.llm.budget import DegradationNote, TokenBudget
from quantagent.agents.llm.call import complete_with_budget
from quantagent.agents.llm.client import LLMClient, LLMResponse, NullLLMClient
from quantagent.agents.llm.metering import CostRecord, CostTracker
from quantagent.agents.llm.prompts import load_common_constraints, load_prompt
from quantagent.shared.errors import (
    BudgetDegrade,
    BudgetExceeded,
    BudgetSkip,
    SchemaValidationError,
)

logger = logging.getLogger(__name__)

TModel = TypeVar("TModel", bound=BaseModel)

_FENCE_RE = re.compile(r"```(?:json)?\s*([\s\S]*?)```", re.IGNORECASE)


@dataclass
class ResearchLlmBundle:
    """Shared LLM + budget + cost sink for the research DAG."""

    llm: LLMClient
    budget: TokenBudget
    costs: CostTracker = field(default_factory=CostTracker)
    allocation: str = "daily_research"
    degradations: list[DegradationNote] = field(default_factory=list)

    def enabled(self) -> bool:
        if isinstance(self.llm, NullLLMClient):
            return False
        return getattr(self.llm, "model", "") != "null"


def llm_enabled(llm: LLMClient | None) -> bool:
    if llm is None:
        return False
    if isinstance(llm, NullLLMClient):
        return False
    return getattr(llm, "model", "") != "null"


def extract_json_object(text: str) -> dict[str, Any]:
    """Parse a JSON object from raw LLM text (allows ```json fences)."""
    raw = (text or "").strip()
    if not raw:
        raise SchemaValidationError("empty LLM response")
    m = _FENCE_RE.search(raw)
    if m:
        raw = m.group(1).strip()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        start = raw.find("{")
        end = raw.rfind("}")
        if start < 0 or end <= start:
            raise SchemaValidationError("LLM response is not a JSON object") from None
        try:
            data = json.loads(raw[start : end + 1])
        except json.JSONDecodeError as exc:
            raise SchemaValidationError(f"JSON parse failed: {exc}") from exc
    if not isinstance(data, dict):
        raise SchemaValidationError("LLM JSON root must be an object")
    return data


async def complete_research_json(
    bundle: ResearchLlmBundle,
    *,
    agent: str,
    tier: str,
    prompt_name: str,
    user_payload: dict[str, Any],
    run_id: str,
    user_prefix: str | None = None,
) -> dict[str, Any] | None:
    """Call LLM under ``daily_research`` budget; return parsed dict or ``None``."""
    if not bundle.enabled():
        return None

    system = load_common_constraints() + "\n\n" + load_prompt(prompt_name)
    prefix = user_prefix or (
        f"根据以下结构化数据生成 {prompt_name} 对应 schema 的 JSON（仅输出 JSON）：\n"
    )
    user = prefix + json.dumps(user_payload, ensure_ascii=False, default=str)

    try:
        resp = await _complete_with_degrade(bundle, tier=tier, system=system, user=user)
    except (BudgetSkip, BudgetExceeded, BudgetDegrade) as exc:
        note = DegradationNote(
            allocation=bundle.allocation,
            action=getattr(exc, "action", getattr(exc, "suggested_tier", "degrade")),
            reason=str(exc),
            impact=f"{agent}: 预算拦截，回退启发式",
        )
        bundle.degradations.append(note)
        _record_cost(
            bundle,
            run_id=run_id,
            agent=agent,
            model="budget_skip",
            mode="budget_skip",
        )
        return None
    except Exception as exc:  # noqa: BLE001 — transport / unexpected
        logger.warning("%s LLM call failed: %s", agent, exc)
        note = DegradationNote(
            allocation=bundle.allocation,
            action="llm_error",
            reason=str(exc)[:300],
            impact=f"{agent}: LLM 调用失败，回退启发式",
        )
        bundle.degradations.append(note)
        return None

    _record_cost(
        bundle,
        run_id=run_id,
        agent=agent,
        model=resp.model,
        mode="llm",
        cost_usd=resp.cost_usd,
        prompt_tokens=resp.prompt_tokens,
        completion_tokens=resp.completion_tokens,
    )
    if not resp.text.strip():
        return None
    try:
        return extract_json_object(resp.text)
    except SchemaValidationError as exc:
        logger.warning("%s JSON extract failed: %s", agent, exc)
        bundle.degradations.append(
            DegradationNote(
                allocation=bundle.allocation,
                action="schema_fail",
                reason=str(exc)[:300],
                impact=f"{agent}: JSON 解析失败，回退启发式",
            )
        )
        return None


async def complete_research_model(
    bundle: ResearchLlmBundle,
    *,
    agent: str,
    tier: str,
    prompt_name: str,
    user_payload: dict[str, Any],
    run_id: str,
    model_cls: type[TModel],
    inject: dict[str, Any] | None = None,
    user_prefix: str | None = None,
    repair_hint: str | None = None,
) -> TModel | None:
    """Parse LLM JSON into ``model_cls``; one schema-repair retry; else ``None``."""
    raw = await complete_research_json(
        bundle,
        agent=agent,
        tier=tier,
        prompt_name=prompt_name,
        user_payload=user_payload,
        run_id=run_id,
        user_prefix=user_prefix,
    )
    if raw is None:
        return None

    merged = dict(raw)
    if inject:
        merged.update(inject)

    try:
        return model_cls.model_validate(merged)
    except Exception as first_exc:  # noqa: BLE001
        if repair_hint is None or not bundle.enabled():
            logger.warning("%s schema validate failed: %s", agent, first_exc)
            bundle.degradations.append(
                DegradationNote(
                    allocation=bundle.allocation,
                    action="schema_fail",
                    reason=str(first_exc)[:300],
                    impact=f"{agent}: schema 校验失败，回退启发式",
                )
            )
            return None

        repair_payload = {
            **user_payload,
            "_validation_error": str(first_exc)[:500],
            "_previous_json": raw,
        }
        prefix = (
            (user_prefix or "")
            + "\n上次输出未通过 schema 校验，请按错误修复后仅输出合法 JSON。"
            f"\n错误：{first_exc}\n"
        )
        raw2 = await complete_research_json(
            bundle,
            agent=agent,
            tier=tier,
            prompt_name=prompt_name,
            user_payload=repair_payload,
            run_id=run_id,
            user_prefix=prefix,
        )
        if raw2 is None:
            return None
        merged2 = dict(raw2)
        if inject:
            merged2.update(inject)
        try:
            return model_cls.model_validate(merged2)
        except Exception as second_exc:  # noqa: BLE001
            logger.warning("%s schema repair failed: %s", agent, second_exc)
            bundle.degradations.append(
                DegradationNote(
                    allocation=bundle.allocation,
                    action="schema_fail",
                    reason=str(second_exc)[:300],
                    impact=f"{agent}: schema 修复仍失败，回退启发式",
                )
            )
            return None


async def _complete_with_degrade(
    bundle: ResearchLlmBundle,
    *,
    tier: str,
    system: str,
    user: str,
) -> LLMResponse:
    try:
        resp, _ = await complete_with_budget(
            bundle.llm,
            bundle.budget,
            allocation=bundle.allocation,
            tier=tier,
            system=system,
            user=user,
        )
        return resp
    except BudgetDegrade as exc:
        bundle.degradations.extend(bundle.budget.degradations[-1:])
        try:
            resp, _ = await complete_with_budget(
                bundle.llm,
                bundle.budget,
                allocation=bundle.allocation,
                tier=exc.suggested_tier,
                system=system,
                user=user,
            )
            return resp
        except (BudgetDegrade, BudgetSkip, BudgetExceeded):
            raise


def _record_cost(
    bundle: ResearchLlmBundle,
    *,
    run_id: str,
    agent: str,
    model: str,
    mode: str,
    cost_usd: float = 0.0,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
) -> None:
    bundle.costs.add(
        CostRecord(
            run_id=run_id,
            agent=agent,
            model=model,
            mode=mode,
            allocation=bundle.allocation,
            cost_usd=cost_usd,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
        )
    )


__all__ = [
    "ResearchLlmBundle",
    "complete_research_json",
    "complete_research_model",
    "extract_json_object",
    "llm_enabled",
]
