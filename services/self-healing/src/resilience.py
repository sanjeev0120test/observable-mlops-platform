"""
Resilience primitives for external calls: retry-with-backoff and a circuit breaker.

Design intent (SRE):
- Retries handle *transient* faults (timeouts, connection resets, 5xx) with
  exponential backoff + full jitter to avoid thundering-herd retry storms.
- The circuit breaker prevents hammering a dependency that is already down:
  after N consecutive failures it "opens" and fast-fails for a cooldown window,
  then allows a single trial request ("half-open") to test recovery.

Security invariant: these helpers NEVER swallow the final failure. The caller
decides the fail-closed/fail-open behaviour. Here we only add resilience, never
change the outcome of an exhausted call — it always re-raises.

Vendored per-service (copied into each service image) so containers stay
self-contained. Keep in sync with the platform-wide copy documented in README.
"""

from __future__ import annotations

import logging
import random
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")


def backoff_delays(
    attempts: int,
    base_seconds: float = 0.1,
    max_seconds: float = 5.0,
    jitter: bool = True,
) -> list[float]:
    """
    Compute exponential backoff delays with optional full jitter.

    Returns a list of `attempts - 1` sleep durations (no sleep after last try).
    Deterministic when jitter=False (useful for tests).
    """
    delays: list[float] = []
    for i in range(max(0, attempts - 1)):
        raw = min(max_seconds, base_seconds * (2**i))
        delays.append(random.uniform(0, raw) if jitter else raw)
    return delays


def retry_call(
    func: Callable[[], T],
    *,
    attempts: int = 3,
    base_seconds: float = 0.1,
    max_seconds: float = 5.0,
    retry_on: Iterable[type[BaseException]] = (Exception,),
    jitter: bool = True,
    sleep: Callable[[float], None] = time.sleep,
    on_retry: Callable[[int, BaseException], None] | None = None,
) -> T:
    """
    Call `func` up to `attempts` times, retrying only on `retry_on` exceptions.

    Re-raises the last exception once attempts are exhausted (never swallows it).
    """
    if attempts < 1:
        raise ValueError("attempts must be >= 1")

    retry_on = tuple(retry_on)
    delays = backoff_delays(attempts, base_seconds, max_seconds, jitter)
    last_exc: BaseException | None = None

    for attempt in range(1, attempts + 1):
        try:
            return func()
        except retry_on as exc:
            last_exc = exc
            if attempt >= attempts:
                break
            if on_retry is not None:
                on_retry(attempt, exc)
            delay = delays[attempt - 1] if attempt - 1 < len(delays) else max_seconds
            logger.warning(
                "retry_call: attempt %d/%d failed (%s) — retrying in %.3fs",
                attempt,
                attempts,
                exc.__class__.__name__,
                delay,
            )
            sleep(delay)

    assert last_exc is not None  # loop always sets it before breaking
    raise last_exc


class CircuitBreakerOpenError(Exception):
    """Raised when the circuit is open and the call is fast-failed."""


@dataclass
class CircuitBreaker:
    """
    Minimal circuit breaker.

    States:
      - closed:     calls flow through; failures are counted.
      - open:       calls fast-fail with CircuitBreakerOpen until `reset_timeout`.
      - half-open:  one trial call allowed; success closes, failure re-opens.
    """

    failure_threshold: int = 5
    reset_timeout: float = 30.0
    _failures: int = field(default=0, init=False)
    _opened_at: float | None = field(default=None, init=False)
    _now: Callable[[], float] = field(default=time.monotonic, init=False)

    @property
    def state(self) -> str:
        if self._opened_at is None:
            return "closed"
        if self._now() - self._opened_at >= self.reset_timeout:
            return "half-open"
        return "open"

    def record_success(self) -> None:
        self._failures = 0
        self._opened_at = None

    def record_failure(self) -> None:
        self._failures += 1
        if self._failures >= self.failure_threshold:
            self._opened_at = self._now()

    def call(self, func: Callable[[], T]) -> T:
        state = self.state
        if state == "open":
            raise CircuitBreakerOpenError(
                f"circuit open — fast-failing (failures={self._failures})"
            )
        try:
            result = func()
        except Exception:
            self.record_failure()
            raise
        # success (covers closed and half-open trial)
        self.record_success()
        return result
