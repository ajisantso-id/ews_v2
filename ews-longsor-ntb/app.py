"""Dashboard Peringatan Dini Longsor & Banjir NTB - BMKG Stasiun Meteorologi ZAM Lombok.

Jalankan:  streamlit run app.py
Kredensial dibaca dari st.secrets / environment (lihat .streamlit/secrets.toml.example).
"""
import json
import logging
from datetime import datetime, timezone

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components
from streamlit_autorefresh import st_autorefresh
from streamlit_folium import st_folium

from ews import awscenter, config, forecast, history, nowcast, radar, rainfall
from ews.mapview import MapData, build_map

log = logging.getLogger("ews")

st.set_page_config(
    page_title="Dashboard Peringatan Dini Longsor dan Banjir NTB",
    page_icon="https://www.bmkg.go.id/asset/img/logo/logo-bmkg.png",
    layout="wide",
)

# Mode TV: halaman refresh otomatis tiap 5 menit.
st_autorefresh(interval=config.AUTO_REFRESH_MS, limit=None, key="auto_refresh_bmkg")

HARI = ("SENIN", "SELASA", "RABU", "KAMIS", "JUMAT", "SABTU", "MINGGU")
BULAN = ("JANUARI", "FEBRUARI", "MARET", "APRIL", "MEI", "JUNI", "JULI", "AGUSTUS",
         "SEPTEMBER", "OKTOBER", "NOVEMBER", "DESEMBER")

CSS = """
<style>
    /* Layar penuh ala command center */
    .appview-container .main .block-container,
    [data-testid="stMainBlockContainer"], .block-container {
        padding: 0 !important; margin: 0 !important; max-width: 100% !important; overflow: hidden !important;
    }
    header, [data-testid="stToolbar"], footer { display: none !important; }

    .top-time-bar {
        position: fixed; top: 0; left: 0; width: 100%; height: 28px; background: #fff;
        border-bottom: 1px solid #e0e0e0; z-index: 999999; display: flex; justify-content: space-between;
        align-items: center; padding: 0 30px; font-size: 11px; color: #0056b3; font-weight: bold;
        letter-spacing: .5px; box-sizing: border-box;
    }
    .top-time-bar .tengah { color: #555; font-weight: normal; }

    /* Peta dipaku memenuhi monitor, di belakang tombol */
    iframe[title="streamlit_folium.st_folium"] {
        position: fixed !important; top: 28px !important; left: 0 !important; width: 100vw !important;
        height: calc(100vh - 28px) !important; border: none !important; z-index: 1 !important;
    }

    /* Panel tombol melayang */
    div[data-testid="stHorizontalBlock"]:has(.jangkar-tombol) {
        position: fixed; bottom: 25px; left: 50%; transform: translateX(-50%); z-index: 99999;
        background: rgba(255,255,255,.95); padding: 10px 15px; border-radius: 12px;
        box-shadow: 0 4px 15px rgba(0,0,0,.5); border: 2px solid #002B5B; width: max-content; gap: 10px;
    }
    div[data-testid="stHorizontalBlock"]:has(.jangkar-tombol) > div { width: auto !important; flex: none !important; }
</style>
"""
st.markdown(CSS, unsafe_allow_html=True)


# ------------------------------------------------------------------ pengambilan data (di-cache)
# Fungsi di bawah MELEMPAR exception bila gagal/kosong -> Streamlit tidak men-cache kegagalan,
# jadi percobaan berikutnya langsung mencoba lagi (tanpa st.cache_data.clear() yang menghapus semuanya).
@st.cache_data(ttl=config.TTL_LIVE, show_spinner=False)
def _data_live():
    akun = config.muat_akun_awscenter()
    if not akun:
        raise RuntimeError("kredensial AWS Center belum diatur di secrets")
    data, errors = awscenter.fetch_stations(akun)
    if not data:
        raise RuntimeError("; ".join(errors) or "data kosong")
    return data, errors, datetime.now(timezone.utc)


@st.cache_data(ttl=config.TTL_PRAKIRAAN, show_spinner=False)
def _data_prakiraan():
    data = forecast.fetch_forecasts()
    if not data:
        raise RuntimeError("prakiraan kosong")
    return data


@st.cache_data(ttl=config.TTL_NOWCAST, show_spinner=False)
def _data_nowcast():
    return nowcast.fetch_nowcast()


@st.cache_data(ttl=config.TTL_RADAR, show_spinner=False)
def _data_radar():
    return radar.fetch_radar(config.get_secret("SIDARMA_BASE_URL"),
                             config.get_secret("SIDARMA_USER"), config.get_secret("SIDARMA_PASS"))


@st.cache_resource(show_spinner=False)
def _geojson(path: str, hanya_dn1: bool = False):
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if hanya_dn1:  # poligon banjir DN=0 tidak pernah digambar; buang agar peta lebih ringan
        data["features"] = [x for x in data["features"] if int(float(x["properties"].get("DN", 0))) == 1]
    return data


def _coba(fungsi, nama: str, gagal: list, default):
    try:
        return fungsi()
    except Exception as e:  # noqa: BLE001
        log.warning("%s gagal: %s: %s", nama, type(e).__name__, e)
        gagal.append(nama)
        return default


# ------------------------------------------------------------------ mesin waktu (Hari Ini / H-1 / H-2)
if "offset_hari" not in st.session_state:
    st.session_state.offset_hari = 0


def set_hari(offset: int):
    st.session_state.offset_hari = offset


offset = st.session_state.offset_hari
gagal: list[str] = []
acuan = None          # waktu acuan umur data stasiun (UTC)
label_data = "REAL-TIME"

if offset == 0:
    live = _coba(_data_live, "AWS Center", gagal, None)
    if live:
        data_sensor, errs, acuan = live
        if errs:
            gagal.append(f"AWS Center ({len(errs)} akun gagal)")
    else:
        data_sensor = []
else:
    snap = history.muat_snapshot(config.H1_FILE if offset == 1 else config.H2_FILE)
    data_sensor, acuan = snap.data, snap.dibuat
    if not data_sensor:
        st.warning(f"⚠️ Data histori H-{offset} belum tersedia (robot GitHub belum menarik datanya).")
    label_data = f"H-{offset}" + (f" (diambil {snap.dibuat.astimezone(config.WITA):%d/%m %H:%M} WITA)" if snap.dibuat else "")

# Alarm 3 hari berturut-turut: hanya bermakna pada mode Hari Ini, dan stasiun yang tidak update diabaikan.
alarm: list[str] = []
if offset == 0 and data_sensor:
    segar = [i for i in data_sensor if not rainfall.is_stale(i, acuan)]
    alarm = rainfall.deret_bahaya(segar, history.muat_snapshot(config.H1_FILE).data,
                                  history.muat_snapshot(config.H2_FILE).data)

prakiraan = _coba(_data_prakiraan, "Prakiraan BMKG", gagal, [])
nowcast_data = _coba(_data_nowcast, "Peringatan Dini", gagal, []) if offset == 0 else []
sidarma_aktif = bool(config.get_secret("SIDARMA_BASE_URL"))
radar_data = _coba(_data_radar, "Radar SIDARMA", gagal, {}) if sidarma_aktif else {}

# ------------------------------------------------------------------ bar waktu
utc_now = datetime.now(timezone.utc)
wita_now = utc_now.astimezone(config.WITA)
tanggal_str = f"{HARI[wita_now.weekday()]}, {wita_now.day:02d} {BULAN[wita_now.month - 1]} {wita_now.year}"
st.markdown(
    f"""<div class="top-time-bar">
        <div>{tanggal_str}</div>
        <div class="tengah">DATA: {label_data}</div>
        <div id="jam-live">{wita_now:%H:%M:%S} WITA &nbsp;|&nbsp; {utc_now:%H:%M:%S} UTC</div>
    </div>""", unsafe_allow_html=True)

# Jam berdetik tiap detik di sisi browser (WITA = UTC+8).
components.html("""
<script>
setInterval(function () {
    var p = function (n) { return String(n).padStart(2, '0'); };
    var u = new Date(), w = new Date(u.getTime() + 8 * 3600 * 1000);
    var el = window.parent.document.getElementById('jam-live');
    if (el) {
        el.innerHTML = p(w.getUTCHours()) + ':' + p(w.getUTCMinutes()) + ':' + p(w.getUTCSeconds()) + ' WITA &nbsp;|&nbsp; '
                     + p(u.getUTCHours()) + ':' + p(u.getUTCMinutes()) + ':' + p(u.getUTCSeconds()) + ' UTC';
    }
}, 1000);
</script>""", height=0, width=0)


# ------------------------------------------------------------------ pop-up tabel
@st.dialog("📋 Tabel Detail Monitoring AWS/ARG", width="large")
def tampilkan_tabel(stasiun: list, acuan_waktu):
    if not stasiun:
        st.warning("Data API masih kosong / belum ketarik.")
        return
    baris = []
    for i in stasiun:
        mm = rainfall.parse_curah(i.get("curah"))
        if mm is None:
            kategori, status = "-", "⚪ Offline"
        elif rainfall.is_stale(i, acuan_waktu):
            kategori, status = "-", "⚪ Data lama"
        else:
            lv = rainfall.klasifikasi(mm)
            kategori, status = lv.kategori, f"{lv.ikon} {lv.status}"
        baris.append({"Stasiun": i.get("name_station"), "Kab/Kota": i.get("nama_kota"),
                      "Hujan (mm)": mm, "Intensitas": kategori, "Status Area": status,
                      "Update Terakhir (UTC)": i.get("tanggal")})
    df = pd.DataFrame(baris).sort_values("Hujan (mm)", ascending=False, na_position="last")
    gaya = (df.style.set_properties(subset=["Kab/Kota", "Hujan (mm)", "Intensitas", "Status Area"],
                                    **{"text-align": "center"})
            .set_table_styles([{"selector": "th", "props": [("text-align", "center")]}])
            .format({"Hujan (mm)": "{:.1f}"}, na_rep="-"))
    try:
        st.dataframe(gaya, width="stretch", hide_index=True)
    except TypeError:  # Streamlit versi lama
        st.dataframe(gaya, use_container_width=True, hide_index=True)


# ------------------------------------------------------------------ peta
peta = build_map(MapData(
    stasiun=data_sensor,
    sekarang_wita=wita_now.replace(tzinfo=None),
    acuan=acuan,
    prakiraan=prakiraan,
    nowcast=nowcast_data,
    radar=radar_data,
    geo_longsor=_coba(lambda: _geojson(str(config.GEOJSON_LONGSOR)), "Zona Longsor", gagal, None),
    geo_banjir=_coba(lambda: _geojson(str(config.GEOJSON_BANJIR), True), "Zona Banjir", gagal, None),
    alarm=alarm,
    sumber_gagal=gagal,
))
st_folium(peta, height=900, width="100%", returned_objects=[])

# ------------------------------------------------------------------ panel tombol melayang
col_dl, col_h2, col_h1, col_h0, col_tab = st.columns(5)
with col_dl:
    st.download_button("📥 Download Peta", data=peta.get_root().render().encode("utf-8"),
                       file_name="Peta_EWS_NTB_Terbaru.html", mime="text/html")
with col_h2:
    st.button("⏮️ H-2", on_click=set_hari, args=(2,))
with col_h1:
    st.button("⏪ H-1", on_click=set_hari, args=(1,))
with col_h0:
    st.button("✅ Hari Ini", on_click=set_hari, args=(0,))
with col_tab:
    if st.button("📋 Tabel Data"):
        tampilkan_tabel(data_sensor, acuan)
    # Jangkar: CSS memakai ini untuk menerbangkan satu baris tombol ke bawah layar.
    st.markdown('<span class="jangkar-tombol"></span>', unsafe_allow_html=True)
