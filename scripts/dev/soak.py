r"""soak.py — soak test ATLAS di DEV (Fase 5): web + semua job berjalan terus selama N jam.

Yang dijalankan (jadwal = usulan produksi, runbook §1):
  * mock NBU (scripts/dev/mock_nbu.py) dengan gangguan: 503 acak + satu master "mati" berkala
  * web ATLAS (uvicorn, port 8002)
  * capacity_job live ke mock NBU tiap 10 menit
  * inventory_job tiap 15 menit (salinan policy_cache.json; tiap run ke-4 satu schedule diubah → diff nyata)
  * maintenance_job saat mulai lalu tiap 24 jam
  * cmdb_import tiap 6 jam (bila --cmdb-xlsx diberikan)
Pemantauan tiap 30 detik: status & latensi endpoint, memori/handle proses web, koneksi DB.
Hasil: <out>/probes.jsonl, <out>/jobs.jsonl, <out>/status.json; laporan: --report <out>.

    .venv\Scripts\python.exe scripts\dev\soak.py --hours 72 --cmdb-xlsx "C:\...\OSPLA.xlsx"
    .venv\Scripts\python.exe scripts\dev\soak.py --report logs\soak\<folder>
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import statistics
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
PY = str(REPO / ".venv" / "Scripts" / "python.exe")
WEB_PORT = 8002
MOCK_PORT = 8781
PROBES = {
    "data": "/api/data",
    "health": "/api/health",
    "inventory_search": "/api/backup-inventory/search?hostnames=e-billpapp2%0Aussdgwbsdpapp1%0Aapp1",
    "audit_events": "/api/audit/events?limit=50",
}
SCHEDULE_MIN = {"capacity": 10, "inventory": 15, "maintenance": 24 * 60, "cmdb": 6 * 60}
JOB_TIMEOUT_S = 20 * 60


def now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def append(path: Path, record: dict) -> None:
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def job_env(out: Path) -> dict[str, str]:
    env = dict(os.environ)
    env.update(
        ATLAS_ALLOW_LIVE_NBU="1",
        ATLAS_CACHE_DIR=str(out / "cache"),
        ATLAS_NBU_MIN_INTERVAL_MS="50",
        PYTHONIOENCODING="utf-8",
    )
    for key in ("TBS", "BSD", "BRN"):
        env[f"NBU_{key}_URL"] = f"http://127.0.0.1:{MOCK_PORT}/{key.lower()}/netbackup"
        env[f"NBU_{key}_TOKEN"] = "soak-dummy-token"  # mock hanya memeriksa header ada
    return env


def mutate_policy_cache(path: Path, run: int) -> None:
    """Ubah startSeconds satu schedule agar inventory_job benar-benar menulis (update + refresh MV)."""
    cache = json.loads(path.read_text(encoding="utf-8"))
    for item in cache["policies"]:
        policy = item["data"]["attributes"]["policy"]
        if policy.get("policyAttributes", {}).get("active") and policy.get("schedules"):
            window = policy["schedules"][0].get("startWindow") or []
            if window:
                window[0]["startSeconds"] = 3600 if run % 2 else 7200
                break
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(cache), encoding="utf-8")
    tmp.replace(path)


def run_job(name: str, args: list[str], env: dict[str, str], jobs_log: Path) -> None:
    started = time.monotonic()
    try:
        proc = subprocess.run(  # noqa: S603 — perintah tetap, tanpa input user
            [PY, "-m", f"atlas.collectors.{args[0]}", *args[1:]],
            cwd=REPO,
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=JOB_TIMEOUT_S,
        )
        code, output = proc.returncode, (proc.stdout or "").strip().splitlines()
    except subprocess.TimeoutExpired:
        code, output = -1, ["TIMEOUT"]
    append(
        jobs_log,
        {
            "ts": now(),
            "job": name,
            "exit": code,
            "duration_s": round(time.monotonic() - started, 1),
            "output": output[-4:],
        },
    )


def probe(name: str, path: str) -> dict:
    started = time.monotonic()
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{WEB_PORT}{path}", timeout=10) as r:  # noqa: S310
            r.read()
            status = r.status
    except urllib.error.HTTPError as exc:
        status = exc.code
    except Exception as exc:
        status = f"ERR {type(exc).__name__}"
    return {"name": name, "status": status, "ms": round((time.monotonic() - started) * 1000, 1)}


def db_connections() -> int | None:
    try:
        import psycopg

        sys.path.insert(0, str(REPO))
        from atlas.core.config import load_settings

        s = load_settings()
        with psycopg.connect(s.db_conninfo("readonly", "soak-monitor"), connect_timeout=3) as conn:
            return conn.execute(
                "SELECT count(*) FROM pg_stat_activity WHERE datname = current_database()"
            ).fetchone()[0]
    except Exception:
        return None


def soak(hours: float, out: Path, cmdb_xlsx: Path | None, policy_cache: Path) -> None:
    import psutil

    out.mkdir(parents=True, exist_ok=True)
    (out / "cache").mkdir(exist_ok=True)
    probes_log, jobs_log = out / "probes.jsonl", out / "jobs.jsonl"
    work_cache = out / "policy_cache.json"
    shutil.copy(policy_cache, work_cache)
    env = job_env(out)
    procs = [
        subprocess.Popen(  # noqa: S603
            [
                PY,
                "scripts/dev/mock_nbu.py",
                "--port",
                str(MOCK_PORT),
                "--fail-rate",
                "0.03",
                "--down-master",
                "brn",
                "--down-every",
                "47",
                "--down-for",
                "2",
            ],
            cwd=REPO,
            stdout=(out / "mock_nbu.log").open("w"),
            stderr=subprocess.STDOUT,
        ),
        subprocess.Popen(  # noqa: S603
            [PY, "-m", "uvicorn", "atlas.web.main:app", "--host", "127.0.0.1", "--port", str(WEB_PORT)],
            cwd=REPO,
            stdout=(out / "web.log").open("w"),
            stderr=subprocess.STDOUT,
        ),
    ]
    web = psutil.Process(procs[1].pid)
    append(jobs_log, {"ts": now(), "job": "soak_start", "hours": hours, "pids": [p.pid for p in procs]})
    time.sleep(8)

    deadline = time.monotonic() + hours * 3600
    next_run = {name: time.monotonic() for name in SCHEDULE_MIN}
    running: dict[str, threading.Thread] = {}
    inventory_runs = 0

    def launch(name: str, job_args: list[str]) -> None:
        """Job di thread sendiri: pemantauan web tetap jalan selama job berlangsung."""
        if name in running and running[name].is_alive():
            append(jobs_log, {"ts": now(), "job": name, "exit": "skipped_still_running"})
            return
        running[name] = threading.Thread(target=run_job, args=(name, job_args, env, jobs_log), daemon=True)
        running[name].start()

    try:
        while time.monotonic() < deadline:
            tick = time.monotonic()
            for name, minutes in SCHEDULE_MIN.items():
                if tick < next_run[name]:
                    continue
                next_run[name] = tick + minutes * 60
                if name == "capacity":
                    launch(name, ["capacity_job"])
                elif name == "inventory":
                    inventory_runs += 1
                    if inventory_runs % 4 == 0 and not (running.get(name) and running[name].is_alive()):
                        mutate_policy_cache(work_cache, inventory_runs)
                    launch(name, ["inventory_job", "--cache", str(work_cache)])
                elif name == "maintenance":
                    launch(name, ["maintenance_job"])
                elif name == "cmdb" and cmdb_xlsx:
                    launch(name, ["cmdb_import", "--xlsx", str(cmdb_xlsx)])
            try:
                rss = web.memory_info().rss
                handles = getattr(web, "num_handles", lambda: None)()
                children = web.children(recursive=True)
                rss += sum(c.memory_info().rss for c in children)
            except psutil.Error:
                rss, handles = None, None
            record = {
                "ts": now(),
                "probes": [probe(n, p) for n, p in PROBES.items()],
                "web_rss_mb": round(rss / 1024**2, 1) if rss else None,
                "web_handles": handles,
                "db_connections": db_connections(),
            }
            append(probes_log, record)
            status = {"updated": now(), "remaining_h": round((deadline - time.monotonic()) / 3600, 2)}
            (out / "status.json").write_text(json.dumps(status), encoding="utf-8")
            time.sleep(max(1.0, 30 - (time.monotonic() - tick)))
    finally:
        for thread in running.values():
            thread.join(timeout=JOB_TIMEOUT_S)
        for p in procs:
            p.terminate()
        append(jobs_log, {"ts": now(), "job": "soak_end"})
    report(out)


# ---------------------------------------------------------------- laporan


def pct(values: list[float], q: float) -> float:
    values = sorted(values)
    return values[min(len(values) - 1, int(round(q * (len(values) - 1))))] if values else 0.0


def report(out: Path) -> str:
    probes = [json.loads(line) for line in (out / "probes.jsonl").read_text(encoding="utf-8").splitlines()]
    jobs = [json.loads(line) for line in (out / "jobs.jsonl").read_text(encoding="utf-8").splitlines()]
    lines = [f"# Laporan soak test — {out.name}", ""]
    if probes:
        lines += [f"Periode: {probes[0]['ts']} s.d. {probes[-1]['ts']} ({len(probes)} sampel pemantauan)", ""]
    lines += [
        "## Endpoint web",
        "",
        "| Endpoint | Sukses | Ketersediaan | p50 ms | p95 ms | maks ms |",
        "|---|---|---|---|---|---|",
    ]
    verdict = []
    for name in PROBES:
        samples = [p for rec in probes for p in rec["probes"] if p["name"] == name]
        ok = [s for s in samples if s["status"] in (200, 304)]
        ms = [s["ms"] for s in ok]
        avail = 100 * len(ok) / len(samples) if samples else 0
        lines.append(
            f"| {name} | {len(ok)}/{len(samples)} | {avail:.2f}% | {pct(ms, 0.5):.0f} | {pct(ms, 0.95):.0f} | {max(ms or [0]):.0f} |"
        )
        verdict.append(avail >= 99.9 and pct(ms, 0.95) < 1000)
    rss = [r["web_rss_mb"] for r in probes if r.get("web_rss_mb")]
    if rss:
        first, last = (
            statistics.mean(rss[: max(1, len(rss) // 10)]),
            statistics.mean(rss[-max(1, len(rss) // 10) :]),
        )
        growth = 100 * (last - first) / first
        lines += [
            "",
            f"Memori web: awal {first:.0f} MB → akhir {last:.0f} MB (pertumbuhan {growth:+.1f}%), maks {max(rss):.0f} MB",
        ]
        verdict.append(growth < 20)
    conns = [r["db_connections"] for r in probes if r.get("db_connections") is not None]
    if conns:
        lines.append(
            f"Koneksi DB (database atlas): maks {max(conns)}, rata-rata {statistics.mean(conns):.1f}"
        )
    lines += [
        "",
        "## Job",
        "",
        "| Job | Run | Exit 0 | Exit ≠ 0 | Durasi rata-rata (dtk) | maks |",
        "|---|---|---|---|---|---|",
    ]
    for name in SCHEDULE_MIN:
        runs = [j for j in jobs if j.get("job") == name]
        if not runs:
            continue
        failed = [j for j in runs if j["exit"] not in (0, "skipped_still_running")]
        durations = [j["duration_s"] for j in runs]
        lines.append(
            f"| {name} | {len(runs)} | {len(runs) - len(failed)} | {len(failed)} | {statistics.mean(durations):.1f} | {max(durations):.1f} |"
        )
        verdict.append(not failed)
    partial = sum(
        1 for j in jobs if j.get("job") == "capacity" and any("PARTIAL" in o for o in j.get("output", []))
    )
    lines += ["", f"Run kapasitas berstatus PARTIAL (master mock 'mati' disengaja): {partial}"]
    lines += [
        "",
        f"## Kesimpulan: {'LULUS' if verdict and all(verdict) else 'PERLU DITINJAU'}",
        "Kriteria: ketersediaan ≥ 99,9%, p95 < 1 dtk, memori web tumbuh < 20%, tidak ada job exit ≠ 0.",
    ]
    text = "\n".join(lines) + "\n"
    (out / "report.md").write_text(text, encoding="utf-8")
    print(text)
    return text


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")  # konsol Windows cp1252 tidak bisa menampilkan "→"
    parser = argparse.ArgumentParser(description="Soak test ATLAS (DEV).")
    parser.add_argument("--hours", type=float, default=72)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--cmdb-xlsx", type=Path)
    parser.add_argument(
        "--policy-cache", type=Path, default=Path(r"D:\bot\NetbackupBotV2\cache\policy_cache.json")
    )
    parser.add_argument("--report", type=Path, help="Buat laporan dari folder hasil soak")
    args = parser.parse_args()
    if args.report:
        report(args.report)
        return
    out = args.out or REPO / "logs" / "soak" / datetime.now().strftime("%Y%m%d_%H%M")
    soak(args.hours, out, args.cmdb_xlsx, args.policy_cache)


if __name__ == "__main__":
    main()
