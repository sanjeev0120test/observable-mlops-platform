"""
Unit tests for the resilience primitives (retry + circuit breaker) used by the
self-healing service. These guarantee retries never mask a final failure and the
circuit breaker opens/half-opens/closes as designed.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(_REPO_ROOT / "services" / "self-healing" / "src"))

from resilience import (  # noqa: E402
    CircuitBreaker,
    CircuitBreakerOpenError,
    backoff_delays,
    retry_call,
)


class TestBackoff:
    def test_no_jitter_is_exponential(self):
        delays = backoff_delays(4, base_seconds=0.1, jitter=False)
        assert delays == [0.1, 0.2, 0.4]

    def test_capped_at_max(self):
        delays = backoff_delays(6, base_seconds=1.0, max_seconds=2.0, jitter=False)
        assert max(delays) <= 2.0

    def test_jitter_within_bounds(self):
        delays = backoff_delays(5, base_seconds=0.1, max_seconds=1.0, jitter=True)
        for d in delays:
            assert 0.0 <= d <= 1.0

    def test_single_attempt_has_no_delays(self):
        assert backoff_delays(1) == []


class TestRetryCall:
    def test_returns_on_first_success(self):
        calls = {"n": 0}

        def ok():
            calls["n"] += 1
            return "ok"

        assert retry_call(ok, attempts=3, sleep=lambda _: None) == "ok"
        assert calls["n"] == 1

    def test_retries_then_succeeds(self):
        calls = {"n": 0}

        def flaky():
            calls["n"] += 1
            if calls["n"] < 3:
                raise ValueError("transient")
            return "recovered"

        assert retry_call(flaky, attempts=5, sleep=lambda _: None) == "recovered"
        assert calls["n"] == 3

    def test_reraises_after_exhaustion(self):
        def always_fails():
            raise RuntimeError("down")

        with pytest.raises(RuntimeError, match="down"):
            retry_call(always_fails, attempts=3, sleep=lambda _: None)

    def test_does_not_retry_unlisted_exception(self):
        calls = {"n": 0}

        def raises_key_error():
            calls["n"] += 1
            raise KeyError("nope")

        with pytest.raises(KeyError):
            retry_call(
                raises_key_error,
                attempts=5,
                retry_on=(ValueError,),
                sleep=lambda _: None,
            )
        assert calls["n"] == 1

    def test_invalid_attempts_raises(self):
        with pytest.raises(ValueError):
            retry_call(lambda: None, attempts=0)


class TestCircuitBreaker:
    def test_opens_after_threshold(self):
        cb = CircuitBreaker(failure_threshold=3, reset_timeout=100)

        def boom():
            raise RuntimeError("x")

        for _ in range(3):
            with pytest.raises(RuntimeError):
                cb.call(boom)
        assert cb.state == "open"
        with pytest.raises(CircuitBreakerOpenError):
            cb.call(boom)

    def test_success_resets_failure_count(self):
        cb = CircuitBreaker(failure_threshold=3, reset_timeout=100)

        def boom():
            raise RuntimeError("x")

        for _ in range(2):
            with pytest.raises(RuntimeError):
                cb.call(boom)
        cb.call(lambda: "ok")
        assert cb.state == "closed"

    def test_half_open_after_reset_timeout(self):
        cb = CircuitBreaker(failure_threshold=1, reset_timeout=0.0)

        with pytest.raises(RuntimeError):
            cb.call(lambda: (_ for _ in ()).throw(RuntimeError("x")))
        # reset_timeout=0 means it immediately transitions to half-open
        assert cb.state == "half-open"
        # a success in half-open closes the circuit
        assert cb.call(lambda: "ok") == "ok"
        assert cb.state == "closed"
