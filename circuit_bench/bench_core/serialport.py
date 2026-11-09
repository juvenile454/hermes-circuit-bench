"""Serial port broker and the monitor action.

One ``Broker`` per process (``broker()`` = ``runtime.get("broker", Broker)``): the tool copy and the route copy of
the package share it.

- ``open(port, baud, *, reset=False)``: right after ``open()`` RTS goes inactive, then DTR (never DTR off with RTS
  on: that is the reset state); ``reset=True`` then pulses EN through RTS;
- one reader thread per port: ring buffer (5 000 lines) with ``seq`` (monotonic per port) and time stamp,
  subscribers get ``{"t": "line"|"panic"|"state", ...}`` messages;
- panic blocks start at every crash line the decoder knows (``crash.is_event_line``: Guru Meditation, abort(), assert,
  ESP_ERROR_CHECK, brownout, task watchdog, stack overflow, CORRUPT HEAP, stack smashing, UBSan) and run up to
  "Rebooting...", the next boot banner or 80 lines; each is stored as an artifact (``log_ref``) and announced as
  ``{"t": "panic", "seq", "summary", "log_ref"}``. A block with the signature of the previous one in the same read
  phase (header and first "Backtrace:" line, see ``panic_signature``) is a repeat: no new artifact, the message carries
  ``repeat`` (2, 3, ...) and the ``log_ref`` of the first block. open, close, pause and a reconnect
  start a new read phase;
- the artifacts folder keeps the newest ARTIFACT_KEEP files per kind (``prune_artifacts``, run when an artifact is
  created); files a project points to in ``debug.last_panic.log_ref`` are kept;
- every port name goes through ``normalize_port`` first (realpath of /dev links), so an alias such as
  /dev/serial/by-id/... shares lock, pause file and broker entry with its device;
- while a real port is open the process holds ``fcntl.flock`` on ``locks/<sha1(port)>.lock`` (second process:
  ``port_busy``);
- ``pause(port)`` frees the port for a flash: in this process directly, in other processes through the pause file
  ``locks/<sha1(port)>.pause``, which makes the holder close the port until the file is gone.
Ports with a registered provider prefix (``sim://``) read lines from ``provider.line_source(port)`` instead of
pyserial; they need no hardware access and no lock file.
"""
from __future__ import annotations

import collections
import contextlib
import datetime as _dt
import errno
import fcntl
import hashlib
import json
import logging
import math
import os
import re
import sys
import threading
import time
from collections.abc import Callable, Iterator, Mapping
from pathlib import Path
from typing import Any

from . import crash, runtime, storage
from . import settings as _settings
from .contracts import ERROR_CODES, BenchError, assumption, envelope, from_error, warning

logger = logging.getLogger(__name__)

RING_LINES = 5000
PANIC_MAX_LINES = 80
SUMMARY_MAX_CHARS = 120
ARTIFACT_KEEP = 200  # newest artifacts kept per kind (prefix before the first "-")
ARTIFACT_PRUNE_AT = 220  # pruning starts at this many files of one kind
TAIL_LIMIT = 200
MONITOR_MAX_LINES = 200
SIM_PANIC_SETTLE_S = 1.0  # a simulated board stops listening this long after its first panic
MONITOR_TEXT_BUDGET = 5000  # characters of line text in a monitor answer (answers stay <= 8 kB)
READ_TIMEOUT_S = 0.2
OPEN_ATTEMPTS = 3  # EPROTO right after a board restart re-enumerated the USB device: retry briefly
OPEN_RETRY_S = 0.7
RECONNECT_S = 10.0  # a board RESET re-enumerates a native USB port: the open monitor reopens it
RECONNECT_POLL_S = 0.25
PARTIAL_FLUSH_S = 1.0
PAUSE_POLL_S = 0.1
PAUSE_LOCK_WAIT_S = 5.0
PAUSE_STALE_S = 15 * 60
JOIN_TIMEOUT_S = 3.0
MAX_LINE_CHARS = 2000

PANIC_START = re.compile(r"Guru Meditation Error|abort\(\) was called|Brownout detector was triggered|"
                         r"Task watchdog got triggered")  # with crash.is_event_line; also the older task watchdog text
PANIC_END = re.compile(r"^\s*Rebooting\.\.\.")
BOOT_BANNER = re.compile(r"^(ESP-ROM:|rst:0x[0-9a-fA-F]+ )")  # a new boot starts: the panic block ended without "Rebooting..."
_GURU_RE = re.compile(r"Guru Meditation Error: Core\s+(\d+) panic'ed \(([^)]+)\)")
_ABORT_RE = re.compile(r"abort\(\) was called at PC (0x[0-9a-fA-F]+) on core (\d+)")
# summaries of the other crash lines of ESP-IDF v6.1 (same texts as the decoder, crash.py; source idf-v6.1-fatal-errors)
_ASSERT_RE = re.compile(r"assert failed: (\S+) (\S+):(\d+) \(")
_ASSERT_NEWLIB_RE = re.compile(r'assertion ".*" failed: file "([^"]*)", line (\d+)(?:, function: (\S+))?')
_ESP_ERR_RE = re.compile(r"ESP_ERROR_CHECK failed: esp_err_t (0x[0-9a-fA-F]+)(?: \(([A-Za-z0-9_]+)\))?")
_STACK_OVERFLOW_RE = re.compile(r"A stack overflow in task (.+?) has been detected")
_HEAP_RE = re.compile(r"CORRUPT HEAP: (.*?)\s*$")
_CANARY_RE = re.compile(r"Stack canary watchpoint triggered \(([^)]*)\)")
_UBSAN_RE = re.compile(r"Undefined behavior of type (\w+)")
_BACKTRACE_RE = re.compile(r"Backtrace:")
_IDF_LOG_TIME_RE = re.compile(r"^[EWIDV] \(\d+\) ")  # "E (10325) task_wdt: ...": the time differs on every print
_REF_RE = re.compile(r"^[a-z]+-\d{8}-\d{6}(?:-\d+)?\.log$")
_KIND_RE = re.compile(r"^([a-z]+)-")


# --------------------------------------------------------------------------------------------- artifacts

def artifacts_dir() -> Path:
    return storage.sub_dir("artifacts")


def open_artifact(kind: str) -> tuple[str, Any]:
    """New log file ``<kind>-YYYYmmdd-HHMMSS[-n].log`` under artifacts/ (0600): (log_ref, text file). Prunes the
    folder afterwards (``prune_artifacts``; never the new file)."""
    if not re.match(r"^[a-z]+$", kind):
        raise BenchError("invalid_args", f"bad artifact kind {kind!r}")
    folder = artifacts_dir()
    stamp = _dt.datetime.now(_dt.UTC).strftime("%Y%m%d-%H%M%S")
    for i in range(1000):
        name = f"{kind}-{stamp}.log" if i == 0 else f"{kind}-{stamp}-{i}.log"
        try:
            fd = os.open(folder / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            continue
        f = os.fdopen(fd, "w", encoding="utf-8", errors="replace")
        prune_artifacts(folder, keep=(name,))
        return name, f
    raise BenchError("invalid_args", "too many artifacts in one second")


def write_artifact(kind: str, lines: list[str]) -> str:
    ref, f = open_artifact(kind)
    with f:
        f.write("\n".join(lines) + "\n")
    return ref


def _referenced_artifacts() -> set[str]:
    """``debug.last_panic.log_ref`` of every readable project. The project files are read as plain JSON (the project
    module imports far more than this one needs); unreadable or foreign projects are skipped."""
    refs: set[str] = set()
    root = storage.data_dir() / "projects"
    try:
        entries = list(os.scandir(root))
    except OSError:
        return refs
    for entry in entries:
        try:
            if not entry.is_dir(follow_symlinks=False):
                continue
            with open(os.path.join(entry.path, "project.json"), encoding="utf-8") as f:
                ref = json.load(f)["debug"]["last_panic"]["log_ref"]
        except Exception:  # noqa: BLE001,S112 - missing, unreadable or damaged project: nothing to keep from it
            continue
        if isinstance(ref, str):
            refs.add(ref)
    return refs


def prune_artifacts(folder: Path | None = None, keep: tuple[str, ...] = ()) -> int:
    """Retention of the artifacts folder: per kind (the prefix before the first "-": panic, build, flash, monitor,
    schematic, ...) at ARTIFACT_PRUNE_AT files or more, the oldest (mtime) are removed until ARTIFACT_KEEP are left.
    Kept: the names in ``keep`` and every ``debug.last_panic.log_ref`` of a project. Only regular files directly in
    the folder count; symlinks and folders are never touched. Errors are logged, never raised. → files removed."""
    removed = 0
    try:
        folder = artifacts_dir() if folder is None else folder
        groups: dict[str, list[tuple[int, str]]] = collections.defaultdict(list)
        with os.scandir(folder) as it:
            for entry in it:
                m = _KIND_RE.match(entry.name)
                if m is None or not entry.is_file(follow_symlinks=False):
                    continue
                groups[m.group(1)].append((entry.stat(follow_symlinks=False).st_mtime_ns, entry.name))
        full = [files for files in groups.values() if len(files) >= ARTIFACT_PRUNE_AT]
        if not full:
            return 0
        protected = _referenced_artifacts() | set(keep)
        failed: list[str] = []
        for files in full:
            excess = len(files) - ARTIFACT_KEEP
            for _mtime, name in sorted(files):
                if excess <= 0:
                    break
                if name in protected:
                    continue
                path = folder / name
                try:
                    if path.is_symlink():  # replaced since the scan: not ours to remove
                        continue
                    path.unlink()
                except FileNotFoundError:
                    pass  # removed by another process in the meantime
                except OSError as e:
                    failed.append(f"{name}: {e}")
                    continue
                else:
                    removed += 1
                excess -= 1
        if failed:
            logger.warning("circuit-bench: artifact cleanup: %d file(s) not removed (%s)", len(failed), failed[0])
    except Exception as e:  # noqa: BLE001 - cleanup must never break storing an artifact
        logger.warning("circuit-bench: artifact cleanup failed (%s: %s)", type(e).__name__, e)
    return removed


def artifact_path(log_ref: str) -> Path:
    """Path of an artifact by its ``log_ref`` (no path traversal)."""
    if not isinstance(log_ref, str) or not _REF_RE.match(log_ref):
        raise BenchError("invalid_args", f"bad log_ref {log_ref!r}")
    path = artifacts_dir() / log_ref
    if not path.is_file():
        raise BenchError("invalid_args", f"unknown log_ref {log_ref!r}")
    return path


# --------------------------------------------------------------------------------------------- locks

def _key(port: str) -> str:
    return hashlib.sha1(port.encode("utf-8"), usedforsecurity=False).hexdigest()


def lock_path(port: str) -> Path:
    return storage.sub_dir("locks") / f"{_key(port)}.lock"


def pause_path(port: str) -> Path:
    return storage.sub_dir("locks") / f"{_key(port)}.pause"


def _try_lock(port: str) -> int:
    """Exclusive flock on the port's lock file; returns the fd. Held by someone else -> port_busy."""
    fd = os.open(lock_path(port), os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as e:
        os.close(fd)
        if e.errno in (errno.EWOULDBLOCK, errno.EAGAIN, errno.EACCES):
            raise BenchError("port_busy", f"{port} is open in another Circuit Bench process",
                             "close it there (serial close) or wait for the flash to finish") from None
        raise
    return fd


def _unlock(fd: int | None) -> None:
    if fd is None:
        return
    with contextlib.suppress(OSError):
        fcntl.flock(fd, fcntl.LOCK_UN)
    with contextlib.suppress(OSError):
        os.close(fd)


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def pause_requested(port: str) -> bool:
    """True while a live process asks to free ``port`` (stale pause files are ignored and removed)."""
    path = pause_path(port)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        pid, at = int(data["pid"]), float(data["at"])
    except FileNotFoundError:
        return False
    except (OSError, ValueError, KeyError, TypeError):
        return True  # being written right now, or foreign content: be safe and treat as a request
    if _pid_alive(pid) and time.time() - at < PAUSE_STALE_S:
        return True
    with contextlib.suppress(OSError):
        path.unlink()
    return False


# --------------------------------------------------------------------------------------------- other holders

PROC_ROOT = Path("/proc")  # Linux; the tests point it at a fake tree
HOLDER_COMMAND_MAX = 60


def _proc_text(path: Path) -> str:
    try:
        return path.read_bytes().decode("utf-8", "replace")
    except OSError:
        return ""


def _holder(pid_dir: Path) -> dict[str, Any]:
    """{pid, name (comm), command (program name + three arguments, short)} of one /proc/<pid>."""
    name = _proc_text(pid_dir / "comm").strip()
    argv = [a for a in _proc_text(pid_dir / "cmdline").split("\0") if a]
    command = " ".join([os.path.basename(argv[0]), *argv[1:4]]) if argv else name
    return {"pid": int(pid_dir.name), "name": name or "?", "command": command[:HOLDER_COMMAND_MAX] or "?"}


def port_holders(port: str) -> list[dict[str, Any]]:
    """Other processes that have ``port`` open, from the ``/proc/<pid>/fd`` links (Linux): [{pid, name, command}].

    Never opens the device. This process is left out (``pause`` has stopped its own monitor). Processes of other
    users are not visible without permission; without /proc (macOS, Windows) the list is empty."""
    try:
        entries = os.listdir(PROC_ROOT)
    except OSError:
        return []
    me = os.getpid()
    out: list[dict[str, Any]] = []
    for entry in entries:
        if not entry.isdigit() or int(entry) == me:
            continue
        fd_dir = PROC_ROOT / entry / "fd"
        try:
            fds = os.listdir(fd_dir)
        except OSError:  # gone meanwhile, another user's process, or no folder
            continue
        for fd in fds:
            try:
                target = os.readlink(fd_dir / fd)
            except OSError:
                continue
            if target == port:
                out.append(_holder(PROC_ROOT / entry))
                break
    return sorted(out, key=lambda h: h["pid"])


def check_port_free(port: str) -> None:
    """Raise BenchError port_busy if another program has ``port`` open (``port_holders``). Called inside ``pause``
    right before esptool runs: a second reader swallows esptool's replies and a flash dies half-written."""
    holders = port_holders(port)
    if not holders:
        return
    who = ", ".join(f"PID {h['pid']} ({h['command']})" for h in holders)
    raise BenchError("port_busy", f"{port} is open in another program: {who}; esptool would lose its replies",
                     "close the serial monitor in that program (Arduino IDE, pio device monitor, screen, another "
                     "Hermes with a Circuit Bench monitor) or stop the process, then retry")


# --------------------------------------------------------------------------------------------- serial

def _ts() -> str:
    now = _dt.datetime.now()
    return now.strftime("%H:%M:%S.") + f"{now.microsecond // 1000:03d}"


def _open_serial(port: str, baud: int, reset: bool) -> Any:
    try:
        import serial
    except ImportError:
        raise BenchError("dependency_missing", "pyserial is not installed", "install the plugin's Python dependencies (pyserial)") from None
    handle = None
    for attempt in range(OPEN_ATTEMPTS):
        try:
            handle = serial.serial_for_url(port, do_not_open=True, baudrate=baud, timeout=READ_TIMEOUT_S)
            handle.open()
            break
        except (serial.SerialException, OSError, ValueError) as e:
            code = getattr(e, "errno", None)
            if code == errno.EBUSY:
                raise BenchError("port_busy", f"{port} is busy (another program has it open)",
                                 "close serial monitors (Arduino IDE, pio device monitor, screen) and retry") from None
            if code == errno.ENOENT:
                raise BenchError("port_not_found", f"{port} does not exist", "replug the board and list the ports again") from None
            if code == errno.EACCES:
                raise BenchError("tool_failed", f"no permission to open {port}", _settings.SERIAL_GROUP_HINT) from None
            if code == errno.EPROTO:
                if attempt + 1 < OPEN_ATTEMPTS:
                    time.sleep(OPEN_RETRY_S)
                    continue
                raise BenchError("tool_failed", f"{port} did not answer (USB protocol error); the board is probably "
                                 "restarting", "wait a few seconds and open the port again") from None
            raise BenchError("tool_failed", f"could not open {port}: {e}") from None
    try:
        # Linux raises DTR and RTS when a tty opens. RTS goes off first, then DTR: the lines never pass DTR off with
        # RTS on, the reset state of the auto-reset circuit and of the USB-Serial/JTAG. Setting both off before open()
        # passes it (pyserial applies DTR first) and restarted an ESP32-S3 on its native USB on every open.
        handle.rts = False
        handle.dtr = False
    except (serial.SerialException, OSError) as e:
        logger.info("circuit-bench: DTR/RTS on %s not set (%s)", port, e)
    if reset:
        try:  # EN pulse through RTS with IO0 high (DTR inactive): normal boot
            handle.dtr = False
            handle.rts = True
            time.sleep(0.1)
            handle.rts = False
        except (serial.SerialException, OSError) as e:
            logger.info("circuit-bench: reset pulse on %s not possible (%s)", port, e)
    return handle


def starts_panic(text: str) -> bool:
    """Does this serial line open a panic block? Every crash line of the decoder (``crash.is_event_line``) and the
    task watchdog text of older IDF versions (PANIC_START)."""
    return bool(PANIC_START.search(text)) or crash.is_event_line(crash.clean_line(text))


def _base(path: str) -> str:
    return path.replace("\\", "/").rsplit("/", 1)[-1]


def panic_summary(first_line: str, lines: list[str] | None = None) -> str:
    """Short name of a crash from its first line; ``lines`` (the whole block) adds the stack canary of a debug
    exception, which the second line names."""
    text = crash.clean_line(first_line)
    out = "panic"
    m = _GURU_RE.search(text)
    if m:
        out = f"{m.group(2)} · core {m.group(1)}"
        canary = next((c for c in map(_CANARY_RE.search, lines or ()) if c), None)
        if canary:
            out = f"Stack canary watchpoint ({canary.group(1)}) · core {m.group(1)}"
    elif m := _ABORT_RE.search(text):
        out = f"abort() · core {m.group(2)}"
    elif m := _ASSERT_RE.search(text):
        out = f"assert failed in {m.group(1)} ({_base(m.group(2))}:{m.group(3)})"
    elif m := _ASSERT_NEWLIB_RE.search(text):
        where = f"{_base(m.group(1))}:{m.group(2)}"
        out = f"assert failed in {m.group(3)} ({where})" if m.group(3) else f"assert failed ({where})"
    elif m := _ESP_ERR_RE.search(text):
        out = f"ESP_ERROR_CHECK failed ({m.group(2) or m.group(1)})"
    elif m := _STACK_OVERFLOW_RE.search(text):
        out = f"stack overflow in task {m.group(1)}"
    elif m := _HEAP_RE.search(text):
        detail = m.group(1).split(". ", 1)[0].rstrip(".")[:60]
        out = f"CORRUPT HEAP: {detail}" if detail else "CORRUPT HEAP"
    elif "Stack smashing protect failure" in text:
        out = "Stack smashing protect failure"
    elif m := _UBSAN_RE.search(text):
        out = f"UBSan: {m.group(1)}"
    elif "Brownout detector was" in text:
        out = "Brownout detector triggered"
    elif "Task watchdog got triggered" in text:
        out = "Task watchdog triggered"
    return out[:SUMMARY_MAX_CHARS]


def _sig_line(text: str) -> str:
    return _IDF_LOG_TIME_RE.sub("", crash.clean_line(text), count=1)


def panic_signature(lines: list[str]) -> tuple[str, ...]:
    """What makes two panic blocks the same crash: the cleaned header line plus the cleaned first "Backtrace:" line;
    without a backtrace the next 3 non-empty cleaned lines. Cleaned = ``crash.clean_line`` (ANSI colours, monitor time
    stamps) and without the IDF log time "E (1234) ". Register values differ between two boots of one reboot loop
    (tests/fixtures/real/esp32s3-reboot-loop.log) and are not part of it."""
    if not lines:
        return ()
    head = _sig_line(lines[0])
    rest = [_sig_line(t) for t in lines[1:]]
    trace = next((t for t in rest if _BACKTRACE_RE.search(t)), None)
    if trace is not None:
        return (head, trace)
    return (head, *[t for t in rest if t.strip()][:3])


class _Run:
    """One reader thread run (a port may be opened, paused and reopened many times)."""

    def __init__(self) -> None:
        self.stop = threading.Event()
        self.thread: threading.Thread | None = None


class _Port:
    def __init__(self, name: str):
        self.name = name
        self.ctl = threading.RLock()  # open/close/pause
        self.data = threading.Lock()  # ring buffer, subscribers, state
        self.seq = 0
        self.lines: collections.deque[dict[str, Any]] = collections.deque(maxlen=RING_LINES)
        self.subs: dict[int, Callable[[dict[str, Any]], None]] = {}
        self.next_token = 0
        self.state = "closed"
        self.detail = ""
        self.baud: int | None = None
        self.simulated = False
        self.want_open = False
        self.run: _Run | None = None
        self.local_pauses = 0
        self.panic_block: dict[str, Any] | None = None
        self.last_panic: dict[str, Any] | None = None
        # repeat detection within one read phase: signature, log_ref and count of the last stored block
        self.panic_sig: tuple[str, ...] | None = None
        self.panic_sig_ref: str | None = None
        self.panic_sig_count = 0

    def reset_signature(self) -> None:
        """A new read phase (open, close, pause, reconnect): the next panic gets its own artifact. The Desktop compares
        the time stamp in log_ref with last_flash.at (serialPanicLive), so a repeat never spans a flash."""
        with self.data:
            self.panic_sig, self.panic_sig_ref, self.panic_sig_count = None, None, 0

    def status(self) -> dict[str, Any]:
        with self.data:
            return {"port": self.name, "state": self.state, "detail": self.detail, "baud": self.baud,
                    "next_seq": self.seq + 1, "simulated": self.simulated}


_DEVICE_RE = re.compile(r"^/dev/(?:tty[^/\s]+|cu\.[^/\s]+)$")  # /dev/ttyACM0, /dev/ttyUSB0, /dev/cu.usbserial-1
_ALIAS_RE = re.compile(r"^/dev/serial/by-(?:id|path)/[^/\s]+$")  # udev links, resolved to the device
_PTS_RE = re.compile(r"^/dev/pts/[^/\s]+$")  # pseudo-terminals: only with CIRCUIT_BENCH_DEV_GUARD=1 (tests, socat)
_COM_RE = re.compile(r"^COM\d{1,3}$")
PORT_HINT = "use a serial device like /dev/ttyACM0, /dev/ttyUSB0, /dev/serial/by-id/..., /dev/cu.*, COM3 or a sim:// port"


_realpath = os.path.realpath  # module level so tests can map /dev/serial/by-id links


def _dev_mode() -> bool:
    return os.environ.get(storage.ENV_DEV_GUARD) == "1"


def normalize_port(port: Any) -> str:
    """The one name of a port for locks, broker, jobs, pause files and approvals.

    - ``sim://`` and other URLs: unchanged (the board module refuses URLs without a provider);
    - ``COM1``..``COM999``: unchanged;
    - ``/dev/tty*``, ``/dev/cu.*`` and the udev links ``/dev/serial/by-id|by-path/*``: ``os.path.realpath`` (no open,
      only lstat/readlink), which must again be a ``/dev/tty*`` or ``/dev/cu.*`` device;
    - with ``CIRCUIT_BENCH_DEV_GUARD=1`` also ``/dev/pts/*`` (pseudo-terminals of tests and socat).
    Anything else raises BenchError ``invalid_args``; a missing by-id/by-path link raises ``port_not_found``."""
    if not isinstance(port, str) or not port.strip() or len(port) > 256 or any(c in port for c in "\0\n\r"):
        raise BenchError("invalid_args", "port must be a device path like /dev/ttyACM0 or a sim:// port")
    port = port.strip()
    if "://" in port or _COM_RE.match(port):
        return port
    dev = _dev_mode()
    if not (_DEVICE_RE.match(port) or _ALIAS_RE.match(port) or (dev and _PTS_RE.match(port))):
        raise BenchError("invalid_args", f"bad port {port[:80]!r}: not a serial device", PORT_HINT)
    real = _realpath(port)
    if _ALIAS_RE.match(port) and real == port:
        raise BenchError("port_not_found", f"{port[:120]} does not exist", "replug the board and list the ports again")
    if not (_DEVICE_RE.match(real) or (dev and _PTS_RE.match(real))):
        raise BenchError("invalid_args", f"{port[:80]} resolves to {real[:80]}, not a serial device", PORT_HINT)
    return real


def _check_port(port: Any) -> str:
    return normalize_port(port)


def _check_baud(baud: Any) -> int:
    if baud is None:
        return int(_settings.load()["default_baud"])
    if isinstance(baud, bool) or not isinstance(baud, int | float) or not 300 <= baud <= 5_000_000 or int(baud) != baud:
        raise BenchError("invalid_args", f"bad baud rate {baud!r}", "use e.g. 115200")
    return int(baud)


def _provider(port: str) -> Any | None:
    from . import board  # lazy: board imports this module
    return board.provider_for(port)


class Broker:
    """Process-wide owner of open serial ports. Thread-safe."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._ports: dict[str, _Port] = {}

    # ----------------------------------------------------------------- bookkeeping
    def _get(self, port: str) -> _Port:
        with self._lock:
            p = self._ports.get(port)
            if p is None:
                p = self._ports[port] = _Port(port)
            return p

    def _publish(self, p: _Port, msg: dict[str, Any]) -> None:
        with p.data:
            subs = list(p.subs.values())
        for cb in subs:
            try:
                cb(dict(msg))
            except Exception as e:  # noqa: BLE001 - a subscriber must not stop the reader
                logger.debug("circuit-bench: serial subscriber failed (%s)", type(e).__name__)

    def _set_state(self, p: _Port, state: str, detail: str = "") -> None:
        with p.data:
            p.state, p.detail = state, detail
        self._publish(p, {"t": "state", "port": p.name, "state": state, "detail": detail})

    def _emit_line(self, p: _Port, run: _Run, text: str) -> None:
        if run.stop.is_set():
            return
        text = text[:MAX_LINE_CHARS]
        with p.data:
            p.seq += 1
            msg = {"t": "line", "seq": p.seq, "ts": _ts(), "text": text}
            p.lines.append(msg)
        self._publish(p, msg)
        for panic in self._feed_panic(p, msg):
            self._publish(p, panic)

    def _feed_panic(self, p: _Port, msg: dict[str, Any]) -> list[dict[str, Any]]:
        """Panic messages caused by this line (usually none; two when a boot banner ends one block)."""
        out: list[dict[str, Any]] = []
        blk = p.panic_block
        if blk is not None and BOOT_BANNER.search(msg["text"]):
            closed = self._close_panic(p)
            if closed is not None:
                out.append(closed)
            blk = None
        if blk is None:
            if starts_panic(msg["text"]):
                p.panic_block = {"seq": msg["seq"], "lines": [msg["text"]]}
            return out
        blk["lines"].append(msg["text"])
        if PANIC_END.search(msg["text"]) or len(blk["lines"]) >= PANIC_MAX_LINES:
            closed = self._close_panic(p)
            if closed is not None:
                out.append(closed)
        return out

    def _close_panic(self, p: _Port) -> dict[str, Any] | None:
        """End the open block: a new artifact, or a repeat of the previous block of this read phase (same
        panic_signature): then no new artifact, ``repeat`` = 2, 3, ... and the first block's log_ref."""
        blk, p.panic_block = p.panic_block, None
        if blk is None:
            return None
        lines = blk["lines"]
        sig = panic_signature(lines)
        ref: str | None = None
        with p.data:
            repeat = p.panic_sig_count + 1 if p.panic_sig_ref is not None and p.panic_sig == sig else None
            if repeat is not None:
                p.panic_sig_count = repeat
                ref = p.panic_sig_ref
        if repeat is None:
            try:
                ref = write_artifact("panic", lines)
            except (BenchError, OSError) as e:
                logger.warning("circuit-bench: panic log not stored (%s)", e)
                ref = None
            with p.data:  # a block that could not be stored is no reference for repeats
                p.panic_sig, p.panic_sig_ref, p.panic_sig_count = (sig, ref, 1) if ref else (None, None, 0)
        msg = {"t": "panic", "seq": blk["seq"], "summary": panic_summary(lines[0], lines), "log_ref": ref}
        if repeat is not None:
            msg["repeat"] = repeat
        with p.data:
            # the newest panic for tail()/the stream snapshot keeps the stream fields (desktop fixture serial.lines)
            p.last_panic = {k: msg[k] for k in ("t", "seq", "summary", "log_ref")}
        return msg

    # ----------------------------------------------------------------- reader threads
    def _start(self, p: _Port, baud: int, reset: bool) -> None:
        """Open the port and start its reader (caller holds p.ctl). Raises BenchError."""
        provider = _provider(p.name)
        run = _Run()
        if provider is None:
            if "://" in p.name:
                raise BenchError("invalid_args", f"unsupported port URL {p.name!r}", "use a local device path or a sim:// port")
            if not _settings.hardware_enabled():
                raise BenchError("sim_only", "hardware access is off: real boards are not reachable",
                                 _settings.sim_only_hint())
            if p.name.startswith("/") and not os.path.exists(p.name):
                raise BenchError("port_not_found", f"{p.name} does not exist", "replug the board and list the ports again")
            fd = _try_lock(p.name)
            try:
                handle = _open_serial(p.name, baud, reset)
            except BaseException:
                _unlock(fd)
                raise
            target, args = self._read_serial, (p, run, handle, fd)
        else:
            source = iter(provider.line_source(p.name))
            target, args = self._read_source, (p, run, source)
        with p.data:
            p.baud, p.simulated = baud, provider is not None
        p.reset_signature()  # open, and the reopen after a pause: a new read phase
        p.run = run
        run.thread = threading.Thread(target=target, args=args, name=f"cb-serial-{p.name}", daemon=True)
        self._set_state(p, "open", f"{baud} baud")
        run.thread.start()

    def _stop(self, p: _Port) -> None:
        """Stop the reader (caller holds p.ctl); the reader closes the port and releases the lock itself."""
        run, p.run = p.run, None
        if run is None:
            return
        run.stop.set()
        if run.thread is not None and run.thread is not threading.current_thread():
            run.thread.join(JOIN_TIMEOUT_S)

    def _reconnect(self, p: _Port, run: _Run, handle: Any) -> Any:
        """The device went away while open. A RESET on a board with a native USB port re-enumerates it under the same
        name within about a second (ESP32-S3): reopen it (DTR/RTS inactive) for up to RECONNECT_S. → the new
        handle, or None (stopped, closed by the user, or the device stayed away)."""
        with contextlib.suppress(Exception):
            handle.close()
        p.reset_signature()  # the board restarted (RESET, replug): a new read phase
        if not p.want_open:
            return None
        self._set_state(p, "reconnecting", "port lost (board reset or unplugged); reopening")
        deadline = time.monotonic() + RECONNECT_S
        while not run.stop.is_set() and time.monotonic() < deadline:
            run.stop.wait(RECONNECT_POLL_S)
            if run.stop.is_set() or not os.path.exists(p.name):
                continue
            try:
                new = _open_serial(p.name, p.baud or 115200, False)
            except BenchError:
                continue
            self._set_state(p, "open", f"{p.baud} baud (reconnected)")
            return new
        return None

    def _read_serial(self, p: _Port, run: _Run, handle: Any, fd: int | None) -> None:
        buf = bytearray()
        last_data = time.monotonic()
        last_pause_check = 0.0
        try:
            while not run.stop.is_set():
                now = time.monotonic()
                if now - last_pause_check >= PAUSE_POLL_S:
                    last_pause_check = now
                    if pause_requested(p.name):
                        self._flush_partial(p, run, buf)
                        handle, fd = self._yield_to_other_process(p, run, handle, fd)
                        if handle is None:
                            return
                        continue
                try:
                    waiting = handle.in_waiting
                    data = handle.read(waiting or 1)
                except Exception as e:  # noqa: BLE001 - unplugged board, pty closed, driver errors
                    self._flush_partial(p, run, buf)
                    if run.stop.is_set():
                        return
                    handle = self._reconnect(p, run, handle)
                    if handle is None:
                        if not run.stop.is_set():
                            self._set_state(p, "error", f"read failed: {type(e).__name__}")
                        return
                    continue
                if data:
                    last_data = time.monotonic()
                    buf.extend(data)
                    while True:
                        i = buf.find(b"\n")
                        if i < 0:
                            break
                        raw = bytes(buf[:i])
                        del buf[:i + 1]
                        self._emit_line(p, run, raw.decode("utf-8", errors="replace").rstrip("\r"))
                    if len(buf) > MAX_LINE_CHARS:
                        self._flush_partial(p, run, buf)
                elif buf and time.monotonic() - last_data > PARTIAL_FLUSH_S:
                    self._flush_partial(p, run, buf)
        finally:
            with contextlib.suppress(Exception):
                if handle is not None:
                    handle.close()
            _unlock(fd)
            panic = self._close_panic(p)
            if panic is not None:
                self._publish(p, panic)

    def _flush_partial(self, p: _Port, run: _Run, buf: bytearray) -> None:
        if buf:
            text = bytes(buf).decode("utf-8", errors="replace").rstrip("\r")
            buf.clear()
            self._emit_line(p, run, text)

    def _yield_to_other_process(self, p: _Port, run: _Run, handle: Any, fd: int | None) -> tuple[Any, int | None]:
        """Another process flashes this port: close it, wait until the pause file is gone, then reopen."""
        with contextlib.suppress(Exception):
            handle.close()
        _unlock(fd)
        p.reset_signature()  # another process flashes: a new read phase afterwards
        self._set_state(p, "paused", "another Circuit Bench process is flashing this board")
        while not run.stop.is_set() and pause_requested(p.name):
            run.stop.wait(PAUSE_POLL_S)
        new_fd = None
        while not run.stop.is_set():
            try:
                new_fd = _try_lock(p.name)
                break
            except BenchError:
                run.stop.wait(PAUSE_POLL_S)
        if run.stop.is_set():
            _unlock(new_fd)
            return None, None
        try:
            new_handle = _open_serial(p.name, p.baud or 115200, False)
        except BenchError as e:
            _unlock(new_fd)
            self._set_state(p, "error", e.message)
            return None, None
        self._set_state(p, "open", f"{p.baud} baud")
        return new_handle, new_fd

    def _read_source(self, p: _Port, run: _Run, source: Iterator[Any]) -> None:
        try:
            for line in source:
                if run.stop.is_set():
                    break
                self._emit_line(p, run, str(line).rstrip("\r\n"))
            else:
                # the simulated log ended: the board stays "open" and quiet until close()/pause()
                panic = self._close_panic(p)
                if panic is not None:
                    self._publish(p, panic)
                run.stop.wait()
        except Exception as e:  # noqa: BLE001 - a broken provider ends the stream, not the process
            if not run.stop.is_set():
                self._set_state(p, "error", f"line source failed: {type(e).__name__}")
        finally:
            close = getattr(source, "close", None)
            if callable(close):
                with contextlib.suppress(Exception):
                    close()
            panic = self._close_panic(p)
            if panic is not None:
                self._publish(p, panic)

    # ----------------------------------------------------------------- public API
    def open(self, port: str, baud: int | None = None, *, reset: bool = False) -> dict[str, Any]:
        """Open ``port`` (idempotent for the same baud). Raises BenchError: invalid_args, sim_only, port_not_found,
        port_busy, dependency_missing, tool_failed."""
        port = _check_port(port)
        baud = _check_baud(baud)
        p = self._get(port)
        with p.ctl:
            if p.local_pauses:
                raise BenchError("port_busy", f"{port} is paused for a flash", "wait until the flash has finished")
            if p.run is not None and p.run.thread is not None and p.run.thread.is_alive():
                if p.baud == baud and not reset:
                    return p.status()
                self._stop(p)
            self._start(p, baud, reset)
            p.want_open = True
        return p.status()

    def close(self, port: str) -> dict[str, Any]:
        port = _check_port(port)
        p = self._get(port)
        with p.ctl:
            p.want_open = False
            self._stop(p)
            p.reset_signature()
            if p.local_pauses == 0:
                self._set_state(p, "closed")
        return p.status()

    def is_open(self, port: str) -> bool:
        try:
            port = _check_port(port)
        except BenchError:
            return False  # not a port name: nothing of it is open
        p = self._ports.get(port)
        return bool(p and p.run is not None and p.run.thread is not None and p.run.thread.is_alive())

    def status(self, port: str) -> dict[str, Any]:
        return self._get(_check_port(port)).status()

    def subscribe(self, port: str, cb: Callable[[dict[str, Any]], None]) -> Callable[[], None]:
        """Call ``cb(msg)`` for every line/panic/state message of ``port`` (from the reader thread; keep it fast)."""
        p = self._get(_check_port(port))
        with p.data:
            token = p.next_token
            p.next_token += 1
            p.subs[token] = cb

        def unsubscribe() -> None:
            with p.data:
                p.subs.pop(token, None)

        return unsubscribe

    def tail(self, port: str, after_seq: int | None = None, limit: int = TAIL_LIMIT) -> dict[str, Any]:
        """Lines with seq > ``after_seq`` (oldest first, at most ``limit``); without ``after_seq`` the last ``limit``.
        {"port", "state", "lines", "panic", "next_seq"} (polling fallback of the stream)."""
        p = self._get(_check_port(port))
        limit = max(1, min(int(limit), RING_LINES))
        with p.data:
            if after_seq is None:
                lines = list(p.lines)[-limit:]
            else:
                lines = [m for m in p.lines if m["seq"] > after_seq][:limit]
            next_seq = lines[-1]["seq"] + 1 if lines else p.seq + 1
            return {"port": p.name, "state": p.state, "lines": [dict(m) for m in lines],
                    "panic": dict(p.last_panic) if p.last_panic else None, "next_seq": next_seq,
                    "simulated": p.simulated}

    @contextlib.contextmanager
    def pause(self, port: str) -> Iterator[None]:
        """Free ``port`` for a flash and reopen it afterwards (if it was open). Raises BenchError port_busy if another
        Circuit Bench process does not release it within PAUSE_LOCK_WAIT_S."""
        port = _check_port(port)
        p = self._get(port)
        simulated = _provider(port) is not None
        with p.ctl:
            p.local_pauses += 1
            reopen = p.baud if p.run is not None else None
            self._stop(p)
            p.reset_signature()  # a flash or detect: the board runs new firmware or was reset
            if reopen is not None:
                self._set_state(p, "paused", "flash in progress")
        fd: int | None = None
        pause_file: Path | None = None
        try:
            if not simulated:
                pause_file = pause_path(port)
                tmp = pause_file.with_suffix(f".tmp{os.getpid()}")
                tmp.write_text(json.dumps({"pid": os.getpid(), "at": time.time()}), encoding="utf-8")
                os.replace(tmp, pause_file)
                deadline = time.monotonic() + PAUSE_LOCK_WAIT_S
                while True:
                    try:
                        fd = _try_lock(port)
                        break
                    except BenchError:
                        if time.monotonic() >= deadline:
                            raise
                        time.sleep(PAUSE_POLL_S)
            yield
        finally:
            _unlock(fd)
            if pause_file is not None:
                with contextlib.suppress(OSError):
                    pause_file.unlink()
            with p.ctl:
                p.local_pauses -= 1
                if p.local_pauses == 0:
                    if reopen is not None and p.want_open:
                        try:
                            self._start(p, reopen, False)
                        except BenchError as e:
                            self._set_state(p, "error", e.message)
                    elif reopen is not None:
                        self._set_state(p, "closed")

    def shutdown(self) -> None:
        """Close every port (tests, process exit)."""
        with self._lock:
            ports = list(self._ports.values())
        for p in ports:
            with p.ctl:
                p.want_open = False
                self._stop(p)


def broker() -> Broker:
    """The process-wide broker (shared by every copy of the package).

    Its methods raise the BenchError class of the package copy that created it. Code in another copy should call
    the module functions below (open_port/close_port/port_status/port_is_open/tail/subscribe/pause), which re-raise as this copy's BenchError."""
    return runtime.get("broker", Broker)


def local_error(exc: BaseException) -> BenchError | None:
    """``exc`` as this copy's BenchError if it is a BenchError of any package copy, else None."""
    if isinstance(exc, BenchError):
        return exc
    code = getattr(exc, "code", None)
    if type(exc).__name__ == "BenchError" and code in ERROR_CODES:
        return BenchError(code, str(getattr(exc, "message", "") or exc), getattr(exc, "hint", None))
    return None


def _call(fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    try:
        return fn(*args, **kwargs)
    except Exception as e:
        err = local_error(e)
        if err is None or err is e:
            raise
        raise err from None


def open_port(port: str, baud: int | None = None, *, reset: bool = False) -> dict[str, Any]:
    return _call(broker().open, port, baud, reset=reset)


def close_port(port: str) -> dict[str, Any]:
    return _call(broker().close, port)


def port_status(port: str) -> dict[str, Any]:
    return _call(broker().status, port)


def port_is_open(port: str) -> bool:
    return bool(_call(broker().is_open, port))


def tail(port: str, after_seq: int | None = None, limit: int = TAIL_LIMIT) -> dict[str, Any]:
    return _call(broker().tail, port, after_seq, limit)


def subscribe(port: str, cb: Callable[[dict[str, Any]], None]) -> Callable[[], None]:
    return _call(broker().subscribe, port, cb)


@contextlib.contextmanager
def pause(port: str) -> Iterator[None]:
    cm = _call(broker().pause, port)
    _call(cm.__enter__)
    try:
        yield
    except BaseException:
        if not cm.__exit__(*sys.exc_info()):
            raise
    else:
        cm.__exit__(None, None, None)


# --------------------------------------------------------------------------------------------- monitor action

def _monitor_notes(port: str) -> dict[str, Any] | None:
    """``monitor_notes(port)`` of the port's provider (optional in the provider protocol), checked; else None."""
    provider = _provider(port)
    fn = getattr(provider, "monitor_notes", None) if provider is not None else None
    if not callable(fn):
        return None
    try:
        notes = fn(port)
    except Exception as e:  # noqa: BLE001 - provider bugs must not break the monitor answer
        logger.warning("circuit-bench: monitor notes of %s failed (%s)", port, type(e).__name__)
        return None
    if not isinstance(notes, Mapping) or not isinstance(notes.get("lines_source"), str):
        return None
    return {"lines_source": notes["lines_source"],
            "assumptions": [a for a in notes.get("assumptions") or [] if isinstance(a, Mapping) and a.get("key")],
            "warnings": [w for w in notes.get("warnings") or [] if isinstance(w, Mapping) and w.get("code")
                         and w.get("severity") in ("info", "caution", "danger")]}


def monitor(port: str, seconds: float, baud: int | None = None, *, reset: bool = False) -> dict[str, Any]:
    """Action serial.monitor (tool): listen ``seconds`` (<= monitor_max_seconds) and return at most 200 lines.
    ``log_ref``: the first panic block (for bench_crash decode); without a panic the full capture when it does not
    fit (with a panic that capture is named in the assumption ``capture_ref``). A port the broker already holds
    (e.g. the desktop stream) is only listened to, not reopened."""
    action = "serial.monitor"
    assumptions: list[dict[str, Any]] = []
    warns: list[dict[str, Any]] = []
    try:
        cfg = _settings.load()
        port = _check_port(port)
        if isinstance(seconds, bool) or not isinstance(seconds, int | float) or not math.isfinite(seconds) or seconds <= 0:
            raise BenchError("invalid_args", "seconds must be a positive number")
        max_s = float(cfg["monitor_max_seconds"])
        if seconds > max_s:
            assumptions.append(assumption("seconds", f"{max_s:g}", f"limited by the monitor_max_seconds setting ({max_s:g} s)"))
            seconds = max_s
        baud = _check_baud(baud)
        events: list[dict[str, Any]] = []
        guard = threading.Lock()

        def collect(msg: dict[str, Any]) -> None:
            if msg.get("t") in ("line", "panic") or (msg.get("t") == "state" and msg.get("state") == "error"):
                with guard:
                    events.append(msg)

        unsubscribe = subscribe(port, collect)
        opened_here = False
        try:
            if port_is_open(port):
                if reset:
                    warns.append(warning("reset_skipped", "info", f"{port} was already open; no reset was done"))
            else:
                open_port(port, baud, reset=reset)
                opened_here = True
            if not reset:
                assumptions.append(assumption("reset", "false", "DTR/RTS were set inactive before opening; some boards "
                                              "still restart when the port opens"))
            sim_port = bool(port_status(port)["simulated"])  # real ports always listen the full time
            started = time.monotonic()
            deadline = started + seconds
            settle_at: float | None = None
            while time.monotonic() < deadline:
                if sim_port and settle_at is None:
                    with guard:
                        if any(m["t"] == "panic" for m in events):
                            settle_at = min(deadline, time.monotonic() + SIM_PANIC_SETTLE_S)
                if settle_at is not None and time.monotonic() >= settle_at:
                    break
                limit = deadline if settle_at is None else settle_at
                time.sleep(min(0.05, max(0.0, limit - time.monotonic())))
            if settle_at is not None and settle_at < deadline:
                seconds = round(time.monotonic() - started, 1)
                assumptions.append(assumption("stopped_early", "true", f"simulated board: stopped {SIM_PANIC_SETTLE_S:g} s "
                                              "after the first panic"))
        finally:
            unsubscribe()
            if opened_here:
                close_port(port)
        simulated = port_status(port)["simulated"]
        notes = _monitor_notes(port) if simulated else None
    except BenchError as e:
        return from_error(action, e, warnings=warns)
    with guard:
        lines = [m["text"] for m in events if m["t"] == "line"]
        panics = [{k: m[k] for k in ("seq", "summary", "log_ref", "repeat") if k in m} for m in events if m["t"] == "panic"]
    shown: list[str] = []
    budget = MONITOR_TEXT_BUDGET
    for text in reversed(lines[-MONITOR_MAX_LINES:]):
        cut = text[:300]
        if budget - len(cut) < 0:
            break
        budget -= len(cut)
        shown.append(cut)
    shown.reverse()
    truncated = len(shown) < len(lines) or any(len(t) > 300 for t in lines)
    capture_ref = None
    if truncated:
        try:
            capture_ref = write_artifact("monitor", lines)
        except (BenchError, OSError) as e:
            logger.warning("circuit-bench: monitor log not stored (%s)", e)
    # log_ref: what bench_crash decode needs, the first panic block; otherwise the full capture
    log_ref = panics[0]["log_ref"] if panics and panics[0].get("log_ref") else capture_ref
    if capture_ref is not None and log_ref != capture_ref:
        assumptions.append(assumption("capture_ref", capture_ref, "log_ref is the first panic block; the full "
                                      "capture of this monitor run is stored under this ref"))
    failed = [m for m in events if m["t"] == "state"]
    if failed:  # e.g. the board restarted and its USB device was re-enumerated: the handle is gone
        warns.append(warning("port_lost", "caution", f"{port} stopped while listening ({failed[0].get('detail') or 'read failed'}); "
                             "the board probably restarted or was unplugged: open the monitor again"))
    # one warning per stored block: repeats of a reboot loop share the first block's log_ref
    groups: dict[Any, list[dict[str, Any]]] = {}
    for pnc in panics:
        groups.setdefault(pnc["log_ref"] or ("seq", pnc["seq"]), []).append(pnc)
    for group in groups.values():
        pnc = group[0]
        seen = f" (seen {len(group)} times: same header and backtrace)" if len(group) > 1 else ""
        warns.append(warning("panic_detected", "caution", f"panic at seq {pnc['seq']}: {pnc['summary']}{seen}; decode it "
                             f"with bench_crash (log_ref {pnc['log_ref']}, and project for the ELF)",
                             ["idf-v6.1-fatal-errors"]))
    result = {"port": port, "baud": baud, "seconds": seconds, "line_count": len(lines), "lines": shown,
              "truncated": truncated, "log_ref": log_ref, "panics": panics, "simulated": simulated}
    if notes is not None:  # a provider port (sim://): where its lines come from
        result["lines_source"] = notes["lines_source"]
        assumptions += notes["assumptions"]
        warns += notes["warnings"]
    tail = f", panic: {panics[0]['summary']}" if panics else ""
    summary = f"{port}: {len(lines)} line{'s' if len(lines) != 1 else ''} in {seconds:g} s at {baud} baud{tail}" + \
              (" (simulated)." if simulated else ".")
    srcs = []
    if panics:
        from . import sources
        srcs = sources.resolve(["idf-v6.1-fatal-errors"])
    return envelope(action, summary, result, warnings=warns, assumptions=assumptions, sources=srcs, simulated=simulated)
