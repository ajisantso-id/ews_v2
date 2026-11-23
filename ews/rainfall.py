"""Logika curah hujan: parsing, klasifikasi, data basi, dan alarm 3 hari. Murni (tanpa UI)."""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from . import config


@dataclass(frozen=True)
class Level:
    urutan: int
    kategori: str
    status: str      # Aman / WASPADA / SIAGA / AWAS
    warna: str       # warna marker (nama warna folium/CSS)
    ikon: str        # emoji status untuk tabel
    glyph: str       # ikon bootstrap untuk marker berbahaya ('' = pakai bentuk SVG)
    rentang: str     # teks legenda


LEVELS = (
    Level(0, "Cerah / Berawan", "Aman", "blue", "🔵", "", "Cerah (0 mm)"),
    Level(1, "Hujan Ringan", "Aman", "green", "🟢", "", "Ringan (0.1 - 20 mm)"),
    Level(2, "Hujan Sedang", "Aman", "yellow", "🟡", "", "Sedang (20 - 50 mm)"),
    Level(3, "Hujan Lebat", "WASPADA", "orange", "🟠", "info-sign", "Lebat - Waspada (50 - 100 mm)"),
    Level(4, "Hujan Sangat Lebat", "SIAGA", "red", "🔴", "warning-sign", "Sangat Lebat - Siaga (100 - 150 mm)"),
    Level(5, "Hujan Ekstrem", "AWAS", "darkred", "⚫", "flash", "Ekstrem - Awas (> 150 mm)"),
)


def parse_curah(nilai) -> float | None:
    """Ubah nilai mentah API jadi mm. None = offline/error (kosong, 'offline', negatif, rusak)."""
    if nilai is None:
        return None
    teks = str(nilai).strip().replace(",", ".")
    if teks == "" or teks.lower() == "offline":
        return None
    try:
        mm = float(teks)
    except ValueError:
        return None
    return None if mm < 0 else mm


def klasifikasi(mm: float) -> Level:
    """Satu-satunya tempat batas kategori didefinisikan (peta, tabel, dan alarm memakai ini)."""
    if mm <= 0:
        return LEVELS[0]
    if mm <= 20:
        return LEVELS[1]
    if mm < 50:
        return LEVELS[2]
    if mm <= 100:
        return LEVELS[3]
    if mm <= 150:
        return LEVELS[4]
    return LEVELS[5]


_RE_ZONA = re.compile(r"([+-])(\d{2})(?::?(\d{2}))?$")


def parse_waktu(teks) -> datetime | None:
    """'2026-10-23 08:50:00+00' -> datetime aware (UTC). None jika tidak terbaca."""
    if not teks:
        return None
    s = str(teks).strip().replace("T", " ")
    zona = timezone.utc
    m = _RE_ZONA.search(s)
    if m:
        jam, menit = int(m.group(2)), int(m.group(3) or 0)
        delta = timedelta(hours=jam, minutes=menit)
        zona = timezone(delta if m.group(1) == "+" else -delta)
        s = s[: m.start()]
    elif s.endswith("Z"):
        s = s[:-1]
    try:
        return datetime.fromisoformat(s).replace(tzinfo=zona)
    except ValueError:
        return None


def umur_jam(item: dict, acuan: datetime | None) -> float | None:
    """Umur data stasiun (jam) relatif terhadap `acuan`. None bila tak bisa dihitung."""
    if acuan is None:
        return None
    waktu = parse_waktu(item.get("tanggal"))
    if waktu is None:
        return None
    return (acuan - waktu).total_seconds() / 3600


def is_stale(item: dict, acuan: datetime | None, batas_jam: float = config.STALE_JAM) -> bool:
    """True bila stasiun sudah lama tidak mengirim data (angka 0.0 lama menyesatkan di EWS)."""
    umur = umur_jam(item, acuan)
    return umur is not None and umur > batas_jam


def deret_bahaya(live: list[dict], h1: list[dict], h2: list[dict],
                 ambang: float = config.AMBANG_ALARM_MM) -> list[str]:
    """Nama stasiun dengan curah >= ambang pada hari ini, H-1, dan H-2 sekaligus."""

    def peta(rows: list[dict]) -> dict:
        return {r.get("id_station"): parse_curah(r.get("curah")) for r in rows}

    d1, d2 = peta(h1), peta(h2)
    hasil = []
    for item in live:
        sid = item.get("id_station")
        nilai = (parse_curah(item.get("curah")), d1.get(sid), d2.get(sid))
        if all(v is not None and v >= ambang for v in nilai):
            hasil.append(item.get("name_station", str(sid)))
    return sorted(hasil)
