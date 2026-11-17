"""Xác thực JWT với NEO API — POST /auth/token (docs 1.1, truy cập 17/11/2026).

Bảo mật:
- Bí mật chỉ đọc từ biến môi trường (.env), không bao giờ ghi log.
- Token giữ trong bộ nhớ; log chỉ ghi thời hạn, không ghi giá trị token.
- Token hết hạn (mặc định 10800s = 3h) → tự đăng nhập lại trước khi hết hạn
  một biên an toàn. (API có refresh_token; endpoint làm mới chưa công bố
  trong docs đã đọc → dùng re-login, ghi rõ trong limitations.)
"""
from __future__ import annotations

import time
from dataclasses import dataclass

import httpx
from loguru import logger

from ..config import Settings, env_secret

EXPIRY_MARGIN_S = 120.0


@dataclass
class Token:
    access_token: str
    expires_at_monotonic: float

    @property
    def valid(self) -> bool:
        return time.monotonic() < self.expires_at_monotonic


class TokenManager:
    def __init__(self, settings: Settings):
        self.auth_url = settings.neo_api.auth_url
        self._token: Token | None = None

    def get_token(self) -> str:
        if self._token is not None and self._token.valid:
            return self._token.access_token
        return self._login()

    def invalidate(self) -> None:
        self._token = None

    def _login(self) -> str:
        username = env_secret("NEO_USERNAME")
        password = env_secret("NEO_PASSWORD")
        resp = httpx.post(
            self.auth_url,
            json={"username": username, "password": password},
            headers={"Content-Type": "application/json"},
            timeout=20.0,
        )
        resp.raise_for_status()
        body = resp.json()
        if body.get("status") != 1:
            # KHÔNG in body (có thể chứa thông tin nhạy cảm) — chỉ mã lỗi
            raise RuntimeError(f"Đăng nhập NEO API thất bại: code={body.get('code')}")
        data = body["data"]
        expires_in = float(data.get("expires_in", 10800))
        self._token = Token(
            access_token=data["access_token"],
            expires_at_monotonic=time.monotonic() + expires_in - EXPIRY_MARGIN_S,
        )
        logger.info("NEO API: đăng nhập thành công, token hiệu lực ~{:.0f}s (không ghi giá trị token)", expires_in)
        return self._token.access_token
