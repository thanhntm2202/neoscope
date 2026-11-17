"""Lưu trữ hai tầng: RAW bất biến (JSONL.gz) + CURATED (Parquet).

- RAW là nguồn sự thật: mọi thông điệp gốc kèm seq + arrival_ts, không sửa.
  Người chấm có thể replay toàn bộ pipeline từ RAW (tính tái lập).
- CURATED là dữ liệu đã chuẩn hóa, mang cờ chất lượng, sẵn sàng cho tài chính.
- Manifest ghi sha256 từng tệp RAW + config_hash để truy vết.
"""
from __future__ import annotations

import gzip
import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator

import pandas as pd

from ..constants import VN_TZ


def now_vn() -> datetime:
    return datetime.now(VN_TZ)


def mode_prefix(mode: str) -> str:
    """Tiền tố thư mục phiên: SYNTHETIC → SYNTH_ (ngắn gọn), LIVE → LIVE_."""
    m = mode.upper()
    return "SYNTH" if m == "SYNTHETIC" else m


def session_dir_name(mode: str, date_str: str) -> str:
    return f"{mode_prefix(mode)}_{date_str}"


class RawWriter:
    """Ghi thông điệp thô theo channel vào JSONL.gz, đánh số sequence."""

    def __init__(self, session_dir: Path, mode: str, meta: dict[str, Any] | None = None):
        self.session_dir = Path(session_dir)
        self.session_dir.mkdir(parents=True, exist_ok=True)
        self.mode = mode.upper()
        self._files: dict[str, Any] = {}
        self._seq = 0
        self._counts: dict[str, int] = {}
        self._meta = meta or {}
        self._closed = False

    def _open(self, channel: str):
        if channel not in self._files:
            path = self.session_dir / f"{channel}.jsonl.gz"
            is_new = not path.exists()
            f = gzip.open(path, "at", encoding="utf-8")
            if is_new:
                header = {
                    "_meta": True,
                    "mode": self.mode,
                    "synthetic": self.mode == "SYNTHETIC",
                    "created_at": now_vn().isoformat(),
                    **self._meta,
                }
                f.write(json.dumps(header, ensure_ascii=False) + "\n")
            self._files[channel] = f
            self._counts.setdefault(channel, 0)
        return self._files[channel]

    def write(self, channel: str, payload: dict[str, Any], arrival_ts: datetime | None = None) -> int:
        self._seq += 1
        rec = {
            "seq": self._seq,
            "arrival_ts": (arrival_ts or now_vn()).isoformat(),
            "channel": channel,
            "data": payload,
        }
        f = self._open(channel)
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        self._counts[channel] += 1
        return self._seq

    def close(self) -> Path:
        if self._closed:
            return self.session_dir / "manifest.json"
        for f in self._files.values():
            f.close()
        self._closed = True
        manifest = {
            "mode": self.mode,
            "synthetic": self.mode == "SYNTHETIC",
            "counts": self._counts,
            "total_messages": self._seq,
            "closed_at": now_vn().isoformat(),
            "sha256": {
                p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                for p in sorted(self.session_dir.glob("*.jsonl.gz"))
            },
            **self._meta,
        }
        mp = self.session_dir / "manifest.json"
        mp.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        return mp


def read_raw(session_dir: Path, channel: str) -> Iterator[dict[str, Any]]:
    """Đọc tuần tự thông điệp thô (bỏ dòng meta)."""
    path = Path(session_dir) / f"{channel}.jsonl.gz"
    if not path.exists():
        return
    with gzip.open(path, "rt", encoding="utf-8") as f:
        for line in f:
            rec = json.loads(line)
            if rec.get("_meta"):
                continue
            yield rec


def read_manifest(session_dir: Path) -> dict[str, Any]:
    mp = Path(session_dir) / "manifest.json"
    return json.loads(mp.read_text(encoding="utf-8")) if mp.exists() else {}


def list_session_dirs(data_dir: Path, mode: str | None = None) -> list[Path]:
    raw = Path(data_dir) / "raw"
    if not raw.exists():
        return []
    dirs = [p for p in raw.iterdir() if p.is_dir() and (p / "manifest.json").exists()]
    if mode:
        dirs = [p for p in dirs if p.name.startswith(mode_prefix(mode) + "_")]
    return sorted(dirs, key=lambda p: p.name.split("_", 1)[1])


def session_date_of(session_dir: Path) -> str:
    return session_dir.name.split("_", 1)[1]


def write_parquet(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path, index=False)


def read_parquet(path: Path) -> pd.DataFrame:
    return pd.read_parquet(path)
