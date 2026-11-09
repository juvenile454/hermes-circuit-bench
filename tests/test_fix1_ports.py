"""One name per port (realpath of /dev links) for lock, pause file, broker, job key and approvals;
only serial devices count as ports."""
import hashlib

import pytest
import board_fixtures as bf
from board_fixtures import *  # noqa: F403

from circuit_bench import hooks, tools
from circuit_bench.bench_core import board, guard, serialport
from circuit_bench.bench_core.contracts import BenchError

ALIAS = "/dev/serial/by-id/usb-Espressif_USB_JTAG_serial_debug_unit_CB:FA:KE-if00"


def _map(monkeypatch, links):
    real = serialport._realpath
    monkeypatch.setattr(serialport, "_realpath", lambda p: links.get(p, real(p)))


@pytest.mark.parametrize("port", ["/dev/ttyACM0", "/dev/ttyUSB0", "/dev/ttyS-cb-fake9", "/dev/cu.usbserial-0001",
                                  "COM3", "COM12", "sim://esp32s3-n16r8", " /dev/ttyACM-cb-fake0 "])
def test_serial_devices_are_ports(port):
    assert serialport.normalize_port(port) == port.strip()


@pytest.mark.parametrize("port", ["/etc/passwd", "/dev/null", "/dev/sda", "/dev/tty", "/dev/ttyACM0/x", "ttyACM0",
                                  "/tmp/ttyACM0", "\\\\.\\COM3", "COM", "/dev/serial/by-id/../../etc/passwd",
                                  "/dev/serial/x", "--port", ""])
def test_everything_else_is_invalid(port):
    with pytest.raises(BenchError) as e:
        serialport.normalize_port(port)
    assert e.value.code == "invalid_args"


def test_aliases_resolve_to_their_device(monkeypatch):
    _map(monkeypatch, {ALIAS: "/dev/ttyACM-cb-fake0", "/dev/serial/by-path/pci-cb-usb-0:1:1.0": "/dev/ttyACM-cb-fake0",
                       "/dev/ttyCB-evil": "/etc/shadow"})
    assert serialport.normalize_port(ALIAS) == "/dev/ttyACM-cb-fake0"
    assert serialport.normalize_port("/dev/serial/by-path/pci-cb-usb-0:1:1.0") == "/dev/ttyACM-cb-fake0"
    assert serialport.lock_path(serialport.normalize_port(ALIAS)) == serialport.lock_path("/dev/ttyACM-cb-fake0")
    with pytest.raises(BenchError) as e:  # a tty name that links somewhere else is not a serial device
        serialport.normalize_port("/dev/ttyCB-evil")
    assert e.value.code == "invalid_args" and "/etc/shadow" in e.value.message
    with pytest.raises(BenchError) as e:  # unplugged: the udev link is gone
        serialport.normalize_port("/dev/serial/by-id/usb-cb-unplugged")
    assert e.value.code == "port_not_found"


def test_pseudo_terminals_only_in_development(monkeypatch):
    assert serialport.normalize_port("/dev/pts/7") == "/dev/pts/7"  # conftest sets CIRCUIT_BENCH_DEV_GUARD=1
    monkeypatch.setenv("CIRCUIT_BENCH_DEV_GUARD", "0")
    with pytest.raises(BenchError):
        serialport.normalize_port("/dev/pts/7")


def test_alias_shares_the_broker_entry_and_pause(hw_on, pty_port, monkeypatch):
    """The UI holds the device open; an agent monitor or a flash on the by-id alias sees the same port."""
    _map(monkeypatch, {ALIAS: pty_port.name})
    st = serialport.open_port(pty_port.name, 115200)
    assert st["state"] == "open"
    assert serialport.port_is_open(ALIAS) and serialport.port_status(ALIAS)["port"] == pty_port.name
    with serialport.pause(ALIAS):  # pausing the alias stops the reader of the device
        assert serialport.port_status(pty_port.name)["state"] == "paused"
    assert bf.wait_for(lambda: serialport.port_status(pty_port.name)["state"] == "open")
    serialport.close_port(ALIAS)
    assert not serialport.port_is_open(pty_port.name)


def test_detect_and_flash_use_the_device_name(fake_tools, hw_on, monkeypatch):
    bf.mock_comports(monkeypatch, [])
    _map(monkeypatch, {ALIAS: "/dev/pts/cb-missing"})
    env = board.detect(ALIAS)
    assert env["error"]["code"] == "port_not_found" and "/dev/pts/cb-missing" in env["error"]["message"]
    assert board.detect("/etc/passwd")["error"]["code"] == "invalid_args"
    assert fake_tools.calls() == []


def test_guard_and_hook_treat_an_alias_like_its_device(monkeypatch):
    _map(monkeypatch, {ALIAS: "/dev/ttyACM-cb-fake0"})
    monkeypatch.setenv("CIRCUIT_BENCH_HW", "on")
    monkeypatch.setenv("CIRCUIT_BENCH_SETTINGS_JSON", '{"approve_serial": true}')
    host = tools.Host(hook_active=True)
    a = hooks.decide(host, "bench_board", {"action": "monitor", "port": ALIAS}) or {}
    b = hooks.decide(host, "bench_board", {"action": "monitor", "port": "/dev/ttyACM-cb-fake0"}) or {}
    assert a["rule_key"] == b["rule_key"] == "circuit-bench:monitor:" + hashlib.sha256(b"/dev/ttyACM-cb-fake0").hexdigest()
    d = hooks.decide(host, "bench_board", {"action": "detect", "port": "/etc/passwd"}) or {}
    assert d["action"] == "block" and "invalid_args" in d["message"]
    refusal = guard.check_serial(via="route", settings=None, port="/etc/passwd", cron=False) or {}
    assert refusal["error"]["code"] == "invalid_args"


def test_tool_refuses_non_serial_paths():
    env = tools.run_tool("bench_board", {"action": "monitor", "port": "/etc/passwd", "seconds": 1},
                         tools.Host(hook_active=True))
    assert env["ok"] is False and env["error"]["code"] == "invalid_args"


# ------------------------------------------------------------------------------------------------ routes
from test_api_support import api  # noqa: E402,F401 - fixture
import test_api_support as sup  # noqa: E402


def test_route_job_key_uses_the_device_name(api, monkeypatch):  # noqa: F811
    """Detect on the by-id alias and on the device are the same job key (port:<device>): the second is busy."""
    import threading
    route_sp, route_board = sup.route_module("serialport"), sup.route_module("board")
    _map(monkeypatch, {ALIAS: "/dev/ttyACM-cb-fake0"})
    real = route_sp._realpath
    monkeypatch.setattr(route_sp, "_realpath", lambda p: "/dev/ttyACM-cb-fake0" if p == ALIAS else real(p))
    monkeypatch.setenv("CIRCUIT_BENCH_HW", "on")
    release, seen = threading.Event(), []

    def slow_detect(port, **kw):
        seen.append(port)
        release.wait(5)
        return sup.route_module("contracts").fail("board.detect", "port_not_found", "stub")

    monkeypatch.setattr(route_board, "detect", slow_detect)
    first = api.post("/board/detect", {"port": ALIAS})
    assert first.status_code == 202, first.json()
    api.err(api.post("/board/detect", {"port": "/dev/ttyACM-cb-fake0"}), 423, "port_busy")
    release.set()
    api.wait_job(first.json()["result"]["job_id"])
    assert seen == ["/dev/ttyACM-cb-fake0"]
    api.err(api.post("/board/detect", {"port": "/etc/passwd"}), 400, "invalid_args")
    api.err(api.post("/serial/open", {"port": "/etc/passwd"}), 400, "invalid_args")
