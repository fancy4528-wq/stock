"""Exception hierarchy for quantagent."""


class QuantAgentError(Exception):
    """Base error for the project."""


class DataError(QuantAgentError):
    """Data pipeline errors (collect / normalize / validate / load)."""


class DataQualityError(DataError):
    """FATAL or ERROR validation failure."""


class LookaheadError(DataError):
    """Raised when data visible after ``as_of`` leaks into a query result."""


class SourceUnavailableError(DataError):
    """External data source failed after retries."""


class ConfigError(QuantAgentError):
    """Invalid or missing configuration."""


class AgentError(QuantAgentError):
    """Agent layer errors."""


class SchemaValidationError(AgentError):
    """Agent output failed Pydantic / schema validation."""


class BudgetExceeded(AgentError):
    """LLM token / cost budget exhausted (abort or hard refuse)."""

    def __init__(
        self,
        allocation: str = "",
        spent: float = 0.0,
        limit: float = 0.0,
        estimated_cost: float = 0.0,
        *,
        detail: str | None = None,
    ) -> None:
        self.allocation = allocation
        self.spent = spent
        self.limit = limit
        self.estimated_cost = estimated_cost
        msg = detail or (
            f"budget exceeded for {allocation}: spent={spent:.4f} "
            f"limit={limit:.4f} est={estimated_cost:.4f}"
        )
        super().__init__(msg)


class BudgetDegrade(AgentError):
    """Allocation over limit; caller should degrade (cheaper tier / less work)."""

    def __init__(
        self,
        allocation: str,
        *,
        suggested_tier: str = "small",
        detail: str | None = None,
    ) -> None:
        self.allocation = allocation
        self.suggested_tier = suggested_tier
        super().__init__(detail or f"budget degrade for {allocation} → tier={suggested_tier}")


class BudgetSkip(AgentError):
    """Allocation over limit; skip this work for today (e.g. news_extraction)."""

    def __init__(self, allocation: str, action: str = "skip", *, detail: str | None = None) -> None:
        self.allocation = allocation
        self.action = action
        super().__init__(detail or f"budget skip for {allocation} action={action}")


class EvidenceMissingError(AgentError):
    """Judgement emitted without required Evidence refs."""


class JournalMutationError(QuantAgentError):
    """Append-only journal rejected an UPDATE/DELETE."""
