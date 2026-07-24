from __future__ import annotations

import unittest

from hou_compact.gaia import _wait_for_job_with_parse_retries


class _FakeClock:
    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


class _FakeJob:
    def __init__(self, outcomes: list[BaseException | None]) -> None:
        self.outcomes = list(outcomes)
        self.timeouts: list[float] = []

    def wait(self, *, timeout: float) -> _FakeJob:
        self.timeouts.append(timeout)
        outcome = self.outcomes.pop(0)
        if outcome is not None:
            raise outcome
        return self


class GaiaStatusParseRetryTests(unittest.TestCase):
    def test_malformed_xml_retries_same_job_with_one_deadline(self) -> None:
        clock = _FakeClock()
        job = _FakeJob(
            [
                ValueError("55:2: mismatched tag"),
                SyntaxError("truncated XML"),
                None,
            ]
        )
        details: dict[str, object] = {}

        receipt = _wait_for_job_with_parse_retries(
            job,
            timeout_seconds=30,
            parse_retries=3,
            retry_backoff_seconds=1,
            monotonic=clock.monotonic,
            sleep=clock.sleep,
            details=details,
        )

        self.assertEqual(receipt["status_parse_failures"], 2)
        self.assertEqual(details["status_parse_failures"], 2)
        self.assertEqual(details["last_status_parse_error_type"], "SyntaxError")
        self.assertEqual(clock.sleeps, [1.0, 2.0])
        self.assertEqual(len(job.timeouts), 3)
        self.assertGreater(job.timeouts[0], job.timeouts[1])
        self.assertGreater(job.timeouts[1], job.timeouts[2])

    def test_retry_budget_exhaustion_preserves_last_parse_error(self) -> None:
        clock = _FakeClock()
        job = _FakeJob(
            [
                ValueError("first malformed response"),
                ValueError("second malformed response"),
            ]
        )
        details: dict[str, object] = {}

        with self.assertRaisesRegex(ValueError, "second malformed response"):
            _wait_for_job_with_parse_retries(
                job,
                timeout_seconds=30,
                parse_retries=1,
                retry_backoff_seconds=1,
                monotonic=clock.monotonic,
                sleep=clock.sleep,
                details=details,
            )

        self.assertEqual(details["status_parse_failures"], 2)
        self.assertEqual(len(job.timeouts), 2)

    def test_non_parser_failure_is_not_retried(self) -> None:
        clock = _FakeClock()
        job = _FakeJob([RuntimeError("real job failure")])

        with self.assertRaisesRegex(RuntimeError, "real job failure"):
            _wait_for_job_with_parse_retries(
                job,
                timeout_seconds=30,
                parse_retries=8,
                retry_backoff_seconds=1,
                monotonic=clock.monotonic,
                sleep=clock.sleep,
            )

        self.assertEqual(len(job.timeouts), 1)
        self.assertEqual(clock.sleeps, [])

    def test_backoff_cannot_extend_total_wait_deadline(self) -> None:
        clock = _FakeClock()
        job = _FakeJob([ValueError("malformed response")])

        with self.assertRaises(TimeoutError):
            _wait_for_job_with_parse_retries(
                job,
                timeout_seconds=1,
                parse_retries=8,
                retry_backoff_seconds=2,
                monotonic=clock.monotonic,
                sleep=clock.sleep,
            )

        self.assertEqual(clock.sleeps, [1.0])
        self.assertEqual(len(job.timeouts), 1)


if __name__ == "__main__":
    unittest.main()
