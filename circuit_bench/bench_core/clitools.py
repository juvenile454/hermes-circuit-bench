"""Finding and running the user's command line tools (pio, esptool, addr2line).

- never through a shell; minimal environment (no API keys, no ESPTOOL_* overrides; PlatformIO telemetry off unless
  the user set PLATFORMIO_SETTING_ENABLE_TELEMETRY);
- own process group, killed as a whole on timeout;
- hardware switch: calls that touch a board are refused with sim_only while
  CIRCUIT_BENCH_HW=off or hardware_access=false.
"""
from __future__ import annotations

import collections
import os
import shutil
import signal
import subprocess
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

from . import settings as _settings
from .contracts import BenchError

_KEEP_ENV = ("PATH", "HOME", "TMPDIR", "USER", "LOGNAME")
_KEEP_PREFIXES = ("PLATFORMIO_",)
_ESPTOOL_NAMES = ("esptool", "esptool.py")
# PlatformIO targets that only build or read the project (PlatformIO Core 6.2.0 builder/main.py, espressif32 6.9.0
# builder/main.py): ``buildprog`` (ELF + firmware.bin), ``checkprogsize`` (RAM/flash lines), ``__idedata``
# (``pio project metadata``), size reports and cleaning. Every other target may reach a board.
BUILD_ONLY_TARGETS = frozenset({"buildprog", "checkprogsize", "size", "sizedata", "__idedata", "compiledb", "clean",
                                "cleanall", "fullclean", "buildfs", "envdump"})
# Explicit targets of the offline build: the default targets of espressif32 (``Default([buildprog, size])``, where
# PlatformIO replaces ``size`` with ``checkprogsize``), so the build and its size lines stay the same while the
# ``targets`` option of platformio.ini is ignored. Order matters: PlatformIO makes every command line target depend
# on the one before it (builder/main.py), and espressif32 makes firmware.bin depend on checkprogsize, so
# ``-t buildprog -t checkprogsize`` is a dependency cycle; ``-t checkprogsize -t buildprog`` is not (checked offline).
PIO_BUILD_TARGETS = ("checkprogsize", "buildprog")
PIO_TELEMETRY = "PLATFORMIO_SETTING_ENABLE_TELEMETRY"


def _candidates(name: str) -> list[Path]:
    home = Path(os.environ.get("HOME") or Path.home())
    if name in ("pio", "platformio"):
        return [home / ".platformio" / "penv" / "bin" / name, home / ".local" / "bin" / name]
    if name in _ESPTOOL_NAMES:
        return [home / ".local" / "bin" / name]
    return []


def _executable(p: str | Path | None) -> str | None:
    if not p:
        return None
    path = Path(p).expanduser()
    return str(path) if path.is_file() and os.access(path, os.X_OK) else None


def find(name: str, override: str | None = None) -> str | None:
    """Absolute path of tool ``name``: explicit override (settings), PATH, then known install folders."""
    if override:
        return _executable(override)
    names = _ESPTOOL_NAMES if name in _ESPTOOL_NAMES else (name,)
    for n in names:
        hit = shutil.which(n)
        if hit:
            return hit
    for n in names:
        for c in _candidates(n):
            hit = _executable(c)
            if hit:
                return hit
    return None


def pio_targets(args: Sequence[str]) -> list[str]:
    """The ``-t``/``--target`` values of a ``pio run`` command line (``-t X``, ``-tX``, ``--target X``, ``--target=X``)."""
    args = [str(a) for a in args]
    out: list[str] = []
    for i, a in enumerate(args):
        if a in ("-t", "--target"):
            if i + 1 < len(args):
                out.append(args[i + 1])
        elif a.startswith("--target="):
            out.append(a.split("=", 1)[1])
        elif a.startswith("-t") and len(a) > 2 and not a.startswith("--"):
            out.append(a[2:])
    return out


def touches_hardware(argv: Sequence[str]) -> bool:
    """True for esptool calls and every PlatformIO call that may reach a board.

    ``pio run`` counts as a build only with explicit targets that are all in ``BUILD_ONLY_TARGETS``: without ``-t``
    PlatformIO runs the ``targets`` of platformio.ini instead (PlatformIO Core 6.2.0, run/cli.py ``process_env``:
    ``targets = targets or config.get(f"env:{name}", "targets", [])``), which can be ``upload, monitor``.
    ``pio test``/``debug``/``remote`` upload or talk to a probe; ``pio device monitor`` opens the port."""
    if not argv:
        return False
    base = os.path.basename(str(argv[0]))
    args = [str(a) for a in argv[1:]]
    if base in _ESPTOOL_NAMES and len(args) == 1 and args[0] in ("version", "--version", "-h", "--help"):
        return False  # esptool prints its version or help without opening a port
    if base in _ESPTOOL_NAMES or any(a in ("esptool", "esptool.py") for a in args[:3]):
        return True
    if base not in ("pio", "platformio"):
        if args[:2] == ["-m", "platformio"]:
            return touches_hardware(["platformio", *args[2:]])
        return False
    if not args or args[0] in ("--version", "--help", "-h"):
        return False
    sub = args[0]
    if sub == "run":
        targets = pio_targets(args[1:])
        return not targets or any(t not in BUILD_ONLY_TARGETS for t in targets)
    if sub == "device":
        return args[1:2] == ["monitor"]
    if sub in ("test", "debug", "remote"):
        return True
    return sub.startswith("-")  # global options before the command: not a call this plugin makes, refuse


def is_pio(argv: Sequence[str]) -> bool:
    return bool(argv) and os.path.basename(str(argv[0])) in ("pio", "platformio")


def minimal_env(extra: Mapping[str, str] | None = None, *, pio: bool = False) -> dict[str, str]:
    """PATH, HOME, TMPDIR, USER, LOGNAME and PLATFORMIO_* of this process plus ``extra``. ``pio``: a PlatformIO call;
    telemetry defaults to off (``PLATFORMIO_SETTING_ENABLE_TELEMETRY=No``) unless the user set the variable."""
    env = {k: v for k, v in os.environ.items() if k in _KEEP_ENV or k.startswith(_KEEP_PREFIXES)}
    env["LANG"] = "C.UTF-8"
    env["LC_ALL"] = "C.UTF-8"
    env["PYTHONUNBUFFERED"] = "1"
    env.setdefault("PATH", os.defpath)
    if pio:
        env.setdefault(PIO_TELEMETRY, "No")
    if extra:
        env.update({str(k): str(v) for k, v in extra.items()})
    return env


def _kill_group(proc: subprocess.Popen) -> None:
    for sig in (signal.SIGTERM, signal.SIGKILL):
        try:
            os.killpg(proc.pid, sig)
        except (ProcessLookupError, PermissionError):
            break
        try:
            proc.wait(timeout=3)
            return
        except subprocess.TimeoutExpired:
            continue
    # the group is gone (or ignored SIGKILL): reap the tool itself so no zombie stays and returncode is set
    try:
        proc.wait(timeout=1)
    except subprocess.TimeoutExpired:
        pass


def run(argv: Sequence[str], *, timeout: float, cwd: str | Path | None = None,
        env_extra: Mapping[str, str] | None = None, tail: int = 200,
        on_line: Callable[[str], None] | None = None, hardware: bool | None = None,
        stop_when: Callable[[str], bool] | None = None) -> dict[str, Any]:
    """Run a tool. Returns {"rc", "out_tail", "duration_s", "timed_out", "stopped", "stop_line"} (stdout+stderr
    merged, last ``tail`` lines).

    ``hardware``: True marks the call as touching a board; None or False leave it to ``touches_hardware(argv)``
    (False cannot clear a command line that reaches a board, e.g. ``pio run`` without ``-t``). ``stop_when``: called
    for every output line (after ``on_line``); True ends the whole process group like a timeout (``stopped`` true,
    ``stop_line`` the line). An exception in ``stop_when`` stops as well (fail-closed: it guards a board). An
    exception while waiting (e.g. KeyboardInterrupt) ends the process group, too, and is raised again.
    Raises BenchError: sim_only (hardware switch off), tool_missing (executable not found), invalid_args (empty argv).
    """
    if not argv:
        raise BenchError("invalid_args", "empty command")
    argv = [str(a) for a in argv]
    if (hardware is True or touches_hardware(argv)) and not _settings.hardware_enabled():
        raise BenchError("sim_only", "hardware access is off: real boards are not reachable", _settings.sim_only_hint())
    started = time.monotonic()
    lines: collections.deque[str] = collections.deque(maxlen=max(1, tail))
    stop = threading.Event()
    stop_line: list[str] = []
    try:
        proc = subprocess.Popen(  # noqa: S603 - argv list, no shell
            argv, cwd=str(cwd) if cwd else None, env=minimal_env(env_extra, pio=is_pio(argv)), stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, start_new_session=True,
            text=True, encoding="utf-8", errors="replace", bufsize=1)
    except FileNotFoundError:
        raise BenchError("tool_missing", f"{os.path.basename(argv[0])} not found",
                         _settings.tool_hint(argv[0])) from None
    except PermissionError:
        raise BenchError("tool_missing", f"{os.path.basename(argv[0])} is not executable") from None

    def _close_stdout() -> None:
        try:
            if proc.stdout is not None:
                proc.stdout.close()
        except (ValueError, OSError):
            pass

    def pump() -> None:
        if proc.stdout is None:
            return
        try:
            for raw in proc.stdout:
                line = raw.rstrip("\r\n")
                if stop.is_set():
                    continue  # output after the stop line is not the tool's answer any more
                lines.append(line)
                if on_line is not None:
                    try:
                        on_line(line)
                    except Exception:  # noqa: BLE001,S110 - a progress callback must not stop the tool
                        pass
                if stop_when is not None:
                    try:
                        hit = bool(stop_when(line))
                    except Exception:  # noqa: BLE001 - a broken guard stops the tool (fail-closed)
                        hit = True
                    if hit:
                        stop_line.append(line)
                        stop.set()
        except (ValueError, OSError):
            pass  # the pipe was closed under the reader: nothing more to read
        finally:
            _close_stdout()

    reader = threading.Thread(target=pump, name="cb-clitools-reader", daemon=True)
    reader.start()
    timed_out = False
    deadline = started + timeout
    try:
        try:
            while True:
                try:
                    proc.wait(timeout=0.05 if stop_when is not None else max(0.0, deadline - time.monotonic()))
                    break
                except subprocess.TimeoutExpired:
                    if stop.is_set():
                        _kill_group(proc)
                        break
                    if time.monotonic() >= deadline:
                        timed_out = True
                        _kill_group(proc)
                        break
        except BaseException:
            # e.g. KeyboardInterrupt: the tool must not outlive the call (a paused port would be handed back while
            # esptool still writes)
            _kill_group(proc)
            reader.join(timeout=1)
            raise
        reader.join(timeout=5)
    finally:
        # The pipe is closed once the reader is done with it (pump closes it too, on every way out). A reader still
        # blocked in read(), because a grandchild outside the process group holds the pipe open, owns the buffer
        # lock, so close() here would block as well: that reader closes the pipe itself when it ends.
        if not reader.is_alive():
            _close_stdout()
    stopped = stop.is_set()
    return {"rc": proc.returncode, "out_tail": list(lines), "duration_s": round(time.monotonic() - started, 3),
            "timed_out": timed_out, "stopped": stopped, "stop_line": stop_line[0] if stopped else None}


def version(path: str, args: Sequence[str] = ("--version",), timeout: float = 20) -> str | None:
    """First non-empty output line of ``path --version`` (no hardware access)."""
    try:
        res = run([path, *args], timeout=timeout, hardware=False, tail=20)
    except BenchError:
        return None
    for line in res["out_tail"]:
        if line.strip():
            return line.strip()
    return None
