# Design (adendum) — Historical Capacity

| | |
|---|---|
| Versi | 0.1 |
| Tanggal | 2026-11-27 |
| Permintaan owner | "Menu historical capacity per week, per day, per quarter, per semester, per year; sample data dummy; grouping per site, per appliance, per master, atau checkbox per appliance" |
| Status | Dikerjakan di DEV atas permintaan owner; menunggu review PR |

## 1. Fitur

| Kontrol | Pilihan |
|---|---|
| Periode | Harian, Mingguan (ISO), Bulanan, Kuartal, Semester, Tahunan |
| Grouping | Site, Master, Appliance (disk pool) |
| Appliance | Checkbox (maks 8 garis); juga berlaku sebagai filter untuk grouping Site/Master |
| Metrik | Usage %, Used TB, Free TB — satu metrik per grafik (satu sumbu Y) |
| Rentang | Default per periode (harian 30 hari … tahunan 5 tahun), dapat diubah |
| Keluaran | Grafik garis + garis acuan 70%/85%, tabel (perubahan & perkiraan kapan mencapai 85%), export Excel |

**Nilai satu periode** = posisi **akhir periode** tiap appliance (hari terakhir yang ada datanya), dijumlahkan per grup; usage % grup = Σ used / Σ usable. **Puncak** usage dalam periode ikut disimpan agar lonjakan sementara tidak hilang. Ini konsisten dengan dashboard: titik terakhir grafik = angka Disk Pool hari ini.

## 2. Data

| Objek | Isi |
|---|---|
| `capacity.disk_pool_daily` (V006) | 1 baris per appliance per hari (Asia/Jakarta): nilai akhir hari, puncak, jumlah sampel, `source` (`collect` / `demo`) |
| `capacity.rollup_disk_pool_daily(from, to)` (V006, diperbaiki V007) | Snapshot → ringkasan harian; idempoten; data asli menimpa data contoh |
| Pengisi | Job kapasitas (hari berjalan, dalam transaksi yang sama) + job maintenance (catch-up 3 hari) |

Alasan tabel harian: grafik 5 tahun membaca ±64 ribu baris, bukan ±18 juta snapshot 10-menitan; query 10–80 ms di DEV. Snapshot detail tetap tersimpan (retensi diatur `ATLAS_CAPACITY_RETENTION_DAYS`) — riwayat harian tidak hilang walau snapshot lama dibuang.

## 3. Data contoh (DEV)

`scripts/dev/seed_capacity_history.py --days 730` membangkitkan riwayat 2 tahun untuk 35 disk pool asli, berakhir tepat di nilai sekarang (tren naik, pola mingguan, hari pembersihan, expansion > 60 hari lalu). Semua baris `source = 'demo'`: tidak pernah menimpa data asli, UI menampilkan label **"Berisi data contoh (demo)"**, Excel diberi catatan, dan `--purge` menghapusnya. Ditolak di `ATLAS_ENV=prod`.

Di staging/production riwayat terbentuk sendiri dari collect nyata; data contoh tidak dipakai.

## 4. Di luar cakupan (usulan lanjutan)

- Riwayat tape library (struktur sama, belum diminta).
- Perkiraan berbasis musiman (saat ini regresi linear sederhana, ditandai "indikatif").
