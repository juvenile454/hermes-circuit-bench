"""Port watcher (bench_core/portwatch.py): one board.changed per change, only while a client is active."""
import threading
import time

from circuit_bench.bench_core import portwatch, runtime


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


class Ports:
    def __init__(self, *devices):
        self.devices = list(devices)
        self.lock = threading.Lock()

    def set(self, *devices):
        with self.lock:
            self.devices = list(devices)

    def __call__(self):
        with self.lock:
            return [{"device": d, "simulated": d.startswith("sim://")} for d in self.devices]


def make(ports, states=None, **kw):
    sent = []
    w = portwatch.PortWatcher(lister=ports, emit=lambda e, p: sent.append((e, p)),
                              state_of=lambda d: (states or {}).get(d), **kw)
    return w, sent


def test_exactly_one_event_per_change():
    ports = Ports("sim://esp32s3-n16r8")
    states = {}
    w, sent = make(ports, states)
    assert w.poll_once() == [] and sent == []  # first poll: baseline only
    assert w.poll_once() == []
    ports.set("sim://esp32s3-n16r8", "/dev/ttyACM9")
    assert w.poll_once() == [{"port": "/dev/ttyACM9", "state": "linked", "simulated": False}]
    assert w.poll_once() == [] and w.poll_once() == []
    states["/dev/ttyACM9"] = "paused"  # broker paused it for a flash
    assert w.poll_once() == [{"port": "/dev/ttyACM9", "state": "busy", "simulated": False}]
    assert w.poll_once() == []
    states["/dev/ttyACM9"] = "open"
    assert w.poll_once() == [{"port": "/dev/ttyACM9", "state": "linked", "simulated": False}]
    ports.set("sim://esp32s3-n16r8")
    assert w.poll_once() == [{"port": "/dev/ttyACM9", "state": "lost", "simulated": False}]
    ports.set()
    ports_after = w.poll_once()
    assert ports_after == [{"port": "sim://esp32s3-n16r8", "state": "lost", "simulated": True}]
    assert [e for e, _ in sent] == ["board.changed"] * 5
    assert [p for _, p in sent][-1] == ports_after[0]


def test_two_changes_in_one_poll_are_two_events():
    ports = Ports("/dev/ttyUSB0")
    w, sent = make(ports)
    w.poll_once()
    ports.set("/dev/ttyUSB1")
    assert sorted((c["port"], c["state"]) for c in w.poll_once()) == [("/dev/ttyUSB0", "lost"), ("/dev/ttyUSB1", "linked")]
    assert len(sent) == 2


def test_failing_lister_keeps_the_snapshot():
    ports = Ports("/dev/ttyUSB0")
    w, sent = make(ports)
    w.poll_once()

    def broken():
        raise OSError("usb gone")

    w._lister = broken
    assert w.poll_once() == []
    w._lister = ports
    assert w.poll_once() == [] and sent == []


def test_active_window_and_websocket_clients():
    clock = Clock()
    w, _ = make(Ports(), clock=clock, interval=3600)
    assert not w.active()
    w.touch()
    assert w.active()
    clock.t += 9.9
    assert w.active()
    clock.t += 0.2
    assert not w.active()
    disconnect = w.connect()
    clock.t += 1000
    assert w.active()  # a socket keeps it active however long
    disconnect()
    disconnect()  # idempotent
    assert w.active()  # the window starts again at the disconnect
    clock.t += 10.1
    assert not w.active()
    w.stop()


def test_thread_polls_while_active_and_ends_by_itself():
    ports = Ports("sim://a")
    clock = Clock()
    w, sent = make(ports, clock=clock, interval=0.01)
    w.touch()
    deadline = time.monotonic() + 5
    while w.polls < 3 and time.monotonic() < deadline:
        time.sleep(0.01)
    assert w.running and w.polls >= 3
    ports.set("sim://a", "sim://b")
    deadline = time.monotonic() + 5
    while not sent and time.monotonic() < deadline:
        time.sleep(0.01)
    assert sent == [("board.changed", {"port": "sim://b", "state": "linked", "simulated": True})]
    clock.t += 60  # no client any more
    deadline = time.monotonic() + 5
    while w.running and time.monotonic() < deadline:
        time.sleep(0.01)
    assert not w.running
    n = w.polls
    time.sleep(0.05)
    assert w.polls == n
    w.touch()  # a new request starts it again
    assert w.running
    w.stop()
    assert not w.running


def test_default_state_reads_the_broker_through_module_functions():
    from circuit_bench.bench_core import serialport

    assert portwatch._default_state_of("sim://nothing") == "closed"
    assert serialport.port_status("sim://nothing")["state"] == "closed"
    assert portwatch._default_state_of("bad port name") is None


def test_watcher_is_process_wide():
    assert portwatch.watcher() is portwatch.watcher() is runtime.get("portwatch", dict)
