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

### Changed
- Web V4 dipindah dari `web/` ke `legacy/web-v4/` sebagai snapshot referensi regresi (tetap bisa dijalankan).
