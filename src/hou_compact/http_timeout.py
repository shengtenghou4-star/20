"""Requests session that widens only undersized HTTP timeouts.

PyVO accepts a caller-provided requests session for TAP communication. Gaia UWS status
polls currently pass a fixed 10-second timeout; transient ESA response latency can then
abort a healthy server-side job before the scientific wait deadline is reached. This
module preserves every request method, URL, body, header, retry policy, and response,
changing only scalar or ``(connect, read)`` timeout values below a configured minimum.
"""

from __future__ import annotations

import math
from typing import Any

import requests

DEFAULT_MINIMUM_HTTP_TIMEOUT_SECONDS = 90.0


def validate_minimum_http_timeout(value: float) -> float:
    """Validate and normalize the minimum requests timeout in seconds."""
    result = float(value)
    if not math.isfinite(result) or not 1.0 <= result <= 600.0:
        raise ValueError("minimum_http_timeout_seconds must be finite and within [1, 600]")
    return result


def widen_timeout(timeout: Any, minimum_seconds: float) -> Any:
    """Return a timeout with scalar or tuple members raised to the minimum.

    Advanced urllib3 timeout objects are returned unchanged rather than guessing their
    semantics. ``None`` receives the configured minimum so the dedicated TAP session
    never creates an unbounded request.
    """
    minimum = validate_minimum_http_timeout(minimum_seconds)
    if timeout is None:
        return minimum
    if isinstance(timeout, (int, float)) and not isinstance(timeout, bool):
        numeric = float(timeout)
        if not math.isfinite(numeric) or numeric <= 0:
            raise ValueError("requests timeout must be finite and positive")
        return max(numeric, minimum)
    if isinstance(timeout, tuple) and len(timeout) == 2:
        widened: list[Any] = []
        for member in timeout:
            if member is None:
                widened.append(minimum)
            elif isinstance(member, (int, float)) and not isinstance(member, bool):
                numeric = float(member)
                if not math.isfinite(numeric) or numeric <= 0:
                    raise ValueError("requests timeout tuple members must be positive")
                widened.append(max(numeric, minimum))
            else:
                widened.append(member)
        return tuple(widened)
    return timeout


class MinimumTimeoutSession(requests.Session):
    """Dedicated requests session that raises only undersized timeout values."""

    def __init__(
        self,
        minimum_timeout_seconds: float = DEFAULT_MINIMUM_HTTP_TIMEOUT_SECONDS,
    ) -> None:
        super().__init__()
        self.minimum_timeout_seconds = validate_minimum_http_timeout(
            minimum_timeout_seconds
        )

    def request(self, method: str, url: str, **kwargs: Any) -> requests.Response:
        kwargs["timeout"] = widen_timeout(
            kwargs.get("timeout"),
            self.minimum_timeout_seconds,
        )
        return super().request(method, url, **kwargs)
