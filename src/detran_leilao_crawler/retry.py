from __future__ import annotations

import random
import time
from dataclasses import dataclass
from typing import Callable, TypeVar


T = TypeVar("T")


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int = 4
    base_delay_sec: float = 0.75
    max_delay_sec: float = 8.0
    jitter: float = 0.25


def retry_call(fn: Callable[[], T], policy: RetryPolicy, should_retry: Callable[[Exception], bool]) -> T:
    last_exc: Exception | None = None
    for attempt in range(1, policy.max_attempts + 1):
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            if attempt >= policy.max_attempts or not should_retry(exc):
                raise
            delay = min(policy.max_delay_sec, policy.base_delay_sec * (2 ** (attempt - 1)))
            delay = delay * (1.0 + random.uniform(-policy.jitter, policy.jitter))
            time.sleep(max(0.0, delay))
    assert last_exc is not None
    raise last_exc
