"""Another program holds the serial port: detect and flash refuse before esptool runs (09.11.2026: a Hermes gateway
with an open bench monitor swallowed esptool's replies, the flash died after the bootloader).

The check reads /proc/<pid>/fd links only (never opens the device); the tests point it at a fake proc tree."""
import os

import pytest
import board_fixtures as bf
from board_fixtures import *  # noqa: F403

from circuit_bench.bench_core import board, contracts, serialport


def fake_proc(tmp_path, monkeypatch, procs):
    """procs: {pid: (comm, argv, [fd link targets])}; also a non-numeric entry and a pid whose fd entry is a file."""
    root = tmp_path / "proc"
    for pid, (comm, argv, targets) in procs.items():
        fd = root / str(pid) / "fd"
        fd.mkdir(parents=True)
        for i, target in enumerate(targets):
            os.symlink(target, fd / str(i))
        (root / str(pid) / "comm").write_text(comm + "\n", encoding="utf-8")
        (root / str(pid) / "cmdline").write_bytes(b"\0".join(a.encode() for a in argv) + b"\0")
    (root / "self").mkdir(parents=True, exist_ok=True)
    os.symlink("/dev/ttyACM0", root / "self" / "0")
    (root / "77").mkdir()
    (root / "77" / "fd").write_text("not a folder", encoding="utf-8")  # unreadable fd folder: skipped
    monkeypatch.setattr(serialport, "PROC_ROOT", root)
    return root


GATEWAY = ("python3", ["/opt/hermes/venv/bin/python3", "-m", "hermes_cli.main", "gateway", "run"])


def test_port_holders_reads_fd_links_and_leaves_out_this_process(tmp_path, monkeypatch):
    me = os.getpid()
    fake_proc(tmp_path, monkeypatch, {
        me: ("pytest", ["pytest"], ["/dev/ttyACM0"]),  # this process (its own paused monitor): not a holder
        4242: (*GATEWAY, ["/dev/null", "socket:[123]", "/dev/ttyACM0"]),
        4300: ("screen", ["screen", "/dev/ttyUSB0", "115200"], ["/dev/ttyUSB0"]),  # another port
        4301: ("bash", ["bash"], ["/dev/pts/3"]),
    })
    holders = serialport.port_holders("/dev/ttyACM0")
    assert holders == [{"pid": 4242, "name": "python3", "command": "python3 -m hermes_cli.main gateway"}]
    assert serialport.port_holders("/dev/ttyUSB0") == [{"pid": 4300, "name": "screen", "command": "screen /dev/ttyUSB0 115200"}]
    assert serialport.port_holders("/dev/ttyACM1") == []


def test_port_holders_without_proc_is_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(serialport, "PROC_ROOT", tmp_path / "no-proc")
    assert serialport.port_holders("/dev/ttyACM0") == []
    serialport.check_port_free("/dev/ttyACM0")  # nothing known: no refusal


def test_check_port_free_names_pid_and_program(tmp_path, monkeypatch):
    fake_proc(tmp_path, monkeypatch, {4242: (*GATEWAY, ["/dev/ttyACM0"]), 4243: ("screen", ["screen"], ["/dev/ttyACM0"])})
    with pytest.raises(contracts.BenchError) as e:
        serialport.check_port_free("/dev/ttyACM0")
    assert e.value.code == "port_busy"
    assert "PID 4242 (python3 -m hermes_cli.main gateway)" in e.value.message
    assert "PID 4243 (screen)" in e.value.message
    assert "close" in (e.value.hint or "")


def test_detect_refuses_when_another_program_holds_the_port(fake_tools, hw_on, pty_port, monkeypatch, tmp_path):
    bf.mock_comports(monkeypatch, [(pty_port.name, 0x303A, 0x1001, "USB JTAG/serial debug unit")])
    fake_tools.scenario("board-esptool-s3.json")
    fake_proc(tmp_path, monkeypatch, {4242: (*GATEWAY, [pty_port.name])})
    env = board.detect(pty_port.name)
    assert contracts.validate_envelope(env) == [], env
    assert not env["ok"] and env["error"]["code"] == "port_busy"
    assert "PID 4242" in env["error"]["message"] and "hermes_cli.main" in env["error"]["message"]
    assert fake_tools.calls("esptool") == []  # esptool never ran
    assert not serialport.pause_path(pty_port.name).exists()


def test_detect_ignores_this_process_and_its_paused_monitor(fake_tools, hw_on, pty_port, monkeypatch, tmp_path):
    bf.mock_comports(monkeypatch, [(pty_port.name, 0x303A, 0x1001, "USB JTAG/serial debug unit")])
    fake_tools.scenario("board-esptool-s3.json")
    fake_proc(tmp_path, monkeypatch, {os.getpid(): ("pytest", ["pytest"], [pty_port.name])})
    b = serialport.broker()
    b.open(pty_port.name, 115200)
    try:
        env = board.detect(pty_port.name)
        assert env["ok"], env["error"]
        assert b.is_open(pty_port.name)  # reopened after the detection
    finally:
        b.close(pty_port.name)


@pytest.fixture
def project(tmp_path):
    d = tmp_path / "fw"
    (d / "src").mkdir(parents=True)
    (d / "platformio.ini").write_text("[env:s3]\nplatform = espressif32@6.9.0\nboard = esp32-s3-devkitc-1\n"
                                      "framework = arduino\n", encoding="utf-8")
    (d / "src" / "main.cpp").write_text("void setup() {}\nvoid loop() {}\n", encoding="utf-8")
    return d


def test_flash_refuses_when_another_program_holds_the_port(fake_tools, project, hw_on, pty_port, monkeypatch, tmp_path):
    bf.mock_comports(monkeypatch, [(pty_port.name, 0x303A, 0x1001, "USB JTAG/serial debug unit")])
    fake_tools.scenario("board-pio-flash-ok.json")
    built = board.build(project, "s3")
    assert built["ok"], built["error"]
    fake_proc(tmp_path, monkeypatch, {4242: (*GATEWAY, [pty_port.name])})
    env = board.flash(project, "s3", pty_port.name, expected_elf_sha256=built["result"]["elf_sha256"], guard=lambda: None)
    assert contracts.validate_envelope(env) == [], env
    assert not env["ok"] and env["error"]["code"] == "port_busy"
    assert "PID 4242" in env["error"]["message"]
    assert not [c for c in fake_tools.calls("esptool") if "write-flash" in c["argv"]]  # nothing written
    assert not serialport.pause_path(pty_port.name).exists()
