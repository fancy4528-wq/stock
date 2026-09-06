"""Idempotency helpers for order placement."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from quantagent.execution.broker.base import OrderAck, OrderRequest
from quantagent.shared.errors import QuantAgentError


class DuplicateOrderInFlight(QuantAgentError):
    """Another place_order is already in flight for this client_order_id."""


def make_client_order_id(run_id: str, symbol: str, side: str, seq: int) -> str:
    """Deterministic id so crashed reruns hit the idempotency guard."""
    clean = symbol.replace(".", "")
    return f"{run_id}-{clean}-{side[0].upper()}-{seq:03d}"


class InMemoryIdempotencyGuard:
    """Process-local idempotency (SimulatedBroker / unit tests)."""

    def __init__(self) -> None:
        self._acks: dict[str, OrderAck] = {}
        self._inflight: set[str] = set()

    def get(self, client_order_id: str) -> OrderAck | None:
        return self._acks.get(client_order_id)

    def remember(self, ack: OrderAck) -> None:
        self._acks[ack.client_order_id] = ack

    async def place_once(
        self,
        req: OrderRequest,
        place_fn: Callable[[OrderRequest], Awaitable[OrderAck]],
    ) -> OrderAck:
        existing = self._acks.get(req.client_order_id)
        if existing is not None:
            return existing.model_copy(update={"is_duplicate": True})

        if req.client_order_id in self._inflight:
            raise DuplicateOrderInFlight(req.client_order_id)

        self._inflight.add(req.client_order_id)
        try:
            ack = await place_fn(req)
            self._acks[req.client_order_id] = ack
            return ack
        finally:
            self._inflight.discard(req.client_order_id)
