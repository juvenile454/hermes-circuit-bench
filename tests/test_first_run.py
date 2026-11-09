"""First-run wording of the doctor and the simulated monitor.

Without PlatformIO the doctor says "not found" (the check status stays ``failed``) and that the simulation needs none
of the tools; a monitor on a simulated board stops shortly after its first panic, real ports listen the full time.
"""
import sys
import threading
import time
import types

import board_fixtures as bf
import pytest
from board_fixtures import _board_isolation, hw_on, pty_port  # noqa: F401 - fixtures
from test_board_serial import XTENSA_PANIC

from circuit_bench import commands
from circuit_bench.bench_core import board, contracts, doctor, serialport

TOOL_IDS = ("doctor.pio", "doctor.esptool", "doctor.addr2line")
NOTE_END = "work without these tools; real boards need them."
PORT = "sim://test-s3"


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    cfg = types.ModuleType("hermes_cli.config")
    cfg.load_config = dict
    pkg = types.ModuleType("hermes_cli")
    pkg.config = cfg
    monkeypatch.setitem(sys.modules, "hermes_cli", pkg)
    monkeypatch.setitem(sys.modules, "hermes_cli.config", cfg)
    monkeypatch.delenv("HERMES_YOLO_MODE", raising=False)
    monkeypatch.setattr(doctor, "_groups", lambda: {"group": "dialout", "member": True})  # independent of this machine


@pytest.fixture
def no_tools(monkeypatch, tmp_path):
    empty = tmp_path / "empty-bin"
    empty.mkdir()
    monkeypatch.setenv("PATH", str(empty))
    monkeypatch.setenv("PLATFORMIO_CORE_DIR", str(tmp_path / "no-pio"))


@pytest.fixture
def all_tools(monkeypatch, tmp_path):
    bin_dir = tmp_path / "all-bin"
    bin_dir.mkdir()
    for name in ("pio", "esptool"):
        (bin_dir / name).symlink_to(bf.FAKES_BIN / name)
    (bin_dir / "xtensa-esp32s3-elf-addr2line").symlink_to(bf.FAKES_BIN / "xtensa-esp32s3-elf-addr2line")
    monkeypatch.setenv("PATH", str(bin_dir))
    monkeypatch.setenv("PLATFORMIO_CORE_DIR", str(tmp_path / "no-pio"))


@pytest.fixture
def missing_dependency(monkeypatch):
    monkeypatch.setattr(doctor, "DEPENDENCIES", (("no_such_module_for_the_doctor", "no-such-dist"),))


def test_doctor_without_tools_says_the_simulation_works(no_tools):
    env = doctor.run()
    assert "(not found: pio, esptool, addr2line)" in env["summary"]
    assert env["summary"].endswith(NOTE_END)
    assert [c["status"] for c in env["checks"] if c["id"] in TOOL_IDS] == ["failed"] * 3  # status stays
    text = commands.doctor_text()
    assert "[miss] pio:" in text and "[miss] esptool:" in text and "[miss] addr2line:" in text
    assert "[FAIL]" not in text


def test_doctor_with_a_real_failure_keeps_fail(no_tools, missing_dependency):
    assert "(not found: pio, esptool, addr2line; failed: dependencies)" in doctor.run()["summary"]
    assert "[FAIL] dependencies:" in commands.doctor_text()


def test_doctor_failure_without_missing_tools_has_no_note(all_tools, missing_dependency):
    s = doctor.run()["summary"]
    assert "(failed: dependencies)" in s and "not found" not in s and "tools" not in s


def test_doctor_with_all_tools_is_unchanged(all_tools):
    s = doctor.run()["summary"]  # the port count depends on the environment
    assert s.startswith("Doctor: 7/7 checks passed; ") and s.endswith("hardware off.") and "tools" not in s


@pytest.fixture
def panic_provider(monkeypatch):
    board.register_provider("sim://", bf.TestProvider(lines=["boot", *XTENSA_PANIC, "after the panic"]))


@pytest.fixture
def quiet_provider(monkeypatch):
    board.register_provider("sim://", bf.TestProvider(lines=["boot", "ready"]))


def test_sim_monitor_returns_soon_after_the_first_panic(panic_provider):
    t0 = time.monotonic()
    env = serialport.monitor(PORT, 30)
    assert time.monotonic() - t0 < 5
    assert contracts.validate_envelope(env) == [] and env["ok"], env.get("error")
    assert env["result"]["panics"] and env["result"]["seconds"] < 5
    stopped = [a for a in env["assumptions"] if a["key"] == "stopped_early"]
    assert [a["reason"] for a in stopped] == ["simulated board: stopped 1 s after the first panic"]
    assert f"in {env['result']['seconds']:g} s" in env["summary"]


def test_sim_monitor_without_panic_waits_the_full_time(quiet_provider):
    t0 = time.monotonic()
    env = serialport.monitor(PORT, 1.5)
    assert time.monotonic() - t0 >= 1.5
    assert env["result"]["seconds"] == 1.5 and not env["result"]["panics"]
    assert not any(a["key"] == "stopped_early" for a in env["assumptions"])


def test_real_port_waits_the_full_time_after_a_panic(hw_on, pty_port):  # noqa: F811
    timer = threading.Timer(0.3, lambda: pty_port.write(*XTENSA_PANIC))
    timer.start()
    try:
        t0 = time.monotonic()
        env = serialport.monitor(pty_port.name, 2.5)
        assert time.monotonic() - t0 >= 2.5
    finally:
        timer.cancel()
    assert env["ok"] and env["result"]["panics"] and env["result"]["seconds"] == 2.5
    assert not any(a["key"] == "stopped_early" for a in env["assumptions"])
