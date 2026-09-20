"""Tool dispatch: Agent schemas omit ``as_of``; framework injects it."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from typing import Any

from quantagent.agents.base import AgentContext
from quantagent.shared.errors import AgentError


class ToolError(AgentError):
    """Tool invocation failed or was rejected by the dispatcher."""


class ToolRegistry:
    """Register callables whose public schema has no ``as_of``.

    On dispatch, ``as_of`` is always taken from ``AgentContext`` and any
    agent-supplied ``as_of`` is rejected (PIT hard rule).
    """

    def __init__(self) -> None:
        self._tools: dict[str, Callable[..., Any]] = {}

    def register(self, name: str, fn: Callable[..., Any]) -> None:
        if not name.strip():
            raise ToolError("tool name must be non-empty")
        self._tools[name] = fn

    def names(self) -> list[str]:
        return sorted(self._tools)

    def call(self, name: str, args: dict[str, Any], ctx: AgentContext) -> Any:
        if name not in self._tools:
            raise ToolError(f"unknown tool: {name}")
        if "as_of" in args:
            raise ToolError(
                f"tool {name!r}: agents must not pass as_of; framework injects it"
            )
        payload = dict(args)
        payload["as_of"] = ctx.as_of
        try:
            return self._tools[name](**payload)
        except TypeError as exc:
            raise ToolError(f"tool {name!r} bad args: {exc}") from exc
        except ToolError:
            raise
        except Exception as exc:  # noqa: BLE001 — surface as ToolError to agent
            raise ToolError(f"tool {name!r} failed: {exc}") from exc


def require_as_of(as_of: date | None) -> date:
    if as_of is None:
        raise ToolError("as_of is required (framework must inject it)")
    return as_of
