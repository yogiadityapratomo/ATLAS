# Setup Environment DEV Lokal (Laptop)

Bagian dari [deployment-workflow.md](deployment-workflow.md) §1 (environment DEV). Semua komponen berjalan di laptop dan tidak menyentuh server production.

## Prasyarat terpasang

| Komponen | Versi | Cara pasang | Catatan |
|---|---|---|---|
| Git | 2.56.1 | `winget install --id Git.Git -e` | Identitas commit diset per repo (noreply GitHub), bukan global |
| Python | 3.13.x | (sudah ada) | Sama dengan server bot (Python 3.13) |
| PostgreSQL | **18.7** | `winget install --id PostgreSQL.PostgreSQL.18 -e` (mode unattended, tanpa Stack Builder) | Versi mayor sama dengan server `dbbackup` (PostgreSQL 18) |

## Konfigurasi PostgreSQL DEV

| Item | Nilai |
|---|---|
| Service | `postgresql-x64-18` (Automatic) |
| Port | 5432 |
| `listen_addresses` | `localhost` (diset lewat `ALTER SYSTEM`, berlaku setelah restart service) → hanya `127.0.0.1` dan `::1` |
| `pg_hba.conf` | Hanya `127.0.0.1/32` dan `::1/128`, `scram-sha-256` (default installer) |
| Firewall | Tidak ada aturan masuk untuk PostgreSQL |
| Superuser | `postgres`; password acak 24 karakter di `%USERPROFILE%\.atlas\pg_postgres_password.txt` (izin hanya untuk akun Windows pemilik; **tidak** di repo) |
| psql | `"C:\Program Files\PostgreSQL\18\bin\psql.exe"` |

Contoh koneksi tanpa mengetik password di layar:

```powershell
$env:PGPASSWORD = (Get-Content "$env:USERPROFILE\.atlas\pg_postgres_password.txt" -Raw).Trim()
& "C:\Program Files\PostgreSQL\18\bin\psql.exe" -h localhost -U postgres
Remove-Item Env:PGPASSWORD
```

## Aturan DEV

- Aplikasi **tidak** memakai superuser `postgres`. Database dan role aplikasi (least privilege) dibuat di Fase 2/3 setelah design disetujui.
- Data production tidak disalin mentah ke DEV. Gunakan data sintetis, mock NBU, atau salinan cache yang sudah disetujui (guide §10).
- Bot Telegram di DEV memakai token bot uji, bukan token produksi.

## Belum disiapkan (menunggu assessment web & design)

- Database dan role aplikasi ATLAS.
- `.env.example` dan skrip `scripts/dev.ps1` untuk menjalankan web, bot uji, collector, dan mock NBU sekaligus.
