"""Port list, VID:PID kinds, hardware switch, provider ports."""
import json

import pytest
import board_fixtures as bf
from board_fixtures import *  # noqa: F403

from circuit_bench.bench_core import board, contracts, runtime, sources

FIXTURE_KEYS = {"device", "vid", "pid", "description", "kind", "likely_esp", "simulated"}


@pytest.mark.parametrize(("vid", "pid", "kind", "auto_reset"), [
    (0x303A, 0x1001, "usb_serial_jtag", True),
    (0x303A, 0x4001, "usb_cdc_app", False),
    (0x303A, 0x4003, "usb_cdc_app", False),  # CDC + MSC under the esp_tinyusb default PID scheme
    (0x303A, 0x4002, "unknown", None),  # MSC only: no serial interface of the TinyUSB scheme
    (0x10C4, 0xEA60, "cp210x", True),
    (0x1A86, 0x7523, "ch340", True),
    (0x1A86, 0x55D3, "ch343", True),
    (0x1A86, 0x55D4, "ch9102", True),
    (0x0403, 0x6001, "ftdi", True),
    (0x1234, 0x5678, "unknown", None),
    (None, None, "unknown", None),
])
def test_classify_usb(vid, pid, kind, auto_reset):
    c = board.classify_usb(vid, pid)
    assert c["kind"] == kind and c["auto_reset"] is auto_reset
    assert c["likely_esp"] is (kind != "unknown" or vid == 0x303A)
    for sid in c["source_ids"]:
        assert sources.get(sid)["retrieved"] == "2026-11-06"


def test_usb_table_sources_exist_and_4001_is_marked_observed():
    for (_vid, _pid), (_kind, _label, _likely, ids) in board._USB_TABLE.items():
        assert ids and all(sources.get(i) for i in ids)
    ids = board.classify_usb(0x303A, 0x4001)["source_ids"]
    assert "board-esp-usb-tinyusb-pid" in ids
    observed = sources.get("board-observed-2026-11-06-usb-cdc-app")
    assert observed["url"] is None and observed["note"].startswith("observed")


def test_hardware_off_lists_no_real_ports(monkeypatch):
    calls = bf.mock_comports(monkeypatch, [("/dev/ttyUSB-cb-fake0", 0x10C4, 0xEA60, "CP2102N")])
    assert board.list_ports() == []
    assert calls == []  # pyserial's list is not even consulted
    env = board.ports()
    assert env["ok"] and env["result"]["ports"] == []
    assert env["warnings"][0]["code"] == "hardware_off"


def test_hardware_on_lists_real_ports_like_the_fixture(monkeypatch, hw_on):
    bf.mock_comports(monkeypatch, [("/dev/ttyACM-cb-fake1", 0x303A, 0x1001, "USB JTAG/serial debug unit"),
                                ("/dev/ttyACM-cb-fake0", 0x303A, 0x4001, "TinyUSB CDC"),
                                ("/dev/ttyS-cb-fake9", None, None, "n/a")])
    items = board.list_ports()
    assert [p["device"] for p in items] == ["/dev/ttyACM-cb-fake0", "/dev/ttyACM-cb-fake1"]  # placeholder ttyS hidden
    jtag = items[1]
    assert jtag == {"device": "/dev/ttyACM-cb-fake1", "vid": "303a", "pid": "1001",
                    "description": "USB JTAG/serial debug unit", "kind": "usb_serial_jtag", "likely_esp": True,
                    "simulated": False}
    assert items[0]["kind"] == "usb_cdc_app"
    with open("desktop-src/fixtures/ports.json", encoding="utf-8") as fh:
        fixture = json.load(fh)
    for p in items + fixture["result"]["ports"]:
        assert set(p) == FIXTURE_KEYS


def test_ports_envelope_warns_about_usb_cdc_app(monkeypatch, hw_on):
    bf.mock_comports(monkeypatch, [("/dev/ttyACM-cb-fake0", 0x303A, 0x4001, "TinyUSB CDC")])
    env = board.ports()
    assert contracts.validate_envelope(env) == []
    w = [w for w in env["warnings"] if w["code"] == "no_auto_reset"]
    assert len(w) == 1 and w[0]["severity"] == "caution" and board.NO_AUTO_RESET_HINT in w[0]["message"]
    assert {"board-esp-usb-tinyusb-pid", "board-observed-2026-11-06-usb-cdc-app"} <= {s["id"] for s in env["sources"]}
    assert env["summary"].startswith("1 port: /dev/ttyACM-cb-fake0 (ESP32 firmware USB CDC")


def test_pyserial_missing_is_a_warning_not_a_crash(monkeypatch, hw_on):
    def missing():
        raise contracts.BenchError("dependency_missing", "pyserial is not installed: real ports cannot be listed")
    monkeypatch.setattr(board, "_comports", missing)
    env = board.ports()
    assert env["ok"] and env["result"]["ports"] == []
    assert any(w["code"] == "dependency_missing" for w in env["warnings"])


def test_provider_ports_are_appended_and_survive_hardware_off(monkeypatch):
    bf.mock_comports(monkeypatch, [("/dev/ttyUSB-cb-fake0", 0x10C4, 0xEA60, "CP2102N")])
    board.register_provider("sim://", bf.TestProvider())
    items = board.list_ports()
    assert [p["device"] for p in items] == ["sim://test-s3", "sim://test-c3"]
    assert all(p["simulated"] and p["kind"] == "sim" and p["vid"] is None for p in items)
    env = board.ports()
    assert env["simulated"] is True and "sim://test-s3 (simulated)" in env["summary"]


def test_provider_ports_after_real_ports(monkeypatch, hw_on):
    bf.mock_comports(monkeypatch, [("/dev/ttyUSB-cb-fake0", 0x10C4, 0xEA60, "CP2102N USB to UART")])
    board.register_provider("sim://", bf.TestProvider())
    env = board.ports()
    assert [p["device"] for p in env["result"]["ports"]] == ["/dev/ttyUSB-cb-fake0", "sim://test-s3", "sim://test-c3"]
    assert env["simulated"] is False


def test_broken_provider_does_not_hide_other_ports(monkeypatch, hw_on):
    class Broken(bf.TestProvider):
        def ports(self):
            raise RuntimeError("boom")
    bf.mock_comports(monkeypatch, [("/dev/ttyUSB-cb-fake0", 0x1A86, 0x7523, "USB Serial")])
    board.register_provider("sim://", Broken())
    env = board.ports()
    assert [p["device"] for p in env["result"]["ports"]] == ["/dev/ttyUSB-cb-fake0"]
    assert any(w["code"] == "provider_failed" for w in env["warnings"])


def test_sim_import_error_means_no_sim_ports(monkeypatch):
    bf.mock_comports(monkeypatch, [])
    assert board.list_ports() == []  # import of bench_core.sim fails (fixture): no sim ports, no error
    assert runtime.peek("board.sim_registered") == {"done": True}
    assert board.ports()["ok"] is True


def test_sim_register_is_called_lazily_once(monkeypatch):
    calls = []

    def register():
        calls.append(1)
        board.register_provider("sim://", bf.TestProvider())

    bf.use_sim_module(monkeypatch, register)
    assert calls == []
    assert [p["device"] for p in board.list_ports()] == ["sim://test-s3", "sim://test-c3"]
    board.list_ports()
    board.detect("sim://test-s3")
    assert calls == [1]


def test_broken_sim_register_does_not_break_ports(monkeypatch, hw_on):
    def register():
        raise RuntimeError("sim broken")

    bf.use_sim_module(monkeypatch, register)
    bf.mock_comports(monkeypatch, [("/dev/ttyUSB-cb-fake0", 0x10C4, 0xEA60, "CP2102N")])
    assert [p["device"] for p in board.list_ports()] == ["/dev/ttyUSB-cb-fake0"]


def test_register_provider_validates():
    with pytest.raises(contracts.BenchError) as e:
        board.register_provider("sim", bf.TestProvider())
    assert e.value.code == "invalid_args"
    with pytest.raises(contracts.BenchError):
        board.register_provider("sim://", object())


def test_unknown_sim_port_without_provider():
    env = board.detect("sim://nothing-here")
    assert env["ok"] is False and env["error"]["code"] == "port_not_found"


def test_placeholder_uarts_are_hidden_and_esp_ports_come_first(monkeypatch):
    """Real finding on the test machine: 32 /dev/ttyS* with hwid 'n/a' next to the ESP32-S3 (06.11.2026)."""
    monkeypatch.setenv("CIRCUIT_BENCH_HW", "on")
    entries = [(f"/dev/ttyS-cb-fake{i}", None, None, "n/a") for i in range(3)]
    entries += [("/dev/ttyUSB-cb-fake0", 0x0403, 0x6001, "FT232R"), ("/dev/ttyACM-cb-fake0", 0x303A, 0x4001, "Espressif CDC Device")]
    bf.mock_comports(monkeypatch, entries)
    devices = [p["device"] for p in board.list_ports() if not p["simulated"]]
    assert devices == ["/dev/ttyACM-cb-fake0", "/dev/ttyUSB-cb-fake0"]
