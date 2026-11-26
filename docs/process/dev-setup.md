# Setup Environment DEV Lokal (Laptop)

Bagian dari [deployment-workflow.md](deployment-workflow.md) §1 (environment DEV). Semua komponen berjalan di laptop dan tidak menyentuh server production.

## Prasyarat terpasang

| Komponen | Versi | Cara pasang | Catatan |
|---|---|---|---|
| Git | 2.56.1 | `winget install --id Git.Git -e` | Identitas commit diset per repo (noreply GitHub), bukan global |
| Python | 3.13.x | (sudah ada) | Sama dengan server bot (Python 3.13) |
| PostgreSQL | **18.7** | `winget install --id PostgreSQL.PostgreSQL.18 -e` (mode unattended, tanpa Stack Builder) | Versi mayor sama dengan server `dbbackup` (PostgreSQL 18) |

## Konfigurasi PostgreSQL DEV

| Item | Nilai |
|---|---|
| Service | `postgresql-x64-18` (Automatic) |
| Port | 5432 |
| `listen_addresses` | `localhost` (diset lewat `ALTER SYSTEM`, berlaku setelah restart service) → hanya `127.0.0.1` dan `::1` |
| `pg_hba.conf` | Hanya `127.0.0.1/32` dan `::1/128`, `scram-sha-256` (default installer) |
| Firewall | Tidak ada aturan masuk untuk PostgreSQL |
| Superuser | `postgres`; password acak 24 karakter di `%USERPROFILE%\.atlas\pg_postgres_password.txt` (izin hanya untuk akun Windows pemilik; **tidak** di repo) |
| psql | `"C:\Program Files\PostgreSQL\18\bin\psql.exe"` |

Contoh koneksi tanpa mengetik password di layar:

```powershell
$env:PGPASSWORD = (Get-Content "$env:USERPROFILE\.atlas\pg_postgres_password.txt" -Raw).Trim()
& "C:\Program Files\PostgreSQL\18\bin\psql.exe" -h localhost -U postgres
Remove-Item Env:PGPASSWORD
```

## Aturan DEV

- Aplikasi **tidak** memakai superuser `postgres`. Database dan role aplikasi (least privilege) dibuat di Fase 2/3 setelah design disetujui.
- Data production tidak disalin mentah ke DEV. Gunakan data sintetis, mock NBU, atau salinan cache yang sudah disetujui (guide §10).
- Bot Telegram di DEV memakai token bot uji, bukan token produksi.

## Database DEV (per 2026-11-26)

| Database | Isi | Cara mengisi ulang |
|---|---|---|
| `atlas` | Kosong (schema dibuat lewat migrasi setelah design Fase 2 disetujui). Collation `builtin C.UTF-8`, timezone `Asia/Jakarta` | — |
| `dbbackup` | Struktur = production (dari `pg_inventory`), collation `English_United States.1252` | lihat di bawah |
| `dbbackup.backup_inventory_*` | Diisi loader legacy production apa adanya (termasuk bug `day_map`) dari salinan `policy_cache.json` | `.venv\Scripts\python.exe scripts\dev\load_legacy_dbbackup.py` |
| `dbbackup.server_inventory` | Dari Excel OSPLA sheet `Master Inventory` (asumsi: sumber import manual production) | `.venv\Scripts\python.exe scripts\dev\load_server_inventory_xlsx.py --xlsx "<path xlsx>"` |

Kedua skrip menolak berjalan jika host bukan localhost dan membaca password dari `PGPASSWORD`.
Catatan: data ini berasal dari production (termasuk nama PIC di CMDB) — hanya untuk laptop DEV, jangan dibagikan atau di-commit.

## Web dashboard (DEV)

```powershell
# sekali saja: venv di root repo
python -m venv .venv
.venv\Scripts\pip install -r web\requirements.txt pandas psycopg2-binary

# jalankan (hanya bisa diakses dari laptop ini)
powershell -ExecutionPolicy Bypass -File web\run_dev.ps1
# buka http://127.0.0.1:8000
```

- `web/.env` dibuat otomatis dari `web/.env.example` dengan `ATLAS_ALLOW_LIVE_NBU=0` → `POST /api/generate` ditolak (403), dashboard memakai cache.
- Token NBU dibaca dari `web/.env` (`NBU_TBS_TOKEN`, dst.), tidak lagi tertulis di kode.

## Belum disiapkan

- Role aplikasi ATLAS (`atlas_owner`, `atlas_migrator`, `atlas_app`, `atlas_readonly`) dan migrasi schema — Fase 2/3.
- Bot Telegram uji + mock NBU untuk menjalankan semua komponen sekaligus.
