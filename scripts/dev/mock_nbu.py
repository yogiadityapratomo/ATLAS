r"""mock_nbu.py — server tiruan 3 master NetBackup untuk DEV/soak test (KHUSUS DEV, hanya 127.0.0.1).

Meniru endpoint yang dipakai ATLAS dengan paginasi asli:
  GET /<master>/netbackup/storage/disk-pools?page[limit]=&page[offset]=   (paginasi offset)
  GET /<master>/netbackup/storage/tape-media?page[limit]=&page[after]=    (paginasi cursor)

Data dibentuk dari cache V4 (legacy/web-v4/cache) sehingga angka dashboard realistis.
Injeksi gangguan (untuk menguji retry, backoff, status partial, lanjutan paginasi tape):
  --fail-rate 0.05      5% request dijawab 503 + Retry-After
  --latency-ms 50       jeda tiap request
  --down-master brn --down-every 7 --down-for 2
                        master BRN "mati" (timeout koneksi) 2 menit setiap 7 menit

Contoh:
    .venv\Scripts\python.exe scripts\dev\mock_nbu.py --port 8781 --fail-rate 0.05
"""

from __future__ import annotations

import argparse
import json
import random
import threading
import time
from collections import Counter
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

REPO = Path(__file__).resolve().parents[2]
CACHE = REPO / "legacy" / "web-v4" / "cache"
TB = 1024**4
KB_PER_TB = 1024**3
# site tape → (master, robotNumber) sesuai ROBOT_SITE_MAP ATLAS/V4
TAPE_ROBOT = {"BRN": ("brn", 0), "BSD": ("bsd", 0), "TBS": ("tbs", 2)}
SUFFIX = {"IBM (LTO8)": "L8", "IBM (LTO9)": "L9"}


def build_data() -> tuple[dict[str, list], dict[str, list]]:
    disk: dict[str, list] = {"tbs": [], "bsd": [], "brn": []}
    for row in json.loads((CACHE / "capacity_cache.json").read_text(encoding="utf-8")):
        site_host = f"{row['Site'].lower()}nbupapp1.telkomsel.co.id"
        disk[row["Master"].lower()].append(
            {
                "attributes": {
                    "name": row["Disk Pool Name"],
                    "sType": "PureDisk",
                    "usableSizeBytes": int(row["Usable (TB)"] * TB),
                    "availableSpaceBytes": int(row["Available (TB)"] * TB),
                    "usedCapacityBytes": int(row["Used (TB)"] * TB),
                },
                "relationships": {"storageServers": {"data": [{"id": f"PureDisk:{site_host}"}]}},
            }
        )
    tape: dict[str, list] = {"tbs": [], "bsd": [], "brn": []}
    for row in json.loads((CACHE / "tape_cache.json").read_text(encoding="utf-8")):
        master, robot = TAPE_ROBOT[row["Site"]]
        suffix = SUFFIX.get(row["Type Tape"], "L8")
        used, total = row["Tape Used (Qty)"], row["Total Tape (Qty)"]
        kb_each = (row["Used Capacity (TB)"] * KB_PER_TB / used) if used else 0
        for i in range(total):
            tape[master].append(
                {
                    "attributes": {
                        "barcode": f"{row['Site'][:1]}{i:05d}{suffix}",
                        "robot": {"robotNumber": robot},
                        "kiloBytes": int(kb_each) if i < used else 0,
                    }
                }
            )
    return disk, tape


class State:
    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        self.disk, self.tape = build_data()
        self.started = time.monotonic()
        self.stats: Counter[str] = Counter()
        self.lock = threading.Lock()

    def master_down(self, master: str) -> bool:
        a = self.args
        if master != a.down_master or not a.down_every:
            return False
        minute = (time.monotonic() - self.started) / 60
        return (minute % a.down_every) < a.down_for

    def count(self, key: str) -> None:
        with self.lock:
            self.stats[key] += 1


def make_handler(state: State):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):  # sunyi; statistik dicetak berkala
            pass

        def _json(self, code: int, body: dict, headers: dict | None = None) -> None:
            data = json.dumps(body).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/vnd.netbackup+json")
            self.send_header("Content-Length", str(len(data)))
            for k, v in (headers or {}).items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):  # noqa: N802
            url = urlparse(self.path)
            parts = url.path.strip("/").split("/")
            if len(parts) < 4 or parts[1] != "netbackup" or parts[0] not in state.disk:
                state.count("404")
                return self._json(404, {"errorMessage": "not found"})
            master, endpoint = parts[0], "/".join(parts[2:])
            if not self.headers.get("Authorization", "").startswith("Bearer "):
                state.count("401")
                return self._json(401, {"errorMessage": "unauthorized"})
            if state.master_down(master):
                state.count(f"down_{master}")
                time.sleep(state.args.down_hang_s)  # meniru master yang tidak menjawab
                self.close_connection = True
                return None
            if state.args.latency_ms:
                time.sleep(state.args.latency_ms / 1000)
            if random.random() < state.args.fail_rate:  # noqa: S311 — simulasi, bukan kriptografi
                state.count("503")
                return self._json(503, {"errorMessage": "busy"}, {"Retry-After": "1"})
            q = {k: v[0] for k, v in parse_qs(url.query).items()}
            limit = int(q.get("page[limit]", 50))
            if endpoint == "storage/disk-pools":
                offset = int(q.get("page[offset]", 0))
                state.count("disk_ok")
                return self._json(200, {"data": state.disk[master][offset : offset + limit]})
            if endpoint == "storage/tape-media":
                start = int(q.get("page[after]", 0))
                items = state.tape[master][start : start + limit]
                nxt = start + limit if start + limit < len(state.tape[master]) else None
                state.count("tape_ok")
                body = {"data": items, "meta": {"pagination": {"next": str(nxt) if nxt else None}}}
                return self._json(200, body)
            state.count("404")
            return self._json(404, {"errorMessage": "unknown endpoint"})

    return Handler


def main() -> None:
    parser = argparse.ArgumentParser(description="Mock 3 master NetBackup (DEV).")
    parser.add_argument("--port", type=int, default=8781)
    parser.add_argument("--fail-rate", type=float, default=0.0)
    parser.add_argument("--latency-ms", type=int, default=0)
    parser.add_argument("--down-master", choices=["tbs", "bsd", "brn"])
    parser.add_argument("--down-every", type=float, default=0, help="menit")
    parser.add_argument("--down-for", type=float, default=0, help="menit")
    parser.add_argument("--down-hang-s", type=float, default=25)
    parser.add_argument("--stats-every", type=int, default=600, help="detik")
    args = parser.parse_args()

    state = State(args)
    server = ThreadingHTTPServer(("127.0.0.1", args.port), make_handler(state))
    sizes = {m: (len(state.disk[m]), len(state.tape[m])) for m in state.disk}
    print(
        f"mock NBU di http://127.0.0.1:{args.port}/<tbs|bsd|brn>/netbackup  (disk, tape) = {sizes}",
        flush=True,
    )

    def report() -> None:
        while True:
            time.sleep(args.stats_every)
            with state.lock:
                print(f"[{time.strftime('%H:%M:%S')}] {dict(state.stats)}", flush=True)

    threading.Thread(target=report, daemon=True).start()
    server.serve_forever()


if __name__ == "__main__":
    main()
