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

- Aplikasi **tidak** memakai superuser `postgres`. Superuser hanya dipakai `scripts/db/bootstrap.py` (membuat role & database). Aplikasi, job, dan test memakai role least privilege di bawah.
- Data production tidak disalin mentah ke DEV. Gunakan data sintetis, mock NBU, atau salinan cache yang sudah disetujui (guide §10).
- Bot Telegram di DEV memakai token bot uji, bukan token produksi.

## Database DEV (per 2026-11-26)

| Database | Isi | Cara mengisi ulang |
|---|---|---|
| `atlas` | Schema V001 (core, audit, cmdb, report) + CMDB dari Excel OSPLA 2026-02-03 (14.185 baris sumber, 13.903 unik). Collation `builtin C.UTF-8`, timezone `Asia/Jakarta`, owner `atlas_owner` | lihat "Database ATLAS" |
| `atlas_test` | Khusus test integrasi; dihapus & dimigrasi ulang otomatis oleh `pytest` | — |
| `dbbackup` | Struktur = production (dari `pg_inventory`), collation `English_United States.1252` | lihat di bawah |
| `dbbackup.backup_inventory_*` | Diisi loader legacy production apa adanya (termasuk bug `day_map`) dari salinan `policy_cache.json` | `.venv\Scripts\python.exe scripts\dev\load_legacy_dbbackup.py` |
| `dbbackup.server_inventory` | Dari Excel OSPLA sheet `Master Inventory` (asumsi: sumber import manual production) | `.venv\Scripts\python.exe scripts\dev\load_server_inventory_xlsx.py --xlsx "<path xlsx>"` |

Kedua skrip menolak berjalan jika host bukan localhost dan membaca password dari `PGPASSWORD`.
Catatan: data ini berasal dari production (termasuk nama PIC di CMDB) — hanya untuk laptop DEV, jangan dibagikan atau di-commit.

## Web dashboard (DEV)

```powershell
# sekali saja: venv di root repo
python -m venv .venv
.venv\Scripts\pip install -r legacy\web-v4\requirements.txt pandas psycopg2-binary

# jalankan (hanya bisa diakses dari laptop ini)
powershell -ExecutionPolicy Bypass -File legacy\web-v4\run_dev.ps1
# buka http://127.0.0.1:8000
```

- `legacy/web-v4/.env` dibuat otomatis dari `legacy/web-v4/.env.example` dengan `ATLAS_ALLOW_LIVE_NBU=0` → `POST /api/generate` ditolak (403), dashboard memakai cache.
- Token NBU dibaca dari `legacy/web-v4/.env` (`NBU_TBS_TOKEN`, dst.), tidak lagi tertulis di kode.

## Paket `atlas` (aplikasi baru) — test & lint

```powershell
# sekali saja: pasang paket atlas (editable) + alat dev ke venv root
.venv\Scripts\pip install -e ".[dev]"

# konfigurasi: .env di root (JANGAN di-commit) — dibuat otomatis oleh bootstrap di bawah

# lint & format
.venv\Scripts\python.exe -m ruff check .
.venv\Scripts\python.exe -m ruff format --check .

# semua test (unit + integrasi ke atlas_test). Test integrasi otomatis dilewati jika .env belum punya password role.
.venv\Scripts\python.exe -m pytest
.venv\Scripts\python.exe -m pytest -m "not integration"   # unit saja
```

- Log aplikasi ditulis ke `logs/<komponen>.log` (JSON, satu baris per event, rotasi harian, disimpan 30 hari).

## Database ATLAS (role, migrasi, data CMDB)

```powershell
# 1) sekali per laptop/server: role + database (superuser; di production = CR)
$env:PGPASSWORD = (Get-Content "$env:USERPROFILE\.atlas\pg_postgres_password.txt" -Raw).Trim()
.venv\Scripts\python.exe scripts\db\bootstrap.py --database atlas --database atlas_test --generate-missing-passwords
Remove-Item Env:PGPASSWORD

# 2) schema (setiap ada file baru di db/migrations/)
.venv\Scripts\python.exe scripts\db\migrate.py --dry-run
.venv\Scripts\python.exe scripts\db\migrate.py

# 3) data CMDB (manual, setiap ada Excel OSPLA baru)
.venv\Scripts\python.exe -m atlas.collectors.cmdb_import --xlsx "<path>\OSPLA Managed Server-03022026.xlsx"
```

| Role | Dipakai oleh | Hak utama |
|---|---|---|
| `atlas_owner` (NOLOGIN) | — | Pemilik semua objek; satu-satunya yang bisa DDL & drop partisi audit |
| `atlas_migrator` | `migrate.py` | `SET ROLE atlas_owner` saat migrasi (tidak mewarisi hak otomatis) |
| `atlas_app` | job/collector | Tulis data, INSERT audit, tabel TEMP untuk staging |
| `atlas_web` | web | Baca data + INSERT/SELECT audit |
| `atlas_readonly` | pembaca lain | SELECT saja, sesi `default_transaction_read_only=on` |

- `--generate-missing-passwords` mengisi password acak ke `.env` (tidak pernah dicetak). Ditolak bila `ATLAS_ENV=prod`.
- `bootstrap.py` menolak berjalan bila `log_statement` server = `all`/`ddl` (password role bisa masuk log server).
- Impor CMDB: file yang sama diimpor ulang = 0 baris ditulis; jumlah baris turun > 50% ditolak kecuali `--allow-shrink`.

## Web ATLAS (baru) & job kapasitas

```powershell
# data kapasitas di DEV: impor cache V4 (live NBU diblok, ATLAS_ALLOW_LIVE_NBU=0)
.venv\Scripts\python.exe -m atlas.collectors.capacity_job --from-json legacy\web-v4\cache

# web baru (hanya bisa diakses dari laptop ini); web V4 lama tetap bisa jalan di port 8000
.venv\Scripts\python.exe -m uvicorn atlas.web.main:app --host 127.0.0.1 --port 8001
# buka http://127.0.0.1:8001  — cek kesehatan: http://127.0.0.1:8001/api/health
```

```powershell
# backup inventory (menu 🔎): dari policy_cache.json milik bot (hanya dibaca)
.venv\Scripts\python.exe -m atlas.collectors.inventory_job --cache "D:\bot\NetbackupBotV2\cache\policy_cache.json"
```

- Operasional (jadwal job, cek kesehatan, menelusuri ID error, retensi, rollback): [docs/06-runbook-atlas.md](../06-runbook-atlas.md).
- Web hanya membaca DB (role `atlas_web`); tidak pernah menembak master NBU. `POST /api/generate` selalu 403.
- Data baru dari job langsung tampil: job mengirim `NOTIFY atlas_data_changed`, web membuang cache.
- Collect live (production, lewat CR): `ATLAS_ALLOW_LIVE_NBU=1` + `NBU_*_TOKEN`, lalu
  `python -m atlas.collectors.capacity_job` dijadwalkan Task Scheduler tiap 10 menit (menggantikan `scheduled_collect.py`).
  Selama transisi, `ATLAS_CAPACITY_JSON_DIR` membuat job juga menulis JSON & Excel format V4 untuk rollback.

## Historical Capacity — data contoh (DEV)

```powershell
.venv\Scripts\python.exe scripts\dev\seed_capacity_history.py --days 730   # riwayat contoh 2 tahun (source=demo)
.venv\Scripts\python.exe scripts\dev\seed_capacity_history.py --purge      # hapus semua data contoh
```

## Frontend (Tailwind CSS) — DEV

Node.js (LTS) hanya dibutuhkan di laptop DEV untuk membangun CSS; server tidak butuh Node.

```
npm ci --ignore-scripts          # pasang Tailwind CLI, font, playwright-core (sekali)
npm run watch:css                # saat mengubah tampilan
npm run build:css                # sebelum commit (CI memeriksa hasilnya)
npm run shots -- http://127.0.0.1:8001 build/ui-shots   # screenshot tiap menu + uji Capture (Edge lokal)
node scripts/ui/live_tour.mjs    # jendela Chrome dengan kursor tur otomatis + reload saat file berubah
```

Detail aturan desain: [frontend/README.md](../../frontend/README.md).

## Paket rilis & self-check

```powershell
# paket dari tag (setelah merge + tag): zip + requirements.lock + wheelhouse offline + SHA256SUMS → dist\
.venv\Scripts\python.exe scripts\release\build_release.py --tag vX.Y.Z
python scripts\release\verify_release.py dist\atlas-vX.Y.Z      # di server, sebelum dipasang

# gerbang sebelum switch rilis (read-only)
.venv\Scripts\python.exe -m atlas.selfcheck
```

Langkah staging lengkap: [docs/08-cr-staging.md](../08-cr-staging.md).

## Belum disiapkan

- Bot Telegram uji + mock NBU untuk menjalankan semua komponen sekaligus.
