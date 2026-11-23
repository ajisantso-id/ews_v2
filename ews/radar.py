"""Radar SIDARMA (jaringan internal BMKG).

Gambar diunduh di sisi server (pakai Basic Auth) lalu disematkan sebagai data-URI ke peta,
jadi browser pengguna TIDAK perlu mengakses IP internal maupun tahu kredensialnya.
Server dashboard harus bisa menjangkau jaringan internal; di Streamlit Cloud layer ini akan kosong.
"""
from __future__ import annotations

import base64
from urllib.parse import urljoin

import requests

from . import config

MAKS_BYTE = 8_000_000


def fetch_radar(base_url: str | None, user: str | None, password: str | None,
                timeout: float = 10, get=requests.get) -> dict[str, str]:
    """Return {nama_layer: data_uri}. Dict kosong bila radar tidak dikonfigurasi/tak terjangkau."""
    if not base_url:
        return {}
    base = base_url.rstrip("/") + "/"
    auth = (user, password) if user else None

    r = get(urljoin(base, config.RADAR_STATUS_PATH), auth=auth, timeout=timeout)
    r.raise_for_status()
    status = r.json()

    hasil: dict[str, str] = {}
    for nama, kunci in config.RADAR_LAYER.items():
        try:
            path = status[kunci]["Latest"]["file"]
        except (KeyError, TypeError):
            continue
        try:
            img = get(urljoin(base, path), auth=auth, timeout=timeout)
            img.raise_for_status()
        except requests.RequestException:
            continue
        tipe = img.headers.get("Content-Type", "image/png").split(";")[0].strip()
        if not tipe.startswith("image/") or len(img.content) > MAKS_BYTE:
            continue
        hasil[nama] = f"data:{tipe};base64,{base64.b64encode(img.content).decode('ascii')}"
    return hasil
