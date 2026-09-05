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
