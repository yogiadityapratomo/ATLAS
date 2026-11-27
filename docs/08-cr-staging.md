# Change Request (DRAFT) — Deploy ATLAS ke STAGING

| | |
|---|---|
| No. CR | [M] diisi setelah diajukan |
| Status | **DRAFT — belum diajukan; belum ada langkah di server** |
| Pemohon | Owner proyek ATLAS (tim Storage & Backup) |
| Approver / CAB | [M] belum ditentukan (charter §4) |
| Rilis | `v0.1.x` (paket dari tag, dibuat `scripts/release/build_release.py`) |
| Jenis | Normal change — **tambahan paralel**, tidak mengubah komponen production |
| Risiko | Rendah (lihat §8) |
| Usulan jendela | [M] hari kerja, di luar jam sibuk backup; durasi ±60 menit |
| Acuan | [deployment-workflow](process/deployment-workflow.md), [runbook](06-runbook-atlas.md), [quality report](07-quality-report.md) |

## 1. Tujuan

Menjalankan dashboard ATLAS di server bot sebagai **STAGING**, berdampingan dengan web V4 dan bot v2, untuk smoke test dan UAT oleh 3 user tim Storage & Backup sebelum CR production.

## 2. Ruang lingkup

| Termasuk | Tidak termasuk |
|---|---|
| Folder `C:\SBM\ATLAS-staging\` (releases, shared, current) | Mengubah/menghentikan web V4, bot v2, collector v2, `scheduled_collect.py` |
| Database baru `atlas_staging` + 5 role ATLAS di cluster PostgreSQL server | Mengubah database `dbbackup` atau loader-nya |
| 1 service NSSM `ATLAS-staging-web`; 4 task Task Scheduler `ATLAS-staging-*` | Akses live ke master NBU (tetap via collector V4) |

### Keputusan desain: staging **tidak menambah beban ke master NBU**

| Data | Sumber di staging | Akses |
|---|---|---|
| Kapasitas disk pool & tape | JSON hasil collector V4 (`capacity_cache.json`, `tape_cache.json`) diimpor tiap 10 menit — file yang tidak berubah dilewati | **Baca saja** |
| Backup inventory | `C:\SBM\NetbackupBotV2\cache\policy_cache.json` | **Baca saja** (kontrak tidak berubah) |
| CMDB | Excel OSPLA *Master Inventory* (impor manual) | — |

Collect live dari master NBU (`ATLAS_ALLOW_LIVE_NBU=1`) baru diaktifkan di CR **production**, sekaligus menggantikan collector V4 — sehingga jumlah request ke master tidak pernah berlipat.

## 3. Prasyarat (harus lengkap sebelum CR diajukan)

| # | Prasyarat | Status |
|---|---|---|
| P1 | Approver/CAB CR ditentukan | [M] |
| P2 | Akun DBA (superuser PostgreSQL) tersedia untuk `bootstrap.py` — dijalankan DBA, password tidak dibagikan | [M] |
| P3 | Port web staging (usulan `8011`) dan cara akses 3 user UAT (bind `0.0.0.0` + firewall dari subnet tim, atau via jump host) | [M] — samakan dengan cara web V4 diakses |
| P4 | Path folder V4 di server (letak `cache\capacity_cache.json`) | [M] |
| P5 | Excel OSPLA terbaru untuk impor CMDB | [M] |
| P6 | Fase 5 lulus: soak 72 jam ([07](07-quality-report.md)), CI hijau | ⏳ |
| P7 | Keputusan penomoran versi: workflow menulis `v3.x`, rilis saat ini `v0.1.x` (lihat §9) | [M] |

## 4. Pre-check — semua **[READ-ONLY]**

```powershell
python --version                                             # harapan: Python 3.13.x
& "C:\Program Files\PostgreSQL\18\bin\psql.exe" --version    # harapan: 18.x
Get-PSDrive C | Select-Object Used, Free                     # sisa disk ≥ 2 GB
Get-Service postgresql*, NetbackupTelegramBotV4 | Format-Table Name, Status
Get-ScheduledTask | Where-Object TaskName -match "Netbackup|Capacity|ATLAS" | Format-Table TaskName, State
Get-NetTCPConnection -LocalPort 8011 -ErrorAction SilentlyContinue   # harapan: kosong (port bebas)
Get-Item "<P4>\cache\capacity_cache.json", "C:\SBM\NetbackupBotV2\cache\policy_cache.json" | Format-Table Name, Length, LastWriteTime
# di psql (DBA): SHOW log_statement;  → harus 'none' atau 'mod' (bootstrap menolak 'all'/'ddl')
```

Simpan output pre-check di release record.

## 5. Langkah — semua **[CHANGE]**, hanya setelah CR disetujui

| # | Langkah | Perintah / catatan |
|---|---|---|
| 1 | Salin paket rilis ke `C:\SBM\ATLAS-staging\incoming\atlas-vX.Y.Z\` lalu verifikasi | `python verify_release.py <folder>` → "semua cocok" (jika tidak: **stop**) |
| 2 | Ekstrak ke `releases\vX.Y.Z\`, buat venv **offline** | `python -m venv .venv`; `.venv\Scripts\pip install --no-index --find-links <paket>\wheels -r <paket>\requirements.lock setuptools`; `pip install --no-index --find-links <paket>\wheels --no-build-isolation --no-deps -e .` |
| 3 | Buat `shared\.env` dari `.env.example` | `ATLAS_ENV=staging`, `ATLAS_DB_NAME=atlas_staging`, `ATLAS_LOG_DIR=C:\SBM\ATLAS-staging\shared\logs`, `ATLAS_CACHE_DIR=...\shared\cache`, `ATLAS_POLICY_CACHE=C:\SBM\NetbackupBotV2\cache\policy_cache.json`, `ATLAS_ALLOW_LIVE_NBU=0`. Set variabel sistem `ATLAS_ENV_FILE=C:\SBM\ATLAS-staging\shared\.env`. ACL file: hanya akun service + admin |
| 4 | DBA: role & database | `$env:PGPASSWORD=<DBA>`; `python scripts\db\bootstrap.py --database atlas_staging --generate-missing-passwords` (password acak masuk `shared\.env`, tidak dicetak) |
| 5 | Schema | `python scripts\db\migrate.py --dry-run` → periksa daftar versi → `python scripts\db\migrate.py` |
| 6 | Junction | `New-Item -ItemType Junction -Path C:\SBM\ATLAS-staging\current -Target ...\releases\vX.Y.Z` |
| 7 | **Self-check** (gerbang) | `python -m atlas.selfcheck` dari `current` → harus **SIAP**; jika GAGAL: **stop**, lanjut §7 rollback |
| 8 | Data awal | `python -m atlas.collectors.cmdb_import --xlsx <P5>`; `python -m atlas.collectors.inventory_job`; `python -m atlas.collectors.capacity_job --from-json <P4>\cache`; `python -m atlas.collectors.maintenance_job` |
| 9 | Service web | `nssm install ATLAS-staging-web <current>\.venv\Scripts\python.exe "-m uvicorn atlas.web.main:app --host <P3> --port 8011"`, AppDirectory `<current>`, env `ATLAS_ENV_FILE`, start otomatis |
| 10 | Task Scheduler | `ATLAS-staging-capacity` (tiap 10 menit, `--from-json <P4>\cache`), `ATLAS-staging-inventory` (tiap 15 menit), `ATLAS-staging-maintenance` (harian 02:00); akun service non-admin; "do not start a new instance" (lapis kedua selain advisory lock) |

## 6. Verifikasi setelah deploy — **[READ-ONLY]**

1. `GET http://<host>:8011/api/health` → `db: ok`; umur data kapasitas < 30 menit setelah task pertama.
2. Dashboard Disk Pool & Tape: total TB, jumlah tape, dan persen **sama** dengan web V4 untuk waktu data yang sama.
3. Backup Inventory: cari 5 hostname yang dikenal → bandingkan dengan Search bot (beda yang sudah disetujui: hari 1 = Minggu, 2 perbaikan bug).
4. Audit Log: event `job_finished` untuk tiap task; tidak ada `error`/`critical` selama 30 menit.
5. Web V4 dan bot v2 tetap berjalan normal (service `RUNNING`, data V4 tetap segar).

### UAT (3 user, ±3 hari kerja)

| Skenario | Diterima jika |
|---|---|
| Buka dashboard kapasitas, export Excel, capture gambar | Sama dengan V4 |
| Cari daftar hostname dari pekerjaan nyata; export | Hasil sesuai, Excel terbaca |
| Cari per aplikasi | Host tanpa backup terlihat |
| Kirim ID error (jika ada) ke admin | Ditemukan di Audit Log |

## 7. Rollback (≤ 15 menit, tidak memengaruhi production)

1. [CHANGE] `nssm stop ATLAS-staging-web`; `nssm remove ATLAS-staging-web confirm`.
2. [CHANGE] Nonaktifkan/hapus task `ATLAS-staging-*`.
3. [CHANGE] (DBA, opsional) `DROP DATABASE atlas_staging;` — `dbbackup` tidak tersentuh.
4. [READ-ONLY] Pastikan web V4, bot v2, dan collector v2 tetap `RUNNING` dan datanya segar.

## 8. Risiko & mitigasi

| Risiko | Kemungkinan | Mitigasi |
|---|---|---|
| Beban tambahan ke master NBU | Nihil | Staging tidak mengakses NBU (§2) |
| Beban ke cluster PostgreSQL yang juga melayani `dbbackup` | Rendah | Volume kecil (±7.500 baris inventory, diff-only); `statement_timeout` & `connection limit` per role; pool web 2–5 koneksi |
| Membaca `policy_cache.json` saat sedang ditulis collector bot | Sedang | JSON tidak valid → job gagal aman (transaksi), dicoba lagi 15 menit kemudian; tidak pernah menulis file itu |
| Port staging terbuka terlalu luas | Rendah | Bind/firewall hanya subnet tim (P3) |
| Secret bocor | Rendah | `shared\.env` dengan ACL; filter secret di log/audit; `verify_release.py` memastikan paket utuh |

## 9. Deviasi dari deployment-workflow (perlu keputusan owner)

| Workflow | ATLAS staging | Alasan |
|---|---|---|
| `shared\state\` (SQLite state store collector) | Tidak dipakai | State ada di PostgreSQL (`core.collect_run`, advisory lock) |
| Versi `v3.x` | Rilis saat ini `v0.1.x` | Usulan: tetap `v0.x` selama staging; rilis production pertama = `v3.0.0` |
| STAGING: "collector mode delta (rate rendah)" | Impor JSON collector V4 | Nol request tambahan ke master; collector delta belum dibuat (design terpisah) |
| Langkah 7 workflow: restart bot & collector | Hanya service web + task job | Bot v3 belum dibuat; rilis ini hanya dashboard |

## 10. Persetujuan

| Peran | Nama | Keputusan | Tanggal |
|---|---|---|---|
| Owner | | | |
| Approver/CAB | | | |
| DBA (langkah 4 & rollback 3) | | | |
