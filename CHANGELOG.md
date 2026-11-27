# Changelog

Format mengikuti [Keep a Changelog](https://keepachangelog.com/id/1.1.0/); versi mengikuti
[Semantic Versioning](https://semver.org/lang/id/). Tag `vX.Y.Z` dibuat saat merge ke `main`
(lihat [docs/process/deployment-workflow.md](docs/process/deployment-workflow.md)).

## [Unreleased]

### Added
- CI GitHub Actions: ruff + test unit + test integrasi/API di PostgreSQL 18 untuk setiap PR dan push ke `main`.
- `python -m atlas.selfcheck`: gerbang read-only sebelum switch rilis (config, koneksi DB per role, versi schema & checksum, partisi, file sumber, aset web; opsional `--nbu-ping`).
- `scripts/release/build_release.py` (paket dari tag: zip, `requirements.lock`, wheelhouse Windows/cp313 untuk instalasi offline, `SHA256SUMS`) dan `scripts/release/verify_release.py`.
- `ATLAS_ENV_FILE`: lokasi `.env` di luar folder rilis (`shared\.env`); `bootstrap.py` menulis password ke file yang sama.
- `V005__selfcheck_grants.sql`: role aplikasi boleh membaca `core.schema_migrations`.
- Draf CR staging: [docs/08-cr-staging.md](docs/08-cr-staging.md).
- **Menu 📈 Historical Capacity**: tren disk pool per hari/minggu/bulan/kuartal/semester/tahun, grouping site/master/appliance (checkbox maks 8), metrik usage %/used/free, garis acuan 70%/85%, perkiraan kapan mencapai 85%, export Excel ([design 09](docs/09-design-capacity-history.md)).
- `V006__capacity_history.sql`: `capacity.disk_pool_daily` + fungsi rollup; `V007`: rollup juga mencakup run yang sedang berjalan (ditemukan test sebelum merge). Job kapasitas & maintenance mengisi ringkasan harian.
- `scripts/dev/seed_capacity_history.py`: riwayat contoh 2 tahun (`source='demo'`, `--purge`).
- Fase 5: `scripts/dev/mock_nbu.py`, `scripts/dev/soak.py`, [quality report](docs/07-quality-report.md).

### Changed
- `capacity_job --from-json` melewati file V4 yang belum berubah sejak impor terakhir (event `job_skipped_unchanged`) — mencegah snapshot duplikat saat collector V4 gagal.
- Test regresi kapasitas memakai fixture sintetis `tests/fixtures/v4_cache` (cache V4 asli tidak ada di repo).

## [0.1.0] - 2026-11-27

Rilis pertama ATLAS (DEV). Belum di-deploy ke staging/production — deploy mengikuti
[deployment-workflow](docs/process/deployment-workflow.md) dan butuh CR.

Ringkasan: database `atlas` (role least privilege, migrasi V001–V004), audit & event log, web baru dengan
menu Disk Pool, Tape Library, **Backup Inventory**, dan **Audit Log**; job kapasitas, inventory, CMDB,
dan maintenance. Disetujui owner lewat PR #1–#6.

### Added
- Kerangka paket `atlas/` (core, repositories, services, collectors, web), `frontend/`, `db/migrations/`, `tests/`.
- `pyproject.toml`: dependency (psycopg 3 + pool), konfigurasi pytest & ruff.
- `atlas/core/config.py`: konfigurasi dari `.env` yang divalidasi saat start; password dibungkus `Secret`.
- `atlas/core/logging.py`: log JSON per komponen (rotasi harian, simpan 30 hari), filter secret, `request_id`, `log_event` untuk event audit.
- `atlas/core/errors.py`: `AtlasError` dengan ID error (`ERR-XXXXXX`).
- `atlas/core/db.py`: connection pool dengan event koneksi (`db_pool_opened`, `db_connect_failed`, `db_reconnected`, `db_pool_exhausted`, `db_query_timeout`, `db_slow_query`).
- `.env.example` di root, `.gitattributes`.

- **Database (PR-2):** `scripts/db/bootstrap.py` (role least privilege `atlas_owner`/`migrator`/`app`/`web`/`readonly` + database, idempoten), `scripts/db/migrate.py` + `atlas/core/migrations.py` (checksum, advisory lock, satu transaksi per versi).
- `db/migrations/V001__init.sql`: `core.collect_run`, `audit.event` (partisi bulanan + default, append-only bagi aplikasi), `core.ensure_monthly_partitions`, `cmdb.server_inventory` (`row_hash` + `occurrences`, index trigram), view `report.cmdb_host` & `report.app_list`, GRANT per role.
- `atlas/core/audit.py`: penulis audit write-behind (antrean terbatas, `COPY` batch, backoff saat DB mati, event `audit_backlog_dropped`).
- `atlas/collectors/runner.py`: kerangka job (advisory lock per source, `collect_run`, satu transaksi data, event `job_started`/`job_finished`/`job_failed`/`job_skipped_locked`/`job_orphaned`).
- `atlas.collectors.cmdb_import`: import Excel OSPLA berbasis diff (impor ulang tanpa perubahan = 0 baris ditulis), pengaman penyusutan > 50%, `NOTIFY atlas_data_changed`.

- **Kapasitas ke database (PR-3):** `V002__capacity.sql` — riwayat `capacity.disk_pool_snapshot` & `capacity.tape_library_snapshot` (partisi bulanan), view `capacity.latest_run` / `*_latest`.
- `atlas/collectors/nbu_client.py`: rate limit per master, retry per halaman (429/5xx/timeout, `Retry-After`), deadline kooperatif, lanjutan paginasi tape antar run.
- `atlas.collectors.capacity_job`: collect live (berurutan per master, status success/partial/failed) dan `--from-json` (impor cache V4); opsi tulis file V4 untuk rollback.
- Web baru `atlas/web` (FastAPI): `/api/data` & `/api/export` dari DB dengan kontrak JSON V4, cache per versi data + ETag/304 + `LISTEN/NOTIFY`, `/api/health`, audit `http_request` per request, error ber-ID.
- `frontend/`: tampilan V4 dengan `app.js` dipecah (`common.js`, `main.js`, `capacity.js`), peringatan bila collect terakhir gagal/parsial, favicon.

- **Backup Inventory (PR-4):** `V003__backup_inventory.sql` — `nbu.backup_inventory` (kunci alami + `row_hash`, fillfactor 90, index trigram) dan materialized view `report.backup_inventory_search` (join CMDB, refresh CONCURRENTLY).
- `services/policy_parser.py`: logika Search bot (`check_v2`) — hari 1 = Minggu, `schedule_days` terisi.
- `atlas.collectors.inventory_job`: `policy_cache.json` → DB berbasis diff (muat ulang tanpa perubahan = 0 baris ditulis), pengaman penyusutan > 50%, `NOTIFY`.
- API `/api/backup-inventory/search|apps|filters|export` dan menu **🔎 Backup Inventory**: cari per hostname (sebagian, sama dengan bot) atau per aplikasi CMDB (termasuk host tanpa backup), export Excel format report bot.
- Cache busting aset frontend (`?v=<hash>`), judul halaman mengikuti menu.

- **Audit Log (PR-5):** API `/api/audit/events` (filter, keyset pagination), `/summary`, `/export` (CSV) dan menu **📜 Audit Log** (tile ringkasan yang bisa diklik, filter, panel detail per `request_id`, auto-refresh 30 detik).
- `V004__audit_maintenance.sql`: `core.drop_old_partitions` (SECURITY DEFINER, daftar izin, minimal 28 hari) dan source `maintenance`.
- `atlas.collectors.maintenance_job`: partisi 3 bulan ke depan + retensi audit (`ATLAS_AUDIT_RETENTION_DAYS`, default 180).
- Runbook operasional: [docs/06-runbook-atlas.md](docs/06-runbook-atlas.md).

### Changed
- Polling rutin `GET /api/audit/*` dan `/api/health` dicatat di level `debug` agar tidak membanjiri audit.
- Pencarian hostname: policy dengan `storage = null` (26 policy aktif, mayoritas Deployment) kini ikut tampil; di bot policy ini hilang karena error.
- Pencarian hostname: kata kunci sebagian yang menemukan host (mis. `app1` → `app10`) tidak lagi ikut dilaporkan "Not Available" (bug bot).
- `POST /api/generate` selalu 403: web tidak lagi memicu fetch live ke master NBU (pengambilan data hanya oleh job terjadwal).
- Collect yang gagal total tidak lagi mengosongkan dashboard (V4 menimpa JSON dengan daftar kosong); data terakhir tetap tampil dengan peringatan.
- Web V4 dipindah dari `web/` ke `legacy/web-v4/` sebagai snapshot referensi regresi (tetap bisa dijalankan).

[Unreleased]: https://github.com/yogiadityapratomo/ATLAS/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/yogiadityapratomo/ATLAS/releases/tag/v0.1.0
