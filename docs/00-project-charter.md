# Project Charter — ATLAS (NetBackup Telegram Bot v3)

| | |
|---|---|
| Versi | 0.1 (draft) |
| Tanggal | 2026-11-24 |
| Baseline proses | `SYSTEM_DESIGN_PRODUCTION_GUIDE_CLAUDE.md` |
| Fase aktif | **Fase 4 — Development**: PR-0–PR-2 merged (2026-11-26); PR-3 `feat/capacity-db`, PR-4, PR-5 berjalan. Fase 1–3 selesai ([plan](04-implementation-plan.md)) |

## 1. Latar belakang

Bot Telegram "NetBackup Assistant" dipakai tim Storage & Backup untuk dua hal: mencari konfigurasi backup per hostname dan mengunduh report seluruh policy. Bot sering nyangkut atau tidak merespons dan harus di-restart manual 3–8 kali per hari. Collector cache juga sering gagal dan ikut membebani master NetBackup.

## 2. Tujuan dan ukuran keberhasilan

| Tujuan | Ukuran keberhasilan (usulan, perlu disepakati) |
|---|---|
| Bot stabil | Restart manual ≤ 1 per bulan; bot otomatis pulih dari gangguan proxy/jaringan tanpa intervensi |
| Data cache selalu tersedia dan segar | Cache tidak pernah rusak/kosong; umur data ≤ 15 menit (target lanjut: ≤ 2 menit via delta audit log) |
| Beban ke master NBU wajar | Tidak ada run collector ganda; request ke NBU turun ≥ 90% dibanding sekarang; nol 503 akibat collector |
| Error terdeteksi sebelum user komplain | Setiap error punya ID, tercatat di log terstruktur, dan memicu alert ke admin |
| Data report benar | Report Collect All dan Search menampilkan hari backup yang sama dan benar |
| Aman | Tidak ada secret di kode/log; token lama dirotasi |

## 3. Scope

**Termasuk:**
- `update_cachev2.py` (collector cache), `telegram_botv2.py` (bot), `check_v2.py` (search hostname), `convert_policy_cache.py` (report lengkap).
- Restart/operasional bot: NSSM service, Task Scheduler collector, skrip restart manual, logging, alerting, runbook.
- **Web dashboard (ditambahkan 2026-11-24):** web existing milik owner + fitur baru, termasuk healthcheck bot Telegram dan collector. Detail menunggu kode web diterima dan diassessment.

**Tidak termasuk:**
- Proses insert ke database (`convert_policy_cache_autoupdatedb.py` dan skrip lain), FastAPI :8443, Dify.
- Namun **kontrak `cache/policy_cache.json` (path dan struktur) wajib tetap**, karena proses DB membacanya.

## 4. Peran

| Peran | Siapa | Tanggung jawab |
|---|---|---|
| Project owner | Yogi (tim Storage & Backup) | Keputusan scope, approval tiap fase, CR |
| User bot | 3 user terdaftar (tim Storage & Backup) | UAT |
| Engineering assistant | Claude Code | Assessment, design, implementasi, test sesuai approval |
| Admin server / CAB | [M] perlu ditentukan | Approval CR untuk perubahan di server production |

## 5. Roadmap (mengikuti guide §17)

| Fase | Fokus | Output | Status |
|---|---|---|---|
| 0 | Quick wins darurat (CR) | Restart aman, collector single instance, rotasi token | Usulan — menunggu keputusan |
| 1 | Assessment | [01-assessment-report.md](01-assessment-report.md) | **Draft selesai — review** |
| 2 | Requirement & design | PRD, design doc, kontrak data, logging spec, test strategy | Belum |
| 3 | Implementation plan | Daftar task, file, test, rollback | Belum |
| 4 | Development | Collector v3, modul report, bot v3 | Belum |
| 5 | Quality | Unit/regression test, integrasi dengan mock NBU, soak test 72 jam | Belum |
| 6 | CI | Pipeline lint + test (jika GitLab + runner tersedia) | Belum |
| 7 | Staging | Jalan paralel dengan bot uji di server yang sama | Belum |
| 8 | Production | CR, cutover via NSSM/Task Scheduler, health check, rollback siap | Belum |
| 9 | Operations | Runbook, monitoring, ringkasan harian | Belum |

## 6. Decision log

| Tanggal | Keputusan | Oleh |
|---|---|---|
| 2026-11-20 | Scope bot dibatasi ke 4 file; proses insert DB di luar scope | Owner |
| 2026-11-20 | Skrip restart `.bat` adalah tindakan manual saat bot nyangkut (gejala, bukan penyebab) | Owner |
| 2026-11-20 | `Backup Inventory.py` tidak dipakai (identik dengan `update_cachev2.py`) | Owner |
| 2026-11-24 | Proyek dijalankan mengikuti baseline `SYSTEM_DESIGN_PRODUCTION_GUIDE_CLAUDE.md` | Owner |
| 2026-11-24 | Kode v3 ditulis di repo baru `D:\bot\ATLAS` (GitHub private `yogiadityapratomo/ATLAS`); v2 tidak diubah dan menjadi jalur rollback | Owner |
| 2026-11-24 | Nama proyek dan repo: **ATLAS** | Owner |
| 2026-11-24 | **Scope diperluas:** ATLAS mencakup web dashboard milik owner (fitur ditambahkan ke web yang sudah ada); bot Telegram menjadi bagian dashboard, termasuk halaman healthcheck proses bot & collector. Pengembangan dimulai di DEV lokal (laptop). Web akan diassessment dulu (adendum Fase 1) sebelum design | Owner |
| 2026-11-24 | Semua deployment wajib mengikuti `docs/process/deployment-workflow.md` (turunan guide §10–12, §16, §20). Deviasi dari guide: Windows + NSSM tanpa Docker; GitHub (bukan GitLab) untuk repo/PR/CI | Owner |
| 2026-11-26 | Nama database: `atlas` (lowercase, permintaan "ATLAS"); DB baru di cluster yang sama, `dbbackup` tidak diubah (opsi A) | Owner |
| 2026-11-26 | `dbbackup` diisi `convert_policy_cache_autoupdatedb.py` dari `policy_cache.json`; `server_inventory` diimport manual | Owner |
| 2026-11-26 | **Semua menu dashboard berbasis database**; tambah menu Backup Inventory (cari hostname & aplikasi) | Owner |
| 2026-11-26 | Design [03](03-design-db-dashboard.md) disetujui ("iya"). Pertanyaan §10 yang tidak dijawab spesifik memakai usulan: hari jadwal dibenarkan (1 = Minggu), `schedule_days` diisi, cari hostname **cocok sebagian** (sama dengan bot), host tanpa backup ditampilkan, retensi kapasitas 90 hari + 1 snapshot/hari, CMDB dari OSPLA *Master Inventory*. Dapat diubah owner | Owner (default usulan) |
| 2026-11-26 | Migrasi schema memakai file SQL murni + `scripts/db/migrate.py` (deviasi dari contoh Alembic di guide; tanpa ORM) | Owner (bagian design) |
| 2026-11-26 | Driver DB: psycopg 3 + psycopg_pool | Usulan plan [04](04-implementation-plan.md) |
| 2026-11-26 | Plan [04](04-implementation-plan.md) disetujui ("lanjut"), dengan tambahan: **audit & event log** untuk koneksi DB, web, job, dan event lain + menu Audit Log ([05](05-design-audit-log.md)). Urutan PR disesuaikan: fondasi (audit termasuk) → kapasitas ke DB → Backup Inventory → menu Audit Log | Owner |
| 2026-11-26 | Owner: "jalankan yang paling direkomendasikan" → PR-2 dikerjakan di branch `feat/db-foundation` (bertumpuk di PR-1) selama PR-0/PR-1 menunggu review; merge tetap berurutan | Owner |
| 2026-11-26 | CMDB disimpan **satu baris per isi unik** + kolom `occurrences` (kunci `row_hash`), karena tidak ada kombinasi kolom yang unik (hostname sama di beberapa site; 282 baris kembar persis). Jumlah baris asli tetap 14.185 | Usulan PR-2 (implementasi design 03 §4.1) |
| 2026-11-26 | `V001` hanya berisi core/audit/cmdb/report; `capacity.*` (V002) dan `nbu.*` (V003) ikut PR yang memakainya | Usulan PR-2 (penyesuaian plan 04) |
| 2026-11-26 | PR #1–#3 disetujui owner ("di approve aja semuanya") dan di-merge ke `main` | Owner |
| 2026-11-27 | Owner: "lanjut … pr semuanya" → PR-3, PR-4, PR-5 dikerjakan berurutan (bertumpuk), merge tetap menunggu approval | Owner |
| 2026-11-27 | Web ATLAS tidak memicu fetch live ke NBU (`POST /api/generate` = 403); collect gagal total tidak mengosongkan dashboard | Usulan PR-3 (perlu konfirmasi owner saat review) |
| 2026-11-27 | Backup Inventory mengikuti logika Search bot, dengan 2 perbaikan bug bot: policy `storage = null` tetap tampil; kata kunci sebagian yang ditemukan tidak dilaporkan "Not Available". Regresi vs bot asli: 2.435/2.435 baris identik | Usulan PR-4 (perlu konfirmasi owner saat review) |
| 2026-11-27 | Retensi riwayat kapasitas default **simpan semua** (±2 juta baris/tahun); usulan design "90 hari + 1 snapshot/hari" ditunda sampai dibutuhkan. Audit 180 hari | Usulan PR-5 (perlu konfirmasi owner saat review) |

## 7. Pertanyaan terbuka

Daftar lengkap ada di [assessment §8](01-assessment-report.md#8-pertanyaan-yang-membutuhkan-keputusan-owner).
