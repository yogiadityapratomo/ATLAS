# Release Record — ATLAS vX.Y.Z

Salin file ini ke `docs/releases/vX.Y.Z.md` untuk setiap rilis. Isi dengan hasil nyata (bukan rencana).

| | |
|---|---|
| Versi / tag | vX.Y.Z (commit `…`) |
| Nomor CR | |
| Jendela waktu | |
| Pelaksana | |
| Approver | |

## Isi rilis
- (ringkasan perubahan, link PR)

## Sebelum deploy
- [ ] Test lulus (link output / CI run)
- [ ] UAT staging ditandatangani (tanggal, oleh)
- [ ] CR disetujui
- [ ] Pre-check server: disk ____ GB kosong, service ____, umur cache ____
- [ ] Backup `.env`, `state\`, `policy_cache.json` → lokasi: ____

## Deploy
- [ ] Paket diekstrak ke `releases\vX.Y.Z`, checksum cocok
- [ ] venv + `requirements.lock` terpasang
- [ ] Self-check lulus
- [ ] Junction `current` → `vX.Y.Z`, service di-restart (jam: ____)

## Setelah deploy
- [ ] Service RUNNING, heartbeat segar
- [ ] `/status` OK, umur cache ____ menit
- [ ] Tidak ada ERROR baru 15 menit (`errors.log`)
- [ ] Smoke test Search (hostname: ____) OK
- [ ] Smoke test Collect All OK

## Hasil
- Status: BERHASIL / ROLLBACK
- Catatan / insiden:
