# Adendum Fase 1 — Assessment PostgreSQL Production

| | |
|---|---|
| Versi | 0.1 (draft untuk review) |
| Tanggal | 2026-11-26 |
| Sumber | `pg_inventory.ps1` (read-only) dijalankan di server bot 2026-11-26 11:36; kode loader `convert_policy_cache_autoupdatedb.py` (salinan 2026-11-20) |
| Diubah di production? | Tidak |

Notasi: **[V]** terverifikasi · **[A]** asumsi · **[M]** belum ada informasi.

---

## 1. Ringkasan

- Satu cluster PostgreSQL **18.1** (Windows), uptime 36 hari, ukuran total ±41 MB. Hanya ada satu database aplikasi: **`dbbackup`** (17 MB). [V]
- Hanya ada **satu role: `postgres` (superuser)**, dipakai semua aplikasi dan juga diizinkan login dari **semua alamat** (`0.0.0.0/0`, `::/0`) ke `dbbackup`, tanpa SSL. [V]
- Loader DB berjalan **jauh lebih sering dari yang direncanakan**: 95.002 kali swap A/B (± 714 juta baris di-insert), padahal jadwalnya setiap 10 menit. [V angka, A penyebab]
- Kolom jadwal di DB **salah hari**: loader memakai mapping 1 = Senin, padahal NetBackup 1 = Minggu (lampiran B assessment utama). Data ini dibaca Netbackup Assistant (Dify) dan tim lain. [V]
- Belum ada bukti backup database (archive off, jadwal `pg_dump` belum diketahui). [M]

## 2. Konfigurasi server

| Item | Production | DEV laptop | Catatan |
|---|---|---|---|
| Versi | 18.1 | 18.7 | Minor beda; disarankan production naik ke 18.7 (CR) |
| Encoding | UTF8 | UTF8 | Sama |
| Collation/ctype | `English_United States.1252` (libc) | DB `dbbackup` DEV dibuat sama; default cluster DEV `English_Indonesia.1252` | Collation Windows tidak portabel ke Linux |
| TimeZone / log_timezone | `Asia/Bangkok` | `Asia/Bangkok` | Offset sama dengan WIB; nama yang tepat `Asia/Jakarta` |
| listen_addresses | `*` | `localhost` | Production terbuka ke jaringan |
| ssl | off | off | Lalu lintas dari luar server tidak terenkripsi |
| max_connections | 100 | 100 | Saat dicek hanya 1 koneksi aktif |
| shared_buffers | 128 MB | default | Cukup untuk DB 17 MB |
| archive_mode | off | off | Tidak ada PITR |
| Logging | `log_line_prefix='%t '`, tanpa slow query log | default | Sulit investigasi koneksi/query lambat |
| Timeout sesi | `statement_timeout`, `idle_in_transaction_session_timeout` = 0 | — | Transaksi menggantung tidak dibatasi |

### Aturan akses (`pg_hba.conf`)

| Baris | Aturan | Penilaian |
|---|---|---|
| 113–122 | `local`/`127.0.0.1`/`::1`, semua DB & user, scram-sha-256 | Wajar |
| **125–126** | `host dbbackup postgres 0.0.0.0/0` dan `::/0`, scram-sha-256 | **Superuser bisa login dari mana saja** ke `dbbackup`. Ditambahkan 2026-10-20 untuk akses tim aplikasi lain (keputusan owner) |

## 3. Struktur `dbbackup`

| Objek | Jenis | Baris | Ukuran | Catatan |
|---|---|---|---|---|
| `backup_inventory_a` | table | 7.516 | 2,8 MB | Staging/aktif bergantian |
| `backup_inventory_b` | table | 7.516 | 2,8 MB | Memakai **sequence milik tabel A** (`backup_inventory_a_id_seq`) |
| `backup_inventory_control` | table | 1 | 56 kB | `active_table` = tabel yang sedang dipakai view; 95.002 update |
| `backup_inventory` | view | — | — | `SELECT * FROM backup_inventory_a` (atau `_b`), dibuat ulang setiap loader jalan |
| `server_inventory` | table | ±14.105 | 2,5 MB | Data CMDB (hostname, IP OAM/service, aplikasi, PIC, prioritas, prod/nonprod, site). Tidak ada insert/update sejak statistik terakhir; belum pernah di-analyze |

Kolom `backup_inventory_*`: `id, client_host, policy_name, policy_type, storage, volume_pool, backup_selections, client_os, client_hw, schedule_name, schedule_days, backup_type, start_times, retention_period, master_server, created_at`. Detail lengkap: `20_schema_dbbackup.sql` (inventory).

Yang **tidak ada**: foreign key, unique key alami, index selain PK, `NOT NULL` di kolom bisnis, kolom `updated_at`, timestamp ber-zona waktu, function, trigger, extension selain plpgsql. [V]

## 4. Temuan dan risiko

| ID | Severity | Temuan | Bukti | Dampak | Rekomendasi |
|---|---|---|---|---|---|
| D1 | **Critical** | Superuser `postgres` bisa login dari semua IP, tanpa SSL; password yang sama tertulis di kode loader | pg_hba 125–126; `ssl=off`; kode loader | Siapa pun yang tahu password punya kendali penuh atas DB, dan sebagai superuser bisa menjalankan perintah OS (`COPY ... PROGRAM`) | Risiko diterima owner untuk akses tim lain (2026-10-20). Minimal: batasi `0.0.0.0/0` ke IP server tim tersebut, ganti password (sudah tersebar di kode & chat), pindahkan password ke `.env`. ATLAS sendiri memakai role terpisah (lihat §6) |
| D2 | **High** | Kolom `start_times` salah hari (geser 1 hari) | Loader `day_map` 1 = Senin; terbukti 1 = Minggu | Jawaban Netbackup Assistant dan data tim lain keliru | Perbaiki mapping di loader (1 baris, CR) |
| D3 | **High** | Loader berjalan ±12–18× lebih sering dari jadwal | 95.002 swap; jika sejak 21 Okt = ±2.600/hari (seharusnya 144/hari); nama CSV per menit menyembunyikan run ganda | Beban CPU/disk/WAL tidak perlu, `CREATE OR REPLACE VIEW` mengunci view berulang kali, CSV 25,5 GB | Cek konfigurasi task loader (M3); jadikan single-instance |
| D4 | High | Tidak ada bukti backup DB | `archive_mode=off`; tidak ada info `pg_dump` terjadwal | Data `server_inventory` (CMDB, tidak bisa diregenerasi dari NBU) bisa hilang | `pg_dump` harian + uji restore (guide §14) [M: konfirmasi] |
| D5 | Medium | `schedule_days` selalu kosong | Loader menulis `""` | Kolom tidak berguna untuk konsumen | Isi seperti di report Search, atau hapus kolom (koordinasi konsumen) |
| D6 | Medium | Pencarian hostname tanpa index; join `client_host = hostname` tanpa normalisasi/unique | Hanya index PK; 47 ribu seq scan per tabel | Lambat seiring data tumbuh; join bisa ganda jika hostname dobel di CMDB | Index `lower(client_host)`; unique `lower(hostname)` di CMDB |
| D7 | Medium | Pola A/B + `CREATE OR REPLACE VIEW` + `TRUNCATE ... RESTART IDENTITY` dengan sequence bersama | DDL & kode | Lock eksklusif berulang; rapuh jika kolom berubah (`SELECT *`) | Desain baru: tabel ber-kunci alami + upsert perubahan saja (cocok dengan collector delta) |
| D8 | Medium | Satu role untuk semua (tidak least privilege) | 30_globals.sql | Bug di satu aplikasi bisa merusak semua data | Role per fungsi (owner, migrator, app, readonly) |
| D9 | Low | `timestamp without time zone`; TimeZone `Asia/Bangkok` | DDL, setting | Ambigu jika server/klien beda zona | `timestamptz`, zona `Asia/Jakarta` |
| D10 | Low | Logging minim; tanpa timeout sesi | setting | Sulit diagnosa | `log_line_prefix` lengkap, `log_min_duration_statement=1000`, `log_lock_waits=on`, timeout per role aplikasi |
| D11 | Low | Versi 18.1 (terbaru 18.7) | version | Perbaikan bug/keamanan belum terpasang | Minor upgrade via CR |

## 5. Pilihan: database baru vs improve database existing

| Kriteria | A. **DB baru `atlas`** di cluster yang sama (disarankan) | B. Pakai `dbbackup`, tambah schema baru |
|---|---|---|
| Risiko ke konsumen existing (Dify, FastAPI :8443, tim lain) | Nol — `dbbackup` tidak disentuh selama transisi | Ada — migrasi dan DDL di DB yang sedang dipakai |
| Paparan aturan `0.0.0.0/0` superuser | Aturan itu hanya berlaku untuk `dbbackup`, jadi DB `atlas` tidak bisa dijangkau dari luar | Data ATLAS (log bot, user, audit) ikut terpapar |
| Migrasi schema (Alembic) bersih | Ya | Bercampur dengan objek lama tanpa riwayat migrasi |
| Join dengan `server_inventory` | Perlu dipindahkan/disinkron ke `atlas` (CMDB jadi milik ATLAS) | Langsung |
| Collation portabel | Bisa memakai `builtin C.UTF-8` (PG17+), sama di Windows dan Linux | Tetap collation Windows |
| Backup & restore | Per DB, terpisah | Satu DB |

**Rekomendasi: A.** Konsumen lama tetap jalan. Di akhir transisi, view kompatibilitas `backup_inventory` (kolom sama persis) diisi dari data ATLAS, lalu loader lama dipensiunkan.

## 6. Gambaran awal DB `atlas` (detail di Fase 2)

| Schema | Isi |
|---|---|
| `nbu` | master server, policy (kunci alami master + nama, generation, data mentah `jsonb`), client, schedule, start window, SLP, `collect_run` (status per master), checkpoint audit log |
| `cmdb` | server (hostname unik, IP, aplikasi, PIC, prioritas, lingkungan, site, sumber, `updated_at`) |
| `bot` | akses user Telegram, log permintaan (siapa, apa, durasi, hasil, ID error) |
| `ops` | heartbeat komponen (bot, collector, web), event error, status kesehatan untuk dashboard |
| `web` | user, role, sesi dashboard (mengikuti hasil assessment web) |
| `report` | view untuk dashboard dan view kompatibilitas `backup_inventory` |

Role (least privilege, guide §5–6):

| Role | Login | Hak |
|---|---|---|
| `atlas_owner` | tidak | Pemilik semua objek |
| `atlas_migrator` | ya | DDL lewat Alembic, hanya saat deploy |
| `atlas_app` | ya | DML pada schema yang dibutuhkan bot/collector/web |
| `atlas_readonly` | ya | `SELECT` pada schema `report` |

Koneksi aplikasi tetap `localhost` (aplikasi dan DB di server yang sama), jadi tidak perlu aturan `pg_hba` baru dari luar.

## 7. Status DEV lokal

- `dbbackup` (struktur saja, **tanpa data**) dibuat di PostgreSQL laptop dengan collation `English_United States.1252`, sama dengan production. [V]
- Data production tidak disalin (guide §10). Untuk uji, gunakan data sintetis atau hasil parsing `policy_cache.json` salinan.

## 8. Pertanyaan untuk owner

1. Setuju **opsi A** (DB baru `atlas`)?
2. Apakah ada backup `dbbackup` terjadwal? Di mana, dan pernah diuji restore?
3. Siapa yang memperbarui `server_inventory` (CMDB), seberapa sering, dan dari sumber apa?
4. IP server tim aplikasi lain yang memakai akses `0.0.0.0/0`. Boleh dipersempit ke IP itu saja?
5. Konsumen `backup_inventory` selain Dify/FastAPI :8443 dan tim lain? Apakah ada yang bergantung pada kolom `id`?
6. Boleh perbaikan cepat lewat CR: mapping hari di loader (D2) dan single-instance loader (D3)?
7. Mohon output read-only: `schtasks /query /fo LIST /v` (filter task loader), untuk memastikan penyebab D3.
