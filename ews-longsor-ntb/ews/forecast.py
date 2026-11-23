"""Prakiraan cuaca BMKG (adm4) - penarikan paralel + helper murni untuk popup."""
from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta

import requests

from . import config

ICON = {
    "Cerah": "☀️", "Cerah Berawan": "⛅", "Berawan": "☁️", "Berawan Tebal": "☁️",
    "Udara Kabur": "🌫️", "Asap": "🌫️", "Kabut": "🌫️",
    "Hujan Ringan": "🌧️", "Hujan Sedang": "🌧️", "Hujan Lebat": "⛈️",
    "Hujan Lokal": "🌦️", "Hujan Petir": "🌩️",
}


def emoji(deskripsi: str) -> str:
    return ICON.get(deskripsi, "☁️")


def fetch_forecasts(lokasi=config.LOKASI_PRAKIRAAN, max_workers: int = 4,
                    timeout: float = 10, get=requests.get) -> list[dict]:
    """Tarik prakiraan semua lokasi secara paralel (batas BMKG 60 req/menit; kita ~18 req).

    Bila BMKG membalas 429, sisa permintaan dibatalkan. Hasil yang sudah didapat tetap dikembalikan.
    """
    stop = threading.Event()
    headers = {"User-Agent": config.USER_AGENT}

    def satu(kode: str):
        if stop.is_set():
            return None
        try:
            r = get(config.BMKG_PRAKIRAAN_URL, params={"adm4": kode}, headers=headers, timeout=timeout)
        except requests.RequestException:
            return None
        if r.status_code == 429:
            stop.set()
            return None
        if r.status_code != 200:
            return None
        try:
            isi = r.json()
        except ValueError:
            return None
        data = isi.get("data") if isinstance(isi, dict) else None
        return data[0] if data else None

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        hasil = list(pool.map(satu, lokasi))
    return [h for h in hasil if h]


def _ramalan_berurut(item: dict) -> list[tuple[datetime, dict]]:
    """Ratakan semua ramalan item, kembalikan [(waktu_lokal, ramalan)] terurut."""
    hasil = []
    for hari in item.get("cuaca", []):
        if not isinstance(hari, list):
            continue
        for r in hari:
            try:
                dt = datetime.strptime(r.get("local_datetime", ""), "%Y-%m-%d %H:%M:%S")
            except (ValueError, TypeError):
                continue
            hasil.append((dt, r))
    hasil.sort(key=lambda x: x[0])
    return hasil


def cuaca_sekarang(item: dict, sekarang_wita: datetime) -> str:
    """Deskripsi cuaca pada slot prakiraan terdekat dengan waktu sekarang (WITA, naive)."""
    terbaik, selisih_min = "Berawan", None
    for dt, r in _ramalan_berurut(item):
        selisih = abs((dt - sekarang_wita).total_seconds())
        if selisih_min is None or selisih < selisih_min:
            selisih_min, terbaik = selisih, r.get("weather_desc", "Berawan")
    return terbaik


PERIODE = (("Pagi Hari", 6, 12), ("Siang Hari", 12, 18), ("Malam Hari", 18, 24), ("Dini Hari", 0, 6))


def prakiraan_periode(item: dict, sekarang_wita: datetime) -> dict[str, str | None]:
    """Cuaca per periode hari. Hanya slot yang BELUM lewat (>= sekarang-3 jam) yang dipakai,
    jadi 'Pagi Hari' tidak menampilkan pagi yang sudah berlalu."""
    batas = sekarang_wita - timedelta(hours=3)
    hasil: dict[str, str | None] = {nama: None for nama, _, _ in PERIODE}
    for dt, r in _ramalan_berurut(item):
        if dt < batas:
            continue
        for nama, awal, akhir in PERIODE:
            if hasil[nama] is None and awal <= dt.hour < akhir:
                desk = r.get("weather_desc", "Berawan")
                hasil[nama] = f"{emoji(desk)} {desk}"
        if all(hasil.values()):
            break
    return hasil
