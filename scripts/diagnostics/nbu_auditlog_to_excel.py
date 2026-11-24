#!/usr/bin/env python3
"""
nbu_auditlog_to_excel.py — ubah hasil nbu_auditlog_dump.py (.jsonl) menjadi Excel rapi.

Sheet:
  1. Ringkasan        : jumlah per kategori/operasi + rentang tanggal
  2. Perubahan Policy : kategori POLICY, 1 baris per atribut yang berubah
  3. Detail Perubahan : semua operasi CREATE/MODIFY/DELETE, 1 baris per atribut yang berubah
  4. Semua Audit      : semua record, 1 baris per record (detail perubahan digabung)

Tanggal dikonversi dari UTC ke WIB (UTC+7).

Contoh:
    python nbu_auditlog_to_excel.py auditlog_output\\auditlogs_brn_xxx.jsonl NBU_AuditLog_BRN.xlsx --master brn
"""
import argparse
import json
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from openpyxl import Workbook
from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

WIB = timezone(timedelta(hours=7))
CHANGE_OPS = {"CREATE", "MODIFY", "DELETE"}
HEADER_FILL = PatternFill("solid", start_color="1F4E78")
HEADER_FONT = Font(bold=True, color="FFFFFF")
TITLE_FONT = Font(bold=True, size=14)
THIN = Side(style="thin", color="BFBFBF")
BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
OP_FILL = {"CREATE": PatternFill("solid", start_color="E2EFDA"),
           "MODIFY": PatternFill("solid", start_color="FFF2CC"),
           "DELETE": PatternFill("solid", start_color="F8CBAD")}
DATE_FMT = "yyyy-mm-dd hh:mm:ss"


def clean(v, maxlen=32000):
    if v is None:
        return ""
    s = ILLEGAL_CHARACTERS_RE.sub("", str(v))
    return s[:maxlen]


def to_wib(s):
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(WIB).replace(tzinfo=None)
    except ValueError:
        return None


def load(path):
    recs = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            r = json.loads(line)
            a = r.get("attributes") or {}
            ident = a.get("auditUserIdentity") or {}
            if isinstance(ident, list):
                ident = ident[0] if ident else {}
            attrs = [(x.get("attributeName", ""), x.get("oldValueDisplayString", x.get("oldValue", "")),
                      x.get("newValueDisplayString", x.get("newValue", "")))
                     for x in a.get("auditRecordAttributeList") or []]
            recs.append({
                "id": r.get("id"), "dt": to_wib(a.get("auditDateTime")),
                "category": a.get("category", ""), "operation": a.get("operation", ""),
                "user": ident.get("userName", ""), "domain": ident.get("domainName", ""),
                "object": " | ".join(str(k.get("typeIdDisplayString", "")) for k in a.get("auditKeyList") or []),
                "message": a.get("message", ""), "reason": a.get("reason", ""), "attrs": attrs,
            })
    recs.sort(key=lambda x: x["dt"] or datetime.min, reverse=True)
    return recs


def write_table(ws, headers, rows, widths, wrap_cols=(), op_col=None, start_row=1):
    for c, h in enumerate(headers, 1):
        cell = ws.cell(row=start_row, column=c, value=h)
        cell.fill, cell.font, cell.border = HEADER_FILL, HEADER_FONT, BORDER
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    wrap = Alignment(wrap_text=True, vertical="top")
    top = Alignment(vertical="top")
    for r_i, row in enumerate(rows, start_row + 1):
        for c, v in enumerate(row, 1):
            cell = ws.cell(row=r_i, column=c, value=clean(v) if isinstance(v, str) else v)
            cell.border = BORDER
            cell.alignment = wrap if c in wrap_cols else top
            if isinstance(v, datetime):
                cell.number_format = DATE_FMT
        if op_col and row[op_col - 1] in OP_FILL:
            ws.cell(row=r_i, column=op_col).fill = OP_FILL[row[op_col - 1]]
    for c, w in enumerate(widths, 1):
        ws.column_dimensions[get_column_letter(c)].width = w
    last = start_row + max(len(rows), 1)
    ws.auto_filter.ref = f"A{start_row}:{get_column_letter(len(headers))}{last}"
    ws.freeze_panes = ws.cell(row=start_row + 1, column=1)


def exploded(recs, only_changes):
    rows = []
    for r in recs:
        if only_changes and r["operation"] not in CHANGE_OPS:
            continue
        base = [r["dt"], r["category"], r["operation"], r["user"], r["object"], r["message"]]
        if r["attrs"]:
            for name, old, new in r["attrs"]:
                rows.append(base + [name, old, new])
        else:
            rows.append(base + ["", "", ""])
    return rows


def main():
    p = argparse.ArgumentParser()
    p.add_argument("jsonl")
    p.add_argument("xlsx")
    p.add_argument("--master", default="")
    args = p.parse_args()

    recs = load(args.jsonl)
    wb = Workbook()

    # ---- 1. Ringkasan ----
    ws = wb.active
    ws.title = "Ringkasan"
    dts = [r["dt"] for r in recs if r["dt"] and r["dt"].year > 2000]
    ws["A1"] = f"Audit Log NetBackup {args.master.upper()}".strip()
    ws["A1"].font = TITLE_FONT
    info = [("Total record", len(recs)),
            ("Rentang tanggal (WIB)", f"{min(dts):%Y-%m-%d %H:%M} s/d {max(dts):%Y-%m-%d %H:%M}" if dts else "-"),
            ("Dibuat", datetime.now().strftime("%Y-%m-%d %H:%M")),
            ("Catatan", "Tanggal sudah dikonversi ke WIB (UTC+7). Warna operasi: hijau=CREATE, kuning=MODIFY, merah=DELETE.")]
    for i, (k, v) in enumerate(info, 3):
        ws.cell(row=i, column=1, value=k).font = Font(bold=True)
        ws.cell(row=i, column=2, value=v)
    agg = defaultdict(lambda: [0, None, None])
    for r in recs:
        a = agg[(r["category"], r["operation"])]
        a[0] += 1
        if r["dt"] and r["dt"].year > 2000:
            a[1] = r["dt"] if a[1] is None or r["dt"] < a[1] else a[1]
            a[2] = r["dt"] if a[2] is None or r["dt"] > a[2] else a[2]
    sum_rows = sorted(([c, o, n, f, l] for (c, o), (n, f, l) in agg.items()), key=lambda x: (-x[2]))
    write_table(ws, ["Kategori", "Operasi", "Jumlah", "Pertama (WIB)", "Terakhir (WIB)"],
                sum_rows, [26, 12, 10, 20, 20], op_col=2, start_row=8)

    # ---- 2. Perubahan Policy ----
    hdr = ["Tanggal (WIB)", "Kategori", "Operasi", "User", "Objek", "Pesan",
           "Atribut yang Diubah", "Nilai Lama", "Nilai Baru"]
    wid = [20, 14, 10, 14, 40, 60, 28, 30, 30]
    ws = wb.create_sheet("Perubahan Policy")
    write_table(ws, hdr, exploded([r for r in recs if r["category"] == "POLICY"], False),
                wid, wrap_cols=(5, 6, 8, 9), op_col=3)

    # ---- 3. Detail Perubahan (semua kategori, operasi CREATE/MODIFY/DELETE) ----
    ws = wb.create_sheet("Detail Perubahan")
    write_table(ws, hdr, exploded(recs, True), wid, wrap_cols=(5, 6, 8, 9), op_col=3)

    # ---- 4. Semua Audit ----
    ws = wb.create_sheet("Semua Audit")
    rows = [[r["dt"], r["category"], r["operation"], r["user"], r["domain"], r["object"], r["message"],
             "\n".join(f"{n}: {o} -> {nv}" for n, o, nv in r["attrs"]), r["reason"], r["id"]] for r in recs]
    write_table(ws, ["Tanggal (WIB)", "Kategori", "Operasi", "User", "Domain", "Objek", "Pesan",
                     "Apa yang Diubah / Detail", "Alasan", "Audit ID"],
                rows, [20, 22, 10, 14, 16, 40, 60, 60, 14, 10], wrap_cols=(6, 7, 8), op_col=3)

    wb.save(args.xlsx)
    print(f"OK: {args.xlsx} | record={len(recs)}")


if __name__ == "__main__":
    main()
