"""Standalone capacity collector — invoked by Windows Task Scheduler every 10
minutes. Reuses the existing fetch/cache/export logic; the web app never
triggers a live master fetch itself."""

import os
import sys
from datetime import datetime

import netbackup_core as core

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_FILE = os.path.join(BASE_DIR, "logs", "scheduled_collect_log.txt")


def log(line):
    os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def main():
    result = core.generate_all()
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    if result["errors"]:
        line = f"[{ts}] Disk Pool & Tape Capacity TBS BSD BRN: FAILED - " + "; ".join(result["errors"])
        log(line)
        print(line)
        sys.exit(1)
    line = f"[{ts}] Disk Pool & Tape Capacity TBS BSD BRN: SUCCESS"
    log(line)
    print(line)


if __name__ == "__main__":
    main()
