"""Peringatan Dini Cuaca (CAP nowcast BMKG) untuk NTB."""
from __future__ import annotations

import re
import time
import xml.etree.ElementTree as ET

import requests

from . import config


def _buang_namespace(root: ET.Element) -> ET.Element:
    for el in root.iter():
        if isinstance(el.tag, str) and "}" in el.tag:
            el.tag = el.tag.split("}", 1)[1]
    return root


def _xml(teks: str) -> ET.Element:
    return _buang_namespace(ET.fromstring(teks))


_RE_NTB = re.compile(r"nusa tenggara barat|\bNTB\b", re.IGNORECASE)


def parse_cap(teks_xml: str) -> list[dict]:
    """Ubah satu dokumen CAP menjadi daftar poligon peringatan (koordinat (lat, lon))."""
    root = _xml(teks_xml)
    blok_id = [i for i in root.findall(".//info") if "id" in i.findtext("language", "").lower()]
    hasil = []
    for idx, info in enumerate(blok_id):
        severity = info.findtext("severity", "").lower()
        if severity in ("moderate", "minor"):
            warna = "yellow"
        elif severity in ("severe", "extreme"):
            warna = "orange"
        else:
            warna = "orange" if idx == 0 else "yellow"

        for area in info.findall(".//area"):
            for poly in area.findall(".//polygon"):
                koordinat = []
                for pt in (poly.text or "").split():
                    if "," in pt:
                        try:
                            lat, lon = pt.split(",")[:2]
                            koordinat.append((float(lat), float(lon)))
                        except ValueError:
                            continue
                if koordinat:
                    hasil.append({
                        "coords": koordinat, "warna": warna,
                        "opacity": 0.6 if warna == "orange" else 0.4,
                        "nama_area": area.findtext("areaDesc", "Wilayah Terdampak"),
                        "event": info.findtext("event", "Peringatan Dini Cuaca"),
                        "description": info.findtext("description", "-"),
                        "effective": info.findtext("effective", "-"),
                        "expires": info.findtext("expires", "-"),
                    })
    return hasil


def fetch_nowcast(timeout: float = 10, get=requests.get) -> list[dict]:
    """Tarik RSS lalu CAP semua peringatan NTB. Gagal total di RSS -> exception (jangan di-cache);
    gagal pada satu CAP -> dilewati."""
    headers = {"User-Agent": config.USER_AGENT}
    stamp = int(time.time())
    r = get(f"{config.NOWCAST_RSS_URL}?t={stamp}", headers=headers, timeout=timeout)
    r.raise_for_status()
    rss = _xml(r.text)

    hasil: list[dict] = []
    for item in rss.findall(".//item"):
        if not _RE_NTB.search(item.findtext("title", "")):
            continue
        link = item.findtext("link", "")
        if not link:
            continue
        try:
            rc = get(f"{link}?t={stamp}", headers=headers, timeout=timeout)
            rc.raise_for_status()
            hasil.extend(parse_cap(rc.text))
        except (requests.RequestException, ET.ParseError):
            continue

    hasil.sort(key=lambda x: 1 if x["warna"] == "yellow" else 2)   # kuning digambar dulu, oranye di atasnya
    return hasil
