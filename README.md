# ATLAS — Restrukturisasi Bot Telegram NetBackup (v3)

Proyek restrukturisasi bot Telegram "NetBackup Assistant" (cari backup per hostname dan report policy lengkap) agar stabil, mudah dipantau, dan aman, mengikuti baseline `SYSTEM_DESIGN_PRODUCTION_GUIDE_CLAUDE.md`.

## Status

| Fase | Nama | Status |
|---|---|---|
| 1 | Discovery / Assessment | **Selesai (draft) — menunggu review** |
| 2 | Requirement & Design | Belum mulai |
| 3 | Implementation Plan | Belum mulai |
| 4–9 | Development → Operations | Belum mulai |

Detail fase, keputusan, dan pertanyaan terbuka: [docs/00-project-charter.md](docs/00-project-charter.md).

## Dokumen

| Dokumen | Isi |
|---|---|
| [docs/00-project-charter.md](docs/00-project-charter.md) | Tujuan, scope, roadmap, status fase, decision log |
| [docs/01-assessment-report.md](docs/01-assessment-report.md) | Hasil Fase 1: kondisi aktual, temuan & risiko, arsitektur target, pertanyaan |
| [docs/process/deployment-workflow.md](docs/process/deployment-workflow.md) | **Alur wajib** pengembangan & deployment (DEV → STAGING → PROD, rollback, DoD) |
| [docs/process/dev-setup.md](docs/process/dev-setup.md) | Setup environment DEV lokal (Git, Python, PostgreSQL 18) |
| [docs/templates/release-checklist.md](docs/templates/release-checklist.md) | Template release record per rilis |
| [docs/reference/](docs/reference/) | Baseline: system design & production guide, referensi arsitektur |

## Alat diagnostik (read-only)

| Skrip | Fungsi |
|---|---|
| [scripts/diagnostics/nbu_auditlog_dump.py](scripts/diagnostics/nbu_auditlog_dump.py) | Tarik audit log NBU (`GET /security/auditlogs`) sampai offset terakhir; retry, resume, filter |
| [scripts/diagnostics/nbu_auditlog_to_excel.py](scripts/diagnostics/nbu_auditlog_to_excel.py) | Ubah hasil dump menjadi Excel (ringkasan, perubahan policy, detail perubahan) |

Token dibaca dari environment variable `NBU_TOKEN`, tidak pernah ditulis di skrip.

## Baseline (v2)

Kode bot yang berjalan saat ini: `C:\SBM\NetbackupBotV2` di server bot (salinan analisis: `D:\bot\NetbackupBotV2`, per 2026-11-20). Folder itu tidak diubah oleh proyek ini.
