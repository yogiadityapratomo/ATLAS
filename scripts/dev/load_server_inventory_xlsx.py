r"""
load_server_inventory_xlsx.py — KHUSUS DEV LOKAL.

Mengisi `dbbackup.public.server_inventory` di PostgreSQL LOKAL dari Excel OSPLA
(sheet 'Master Inventory'), meniru import manual yang dulu dilakukan di production.
Tabel dikosongkan dulu (TRUNCATE ... RESTART IDENTITY) lalu diisi ulang dalam satu transaksi.

Contoh (PowerShell):
    $env:PGPASSWORD = (Get-Content "$env:USERPROFILE\.atlas\pg_postgres_password.txt" -Raw).Trim()
    .venv\Scripts\python.exe scripts\dev\load_server_inventory_xlsx.py --xlsx "C:\...\OSPLA Managed Server-03022026.xlsx"
"""
import argparse
import os
import sys

import psycopg2
from openpyxl import load_workbook
from psycopg2.extras import execute_values

LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}
# kolom Excel -> kolom tabel
COLUMN_MAP = {
    "Name": "hostname",
    "IP OAM": "ip_oam",
    "IP Service": "ip_service",
    "Apps": "apps_invent_ospla",
    "PIC": "pic",
    "Apps Priority": "apps_priority",
    "Prod/Nonprod": "prod_nonprod",
    "VM/Baremetal": "vm_baremetal",
    "Site": "site",
}


def clean(v):
    if v is None:
        return None
    s = str(v).strip()
    return s or None


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--xlsx", required=True)
    p.add_argument("--sheet", default="Master Inventory")
    p.add_argument("--host", default="localhost")
    p.add_argument("--port", type=int, default=5432)
    p.add_argument("--dbname", default="dbbackup")
    p.add_argument("--user", default="postgres")
    args = p.parse_args()

    if args.host not in LOCAL_HOSTS:
        sys.exit(f"DITOLAK: host '{args.host}' bukan localhost. Skrip ini hanya untuk DEV lokal.")
    password = os.environ.get("PGPASSWORD")
    if not password:
        sys.exit("PGPASSWORD belum di-set.")

    wb = load_workbook(args.xlsx, read_only=True, data_only=True)
    ws = wb[args.sheet]
    rows = ws.iter_rows(values_only=True)
    header = [str(h).strip() if h is not None else "" for h in next(rows)]
    missing = [c for c in COLUMN_MAP if c not in header]
    if missing:
        sys.exit(f"Kolom tidak ditemukan di sheet '{args.sheet}': {missing}")
    idx = {c: header.index(c) for c in COLUMN_MAP}

    records, skipped = [], 0
    for r in rows:
        rec = tuple(clean(r[idx[c]]) if idx[c] < len(r) else None for c in COLUMN_MAP)
        if not rec[0]:  # tanpa hostname -> lewati
            skipped += 1
            continue
        records.append(rec)
    wb.close()

    cols = ", ".join(COLUMN_MAP.values())
    with psycopg2.connect(host=args.host, port=args.port, dbname=args.dbname,
                          user=args.user, password=password) as conn, conn.cursor() as cur:
        cur.execute("TRUNCATE TABLE server_inventory RESTART IDENTITY")
        execute_values(cur, f"INSERT INTO server_inventory ({cols}) VALUES %s", records, page_size=1000)
        cur.execute("SELECT count(*), count(DISTINCT lower(hostname)) FROM server_inventory")
        total, distinct_hosts = cur.fetchone()
        cur.execute("""SELECT count(DISTINCT lower(b.client_host)),
                              count(DISTINCT lower(b.client_host)) FILTER (WHERE s.hostname IS NOT NULL)
                       FROM backup_inventory b
                       LEFT JOIN server_inventory s ON lower(s.hostname) = lower(b.client_host)""")
        bi_hosts, matched = cur.fetchone()

    print(f"Diimpor: {total} baris ({distinct_hosts} hostname unik, {total - distinct_hosts} duplikat); "
          f"dilewati tanpa hostname: {skipped}")
    print(f"Kecocokan dengan backup_inventory: {matched} dari {bi_hosts} client_host ditemukan di CMDB")


if __name__ == "__main__":
    main()
