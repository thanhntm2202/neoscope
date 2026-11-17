"""REST client NEO API — CHỈ DỮ LIỆU THỊ TRƯỜNG.

An toàn theo thiết kế (safety by construction): module này KHÔNG có hàm
đặt/sửa/hủy lệnh. Kiểm chứng bằng:
    grep -ri "placeOrder\|amendOrder\|cancelOrder\|/order" src/neoscope/neo_api/
(kết quả mong đợi: không khớp).

Tuân thủ: token-bucket 5 RPS; retry/backoff với 429/5xx; header đúng docs
(Authorization Bearer, x-device, x-devicetype).
"""
from __future__ import annotations

import os
import uuid
from typing import Any

import httpx
from loguru import logger

from ..config import Settings, env_secret
from .auth import TokenManager
from .rate_limiter import TokenBucket


class NeoRestClient:
    def __init__(self, settings: Settings):
        self.cfg = settings.neo_api
        self.tokens = TokenManager(settings)
        self.bucket = TokenBucket(rate=float(self.cfg.rate_limit_rps))
        self.device_id = env_secret("NEO_DEVICE_ID", required=False) or self._stable_device_id()
        self._client = httpx.Client(base_url=str(self.cfg.base_url), timeout=float(self.cfg.rest_timeout_s))

    @staticmethod
    def _stable_device_id() -> str:
        """UUID ổn định suy từ tên máy (không phải thông tin nhạy cảm)."""
        return str(uuid.uuid5(uuid.NAMESPACE_DNS, os.uname().nodename))

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.tokens.get_token()}",
            "x-device": self.device_id,
            "x-devicetype": str(self.cfg.device_type),
        }

    def _get(self, path: str, params: dict[str, Any] | None = None, retries: int = 3) -> dict[str, Any]:
        backoff = 1.0
        for attempt in range(retries + 1):
            self.bucket.acquire_sync()
            try:
                resp = self._client.get(path, params=params, headers=self._headers())
            except httpx.TransportError as e:
                logger.warning("NEO REST lỗi mạng ({}), thử lại {}/{}", type(e).__name__, attempt + 1, retries)
                if attempt == retries:
                    raise
                import time as _t
                _t.sleep(backoff)
                backoff *= 2
                continue
            if resp.status_code in (429, 500, 502, 503, 504):
                logger.warning("NEO REST HTTP {} — backoff {:.1f}s", resp.status_code, backoff)
                if attempt == retries:
                    resp.raise_for_status()
                import time as _t
                _t.sleep(backoff)
                backoff *= 2
                continue
            if resp.status_code == 401:
                logger.info("NEO REST 401 — làm mới token rồi thử lại")
                self.tokens.invalidate()
                continue
            resp.raise_for_status()
            body = resp.json()
            if body.get("status") != 1:
                raise RuntimeError(f"NEO API trả lỗi: code={body.get('code')} message={body.get('message')}")
            return body
        raise RuntimeError("NEO REST: hết số lần thử")

    # ---------------- các endpoint DỮ LIỆU (không giao dịch) ----------------
    def stock_detail(self, symbols: list[str] | None = None, market_code: str = "HOSE",
                     page_no: int = 1, page_size: int = 1000) -> dict[str, Any]:
        """GET /stock/stockDetail — snapshot sổ lệnh 3 mức + trường thị trường (docs 4.6)."""
        params: dict[str, Any] = {"marketCode": market_code, "pageNo": page_no, "pageSize": page_size}
        if symbols:
            params["symbols"] = ",".join(symbols)
        return self._get("stock/stockDetail", params)

    def compliance_report(self) -> dict[str, float]:
        return {"requests_total": self.bucket.total_acquired,
                "rate_limit_rps": self.bucket.rate,
                "seconds_waited_for_limit": round(self.bucket.total_waited_s, 3)}

    def close(self) -> None:
        self._client.close()
