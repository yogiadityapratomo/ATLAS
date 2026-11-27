# frontend/

Tampilan dashboard ATLAS (jQuery, tanpa bundler), disajikan oleh `atlas/web` di `/static`.
CSS ditulis dengan **Tailwind CSS v4** di `src/app.css` dan di-build menjadi `css/app.css` (di-commit),
sehingga server tidak butuh Node maupun internet.

| File | Isi |
|---|---|
| `index.html` | Kerangka halaman, sidebar, dan semua menu |
| `src/app.css` | **Sumber** CSS: token warna/font (`@theme`), komponen, animasi |
| `css/app.css` | Hasil build (jangan diedit langsung) |
| `js/common.js` | Util bersama: format angka, tabel, gauge, donut, stat tile, ikon SVG, count-up, alert, capture |
| `js/main.js` | Navigasi menu, indikator sidebar, sidebar ciut; setiap menu mendaftar dengan `registerView()` |
| `js/capacity.js` | Menu Disk Pool & Tape Library (termasuk tab detail BRN/BSD/TBS dan Capture) |
| `vendor/` | jQuery, html2canvas, font IBM Plex (SIL OFL 1.1) |

## Mengubah tampilan

```
npm ci --ignore-scripts      # sekali, memasang Tailwind CLI (dev saja)
npm run watch:css            # build ulang otomatis saat src/app.css atau HTML/JS berubah
npm run build:css            # build sekali (minify) — WAJIB sebelum commit
npm run shots -- http://127.0.0.1:8001 build/ui-shots   # screenshot + uji Capture memakai Edge lokal
```

CI (`frontend-css`) gagal bila `css/app.css` tidak sama dengan hasil build `src/app.css`.

## Aturan desain

- **Warna = data.** Chrome netral (navy/abu dingin) + satu warna brand indigo-violet untuk aksi dan navigasi.
  Hijau/oranye/merah hanya untuk status kapasitas (<70%, 70–85%, ≥85%); ungu/magenta/oranye hanya untuk
  identitas master BRN/BSD/TBS.
- **html2canvas (Capture) tidak bisa membaca `oklch()`/`color-mix()`.** Semua warna di `@theme` ditulis hex,
  dan jangan memakai modifier opasitas Tailwind (mis. `bg-ink/50`); pakai `rgba()` eksplisit.
- Selama Capture, kelas `capturing` di `<html>` mematikan animasi dan mengembalikan `img` ke `inline-block`
  (preflight Tailwind membuat teks hasil html2canvas turun beberapa piksel).
- Jangan memakai nama kelas yang sama dengan utility Tailwind (mis. `ring`, `hidden`, `table`) untuk komponen.
- Animasi hanya sebagai respons (pindah menu, isi gauge/bar/donut, drawer, tab) dan otomatis mati bila
  sistem meminta *reduce motion*.

Menambah menu: buat `js/<menu>.js` yang memanggil `registerView("<nama>", {...})`, tambah tombol
`.side-btn[data-view]` (dengan ikon SVG dan `.side-label`) dan `<section id="view-<nama>" class="view">` di `index.html`.
