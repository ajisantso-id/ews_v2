# Dashboard Peringatan Dini Longsor & Banjir NTB

BMKG Stasiun Meteorologi Zainuddin Abdul Madjid Lombok. Peta interaktif (Streamlit + Folium) yang
menggabungkan curah hujan AWS/ARG (AWS Center), prakiraan cuaca, peringatan dini (nowcast), radar SIDARMA,
serta zona kerentanan gerakan tanah (PVMBG) dan rawan banjir (InaRISK).

## Menjalankan

```bash
pip install -r requirements.txt
cp .streamlit/secrets.toml.example .streamlit/secrets.toml   # lalu isi kredensial
streamlit run app.py
```

## Kredensial (WAJIB baca)

Kredensial **tidak pernah ditulis di kode**. Cukup di dua tempat:

| Tempat | Dipakai oleh | Cara isi |
|---|---|---|
| Streamlit Cloud -> *App settings -> Secrets* (atau `.streamlit/secrets.toml` lokal) | Dashboard | lihat `secrets.toml.example` |
| GitHub -> *Settings -> Secrets and variables -> Actions* | Robot harian | `AWSCENTER_USER`, `AWSCENTER_PASS`, `AWSCENTER_USER2`, `AWSCENTER_PASS2` |

Nama secret sama dengan versi lama, jadi secret yang sudah ada tetap berlaku.

## Struktur

```
app.py                  UI Streamlit (CSS layar penuh, bar waktu, tombol H-2/H-1/Hari Ini, tabel)
ews/
  config.py             semua konstanta, daftar lokasi, pembaca secrets
  rainfall.py           parsing curah, kategori (SATU sumber kebenaran), data basi, alarm 3 hari
  awscenter.py          login + tarik data AWS Center (dipakai dashboard & robot)
  history.py            snapshot H-1/H-2 (atomik, aman dari tarikan gagal)
  forecast.py           prakiraan BMKG (paralel) + helper popup
  nowcast.py            peringatan dini CAP
  radar.py              radar SIDARMA (disematkan sebagai gambar base64)
  mapview.py            seluruh pembuatan peta Folium
scripts/update_data.py  robot harian (GitHub Actions)
scripts/simplify_geojson.py  memperkecil GeoJSON (tanpa dependensi)
tests/test_core.py      tes unit:  python -m unittest discover -s tests -v
```

## Robot harian

`.github/workflows/jadwal_hujan.yml` jalan tiap 07:47 WITA: menarik data, menyimpan sebagai `data_h1.json`,
dan menggeser H-1 lama ke `data_h2.json`. Bila tarikan gagal, workflow **merah** dan histori lama dibiarkan utuh.

## Memperkecil GeoJSON

```bash
python scripts/simplify_geojson.py zona_longsor.geojson --keep REMARK
python scripts/simplify_geojson.py banjir_ntb.geojson --keep DN --where DN=1
```

Hasil `*.min.geojson` otomatis dipakai dashboard bila ada (file asli tidak diubah).

## Aturan kategori & alarm

| Curah 24 jam | Kategori | Status |
|---|---|---|
| 0 | Cerah / Berawan | Aman |
| 0.1 - 20 | Hujan Ringan | Aman |
| 20 - <50 | Hujan Sedang | Aman |
| 50 - 100 | Hujan Lebat | WASPADA |
| >100 - 150 | Hujan Sangat Lebat | SIAGA |
| >150 | Hujan Ekstrem | AWAS |

* **Alarm darurat**: curah >= 50 mm pada hari ini, H-1, dan H-2 sekaligus (ambang di `config.AMBANG_ALARM_MM`).
* **Data lama**: stasiun yang terakhir mengirim data > 6 jam (`config.STALE_JAM`) ditandai abu-abu dan tidak
  ikut alarm, supaya angka 0 mm yang sebenarnya sudah basi tidak tampil sebagai "cerah".
