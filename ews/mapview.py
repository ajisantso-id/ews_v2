"""Pembuat peta Folium. Satu fungsi publik: build_map(MapData)."""
from __future__ import annotations

import html
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime

import folium
from branca.element import MacroElement, Template

from . import config, forecast, rainfall

log = logging.getLogger(__name__)
esc = html.escape

NAMA_LONGSOR = "Zona Kerentanan Gerakan Tanah"
NAMA_BANJIR = "Zona Rawan Banjir (InaRISK)"
NAMA_PRAKIRAAN = "🌤️ Prakiraan Cuaca BMKG (Se-NTB)"
NAMA_NOWCAST = "🚨 Peringatan Dini Cuaca"


@dataclass
class MapData:
    stasiun: list
    sekarang_wita: datetime                 # naive WITA, untuk mencocokkan slot prakiraan
    acuan: datetime | None = None           # waktu acuan umur data (UTC); None = jangan cek data lama
    prakiraan: list = field(default_factory=list)
    nowcast: list = field(default_factory=list)
    radar: dict = field(default_factory=dict)
    geo_longsor: dict | None = None
    geo_banjir: dict | None = None
    alarm: list = field(default_factory=list)
    sumber_gagal: list = field(default_factory=list)


# ------------------------------------------------------------------ marker stasiun
def _bentuk(item: dict) -> str:
    nama = str(item.get("name_station", "")).upper()
    tipe = str(item.get("type", "")).lower()
    if "ARG" in nama:
        return "segitiga"
    if "MAWS" in nama or "MARITIM" in nama:
        return "belah_ketupat"
    if "AAWS" in nama or "AGRO" in nama:
        return "kotak"
    return {"arg": "segitiga", "aaws": "kotak"}.get(tipe, "lingkaran")


def _svg(bentuk: str, warna: str) -> str:
    badan = {
        "segitiga": (18, f'<polygon points="9,2 2,15 16,15" fill="{warna}" stroke="black" stroke-width="1.5" stroke-linejoin="round"/>'),
        "belah_ketupat": (18, f'<polygon points="9,2 16,9 9,16 2,9" fill="{warna}" stroke="black" stroke-width="1.5" stroke-linejoin="round"/>'),
        "kotak": (16, f'<rect x="2" y="2" width="12" height="12" fill="{warna}" stroke="black" stroke-width="1.5" rx="1"/>'),
        "lingkaran": (16, f'<circle cx="8" cy="8" r="6" fill="{warna}" stroke="black" stroke-width="1.5"/>'),
    }[bentuk]
    ukuran, isi = badan
    return (f'<div style="display:flex;justify-content:center;align-items:center;width:100%;height:100%;">'
            f'<svg width="{ukuran}" height="{ukuran}" viewBox="0 0 {ukuran} {ukuran}" '
            f'style="filter:drop-shadow(1px 1px 2px rgba(0,0,0,0.5));">{isi}</svg></div>')


def _bulatan_abu(simbol: str, warna_simbol: str) -> str:
    return (f'<div style="background:grey;border-radius:50%;width:18px;height:18px;color:{warna_simbol};'
            f'text-align:center;line-height:16px;font-weight:bold;border:2px solid white;'
            f'box-shadow:1px 1px 3px rgba(0,0,0,0.5);font-size:12px;">{simbol}</div>')


def _popup(judul: str, baris: list[str], tanggal: str) -> folium.Popup:
    isi = "".join(f"<br>{b}" for b in baris)
    return folium.Popup(
        f"<div style='min-width:150px;'><b>{judul}</b>{isi}<br><small>Update: {tanggal} UTC</small></div>",
        max_width=300)


def _div_icon(isi: str) -> folium.DivIcon:
    return folium.DivIcon(html=isi, icon_size=(20, 20), icon_anchor=(10, 10))


def _satu_stasiun(m: folium.Map, item: dict, acuan: datetime | None) -> None:
    lat, lon = float(item["lat"]), float(item["lng"])
    nama = esc(str(item.get("name_station", "?")))
    tanggal = esc(str(item.get("tanggal", "waktu tidak diketahui")))
    mm = rainfall.parse_curah(item.get("curah"))

    if mm is None:
        folium.Marker([lat, lon], popup=_popup(nama, ["Status: <b>OFFLINE / ERROR</b>"], tanggal),
                      tooltip=f"{nama}: OFFLINE", icon=_div_icon(_bulatan_abu("✖", "red"))).add_to(m)
        return

    if rainfall.is_stale(item, acuan):
        umur = rainfall.umur_jam(item, acuan) or 0
        teks_umur = f"{umur / 24:.1f} hari" if umur >= 48 else f"{umur:.0f} jam"
        folium.Marker(
            [lat, lon],
            popup=_popup(nama, [f"Data terakhir <b>{teks_umur}</b> lalu (stasiun tidak update)",
                                f"Nilai terakhir: {mm} mm (tidak dipakai)"], tanggal),
            tooltip=f"{nama}: data lama ({teks_umur})",
            icon=_div_icon(_bulatan_abu("⏱", "white"))).add_to(m)
        return

    lv = rainfall.klasifikasi(mm)
    baris = [f"Curah Hujan: <b>{mm} mm</b>", f"Kategori: <b>{lv.kategori}</b>", f"Status Area: <b>{lv.status}</b>"]
    if lv.urutan < 3:
        icon = _div_icon(_svg(_bentuk(item), lv.warna))
        tip = f"{nama}: {mm} mm ({lv.kategori})"
    else:
        icon = folium.Icon(color=lv.warna, icon=lv.glyph, icon_color="white")
        tip = f"{nama} ({lv.kategori})"
    folium.Marker([lat, lon], popup=_popup(nama, baris, tanggal), tooltip=tip, icon=icon).add_to(m)


def _tambah_stasiun(m: folium.Map, d: MapData) -> None:
    # Urut naik: stasiun paling berbahaya digambar terakhir sehingga selalu di atas.
    urut = sorted(d.stasiun, key=lambda i: rainfall.parse_curah(i.get("curah")) if rainfall.parse_curah(i.get("curah")) is not None else -1)
    for item in urut:
        try:
            _satu_stasiun(m, item, d.acuan)
        except Exception as e:  # noqa: BLE001 - satu stasiun rusak tak boleh merusak peta
            log.warning("stasiun %s dilewati: %s", item.get("id_station"), e)


# ------------------------------------------------------------------ layer zona
def _style_longsor(feature: dict) -> dict:
    kat = str(feature["properties"].get("REMARK", "")).upper()
    if "SANGAT TINGGI" in kat:
        warna, op = "#cc0000", 0.4
    elif "TINGGI" in kat:
        warna, op = "#ff3385", 0.4
    elif "MENENGAH" in kat or "SEDANG" in kat:
        warna, op = "#ffff00", 0.4
    elif "SANGAT RENDAH" in kat:
        warna, op = "#00ccff", 0.4
    elif "RENDAH" in kat:
        warna, op = "#00cc00", 0.2
    elif "ALUR" in kat:                   # Alur Aliran Bahan Rombakan
        warna, op = "#8e24aa", 0.5
    else:                                  # Danau/Situ & tak dikenal: jangan diwarnai seolah 'rendah'
        return {"fillOpacity": 0, "weight": 0, "interactive": False}
    return {"fillColor": warna, "color": warna, "weight": 0.5, "fillOpacity": op, "interactive": False}


def _style_banjir(_feature: dict) -> dict:
    return {"fillColor": "#00008B", "color": "#00008B", "weight": 0.5, "fillOpacity": 0.5, "interactive": False}


# ------------------------------------------------------------------ prakiraan & nowcast
def _layer_prakiraan(d: MapData) -> folium.FeatureGroup:
    grup = folium.FeatureGroup(name=NAMA_PRAKIRAAN, show=False)
    for item in d.prakiraan:
        try:
            lok = item.get("lokasi", {})
            lat, lon = float(lok.get("lat", 0)), float(lok.get("lon", 0))
            if lat == 0 and lon == 0:
                continue
            kec, kab = esc(str(lok.get("kecamatan", "Lokasi"))), esc(str(lok.get("kotkab", "")))
            sekarang = forecast.cuaca_sekarang(item, d.sekarang_wita)
            ikon = (f'<div style="font-size:16px;background:rgba(255,255,255,0.85);border-radius:50%;width:26px;'
                    f'height:26px;display:flex;justify-content:center;align-items:center;'
                    f'box-shadow:1px 1px 3px rgba(0,0,0,0.5);border:1px solid #777;">{forecast.emoji(sekarang)}</div>')
            tabel = "".join(
                f"<tr><td style='padding:6px;border-bottom:1px solid #ddd;font-weight:bold;'>{periode}</td>"
                f"<td style='padding:6px;border-bottom:1px solid #ddd;text-align:right;'>{esc(isi or '-')}</td></tr>"
                for periode, isi in forecast.prakiraan_periode(item, d.sekarang_wita).items())
            popup = (f"<div style='min-width:220px;font-family:sans-serif;'>"
                     f"<h4 style='margin:5px 0 0 0;color:#002B5B;text-align:center;'>📍 Kec. {kec}</h4>"
                     f"<div style='text-align:center;'><small style='color:gray;'>{kab}</small></div>"
                     f"<hr style='margin:8px 0;'><table style='width:100%;font-size:13px;border-collapse:collapse;'>"
                     f"{tabel}</table></div>")
            folium.Marker([lat, lon], tooltip=f"<b>Kec. {kec}</b>: {esc(sekarang)}",
                          popup=folium.Popup(popup, max_width=300),
                          icon=folium.DivIcon(html=ikon, icon_size=(26, 26), icon_anchor=(13, 13))).add_to(grup)
        except Exception as e:  # noqa: BLE001
            log.warning("prakiraan dilewati: %s", e)
    return grup


def _layer_nowcast(d: MapData) -> folium.FeatureGroup:
    grup = folium.FeatureGroup(name=NAMA_NOWCAST, show=False)
    for p in d.nowcast:
        deskripsi = esc(str(p["description"])).replace("\n", "<br>")
        popup = (f"<div style='min-width:280px;max-height:250px;overflow-y:auto;'>"
                 f"<h4 style='color:#cc0000;margin-top:0;'>🚨 {esc(p['event'])}</h4><b>{esc(p['nama_area'])}</b><br><br>"
                 f"<span style='font-size:12px;color:#333;'>{deskripsi}</span><br><br><hr style='margin:5px 0;'>"
                 f"<small style='color:#555;'><b>Mulai:</b> {esc(p['effective'])}<br><b>Berakhir:</b> {esc(p['expires'])}</small></div>")
        folium.Polygon(locations=p["coords"], color=p["warna"], weight=2, fill=True, fill_color=p["warna"],
                       fill_opacity=p["opacity"],
                       tooltip=f"<b>🚨 {esc(p['event'])}</b><br>{esc(p['nama_area'])}",
                       popup=folium.Popup(popup, max_width=350)).add_to(grup)
    return grup


# ------------------------------------------------------------------ legenda, banner, judul
_KOTAK = "position:fixed;bottom:45px;display:flex;gap:15px;z-index:9999;align-items:flex-end;"
_PANEL = ("background-color:rgba(255,255,255,0.9);border:2px solid {border};font-size:12px;padding:10px;"
          "border-radius:8px;box-shadow:2px 2px 5px rgba(0,0,0,0.3);color:black;width:{w}px;{extra}")


def _panel(id_: str, judul: str, isi: str, border: str, w: int, tampil: bool = False) -> str:
    extra = "" if tampil else "display:none;"
    return (f'<div id="{id_}" style="{_PANEL.format(border=border, w=w, extra=extra)}">'
            f'<h4 style="margin:0 0 10px 0;font-size:14px;text-align:center;"><b>{judul}</b></h4>{isi}</div>')


def _kotak_warna(warna: str, opacity: float, label: str) -> str:
    return (f'<div style="margin-bottom:2px;"><i style="background:{warna};opacity:{opacity};width:12px;height:12px;'
            f'float:left;margin-right:8px;"></i>{label}</div>')


def _legenda_hujan() -> str:
    baris = ""
    for lv in rainfall.LEVELS:
        simbol = "⚠" if lv.urutan in (3, 4) else ("⚡" if lv.urutan == 5 else "")
        teks = "black" if lv.warna == "yellow" else "white"
        border = "border:1px solid #ccc;" if lv.warna == "yellow" else ""
        baris += (f'<div style="margin-bottom:6px;height:18px;"><div style="background:{lv.warna};border-radius:50%;'
                  f'width:18px;height:18px;color:{teks};text-align:center;line-height:18px;float:left;margin-right:8px;'
                  f'font-size:10px;{border}">{simbol}</div><span style="line-height:18px;">{lv.rentang}</span></div>')
    baris += ('<div style="margin-bottom:6px;height:18px;"><div style="background:grey;border-radius:50%;width:18px;'
              'height:18px;color:white;text-align:center;line-height:18px;float:left;margin-right:8px;font-size:10px;">⏱</div>'
              f'<span style="line-height:18px;">Offline / data &gt; {config.STALE_JAM} jam</span></div>')
    baris += ('<div style="margin-top:4px;font-size:10px;color:#444;">▲ ARG &nbsp; ● AWS &nbsp; ■ AAWS &nbsp; ◆ MAWS</div>')
    return ('<div style="margin-bottom:5px;font-weight:bold;">Intensitas Curah Hujan (24 Jam) dan Bahaya:</div>' + baris)


def _legenda_html() -> str:
    prakiraan = "".join(f'<div style="margin-bottom:4px;"><span style="font-size:14px;margin-right:8px;">{e}</span>{t}</div>'
                        for e, t in [("☀️", "Cerah"), ("⛅", "Cerah Berawan"), ("☁️", "Berawan"), ("🌫️", "Kabut / Asap"),
                                     ("🌦️", "Hujan Lokal"), ("🌧️", "Hujan Ringan-Sedang"), ("⛈️", "Hujan Lebat"), ("🌩️", "Hujan Petir")])
    longsor = (_kotak_warna("#cc0000", 0.6, "Sangat Tinggi") + _kotak_warna("#ff3385", 0.6, "Tinggi")
               + _kotak_warna("#ffff00", 0.6, "Menengah") + _kotak_warna("#00cc00", 0.3, "Rendah")
               + _kotak_warna("#00ccff", 0.3, "Sangat Rendah") + _kotak_warna("#8e24aa", 0.5, "Alur Aliran Bahan Rombakan"))
    banjir = _kotak_warna("#00008B", 0.5, "Rawan Banjir (InaRISK)")
    nowcast = (_kotak_warna("orange", 0.6, "Wilayah Peringatan Dini") + _kotak_warna("yellow", 0.6, "Wilayah Potensi Meluas"))
    kiri = (_panel("legend_prakiraan", "Prakiraan Cuaca", prakiraan, "#00aaff", 180)
            + _panel("legend_longsor", "Zona Kerentanan Gerakan Tanah (PVMBG)", longsor, "grey", 210)
            + _panel("legend_banjir", "Zona Kerentanan Banjir", banjir, "#0000FF", 190))
    kanan = (_panel("legend_hujan", "Peringatan Longsor &amp; Banjir", _legenda_hujan(), "grey", 240, tampil=True)
             + _panel("legend_nowcast", "Peringatan Dini Cuaca", nowcast, "darkorange", 210))
    return (f'<div style="{_KOTAK}left:30px;">{kiri}</div>'
            f'<div style="{_KOTAK}right:30px;flex-direction:row-reverse;">{kanan}</div>')


def _banner_html(alarm: list, gagal: list) -> str:
    kartu = []
    if alarm:
        kartu.append(f'<div class="ews-alarm">🚨 <b>PERINGATAN DARURAT:</b> curah hujan ≥ {config.AMBANG_ALARM_MM:.0f} mm '
                     f'selama 3 hari berturut-turut di: <b>{esc(", ".join(alarm))}</b>. '
                     f'Potensi longsor/banjir sangat tinggi!</div>')
    if gagal:
        kartu.append(f'<div class="ews-gagal">⚠ Sumber data bermasalah: {esc(", ".join(gagal))}</div>')
    if not kartu:
        return ""
    return ('<style>@keyframes ewsKedip{0%,100%{opacity:1}50%{opacity:.65}}'
            '.ews-alarm{background:#b71c1c;color:#fff;padding:10px 14px;border-radius:8px;font:13px sans-serif;'
            'box-shadow:0 2px 8px rgba(0,0,0,.5);animation:ewsKedip 1.6s infinite;}'
            '.ews-gagal{background:#fff3cd;color:#664d03;padding:6px 12px;border-radius:8px;font:12px sans-serif;'
            'border:1px solid #ffecb5;box-shadow:0 2px 6px rgba(0,0,0,.3);}</style>'
            '<div style="position:fixed;top:85px;left:60px;max-width:560px;z-index:10000;display:flex;'
            f'flex-direction:column;gap:8px;">{"".join(kartu)}</div>')


_JUDUL = '''
<div style="position:fixed;top:15px;left:60px;z-index:9999;background:rgba(255,255,255,0.95);padding:10px 20px;border-radius:8px;box-shadow:2px 2px 8px rgba(0,0,0,0.4);display:flex;align-items:center;border-left:5px solid #002B5B;pointer-events:auto;">
    <img src="https://www.bmkg.go.id/asset/img/logo/logo-bmkg.png" style="width:45px;margin-right:15px;" alt="BMKG">
    <div>
        <h3 style="margin:0;color:#002B5B;font-size:18px;font-weight:800;font-family:sans-serif;">Stasiun Meteorologi Zainuddin Abdul Madjid Lombok</h3>
        <p style="margin:0;color:#444;font-size:13px;font-family:sans-serif;">Dashboard Peringatan Dini Longsor dan Banjir Nusa Tenggara Barat</p>
    </div>
</div>'''


class LegendToggle(MacroElement):
    """Tampilkan/sembunyikan legenda mengikuti layer yang dicentang di LayerControl."""

    _template = Template("""
    {% macro script(this, kwargs) %}
    (function () {
        var peta = {{ this._parent.get_name() }};
        var peta_legenda = {{ this.mapping_json }};
        function atur(e, tampil) {
            for (var kunci in peta_legenda) {
                if (e.name.indexOf(kunci) !== -1) {
                    var el = document.getElementById(peta_legenda[kunci]);
                    if (el) { el.style.display = tampil ? 'block' : 'none'; }
                }
            }
        }
        peta.on('overlayadd', function (e) { atur(e, true); });
        peta.on('overlayremove', function (e) { atur(e, false); });
    })();
    {% endmacro %}
    """)

    def __init__(self, mapping: dict[str, str]):
        super().__init__()
        self._name = "LegendToggle"
        self.mapping_json = json.dumps(mapping)


# ------------------------------------------------------------------ rakit peta
def build_map(d: MapData) -> folium.Map:
    # prefer_canvas: ribuan poligon digambar di canvas, jauh lebih ringan dari SVG per-poligon.
    m = folium.Map(location=[-8.65, 117.36], zoom_start=8.5, zoom_snap=0.5, tiles=None,
                   attributionControl=False, prefer_canvas=True)

    folium.TileLayer(tiles="https://mt0.google.com/vt/lyrs=m&hl=en&x={x}&y={y}&z={z}", attr=" ",
                     name="Google Maps (Standar)", overlay=False, control=True).add_to(m)
    folium.TileLayer(tiles="https://mt0.google.com/vt/lyrs=y&hl=en&x={x}&y={y}&z={z}", attr=" ",
                     name="Google Satellite (Satelit)", overlay=False, control=True, show=False).add_to(m)

    for nama, uri in d.radar.items():
        label = "PAC12H" if nama == "PAC" else nama
        folium.raster_layers.ImageOverlay(image=uri, bounds=config.BATAS_RADAR_LOMBOK, opacity=0.7,
                                          name=f"📡 Radar SIDARMA ({label})", show=False,
                                          interactive=False, cross_origin=False).add_to(m)

    if d.geo_longsor:
        folium.GeoJson(d.geo_longsor, name=NAMA_LONGSOR, style_function=_style_longsor, show=False,
                       smooth_factor=1.5).add_to(m)
    if d.geo_banjir:
        folium.GeoJson(d.geo_banjir, name=NAMA_BANJIR, style_function=_style_banjir, show=False,
                       smooth_factor=1.5).add_to(m)

    _tambah_stasiun(m, d)
    _layer_prakiraan(d).add_to(m)
    _layer_nowcast(d).add_to(m)

    root = m.get_root().html
    root.add_child(folium.Element(_legenda_html()))
    root.add_child(folium.Element(_JUDUL))
    root.add_child(folium.Element(_banner_html(d.alarm, d.sumber_gagal)))

    m.add_child(LegendToggle({"Peringatan Dini Cuaca": "legend_nowcast", "Gerakan Tanah": "legend_longsor",
                              "Banjir (InaRISK)": "legend_banjir", "Prakiraan Cuaca": "legend_prakiraan"}))
    folium.LayerControl().add_to(m)
    return m
