"""Pipeline: RAW → chuẩn hóa → CURATED (snapshots, bars, indices, quality).

Tính tái lập: pipeline thuần túy trên RAW + config; không trộn thời gian
thực vào dữ liệu output → chạy hai lần cho kết quả GIỐNG HỆT (có test
băm Parquet kiểm chứng — tests/test_replay.py).
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
from loguru import logger

from ..config import Settings
from ..constants import bucket_of_time
from ..data.normalize import StockNormalizer, normalize_index_record
from ..data.store import (list_session_dirs, read_parquet, read_raw,
                          session_date_of, write_parquet)
from ..finance.liquidity import amihud_bps_per_bn
from ..finance.microstructure import BPS, add_microstructure_cols


def curated_dir_for(settings: Settings, session_dir: Path) -> Path:
    return settings.data_path("curated", session_dir.name)


def process_session(settings: Settings, session_dir: Path, force: bool = False) -> Path:
    """Chuẩn hóa một phiên RAW → snapshots/bars/indices/quality Parquet."""
    out_dir = curated_dir_for(settings, session_dir)
    snap_path = out_dir / "snapshots.parquet"
    if snap_path.exists() and not force:
        return out_dir

    date_str = session_date_of(session_dir)
    norm = StockNormalizer(
        stale_gap_s=float(settings.quality.stale_gap_s),
        dedup_window=int(settings.quality.dedup_window),
    )
    rows = []
    n_raw = 0
    for rec in read_raw(session_dir, "stockInfo"):
        n_raw += 1
        row = norm.normalize(rec)
        if row is not None:
            rows.append(row)
    if not rows:
        raise RuntimeError(f"Không có bản ghi stockInfo hợp lệ trong {session_dir}")
    snaps = pd.DataFrame(rows)
    snaps["session_date"] = date_str
    snaps["group"] = snaps["symbol"].map(settings.group_of)
    snaps = snaps.sort_values(["ts", "seq"]).reset_index(drop=True)
    snaps["d_f_net_val"] = snaps["d_f_buy_val"] - snaps["d_f_sell_val"]
    snaps = add_microstructure_cols(snaps)
    snaps["bucket"] = snaps["ts"].dt.time.map(lambda t: bucket_of_time(t, int(settings.alerts.bucket_min)))

    # --- chỉ số thị trường ---
    idx_rows = [normalize_index_record(r) for r in read_raw(session_dir, "marketInfo")]
    indices = pd.DataFrame([r for r in idx_rows if r]) if idx_rows else pd.DataFrame()
    if not indices.empty:
        indices = indices.sort_values(["ts", "seq"]).reset_index(drop=True)
        indices["session_date"] = date_str

    # --- tổng hợp chất lượng ---
    q = snaps[["symbol", "flags"]].explode("flags").dropna()
    quality = (q.groupby(["symbol", "flags"]).size().reset_index(name="n")
               if not q.empty else pd.DataFrame(columns=["symbol", "flags", "n"]))
    quality["session_date"] = date_str
    meta_q = pd.DataFrame([{
        "session_date": date_str, "n_raw": n_raw, "n_curated": len(snaps),
        "n_duplicates_dropped": n_raw - len(snaps),
    }])

    bars = build_bars(snaps, settings)

    write_parquet(snaps, snap_path)
    write_parquet(bars, out_dir / "bars.parquet")
    write_parquet(indices, out_dir / "indices.parquet")
    write_parquet(quality, out_dir / "quality.parquet")
    write_parquet(meta_q, out_dir / "quality_meta.parquet")
    logger.info("Curated {} — {} snapshots ({} raw, {} lặp bị loại), {} bars",
                date_str, len(snaps), n_raw, n_raw - len(snaps), len(bars))
    return out_dir


def build_bars(snaps: pd.DataFrame, settings: Settings) -> pd.DataFrame:
    """Bar 1 phút từ snapshot 5s — nền tảng cho ILLIQ, σ, LHS, hiệu chỉnh κ."""
    freq = int(settings.bars.freq_s)
    lo = snaps[snaps["session"].isin(["LO_AM", "LO_PM"])].copy()
    lo["bar_ts"] = lo["ts"].dt.floor(f"{freq}s")
    g = lo.groupby(["symbol", "bar_ts"], sort=True)
    bars = g.agg(
        mid_open=("mid", "first"),
        mid_close=("mid", "last"),
        mid_high=("mid", "max"),
        mid_low=("mid", "min"),
        spread_bps=("spread_bps", "mean"),
        depth_bid_vnd=("depth_bid_vnd", "mean"),
        depth_ask_vnd=("depth_ask_vnd", "mean"),
        obi_mean=("obi", "mean"),
        obi_last=("obi", "last"),
        d_vol=("d_vol", "sum"),
        d_val=("d_val", "sum"),
        d_f_buy_val=("d_f_buy_val", "sum"),
        d_f_sell_val=("d_f_sell_val", "sum"),
        n_snap=("mid", "size"),
        n_flags=("n_flags", "sum"),
        session_date=("session_date", "first"),
        group=("group", "first"),
    ).reset_index()
    bars["d_f_net_val"] = bars["d_f_buy_val"] - bars["d_f_sell_val"]
    bars = bars.sort_values(["symbol", "bar_ts"]).reset_index(drop=True)

    # lợi nhuận phút (bps); loại nhịp bắc qua nghỉ trưa/khoảng trống lớn
    dt = bars.groupby("symbol")["bar_ts"].diff().dt.total_seconds()
    ret = bars.groupby("symbol")["mid_close"].pct_change() * BPS
    bars["ret_bps"] = ret.where(dt <= freq * 1.5)
    bars["illiq"] = amihud_bps_per_bn(bars["ret_bps"], bars["d_val"])
    bars["bucket"] = bars["bar_ts"].dt.time.map(lambda t: bucket_of_time(t, int(settings.alerts.bucket_min)))
    return bars


def process_all(settings: Settings, force: bool = False) -> list[Path]:
    dirs = list_session_dirs(settings.data_path(), mode=settings.mode)
    if not dirs:
        raise RuntimeError(
            f"Không có phiên RAW nào ở chế độ {settings.mode}. "
            "Chạy `neoscope synth` (mô phỏng) hoặc `neoscope record` (LIVE) trước."
        )
    return [process_session(settings, d, force=force) for d in dirs]


def load_curated(settings: Settings) -> dict[str, pd.DataFrame]:
    """Nạp toàn bộ curated của chế độ hiện tại, ghép theo phiên."""
    dirs = sorted(curated_dir_for(settings, d) for d in list_session_dirs(settings.data_path(), settings.mode))
    frames: dict[str, list[pd.DataFrame]] = {"snapshots": [], "bars": [], "indices": [], "quality": [], "quality_meta": []}
    for d in dirs:
        for key in frames:
            p = d / f"{key}.parquet"
            if p.exists():
                frames[key].append(read_parquet(p))
    return {k: (pd.concat(v, ignore_index=True) if v else pd.DataFrame()) for k, v in frames.items()}
