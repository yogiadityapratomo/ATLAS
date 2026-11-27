r"""seed_capacity_history.py — isi riwayat kapasitas CONTOH (dummy) untuk menu Historical Capacity. KHUSUS DEV.

Memakai daftar disk pool asli (snapshot terbaru) lalu membangkitkan riwayat harian mundur N hari yang
berakhir tepat di nilai sekarang: tren naik + pola mingguan + derau, hari pembersihan (expired image),
dan penambahan kapasitas (expansion) saat pool hampir penuh. Semua baris bertanda source='demo':
  * tidak pernah menimpa data asli (ON CONFLICT DO NOTHING; data 'collect' selalu menang),
  * UI menampilkan label "berisi data contoh",
  * dihapus dengan --purge.

    .venv\Scripts\python.exe scripts\dev\seed_capacity_history.py --days 730
    .venv\Scripts\python.exe scripts\dev\seed_capacity_history.py --purge
"""

from __future__ import annotations

import argparse
import math
import random
import sys
from datetime import date, timedelta
from pathlib import Path

import psycopg

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from atlas.core.config import load_settings  # noqa: E402

COLUMNS = (
    "day, site, master, disk_pool_name, usable_tb, available_tb, used_tb, usage_pct,"
    " max_used_tb, max_usage_pct, samples, source"
)


def simulate(pool: tuple, days: int, end: date, rng: random.Random) -> list[tuple]:
    site, master, name, usable_now, used_now = pool
    usable_now, used_now = float(usable_now), float(used_now)
    if usable_now <= 0:
        return []
    # riwayat dibangun MUNDUR dari kondisi sekarang agar titik terakhir = nilai dashboard hari ini
    daily_growth = rng.uniform(0.0004, 0.0022) * usable_now  # TB/hari
    rows = []
    used, usable = used_now, usable_now
    for offset in range(1, days + 1):
        day = end - timedelta(days=offset)
        weekly = math.sin(2 * math.pi * day.weekday() / 7) * 0.004 * usable  # full backup akhir pekan
        noise = rng.gauss(0, 0.002) * usable
        used = used - daily_growth - noise
        if rng.random() < 0.015:  # hari pembersihan di masa lalu → mundur ke sebelum pembersihan = lebih penuh
            used += rng.uniform(0.02, 0.06) * usable
        # mundur melewati expansion → kapasitas lebih kecil; used tidak berubah (expansion hanya menambah ruang).
        # Tidak dalam 60 hari terakhir agar riwayat bersambung mulus dengan data asli.
        factor = rng.choice((1.25, 1.5))
        if offset > 60 and rng.random() < 0.004 and used / (usable / factor) < 0.9:
            usable = round(usable / factor, 2)
        used = min(max(used, 0.05 * usable), 0.97 * usable)
        shown = max(min(used + weekly, 0.98 * usable), 0.0)
        peak = min(shown * rng.uniform(1.0, 1.03), 0.99 * usable)
        rows.append(
            (
                day,
                site,
                master,
                name,
                round(usable, 2),
                round(usable - shown, 2),
                round(shown, 2),
                round(shown / usable * 100, 2),
                round(peak, 2),
                round(peak / usable * 100, 2),
                144,
                "demo",
            )
        )
    return rows


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Isi / hapus riwayat kapasitas contoh (DEV).")
    parser.add_argument("--days", type=int, default=730)
    parser.add_argument("--seed", type=int, default=20261127)
    parser.add_argument("--purge", action="store_true", help="Hapus semua baris source='demo'")
    args = parser.parse_args()

    settings = load_settings()
    if settings.env == "prod":
        print("DITOLAK: data contoh tidak boleh diisi di prod.")
        return 2
    with psycopg.connect(settings.db_conninfo("app", "atlas-seed-history")) as conn:
        if args.purge:
            n = conn.execute("DELETE FROM capacity.disk_pool_daily WHERE source = 'demo'").rowcount
            print(f"Dihapus {n} baris data contoh.")
            return 0
        pools = conn.execute(
            "SELECT site, master, disk_pool_name, usable_tb, used_tb FROM capacity.disk_pool_latest"
            " ORDER BY master, disk_pool_name"
        ).fetchall()
        if not pools:
            print("Belum ada snapshot kapasitas; jalankan capacity_job dulu.")
            return 1
        first_real = conn.execute(
            "SELECT coalesce(min(day), current_date + 1) FROM capacity.disk_pool_daily WHERE source = 'collect'"
        ).fetchone()[0]
        rng = random.Random(args.seed)
        rows = [r for pool in pools for r in simulate(pool, args.days, first_real, rng)]
        conn.execute(
            "CREATE TEMP TABLE seed_daily (LIKE capacity.disk_pool_daily INCLUDING DEFAULTS) ON COMMIT DROP"
        )
        with conn.cursor() as cur, cur.copy(f"COPY seed_daily ({COLUMNS}) FROM STDIN") as copy:
            for row in rows:
                copy.write_row(row)
        inserted = conn.execute(
            f"INSERT INTO capacity.disk_pool_daily ({COLUMNS}) SELECT {COLUMNS} FROM seed_daily"  # noqa: S608
            " ON CONFLICT (master, disk_pool_name, day) DO NOTHING"
        ).rowcount
    print(
        f"Data contoh: {inserted} baris ({len(pools)} disk pool × {args.days} hari, "
        f"s.d. {first_real - timedelta(days=1)}); data asli mulai {first_real} tidak disentuh."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
