# Runbook — ATLAS (web + job + database)

| | |
|---|---|
| Versi | 0.1 (DEV; diperbarui saat staging/production) |
| Tanggal | 2026-11-27 |
| Dasar | [04-implementation-plan.md](04-implementation-plan.md), [05-design-audit-log.md](05-design-audit-log.md), [process/deployment-workflow.md](process/deployment-workflow.md) |

Semua perintah dijalankan dari root repo dengan `.venv\Scripts\python.exe`. Di server production setiap perintah yang mengubah state adalah **CHANGE — butuh CR**.

## 1. Komponen

| Komponen | Perintah | Jadwal usulan | Role DB |
|---|---|---|---|
| Web | `-m uvicorn atlas.web.main:app --host 127.0.0.1 --port 8001` | Service NSSM | `atlas_web` |
| Kapasitas (disk pool & tape) | `-m atlas.collectors.capacity_job` | Task Scheduler tiap 10 menit (pengganti `scheduled_collect.py`) | `atlas_app` |
| Backup inventory | `-m atlas.collectors.inventory_job` (`ATLAS_POLICY_CACHE`) | Setelah collector bot memperbarui `policy_cache.json` (usulan tiap 15 menit) | `atlas_app` |
| CMDB | `-m atlas.collectors.cmdb_import --xlsx "<file OSPLA>"` | Manual saat ada Excel baru | `atlas_app` |
| Maintenance | `-m atlas.collectors.maintenance_job` | Harian 02:00 | `atlas_app` |
| Migrasi schema | `scripts\db\migrate.py` (`--dry-run` dulu) | Saat deploy | `atlas_migrator` |

Semua job aman dipicu ganda: run kedua otomatis `job_skipped_locked` (advisory lock). Exit code `0` = sukses/parsial/dilewati, `1` = gagal.

## 2. Cek kesehatan

1. `GET /api/health` → `status` (`ok`/`degraded`/`down`), umur data per sumber, status run terakhir.
2. Menu **📜 Audit Log** → tile *Error 24 jam*, *Job gagal 24 jam*, *Koneksi DB gagal 24 jam* (klik tile = filter).
3. File log: `logs/<komponen>.log` (JSON per baris, rotasi harian, 30 hari).

## 3. Menelusuri keluhan user

1. User menyebut ID error (mis. `ERR-7F3A2C`) dari pesan di layar.
2. Audit Log → kolom *Request ID / ERR-XXXXXX* → isi ID → Terapkan (pencarian ID otomatis 30 hari ke belakang).
3. Klik baris → panel detail: JSON `details` + semua event dengan `request_id` yang sama (urutan kejadian request itu).
4. Bila DB sedang mati saat kejadian: cari ID yang sama di `logs/web.log` (file log selalu lengkap).

## 4. Gangguan umum

| Gejala | Cek | Tindakan |
|---|---|---|
| Banner "pengumpulan terakhir gagal" di menu kapasitas | Audit Log, kategori `job`, event `job_failed` / `nbu_fetch_failed` | Lihat `details.reason` per master. Data terakhir yang berhasil tetap tampil. Ulangi job manual bila master sudah pulih |
| Data parsial (satu master hilang) | `collect_status.capacity.errors` di `/api/data` | Biasanya 503/timeout master; job berikutnya mengulang otomatis (retry per halaman, lanjutan tape) |
| Web 503 + ID error | Audit Log kategori `db` (`db_connect_failed`) | Cek service PostgreSQL. Web pulih sendiri (`db_reconnected`) tanpa restart |
| Job ditolak "jumlah baris turun > 50%" | File sumber (Excel / `policy_cache.json`) terpotong? | Perbaiki file; bila penurunan memang benar, jalankan ulang dengan `--allow-shrink` |
| `audit_backlog_dropped` | Antrean audit penuh saat DB lama mati | Event lengkap tetap ada di file log |

## 5. Retensi

- `audit.event`: partisi bulanan, dibuang setelah `ATLAS_AUDIT_RETENTION_DAYS` (default 180) oleh job maintenance lewat `core.drop_old_partitions` (aplikasi sendiri tidak punya hak DROP; batas minimal 28 hari).
- Riwayat kapasitas: `ATLAS_CAPACITY_RETENTION_DAYS` (default 0 = simpan semua).
- File log: 30 hari.

## 6. Rollback

- Web: hentikan service ATLAS, jalankan web V4 (`legacy/web-v4`). Selama transisi isi `ATLAS_CAPACITY_JSON_DIR` agar job kapasitas tetap menulis JSON & Excel V4.
- Data: setiap job satu transaksi — run gagal tidak mengubah data. `dbbackup` lama tidak pernah disentuh ATLAS.
- Schema: migrasi bersifat maju; rollback = restore backup DB `atlas` (tanpa memengaruhi `dbbackup`).
