"""Engine exception hierarchy.

Engines raise these to signal error conditions. The dispatch code in
commands.py catches them and decides what (if anything) to show the user.
"""

import httpx

__all__ = ["EngineError", "RateLimitError", "SearchError", "is_transient"]

#: Exception types that indicate a transient network problem — not a bug.
#: Deliberately no bare OSError — that would swallow real bugs (ffmpeg, file I/O).
_TRANSIENT_TYPES = (httpx.TimeoutException, httpx.TransportError, ConnectionError, TimeoutError)


def is_transient(exc: BaseException | None) -> bool:
    """Walk the exception chain looking for transient network errors (timeouts, DNS, connect failures)."""
    seen: set[int] = set()
    while exc is not None and id(exc) not in seen:
        seen.add(id(exc))
        if isinstance(exc, _TRANSIENT_TYPES):
            return True
        exc = exc.__cause__ or exc.__context__
    return False


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
    """Search failed (network, parsing, bad response, etc.).

    Args:
        message: Internal log message.
        report: When False, the error is logged locally but not sent to
            error tracking (use for known-broken upstreams we can't fix).
    """

    def __init__(self, message: str = "Search failed", *, report: bool = True):
        super().__init__(message)
        self.report = report
