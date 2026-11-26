# Changelog

Format mengikuti [Keep a Changelog](https://keepachangelog.com/id/1.1.0/); versi mengikuti
[Semantic Versioning](https://semver.org/lang/id/). Tag `vX.Y.Z` dibuat saat merge ke `main`
(lihat [docs/process/deployment-workflow.md](docs/process/deployment-workflow.md)).

## [Unreleased]

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

### Changed
- Web V4 dipindah dari `web/` ke `legacy/web-v4/` sebagai snapshot referensi regresi (tetap bisa dijalankan).
