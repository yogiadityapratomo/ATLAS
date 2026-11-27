# Fase 5 — Quality Report: ATLAS v0.1.0

| | |
|---|---|
| Versi | 0.1 (interim — hasil soak 72 jam menyusul) |
| Tanggal | 2026-11-27 |
| Rilis diuji | `v0.1.0` (commit `7777319`) |
| Lingkungan | DEV laptop: Windows 11, Python 3.13.15, PostgreSQL 18.7 lokal |

## 1. Ringkasan

| Area | Hasil | Status |
|---|---|---|
| Test otomatis (unit + integrasi DB + API) | 153 lulus, 0 gagal | ✅ |
| Regresi kapasitas vs web V4 | JSON `/api/data` identik byte-per-byte dengan cache V4 (35 disk pool, 4 tape) | ✅ |
| Regresi Backup Inventory vs bot `check_v2` asli | 2.435/2.435 baris identik (14 kolom); perbedaan hanya 2 perbaikan bug yang disetujui | ✅ |
| Integrasi dengan mock NBU (HTTP sungguhan + gangguan) | Uji singkat 7 menit lulus; status PARTIAL saat master mati tertangani | ✅ |
| Soak test 72 jam | Berjalan sejak 2026-11-27 09:43, selesai ±2026-11-30 09:44 | ⏳ |

## 2. Test otomatis

```
.venv\Scripts\python.exe -m pytest      → 153 passed (2026-11-27, main @ 9e37fdd)
.venv\Scripts\python.exe -m ruff check  → All checks passed!
```

| Kelompok | Isi utama |
|---|---|
| Unit | config & secret, filter secret log, ID error, pool DB (event koneksi), penulis audit (DB mati, antrean penuh), klien NBU (rate limit, retry per halaman, Retry-After, deadline, lanjutan tape), parser policy (hari 1 = Minggu), transformasi kapasitas, cache ber-versi |
| Integrasi DB (`atlas_test`) | migrasi (checksum, idempoten, gagal = tanpa perubahan), 20 kombinasi hak akses role, partisi & retensi, job (lock paralel, rollback, run yatim), import CMDB berbasis diff, `NOTIFY` |
| API | kontrak JSON V4, ETag/304, export Excel, health, pencarian inventory (sebagian, `_` literal, per aplikasi, host tanpa backup), audit (keyset, filter, CSV), 100 ribu event < 1 dtk |

## 3. Kinerja (DEV, data asli)

| Operasi | Hasil | Target |
|---|---|---|
| Cari 50 hostname | 21–70 ms | < 1 dtk |
| Saran aplikasi / cari per aplikasi | 11 ms / 62 ms | < 1 dtk |
| Filter Audit Log, 100 ribu event | 13–14 ms (ringkasan 266 ms) | < 1 dtk |
| Muat backup inventory (7.534 baris) | 1,4 dtk; muat ulang tanpa perubahan 0,6 dtk & **0 baris ditulis** | — |
| Import CMDB (14.185 baris) | 2,2 dtk; impor ulang **0 baris ditulis** | — |

## 4. Soak test 72 jam

Alat: [`scripts/dev/soak.py`](../scripts/dev/soak.py) + [`scripts/dev/mock_nbu.py`](../scripts/dev/mock_nbu.py).

| Komponen | Konfigurasi |
|---|---|
| Mock NBU | 3 master, data dari cache V4 (35 disk pool, 1.654 tape, paginasi asli); 3% request dijawab 503 + `Retry-After`; master BRN tidak menjawab 2 menit setiap 47 menit |
| Web | uvicorn port 8002, dipantau tiap 30 dtk: `/api/data`, `/api/health`, cari 3 hostname, `/api/audit/events` |
| Job | kapasitas live tiap 10 menit; inventory tiap 15 menit (setiap run ke-4 satu schedule diubah → update + refresh MV + NOTIFY); CMDB tiap 6 jam; maintenance tiap 24 jam |

**Kriteria lulus:** ketersediaan setiap endpoint ≥ 99,9%; p95 < 1 dtk; memori web tumbuh < 20%; tidak ada job exit ≠ 0 (PARTIAL karena master mati yang disengaja = perilaku benar).

Hasil uji singkat (7 menit, `logs/soak/smoke`): semua endpoint 100%, p95 ≤ 43 ms, semua job exit 0, kapasitas PARTIAL 1× (BRN mati disengaja). **LULUS.**

Hasil 72 jam: *menyusul* (`.venv\Scripts\python.exe scripts\dev\soak.py --report logs\soak\20261127_0943`).

## 5. Yang belum tercakup (masuk Fase 7 staging)

- Akses nyata ke master NBU (butuh token read-only & CR) — di DEV live NBU diblok.
- Restart service PostgreSQL di tengah jalan (butuh hak admin Windows); perilaku DB mati sudah diuji di level unit/integrasi.
- Beban banyak user bersamaan (tim 3 user; tidak diprioritaskan).
