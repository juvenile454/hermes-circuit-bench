"""Serial routes and the serial WebSocket: open/close/tail, state + snapshot on every connect, epoch,
live lines with seq, panic messages and panic.detected, polling fallback with the same seq, socket credentials."""
import time

import board_fixtures as bf
import pytest
import test_api_support as sup
from board_fixtures import hw_on, pty_port  # noqa: F401 - fixtures
from starlette.websockets import WebSocketDisconnect
from test_api_support import *  # noqa: F403

# synthetic panic in the format of ESP-IDF v6.1 "Fatal Errors" (source idf-v6.1-fatal-errors); addresses invented
PANIC = [
    "Guru Meditation Error: Core  1 panic'ed (StoreProhibited). Exception was unhandled.",
    "",
    "Core  1 register dump:",
    "PC      : 0x42001d6a  PS      : 0x00060030  A0      : 0x82001d8d  A1      : 0x3fcebd70",
    "EXCCAUSE: 0x0000001d  EXCVADDR: 0x0000000c",
    "",
    "Backtrace: 0x42001d67:0x3fcebd70 0x42001d8a:0x3fcebd90 0x42003a5e:0x3fcebdb0",
    "",
    "ELF file SHA256: 3f9a5c0d21e8b47a",
    "Rebooting...",
]
BOOT = ["ESP-ROM:esp32s3-20210327", "rst:0x1 (POWERON),boot:0x8 (SPI_FAST_FLASH_BOOT)"]


def tail(api, port, **params):
    return api.ok(api.get("/serial/tail", params={"port": port, **params}))["result"]


def test_open_tail_close_on_a_simulated_port(api, events):
    opened = api.ok(api.post("/serial/open", {"port": "sim://test-s3", "baud": 115200, "project": "demo-x"}))
    res = opened["result"]
    assert opened["action"] == "serial.open" and opened["simulated"] is True
    assert res["state"] == "open" and res["baud"] == 115200 and res["epoch"]
    assert bf.wait_for(lambda: len(tail(api, "sim://test-s3")["lines"]) == 2)
    t = tail(api, "sim://test-s3")
    assert [m["seq"] for m in t["lines"]] == [1, 2] and [m["text"] for m in t["lines"]] == ["boot", "ready"]
    assert t["epoch"] == res["epoch"] and t["next_seq"] == 3
    assert tail(api, "sim://test-s3", after=1)["lines"][0]["seq"] == 2
    assert tail(api, "sim://test-s3", after=2)["lines"] == []
    closed = api.ok(api.post("/serial/close", {"port": "sim://test-s3"}))
    assert closed["action"] == "serial.close" and closed["result"]["state"] == "closed"
    api.err(api.get("/serial/tail", params={"port": "sim://test-s3", "after": "x"}), 400, "invalid_args")
    api.err(api.get("/serial/tail", params={"port": "sim://test-s3", "limit": "0"}), 400, "invalid_args")
    api.err(api.get("/serial/tail"), 400, "invalid_args")
    api.err(api.post("/serial/open", {"port": "sim://test-s3", "reset": "yes"}), 400, "invalid_args")
    api.err(api.post("/serial/open", {"port": "sim://test-s3", "baud": 12}), 400, "invalid_args")
    api.err(api.post("/serial/open", {"port": "socket://evil:1234"}), 423, "sim_only")  # not sim://: a real port


def test_socket_sends_state_and_snapshot_then_live_lines_and_panic(api, hw_on, pty_port, events):  # noqa: F811
    port = pty_port.name
    opened = api.ok(api.post("/serial/open", {"port": port, "baud": 115200, "project": "bench-x"}))
    ep = opened["result"]["epoch"]
    pty_port.write("hello", "world")
    assert bf.wait_for(lambda: len(tail(api, port)["lines"]) == 2)
    with api.ws(f"/serial/stream?port={port}&native_dial=ticket-ignored") as ws:
        state = ws.get()
        assert state["t"] == "state" and state["port"] == port and state["state"] == "open"
        assert state["epoch"] == ep and state["simulated"] is False
        snap = [ws.get(), ws.get()]
        assert [(m["t"], m["seq"], m["text"]) for m in snap] == [("line", 1, "hello"), ("line", 2, "world")]
        pty_port.write(*BOOT, *PANIC)
        msgs = ws.until(lambda m: m["t"] == "panic", timeout=8)
        lines = [m for m in msgs if m["t"] == "line"]
        assert [m["seq"] for m in lines] == list(range(3, 3 + len(lines)))
        panic = msgs[-1]
        assert panic["summary"] == "StoreProhibited · core 1" and panic["seq"] == 5
        assert panic["log_ref"].startswith("panic-") and panic["log_ref"].endswith(".log")
    # a second connect with the same URL replays state and snapshot (the client drops seen seq per epoch)
    with api.ws(f"/serial/stream?port={port}") as ws:
        again = ws.until(lambda m: m["t"] == "panic", timeout=8)
        assert again[0]["t"] == "state" and again[0]["epoch"] == ep
        assert [m["seq"] for m in again if m["t"] == "line"] == list(range(1, 3 + len(PANIC) + len(BOOT)))
        assert again[-1] == panic
    # the polling fallback has the same seq and the same panic
    t = tail(api, port, after=0)
    assert [m["seq"] for m in t["lines"]] == [m["seq"] for m in again if m["t"] == "line"]
    assert t["panic"] == panic and t["epoch"] == ep
    detected = events.of("panic.detected")
    assert detected == [{"project": "bench-x", "port": port, "reason": "StoreProhibited · core 1", "top_frame": None,
                         "log_ref": panic["log_ref"], "seq": 5}]
    api.ok(api.post("/serial/close", {"port": port}))


def test_socket_follows_open_and_close_and_adds_epoch_to_state(api):
    with api.ws("/serial/stream?port=sim://test-c3") as ws:
        first = ws.get()
        assert first["state"] == "closed" and first["next_seq"] == 1 and first["epoch"]
        api.ok(api.post("/serial/open", {"port": "sim://test-c3"}))
        msgs = ws.until(lambda m: m.get("text") == "ready")
        assert msgs[0] == {"t": "state", "port": "sim://test-c3", "state": "open", "detail": "115200 baud",
                           "epoch": first["epoch"]}
        assert [m["seq"] for m in msgs[1:]] == [1, 2]
        api.ok(api.post("/serial/close", {"port": "sim://test-c3"}))
        closed = ws.until(lambda m: m["t"] == "state")
        assert closed[-1]["state"] == "closed" and closed[-1]["epoch"] == first["epoch"]


def test_several_clients_and_unsubscribe_on_disconnect(api):
    serialport = sup.route_module("serialport")
    pw = sup.route_module("portwatch").watcher()
    with api.ws("/serial/stream?port=sim://test-s3") as a, api.ws("/serial/stream?port=sim://test-s3") as b:
        a.get()
        b.get()
        assert pw._clients == 2 and pw.active()
        api.ok(api.post("/serial/open", {"port": "sim://test-s3"}))
        assert a.until(lambda m: m.get("text") == "ready")[-1]["seq"] == 2
        assert b.until(lambda m: m.get("text") == "ready")[-1]["seq"] == 2
    assert bf.wait_for(lambda: pw._clients == 0)
    subs = serialport.broker()._get("sim://test-s3").subs
    assert bf.wait_for(lambda: len(subs) == 1)  # only the panic relay of POST /serial/open is left
    assert "watch_panics" in next(iter(subs.values())).__qualname__


def test_anonymous_socket_is_refused_before_accept(api):
    with pytest.raises(WebSocketDisconnect) as e:
        with api.ws("/serial/stream?port=sim://test-s3", stamp=False) as ws:
            ws.get(timeout=2)
    assert e.value.code == 1008
    with pytest.raises(WebSocketDisconnect) as e:
        with api.ws("/serial/stream?port=bad%20port") as ws:
            ws.get(timeout=2)
    assert e.value.code == 1008


def test_epoch_changes_with_a_new_process_and_seq_restarts(api):
    runtime = sup.route_module("runtime")
    api.ok(api.post("/serial/open", {"port": "sim://test-s3"}))
    assert bf.wait_for(lambda: len(tail(api, "sim://test-s3")["lines"]) == 2)
    old = tail(api, "sim://test-s3")
    sup.shutdown()
    runtime.reset()  # what a backend restart does to the process-wide objects
    board = sup.route_module("board")
    runtime.get("board.sim_registered", lambda: {"done": True})["done"] = True
    board.register_provider("sim://", bf.TestProvider())
    api.ok(api.post("/serial/open", {"port": "sim://test-s3"}))
    assert bf.wait_for(lambda: len(tail(api, "sim://test-s3")["lines"]) == 2)
    new = tail(api, "sim://test-s3")
    assert new["epoch"] != old["epoch"]
    assert [m["seq"] for m in new["lines"]] == [m["seq"] for m in old["lines"]] == [1, 2]


def test_lagging_client_gets_a_notice(api, monkeypatch):
    stream = __import__("circuit_bench_api_routes.serial_stream", fromlist=["QUEUE_MAX"])
    monkeypatch.setattr(stream, "QUEUE_MAX", 1)
    provider = bf.TestProvider(lines=[f"l{i}" for i in range(200)])
    sup.route_module("board").register_provider("sim://", provider)
    with api.ws("/serial/stream?port=sim://test-s3") as ws:
        ws.get()
        api.ok(api.post("/serial/open", {"port": "sim://test-s3"}))
        deadline = time.monotonic() + 5
        seen = []
        while time.monotonic() < deadline:
            try:
                seen.append(ws.get(timeout=0.5))
            except Exception:  # noqa: BLE001 - quiet socket
                break
        assert seen
        notices = [m for m in seen if m["t"] == "state" and "lagging" in m.get("detail", "")]
        lines = [m for m in seen if m["t"] == "line"]
        assert notices or len(lines) == 200
        assert [m["seq"] for m in lines] == sorted(m["seq"] for m in lines)
