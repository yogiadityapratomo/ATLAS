# CLAUDE.md — NetBackup Bot v3 (proyek restrukturisasi)

Baseline proses: `SYSTEM_DESIGN_PRODUCTION_GUIDE_CLAUDE.md` (SDLC bertahap + approval per fase).
Status fase saat ini ada di [docs/00-project-charter.md](docs/00-project-charter.md) — selalu baca dulu sebelum bekerja.

## Aturan kerja wajib

1. Kerjakan satu fase pada satu waktu. Jangan lanjut ke fase berikutnya tanpa approval eksplisit dari project owner.
2. Fase 1–3 hanya menghasilkan dokumen. Kode production baru boleh ditulis mulai Fase 4, setelah implementation plan disetujui.
3. Jangan berasumsi; verifikasi dari kode, log, atau data. Tandai setiap temuan sebagai **[V] terverifikasi**, **[A] asumsi**, atau **[M] informasi belum ada**.
4. Pertahankan perilaku existing kecuali perubahannya disetujui (lihat daftar perbedaan perilaku di design doc).
5. Jangan pernah menulis, mencetak, atau meng-commit secret (token bot Telegram, API key NetBackup, password DB). Gunakan `.env` (tidak di-commit) dan `.env.example`.
6. Server production (bot server `C:\SBM\NetbackupBotV2`, master NetBackup) hanya untuk perintah **read-only**. Perintah yang mengubah state ditandai **CHANGE — butuh CR** dan dipisahkan.
7. Laporkan command test dan hasil sebenarnya. Jangan klaim lulus/berhasil jika belum dijalankan.
8. Tidak ada deploy ke production tanpa CR dan approval eksplisit.

## Fakta proyek yang harus dijaga

- Scope bot = 4 file: `update_cachev2.py`, `telegram_botv2.py`, `check_v2.py`, `convert_policy_cache.py` (baseline v2 di `D:\bot\NetbackupBotV2`, salinan per 2026-11-20 — read-only, jangan diubah, berisi secret).
- **Kontrak data:** `cache/policy_cache.json` (path + struktur `{"policies": [...], "slps": {...}}`) juga dibaca proses insert DB di luar scope. Format ini tidak boleh berubah.
- `dayOfWeek` NetBackup: 1 = Minggu … 7 = Sabtu (terbukti dari audit log, lihat assessment §Lampiran B).
- Runtime: Windows Server, Python 3.13, NSSM (`NetbackupTelegramBotV4`), Task Scheduler, keluar internet via proxy `prelly.telkomsel.co.id:8080`; akses ke master NBU tanpa proxy.
- Master NBU (tbs/bsd/brn) adalah sistem kritis: semua akses API harus rate-limited, dengan backoff saat 503, dan retry melanjutkan halaman yang gagal (bukan dari offset 0).

## Struktur repo

- `docs/` — dokumen per fase (charter, assessment, design, plan, runbook).
- `scripts/diagnostics/` — alat read-only (dump audit log NBU, konversi ke Excel).
- `src/`, `tests/` — dibuat mulai Fase 3/4.
