"""Engine exception hierarchy.

Engines raise these to signal error conditions. The dispatch code in
commands.py catches them and decides what (if anything) to show the user.
"""

__all__ = ["EngineError", "RateLimitError", "SearchError"]


class EngineError(Exception):
    """Base engine error — always logged, never shown to user by default."""


class RateLimitError(EngineError):
    """API rate limit reached.

    Args:
        message: Internal log message (e.g. "SauceNAO daily limit hit").
        period: Human-readable period for the user (e.g. "Daily", "Monthly").
        retry_after: Optional seconds until the limit resets.
    """

    def __init__(self, message: str = "Rate limit reached", *, period: str = "", retry_after: float | None = None):
        super().__init__(message)
        self.period = period
        self.retry_after = retry_after


class SearchError(EngineError):
    """Search failed (network, parsing, bad response, etc.)."""
