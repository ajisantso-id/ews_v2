"""Perkecil file GeoJSON poligon tanpa dependensi tambahan (murni Python).

Langkah: bulatkan koordinat -> buang titik duplikat -> sederhanakan garis (Douglas-Peucker)
-> (opsional) buang properti yang tak dipakai & filter fitur.

Contoh (hasil ditulis ke *.min.geojson; dashboard otomatis memakainya bila ada):
    python scripts/simplify_geojson.py zona_longsor.geojson --keep REMARK
    python scripts/simplify_geojson.py banjir_ntb.geojson --keep DN --where DN=1

Toleransi default 0.0002 derajat (~22 m) tak terlihat pada peta tingkat provinsi.
"""
import argparse
import json
import math
import sys
from pathlib import Path


def _jarak_tegak(p, a, b):
    (x, y), (x1, y1), (x2, y2) = p, a, b
    dx, dy = x2 - x1, y2 - y1
    if dx == 0 and dy == 0:
        return math.hypot(x - x1, y - y1)
    t = max(0.0, min(1.0, ((x - x1) * dx + (y - y1) * dy) / (dx * dx + dy * dy)))
    return math.hypot(x - (x1 + t * dx), y - (y1 + t * dy))


def douglas_peucker(pts, tol):
    """Versi iteratif (tanpa rekursi) supaya aman untuk garis sangat panjang."""
    n = len(pts)
    if n < 3:
        return pts[:]
    simpan = [False] * n
    simpan[0] = simpan[-1] = True
    tumpukan = [(0, n - 1)]
    while tumpukan:
        i, j = tumpukan.pop()
        jauh, idx = 0.0, None
        for k in range(i + 1, j):
            d = _jarak_tegak(pts[k], pts[i], pts[j])
            if d > jauh:
                jauh, idx = d, k
        if idx is not None and jauh > tol:
            simpan[idx] = True
            tumpukan += [(i, idx), (idx, j)]
    return [p for p, s in zip(pts, simpan) if s]


def sederhanakan_ring(ring, tol, desimal):
    """Return ring baru, atau None bila ring runtuh (terlalu kecil setelah dibulatkan)."""
    bulat = []
    for x, y, *_ in ring:
        p = (round(x, desimal), round(y, desimal))
        if not bulat or p != bulat[-1]:
            bulat.append(p)
    if len(bulat) < 4:
        return None
    hasil = douglas_peucker(bulat, tol)
    if len(hasil) < 4:          # jangan sampai ring jadi garis; pakai versi yang cuma dibulatkan
        hasil = bulat
    return [list(p) for p in hasil]


def _poligon(rings, tol, desimal):
    """Satu poligon = [ring_luar, *lubang]. Return None bila ring luar runtuh."""
    baru = [sederhanakan_ring(r, tol, desimal) for r in rings]
    if not baru or baru[0] is None:
        return None
    return [r for r in baru if r is not None]


def proses_geometri(g, tol, desimal):
    """Return geometri baru, atau None bila kosong/runtuh (fitur akan dibuang)."""
    if g["type"] == "Polygon":
        koord = _poligon(g["coordinates"], tol, desimal)
        if koord is None:
            return None
        g["coordinates"] = koord
    elif g["type"] == "MultiPolygon":
        koord = [p for p in (_poligon(poly, tol, desimal) for poly in g["coordinates"]) if p]
        if not koord:
            return None
        g["coordinates"] = koord
    return g


def cocok(nilai, target):
    try:
        return float(nilai) == float(target)
    except (TypeError, ValueError):
        return str(nilai) == target


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("sumber")
    ap.add_argument("-o", "--output", help="default: <nama>.min.geojson")
    ap.add_argument("--tol", type=float, default=0.0002, help="toleransi (derajat), default 0.0002")
    ap.add_argument("--desimal", type=int, default=5, help="angka di belakang koma koordinat, default 5")
    ap.add_argument("--keep", nargs="*", help="hanya pertahankan properti ini (default: semua)")
    ap.add_argument("--where", help="filter fitur, format KUNCI=NILAI (mis. DN=1)")
    a = ap.parse_args()

    src = Path(a.sumber)
    out = Path(a.output) if a.output else src.with_name(src.stem + ".min.geojson")
    data = json.loads(src.read_text(encoding="utf-8"))

    awal = len(data["features"])
    fitur = data["features"]
    if a.where:
        k, v = a.where.split("=", 1)
        fitur = [f for f in fitur if cocok(f["properties"].get(k), v)]
    hasil = []
    for f in fitur:
        geom = proses_geometri(f["geometry"], a.tol, a.desimal)
        if geom is None:          # geometri kosong / runtuh: tak ada yang bisa digambar
            continue
        f["geometry"] = geom
        if a.keep is not None:
            f["properties"] = {k: f["properties"].get(k) for k in a.keep}
        hasil.append(f)
    fitur = hasil
    data["features"] = fitur
    data.pop("crs", None)

    out.write_text(json.dumps(data, separators=(",", ":"), ensure_ascii=False), encoding="utf-8")
    kecil, besar = out.stat().st_size, src.stat().st_size
    print(f"{src.name}: {besar/1e6:.2f} MB -> {out.name}: {kecil/1e6:.2f} MB "
          f"({100 * (1 - kecil / besar):.0f}% lebih kecil, {len(fitur)} dari {awal} fitur dipertahankan)")


if __name__ == "__main__":
    sys.exit(main())
