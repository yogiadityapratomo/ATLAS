# Alur Pengembangan & Deployment ATLAS

Turunan dari [SYSTEM_DESIGN_PRODUCTION_GUIDE_CLAUDE.md](../reference/SYSTEM_DESIGN_PRODUCTION_GUIDE_CLAUDE.md) §10–§12, §16, §20, disesuaikan dengan infrastruktur ATLAS: Windows Server + NSSM + Task Scheduler, tanpa Docker. Docker dan Kubernetes belum dibutuhkan (guide §7).

> Dokumen ini wajib diikuti untuk **setiap** perubahan yang menuju server. Deviasi harus dicatat di decision log charter.

---

## 1. Environment

| Env | Lokasi | Bot Telegram | Data NBU | Tujuan |
|---|---|---|---|---|
| **DEV** | Laptop (`D:\bot\ATLAS`) | Bot uji (token terpisah) | Mock NBU lokal; baca-saja ke master hanya jika disetujui | Coding, unit test, test integrasi |
| **STAGING** | Server bot, `C:\SBM\ATLAS-staging\` | Bot uji (token terpisah) | Salinan cache produksi + collector mode delta (rate rendah) | Smoke test, UAT, soak test 72 jam |
| **PROD** | Server bot, `C:\SBM\ATLAS\` | Bot produksi | Collector produksi | Dipakai user |

Aturan:
- Secret per environment ada di `.env` masing-masing (tidak di-commit). Bot uji dan bot produksi **tidak boleh** memakai token yang sama.
- **Kontrak data:** di PROD, collector menulis ke path yang dibaca proses DB (`C:\SBM\NetbackupBotV2\cache\policy_cache.json`) atau path baru yang sudah disepakati dengan pemilik proses DB. Path diatur lewat config, bukan hardcode.
- STAGING tidak boleh menulis ke cache PROD.

## 2. Struktur folder di server (PROD dan STAGING sama)

```
C:\SBM\ATLAS\
├── releases\
│   ├── v3.0.0\          # isi tag Git + venv sendiri
│   └── v3.0.1\
├── current  -> releases\v3.0.1     (junction; NSSM menunjuk ke sini)
└── shared\
    ├── .env             # secret & config environment ini
    ├── state\           # SQLite state store collector
    └── logs\            # log JSON berotasi
```

Rollback = arahkan `current` ke rilis sebelumnya, lalu restart service. Hitungannya menit, bukan jam.

## 3. Alur perubahan kode (guide §11)

```
branch fitur/perbaikan → commit kecil + test lokal
        → Pull Request ke main (GitHub private ATLAS)
        → review (code-review Claude + owner) + bukti test
        → merge ke main
        → tag rilis vX.Y.Z + CHANGELOG
        → paket rilis (zip dari tag + requirements terkunci + checksum)
        → deploy STAGING → smoke test + UAT
        → CR disetujui → deploy PROD → health check → pantau
```

| Aturan | Keterangan |
|---|---|
| Tidak push langsung ke `main` untuk kode | Mulai Fase 3, semua perubahan kode lewat branch + PR. (Commit dokumen Fase 1 langsung ke `main` sebelum aturan ini berlaku.) |
| Nama branch | `feat/<ringkas>`, `fix/<ringkas>`, `docs/<ringkas>`, `chore/<ringkas>` |
| Pesan commit | Kalimat jelas dalam bahasa Indonesia; satu perubahan logis per commit |
| Versi | Semantic versioning: `MAJOR.MINOR.PATCH` (v3.x untuk ATLAS) |
| CI | Fase 6: GitHub Actions menjalankan lint + `pytest` di setiap PR. Sebelum CI ada, output test lokal ditempel di PR |
| Bukti | Setiap PR berisi command test dan hasilnya yang **benar-benar dijalankan** |

## 4. Prosedur deploy (guide §12 — strategi *recreate* dengan rollback cepat)

Semua langkah di server ditulis di runbook rilis. Setiap langkah ditandai **[READ-ONLY]** atau **[CHANGE]**. Langkah [CHANGE] hanya boleh dijalankan setelah CR disetujui.

### 4.1 Sebelum deploy
1. [READ-ONLY] Versi rilis jelas (tag), CHANGELOG terisi, test lulus, UAT staging ditandatangani.
2. [READ-ONLY] Nomor CR dan jendela waktu disetujui; user bot diberi tahu jika ada downtime.
3. [READ-ONLY] Pre-check server: disk kosong, service status, umur cache, tidak ada run collector yang sedang berjalan.
4. [CHANGE] Backup: salin `shared\.env`, `shared\state\`, dan `cache\policy_cache.json` ke folder backup bertanggal.

### 4.2 Deploy
5. [CHANGE] Ekstrak paket ke `releases\vX.Y.Z\`, verifikasi checksum, buat venv, lalu `pip install -r requirements.lock`.
6. [CHANGE] Jalankan self-check rilis (`python -m atlas.selfcheck`: config valid, koneksi DB/state, akses cache) **sebelum** switch.
7. [CHANGE] Arahkan junction `current` ke rilis baru, lalu `nssm restart` service ATLAS (bot, kemudian collector).

### 4.3 Setelah deploy (health check & smoke test)
8. [READ-ONLY] Service `RUNNING`; heartbeat bot dan collector segar (< 2 menit).
9. [READ-ONLY] `/status` di bot menjawab; umur cache sesuai target; tidak ada ERROR baru di `errors.log` selama 15 menit.
10. [READ-ONLY] Smoke test: Search 1 hostname yang diketahui, dan Collect All; bandingkan dengan output rilis sebelumnya.
11. Catat hasil di release record (template: [release-checklist.md](../templates/release-checklist.md)).

### 4.4 Rollback (jika langkah 8–10 gagal, atau ada error kritis dalam 24 jam)
1. [CHANGE] Arahkan `current` ke rilis sebelumnya, lalu `nssm restart` service ATLAS.
2. [CHANGE] Jika format state berubah, pulihkan `shared\state\` dari backup langkah 4.
3. [READ-ONLY] Ulangi health check 8–10.
4. Catat insiden dan penyebabnya; perbaikan masuk lewat PR baru.

Selama transisi dari v2: rollback darurat = hentikan service ATLAS, lalu jalankan kembali service v2 (`NetbackupTelegramBotV4`) dan task collector v2 yang **tidak dihapus** sampai ATLAS stabil minimal 2 minggu.

## 5. Larangan

- Tidak ada deploy PROD tanpa CR dan approval eksplisit owner.
- Tidak mengedit file langsung di server (hotfix pun lewat branch → PR → tag → deploy).
- Tidak menyimpan secret di repo, di log, atau di dokumen.
- Tidak memakai `taskkill /IM python.exe`; restart hanya per service lewat NSSM.
- Tidak menjalankan STAGING terhadap cache atau state PROD.

## 6. Definition of Done (guide §20)

Sebuah perubahan selesai jika:
- requirement dan acceptance criteria terpenuhi;
- sesuai design yang disetujui;
- tidak merusak fitur existing (test regresi lulus);
- error handling dan logging ada;
- test relevan lulus, dengan bukti di PR;
- secret aman;
- dokumentasi (README, runbook, CHANGELOG) diperbarui;
- review selesai;
- sudah lolos STAGING sebelum PROD.
