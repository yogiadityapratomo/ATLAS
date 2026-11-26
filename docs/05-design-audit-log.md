# Fase 2 (adendum) — Design: Audit & Event Log

| | |
|---|---|
| Versi | 0.1 |
| Tanggal | 2026-11-26 |
| Permintaan owner | "Dari sisi log — koneksi database, web, atau event apa pun — ada menu audit log-nya, agar rapi" |
| Status | Disetujui sebagai bagian fondasi (owner: "lanjut") — detail dapat direvisi saat review PR |

## 1. Tujuan

Satu tempat untuk melihat **semua kejadian penting** ATLAS: siapa mengakses apa, job mana yang gagal, kapan koneksi database putus, error apa yang muncul, dan berapa lama prosesnya. Tersedia sebagai menu **Audit Log** di dashboard, dan tetap tercatat di file log walaupun database sedang tidak bisa diakses.

## 2. Event yang dicatat

| Kategori | Contoh `event_type` | Sumber | Isi penting di `details` |
|---|---|---|---|
| `web` | `http_request` | Middleware FastAPI (setiap request API) | method, path, status, durasi, IP klien, user agent |
| `app` | `inventory_search`, `export_excel`, `cache_invalidated` | Route & service | kata kunci, filter, jumlah hasil, versi data |
| `db` | `db_pool_opened`, `db_connect_failed`, `db_reconnected`, `db_slow_query`, `db_pool_exhausted` | `atlas/core/db.py` | host/database (tanpa password), durasi, nama query |
| `job` | `job_started`, `job_finished`, `job_failed`, `job_skipped_locked` | Collector, loader, import | `collect_run.id`, jumlah baris ditulis/diubah/dihapus, error per master |
| `security` | `request_rejected`, `live_nbu_blocked`, `validation_failed` | Web | alasan, IP klien |
| `system` | `app_started`, `app_stopped`, `config_loaded` | Proses web/job | versi, environment (tanpa secret) |
| `bot` | `command`, `telegram_error`, `heartbeat_missed` | Bot v3 (menyusul) | user Telegram, perintah, durasi |

Level: `debug`, `info`, `warning`, `error`, `critical`. Setiap error mendapat **ID error** (mis. `ERR-7F3A2C`), yang sama di pesan ke user, file log, dan tabel audit.

**Tidak pernah dicatat:** password, token, API key, isi `.env`, stack trace di layar user. Filter secret yang sama dipakai untuk file log dan tabel audit.

## 3. Penyimpanan

### 3.1 Tabel `audit.event` (database `atlas`)

| Kolom | Tipe | Keterangan |
|---|---|---|
| `id` | bigint identity | |
| `occurred_at` | timestamptz | Waktu kejadian (bukan waktu insert) |
| `category` | text, CHECK | Lihat §2 |
| `event_type` | text | |
| `severity` | text, CHECK | debug … critical |
| `component` | text | `web`, `capacity_job`, `inventory_job`, `cmdb_import`, `bot`, … |
| `actor` | text | User/IP klien/nama job |
| `request_id` | uuid | Menghubungkan semua event dari satu request/run |
| `error_id` | text | Kosong jika bukan error |
| `message` | text | Ringkas, Bahasa Indonesia |
| `duration_ms` | integer | Jika relevan |
| `details` | jsonb | Data terstruktur tambahan |
| `host`, `pid`, `app_version` | text/int | Asal kejadian |

Teknik database:

| Teknik | Manfaat |
|---|---|
| **Partisi bulanan** pada `occurred_at` | Retensi = drop partisi lama (instan), query per rentang waktu hanya menyentuh partisi terkait |
| **BRIN** pada `occurred_at` | Index sangat kecil untuk data yang selalu bertambah menurut waktu |
| btree `(category, occurred_at DESC)`, partial `(occurred_at DESC) WHERE severity IN ('error','critical')`, `request_id`, `error_id` | Filter menu cepat; daftar error terbaru instan |
| `pg_trgm` GIN pada `message` | Pencarian teks bebas di menu |
| **Append-only**: role aplikasi hanya punya `INSERT` (tanpa `UPDATE`/`DELETE`) | Audit tidak bisa diubah atau dihapus oleh aplikasi — hanya retensi partisi oleh owner |

Retensi usulan: **180 hari** di database; file log 30 hari.

### 3.2 Jalur tulis yang tidak memperlambat aplikasi

```
kode ──► logger ATLAS ──┬──► file log JSON (berotasi)   ← selalu, sumber kebenaran saat DB mati
                        └──► antrean di memori ──► penulis latar belakang
                                                     tiap 1 detik / 200 event: COPY batch ke audit.event
                                                     DB mati → tetap di file; hitung event terlewat;
                                                     saat pulih → event 'audit_backlog_dropped'
```

- Request web **tidak menunggu** penulisan audit (write-behind, batch dengan `COPY`).
- Antrean dibatasi (mis. 10.000 event); jika penuh, event `debug/info` dibuang lebih dulu, `error/critical` dipertahankan.
- File log tetap lengkap, sehingga tidak ada event yang hilang walau database bermasalah.

### 3.3 Log server PostgreSQL

Event di sisi server database (login gagal, koneksi putus, query lambat, lock menunggu) dicatat oleh PostgreSQL sendiri lewat setting `log_connections`, `log_disconnections`, `log_min_duration_statement`, `log_lock_waits`, dan `log_line_prefix` lengkap. Di DEV diaktifkan sekarang; di production lewat CR.

## 4. Menu Audit Log

```
┌ Sidebar ┐ ┌──────────────────────────────────────────────────────────────────┐
│ 🗄️ Disk │ │ Audit Log                                   Auto-refresh 30 dtk  │
│ 📼 Tape │ │ [Event 24 jam] [Error 24 jam] [Job gagal 24 jam] [Koneksi DB gagal]│
│ 🔎 BI   │ ├──────────────────────────────────────────────────────────────────┤
│ 📜 Audit◀│ │ Waktu [24 jam ▼]  Kategori [Semua ▼]  Level [≥ info ▼]           │
└─────────┘ │ Komponen [Semua ▼]  Cari teks [........]  Request/Error ID [....] │
            │ Tabel: Waktu | Level | Kategori | Komponen | Event | Pesan | Durasi│
            │ (klik baris → panel detail: JSON details + semua event dengan     │
            │  request_id yang sama)                       [Muat lebih] [⬇ CSV] │
            └──────────────────────────────────────────────────────────────────┘
```

- Pagination keyset (`occurred_at, id`), maksimal 200 baris per halaman.
- Warna level konsisten dengan dashboard (hijau info, oranye warning, merah error/critical).
- API: `GET /api/audit/events?from=&to=&category=&severity=&component=&q=&request_id=&error_id=&before_id=&limit=`, `GET /api/audit/summary`, `GET /api/audit/export`.

## 5. Role database (pembaruan dari design 03 §4.3)

| Role | Hak audit |
|---|---|
| `atlas_web` (baru, menggantikan pemakaian `atlas_readonly` oleh web) | SELECT data dashboard + **INSERT** `audit.event` |
| `atlas_app` (job) | INSERT `audit.event` |
| `atlas_readonly` | SELECT (termasuk `audit.event`) — untuk pembaca lain |
| `atlas_owner` | Satu-satunya yang bisa drop partisi audit (retensi) |

## 6. Acceptance criteria

1. Setiap request API menghasilkan satu event `web/http_request` dengan `request_id`, status, dan durasi.
2. Mematikan PostgreSQL saat web berjalan → event `db_connect_failed` tercatat di file log; setelah DB hidup → `db_reconnected` dan `audit_backlog_dropped` (jika ada) masuk ke tabel; web tidak crash.
3. Job yang dipicu dua kali bersamaan → run kedua tercatat `job_skipped_locked`.
4. Error di API → user melihat pesan + ID error; ID yang sama bisa dicari di menu Audit Log.
5. Role web tidak bisa `UPDATE`/`DELETE` `audit.event` (diuji otomatis).
6. Tidak ada secret di file log maupun tabel audit (diuji dengan secret palsu).
7. Menu Audit Log memfilter 100 ribu event < 1 detik di DEV.
