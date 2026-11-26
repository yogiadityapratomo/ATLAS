r"""
load_legacy_dbbackup.py — KHUSUS DEV LOKAL.

Mengisi database `dbbackup` di PostgreSQL LOKAL memakai loader production apa adanya
(`convert_policy_cache_autoupdatedb.py`, termasuk perilaku/bug-nya), supaya data DEV
identik dengan production. Yang diubah hanya tujuan koneksi (dipaksa ke localhost)
dan folder kerja (sementara, supaya CSV legacy tidak menumpuk di folder lain).

Password diambil dari env PGPASSWORD; skrip menolak jalan jika host bukan localhost.

Contoh (PowerShell):
    $env:PGPASSWORD = (Get-Content "$env:USERPROFILE\.atlas\pg_postgres_password.txt" -Raw).Trim()
    .venv\Scripts\python.exe scripts\dev\load_legacy_dbbackup.py
"""
import argparse
import importlib.util
import os
import shutil
import sys
import tempfile

import psycopg2

LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}


def main():
    p = argparse.ArgumentParser(description="Isi dbbackup LOKAL dengan loader legacy (DEV only).")
    p.add_argument("--legacy", default=r"D:\bot\NetbackupBotV2\convert_policy_cache_autoupdatedb.py")
    p.add_argument("--cache", default=r"D:\bot\NetbackupBotV2\cache\policy_cache.json")
    p.add_argument("--host", default="localhost")
    p.add_argument("--port", type=int, default=5432)
    p.add_argument("--dbname", default="dbbackup")
    p.add_argument("--user", default="postgres")
    args = p.parse_args()

    sys.stdout.reconfigure(encoding="utf-8")  # loader legacy mencetak emoji

    if args.host not in LOCAL_HOSTS:
        sys.exit(f"DITOLAK: host '{args.host}' bukan localhost. Skrip ini hanya untuk DEV lokal.")
    password = os.environ.get("PGPASSWORD")
    if not password:
        sys.exit("PGPASSWORD belum di-set.")
    for f in (args.legacy, args.cache):
        if not os.path.exists(f):
            sys.exit(f"File tidak ditemukan: {f}")

    real_connect = psycopg2.connect

    def local_connect(*_a, **_kw):  # abaikan host/password yang tertulis di loader legacy
        return real_connect(host=args.host, port=args.port, dbname=args.dbname,
                            user=args.user, password=password)

    # Seed baris kontrol id=1 jika belum ada (DB lokal hanya berisi struktur).
    with local_connect() as conn, conn.cursor() as cur:
        cur.execute("INSERT INTO backup_inventory_control (id, active_table) "
                    "VALUES (1, 'backup_inventory_a') ON CONFLICT (id) DO NOTHING")

    psycopg2.connect = local_connect

    work = tempfile.mkdtemp(prefix="dbbackup_load_")
    try:
        os.makedirs(os.path.join(work, "cache"))
        shutil.copy2(args.cache, os.path.join(work, "cache", "policy_cache.json"))
        os.chdir(work)

        spec = importlib.util.spec_from_file_location("legacy_loader", args.legacy)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        mod.convert_policy_cache()
    finally:
        os.chdir(os.path.dirname(os.path.abspath(__file__)))
        shutil.rmtree(work, ignore_errors=True)
        psycopg2.connect = real_connect

    with real_connect(host=args.host, port=args.port, dbname=args.dbname,
                      user=args.user, password=password) as conn, conn.cursor() as cur:
        cur.execute("SELECT active_table FROM backup_inventory_control WHERE id = 1")
        active = cur.fetchone()[0]
        cur.execute("SELECT count(*), count(DISTINCT client_host), count(DISTINCT policy_name), "
                    "count(DISTINCT master_server) FROM backup_inventory")
        rows, hosts, pols, masters = cur.fetchone()
    print(f"\nSELESAI. View backup_inventory -> {active}: {rows} baris, "
          f"{hosts} hostname, {pols} policy, {masters} master.")


if __name__ == "__main__":
    main()
