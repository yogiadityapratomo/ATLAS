r"""verify_release.py — cek SHA256SUMS paket rilis ATLAS sebelum dipasang.

deployment-workflow §4.2 langkah 5.

Hanya pustaka standar Python: bisa dijalankan di server sebelum venv rilis dibuat. [READ-ONLY]

    python verify_release.py C:\SBM\ATLAS\incoming\atlas-v0.1.1
"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path


def main() -> int:
    if len(sys.argv) != 2:
        print("Pemakaian: python verify_release.py <folder paket>")
        return 2
    root = Path(sys.argv[1])
    sums = root / "SHA256SUMS"
    if not sums.is_file():
        print(f"SHA256SUMS tidak ada di {root}")
        return 1
    bad, count = [], 0
    for line in sums.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        expected, name = line.split(None, 1)
        path = root / name.strip()
        count += 1
        if not path.is_file():
            bad.append(f"HILANG  {name}")
            continue
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest != expected:
            bad.append(f"BERUBAH {name}")
    listed = {
        line.split(None, 1)[1].strip()
        for line in sums.read_text(encoding="utf-8").splitlines()
        if line.strip()
    }
    extra = [
        p.relative_to(root).as_posix()
        for p in root.rglob("*")
        if p.is_file() and p.name != "SHA256SUMS" and p.relative_to(root).as_posix() not in listed
    ]
    bad += [f"TAMBAHAN {e}" for e in extra]
    for item in bad:
        print(item)
    print(f"{count} file diperiksa: {'GAGAL — jangan dipasang' if bad else 'semua cocok'}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
