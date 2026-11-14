"""Detect and monitor questions: a port URL without a provider (anything with ``://`` that is no ``sim://`` port) is
blocked before the question, with the handler's own words, and leaves no grant; the port of the question shows only
letters, digits and ``._:/-`` as they are (every other character as ``\\uXXXX``), like the flash question. Normal
ports give the same question and rule key as before."""
import hashlib
import json
import sys
import types

import pytest

from circuit_bench import hooks, tools
from circuit_bench.bench_core import board, project, serialport, shown
from circuit_bench.bench_core.contracts import BenchError

MEASURED = "x:// on sim://esp32? Simulated board, nothing is reset. OK"
URL_PORTS = [MEASURED, "rfc2217://host:4000 (simulated)", "socket://192.0.2.1:3333", "x://"]
DETECT = "Detect the board on {} with esptool? This resets the board (the running firmware restarts)."
MONITOR = "Open {} for the serial monitor? Opening the port can reset the board (DTR/RTS)."
WHAT = {"detect": "board detection", "monitor": "the serial monitor"}
SHA = "e" * 64
MAC = "02:00:00:00:00:02"


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    cfg = types.ModuleType("hermes_cli.config")
    cfg.load_config = lambda: {"approvals": {"mode": "manual"}}
    pkg = types.ModuleType("hermes_cli")
    pkg.config = cfg
    monkeypatch.setitem(sys.modules, "hermes_cli", pkg)
    monkeypatch.setitem(sys.modules, "hermes_cli.config", cfg)
    monkeypatch.delenv("HERMES_YOLO_MODE", raising=False)
    monkeypatch.delenv("HERMES_CRON_SESSION", raising=False)
    monkeypatch.setenv("CIRCUIT_BENCH_HW", "on")  # the hook only decides; nothing here runs a tool or opens a port
    settings(monkeypatch, allow_flash=True)


def settings(monkeypatch, **values):
    monkeypatch.setenv("CIRCUIT_BENCH_SETTINGS_JSON", json.dumps(values))


@pytest.fixture
def host():
    return tools.Host(hook_active=True)


def decide(host, args):
    return hooks.make_pre_tool_call(host)(tool_name="bench_board", args=args, task_id="task-1", session_id="s",
                                          tool_call_id="c")


def handler_refusal(port):
    with pytest.raises(BenchError) as e:
        board._check_real_port(port)
    return e.value


def expected_block(what, port):
    err = handler_refusal(port)
    assert err.code == "invalid_args" and err.message.startswith("unsupported port URL")
    return shown.for_model(f"Circuit Bench blocked {what}: {err.message} ({err.code}); {err.hint}.")


# --------------------------------------------------------------------------------------------- port URLs

@pytest.mark.parametrize("action", ["detect", "monitor"])
@pytest.mark.parametrize("port", URL_PORTS)
def test_a_port_url_without_provider_is_blocked_before_the_question(host, action, port):
    dec = decide(host, {"action": action, "port": port, "seconds": 5})
    assert dec == {"action": "block", "message": expected_block(WHAT[action], port)}
    assert not host._grants  # no grant: the handler would find nothing to run


@pytest.mark.parametrize("action", ["detect", "monitor"])
def test_the_measured_question_is_never_asked_also_without_serial_approval(host, monkeypatch, action):
    settings(monkeypatch, approve_serial=False)
    dec = decide(host, {"action": action, "port": MEASURED})
    assert dec is not None and dec["action"] == "block" and "unsupported port URL" in dec["message"]
    assert not host._grants


@pytest.mark.parametrize("port", URL_PORTS)
def test_the_block_has_the_words_of_the_detect_and_monitor_refusals(host, monkeypatch, port):
    """The hook uses the detect handler's own check (``board._check_real_port``); board.detect and the serial
    monitor refuse such a port with the same words (hardware off: their URL check comes first, nothing is opened)."""
    monkeypatch.setenv("CIRCUIT_BENCH_HW", "off")
    for action, refused in (("detect", board.detect(port)), ("monitor", serialport.monitor(port, 1))):
        assert not refused["ok"] and refused["error"]["code"] == "invalid_args", refused
        monkeypatch.setenv("CIRCUIT_BENCH_HW", "on")
        msg = decide(host, {"action": action, "port": port})["message"]
        monkeypatch.setenv("CIRCUIT_BENCH_HW", "off")
        assert msg == shown.for_model(f"Circuit Bench blocked {WHAT[action]}: {refused['error']['message']} "
                                      f"(invalid_args); {refused['error']['hint']}.")


@pytest.mark.parametrize("action", ["detect", "monitor"])
def test_sim_ports_still_get_no_directive(host, action):
    assert decide(host, {"action": action, "port": "sim://esp32s3-n16r8"}) is None


def test_a_flash_to_a_port_url_is_blocked_before_the_question(host, short_tmp):
    fw = short_tmp / "fw"
    fw.mkdir()
    (fw / "platformio.ini").write_text("[env:s3]\n", encoding="utf-8")
    assert project.create("u", "U", "esp32s3", "n16r8")["ok"]
    assert project.update("u", 1, [
        {"op": "set_detected", "port": MEASURED, "mac": MAC, "chip": "ESP32-S3"},
        {"op": "set_firmware", "dir": str(fw), "env": "s3"},
        {"op": "set_build", "ok": True, "elf_sha256": SHA}], by="ui", trusted=True)["ok"]
    dec = decide(host, {"action": "flash", "project": "u", "elf_sha256": SHA[:12]})
    assert dec == {"action": "block", "message": expected_block("the flash", MEASURED)}
    assert not host._grants


# --------------------------------------------------------------------------------------------- shown port

@pytest.mark.parametrize("action, template", [("detect", DETECT), ("monitor", MONITOR)])
def test_a_device_name_with_punctuation_is_shown_with_escapes(host, action, template):
    port = "/dev/ttyACM0?Simulated,nothing-is-reset.OK"
    dec = decide(host, {"action": action, "port": port})
    assert dec["action"] == "approve", dec
    assert dec["message"] == template.format("/dev/ttyACM0\\u003fSimulated\\u002cnothing-is-reset.OK")
    assert dec["rule_key"] == hooks.serial_rule_key(action, port)
    assert host._grants


@pytest.mark.parametrize("action, template", [("detect", DETECT), ("monitor", MONITOR)])
def test_a_typographic_apostrophe_in_a_device_name_is_an_escape(host, action, template):
    port = "/dev/cu.Lab\u2019s-Headphones"
    dec = decide(host, {"action": action, "port": port})
    assert dec["message"] == template.format("/dev/cu.Lab\\u2019s-Headphones")


@pytest.mark.parametrize("action, template", [("detect", DETECT), ("monitor", MONITOR)])
@pytest.mark.parametrize("port, device", [
    ("/dev/ttyACM0", "/dev/ttyACM0"),
    ("/dev/ttyUSB0", "/dev/ttyUSB0"),
    ("COM3", "COM3"),
    ("/dev/cu.usbmodem1101", "/dev/cu.usbmodem1101"),
    ("/dev/serial/by-id/usb-Espressif_USB_JTAG_serial_debug_unit_F4:12:FA:00:00:01-if00", "/dev/ttyACM1"),
    ("/dev/pts/7", "/dev/pts/7"),
])
def test_normal_ports_give_the_same_question_and_rule_key(host, monkeypatch, action, template, port, device):
    monkeypatch.setenv("CIRCUIT_BENCH_DEV_GUARD", "1")  # /dev/pts/* like the pty fixtures of the tests
    real = serialport._realpath
    monkeypatch.setattr(serialport, "_realpath", lambda p: device if p == port else real(p))
    dec = decide(host, {"action": action, "port": port, "seconds": 5})
    assert dec == {"action": "approve", "message": template.format(device),
                   "rule_key": f"circuit-bench:{action}:" + hashlib.sha256(device.encode()).hexdigest()}
    assert dec["rule_key"] == hooks.serial_rule_key(action, device)
    assert list(host._grants) == [("task-1", action, device)]


@pytest.mark.parametrize("action", ["detect", "monitor"])
def test_a_failing_port_check_blocks_and_leaves_no_grant(host, monkeypatch, action):
    def broken(port):
        raise RuntimeError("unreadable")
    monkeypatch.setattr(board, "provider_for", broken)
    dec = decide(host, {"action": action, "port": "/dev/ttyACM0"})
    assert dec["action"] == "block" and "approval check failed (RuntimeError)" in dec["message"], dec
    assert not host._grants
