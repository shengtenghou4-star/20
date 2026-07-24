from __future__ import annotations

import unittest
from unittest import mock

from hou_compact.http_timeout import (
    MinimumTimeoutSession,
    validate_minimum_http_timeout,
    validate_retry_backoff_seconds,
    validate_transient_http_retries,
    widen_timeout,
)


class MinimumTimeoutTests(unittest.TestCase):
    def test_scalar_and_none_timeouts_are_widened(self) -> None:
        self.assertEqual(widen_timeout(None, 90), 90.0)
        self.assertEqual(widen_timeout(10, 90), 90.0)
        self.assertEqual(widen_timeout(120, 90), 120.0)

    def test_connect_read_tuple_is_widened_memberwise(self) -> None:
        self.assertEqual(widen_timeout((10, 20), 90), (90.0, 90.0))
        self.assertEqual(widen_timeout((None, 120), 90), (90.0, 120.0))

    def test_advanced_timeout_object_is_preserved(self) -> None:
        marker = object()
        self.assertIs(widen_timeout(marker, 90), marker)

    def test_invalid_minimum_and_numeric_timeout_fail_closed(self) -> None:
        for value in (0, -1, float("nan"), float("inf"), 601):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    validate_minimum_http_timeout(value)
        for timeout in (0, -1, float("nan"), float("inf")):
            with self.subTest(timeout=timeout):
                with self.assertRaises(ValueError):
                    widen_timeout(timeout, 90)

    def test_invalid_retry_settings_fail_closed(self) -> None:
        for value in (-1, 21):
            with self.subTest(retries=value):
                with self.assertRaises(ValueError):
                    validate_transient_http_retries(value)
        for value in (True, 1.5, "3"):
            with self.subTest(retries=value):
                with self.assertRaises(TypeError):
                    validate_transient_http_retries(value)  # type: ignore[arg-type]
        for value in (-1, float("nan"), float("inf"), 61):
            with self.subTest(backoff=value):
                with self.assertRaises(ValueError):
                    validate_retry_backoff_seconds(value)

    def test_session_retries_only_idempotent_read_methods(self) -> None:
        session = MinimumTimeoutSession(
            90,
            transient_http_retries=6,
            retry_backoff_seconds=0.5,
        )
        retries = session.get_adapter("https://example.invalid/status").max_retries
        self.assertEqual(retries.total, 6)
        self.assertEqual(retries.connect, 6)
        self.assertEqual(retries.read, 6)
        self.assertEqual(retries.status, 6)
        self.assertIn("GET", retries.allowed_methods)
        self.assertIn("HEAD", retries.allowed_methods)
        self.assertNotIn("POST", retries.allowed_methods)
        self.assertNotIn("DELETE", retries.allowed_methods)
        self.assertIn(503, retries.status_forcelist)
        self.assertEqual(retries.backoff_factor, 0.5)

    def test_session_passes_widened_timeout_without_changing_request(self) -> None:
        session = MinimumTimeoutSession(90)
        sentinel = mock.Mock()
        with mock.patch(
            "requests.sessions.Session.request",
            autospec=True,
            return_value=sentinel,
        ) as request:
            result = session.request(
                "GET",
                "https://example.invalid/status",
                timeout=10,
                headers={"Accept": "text/xml"},
            )
        self.assertIs(result, sentinel)
        request.assert_called_once_with(
            session,
            "GET",
            "https://example.invalid/status",
            timeout=90.0,
            headers={"Accept": "text/xml"},
        )


if __name__ == "__main__":
    unittest.main()
