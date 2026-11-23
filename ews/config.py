"""Konfigurasi terpusat. Semua angka 'ajaib' dan daftar tetap ada di sini."""
from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import timedelta, timezone
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

# WITA = UTC+8 tetap (Indonesia tidak pakai DST), jadi tidak perlu pytz/tzdata.
WITA = timezone(timedelta(hours=8))

# --- AWS Center ---------------------------------------------------------------
AWSCENTER_LOGIN_URL = "https://awscenter.bmkg.go.id/base/verify"
AWSCENTER_API_URL = "https://awscenter.bmkg.go.id/dashboard/get_parameter_terkini_hujan"

KOTA_NTB = (
    "Kota Mataram", "Kab. Lombok Barat", "Kab. Lombok Tengah", "Kab. Lombok Timur",
    "Kab. Lombok Utara", "Kab. Sumbawa Barat", "Kab. Sumbawa", "Kab. Dompu",
    "Kab. Bima", "Kota Bima",
)

# --- File data ------------------------------------------------------------------
H1_FILE = BASE_DIR / "data_h1.json"
H2_FILE = BASE_DIR / "data_h2.json"


def _pilih_file(*nama: str) -> Path:
    """Ambil file pertama yang ada (mis. versi .min hasil scripts/simplify_geojson.py)."""
    for n in nama:
        p = BASE_DIR / n
        if p.exists():
            return p
    return BASE_DIR / nama[-1]


GEOJSON_LONGSOR = _pilih_file("zona_longsor.min.geojson", "zona_longsor.geojson")
GEOJSON_BANJIR = _pilih_file("banjir_ntb.min.geojson", "banjir_ntb.geojson")

# --- Perilaku ---------------------------------------------------------------------
TTL_LIVE = 300          # detik, cache data AWS Center
TTL_PRAKIRAAN = 3600    # detik, prakiraan BMKG update ~2x sehari
TTL_NOWCAST = 60
TTL_RADAR = 300
AUTO_REFRESH_MS = 300_000

AMBANG_ALARM_MM = 50.0     # >= nilai ini selama 3 hari berturut-turut => alarm darurat
STALE_JAM = 6              # data stasiun lebih tua dari ini dianggap 'tidak update'

# --- Radar SIDARMA (jaringan internal) -----------------------------------------------
# Bounding box kasar radar Lombok: [[lat_bawah, lon_kiri], [lat_atas, lon_kanan]].
# Kalau gambar melenceng, minta koordinat pasti ke teknisi SIDARMA.
BATAS_RADAR_LOMBOK = [[-10.85, 113.85], [-6.45, 118.45]]
RADAR_STATUS_PATH = "imageStatus_Lombok.json?id=123"
RADAR_LAYER = {"CMAX": "CMAX", "PAC": "PAC12H"}   # nama tampil -> kunci di JSON

# --- Prakiraan cuaca BMKG (kode adm4) -------------------------------------------------
BMKG_PRAKIRAAN_URL = "https://api.bmkg.go.id/publik/prakiraan-cuaca"
LOKASI_PRAKIRAAN = (
    "52.08.05.2004",  # Malaka (Pusuk Gunung Sari)
    "52.02.12.2006",  # Aik Berik (Batukliang Utara)
    "52.03.15.2001",  # Sembalun Bumbung (Pusuk Sembalun)
    "52.01.07.2002",  # Sekotong Barat (Sekotong)
    "52.07.04.2001",  # Sekongkang Atas
    "52.04.07.2003",  # Bao Desa (Batu Lanteh)
    "52.04.11.2008",  # Ropang
    "52.06.11.2006",  # Doro O'o (Langgudu)
    "52.06.15.2005",  # Sai (Soromandi)
    "52.06.14.2003",  # Kawinda Toi (Tambora)
    "52.71.06.1003",  # Bertais (Sandubaya)
    "52.02.01.1001",  # Praya
    "52.07.02.1005",  # Kuang (Taliwang)
    "52.04.02.2001",  # Lunyuk Rea (Lunyuk)
    "52.04.13.2004",  # Plampang
    "52.05.05.2005",  # Wawonduru (Woja)
    "52.06.18.2002",  # Belo (Palibelo)
    "52.72.01.1001",  # Paruga (Kota Bima)
)

NOWCAST_RSS_URL = "https://www.bmkg.go.id/alerts/nowcast/id/rss.xml"
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) EWS-NTB-Dashboard"


# --- Rahasia (kredensial) --------------------------------------------------------------
def get_secret(nama: str, default: str | None = None) -> str | None:
    """Baca rahasia dari environment variable dulu (GitHub Actions), lalu st.secrets.

    Kredensial TIDAK BOLEH ditulis di kode / di-commit ke repo.
    """
    nilai = os.environ.get(nama)
    if nilai:
        return nilai
    try:
        import streamlit as st  # hanya ada di sisi dashboard

        nilai = st.secrets.get(nama)
        return str(nilai) if nilai not in (None, "") else default
    except Exception:
        return default


@dataclass(frozen=True)
class Akun:
    username: str
    password: str

    def samar(self) -> str:
        """Bentuk aman untuk log: ***40"""
        return "***" + self.username[-2:]

    def __repr__(self) -> str:  # jangan pernah bocorkan password lewat repr/log
        return f"Akun({self.samar()})"


def muat_akun_awscenter() -> list[Akun]:
    """Nama secret sama dengan versi lama: AWSCENTER_USER/PASS, AWSCENTER_USER2/PASS2, dst."""
    akun: list[Akun] = []
    for sufiks in ("", "2", "3", "4"):
        u = get_secret(f"AWSCENTER_USER{sufiks}")
        p = get_secret(f"AWSCENTER_PASS{sufiks}")
        if u and p:
            akun.append(Akun(str(u), str(p)))
    return akun
