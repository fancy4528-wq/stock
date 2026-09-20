"""Per-agent tool-call trace for Gate 2 output validation."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ToolCallRecord:
    name: str
    args: dict[str, Any]
    result: Any = None
    error: str | None = None


@dataclass
class AgentTrace:
    """In-memory trace for one agent invocation (not yet persisted to ``agent_trace``)."""

    agent_name: str
    tool_calls: list[ToolCallRecord] = field(default_factory=list)
    context_blobs: list[tuple[str, Any]] = field(default_factory=list)

    def record_tool(
        self,
        name: str,
        args: dict[str, Any],
        *,
        result: Any = None,
        error: str | None = None,
    ) -> None:
        # Drop framework-injected as_of from recorded args (agents never send it).
        clean = {k: v for k, v in args.items() if k != "as_of"}
        self.tool_calls.append(
            ToolCallRecord(name=name, args=clean, result=result, error=error)
        )

    def add_context(self, name: str, payload: Any) -> None:
        self.context_blobs.append((name, payload))


_active_trace: ContextVar[AgentTrace | None] = ContextVar(
    "quantagent_agent_trace", default=None
)


def get_active_trace() -> AgentTrace | None:
    return _active_trace.get()


@contextmanager
def bind_trace(trace: AgentTrace) -> Iterator[AgentTrace]:
    """Bind ``trace`` for the current asyncio Task (safe under concurrent agents)."""
    token = _active_trace.set(trace)
    try:
        yield trace
    finally:
        _active_trace.reset(token)
