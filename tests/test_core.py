"""Tes unit logika inti (tanpa Streamlit/Folium/jaringan).  Jalankan:  python -m unittest discover -s tests -v"""
import base64
import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ews import awscenter, config, forecast, history, nowcast, radar, rainfall  # noqa: E402

UTC = timezone.utc


class TestRainfall(unittest.TestCase):
    def test_parse_curah(self):
        self.assertEqual(rainfall.parse_curah("12,5"), 12.5)
        self.assertEqual(rainfall.parse_curah(0), 0.0)
        for rusak in (None, "", "  ", "offline", "OFFLINE", "-1", "abc"):
            self.assertIsNone(rainfall.parse_curah(rusak), rusak)

    def test_batas_kategori_konsisten(self):
        kasus = {0: "Aman", 0.1: "Aman", 20: "Aman", 20.1: "Aman", 49.9: "Aman",
                 50: "WASPADA", 100: "WASPADA", 100.1: "SIAGA", 150: "SIAGA", 150.1: "AWAS"}
        for mm, status in kasus.items():
            self.assertEqual(rainfall.klasifikasi(mm).status, status, mm)
        self.assertEqual(rainfall.klasifikasi(0).kategori, "Cerah / Berawan")
        self.assertEqual(rainfall.klasifikasi(30).kategori, "Hujan Sedang")

    def test_parse_waktu_dan_stale(self):
        w = rainfall.parse_waktu("2026-10-23 08:50:00+00")
        self.assertEqual(w, datetime(2026, 10, 23, 8, 50, tzinfo=UTC))
        self.assertEqual(rainfall.parse_waktu("2026-10-23T16:50:00+08:00"), w)
        self.assertIsNone(rainfall.parse_waktu("bukan tanggal"))
        acuan = datetime(2026, 10, 25, 0, 0, tzinfo=UTC)
        lama = {"tanggal": "2026-10-23 08:50:00+00"}
        baru = {"tanggal": "2026-10-24 22:00:00+00"}
        self.assertTrue(rainfall.is_stale(lama, acuan))
        self.assertFalse(rainfall.is_stale(baru, acuan))
        self.assertFalse(rainfall.is_stale(lama, None))          # tanpa acuan: tidak menuduh
        self.assertFalse(rainfall.is_stale({}, acuan))           # tanpa tanggal: tidak menuduh

    def test_deret_bahaya(self):
        live = [{"id_station": "A", "name_station": "Stasiun A", "curah": "60"},
                {"id_station": "B", "name_station": "Stasiun B", "curah": "60"},
                {"id_station": "C", "name_station": "Stasiun C", "curah": "offline"}]
        h1 = [{"id_station": "A", "curah": "55"}, {"id_station": "B", "curah": "10"}, {"id_station": "C", "curah": "99"}]
        h2 = [{"id_station": "A", "curah": "50"}, {"id_station": "B", "curah": "99"}, {"id_station": "C", "curah": "99"}]
        self.assertEqual(rainfall.deret_bahaya(live, h1, h2), ["Stasiun A"])
        self.assertEqual(rainfall.deret_bahaya(live, [], []), [])   # histori kosong: tidak ada alarm


class FakeResp:
    def __init__(self, payload=None, status=200, content=b"", headers=None, text=""):
        self._p, self.status_code, self.content = payload, status, content
        self.headers, self.text = headers or {}, text

    def json(self):
        if isinstance(self._p, Exception):
            raise self._p
        return self._p

    def raise_for_status(self):
        if self.status_code >= 400:
            import requests
            raise requests.HTTPError(f"HTTP {self.status_code}")


class FakeSession:
    def __init__(self, login_status=200, rows=None):
        self.login_status, self.rows = login_status, rows
        self.posted = None

    def post(self, url, data=None, timeout=None):
        self.posted = data
        return FakeResp(status=self.login_status)

    def get(self, url, timeout=None):
        return FakeResp(self.rows)


class TestAwsCenter(unittest.TestCase):
    def test_gabung_dedupe_dan_filter(self):
        a = [{"id_station": "S1", "nama_kota": "Kab. Bima", "tanggal": "2026-10-25 01:00:00+00", "curah": "1"},
             {"id_station": "X", "nama_kota": "Kota Surabaya"}]
        b = [{"id_station": "S1", "nama_kota": "Kab. Bima", "tanggal": "2026-10-25 02:00:00+00", "curah": "2"},
             {"id_station": "S2", "nama_kota": "Kota Mataram", "tanggal": "2026-10-25 02:00:00+00", "curah": "3"}]
        sesi = iter([FakeSession(rows=a), FakeSession(rows=b)])
        data, errors = awscenter.fetch_stations([config.Akun("11", "x"), config.Akun("22", "y")],
                                                session_factory=lambda: next(sesi))
        self.assertEqual(errors, [])
        self.assertEqual({d["id_station"]: d["curah"] for d in data}, {"S1": "2", "S2": "3"})

    def test_error_tidak_membocorkan_password(self):
        sesi = iter([FakeSession(login_status=500), FakeSession(rows={"pesan": "login gagal"})])
        data, errors = awscenter.fetch_stations([config.Akun("11111", "RAHASIA1"), config.Akun("22222", "RAHASIA2")],
                                                session_factory=lambda: next(sesi))
        self.assertEqual(data, [])
        self.assertEqual(len(errors), 2)
        teks = " ".join(errors) + repr(config.Akun("11111", "RAHASIA1"))
        self.assertNotIn("RAHASIA", teks)
        self.assertNotIn("11111", teks)

    def test_satu_akun_gagal_akun_lain_tetap_jalan(self):
        ok = [{"id_station": "S9", "nama_kota": "Kab. Dompu", "tanggal": "2026-10-25 01:00:00+00"}]
        sesi = iter([FakeSession(login_status=500), FakeSession(rows=ok)])
        data, errors = awscenter.fetch_stations([config.Akun("11", "x"), config.Akun("22", "y")],
                                                session_factory=lambda: next(sesi))
        self.assertEqual(len(data), 1)
        self.assertEqual(len(errors), 1)


class TestHistory(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.h1, self.h2 = Path(self.tmp.name, "h1.json"), Path(self.tmp.name, "h2.json")

    def tearDown(self):
        self.tmp.cleanup()

    def test_data_kosong_tidak_menghapus_histori(self):
        self.h1.write_text(json.dumps([{"id_station": "A"}]))
        self.assertIn("dilewati", history.simpan_dan_geser([], self.h1, self.h2))
        self.assertEqual(json.loads(self.h1.read_text()), [{"id_station": "A"}])
        self.assertFalse(self.h2.exists())

    def test_geser_hari_berbeda(self):
        hari1 = datetime(2026, 10, 24, 23, 47, tzinfo=UTC)
        hari2 = hari1 + timedelta(days=1)
        history.simpan_dan_geser([{"id_station": "A", "curah": "1"}], self.h1, self.h2, hari1)
        history.simpan_dan_geser([{"id_station": "A", "curah": "2"}], self.h1, self.h2, hari2)
        self.assertEqual(history.muat_snapshot(self.h1).data[0]["curah"], "2")
        self.assertEqual(history.muat_snapshot(self.h2).data[0]["curah"], "1")

    def test_jalan_dua_kali_sehari_tidak_menimpa_h2(self):
        t = datetime(2026, 10, 24, 23, 47, tzinfo=UTC)
        self.h2.write_text(json.dumps([{"id_station": "A", "curah": "KEMARIN"}]))
        history.simpan_dan_geser([{"id_station": "A", "curah": "1"}], self.h1, self.h2, t)
        history.simpan_dan_geser([{"id_station": "A", "curah": "2"}], self.h1, self.h2, t + timedelta(hours=2))
        self.assertEqual(history.muat_snapshot(self.h2).data[0]["curah"], "KEMARIN")
        self.assertEqual(history.muat_snapshot(self.h1).data[0]["curah"], "2")

    def test_format_lama_dan_file_rusak(self):
        self.h1.write_text(json.dumps([{"id_station": "A"}]))
        snap = history.muat_snapshot(self.h1)
        self.assertEqual((snap.data, snap.dibuat), ([{"id_station": "A"}], None))
        self.h2.write_text("{rusak")
        self.assertEqual(history.muat_snapshot(self.h2).data, [])
        self.assertEqual(history.muat_snapshot(Path(self.tmp.name, "tidak_ada.json")).data, [])
        # file format lama dianggap 'hari berbeda' -> ikut tergeser, tidak hilang
        history.simpan_dan_geser([{"id_station": "B"}], self.h1, self.h2, datetime(2026, 10, 25, tzinfo=UTC))
        self.assertEqual(history.muat_snapshot(self.h2).data, [{"id_station": "A"}])


class TestForecast(unittest.TestCase):
    ITEM = {"cuaca": [[
        {"local_datetime": "2026-11-23 07:00:00", "weather_desc": "Cerah"},
        {"local_datetime": "2026-11-23 13:00:00", "weather_desc": "Hujan Lebat"},
        {"local_datetime": "2026-11-23 19:00:00", "weather_desc": "Berawan"},
    ], [
        {"local_datetime": "2026-11-24 01:00:00", "weather_desc": "Hujan Ringan"},
        {"local_datetime": "2026-11-24 07:00:00", "weather_desc": "Cerah Berawan"},
    ]]}

    def test_cuaca_sekarang_slot_terdekat(self):
        self.assertEqual(forecast.cuaca_sekarang(self.ITEM, datetime(2026, 11, 23, 12, 0)), "Hujan Lebat")
        self.assertEqual(forecast.cuaca_sekarang({}, datetime(2026, 11, 23, 12, 0)), "Berawan")

    def test_periode_hanya_slot_yang_belum_lewat(self):
        hasil = forecast.prakiraan_periode(self.ITEM, datetime(2026, 11, 23, 14, 0))
        self.assertIn("Hujan Lebat", hasil["Siang Hari"])
        self.assertIn("Berawan", hasil["Malam Hari"])
        self.assertIn("Hujan Ringan", hasil["Dini Hari"])
        self.assertIn("Cerah Berawan", hasil["Pagi Hari"])      # pagi BESOK, bukan pagi tadi yang sudah lewat

    def test_fetch_berhenti_saat_429(self):
        panggilan = []

        def get(url, params=None, headers=None, timeout=None):
            panggilan.append(params["adm4"])
            return FakeResp(status=429)

        self.assertEqual(forecast.fetch_forecasts(("a", "b", "c"), max_workers=1, get=get), [])
        self.assertEqual(len(panggilan), 1)


CAP = """<alert xmlns="urn:oasis:names:tc:emergency:cap:1.2">
 <info><language>id-ID</language><event>Hujan Lebat</event><severity>Moderate</severity>
  <description>Hujan lebat disertai petir.
  Waspada.</description><effective>2026-11-23T10:00:00+08:00</effective><expires>2026-11-23T12:00:00+08:00</expires>
  <area><areaDesc>Lombok Tengah</areaDesc><polygon>-8.6,116.1 -8.7,116.2 -8.6,116.3 -8.6,116.1</polygon></area></info>
 <info><language>en-US</language><event>Heavy Rain</event>
  <area><areaDesc>Central Lombok</areaDesc><polygon>-8.6,116.1 -8.7,116.2 -8.6,116.3</polygon></area></info>
</alert>"""


class TestNowcastRadar(unittest.TestCase):
    def test_parse_cap_hanya_bahasa_indonesia(self):
        hasil = nowcast.parse_cap(CAP)
        self.assertEqual(len(hasil), 1)
        p = hasil[0]
        self.assertEqual((p["event"], p["nama_area"], p["warna"]), ("Hujan Lebat", "Lombok Tengah", "yellow"))
        self.assertEqual(p["coords"][0], (-8.6, 116.1))
        self.assertEqual(len(p["coords"]), 4)

    def test_radar_tidak_dikonfigurasi(self):
        self.assertEqual(radar.fetch_radar(None, None, None), {})

    def test_radar_data_uri_dan_auth(self):
        dipakai = []

        def get(url, auth=None, timeout=None):
            dipakai.append((url, auth))
            if url.endswith("imageStatus_Lombok.json?id=123"):
                return FakeResp({"CMAX": {"Latest": {"file": "img/cmax.png"}}})
            if url.endswith("img/cmax.png"):
                return FakeResp(content=b"\x89PNG", headers={"Content-Type": "image/png"})
            raise AssertionError(url)

        hasil = radar.fetch_radar("http://10.0.0.1/sidarma", "u", "p", get=get)
        self.assertEqual(list(hasil), ["CMAX"])        # PAC tidak ada di JSON -> dilewati
        self.assertEqual(hasil["CMAX"], "data:image/png;base64," + base64.b64encode(b"\x89PNG").decode())
        self.assertTrue(all(a == ("u", "p") for _, a in dipakai))


class TestSecrets(unittest.TestCase):
    def test_akun_dari_environment(self):
        import os
        kunci = ["AWSCENTER_USER", "AWSCENTER_PASS", "AWSCENTER_USER2", "AWSCENTER_PASS2"]
        lama = {k: os.environ.get(k) for k in kunci}
        try:
            os.environ.update({"AWSCENTER_USER": "1", "AWSCENTER_PASS": "a", "AWSCENTER_USER2": "2"})
            os.environ.pop("AWSCENTER_PASS2", None)
            akun = config.muat_akun_awscenter()
            self.assertEqual([a.username for a in akun], ["1"])      # akun 2 tanpa password diabaikan
        finally:
            for k, v in lama.items():
                os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)


if __name__ == "__main__":
    unittest.main()
