"""Test isolation for every test.

- HOME, HERMES_HOME, CIRCUIT_BENCH_DATA_DIR point into tmp_path; settings come from CIRCUIT_BENCH_SETTINGS_JSON;
- CIRCUIT_BENCH_HW=off and CIRCUIT_BENCH_DEV_GUARD=1;
- PATH starts with tests/fakes/bin, ESPTOOL_* variables are removed;
- a fake plugins.plugin_storage maps plugin_data_dir() into tmp_path;
- an audit hook refuses real serial devices and real esptool/pio/addr2line processes for the whole session, and
  `pio run` without explicit -t targets even for the fakes (PlatformIO would run the `targets` of platformio.ini).
  CB_TOOLCHAIN_TESTS=1 additionally allows real `pio run` with build-only targets (buildprog, checkprogsize,
  __idedata, size), `pio project metadata|config` and real addr2line (offline builds).
"""
from __future__ import annotations

import os
import re
import shutil
import sys
import tempfile
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
FAKES_BIN = (ROOT / "tests" / "fakes" / "bin").resolve()
# Linux ttyUSB*/ttyACM*/ttyS*, udev /dev/serial/, macOS cu.* and tty.* (tty.usbserial-*, tty.usbmodem*). Pseudo-terminals
# (/dev/pts/N on Linux, /dev/ttysNNN on macOS) stay allowed.
_SERIAL_DEV = re.compile(r"^/dev/(tty[A-Z]|tty\.|cu\.|serial/)")
_TOOL_NAMES = ("esptool", "esptool.py", "pio", "platformio")
# `pio run` targets the toolchain tests may run for real (builds only; kept separate from clitools on purpose)
_TOOLCHAIN_TARGETS = frozenset({"buildprog", "checkprogsize", "size", "sizedata", "__idedata"})


class HardwareAccessRefused(RuntimeError):
    pass


def _pio_run_targets(argv_list: list[str]) -> list[str] | None:
    """The explicit -t/--target values of `pio run ...` (None: not a `pio run`)."""
    if argv_list[1:2] != ["run"]:
        return None
    out = []
    for i, a in enumerate(argv_list):
        if a in ("-t", "--target") and i + 1 < len(argv_list):
            out.append(argv_list[i + 1])
        elif a.startswith("--target="):
            out.append(a.split("=", 1)[1])
        elif a.startswith("-t") and len(a) > 2 and not a.startswith("--"):
            out.append(a[2:])
    return out


def _tool_name(path: str) -> str | None:
    base = os.path.basename(path)
    if base in _TOOL_NAMES or base.endswith("-addr2line"):
        return base
    return None


def _audit(event: str, args: tuple) -> None:
    if event == "open":
        path = args[0]
        if isinstance(path, bytes):
            path = path.decode(errors="replace")
        if isinstance(path, str) and _SERIAL_DEV.match(path):
            raise HardwareAccessRefused(f"tests must not open serial devices: {path}")
    elif event == "subprocess.Popen":
        executable, argv = args[0], args[1]
        argv_list = [str(a) for a in (argv if isinstance(argv, list | tuple) else [argv])]
        first = str(executable) if executable else (argv_list[0] if argv_list else "")
        name = _tool_name(first)
        if name is None and any(a in ("esptool", "esptool.py") for a in argv_list[1:3]):
            name = "esptool"
        if name is None:
            return
        targets = _pio_run_targets(argv_list) if name in ("pio", "platformio") else None
        if targets is not None and not targets:  # even the fakes: without -t pio runs the ini's `targets` (upload)
            raise HardwareAccessRefused(f"`pio run` without -t runs the targets of platformio.ini: "
                                        f"{' '.join(argv_list)[:200]}")
        try:
            if Path(first).resolve().is_relative_to(FAKES_BIN):
                return
        except OSError:
            pass
        if os.environ.get("CB_TOOLCHAIN_TESTS") == "1":
            joined = " ".join(argv_list)
            if name.endswith("-addr2line"):
                return
            if name == "esptool" and argv_list[1:2] == ["image-info"] and "--port" not in joined and len(argv_list) == 3:
                return  # reads an image file, opens no port (board.image_info)
            if name in ("pio", "platformio") and "upload" not in joined and "monitor" not in joined \
                    and "erase" not in joined:
                if targets and set(targets) <= _TOOLCHAIN_TARGETS:
                    return
                if argv_list[1:3] in (["project", "metadata"], ["project", "config"]) or argv_list[1:2] == ["--version"]:
                    return
        raise HardwareAccessRefused(f"tests must not run real {name}: {' '.join(argv_list)[:200]}")


if not getattr(sys, "_circuit_bench_audit", False):
    sys.addaudithook(_audit)
    sys._circuit_bench_audit = True


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    home = tmp_path / "home"
    hermes_home = tmp_path / "hhome"
    data = tmp_path / "data"
    for d in (home, hermes_home, data):
        d.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("HERMES_HOME", str(hermes_home))
    monkeypatch.setenv("CIRCUIT_BENCH_DATA_DIR", str(data))
    monkeypatch.setenv("CIRCUIT_BENCH_SETTINGS_JSON", "{}")
    monkeypatch.setenv("CIRCUIT_BENCH_HW", "off")
    monkeypatch.setenv("CIRCUIT_BENCH_DEV_GUARD", "1")
    monkeypatch.setenv("PATH", f"{FAKES_BIN}{os.pathsep}{os.environ.get('PATH', '')}")
    for key in list(os.environ):
        if key.startswith("ESPTOOL_"):
            monkeypatch.delenv(key, raising=False)

    storage = types.ModuleType("plugins.plugin_storage")

    def plugin_data_dir(name: str) -> Path:
        p = hermes_home / "plugin-data" / name
        p.mkdir(parents=True, exist_ok=True)
        return p

    storage.plugin_data_dir = plugin_data_dir
    pkg = types.ModuleType("plugins")
    pkg.plugin_storage = storage
    monkeypatch.setitem(sys.modules, "plugins", pkg)
    monkeypatch.setitem(sys.modules, "plugins.plugin_storage", storage)

    from circuit_bench.bench_core import runtime
    runtime.reset()
    yield
    runtime.reset()


# Approval texts show a folder of at most 120 characters whole and shorten longer ones (" (path shortened)"). Tests that
# check the exact text of a short folder must not depend on how long the system temp path is (macOS: /private/var/folders/...,
# CI runners and TMPDIR settings can be longer still). The longest sub-folder name below such a path is "my fw<U+2003>x",
# shown as 14 characters (the separator, "my fw", a six-character escape, "x"); 90 + 14 = 104 leaves 16 characters to spare
# under the 120 limit.
SHORT_TMP_MAX = 90


@pytest.fixture
def short_tmp(tmp_path):
    """A folder whose resolved path is at most SHORT_TMP_MAX characters long: ``tmp_path`` itself when it is short
    enough, else a fresh folder under the resolved ``/tmp`` that is removed after the test. Isolation (HOME,
    HERMES_HOME, data folder) stays in ``tmp_path``; only project folders for approval texts go here."""
    resolved = tmp_path.resolve()
    if len(str(resolved)) <= SHORT_TMP_MAX:
        yield resolved
        return
    base = Path("/tmp").resolve()
    folder = Path(tempfile.mkdtemp(prefix="cb-short-", dir=base)).resolve()
    try:
        assert len(str(folder)) <= SHORT_TMP_MAX, folder
        yield folder
    finally:
        shutil.rmtree(folder, ignore_errors=True)


# Linux-only: the shared pty_port fixture (tests/board_fixtures.py) expects /dev/pts/N pseudo-terminals; macOS names
# them /dev/ttysNNN. Every test using it is skipped elsewhere, listed by `pytest -rs` with this reason.
PTY_LINUX_ONLY = "Linux pseudo-terminals only: the pty_port fixture expects /dev/pts/N (macOS uses /dev/ttysNNN)"


def pytest_collection_modifyitems(config, items):
    if sys.platform == "linux":
        return
    skip = pytest.mark.skip(reason=PTY_LINUX_ONLY)
    for item in items:
        if "pty_port" in getattr(item, "fixturenames", ()):
            item.add_marker(skip)
