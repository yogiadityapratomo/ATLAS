## Ringkasan
<!-- Apa yang berubah dan kenapa. Link ke task di implementation plan. -->

## Fase / task
<!-- contoh: Fase 4 — task 4b-2 collector delta -->

## Dampak ke perilaku existing
<!-- "Tidak ada", atau jelaskan perbedaan perilaku yang sudah disetujui di design doc. -->

## Bukti test (wajib — hasil yang benar-benar dijalankan)
```
<command>
<output>
```

## Checklist (docs/process/deployment-workflow.md §6)
- [ ] Sesuai design & plan yang disetujui
- [ ] Test relevan lulus (bukti di atas)
- [ ] Tidak ada secret di kode, log, atau dokumen
- [ ] Error handling & logging ada
- [ ] Kontrak `policy_cache.json` tidak berubah (atau perubahan sudah disetujui)
- [ ] Dokumentasi / CHANGELOG diperbarui
- [ ] Rencana rollback jelas
