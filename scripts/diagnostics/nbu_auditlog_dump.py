#!/usr/bin/env python3
"""
nbu_auditlog_dump.py — READ-ONLY.

Mengambil SEMUA record audit log NetBackup (GET /security/auditlogs) dari
offset 0 sampai offset terakhir, lalu menyimpannya ke JSONL + CSV dan
menampilkan ringkasan per kategori (termasuk contoh record kategori POLICY).

Hanya melakukan HTTP GET. Tidak mengubah apa pun di NetBackup.

Token TIDAK ditulis di skrip; dibaca dari environment variable (default NBU_TOKEN).

Contoh (PowerShell):
    $env:NBU_TOKEN = "<API key master>"
    python nbu_auditlog_dump.py --master brn
    python nbu_auditlog_dump.py --master brn --filter "category eq 'POLICY'"
    python nbu_auditlog_dump.py --master brn --since 2026-11-01T00:00:00Z
    python nbu_auditlog_dump.py --master brn --resume      # lanjut jika sempat terputus
"""
import argparse
import csv
import json
import logging
import os
import sys
import time
from collections import Counter
from datetime import datetime

import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

MASTERS = {
    "tbs": "https://tbsnbuvpapp1.telkomsel.co.id/netbackup",
    "bsd": "https://bsdnbuvpapp1.telkomsel.co.id/netbackup",
    "brn": "https://brnnbuvpapp1.telkomsel.co.id/netbackup",
}
RETRY_STATUS = {429, 500, 502, 503, 504}
CSV_FIELDS = ["id", "auditDateTime", "category", "operation", "messageId",
              "userName", "domainName", "keys", "message", "attributes", "reason"]

log = logging.getLogger("auditlog")


class FetchError(RuntimeError):
    pass


def parse_args():
    p = argparse.ArgumentParser(description="Dump audit log NetBackup (read-only) sampai offset terakhir.")
    p.add_argument("--master", required=True, help="tbs | bsd | brn, atau URL lengkap yang diakhiri /netbackup")
    p.add_argument("--limit", type=int, default=100, help="Jumlah record per halaman (default 100)")
    p.add_argument("--sleep", type=float, default=0.5, help="Jeda antar request dalam detik (default 0.5)")
    p.add_argument("--api-version", default="12.0", help="Versi API di header Accept (default 12.0)")
    p.add_argument("--filter", default=None, help="Filter OData, contoh: \"category eq 'POLICY'\"")
    p.add_argument("--since", default=None,
                   help="Berhenti saat record lebih lama dari waktu ini (ISO UTC), contoh 2026-11-01T00:00:00Z")
    p.add_argument("--max-pages", type=int, default=0, help="Batas jumlah halaman (0 = tanpa batas)")
    p.add_argument("--timeout", type=int, default=60, help="Timeout per request dalam detik (default 60)")
    p.add_argument("--retries", type=int, default=5, help="Jumlah percobaan per halaman (default 5)")
    p.add_argument("--out-dir", default="auditlog_output", help="Folder output (default auditlog_output)")
    p.add_argument("--token-env", default="NBU_TOKEN", help="Nama environment variable token (default NBU_TOKEN)")
    p.add_argument("--resume", action="store_true", help="Lanjutkan dari checkpoint run sebelumnya")
    return p.parse_args()


def parse_dt(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def setup_logging(out_dir, name):
    os.makedirs(out_dir, exist_ok=True)
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
    log.setLevel(logging.INFO)
    for h in (logging.StreamHandler(sys.stdout),
              logging.FileHandler(os.path.join(out_dir, f"auditlog_{name}.log"), encoding="utf-8")):
        h.setFormatter(fmt)
        log.addHandler(h)


def fetch_page(session, url, params, args):
    last_err = ""
    for attempt in range(1, args.retries + 1):
        try:
            r = session.get(url, params=params, timeout=args.timeout)
        except requests.RequestException as e:
            last_err = f"{type(e).__name__}: {e}"
        else:
            if r.status_code == 200:
                try:
                    return r.json()
                except ValueError:
                    last_err = f"respons bukan JSON: {r.text[:200]}"
            elif r.status_code in RETRY_STATUS:
                last_err = f"HTTP {r.status_code}: {r.text[:200]}"
            else:
                raise FetchError(f"HTTP {r.status_code} (tidak di-retry): {r.text[:500]}")
        if attempt < args.retries:
            wait = min(60, 2 ** attempt)
            log.warning("offset=%s percobaan %d/%d gagal (%s) - tunggu %ds",
                        params["page[offset]"], attempt, args.retries, last_err, wait)
            time.sleep(wait)
    raise FetchError(f"Gagal setelah {args.retries} percobaan pada offset {params['page[offset]']}: {last_err}")


def to_csv_row(rec):
    a = rec.get("attributes") or {}
    ident = a.get("auditUserIdentity") or {}
    if isinstance(ident, list):  # beberapa versi API mengembalikan list
        ident = ident[0] if ident else {}
    keys = " | ".join(str(k.get("typeIdDisplayString", "")) for k in a.get("auditKeyList") or [])
    attrs = " ; ".join(
        f"{x.get('attributeName', '')}: {x.get('oldValueDisplayString', '')} -> {x.get('newValueDisplayString', '')}"
        for x in a.get("auditRecordAttributeList") or [])
    return {
        "id": rec.get("id"), "auditDateTime": a.get("auditDateTime"), "category": a.get("category"),
        "operation": a.get("operation"), "messageId": a.get("messageId"),
        "userName": ident.get("userName"), "domainName": ident.get("domainName"),
        "keys": keys, "message": a.get("message"), "attributes": attrs, "reason": a.get("reason"),
    }


def main():
    args = parse_args()
    base = MASTERS.get(args.master.lower(), args.master).rstrip("/")
    name = args.master.lower() if args.master.lower() in MASTERS else "custom"
    setup_logging(args.out_dir, name)

    token = os.environ.get(args.token_env, "").strip()
    if not token:
        log.error("Token kosong. Set dulu, contoh PowerShell:  $env:%s = \"<API key>\"", args.token_env)
        return 2

    since = parse_dt(args.since) if args.since else None
    ckpt_path = os.path.join(args.out_dir, f"checkpoint_{name}.json")
    seen = set()

    if args.resume and os.path.exists(ckpt_path):
        with open(ckpt_path, encoding="utf-8") as f:
            ckpt = json.load(f)
        offset, jsonl_path, csv_path = ckpt["offset"], ckpt["jsonl"], ckpt["csv"]
        if ckpt.get("filter") != args.filter or ckpt.get("since") != args.since:
            log.warning("Filter/since berbeda dari checkpoint (%s / %s). Pastikan ini disengaja.",
                        ckpt.get("filter"), ckpt.get("since"))
        if os.path.exists(jsonl_path):
            with open(jsonl_path, encoding="utf-8") as f:
                for line in f:
                    if line.strip():
                        seen.add(str(json.loads(line).get("id")))
        log.info("RESUME dari offset %d (%d record sudah ada di %s)", offset, len(seen), jsonl_path)
    else:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        offset = 0
        jsonl_path = os.path.join(args.out_dir, f"auditlogs_{name}_{ts}.jsonl")
        csv_path = os.path.join(args.out_dir, f"auditlogs_{name}_{ts}.csv")

    session = requests.Session()
    session.trust_env = False  # abaikan HTTP(S)_PROXY: akses langsung ke master (sama seperti collector)
    session.verify = False
    session.headers.update({
        "Accept": f"application/vnd.netbackup+json;version={args.api_version}",
        "Authorization": f"Bearer {token}",
    })
    url = f"{base}/security/auditlogs"

    cat_count, catop_count = Counter(), Counter()
    policy_samples, newest, oldest = [], None, None
    saved = dupes = pages = 0
    total = None
    started = time.time()
    exit_code = 0

    csv_new = not os.path.exists(csv_path)
    with open(jsonl_path, "a", encoding="utf-8") as fj, \
            open(csv_path, "a", encoding="utf-8-sig", newline="") as fc:
        writer = csv.DictWriter(fc, fieldnames=CSV_FIELDS)
        if csv_new:
            writer.writeheader()

        log.info("Mulai: %s | limit=%d | filter=%s | since=%s", url, args.limit, args.filter, args.since)
        try:
            while True:
                params = {"page[offset]": offset, "page[limit]": args.limit, "sort": "-auditDateTime"}
                if args.filter:
                    params["filter"] = args.filter
                body = fetch_page(session, url, params, args)
                data = body.get("data") or []
                pag = (body.get("meta") or {}).get("pagination") or {}
                pages += 1

                if total is None:
                    total = pag.get("count")
                    log.info("Total record menurut server: %s | halaman: %s | limit dipakai server: %s",
                             total, pag.get("pages"), pag.get("limit"))

                reached_since = False
                for rec in data:
                    a = rec.get("attributes") or {}
                    dt_s = a.get("auditDateTime")
                    if since and dt_s and parse_dt(dt_s) < since:
                        reached_since = True
                        continue
                    rid = str(rec.get("id"))
                    if rid in seen:  # data baru masuk saat paging menggeser offset -> bisa duplikat
                        dupes += 1
                        continue
                    seen.add(rid)
                    fj.write(json.dumps(rec, ensure_ascii=False) + "\n")
                    writer.writerow(to_csv_row(rec))
                    saved += 1
                    cat, op = a.get("category", "?"), a.get("operation", "?")
                    cat_count[cat] += 1
                    catop_count[f"{cat}/{op}"] += 1
                    if dt_s:
                        newest = dt_s if newest is None or dt_s > newest else newest
                        oldest = dt_s if oldest is None or dt_s < oldest else oldest
                    if "POLICY" in str(cat).upper() and len(policy_samples) < 15:
                        policy_samples.append(to_csv_row(rec))
                fj.flush()
                fc.flush()

                next_offset = pag.get("next", offset + len(data))
                with open(ckpt_path, "w", encoding="utf-8") as f:
                    json.dump({"offset": next_offset, "jsonl": jsonl_path, "csv": csv_path,
                               "filter": args.filter, "since": args.since}, f)

                log.info("offset=%-6d diterima=%-4d tersimpan total=%-6d (dari %s) | %.0fs",
                         offset, len(data), saved, total, time.time() - started)

                if not data or "next" not in pag or reached_since:
                    if reached_since:
                        log.info("Mencapai batas --since, berhenti.")
                    break
                if args.max_pages and pages >= args.max_pages:
                    log.info("Mencapai --max-pages=%d, berhenti (bisa dilanjut dengan --resume).", args.max_pages)
                    break
                offset = next_offset
                time.sleep(args.sleep)
            if not (args.max_pages and pages >= args.max_pages) and os.path.exists(ckpt_path):
                os.remove(ckpt_path)  # selesai normal -> checkpoint tidak diperlukan
        except FetchError as e:
            log.error("%s", e)
            if os.path.exists(ckpt_path):
                log.error("Checkpoint tersimpan. Lanjutkan dengan argumen yang sama + --resume")
            exit_code = 1
        except KeyboardInterrupt:
            log.warning("Dihentikan (Ctrl+C). Lanjutkan dengan argumen yang sama + --resume")
            exit_code = 130

    # ----- Ringkasan -----
    log.info("=" * 70)
    log.info("SELESAI: %d record tersimpan, %d duplikat dilewati, %d halaman, %.0f detik",
             saved, dupes, pages, time.time() - started)
    log.info("Rentang waktu (run ini): %s  s/d  %s", oldest, newest)
    log.info("JSONL: %s", os.path.abspath(jsonl_path))
    log.info("CSV  : %s", os.path.abspath(csv_path))
    log.info("--- Jumlah per kategori ---")
    for cat, n in cat_count.most_common():
        log.info("  %-28s %d", cat, n)
    log.info("--- Jumlah per kategori/operasi ---")
    for k, n in catop_count.most_common():
        log.info("  %-40s %d", k, n)
    if policy_samples:
        log.info("--- Contoh record kategori POLICY (maks 15) ---")
        for r in policy_samples:
            log.info("  [%s] %s %s | user=%s | keys=%s | %s",
                     r["auditDateTime"], r["category"], r["operation"], r["userName"], r["keys"], r["message"])
            if r["attributes"]:
                log.info("      atribut: %s", r["attributes"][:400])
    else:
        log.info("Tidak ada record kategori POLICY pada data yang diambil.")

    summary_path = os.path.join(args.out_dir, f"summary_{name}.json")
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump({"master": base, "saved": saved, "duplicates": dupes, "pages": pages,
                   "server_count": total, "oldest": oldest, "newest": newest,
                   "per_category": dict(cat_count), "per_category_operation": dict(catop_count),
                   "policy_samples": policy_samples}, f, indent=2, ensure_ascii=False)
    log.info("Ringkasan JSON: %s", os.path.abspath(summary_path))
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
