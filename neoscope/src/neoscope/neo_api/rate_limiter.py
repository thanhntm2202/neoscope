"""Token-bucket giới hạn tần suất — tuân thủ cứng 5 request/giây của NEO API.

Bằng chứng tuân thủ: mọi lần acquire được đếm; REST client ghi log số request
theo cửa sổ giây để đưa vào báo cáo (tiêu chí 'sử dụng hạ tầng có trách nhiệm').
"""
from __future__ import annotations

import asyncio
import time


class TokenBucket:
    def __init__(self, rate: float = 5.0, capacity: float | None = None):
        self.rate = float(rate)
        self.capacity = float(capacity if capacity is not None else rate)
        self._tokens = self.capacity
        self._last = time.monotonic()
        self._lock = asyncio.Lock()
        self.total_acquired = 0
        self.total_waited_s = 0.0

    async def acquire(self, tokens: float = 1.0) -> None:
        async with self._lock:
            while True:
                now = time.monotonic()
                self._tokens = min(self.capacity, self._tokens + (now - self._last) * self.rate)
                self._last = now
                if self._tokens >= tokens:
                    self._tokens -= tokens
                    self.total_acquired += 1
                    return
                wait = (tokens - self._tokens) / self.rate
                self.total_waited_s += wait
                await asyncio.sleep(wait)

    def acquire_sync(self, tokens: float = 1.0) -> None:
        """Biến thể đồng bộ cho ngữ cảnh không asyncio (REST client dùng httpx sync)."""
        while True:
            now = time.monotonic()
            self._tokens = min(self.capacity, self._tokens + (now - self._last) * self.rate)
            self._last = now
            if self._tokens >= tokens:
                self._tokens -= tokens
                self.total_acquired += 1
                return
            wait = (tokens - self._tokens) / self.rate
            self.total_waited_s += wait
            time.sleep(wait)
