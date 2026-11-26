"""
Shared NetBackup capacity report logic: disk pool + tape library.

Disk pool fetching reuses capacity_cache_V2_patched.py (single source of
truth for master URLs/tokens). Tape library fetching/mapping is new.
"""

import os
import json
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from datetime import datetime
from collections import defaultdict

import requests
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment

import capacity_cache_V2_patched as legacy

BASE_DIR = legacy.BASE_DIR
CACHE_DIR = legacy.CACHE_DIR
REPORT_DIR = legacy.REPORT_DIR

DISK_CACHE_FILE = os.path.join(CACHE_DIR, "capacity_cache.json")
TAPE_CACHE_FILE = os.path.join(CACHE_DIR, "tape_cache.json")
EXCEL_FILE = os.path.join(REPORT_DIR, "capacity_report.xlsx")

MASTERS = legacy.MASTERS
headers = legacy.headers
NO_PROXY = legacy.NO_PROXY
fetch_disk_pools = legacy.fetch_master

TAPE_LIMIT = 50
TAPE_MAX_RETRIES = 3
TAPE_RETRY_BACKOFF_SEC = 2
TAPE_MAX_PAGES = 500
REQUEST_TIMEOUT_SEC = 20

# Hard ceiling per master/endpoint call: no matter what, a single fetch can never
# hang longer than this — it either finishes or is reported as a timeout error.
# Masters are fetched one at a time (not in parallel): firing several requests at
# once through the same VPN tunnel proved to be *less* reliable, not faster.
#
# Tape gets a much bigger budget than disk-pool: a single tape-media page is fast
# (confirmed by manual testing), but a master's *whole* tape inventory can span
# dozens of pages (e.g. BSD alone has 320 tapes / 50 per page = 7 pages, and TBS
# looks to have even more) — so the bottleneck is page *count*, not per-request
# slowness. Disk-pool result sets are small (tens of rows, 1-2 pages) so it stays tight.
#
# TBS specifically has repeatedly failed to finish its full tape pagination within
# 180s in production (mix of transient 503s and plain timeouts), even though any
# single page fetched manually succeeds fine — it just has more pages than the
# other masters. Collection now runs unattended via Task Scheduler (nothing waits
# on it live), so there's no UX cost to giving it more room.
DISK_FETCH_DEADLINE_SEC = 45
TAPE_FETCH_DEADLINE_SEC = 360

# How long a partial tape-pagination attempt (saved after a timeout/error) stays
# eligible to resume from. Older partial progress is discarded and refetched from
# page 1 instead of being stitched onto fresh data, since tape state can drift
# over multi-hour gaps.
TAPE_RESUME_MAX_AGE_SEC = 2 * 60 * 60

# RobotNumber -> Site mapping, per master. Exhaustive per master as specified.
ROBOT_SITE_MAP = {
    "tbs": {1: "BRN", 2: "TBS"},
    "bsd": {0: "BSD"},
    "brn": {0: "BRN", 1: "BRN"},
}

TAPE_LIBRARY_INFO = {
    "BRN": {"ip": "10.2.119.203", "serial_number": "78BA713", "storage_name": "brn02_ts4500"},
    "TBS": {"ip": "10.2.245.104", "serial_number": "78BA712", "storage_name": "tbs03_ts4500"},
    "BSD": {"ip": "10.52.140.6", "serial_number": "78DD440", "storage_name": "bsd01_ts4500"},
}

TAPE_TYPE_SIZE_TB = {"L8": 12, "L9": 18}
TAPE_TYPE_LABEL = {"L8": "IBM (LTO8)", "L9": "IBM (LTO9)"}


def kb_to_tb(kb):
    return (kb or 0) / (1024 ** 3)


def _bounded_call(fn, *args, timeout):
    """Run fn(*args) with a hard wall-clock ceiling. If it doesn't finish in time,
    give up waiting and raise TimeoutError — the thread may keep running in the
    background, but the caller is never blocked past `timeout`."""
    ex = ThreadPoolExecutor(max_workers=1)
    try:
        fut = ex.submit(fn, *args)
        try:
            return fut.result(timeout=timeout)
        except FuturesTimeoutError:
            raise TimeoutError(f"tidak merespons dalam {timeout}s — master kemungkinan overload/lambat")
    finally:
        ex.shutdown(wait=False, cancel_futures=True)


def _retry_transient(fn, *args, max_retries=TAPE_MAX_RETRIES, backoff=TAPE_RETRY_BACKOFF_SEC):
    """Call fn(*args), retrying on transient 5xx / timeout / connection errors."""
    last_exc = None
    for attempt in range(max_retries):
        try:
            return fn(*args)
        except (requests.exceptions.HTTPError, requests.exceptions.Timeout,
                requests.exceptions.ConnectionError) as e:
            last_exc = e
            is_server_error = getattr(e, "response", None) is not None and e.response.status_code >= 500
            is_network_hiccup = isinstance(e, (requests.exceptions.Timeout, requests.exceptions.ConnectionError))
            if attempt < max_retries - 1 and (is_server_error or is_network_hiccup):
                time.sleep(backoff * (attempt + 1))
                continue
            raise
    raise last_exc


def fetch_disk_pools_resilient(master):
    """Disk-pool fetch has no built-in retry (it's the legacy, untouched script) —
    wrap the whole paginated fetch with a retry-on-transient-error instead. On
    retry it restarts from page 1, which is fine since disk-pool result sets are
    small (tens of rows)."""
    return _retry_transient(fetch_disk_pools, master)


def _get_tape_page(url, params, master):
    r = requests.get(
        url, headers=headers(master["token"]), params=params,
        verify=False, timeout=REQUEST_TIMEOUT_SEC, proxies=NO_PROXY,
    )
    r.raise_for_status()
    return r.json()


def fetch_tape_media_page(url, params, master):
    """GET one tape-media page, retrying on transient 5xx / timeout errors."""
    return _retry_transient(_get_tape_page, url, params, master)


def _tape_resume_file(key):
    return os.path.join(CACHE_DIR, f"tape_resume_{key}.json")


def _load_tape_resume(key):
    """Load partial tape-pagination progress left by a previous failed attempt
    for this master, if any and not older than TAPE_RESUME_MAX_AGE_SEC. Returns
    (records, cursor) - ([], None) if there's nothing usable to resume from."""
    path = _tape_resume_file(key)
    if not os.path.exists(path):
        return [], None
    if time.time() - os.path.getmtime(path) > TAPE_RESUME_MAX_AGE_SEC:
        os.remove(path)
        return [], None
    try:
        with open(path, encoding="utf-8") as f:
            state = json.load(f)
        return state["records"], state["cursor"]
    except (json.JSONDecodeError, KeyError):
        os.remove(path)
        return [], None


def _save_tape_resume(key, records, cursor):
    with open(_tape_resume_file(key), "w", encoding="utf-8") as f:
        json.dump({"records": records, "cursor": cursor}, f)


def _clear_tape_resume(key):
    path = _tape_resume_file(key)
    if os.path.exists(path):
        os.remove(path)


def fetch_tape_media(master, deadline_sec=None, resume_key=None):
    """Fetch all tape-media records for one master (cursor-paginated).

    If deadline_sec is given, elapsed time is checked before each page
    request; once exceeded, raises TimeoutError immediately instead of
    starting another page. This actually stops making requests once the
    deadline is hit - unlike wrapping the whole call in a thread-pool
    timeout (the previous approach), it doesn't leave a background thread
    still hammering the master after the caller has already given up.

    If resume_key is given, a previous failed attempt's progress (records
    already fetched + the cursor to continue from) is picked up instead of
    starting over from page 1 - TBS's full tape inventory takes long enough,
    and fails often enough, that restarting from scratch every attempt meant
    it rarely got anywhere near the end. Progress is saved on every failure
    and cleared once pagination completes."""
    out, after = ([], None) if resume_key is None else _load_tape_resume(resume_key)
    url = f"{master['base_url']}/storage/tape-media"
    start = time.time()
    for _ in range(TAPE_MAX_PAGES):
        if deadline_sec is not None and time.time() - start > deadline_sec:
            if resume_key is not None:
                _save_tape_resume(resume_key, out, after)
            raise TimeoutError(
                f"tidak merespons dalam {deadline_sec}s — master kemungkinan overload/lambat "
                f"(baru dapat {len(out)} record sebelum berhenti)"
            )
        params = {"page[limit]": TAPE_LIMIT}
        if after:
            params["page[after]"] = after
        try:
            js = fetch_tape_media_page(url, params, master)
        except Exception:
            if resume_key is not None:
                _save_tape_resume(resume_key, out, after)
            raise
        data = js.get("data", [])
        if not data:
            break
        out.extend(item["attributes"] for item in data)
        after = js.get("meta", {}).get("pagination", {}).get("next")
        if not after:
            break
    else:
        if resume_key is not None:
            _save_tape_resume(resume_key, out, after)
        raise RuntimeError(f"tape-media pagination exceeded {TAPE_MAX_PAGES} halaman — kemungkinan loop cursor")
    if resume_key is not None:
        _clear_tape_resume(resume_key)
    return out


def build_tape_rows(tape_items_by_master):
    """Pure transform: {master_key: [raw tape attrs]} -> table rows, mapped robotNumber -> site."""
    site_groups = defaultdict(list)
    for key, items in tape_items_by_master.items():
        robot_map = ROBOT_SITE_MAP.get(key, {})
        for a in items:
            robot_no = (a.get("robot") or {}).get("robotNumber")
            site = robot_map.get(robot_no)
            if site is None:
                continue
            site_groups[site].append(a)

    rows = []
    for site in sorted(site_groups):
        by_type = defaultdict(list)
        for a in site_groups[site]:
            barcode = a.get("barcode") or ""
            suffix = barcode[-2:].upper()
            by_type[suffix].append(a)
        info = TAPE_LIBRARY_INFO.get(site, {})
        for suffix in sorted(by_type):
            tapes = by_type[suffix]
            size_tb = TAPE_TYPE_SIZE_TB.get(suffix, 0)
            label = TAPE_TYPE_LABEL.get(suffix, f"Unknown ({suffix})")
            total_qty = len(tapes)
            used_qty = sum(1 for t in tapes if (t.get("kiloBytes") or 0) > 0)
            free_qty = total_qty - used_qty
            raw_capacity_tb = round(size_tb * total_qty, 2)
            used_capacity_tb = round(sum(kb_to_tb(t.get("kiloBytes")) for t in tapes), 2)
            used_pct = round((used_qty / total_qty) * 100, 2) if total_qty else 0
            free_pct = round(100 - used_pct, 2) if total_qty else 0
            rows.append({
                "Site": site,
                "IP": info.get("ip", ""),
                "Brand": "IBM",
                "Type": "Tape Library",
                "Model": "TS4500",
                "Serial Number": info.get("serial_number", ""),
                "Storage Name": info.get("storage_name", ""),
                "Domain": "Legacy",
                "Type Tape": label,
                "Total Tape (Qty)": total_qty,
                "Tape Used (Qty)": used_qty,
                "Tape Free (Qty)": free_qty,
                "Raw Capacity (TB)": raw_capacity_tb,
                "Used Capacity (TB)": used_capacity_tb,
                "Tape Used %": used_pct,
                "Tape Free %": free_pct,
            })
    return rows


def load_json(path):
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return []


def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def export_excel(disk_rows, tape_rows):
    wb = Workbook()

    ws = wb.active
    ws.title = "Disk Pool Detail"
    disk_headers = ["Site", "Master", "Disk Pool Name", "Usable (TB)", "Available (TB)", "Used (TB)", "Usage (%)"]
    for i, h in enumerate(disk_headers, 1):
        c = ws.cell(row=1, column=i, value=h)
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", start_color="4F81BD")
    for r in disk_rows:
        ws.append([r[h] for h in disk_headers])
    ws.freeze_panes = "A2"
    if disk_rows:
        ws.auto_filter.ref = ws.dimensions

    sw = wb.create_sheet("Disk Pool Summary")
    now = datetime.now()
    hm = now.hour * 100 + now.minute
    if 800 <= hm <= 1500:
        shift = 1
    elif 1501 <= hm <= 2300:
        shift = 2
    else:
        shift = 3
    title = f"Shift {shift} {now.strftime('%d %B %Y')}"
    sw.merge_cells("A1:E1")
    c = sw["A1"]
    c.value = title
    c.font = Font(bold=True, size=14)
    c.alignment = Alignment(horizontal="center")
    hdr = ["Site", "Total Capacity (TB)", "Used Capacity (TB)", "Free Capacity (TB)", "Used Percentage (%)"]
    for i, h in enumerate(hdr, 1):
        cc = sw.cell(row=2, column=i, value=h)
        cc.font = Font(bold=True, color="FFFFFF")
        cc.fill = PatternFill("solid", start_color="4F81BD")
    grp = defaultdict(lambda: [0, 0, 0])
    for r in disk_rows:
        grp[r["Site"]][0] += r["Usable (TB)"]
        grp[r["Site"]][1] += r["Used (TB)"]
        grp[r["Site"]][2] += r["Available (TB)"]
    for s in sorted(grp):
        total, used, free = grp[s]
        pct = round((used / total) * 100, 2) if total else 0
        sw.append([s, round(total, 2), round(used, 2), round(free, 2), pct])

    tw = wb.create_sheet("Tape Library")
    tape_headers = [
        "No", "Site", "IP", "Brand", "Type", "Model", "Serial Number", "Storage Name", "Domain",
        "Type Tape", "Total Tape (Qty)", "Tape Used (Qty)", "Tape Free (Qty)",
        "Raw Capacity (TB)", "Used Capacity (TB)", "Tape Used %", "Tape Free %",
    ]
    for i, h in enumerate(tape_headers, 1):
        c = tw.cell(row=1, column=i, value=h)
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", start_color="4F81BD")
    for idx, r in enumerate(tape_rows, 1):
        tw.append([idx] + [r[h] for h in tape_headers[1:]])
    tw.freeze_panes = "A2"
    if tape_rows:
        tw.auto_filter.ref = tw.dimensions

    wb.save(EXCEL_FILE)


def generate_all():
    """Fetch disk-pool + tape-media, one master/endpoint at a time.

    Masters are deliberately fetched *sequentially*, not in parallel — firing all
    6 requests at once through the same VPN tunnel turned out to make every master
    (including disk-pool, which used to work fine) fail together, presumably
    because the tunnel/servers can't handle the concurrent burst.

    Disk-pool calls are wrapped in `_bounded_call` (thread-pool timeout) so a
    stuck master can't block the rest. Tape calls enforce their own deadline
    cooperatively inside `fetch_tape_media` instead — `_bounded_call`'s timeout
    only stops *waiting*, it doesn't stop the underlying thread, which kept
    running (and kept hitting the master) in the background even after giving
    up; that repeatedly caused TBS to fail simply because it has ~338 tape
    pages to page through and a leftover thread from a previous "timed out"
    run was still hammering it when the next run started."""
    errors = []
    disk_rows = []
    tape_items_by_master = {}

    for m in MASTERS.values():
        try:
            disk_rows.extend(_bounded_call(fetch_disk_pools_resilient, m, timeout=DISK_FETCH_DEADLINE_SEC))
        except Exception as e:
            errors.append(f"{m['name']} (disk pool): {e}")

    for key, m in MASTERS.items():
        try:
            tape_items_by_master[key] = fetch_tape_media(m, deadline_sec=TAPE_FETCH_DEADLINE_SEC, resume_key=key)
        except Exception as e:
            errors.append(f"{m['name']} (tape): {e}")

    disk_rows = sorted(disk_rows, key=lambda x: (x["Master"], x["Disk Pool Name"]))
    tape_rows = build_tape_rows(tape_items_by_master)

    save_json(DISK_CACHE_FILE, disk_rows)
    save_json(TAPE_CACHE_FILE, tape_rows)

    if disk_rows or tape_rows:
        export_excel(disk_rows, tape_rows)

    return {
        "disk_pools": disk_rows,
        "tape_library": tape_rows,
        "errors": errors,
        "generated_at": datetime.now().isoformat(),
    }
