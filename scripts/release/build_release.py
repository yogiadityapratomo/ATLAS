r"""build_release.py — paket rilis ATLAS dari tag Git.

deployment-workflow §3: zip + requirements terkunci + checksum.

Hasil di ``dist\atlas-<tag>\``:
  atlas-<tag>.zip     isi tag Git apa adanya (git archive) — tanpa .env, cache, log
  requirements.lock   dependency runtime terkunci (hasil resolve dari pyproject tag tsb)
  wheels\             wheel Windows/Python 3.13 untuk semua dependency + setuptools
                      → server bisa install TANPA internet/proxy: pip install --no-index --find-links wheels
  RELEASE.txt         tag, commit, waktu build, versi Python
  SHA256SUMS          checksum semua file di atas (diverifikasi saat deploy, langkah 5)

    .venv\Scripts\python.exe scripts\release\build_release.py --tag v0.1.1
    .venv\Scripts\python.exe scripts\release\build_release.py --ref HEAD     # uji coba, bukan untuk deploy
"""

from __future__ import annotations

import argparse
import hashlib
import shutil
import subprocess
import sys
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
PLATFORM = [
    "--platform",
    "win_amd64",
    "--python-version",
    "3.13",
    "--implementation",
    "cp",
    "--only-binary=:all:",
]


def git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=REPO, check=True, capture_output=True, text=True).stdout.strip()  # noqa: S603,S607


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build(ref: str, out_root: Path, *, wheels: bool) -> Path:
    commit = git("rev-parse", "--verify", f"{ref}^{{commit}}")
    name = ref if ref.startswith("v") else f"{ref}-{commit[:8]}"
    out = out_root / f"atlas-{name}"
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    archive = out / f"atlas-{name}.zip"
    git("archive", "--format=zip", f"--prefix=atlas-{name}/", "-o", str(archive), commit)
    print(f"[1/4] arsip {archive.name} dari {ref} ({commit[:8]})")

    with tempfile.TemporaryDirectory(prefix="atlas-release-") as tmp:
        src = Path(tmp) / "src"
        with zipfile.ZipFile(archive) as z:
            z.extractall(src)
        project = src / f"atlas-{name}"
        venv = Path(tmp) / "venv"
        subprocess.run([sys.executable, "-m", "venv", str(venv)], check=True)  # noqa: S603
        py = (
            str(venv / "Scripts" / "python.exe")
            if (venv / "Scripts").exists()
            else str(venv / "bin" / "python")
        )
        subprocess.run([py, "-m", "pip", "install", "-q", str(project)], check=True)  # noqa: S603
        frozen = subprocess.run(  # noqa: S603
            [py, "-m", "pip", "freeze", "--exclude", "atlas"], check=True, capture_output=True, text=True
        ).stdout
    lock = out / "requirements.lock"
    lines = sorted(line for line in frozen.splitlines() if line and not line.startswith("#"))
    lock.write_text(
        f"# ATLAS {name} — dependency runtime terkunci ({datetime.now():%Y-%m-%d})\n"
        + "\n".join(lines)
        + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(f"[2/4] requirements.lock: {len(lines)} paket")

    if wheels:
        wheel_dir = out / "wheels"
        subprocess.run(  # noqa: S603
            [
                sys.executable,
                "-m",
                "pip",
                "download",
                "-q",
                "-r",
                str(lock),
                "setuptools",
                "-d",
                str(wheel_dir),
                *PLATFORM,
            ],
            check=True,
        )
        print(f"[3/4] wheelhouse: {len(list(wheel_dir.glob('*.whl')))} wheel (win_amd64, cp313)")
    else:
        print("[3/4] wheelhouse dilewati (--no-wheels)")

    (out / "RELEASE.txt").write_text(
        f"tag/ref: {ref}\ncommit: {commit}\n"
        f"built_at: {datetime.now().astimezone().isoformat(timespec='seconds')}\n"
        f"build_python: {sys.version.split()[0]}\n",
        encoding="utf-8",
        newline="\n",
    )
    files = sorted(p for p in out.rglob("*") if p.is_file() and p.name != "SHA256SUMS")
    sums = "\n".join(f"{sha256(p)}  {p.relative_to(out).as_posix()}" for p in files) + "\n"
    (out / "SHA256SUMS").write_text(sums, encoding="utf-8", newline="\n")
    print(f"[4/4] SHA256SUMS: {len(files)} file → {out}")
    return out


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")  # konsol Windows cp1252
    parser = argparse.ArgumentParser(description="Bangun paket rilis ATLAS dari tag Git.")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--tag", help="Tag rilis, mis. v0.1.1 (untuk deploy)")
    group.add_argument("--ref", help="Ref lain untuk uji coba (bukan untuk deploy)")
    parser.add_argument("--out", type=Path, default=REPO / "dist")
    parser.add_argument("--no-wheels", action="store_true")
    args = parser.parse_args()
    if args.tag and not git("tag", "--list", args.tag):
        print(f"Tag {args.tag} tidak ada. Buat tag setelah merge ke main (deployment-workflow §3).")
        return 2
    build(args.tag or args.ref, args.out, wheels=not args.no_wheels)
    return 0


if __name__ == "__main__":
    sys.exit(main())
