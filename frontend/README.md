# frontend/

Tampilan dashboard ATLAS tanpa build step (jQuery, sama dengan web V4), disajikan oleh `atlas/web` di `/static`.

| File | Isi |
|---|---|
| `index.html` | Kerangka halaman & semua menu |
| `css/style.css` | Gaya (dari V4) |
| `js/common.js` | Util bersama: format angka, tabel, bar, stat tile, alert, capture |
| `js/main.js` | Navigasi menu; setiap menu mendaftar dengan `registerView()` |
| `js/capacity.js` | Menu Disk Pool & Tape Library (dipindah dari `app.js` V4) |
| `vendor/` | jQuery, html2canvas |

Menambah menu: buat `js/<menu>.js` yang memanggil `registerView("<nama>", {...})`, tambah tombol
`.side-btn[data-view]` dan `<section id="view-<nama>" class="view">` di `index.html`.
