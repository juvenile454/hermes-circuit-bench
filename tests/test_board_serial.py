"""serialport.Broker with pty ports and providers (seq, panic blocks, pause, flock, DTR/RTS, monitor)."""
import builtins
import importlib
import importlib.util
import json
import os
import subprocess
import sys
import textwrap
import time
import types
from pathlib import Path

import board_fixtures as bf
import pytest
from board_fixtures import *  # noqa: F403

import circuit_bench
from circuit_bench.bench_core import board, contracts, serialport, storage
from conftest import HardwareAccessRefused

ROOT = Path(__file__).resolve().parent.parent

# Synthetic panic logs in the format of ESP-IDF v6.1 "Fatal Errors" (source idf-v6.1-fatal-errors); addresses invented.
XTENSA_PANIC = [
    "Guru Meditation Error: Core  1 panic'ed (StoreProhibited). Exception was unhandled.",
    "",
    "Core  1 register dump:",
    "PC      : 0x42001d6a  PS      : 0x00060030  A0      : 0x82001d8d  A1      : 0x3fcebd70",
    "A2      : 0x00000000  A3      : 0x00000001  A4      : 0x00000001  A5      : 0x3fcebd9c",
    "A14     : 0x3fceb078  A15     : 0x00000000  SAR     : 0x00000014  EXCCAUSE: 0x0000001d",
    "EXCVADDR: 0x0000000c  LBEG    : 0x400556d5  LEND    : 0x400556e5  LCOUNT  : 0xffffffff",
    "",
    "Backtrace: 0x42001d67:0x3fcebd70 0x42001d8a:0x3fcebd90 0x42003a5e:0x3fcebdb0",
    "",
    "ELF file SHA256: 3f9a5c0d21e8b47a",
    "",
    "Rebooting...",
]
RISCV_PANIC = [
    "Guru Meditation Error: Core  0 panic'ed (Store access fault). Exception was unhandled.",
    "",
    "Core  0 register dump:",
    "MEPC    : 0x420048b4  RA      : 0x420048b4  SP      : 0x3fc8f2f0  GP      : 0x3fc8a600",
    "TP      : 0x3fc8a2ac  T0      : 0x40057fa6  T1      : 0x0000000f  T2      : 0x00000000",
    "MSTATUS : 0x00001881  MTVEC   : 0x40380001  MCAUSE  : 0x00000007  MTVAL   : 0x00000000",
    "MHARTID : 0x00000000",
    "",
    "Stack memory:",
    "3fc8f2f0: 0x00000000 0x00000000 0x00000000 0x42006692 0x00000000 0x00000000 0x00000000 0x3fc8f330",
    "",
    "ELF file SHA256: 3f9a5c0d21e8b47a",
    "",
    "Rebooting...",
]
BOOT = ["ESP-ROM:esp32s3-20210327", "rst:0x1 (POWERON),boot:0x8 (SPI_FAST_FLASH_BOOT)", "entry 0x403c8854"]


def _child_env(data_dir: Path) -> dict:
    env = {k: v for k, v in os.environ.items() if not k.startswith("PYTHON")}
    env.update({"PYTHONPATH": str(ROOT), "CIRCUIT_BENCH_DATA_DIR": str(data_dir), "CIRCUIT_BENCH_HW": "on",
                "CIRCUIT_BENCH_SETTINGS_JSON": "{}", "CIRCUIT_BENCH_DEV_GUARD": "1"})
    return env


SLOW_S = 15.0  # ceiling for event waits under parallel test processes (wait_for returns as soon as it holds)


def _stays_away(monkeypatch, pty_port):
    """After the pty is closed, its /dev/pts number may be reused at once by a pty of a parallel test process, and the
    reader's reconnect would open that foreign pty. The unplugged board stays away: reopening its name fails like a
    missing device (the first open is untouched)."""
    real = serialport._open_serial
    opened: list[str] = []

    def open_serial(port, baud, reset):
        if port == pty_port.name and opened:
            raise contracts.BenchError("port_not_found", f"{port} is gone (test: the board stays unplugged)")
        opened.append(port)
        return real(port, baud, reset)

    monkeypatch.setattr(serialport, "_open_serial", open_serial)


def _collect(port):
    msgs = []
    serialport.subscribe(port, msgs.append)
    return msgs


# ------------------------------------------------------------------------------------------------ pty lines

def test_pty_lines_arrive_in_order_with_seq(hw_on, pty_port):
    msgs = _collect(pty_port.name)
    st = serialport.open_port(pty_port.name, 115200)
    assert st["state"] == "open" and st["simulated"] is False
    pty_port.write(*[f"line {i}" for i in range(1, 51)])
    assert bf.wait_for(lambda: len(serialport.tail(pty_port.name)["lines"]) == 50)
    tail = serialport.tail(pty_port.name)
    assert [m["text"] for m in tail["lines"]] == [f"line {i}" for i in range(1, 51)]
    assert [m["seq"] for m in tail["lines"]] == list(range(1, 51)) and tail["next_seq"] == 51
    assert all(m["t"] == "line" and len(m["ts"]) == 12 for m in tail["lines"])
    lines = [m for m in msgs if m["t"] == "line"]
    assert [m["seq"] for m in lines] == list(range(1, 51))
    assert msgs[0] == {"t": "state", "port": pty_port.name, "state": "open", "detail": "115200 baud"}
    # polling fallback: after=<seq> continues the same numbering
    later = serialport.tail(pty_port.name, after_seq=45)
    assert [m["seq"] for m in later["lines"]] == [46, 47, 48, 49, 50] and later["next_seq"] == 51
    assert serialport.tail(pty_port.name, after_seq=50)["lines"] == []
    assert [m["seq"] for m in serialport.tail(pty_port.name, after_seq=0, limit=3)["lines"]] == [1, 2, 3]
    # partial line without newline is flushed after a quiet second
    os.write(pty_port.master, b"no newline")
    assert bf.wait_for(lambda: serialport.tail(pty_port.name, after_seq=50)["lines"], timeout=4)
    assert serialport.tail(pty_port.name, after_seq=50)["lines"][0]["text"] == "no newline"
    assert serialport.close_port(pty_port.name)["state"] == "closed"
    assert not serialport.port_is_open(pty_port.name)
    fixture = json.loads((ROOT / "desktop-src" / "fixtures" / "serial.lines.json").read_text(encoding="utf-8"))
    # the fixture is the GET /serial/tail answer: the route adds the broker epoch, the module call does not
    assert set(fixture["result"]) - {"epoch"} <= set(tail) and set(fixture["result"]["lines"][0]) == set(tail["lines"][0])


def test_open_is_idempotent_and_unsubscribe_works(hw_on, pty_port):
    msgs = []
    unsub = serialport.subscribe(pty_port.name, msgs.append)
    serialport.open_port(pty_port.name, 115200)
    serialport.open_port(pty_port.name, 115200)
    assert [m["state"] for m in msgs if m["t"] == "state"] == ["open"]
    unsub()
    pty_port.write("after unsubscribe")
    assert bf.wait_for(lambda: serialport.tail(pty_port.name)["lines"])
    assert not [m for m in msgs if m["t"] == "line"]


def test_ring_buffer_keeps_last_5000():
    board.register_provider("sim://", bf.TestProvider(lines=[f"l{i}" for i in range(1, 5101)]))
    serialport.open_port("sim://test-s3")
    assert bf.wait_for(lambda: serialport.port_status("sim://test-s3")["next_seq"] == 5101)
    t = serialport.tail("sim://test-s3", after_seq=0, limit=5000)
    assert len(t["lines"]) == 5000 and t["lines"][0]["seq"] == 101 and t["lines"][-1]["text"] == "l5100"
    assert len(serialport.tail("sim://test-s3")["lines"]) == serialport.TAIL_LIMIT


# ------------------------------------------------------------------------------------------------ panic

@pytest.mark.parametrize(("log", "summary"), [(XTENSA_PANIC, "StoreProhibited · core 1"),
                                              (RISCV_PANIC, "Store access fault · core 0")])
def test_panic_block_is_detected(hw_on, pty_port, log, summary):
    msgs = _collect(pty_port.name)
    serialport.open_port(pty_port.name, 115200)
    pty_port.write(*BOOT, "app running", *log, *BOOT)
    assert bf.wait_for(lambda: [m for m in msgs if m["t"] == "panic"])
    (panic,) = [m for m in msgs if m["t"] == "panic"]
    first = len(BOOT) + 2
    assert panic == {"t": "panic", "seq": first, "summary": summary, "log_ref": panic["log_ref"]}
    stored = serialport.artifact_path(panic["log_ref"]).read_text(encoding="utf-8").splitlines()
    assert stored == log  # from the Guru Meditation line up to "Rebooting..."
    assert oct(serialport.artifact_path(panic["log_ref"]).stat().st_mode & 0o777) == "0o600"
    assert bf.wait_for(lambda: serialport.tail(pty_port.name)["panic"] is not None)
    assert serialport.tail(pty_port.name)["panic"] == panic
    # the panic message follows the line it points to
    idx = msgs.index(panic)
    assert [m for m in msgs[:idx] if m["t"] == "line"][-1]["text"] == "Rebooting..."


def test_panic_kinds_and_limits(monkeypatch):
    lines = (["abort() was called at PC 0x400dca43 on core 0", "", "Backtrace: 0x4008155e:0x3ffb5d30", "Rebooting..."]
             + ["Brownout detector was triggered"] + BOOT
             + ["E (1234) task_wdt: Task watchdog got triggered. The following tasks did not reset the watchdog in time:"]
             + [f"noise {i}" for i in range(100)])
    board.register_provider("sim://", bf.TestProvider(lines=lines))
    msgs = _collect("sim://test-s3")
    serialport.open_port("sim://test-s3")
    assert bf.wait_for(lambda: len([m for m in msgs if m["t"] == "panic"]) == 3)
    panics = [m for m in msgs if m["t"] == "panic"]
    assert [p["summary"] for p in panics] == ["abort() · core 0", "Brownout detector triggered", "Task watchdog triggered"]
    brownout = serialport.artifact_path(panics[1]["log_ref"]).read_text().splitlines()
    assert brownout == ["Brownout detector was triggered"]  # the next boot banner ends the block
    wdt = serialport.artifact_path(panics[2]["log_ref"]).read_text().splitlines()
    assert len(wdt) == serialport.PANIC_MAX_LINES  # no "Rebooting...": closed after 80 lines


# ------------------------------------------------------------------------------------------------ pause / locks

def test_pause_closes_and_reopens(hw_on, pty_port):
    # waits are event-driven with a generous ceiling (SLOW_S): under parallel test processes the reader thread may
    # need seconds to get CPU time; the assertions are unchanged
    msgs = _collect(pty_port.name)
    serialport.open_port(pty_port.name, 115200)
    pty_port.write("before")
    assert bf.wait_for(lambda: serialport.tail(pty_port.name)["lines"], timeout=SLOW_S)
    with serialport.pause(pty_port.name):
        assert not serialport.port_is_open(pty_port.name)
        assert serialport.port_status(pty_port.name)["state"] == "paused"
        assert serialport.pause_path(pty_port.name).exists()
        with pytest.raises(contracts.BenchError) as e:
            serialport.open_port(pty_port.name, 115200)
        assert e.value.code == "port_busy"
    assert serialport.port_is_open(pty_port.name) and not serialport.pause_path(pty_port.name).exists()
    pty_port.write("after")
    assert bf.wait_for(lambda: [m["text"] for m in serialport.tail(pty_port.name)["lines"]] == ["before", "after"],
                       timeout=SLOW_S), (serialport.tail(pty_port.name), msgs)
    assert [m["seq"] for m in serialport.tail(pty_port.name)["lines"]] == [1, 2]  # seq continues over the pause
    assert [m["state"] for m in msgs if m["t"] == "state"] == ["open", "paused", "open"]


def test_pause_of_a_closed_port_keeps_it_closed(hw_on, pty_port):
    with serialport.pause(pty_port.name):
        pass
    assert not serialport.port_is_open(pty_port.name)


def test_second_process_gets_port_busy(hw_on, pty_port):
    serialport.open_port(pty_port.name, 115200)
    code = textwrap.dedent("""
        import json, sys
        from circuit_bench.bench_core import serialport
        from circuit_bench.bench_core.contracts import BenchError
        try:
            serialport.open_port(sys.argv[1], 115200)
            print(json.dumps({"ok": True}))
            serialport.close_port(sys.argv[1])
        except BenchError as e:
            print(json.dumps({"code": e.code, "message": e.message}))
    """)
    env = _child_env(storage.data_dir())
    out = subprocess.run([sys.executable, "-c", code, pty_port.name], env=env, capture_output=True, text=True, timeout=30,
                         check=False)
    assert json.loads(out.stdout.strip().splitlines()[-1])["code"] == "port_busy", out.stderr
    serialport.close_port(pty_port.name)
    out = subprocess.run([sys.executable, "-c", code, pty_port.name], env=env, capture_output=True, text=True, timeout=30,
                         check=False)
    assert json.loads(out.stdout.strip().splitlines()[-1]) == {"ok": True}, out.stderr


def test_pause_file_makes_another_process_release_the_port(hw_on, pty_port):
    """A monitor in another process holds the port; this process flashes: the holder yields and reopens."""
    code = textwrap.dedent("""
        import json, sys, time
        from circuit_bench.bench_core import serialport
        port = sys.argv[1]
        serialport.subscribe(port, lambda m: print(json.dumps(m), flush=True))
        serialport.open_port(port, 115200)
        print("READY", flush=True)
        sys.stdin.readline()
        serialport.close_port(port)
    """)
    proc = subprocess.Popen([sys.executable, "-c", code, pty_port.name], env=_child_env(storage.data_dir()),
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        assert proc.stdout.readline().strip().startswith("{")  # state open
        assert proc.stdout.readline().strip() == "READY"
        with pytest.raises(contracts.BenchError) as e:
            serialport.open_port(pty_port.name, 115200)
        assert e.value.code == "port_busy"
        t0 = time.monotonic()
        with serialport.pause(pty_port.name):
            waited = time.monotonic() - t0
            paused = json.loads(proc.stdout.readline())
            assert paused["t"] == "state" and paused["state"] == "paused"
        reopened = json.loads(proc.stdout.readline())
        assert reopened["state"] == "open"
        pty_port.write("hello after flash")
        line = json.loads(proc.stdout.readline())
        assert line["t"] == "line" and line["text"] == "hello after flash" and line["seq"] == 1
        assert waited < serialport.PAUSE_LOCK_WAIT_S
    finally:
        proc.communicate("\n", timeout=15)
    assert proc.returncode == 0, proc.stderr


def test_pause_times_out_with_port_busy_if_holder_does_not_yield(hw_on, pty_port, monkeypatch):
    import fcntl
    fd = os.open(serialport.lock_path(pty_port.name), os.O_RDWR | os.O_CREAT, 0o600)
    fcntl.flock(fd, fcntl.LOCK_EX)
    monkeypatch.setattr(serialport, "PAUSE_LOCK_WAIT_S", 0.5)
    try:
        with pytest.raises(contracts.BenchError) as e, serialport.pause(pty_port.name):
            pytest.fail("pause must not be entered while another holder keeps the lock")
        assert e.value.code == "port_busy"
    finally:
        os.close(fd)
    assert not serialport.pause_path(pty_port.name).exists()


def test_stale_pause_file_is_ignored(hw_on, pty_port):
    path = serialport.pause_path(pty_port.name)
    path.write_text(json.dumps({"pid": 2 ** 22 + 12345, "at": time.time()}))
    assert serialport.pause_requested(pty_port.name) is False and not path.exists()
    path.write_text(json.dumps({"pid": os.getpid(), "at": time.time() - 3600}))
    assert serialport.pause_requested(pty_port.name) is False


# ------------------------------------------------------------------------------------------------ open details

class _FakeHandle:
    def __init__(self, events):
        self.events = events
        self._dtr = self._rts = None

    @property
    def dtr(self):
        return self._dtr

    @dtr.setter
    def dtr(self, v):
        self._dtr = v
        self.events.append(("dtr", v))

    @property
    def rts(self):
        return self._rts

    @rts.setter
    def rts(self, v):
        self._rts = v
        self.events.append(("rts", v))

    def open(self):
        self.events.append("open")


def _fake_serial(monkeypatch, events, kwargs):
    mod = types.ModuleType("serial")

    class SerialException(OSError):
        pass

    def serial_for_url(port, **kw):
        kwargs.update(kw, port=port)
        return _FakeHandle(events)

    mod.SerialException = SerialException
    mod.serial_for_url = serial_for_url
    monkeypatch.setitem(sys.modules, "serial", mod)
    monkeypatch.setattr(serialport.time, "sleep", lambda s: None)


def _line_states(events):
    """DTR/RTS after each step; Linux raises both when a tty opens (cdc_acm, usb-serial)."""
    dtr = rts = False
    states = []
    for ev in events:
        if ev == "open":
            dtr = rts = True
        elif ev[0] == "dtr":
            dtr = ev[1]
        else:
            rts = ev[1]
        states.append((dtr, rts))
    return states


RESET_STATE = (False, True)  # DTR off, RTS on: EN low on the auto-reset circuit and on the USB-Serial/JTAG


def test_open_never_passes_the_reset_state(monkeypatch):
    # hardware test (2026-11-06, ESP32-S3 on its native USB, firmware running): DTR/RTS off before open() restarted the board
    # on every open (pyserial sets DTR first: DTR off with RTS still on); RTS first, then DTR did not.
    events, kwargs = [], {}
    _fake_serial(monkeypatch, events, kwargs)
    serialport._open_serial("/dev/pts/cb-fake", 115200, False)
    assert events == ["open", ("rts", False), ("dtr", False)]
    assert RESET_STATE not in _line_states(events)
    assert _line_states(events)[-1] == (False, False)
    assert kwargs["do_not_open"] is True and kwargs["baudrate"] == 115200


def test_reset_true_pulses_en_after_open(monkeypatch):
    events, kwargs = [], {}
    _fake_serial(monkeypatch, events, kwargs)
    serialport._open_serial("/dev/pts/cb-fake", 115200, True)
    assert events == ["open", ("rts", False), ("dtr", False), ("dtr", False), ("rts", True), ("rts", False)]
    states = _line_states(events)
    assert states.count(RESET_STATE) == 1 and states[-1] == (False, False)  # exactly one EN pulse, IO0 high


def test_open_retries_eproto_then_reports(monkeypatch):
    import errno as _errno
    events, kwargs = [], {}
    _fake_serial(monkeypatch, events, kwargs)
    mod = sys.modules["serial"]
    calls = []

    class Flaky(_FakeHandle):
        def open(self):
            calls.append(1)
            if len(calls) < 3:
                raise mod.SerialException(_errno.EPROTO, "Protocol error")
            super().open()

    mod.serial_for_url = lambda port, **kw: Flaky(events)
    serialport._open_serial("/dev/pts/cb-fake", 115200, False)  # third attempt opens
    assert len(calls) == 3 and events == ["open", ("rts", False), ("dtr", False)]

    class Dead(_FakeHandle):
        def open(self):
            raise mod.SerialException(_errno.EPROTO, "Protocol error")

    mod.serial_for_url = lambda port, **kw: Dead(events)
    with pytest.raises(contracts.BenchError) as e:
        serialport._open_serial("/dev/pts/cb-fake", 115200, False)
    assert e.value.code == "tool_failed" and "restarting" in str(e.value)


def test_hardware_off_open_is_sim_only():
    for port in ("/dev/ttyACM0", "/dev/ttyUSB0", "COM3"):
        with pytest.raises(contracts.BenchError) as e:
            serialport.open_port(port, 115200)
        assert e.value.code == "sim_only"
    assert not serialport.lock_path("/dev/ttyACM0").exists()


def test_real_tty_is_refused_by_the_test_guard(hw_on, monkeypatch):
    """Even with the switch on, tests cannot open real serial devices (tests/conftest.py audit hook)."""
    fake_dev = "/dev/ttyCBFAKE9"  # does not exist; exists() is faked so the open() really reaches pyserial
    real_exists = os.path.exists
    monkeypatch.setattr(serialport.os.path, "exists", lambda p: True if p == fake_dev else real_exists(p))
    with pytest.raises(HardwareAccessRefused):
        serialport.open_port(fake_dev, 115200)
    assert not serialport.port_is_open(fake_dev)
    # the lock was released again
    fd = serialport._try_lock(fake_dev)
    serialport._unlock(fd)


def test_bad_arguments():
    for port in ("", "socket://10.0.0.1:2217", "rfc2217://x:1", "ttyUSB0", 5):
        with pytest.raises(contracts.BenchError) as e:
            serialport.open_port(port, 115200)
        assert e.value.code in ("invalid_args", "port_not_found"), port
    with pytest.raises(contracts.BenchError):
        serialport.open_port("sim://x", 12)


def test_missing_pyserial_is_dependency_missing(hw_on, pty_port, monkeypatch):
    real_import = builtins.__import__

    def guarded(name, *a, **kw):
        if name.split(".")[0] == "serial":
            raise ImportError("blocked for test")
        return real_import(name, *a, **kw)

    monkeypatch.delitem(sys.modules, "serial", raising=False)
    monkeypatch.setattr(builtins, "__import__", guarded)
    with pytest.raises(contracts.BenchError) as e:
        serialport.open_port(pty_port.name, 115200)
    assert e.value.code == "dependency_missing"
    with pytest.raises(contracts.BenchError) as e:
        bf.ORIGINAL_COMPORTS()
    assert e.value.code == "dependency_missing"


def test_read_error_sets_state_error(hw_on, pty_port, monkeypatch):
    monkeypatch.setattr(serialport, "RECONNECT_S", 0.5)
    msgs = _collect(pty_port.name)
    serialport.open_port(pty_port.name, 115200)
    _stays_away(monkeypatch, pty_port)
    pty_port.close()  # board unplugged
    assert bf.wait_for(lambda: serialport.port_status(pty_port.name)["state"] == "error", timeout=SLOW_S), msgs
    states = [m for m in msgs if m["t"] == "state"]
    assert states[-1]["detail"].startswith("read failed")
    assert any(m["state"] == "reconnecting" for m in states)  # it tried to reopen first (seen in the hardware test)
    fd = serialport._try_lock(pty_port.name)  # the reader released the lock
    serialport._unlock(fd)


# ------------------------------------------------------------------------------------------------ providers, copies

def test_provider_port_works_with_hardware_off():
    prov = bf.TestProvider(lines=["sim boot", "sim ready"])
    board.register_provider("sim://", prov)
    st = serialport.open_port("sim://test-s3")
    assert st["simulated"] is True
    assert bf.wait_for(lambda: len(serialport.tail("sim://test-s3")["lines"]) == 2)
    assert serialport.port_is_open("sim://test-s3")  # stays open (quiet) after the log ended
    with serialport.pause("sim://test-s3"):
        assert not serialport.port_is_open("sim://test-s3")
    assert bf.wait_for(lambda: len(serialport.tail("sim://test-s3")["lines"]) == 4)  # new line source after the pause
    assert prov.sources == 2 and serialport.tail("sim://test-s3")["simulated"] is True
    assert not serialport.lock_path("sim://test-s3").exists()


def _load_copy(name):
    pkg = Path(circuit_bench.__file__).resolve().parent / "bench_core"
    spec = importlib.util.spec_from_file_location(name, pkg / "__init__.py", submodule_search_locations=[str(pkg)])
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return importlib.import_module(f"{name}.serialport"), importlib.import_module(f"{name}.board")


def test_two_package_copies_share_one_broker():
    names = ("cb_copy_tools", "cb_copy_routes")
    board.list_ports()  # marks the (blocked) sim provider as loaded for every copy: only TestProvider below
    try:
        (sp1, b1), (sp2, b2) = (_load_copy(n) for n in names)
        assert sp1 is not sp2 and sp1.Broker is not sp2.Broker
        assert sp1.broker() is sp2.broker() is serialport.broker()
        b1.register_provider("sim://", bf.TestProvider(lines=["one", "two"]))
        assert [p["device"] for p in b2.list_ports()] == ["sim://test-s3", "sim://test-c3"]
        sp1.open_port("sim://test-s3")
        assert bf.wait_for(lambda: len(sp2.tail("sim://test-s3")["lines"]) == 2)
        # an error raised by the other copy's broker arrives as this copy's BenchError
        with sp1.pause("sim://test-s3"):
            with pytest.raises(sp2.BenchError) as e:
                sp2.open_port("sim://test-s3")
            assert e.value.code == "port_busy"
        env = sp2.monitor("/dev/ttyACM0", 1)
        assert env["error"]["code"] == "sim_only"
    finally:
        for n in list(sys.modules):
            if n.split(".")[0] in names:
                del sys.modules[n]


# ------------------------------------------------------------------------------------------------ monitor

def test_monitor_sim_port_lines_and_limits(monkeypatch):
    monkeypatch.setenv("CIRCUIT_BENCH_SETTINGS_JSON", json.dumps({"monitor_max_seconds": 1}))
    board.register_provider("sim://", bf.TestProvider(lines=[f"line {i}" for i in range(1, 301)] + XTENSA_PANIC))
    t0 = time.monotonic()
    env = serialport.monitor("sim://test-s3", 30)
    assert time.monotonic() - t0 < 5
    assert contracts.validate_envelope(env) == [] and env["ok"], env["error"]
    r = env["result"]
    assert r["seconds"] == 1 and env["assumptions"][0]["key"] == "seconds"
    assert r["line_count"] == 300 + len(XTENSA_PANIC)
    assert len(r["lines"]) <= serialport.MONITOR_MAX_LINES and r["lines"][-1] == "Rebooting..."
    assert r["truncated"] is True and r["log_ref"]
    assert r["log_ref"] == r["panics"][0]["log_ref"]  # the panic block for bench_crash decode
    assert serialport.artifact_path(r["log_ref"]).read_text().startswith("Guru Meditation Error")
    capture = next(a["value"] for a in env["assumptions"] if a["key"] == "capture_ref")
    stored = serialport.artifact_path(capture).read_text().splitlines()
    assert stored[0] == "line 1" and len(stored) == r["line_count"]
    assert r["panics"][0]["summary"] == "StoreProhibited · core 1"
    assert any(w["code"] == "panic_detected" for w in env["warnings"])
    assert env["simulated"] is True and "(simulated)" in env["summary"]
    assert len(json.dumps(env)) <= contracts.MAX_RESULT_BYTES
    assert not serialport.port_is_open("sim://test-s3")  # opened by monitor -> closed again


def test_monitor_log_ref_is_the_first_panic_without_truncation(monkeypatch):
    """A short run with a panic used to answer log_ref null; now it names the panic block."""
    monkeypatch.setenv("CIRCUIT_BENCH_SETTINGS_JSON", json.dumps({"monitor_max_seconds": 1}))
    # two different crashes: two identical blocks are one artifact with repeat 2
    board.register_provider("sim://", bf.TestProvider(lines=["boot", *XTENSA_PANIC, *RISCV_PANIC]))
    env = serialport.monitor("sim://test-s3", 1)
    r = env["result"]
    assert env["ok"] and r["truncated"] is False and len(r["panics"]) == 2
    assert r["log_ref"] == r["panics"][0]["log_ref"] and r["log_ref"] != r["panics"][1]["log_ref"]
    assert not any(a["key"] == "capture_ref" for a in env["assumptions"])
    board.register_provider("sim://", bf.TestProvider(lines=["boot", "ready"]))
    assert serialport.monitor("sim://test-s3", 1)["result"]["log_ref"] is None  # no panic, nothing cut


def test_monitor_listens_to_an_already_open_port(hw_on, pty_port):
    serialport.open_port(pty_port.name, 115200)
    pty_port.write("old line")
    assert bf.wait_for(lambda: serialport.tail(pty_port.name)["lines"])

    def later():
        time.sleep(0.3)
        pty_port.write("new line")

    import threading
    threading.Thread(target=later, daemon=True).start()
    env = serialport.monitor(pty_port.name, 1.0, reset=True)
    assert env["ok"], env["error"]
    assert env["result"]["lines"] == ["new line"] and env["result"]["truncated"] is False
    assert any(w["code"] == "reset_skipped" for w in env["warnings"])
    assert serialport.port_is_open(pty_port.name)  # still open for the other listener


def test_monitor_reports_a_port_lost_while_listening(hw_on, pty_port, monkeypatch):
    monkeypatch.setattr(serialport, "RECONNECT_S", 0.3)
    # hardware test: the board restarted, its USB device was re-enumerated, the monitor answered "0 lines" without a word
    import threading
    _stays_away(monkeypatch, pty_port)
    states = _collect(pty_port.name)

    def unplug():  # once the monitor has the port open (an event, not a fixed delay)
        if bf.wait_for(lambda: any(m.get("state") == "open" for m in states), timeout=SLOW_S):
            pty_port.close()

    threading.Thread(target=unplug, daemon=True).start()
    env = serialport.monitor(pty_port.name, 3.0)  # unplug + RECONNECT_S 0.3 + give-up fit with room under load
    assert env["ok"], env["error"]
    assert any(m.get("state") == "reconnecting" for m in states)  # it tried to reopen before giving up
    lost = [w for w in env["warnings"] if w["code"] == "port_lost"]
    assert lost and lost[0]["severity"] == "caution" and "open the monitor again" in lost[0]["message"]


def test_monitor_errors():
    assert serialport.monitor("/dev/ttyACM0", 2)["error"]["code"] == "sim_only"
    assert serialport.monitor("sim://test-s3", 0)["error"]["code"] == "invalid_args"
    assert serialport.monitor("sim://nothing", 1)["error"]["code"] == "port_not_found"


@pytest.mark.skipif(sys.platform != "linux", reason="Linux pseudo-terminals only: bf.PtyPort pairs (/dev/pts/N)")
def test_reader_reopens_a_port_that_comes_back(hw_on, monkeypatch, tmp_path):
    # hardware test: RESET on an ESP32-S3 re-enumerated /dev/ttyACM0; the open monitor lost the port and showed nothing more.
    # A symlink stands for the device name; the reader opens through it, a new pty takes its place like the new USB
    # device under the same name.
    import threading
    monkeypatch.setattr(serialport, "RECONNECT_POLL_S", 0.05)
    first, second = bf.PtyPort(), bf.PtyPort()
    dev = tmp_path / "ttyCB0"
    dev.symlink_to(first.name)
    name = str(dev)
    monkeypatch.setattr(serialport, "normalize_port", lambda port: str(port))
    monkeypatch.setattr(serialport, "_check_port", lambda port: str(port))
    msgs = _collect(name)
    try:
        serialport.open_port(name, 115200)
        first.write("before reset")
        assert bf.wait_for(lambda: any(m.get("text") == "before reset" for m in msgs))
        dev.unlink()
        first.close()
        assert bf.wait_for(lambda: serialport.port_status(name)["state"] == "reconnecting", timeout=5)

        def come_back():
            time.sleep(0.3)
            dev.symlink_to(second.name)

        threading.Thread(target=come_back, daemon=True).start()
        assert bf.wait_for(lambda: serialport.port_status(name)["state"] == "open", timeout=5)
        second.write("rst:0x15 (USB_UART_CHIP_RESET),boot:0x8 (SPI_FAST_FLASH_BOOT)", "[laser-trigger] boot ok")
        assert bf.wait_for(lambda: any(m.get("text") == "[laser-trigger] boot ok" for m in msgs))
        seqs = [m["seq"] for m in msgs if m.get("t") == "line"]
        assert seqs == sorted(seqs) and len(set(seqs)) == len(seqs)  # one stream, seq goes on
        assert any(m.get("t") == "state" and "reconnected" in (m.get("detail") or "") for m in msgs)
    finally:
        serialport.close_port(name)
        second.close()
