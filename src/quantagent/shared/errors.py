"""Exception hierarchy for quantagent."""


class QuantAgentError(Exception):
    """Base error for the project."""


class LookaheadError(QuantAgentError):
    """Raised when data visible after ``as_of`` leaks into a query result."""


class ConfigError(QuantAgentError):
    """Invalid or missing configuration."""
