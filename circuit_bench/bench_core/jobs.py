"""Background jobs of the Bench routes: detect, build and flash run in a thread each.

One ``JobTable`` per process (``table()`` = ``runtime.get("jobs", JobTable)``): the tool copy and the route copy of
the package share it. A job object::

    {"job_id", "kind": "detect|build|flash", "state": "queued|running|done|failed", "progress": 0..1|null,
     "started", "finished", "log_tail": [...], "result": <result envelope>|null}

- ``start(kind, work, key=...)`` returns the job object at once; ``work(ctx)`` runs in its own daemon thread and
  returns a result envelope. ``ctx.log(line)`` feeds ``log_tail`` (and the flash progress), ``ctx.progress(x)`` sets
  the progress. A job that returns ``ok: false`` (or raises) ends ``failed``.
- Every state change and (throttled) progress change sends ``job.updated`` ``{job_id, kind, state, progress}``.
- At most ``MAX_JOBS`` jobs are kept; finished jobs are dropped first (oldest first).
- ``key`` (e.g. ``"port:/dev/ttyACM0"``): while a job with the same key runs, another one is refused (``port_busy``).
- ``record(kind, project_id, envelope)`` stores the outcome in the bench project (``set_detected``, ``set_build``,
  ``set_flash``) through ``project.update`` (retried on ``project_conflict``).

Jobs do not survive a backend restart (new process): the job id carries a per-process suffix, so an id
from an earlier process is unknown instead of naming another job.
"""
from __future__ import annotations

import collections
import datetime as _dt
import logging
import re
import secrets
import threading
import time
from collections.abc import Callable, Mapping
from typing import Any

from . import events, runtime
from .contracts import BenchError, fail, warning

logger = logging.getLogger(__name__)

KINDS = ("detect", "build", "flash")
STATES = ("queued", "running", "done", "failed")
MAX_JOBS = 20
LOG_TAIL_LINES = 20
LOG_LINE_CHARS = 200
PROGRESS_EVENT_S = 0.5  # at most one progress event per job and interval
RECORD_ATTEMPTS = 3
_ACTION = {"detect": "board.detect", "build": "board.build", "flash": "board.flash"}
# esptool 5.x: "Writing at 0x00010000 [=====>     ] 52.3%"; esptool 4.x: "Writing at 0x00010000... (52 %)"
_WRITE_PCT_RE = re.compile(r"Writing at (0x[0-9a-fA-F]+).*?(\d{1,3}(?:\.\d+)?)\s*%")
# board.flash also writes bootloader, partition table and boot_app0 below the app; only the app's lines
# (from 0x10000, PlatformIO's application_offset of the espressif32 boards) move the progress bar
APP_MIN_OFFSET = 0x10000


def _now() -> str:
    return _dt.datetime.now(_dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


class JobContext:
    """Handed to ``work(ctx)``: feeds the job's log tail and progress (thread-safe, never raises)."""

    def __init__(self, table: JobTable, job: _Job):
        self._table = table
        self._job = job

    @property
    def job_id(self) -> str:
        return self._job.job_id

    def log(self, line: Any) -> None:
        try:
            text = str(line).rstrip("\r\n")[:LOG_LINE_CHARS]
            with self._table._lock:
                self._job.log_tail.append(text)
            if self._job.kind == "flash":
                m = _WRITE_PCT_RE.search(text)
                if m and int(m.group(1), 16) >= APP_MIN_OFFSET:
                    self.progress(min(float(m.group(2)), 100.0) / 100.0)
        except Exception as e:  # noqa: BLE001 - a progress callback must never stop the tool
            logger.debug("circuit-bench: job log line dropped (%s)", type(e).__name__)

    def progress(self, value: float | None) -> None:
        try:
            if value is not None:
                value = round(max(0.0, min(1.0, float(value))), 3)
            self._table._set_progress(self._job, value)
        except Exception as e:  # noqa: BLE001
            logger.debug("circuit-bench: job progress dropped (%s)", type(e).__name__)


class _Job:
    def __init__(self, job_id: str, kind: str, key: str | None):
        self.job_id = job_id
        self.kind = kind
        self.key = key
        self.state = "queued"
        self.progress: float | None = None
        self.started = _now()
        self.finished: str | None = None
        self.log_tail: collections.deque[str] = collections.deque(maxlen=LOG_TAIL_LINES)
        self.result: dict[str, Any] | None = None
        self.done = threading.Event()
        self.last_progress_event = 0.0
        self.thread: threading.Thread | None = None
        self.simulated = False

    def as_dict(self) -> dict[str, Any]:
        return {"job_id": self.job_id, "kind": self.kind, "state": self.state, "progress": self.progress,
                "started": self.started, "finished": self.finished, "log_tail": list(self.log_tail),
                "result": self.result}


class JobTable:
    """Process-wide job table (thread-safe)."""

    def __init__(self, *, emit: Callable[[str, Mapping[str, Any]], Any] | None = None, max_jobs: int = MAX_JOBS):
        self._lock = threading.Lock()
        self._jobs: collections.OrderedDict[str, _Job] = collections.OrderedDict()
        self._counter = 0
        self._suffix = secrets.token_hex(3)  # per process: ids of an earlier backend are unknown, not reused
        self._emit = emit if emit is not None else events.emit
        self._max = max(1, int(max_jobs))

    # ----------------------------------------------------------------- events
    def _event(self, job: _Job) -> None:
        if job.state == "queued":
            return
        try:
            self._emit("job.updated", {"job_id": job.job_id, "kind": job.kind, "state": job.state,
                                       "progress": job.progress})
        except Exception as e:  # noqa: BLE001 - an event never breaks a job
            logger.debug("circuit-bench: job.updated not sent (%s)", type(e).__name__)

    def _set_progress(self, job: _Job, value: float | None) -> None:
        with self._lock:
            if job.state != "running" or value == job.progress:
                return
            job.progress = value
            now = time.monotonic()
            send = now - job.last_progress_event >= PROGRESS_EVENT_S
            if send:
                job.last_progress_event = now
        if send:
            self._event(job)

    # ----------------------------------------------------------------- table
    def _evict(self) -> None:
        """Keep at most max_jobs - 1 entries before adding one (finished jobs first, oldest first)."""
        while len(self._jobs) >= self._max:
            victim = next((j for j in self._jobs.values() if j.done.is_set()), None)
            if victim is None:
                victim = next(iter(self._jobs.values()))
            self._jobs.pop(victim.job_id, None)

    def start(self, kind: str, work: Callable[[JobContext], Mapping[str, Any]], *, key: str | None = None,
              simulated: bool = False) -> dict[str, Any]:
        """Start ``work`` in a thread; returns the job object. Raises BenchError invalid_args (unknown kind) or
        port_busy (a job with the same ``key`` still runs). ``simulated``: the job targets a sim:// board."""
        if kind not in KINDS:
            raise BenchError("invalid_args", f"unknown job kind {kind!r}", f"kinds: {', '.join(KINDS)}")
        with self._lock:
            if key is not None:
                for other in self._jobs.values():
                    if other.key == key and not other.done.is_set():
                        what = key.split(":", 1)[1] if ":" in key else key
                        raise BenchError("port_busy", f"a {other.kind} job ({other.job_id}) is still running for {what}",
                                         f"wait for {other.job_id} to finish (GET /jobs/{other.job_id})")
            self._counter += 1
            job = _Job(f"j-{self._counter:04d}-{self._suffix}", kind, key)
            job.simulated = bool(simulated)
            self._evict()
            self._jobs[job.job_id] = job
            ctx = JobContext(self, job)
            job.thread = threading.Thread(target=self._run, args=(job, ctx, work), name=f"cb-job-{job.job_id}",
                                          daemon=True)
            snapshot = job.as_dict()
        job.thread.start()
        return snapshot

    def _run(self, job: _Job, ctx: JobContext, work: Callable[[JobContext], Mapping[str, Any]]) -> None:
        with self._lock:
            job.state = "running"
            job.started = _now()
        self._event(job)
        try:
            result = work(ctx)
            if not isinstance(result, Mapping) or "ok" not in result:
                result = fail(_ACTION[job.kind], "tool_failed", f"{job.kind} job returned no result envelope")
        except Exception as e:  # a job ends with an error envelope, never with an exception (logged)
            logger.exception("circuit-bench: %s job %s failed", job.kind, job.job_id)
            code = getattr(e, "code", None)
            if type(e).__name__ == "BenchError" and isinstance(code, str):
                try:
                    result = fail(_ACTION[job.kind], code, str(getattr(e, "message", e)), getattr(e, "hint", None))
                except ValueError:
                    result = fail(_ACTION[job.kind], "tool_failed", f"{job.kind} failed ({type(e).__name__})")
            else:
                result = fail(_ACTION[job.kind], "tool_failed", f"{job.kind} failed ({type(e).__name__})",
                              "see the Hermes log")
        with self._lock:
            job.result = dict(result)
            job.state = "done" if result.get("ok") is True else "failed"
            if job.state == "done":
                job.progress = 1.0
            job.finished = _now()
        job.done.set()
        self._event(job)

    def get(self, job_id: str) -> dict[str, Any] | None:
        with self._lock:
            job = self._jobs.get(job_id) if isinstance(job_id, str) else None
            return job.as_dict() if job else None

    def is_simulated(self, job_id: str) -> bool | None:
        """True if the job targets a sim:// board; None for an unknown job."""
        with self._lock:
            job = self._jobs.get(job_id) if isinstance(job_id, str) else None
            return job.simulated if job else None

    def running(self, key: str) -> str | None:
        """Id of an unfinished job started with ``key`` (e.g. ``build:<project>``), else None."""
        with self._lock:
            return next((j.job_id for j in self._jobs.values() if j.key == key and not j.done.is_set()), None)

    def list(self) -> list[dict[str, Any]]:
        with self._lock:
            return [j.as_dict() for j in self._jobs.values()]

    def wait(self, job_id: str, timeout: float | None = None) -> dict[str, Any] | None:
        """The job object after it finished (or the current one after ``timeout``); None if unknown."""
        with self._lock:
            job = self._jobs.get(job_id)
        if job is None:
            return None
        job.done.wait(timeout)
        return self.get(job_id)

    def wait_all(self, timeout: float = 10.0) -> bool:
        """Tests and shutdown: wait until every job finished. True if all did."""
        deadline = time.monotonic() + timeout
        with self._lock:
            jobs = list(self._jobs.values())
        for job in jobs:
            if not job.done.wait(max(0.0, deadline - time.monotonic())):
                return False
        return True


def table() -> JobTable:
    """The process-wide job table (shared by every copy of the package)."""
    return runtime.get("jobs", JobTable)


def summary(job: Mapping[str, Any]) -> str:
    """One English sentence about a job object (for the ``job.get`` envelope)."""
    kind = str(job.get("kind", "job")).capitalize()
    state = job.get("state")
    res = job.get("result") if isinstance(job.get("result"), Mapping) else None
    if state in ("done", "failed") and res is not None:
        return f"{kind} {state}: {res.get('summary', '')}".strip()
    if state == "running" and isinstance(job.get("progress"), int | float):
        return f"{kind} running ({round(float(job['progress']) * 100)} %)."
    return f"{kind} {state} (job {job.get('job_id')})."


# --------------------------------------------------------------------------------------------- project record

def _project_fields(kind: str, env: Mapping[str, Any], *, port: str | None, mac: str | None) -> tuple[str, dict] | None:
    """(op name, fields) for the project, or None if nothing is to be stored."""
    raw = env.get("result")
    res: Mapping[str, Any] = raw if isinstance(raw, Mapping) else {}
    if kind == "detect":
        if env.get("ok") is not True or not res.get("port"):
            return None  # a failed detection keeps the previous one
        return "set_detected", dict(res)
    if kind == "build":
        if env.get("ok") is True:
            return "set_build", dict(res)
        # a failed build must not leave an older approved ELF hash behind (the flash check reads last_build)
        return "set_build", {"ok": False, "ram_pct": res.get("ram_pct"), "flash_pct": res.get("flash_pct")}
    if kind == "flash":
        fields = {"ok": env.get("ok") is True, "port": res.get("port") or port, "mac": res.get("mac") or mac,
                  "elf_sha256": res.get("elf_sha256")}
        return "set_flash", fields
    return None


def record(kind: str, project_id: str, env: Mapping[str, Any], *, port: str | None = None,
           mac: str | None = None, by: str = "ui") -> dict[str, Any] | None:
    """Store a detect/build/flash outcome in project ``project_id`` (``set_detected``/``set_build``/``set_flash``).

    Returns None when stored (or nothing to store), else a warning object for the result envelope. ``mac``: the
    detected MAC, used when the flash output does not name one."""
    from . import project  # lazy: project imports pins, bom, solder ...

    picked = _project_fields(kind, env, port=port, mac=mac)
    if picked is None:
        return None
    op_name, fields = picked
    last: Mapping[str, Any] | None = None
    for _ in range(RECORD_ATTEMPTS):
        current = project.get(project_id)
        if current.get("ok") is not True:
            last = current
            break
        last = project.update(project_id, current["result"]["rev"], [{"op": op_name, **fields}], by=by, trusted=True)
        if last.get("ok") is True:
            return None
        if (last.get("error") or {}).get("code") != "project_conflict":
            break
    err = (last or {}).get("error") or {}
    return warning("project_not_updated", "caution",
                   f"the {kind} result was not stored in project {project_id!r}: {err.get('message', 'unknown error')}")
