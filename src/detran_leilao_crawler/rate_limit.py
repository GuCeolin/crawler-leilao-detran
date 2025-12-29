from __future__ import annotations

import time
from dataclasses import dataclass


@dataclass
class RateLimiter:
    """Simple interval-based rate limiter.

    rate_per_sec: 0.5 means at most one request every 2 seconds.
    """

    rate_per_sec: float
    _next_allowed_at: float = 0.0

    def wait(self) -> None:
        if self.rate_per_sec <= 0:
            return
        interval = 1.0 / self.rate_per_sec
        now = time.monotonic()
        if self._next_allowed_at == 0.0:
            self._next_allowed_at = now
        sleep_for = max(0.0, self._next_allowed_at - now)
        if sleep_for > 0:
            time.sleep(sleep_for)
        self._next_allowed_at = max(self._next_allowed_at, now) + interval
