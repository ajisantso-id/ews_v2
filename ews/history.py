"""Snapshot harian H-1 / H-2 (dibuat robot GitHub, dibaca dashboard)."""
from __future__ import annotations

import json
import os
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import NamedTuple

from . import config


class Snapshot(NamedTuple):
    data: list
    dibuat: datetime | None   # waktu snapshot dibuat (UTC). None = file format lama / tak ada.


def muat_snapshot(path: Path) -> Snapshot:
    """Baca snapshot. Mendukung format lama (list polos) dan format baru
    {"dibuat": ISO8601, "data": [...]}. File hilang/rusak -> Snapshot([], None)."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            isi = json.load(f)
    except (OSError, ValueError):
        return Snapshot([], None)

    if isinstance(isi, list):
        return Snapshot(isi, None)
    if isinstance(isi, dict) and isinstance(isi.get("data"), list):
        dibuat = None
        try:
            dibuat = datetime.fromisoformat(isi["dibuat"]).astimezone(timezone.utc)
        except (KeyError, TypeError, ValueError):
            pass
        return Snapshot(isi["data"], dibuat)
    return Snapshot([], None)


def _tulis_atomik(path: Path, isi: dict) -> None:
    """Tulis lewat file sementara lalu rename, supaya dashboard tak pernah baca file setengah jadi."""
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(isi, f, ensure_ascii=False)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def simpan_dan_geser(data: list, h1: Path = config.H1_FILE, h2: Path = config.H2_FILE,
                     sekarang: datetime | None = None) -> str:
    """Simpan `data` sebagai H-1 baru. Geser H-1 lama ke H-2 HANYA bila:
      * data baru tidak kosong (tarikan gagal tidak boleh menghapus histori), dan
      * H-1 lama dibuat pada tanggal (WITA) berbeda (menjalankan robot dua kali sehari
        tidak boleh menimpa H-2 dengan data hari yang sama).
    Return string status untuk log.
    """
    if not data:
        return "dilewati: data kosong, histori lama dipertahankan"

    sekarang = (sekarang or datetime.now(timezone.utc)).astimezone(timezone.utc)
    status = []

    if h1.exists():
        lama = muat_snapshot(h1)
        tanggal_lama = lama.dibuat.astimezone(config.WITA).date() if lama.dibuat else None
        if tanggal_lama != sekarang.astimezone(config.WITA).date():
            shutil.copyfile(h1, h2)
            status.append("H-1 lama digeser ke H-2")
        else:
            status.append("H-1 hari ini ditimpa (H-2 tidak berubah)")

    _tulis_atomik(h1, {"dibuat": sekarang.isoformat(), "data": data})
    status.append(f"H-1 baru disimpan ({len(data)} stasiun)")
    return "; ".join(status)
