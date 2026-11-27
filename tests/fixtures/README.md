# tests/fixtures

Data **sintetis** untuk test — bukan data production (guide §10: data production tidak disalin ke repo).

| Folder | Isi |
|---|---|
| `v4_cache/` | `capacity_cache.json` & `tape_cache.json` berformat persis web V4 (urutan kunci, indent 2, `Raw Capacity (TB)` bertipe int, `Usage (%)` = 0 saat kapasitas 0). Dipakai test regresi DB ⇄ JSON V4. |

Regresi terhadap data asli (cache V4 production di laptop DEV) tercatat di [docs/07-quality-report.md](../../docs/07-quality-report.md).
