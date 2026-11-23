"""Penarik data AWS Center (dipakai dashboard DAN robot harian)."""
from __future__ import annotations

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from . import config


def _buat_session() -> requests.Session:
    s = requests.Session()
    retry = Retry(total=2, backoff_factor=1.0, status_forcelist=(502, 503, 504),
                  allowed_methods=frozenset({"GET", "POST"}))
    s.mount("https://", HTTPAdapter(max_retries=retry))
    s.headers.update({"User-Agent": config.USER_AGENT})
    return s


def fetch_stations(akun_list, kota=config.KOTA_NTB, timeout: float = 15,
                   session_factory=_buat_session) -> tuple[list[dict], list[str]]:
    """Login tiap akun, tarik stasiun hujan NTB, gabung tanpa duplikat.

    Return (data, daftar_error). Error tidak pernah memuat password.
    Bila stasiun sama muncul di dua akun, dipakai yang `tanggal`-nya paling baru.
    """
    gabungan: dict[str, dict] = {}
    errors: list[str] = []

    for akun in akun_list:
        try:
            s = session_factory()
            r = s.post(config.AWSCENTER_LOGIN_URL,
                       data={"username": akun.username, "password": akun.password},
                       timeout=timeout)
            r.raise_for_status()
            r = s.get(config.AWSCENTER_API_URL, timeout=timeout)
            r.raise_for_status()
            baris = r.json()
            if not isinstance(baris, list):
                raise ValueError("respons bukan daftar stasiun (login kemungkinan gagal)")
        except Exception as e:  # noqa: BLE001 - tiap akun dibiarkan gagal sendiri-sendiri
            errors.append(f"akun {akun.samar()}: {type(e).__name__}: {e}")
            continue

        for item in baris:
            if not isinstance(item, dict) or item.get("nama_kota") not in kota:
                continue
            kunci = item.get("id_station") or f"{item.get('name_station')}|{item.get('lat')}|{item.get('lng')}"
            lama = gabungan.get(kunci)
            if lama is None or str(item.get("tanggal", "")) > str(lama.get("tanggal", "")):
                gabungan[kunci] = item

    return list(gabungan.values()), errors
