"""Detect runs esptool inside serialport.pause (the port's flock), for the agent and the
route; the route no longer pauses itself (a nested pause would wait for its own lock). pty ports and fakes only."""
import json
import subprocess
import sys
import textwrap
import time

import board_fixtures as bf
import pytest
import test_api_support as sup
from board_fixtures import fake_tools, hw_on, pty_port  # noqa: F401 - fixtures
from test_api_support import api  # noqa: F401 - fixture

from circuit_bench import tools
from circuit_bench.bench_core import board, serialport

HOLDER = textwrap.dedent("""
    import fcntl, os, sys
    fd = os.open(sys.argv[1], os.O_RDWR | os.O_CREAT, 0o600)
    fcntl.flock(fd, fcntl.LOCK_EX)
    print("READY", flush=True)
    sys.stdin.readline()
""")


class Holder:
    """Another process that keeps the port's flock (like a monitor in a second Circuit Bench process that does not
    yield)."""

    def __init__(self, lock_file):
        self.proc = subprocess.Popen([sys.executable, "-c", HOLDER, str(lock_file)], stdin=subprocess.PIPE,
                                     stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        assert self.proc.stdout.readline().strip() == "READY", self.proc.stderr.read()

    def release(self):
        if self.proc.poll() is None:
            self.proc.communicate("\n", timeout=15)


@pytest.fixture
def holder():
    made = []

    def make(lock_file):
        h = Holder(lock_file)
        made.append(h)
        return h

    yield make
    for h in made:
        h.release()


def _lock_is_free(sp, port):
    try:
        fd = sp._try_lock(port)
    except Exception:  # noqa: BLE001 - port_busy of either package copy
        return False
    sp._unlock(fd)
    return True


# ------------------------------------------------------------------------------------------------ board / agent

def test_detect_holds_the_port_lock_while_esptool_runs(fake_tools, hw_on, pty_port, monkeypatch):  # noqa: F811
    bf.mock_comports(monkeypatch, [(pty_port.name, 0x303A, 0x1001, "USB JTAG/serial debug unit", "TEST0001")])
    fake_tools.scenario("board-esptool-s3.json")
    seen = {}
    real_run = board.clitools.run

    def spy(argv, **kw):
        if "flash-id" in argv:
            seen["lock_free"] = _lock_is_free(serialport, pty_port.name)
            seen["pause_file"] = serialport.pause_path(pty_port.name).exists()
        return real_run(argv, **kw)

    monkeypatch.setattr(board.clitools, "run", spy)
    env = board.detect(pty_port.name)
    assert env["ok"], env["error"]
    assert seen == {"lock_free": False, "pause_file": True}
    assert _lock_is_free(serialport, pty_port.name) and not serialport.pause_path(pty_port.name).exists()


def test_agent_detect_ends_with_port_busy_while_another_process_holds_the_lock(fake_tools, hw_on, pty_port,  # noqa: F811
                                                                               monkeypatch, holder):
    bf.mock_comports(monkeypatch, [(pty_port.name, 0x303A, 0x1001, "USB JTAG/serial debug unit")])
    fake_tools.scenario("board-esptool-s3.json")
    h = holder(serialport.lock_path(pty_port.name))
    t0 = time.monotonic()
    env = json.loads(tools.make_handlers(tools.Host(hook_active=True))["bench_board"](
        {"action": "detect", "port": pty_port.name}))
    took = time.monotonic() - t0
    assert env["ok"] is False and env["error"]["code"] == "port_busy", env
    assert env["action"] == "board.detect"
    assert took <= 6.0 + 1.0, took  # PAUSE_LOCK_WAIT_S (5 s) plus start-up
    assert fake_tools.calls("esptool") == []  # esptool never started
    h.release()
    env = board.detect(pty_port.name)  # the holder is gone: detect works again
    assert env["ok"], env["error"]


# ------------------------------------------------------------------------------------------------ route

def _route_ports(monkeypatch, pty_port):  # noqa: F811
    return sup.mock_ports(monkeypatch, [(pty_port.name, 0x303A, 0x1001, "USB JTAG/serial debug unit", "TEST0001")])


def test_route_detect_with_an_open_broker_is_quick_and_reopens(api, fake_tools, pty_port, monkeypatch):  # noqa: F811
    monkeypatch.setenv("CIRCUIT_BENCH_HW", "on")
    _route_ports(monkeypatch, pty_port)
    fake_tools.scenario("board-esptool-s3.json")
    sp = sup.route_module("serialport")
    assert sp.open_port(pty_port.name, 115200)["state"] == "open"
    t0 = time.monotonic()
    resp = api.post("/board/detect", {"port": pty_port.name})
    assert resp.status_code == 202, resp.json()
    job = api.wait_job(resp.json()["result"]["job_id"])
    took = time.monotonic() - t0
    assert job["result"]["state"] == "done", job
    assert job["result"]["result"]["result"]["usb_id"] == {"vid": "303a", "pid": "1001", "serial": "TEST0001"}
    assert took < 2.0, took
    assert bf.wait_for(lambda: sp.port_status(pty_port.name)["state"] == "open", timeout=10)
    assert sp.port_is_open(pty_port.name)


def test_route_detect_ends_with_port_busy_while_another_process_holds_the_lock(api, fake_tools, pty_port,  # noqa: F811
                                                                               monkeypatch, holder):
    monkeypatch.setenv("CIRCUIT_BENCH_HW", "on")
    _route_ports(monkeypatch, pty_port)
    fake_tools.scenario("board-esptool-s3.json")
    sp = sup.route_module("serialport")
    holder(sp.lock_path(pty_port.name))
    t0 = time.monotonic()
    resp = api.post("/board/detect", {"port": pty_port.name})
    assert resp.status_code == 202, resp.json()
    job = api.wait_job(resp.json()["result"]["job_id"], timeout=15)
    took = time.monotonic() - t0
    assert job["result"]["state"] == "failed"
    assert job["result"]["result"]["error"]["code"] == "port_busy"
    assert took <= 6.0, took
    assert fake_tools.calls("esptool") == []
