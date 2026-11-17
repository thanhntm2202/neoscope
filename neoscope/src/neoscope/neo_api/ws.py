"""WebSocket client NEO API — luồng thị trường thời gian thực, ghi RAW bất biến.

Giao thức đúng docs (overview + 6.2 market-stream):
1. Kết nối ws://neoapi.vpbanks.com.vn/stock-stream/broker
2. Gửi {"action": "auth", "data": "<jwt>"}; chờ {"type":"auth","status":"success"}
3. Gửi {"type":"sub","channel":..., "listId":[...]} cho từng channel
4. Mỗi thông điệp → RawWriter (seq + arrival_ts UTC+7)

Độ bền: watchdog (không thấy thông điệp trong phiên quá ngưỡng → tái kết nối),
backoff hàm mũ, tự resubscribe, làm mới JWT khi auth lỗi. Ghi heartbeat
ra data/live_status.json để dashboard hiển thị trạng thái kết nối.
"""
from __future__ import annotations

import asyncio
import json
import signal
from datetime import datetime
from pathlib import Path
from typing import Any

import websockets
from loguru import logger

from ..config import Settings
from ..constants import VN_TZ, session_of_time
from ..data.store import RawWriter
from .auth import TokenManager

CONTINUOUS = {"LO_AM", "LO_PM", "ATO", "ATC"}


class NeoMarketWS:
    def __init__(self, settings: Settings, session_dir: Path):
        self.cfg = settings
        self.tokens = TokenManager(settings)
        self.writer = RawWriter(session_dir, "LIVE", meta={
            "session_date": datetime.now(VN_TZ).strftime("%Y-%m-%d"),
            "config_hash": settings.config_hash,
        })
        self.status_path = settings.data_path("live_status.json")
        self._stop = asyncio.Event()
        self._last_msg_mono: float = 0.0
        self._msg_count = 0

    def _subscriptions(self) -> list[dict[str, Any]]:
        wl = self.cfg.watchlist()
        idx = list(self.cfg.indices)
        return [
            {"type": "sub", "channel": "stockInfo", "listId": wl},
            {"type": "sub", "channel": "marketInfo", "listId": idx},
            {"type": "sub", "channel": "marketVolume", "listId": idx},
            {"type": "sub", "channel": "marketSession", "listId": ["HOSE", "HNX", "UPCOM"]},
        ]

    def _write_status(self, state: str, detail: str = "") -> None:
        self.status_path.parent.mkdir(parents=True, exist_ok=True)
        self.status_path.write_text(json.dumps({
            "state": state, "detail": detail,
            "updated_at": datetime.now(VN_TZ).isoformat(),
            "messages": self._msg_count,
            "mode": "LIVE",
        }, ensure_ascii=False), encoding="utf-8")

    async def _run_once(self) -> None:
        url = str(self.cfg.neo_api.ws_url)
        token = self.tokens.get_token()
        async with websockets.connect(url, ping_interval=20, ping_timeout=20, max_size=2**22) as ws:
            await ws.send(json.dumps({"action": "auth", "data": token}))
            auth_raw = await asyncio.wait_for(ws.recv(), timeout=15)
            auth = json.loads(auth_raw)
            if auth.get("type") != "auth" or auth.get("status") != "success":
                self.tokens.invalidate()
                raise ConnectionError("NEO WS auth thất bại (token hết hạn hoặc sai quyền/IP)")
            logger.info("NEO WS: xác thực thành công")
            for sub in self._subscriptions():
                await ws.send(json.dumps(sub))
            self._write_status("connected")
            loop = asyncio.get_running_loop()
            self._last_msg_mono = loop.time()
            watchdog_s = float(self.cfg.neo_api.ws_watchdog_s)

            while not self._stop.is_set():
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=5.0)
                except asyncio.TimeoutError:
                    in_session = session_of_time(datetime.now(VN_TZ).time()) in CONTINUOUS
                    if in_session and loop.time() - self._last_msg_mono > watchdog_s:
                        raise ConnectionError(f"Watchdog: không có thông điệp >{watchdog_s:.0f}s trong phiên")
                    continue
                self._last_msg_mono = loop.time()
                msg = json.loads(raw)
                channel = self._channel_of(msg)
                if channel:
                    self.writer.write(channel, msg)
                    self._msg_count += 1
                    if self._msg_count % 200 == 0:
                        self._write_status("connected")

    @staticmethod
    def _channel_of(msg: dict[str, Any]) -> str | None:
        """Suy channel từ hình dạng payload (docs không nêu trường channel tường minh)."""
        if "symbol" in msg:
            return "stockInfo"
        if "indexCode" in msg and "advances" in msg:
            return "marketInfo"
        if "indexCode" in msg and "volume" in msg:
            return "marketVolume"
        if "marketStatus" in msg and "marketCode" in msg and "indexCode" not in msg:
            return "marketSession"
        if msg.get("type") in {"auth", "sub", "unsub", "ping", "pong"}:
            return None
        return "unknown"

    async def run(self) -> None:
        backoff = 1.0
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, self._stop.set)
            except NotImplementedError:
                pass
        self._write_status("starting")
        while not self._stop.is_set():
            try:
                await self._run_once()
                backoff = 1.0
            except asyncio.CancelledError:
                break
            except Exception as e:  # noqa: BLE001 — chủ đích: mọi lỗi kết nối đều retry
                if self._stop.is_set():
                    break
                logger.warning("NEO WS đứt ({}: {}) — tái kết nối sau {:.0f}s", type(e).__name__, e, backoff)
                self._write_status("reconnecting", f"{type(e).__name__}")
                try:
                    await asyncio.wait_for(self._stop.wait(), timeout=backoff)
                except asyncio.TimeoutError:
                    pass
                backoff = min(backoff * 2, 60.0)
        self.writer.close()
        self._write_status("stopped")
        logger.info("NEO WS: dừng ghi, {} thông điệp", self._msg_count)
