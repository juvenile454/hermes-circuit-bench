"""Shared fixtures of the board tests: fake CLIs, pty ports, mocked port lists, a test provider.

Test modules use ``from board_fixtures import *`` (fixtures, listed in __all__) and ``import board_fixtures as bf``
(helpers). Nothing here touches a real serial device:
ports are pty pairs (/dev/pts/N), port lists are mocked, esptool/pio are the fakes in tests/fakes/bin.
"""
from __future__ import annotations

import json
import os
import sys
import time
import types
from pathlib import Path

import pytest

from circuit_bench.bench_core import board as _board

ORIGINAL_COMPORTS = _board._comports  # the real pyserial lookup (tests call it only with pyserial blocked)
TESTS = Path(__file__).resolve().parent
FAKES_BIN = TESTS / "fakes" / "bin"
SCENARIOS = TESTS / "fakes" / "scenarios"
SHA_A = "a" * 64
__all__ = ["_board_isolation", "fake_tools", "hw_on", "pty_port"]


class FakeTools:
    """A temporary bin folder (first on PATH) with links to the fake esptool/pio, its scenario and argv log."""

    def __init__(self, bin_dir: Path):
        self.bin = bin_dir
        self.log = bin_dir / "cb-fake-argv.log"

    def scenario(self, name: str | dict, **steps: dict) -> dict:
        data = json.loads((SCENARIOS / name).read_text(encoding="utf-8")) if isinstance(name, str) else dict(name)
        for key, value in steps.items():
            data[key] = {**data.get(key, {}), **value}
        (self.bin / "cb-fake-scenario.json").write_text(json.dumps(data), encoding="utf-8")
        return data

    def calls(self, tool: str | None = None) -> list[dict]:
        if not self.log.is_file():
            return []
        out = [json.loads(line) for line in self.log.read_text(encoding="utf-8").splitlines() if line.strip()]
        return [c for c in out if tool is None or c["tool"] == tool]


@pytest.fixture
def fake_tools(tmp_path, monkeypatch) -> FakeTools:
    b = tmp_path / "fakebin"
    b.mkdir()
    for name in ("esptool", "pio"):
        (b / name).symlink_to(FAKES_BIN / name)
    monkeypatch.setenv("PATH", f"{b}{os.pathsep}{os.environ['PATH']}")
    return FakeTools(b)


@pytest.fixture
def hw_on(monkeypatch):
    """Hardware switch on (only together with fakes and pty ports)."""
    monkeypatch.setenv("CIRCUIT_BENCH_HW", "on")


class PtyPort:
    def __init__(self):
        self.master, self.slave = os.openpty()
        self.name = os.ttyname(self.slave)

    def write(self, *lines: str, end: str = "\r\n") -> None:
        os.write(self.master, "".join(line + end for line in lines).encode("utf-8"))

    def close(self) -> None:
        for fd in (self.master, self.slave):
            try:
                os.close(fd)
            except OSError:
                pass


@pytest.fixture
def pty_port():
    p = PtyPort()
    assert p.name.startswith("/dev/pts/")
    yield p
    p.close()


def mock_comports(monkeypatch, entries: list[tuple]) -> list:
    """Replace board._comports by a fixed list of (device, vid, pid, description[, serial_number]); returns the call
    log. The serial number (USB iSerial, synthetic like ``TEST0001``) is optional, None without it."""
    from circuit_bench.bench_core import board
    calls: list = []

    def fake():
        calls.append(1)
        return [types.SimpleNamespace(device=d, vid=v, pid=p, description=desc, product=None,
                                      serial_number=(rest[0] if rest else None),
                                      hwid=(f"USB VID:PID={v:04X}:{p:04X}" if v is not None else "n/a"))
                for d, v, p, desc, *rest in entries]

    monkeypatch.setattr(board, "_comports", fake)
    return calls


class TestProvider:
    """Provider protocol of board.register_provider, as the sim provider implements it for sim://."""

    __test__ = False

    def __init__(self, lines=("boot", "ready"), delay=0.0, sha=SHA_A):
        self.lines = list(lines)
        self.delay = delay
        self.sha = sha
        self.flashed: list[tuple] = []
        self.sources = 0

    def ports(self):
        return [{"device": "sim://test-s3", "description": "Simulated test board"}, "sim://test-c3"]

    def detect(self, port):
        return {"port": port, "mac": "aa:bb:cc:dd:ee:ff", "chip": "ESP32-S3 (QFN56) (revision v0.2)",
                "description": "Simulated test board", "features": ["Wi-Fi"], "flash_size": "16MB",
                "variant_suggestion": "n16r8"}

    def build(self, project_dir, env):
        return {"ram_pct": 5.6, "flash_pct": 7.9, "elf_sha256": self.sha, "elf": "firmware.elf"}

    def flash(self, project_dir, env, port):
        self.flashed.append((project_dir, env, port))
        return {"mac": "aa:bb:cc:dd:ee:ff", "elf_sha256": self.sha, "duration_s": 0.1}

    def line_source(self, port):
        self.sources += 1
        for line in self.lines:
            if self.delay:
                time.sleep(self.delay)
            yield line

    def elf_sha256(self, project_dir, env):
        return self.sha


def use_sim_module(monkeypatch, register) -> None:
    """Install a fake ``bench_core.sim`` whose register() is ``register``."""
    mod = types.ModuleType("circuit_bench.bench_core.sim")
    mod.register = register
    monkeypatch.setitem(sys.modules, "circuit_bench.bench_core.sim", mod)


def wait_for(predicate, timeout=5.0, step=0.02):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(step)
    return predicate()


@pytest.fixture(autouse=True)
def _board_isolation(monkeypatch):
    """- pyserial's real port list is never consulted (mock_comports replaces it);
    - the real sim provider stays out: these tests drive the provider interface with TestProvider
      (``import bench_core.sim`` raises ImportError, see use_sim_module() to install a fake one);
    - the broker is closed after each test."""
    import circuit_bench.bench_core as core
    from circuit_bench.bench_core import board

    def unmocked():
        raise AssertionError("test called the real serial port list; use mock_comports()")

    monkeypatch.setattr(board, "_comports", unmocked)
    monkeypatch.delattr(core, "sim", raising=False)
    monkeypatch.setitem(sys.modules, "circuit_bench.bench_core.sim", None)
    yield
    from circuit_bench.bench_core import runtime
    b = runtime.peek("broker")
    if b is not None:
        b.shutdown()
