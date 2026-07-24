"""Requests session with bounded timeouts and safe read-only retries.

PyVO accepts a caller-provided requests session for TAP communication. Gaia UWS status
polls currently pass a fixed 10-second timeout; transient ESA response latency can then
abort a healthy server-side job before the scientific wait deadline is reached. This
module widens undersized timeouts and retries only idempotent read-only HTTP methods.
Job-submission POST requests are deliberately excluded so a transport failure can never
silently create duplicate remote jobs.
"""

from __future__ import annotations

import math
from typing import Any

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

DEFAULT_MINIMUM_HTTP_TIMEOUT_SECONDS = 90.0
DEFAULT_TRANSIENT_HTTP_RETRIES = 8
DEFAULT_RETRY_BACKOFF_SECONDS = 1.0
_RETRYABLE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
_RETRYABLE_STATUS_CODES = (429, 500, 502, 503, 504)


def validate_minimum_http_timeout(value: float) -> float:
    """Validate and normalize the minimum requests timeout in seconds."""
    result = float(value)
    if not math.isfinite(result) or not 1.0 <= result <= 600.0:
        raise ValueError("minimum_http_timeout_seconds must be finite and within [1, 600]")
    return result


def validate_transient_http_retries(value: int) -> int:
    """Validate the bounded retry count for idempotent TAP requests."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError("transient_http_retries must be an integer")
    if not 0 <= value <= 20:
        raise ValueError("transient_http_retries must lie within [0, 20]")
    return value


def validate_retry_backoff_seconds(value: float) -> float:
    """Validate the urllib3 exponential-backoff factor."""
    result = float(value)
    if not math.isfinite(result) or not 0.0 <= result <= 60.0:
        raise ValueError("retry_backoff_seconds must be finite and within [0, 60]")
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
    """Dedicated TAP session with widened timeouts and read-only retries."""

    def __init__(
        self,
        minimum_timeout_seconds: float = DEFAULT_MINIMUM_HTTP_TIMEOUT_SECONDS,
        *,
        transient_http_retries: int = DEFAULT_TRANSIENT_HTTP_RETRIES,
        retry_backoff_seconds: float = DEFAULT_RETRY_BACKOFF_SECONDS,
    ) -> None:
        super().__init__()
        self.minimum_timeout_seconds = validate_minimum_http_timeout(
            minimum_timeout_seconds
        )
        self.transient_http_retries = validate_transient_http_retries(
            transient_http_retries
        )
        self.retry_backoff_seconds = validate_retry_backoff_seconds(
            retry_backoff_seconds
        )
        retry_policy = Retry(
            total=self.transient_http_retries,
            connect=self.transient_http_retries,
            read=self.transient_http_retries,
            status=self.transient_http_retries,
            allowed_methods=_RETRYABLE_METHODS,
            status_forcelist=_RETRYABLE_STATUS_CODES,
            backoff_factor=self.retry_backoff_seconds,
            respect_retry_after_header=True,
            raise_on_status=True,
        )
        adapter = HTTPAdapter(max_retries=retry_policy)
        self.mount("https://", adapter)

    def request(self, method: str, url: str, **kwargs: Any) -> requests.Response:
        kwargs["timeout"] = widen_timeout(
            kwargs.get("timeout"),
            self.minimum_timeout_seconds,
        )
        return super().request(method, url, **kwargs)
