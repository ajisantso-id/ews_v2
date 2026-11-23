"""Robot harian: tarik data hujan AWS Center -> data_h1.json (H-1), geser yang lama ke data_h2.json.

Dijalankan GitHub Actions (lihat .github/workflows/jadwal_hujan.yml).
Kredensial dari environment: AWSCENTER_USER/PASS, AWSCENTER_USER2/PASS2 (GitHub Secrets).
Exit code != 0 bila tarikan gagal, sehingga kegagalan terlihat merah di tab Actions.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ews import awscenter, config, history  # noqa: E402


def main() -> int:
    akun = config.muat_akun_awscenter()
    if not akun:
        print("GAGAL: tidak ada kredensial AWSCENTER_USER/AWSCENTER_PASS di environment.")
        return 2

    data, errors = awscenter.fetch_stations(akun)
    for e in errors:
        print(f"PERINGATAN: {e}")
    print(f"Berhasil menarik {len(data)} stasiun NTB dari {len(akun) - len(errors)}/{len(akun)} akun.")

    if not data:
        print("GAGAL: data NTB kosong. Histori lama TIDAK diubah.")
        return 1

    print(history.simpan_dan_geser(data))
    return 0


if __name__ == "__main__":
    sys.exit(main())
