"""Klien HTTP ke master NetBackup — master adalah sistem kritis, jadi klien ini sengaja "sopan".

* **Rate limit**: jeda minimum antar request per master (``ATLAS_NBU_MIN_INTERVAL_MS``).
* **Retry per halaman** untuk 429/5xx/timeout/koneksi putus, dengan backoff bertambah dan menghormati
  header ``Retry-After``. Retry **melanjutkan halaman yang gagal**, bukan mengulang dari halaman 1
  (V4 mengulang paginasi disk pool dari offset 0).
* **Deadline kooperatif** per master: dicek sebelum setiap halaman; tidak ada thread yang terus
  menembak master setelah pemanggil menyerah (masalah yang pernah terjadi di V4).
* **Lanjutan paginasi tape** antar run (sama dengan V4): progres disimpan saat gagal, dipakai lagi
  bila umurnya < 2 jam.
* Master diakses **berurutan, tidak paralel** (V4: request paralel lewat VPN membuat semua master gagal).
* Akses ke master tanpa proxy; sertifikat self-signed (``verify=False``, sama dengan V4).
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import requests
import urllib3

from atlas.core.config import NbuMaster
from atlas.core.errors import AtlasError
from atlas.core.logging import log_event

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
logger = logging.getLogger("atlas.nbu")

ACCEPT = "application/vnd.netbackup+json;version=11.0"
NO_PROXY = {"http": None, "https": None}
PAGE_LIMIT = 50
MAX_PAGES = 500
BACKOFF_BASE_S = 2.0
MAX_RETRY_AFTER_S = 60.0
TAPE_RESUME_MAX_AGE_S = 2 * 60 * 60
RETRYABLE_STATUS = {429, 500, 502, 503, 504}


class NbuError(AtlasError):
    default_user_message = "Gagal mengambil data dari master NetBackup."


class NbuClient:
    def __init__(
        self,
        master: NbuMaster,
        *,
        timeout_s: float = 20,
        min_interval_s: float = 0.2,
        max_retries: int = 3,
        session: Any = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if not master.token:
            raise NbuError(f"token NBU untuk {master.name} belum di-set (NBU_{master.name}_TOKEN)")
        self.master = master
        self.timeout_s = timeout_s
        self.min_interval_s = min_interval_s
        self.max_retries = max_retries
        self.session = session or requests.Session()
        self.sleep = sleep
        self.clock = clock
        self._last_request = 0.0
        self.requests_made = 0

    # ------------------------------------------------------------------ request dasar

    def _throttle(self) -> None:
        wait = self.min_interval_s - (self.clock() - self._last_request)
        if self._last_request and wait > 0:
            self.sleep(wait)
        self._last_request = self.clock()

    def get(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        """GET satu halaman dengan retry. Error akhir dilempar sebagai :class:`NbuError`."""
        url = f"{self.master.base_url}{path}"
        last: Exception | None = None
        for attempt in range(1, self.max_retries + 1):
            self._throttle()
            self.requests_made += 1
            try:
                response = self.session.get(
                    url,
                    headers={"Accept": ACCEPT, "Authorization": f"Bearer {self.master.token.get()}"},
                    params=params,
                    verify=False,
                    timeout=self.timeout_s,
                    proxies=NO_PROXY,
                )
            except (requests.Timeout, requests.ConnectionError) as exc:
                last, retry_after = exc, None
            else:
                if response.status_code < 400:
                    return response.json()
                last = NbuError(f"HTTP {response.status_code} dari {self.master.name} {path}")
                if response.status_code not in RETRYABLE_STATUS:
                    raise last
                retry_after = _retry_after(response)
            if attempt == self.max_retries:
                break
            delay = retry_after if retry_after is not None else BACKOFF_BASE_S * attempt
            log_event(
                logger,
                "job",
                "nbu_retry",
                f"Retry {self.master.name} {path} ({attempt}/{self.max_retries}) dalam {delay:.1f} dtk",
                severity="warning",
                master=self.master.name,
                path=path,
                attempt=attempt,
                reason=str(last),
            )
            self.sleep(delay)
        raise NbuError(
            f"{self.master.name} {path} gagal setelah {self.max_retries} percobaan: {last}"
        ) from last

    # ------------------------------------------------------------------ endpoint

    def disk_pools(self, *, deadline_s: float) -> list[dict[str, Any]]:
        """Semua item ``/storage/disk-pools`` (paginasi offset)."""
        items: list[dict[str, Any]] = []
        started = self.clock()
        offset = 0
        for _ in range(MAX_PAGES):
            self._check_deadline(started, deadline_s, len(items))
            data = self.get("/storage/disk-pools", {"page[limit]": PAGE_LIMIT, "page[offset]": offset}).get(
                "data", []
            )
            if not data:
                break
            items.extend(data)
            if len(data) < PAGE_LIMIT:
                break
            offset += PAGE_LIMIT
        else:
            raise NbuError(f"paginasi disk-pools {self.master.name} melebihi {MAX_PAGES} halaman")
        return items

    def tape_media(self, *, deadline_s: float, resume_dir: Path | None = None) -> list[dict[str, Any]]:
        """Atribut semua ``/storage/tape-media`` (paginasi cursor), dengan lanjutan antar run."""
        resume = _TapeResume(resume_dir, self.master.key) if resume_dir else None
        records, cursor = resume.load() if resume else ([], None)
        if cursor:
            log_event(
                logger,
                "job",
                "nbu_tape_resumed",
                f"Tape {self.master.name} dilanjutkan dari {len(records)} record sebelumnya",
                master=self.master.name,
                records=len(records),
            )
        started = self.clock()
        try:
            for _ in range(MAX_PAGES):
                self._check_deadline(started, deadline_s, len(records))
                params: dict[str, Any] = {"page[limit]": PAGE_LIMIT}
                if cursor:
                    params["page[after]"] = cursor
                page = self.get("/storage/tape-media", params)
                data = page.get("data", [])
                if not data:
                    break
                records.extend(item["attributes"] for item in data)
                cursor = page.get("meta", {}).get("pagination", {}).get("next")
                if not cursor:
                    break
            else:
                raise NbuError(f"paginasi tape-media {self.master.name} melebihi {MAX_PAGES} halaman")
        except Exception:
            if resume:
                resume.save(records, cursor)
            raise
        if resume:
            resume.clear()
        return records

    def _check_deadline(self, started: float, deadline_s: float, fetched: int) -> None:
        if self.clock() - started > deadline_s:
            raise NbuError(
                f"{self.master.name} tidak selesai dalam {deadline_s:.0f} dtk "
                f"(baru {fetched} record) — master kemungkinan overload/lambat"
            )


def _retry_after(response: Any) -> float | None:
    raw = (getattr(response, "headers", None) or {}).get("Retry-After")
    try:
        return min(float(raw), MAX_RETRY_AFTER_S) if raw is not None else None
    except ValueError:
        return None


class _TapeResume:
    def __init__(self, directory: Path, key: str) -> None:
        self.path = directory / f"tape_resume_{key}.json"

    def load(self) -> tuple[list[dict[str, Any]], str | None]:
        if not self.path.exists():
            return [], None
        if time.time() - self.path.stat().st_mtime > TAPE_RESUME_MAX_AGE_S:
            self.path.unlink(missing_ok=True)
            return [], None
        try:
            state = json.loads(self.path.read_text(encoding="utf-8"))
            return list(state["records"]), state["cursor"]
        except (ValueError, KeyError, TypeError):
            self.path.unlink(missing_ok=True)
            return [], None

    def save(self, records: list[dict[str, Any]], cursor: str | None) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"records": records, "cursor": cursor}), encoding="utf-8")
        tmp.replace(self.path)  # atomik: tidak ada file setengah tertulis

    def clear(self) -> None:
        self.path.unlink(missing_ok=True)
