# Fase 3 — Implementation Plan: Dashboard ATLAS Berbasis Database

| | |
|---|---|
| Versi | 0.1 (draft untuk approval) |
| Tanggal | 2026-11-26 |
| Dasar | [03-design-db-dashboard.md](03-design-db-dashboard.md) (disetujui 2026-11-26) |
| Alur kerja | [process/deployment-workflow.md](process/deployment-workflow.md) — branch → PR → review + bukti test → merge |

---

## 1. Struktur folder target

Modular monolith (guide §4, §8): satu paket Python `atlas`, dipisah per lapisan. Setiap lapisan hanya boleh memanggil lapisan di bawahnya.

```
ATLAS/
├── atlas/                         # paket aplikasi (Python)
│   ├── core/                      # lapisan dasar, dipakai semua komponen
│   │   ├── config.py              #   baca .env → objek Settings (tervalidasi saat start)
│   │   ├── db.py                  #   connection pool, transaksi, advisory lock
│   │   ├── logging.py             #   log JSON + rotasi + filter secret + request_id
│   │   ├── audit.py               #   event audit: antrean + penulis batch ke audit.event
│   │   └── errors.py              #   AtlasError + ID error
│   ├── repositories/              # SEMUA SQL ada di sini (satu file per domain)
│   │   ├── runs.py                #   core.collect_run
│   │   ├── capacity.py            #   capacity.*
│   │   ├── inventory.py           #   nbu.backup_inventory + report.*
│   │   ├── cmdb.py                #   cmdb.*
│   │   └── audit.py               #   audit.event (insert batch, query menu)
│   ├── services/                  # logika bisnis, tanpa SQL & tanpa HTTP → mudah dites
│   │   ├── policy_parser.py       #   policy_cache.json → baris inventory (mapping hari benar)
│   │   ├── capacity.py            #   transform disk pool & tape (dari web V4)
│   │   ├── inventory_search.py    #   parsing input pencarian, not_found
│   │   └── excel_export.py        #   semua export xlsx
│   ├── collectors/                # job terjadwal / CLI (menulis DB lewat repositories)
│   │   ├── nbu_client.py          #   HTTP ke master NBU: timeout, retry, backoff
│   │   ├── capacity_job.py        #   pengganti scheduled_collect.py
│   │   ├── inventory_job.py       #   policy_cache.json → nbu.backup_inventory
│   │   ├── cmdb_import.py         #   Excel OSPLA → cmdb.server_inventory
│   │   └── maintenance_job.py     #   retensi partisi (kapasitas, audit)
│   └── web/                       # FastAPI (hanya baca DB)
│       ├── main.py                #   app, middleware, static
│       ├── deps.py                #   dependency: koneksi read-only, cache
│       ├── cache.py               #   cache in-process ber-versi (lihat §3.3)
│       ├── schemas.py             #   model Pydantic request/response
│       └── routes/
│           ├── capacity.py        #   /api/data, /api/export
│           ├── inventory.py       #   /api/backup-inventory/*
│           ├── audit.py           #   /api/audit/*
│           └── health.py          #   /api/health
├── frontend/                      # tanpa build step (jQuery)
│   ├── index.html
│   ├── css/style.css
│   ├── js/
│   │   ├── common.js              #   util bersama (esc, fmtNum, buildTable, statTile, alert)
│   │   ├── capacity.js            #   menu Disk Pool & Tape (dari app.js V4)
│   │   ├── inventory.js           #   menu Backup Inventory (baru)
│   │   ├── audit.js               #   menu Audit Log (baru)
│   │   └── main.js                #   navigasi & lifecycle
│   └── vendor/                    #   jquery, html2canvas
├── db/
│   └── migrations/                # V001__init.sql, V002__... (urutan = versi)
├── scripts/
│   ├── db/migrate.py              # jalankan migrasi + catat checksum
│   ├── dev/                       # khusus laptop (data lokal, seed)
│   └── diagnostics/               # alat read-only (pg_inventory, audit log NBU)
├── tests/
│   ├── unit/                      # tanpa DB
│   ├── integration/               # pakai DB atlas_test
│   └── api/                       # FastAPI TestClient
├── legacy/                        # referensi read-only, tidak dijalankan
│   └── web-v4/                    #   snapshot web V4 apa adanya (tanpa token) untuk uji regresi
├── docs/
├── .env.example
├── pyproject.toml                 # dependency + konfigurasi pytest & ruff
├── CHANGELOG.md
└── README.md
```

Aturan:
- **SQL hanya di `repositories/`**, logika hanya di `services/`, HTTP hanya di `web/`. Dengan begitu query mudah direview dan di-tuning di satu tempat.
- Tidak ada path, URL, token, atau password di kode; semuanya dari `atlas/core/config.py`.
- Nama file dan fungsi dalam bahasa Inggris; teks yang tampil ke user dalam Bahasa Indonesia (mengikuti konvensi web V4).

## 2. Stack & dependency

| Kebutuhan | Pilihan | Alasan |
|---|---|---|
| Driver PostgreSQL | **psycopg 3** (`psycopg[binary]`) + `psycopg_pool` | Driver modern; `COPY` cepat, prepared statement otomatis, pool resmi |
| Web | FastAPI + Uvicorn (versi sama dengan V4) | Tidak mengubah stack yang sudah dikenal |
| Config | `python-dotenv` + dataclass tervalidasi | Ringan, tanpa dependency berat |
| Excel | openpyxl | Sama dengan V4 |
| Test & lint | pytest, ruff | Standar, cepat |

## 3. Teknik database (read & write)

### 3.1 Penulisan (write) — cepat, hemat, aman

| Teknik | Diterapkan di | Manfaat |
|---|---|---|
| **`COPY` ke tabel staging sementara** (bukan INSERT per baris) | Loader inventory, import CMDB | Bulk load 10–50× lebih cepat dari `execute_batch` |
| **Upsert berbasis diff** — `INSERT … ON CONFLICT (kunci alami) DO UPDATE … WHERE row_hash IS DISTINCT FROM excluded.row_hash` + hapus baris yang hilang | `nbu.backup_inventory` | Hanya baris yang **berubah** yang ditulis. Pola lama: TRUNCATE + 7.500 INSERT setiap run (714 juta baris tertulis). Pola baru: biasanya puluhan baris per run → WAL, bloat, dan beban autovacuum turun drastis |
| **Kolom `row_hash`** (md5 isi baris) | `nbu.backup_inventory`, `cmdb.server_inventory` | Deteksi perubahan murah, satu perbandingan per baris |
| **Kunci alami + UNIQUE** (`master, policy, client_host_norm, schedule`) | `nbu.backup_inventory` | Data tidak bisa dobel; dasar upsert |
| **Satu transaksi per job** | Semua job | Pembaca tidak pernah melihat data setengah jadi; gagal = rollback, data lama utuh (tanpa A/B swap & `CREATE OR REPLACE VIEW`) |
| **Advisory lock PostgreSQL** (`pg_try_advisory_lock`) per job | Semua job | **Job tidak bisa berjalan ganda** walau Task Scheduler memicu dua kali — menutup masalah R1/D3 langsung di level DB |
| **Partisi bulanan** (`PARTITION BY RANGE (collected_at)`) | `capacity.*_snapshot` | Retensi = `DROP` partisi lama (instan, tanpa DELETE besar, tanpa bloat) |
| **`fillfactor = 90`** | `nbu.backup_inventory` | Ruang untuk HOT update → update tanpa menyentuh index |
| **Kolom generated** `client_host_norm = lower(btrim(client_host))` | `nbu`, `cmdb` | Normalisasi dijamin DB, bukan kode; dipakai index & join |
| **Constraint data** (`NOT NULL`, `CHECK` status/persen) | Semua tabel | Data rusak ditolak saat ditulis, bukan ketahuan saat dibaca |

### 3.2 Pembacaan (read) — cepat & tidak saling mengunci

| Teknik | Diterapkan di | Manfaat |
|---|---|---|
| **Index trigram `pg_trgm` (GIN)** | `client_host_norm`, `lower(app_name)` | `ILIKE '%app1%'` tetap memakai index → cari sebagian < 50 ms |
| **Index komposit & expression** | `(source, finished_at DESC) WHERE status='success'` (partial), `hostname_norm`, `(master_server, policy_type)` | Ambil run terakhir & filter tanpa scan penuh |
| **Materialized view `report.backup_inventory_search`** (join backup ↔ CMDB, aplikasi digabung) + `REFRESH … CONCURRENTLY` di akhir job | Menu Backup Inventory | Join & agregasi dihitung sekali per load, bukan per request; refresh concurrently tidak memblok pembaca |
| **BRIN index** `collected_at` | `capacity.*_snapshot` | Index sangat kecil untuk data deret waktu (grafik tren) |
| **Connection pool** (2–5 koneksi) | Web | Tidak buka-tutup koneksi tiap request |
| **Role web read-only** + `default_transaction_read_only = on` + `statement_timeout` | `atlas_readonly` | Web secara teknis tidak bisa menulis; query lari tidak bisa menggantung |
| **Pagination keyset** + batas `limit` | API search | Respons tetap kecil walau hasil besar |

### 3.3 Cache bertingkat dengan invalidasi otomatis

```
Browser ──(ETag = versi data)──► Web ──(cache in-process per versi)──► PostgreSQL
   ▲  304 Not Modified jika sama        ▲  dibuang otomatis saat versi berubah
   └────────────────────────────────────┴──── LISTEN 'atlas_data_changed' ◄── NOTIFY dari job
```

| Lapisan | Cara kerja | Manfaat |
|---|---|---|
| **Versi data** | `data_version` = id `collect_run` sukses terakhir per sumber | Kunci cache yang pasti benar — tidak perlu TTL tebakan |
| **Cache in-process** | Hasil `/api/data`, daftar aplikasi, dan hasil cari populer disimpan per `data_version` | Request berulang tidak menyentuh DB |
| **`LISTEN/NOTIFY`** | Job selesai → `NOTIFY atlas_data_changed`; web mendengar → cache dibuang seketika | Data baru langsung tampil, tanpa polling DB |
| **HTTP `ETag` / `304`** | Browser kirim `If-None-Match`; bila versi sama → 304 tanpa body | Refresh otomatis 5 menit di frontend hampir tanpa biaya |
| **Cache file Excel per versi** | Export kapasitas dibuat sekali per `data_version` | Klik export berulang tidak menghitung ulang |

### 3.4 Observability database

- `pg_stat_statements` (DEV sekarang; production lewat CR karena butuh restart) → daftar query paling lambat/sering.
- `log_min_duration_statement = 500ms`, `log_lock_waits = on` pada role aplikasi.
- `/api/health` menampilkan umur data per sumber dan status job terakhir (dasar halaman healthcheck bot).

## 4. Daftar task

Setiap task = satu atau beberapa commit kecil; setiap branch = satu PR dengan bukti test.

| # | Task | File utama | Test / bukti | Rollback |
|---|---|---|---|---|
| **PR-0** `chore/dev-local-baseline` | | | | |
| 0.1 | Commit pekerjaan DEV yang sudah ada: alat `pg_inventory`, assessment DB, web V4 (token dipindah ke `.env`), skrip dev, design & plan | `docs/`, `scripts/`, `web/` | Pemindaian secret bersih; web jalan di 127.0.0.1 | Revert PR |
| **PR-1** `refactor/project-structure` | | | | |
| 1.1 | Pindah `web/` → `legacy/web-v4/` (referensi, tetap bisa dijalankan) + `.gitattributes` (line ending konsisten) | `legacy/` | Web V4 tetap jalan dari lokasi baru | Revert |
| 1.2 | Kerangka `atlas/`, `frontend/`, `tests/`, `pyproject.toml`, `.env.example`, `CHANGELOG.md` | struktur §1 | `pytest` & `ruff` bersih | Revert |
| 1.3 | `atlas/core`: config, logging (JSON + rotasi + filter secret + ID error + request_id), db pool (event koneksi), errors | `atlas/core/*` | Unit test config, filter secret, ID error, format log | Revert |
| **PR-2** `feat/db-foundation` | | | | |
| 2.1 | `scripts/db/migrate.py` + `core.schema_migrations` (checksum) | `scripts/db/`, `db/migrations/` | Test: DB kosong → semua versi; ulang = no-op; file berubah = ditolak | `DROP DATABASE atlas` (DEV) |
| 2.2 | `V001__init.sql`: schema, role, tabel (termasuk `audit.event`), partisi, constraint, index, view | `db/migrations/` | Test integrasi: struktur & hak akses role (web tidak bisa UPDATE/DELETE audit) | Migrasi down manual (DEV) |
| 2.3 | Penulis audit write-behind (antrean + `COPY` batch + fallback file) | `atlas/core/audit.py`, `repositories/audit.py` | Test: event masuk tabel; DB mati → tidak crash, tercatat di file; secret tersaring | Revert |
| 2.4 | Import CMDB (`COPY` + upsert + `row_hash`, advisory lock, event job) | `collectors/cmdb_import.py`, `repositories/cmdb.py` | 14.185 baris; impor ulang tanpa perubahan = 0 baris ditulis | Data lama utuh (transaksi) |
| **PR-3** `feat/capacity-db` | | | | |
| 3.1 | `nbu_client.py` + `capacity_job.py` menulis DB (dan tetap JSON selama transisi) | `collectors/` | Integrasi dengan mock NBU: sukses, sebagian gagal, timeout | Collector V4 lama tetap ada |
| 3.2 | Web baru `atlas/web` + `frontend/` (port tampilan V4, `app.js` dipecah per menu), middleware audit `http_request` | `atlas/web/`, `frontend/` | Uji visual sebelum/sesudah | Jalankan `legacy/web-v4` |
| 3.3 | `/api/data` & `/api/export` dari DB (bentuk JSON sama) + cache ber-versi + ETag | `web/routes/capacity.py`, `web/cache.py` | **Regresi: JSON dari DB identik dengan JSON file**; 304 bekerja | Jalankan `legacy/web-v4` |
| 3.4 | `/api/health` | `web/routes/health.py` | API test | Revert |
| **PR-4** `feat/backup-inventory` | | | | |
| 4.1 | `services/policy_parser.py` (gabungan logika bot & loader, mapping hari benar) | `services/` | Unit test: hari, retensi SLP/non-SLP, filter; regresi vs `check_v2` | — |
| 4.2 | Job inventory: `COPY` → upsert diff → refresh MV → `NOTIFY`, dengan advisory lock | `collectors/inventory_job.py`, `repositories/inventory.py` | Run kedua tanpa perubahan = 0 update; dua run paralel → satu `job_skipped_locked` | Transaksi |
| 4.3 | API search / apps / export | `web/routes/inventory.py` | API test: validasi, not_found, limit; performa < 1 dtk | Revert |
| 4.4 | Menu Backup Inventory (UI) | `frontend/js/inventory.js` | Uji manual di browser | Revert |
| **PR-5** `feat/audit-log-menu` | | | | |
| 5.1 | API `/api/audit/events`, `/summary`, `/export` (keyset pagination) | `web/routes/audit.py`, `repositories/audit.py` | API test filter & pagination; 100 ribu event < 1 dtk | Revert |
| 5.2 | Menu Audit Log (UI) + panel detail per `request_id` | `frontend/js/audit.js` | Uji manual; acceptance criteria design 05 §6 | Revert |
| 5.3 | Retensi partisi (kapasitas 90 hari, audit 180 hari), runbook | `collectors/maintenance_job.py`, `docs/` | Test drop partisi di DB test | Revert |

Urutan: aplikasi baru lebih dulu mereproduksi menu yang sudah ada (PR-3) sebelum menambah fitur baru (PR-4, PR-5), sehingga dashboard tidak pernah dalam kondisi setengah jadi. Design audit: [05-design-audit-log.md](05-design-audit-log.md).

## 5. Definition of Done per PR

Mengikuti [deployment-workflow.md §6](process/deployment-workflow.md): test relevan lulus dengan output nyata di PR, tidak ada secret, dokumentasi & CHANGELOG diperbarui, perilaku lama tidak berubah kecuali yang disetujui di design §2.

## 6. Risiko & mitigasi

| Risiko | Mitigasi |
|---|---|
| Refactor struktur merusak tampilan V4 | Snapshot `legacy/web-v4` + uji regresi JSON & uji visual sebelum/sesudah |
| `pg_trgm` / partisi tidak tersedia di production | Keduanya bawaan PostgreSQL 18 (contrib). Dicek di migrasi; gagal = migrasi berhenti tanpa perubahan |
| Kebiasaan tim membaca `dbbackup` | `dbbackup` tidak diubah; view kompatibilitas dibuat belakangan |
| `LISTEN/NOTIFY` terputus | Fallback: cek `data_version` setiap 60 detik |
