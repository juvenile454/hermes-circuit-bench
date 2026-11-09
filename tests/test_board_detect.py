"""board.detect with the fake esptool (S3, C3, no serial data, busy, timeout, tool missing, switch off)."""
import json
import os
import time

import pytest
import board_fixtures as bf
from board_fixtures import *  # noqa: F403

from circuit_bench.bench_core import board, contracts


def _detect(port, **kw):
    env = board.detect(port, **kw)
    assert contracts.validate_envelope(env) == [], env
    return env


def test_detect_s3_fields(fake_tools, hw_on, pty_port, monkeypatch):
    monkeypatch.setenv("ESPTOOL_BEFORE", "no-reset")
    monkeypatch.setenv("ESPTOOL_CFGFILE", "/nonexistent/esptool.cfg")
    bf.mock_comports(monkeypatch, [(pty_port.name, 0x303A, 0x1001, "USB JTAG/serial debug unit")])
    fake_tools.scenario("board-esptool-s3.json")
    env = _detect(pty_port.name)
    assert env["ok"], env["error"]
    r = env["result"]
    assert r["chip"] == "ESP32-S3 (QFN56) (revision v0.2)" and r["chip_id"] == "esp32s3"
    assert r["mac"] == "aa:bb:cc:dd:ee:ff" and r["flash_size"] == "16MB" and r["flash_type"] == "quad"
    assert r["features"] == ["Wi-Fi", "BT 5 (LE)", "Dual Core + LP Core", "240MHz", "Embedded PSRAM 8MB (AP_3v3)"]
    assert r["psram_mb"] == 8 and r["psram_vendor"] == "AP_3v3" and r["crystal_mhz"] == 40
    assert r["usb_mode"] == "USB-Serial/JTAG" and r["port_kind"] == "usb_serial_jtag"
    assert r["variant_suggestion"] == "n16r8?" and r["reset_happened"] is True and r["simulated"] is False
    assert r["description"] == "USB JTAG/serial debug unit" and r["at"].endswith("Z")
    # board.detected fields are all present
    assert {"port", "mac", "chip", "description", "features", "flash_size", "variant_suggestion", "at", "simulated"} <= set(r)
    codes = {w["code"]: w for w in env["warnings"]}
    assert "unverified mapping" in codes["variant_unverified"]["message"] and codes["variant_unverified"]["severity"] == "info"
    assert "board_reset" in codes
    assert "(unverified)" in env["summary"]
    (call,) = fake_tools.calls("esptool")
    assert call["argv"] == ["--port", pty_port.name, "--before", "default-reset", "--after", "hard-reset", "flash-id"]
    assert call["esptool_env"] == []  # ESPTOOL_* never reach esptool
    assert os.path.basename(call["cwd"]).startswith("cb-esptool-") and call["cwd"] != os.getcwd()
    assert call["home"] == call["cwd"]  # no ~/.config/esptool or ~/esptool.cfg applies
    assert not os.path.exists(call["cwd"])  # temporary folder removed


def test_detect_c3_fields(fake_tools, hw_on, pty_port, monkeypatch):
    bf.mock_comports(monkeypatch, [(pty_port.name, 0x303A, 0x1001, "USB JTAG/serial debug unit")])
    fake_tools.scenario("board-esptool-c3.json")
    env = _detect(pty_port.name, before="usb-reset")
    assert env["ok"], env["error"]
    r = env["result"]
    assert r["chip"] == "ESP32-C3 (QFN32) (revision v0.4)" and r["chip_id"] == "esp32c3"
    assert r["flash_size"] == "4MB" and r["embedded_flash_mb"] == 4 and r["psram_mb"] is None
    assert r["variant_suggestion"] is None and r["flash_type"] is None
    assert not any(w["code"] == "variant_unverified" for w in env["warnings"])
    assert fake_tools.calls("esptool")[0]["argv"][3] == "usb-reset"


def test_detect_no_serial_data_gives_tool_failed_with_boot_hint(fake_tools, hw_on, pty_port, monkeypatch):
    bf.mock_comports(monkeypatch, [(pty_port.name, 0x303A, 0x4001, "TinyUSB CDC")])
    fake_tools.scenario("board-esptool-no-serial-data.json")
    lines = []
    env = _detect(pty_port.name, on_line=lines.append)
    assert env["ok"] is False
    assert env["error"]["code"] == "tool_failed"
    assert env["error"]["hint"] == board.NO_AUTO_RESET_HINT
    assert "No serial data received" in env["error"]["message"]
    # usb_cdc_app: the same hint is given as a warning before esptool runs
    (w,) = [w for w in env["warnings"] if w["code"] == "no_auto_reset"]
    assert board.NO_AUTO_RESET_HINT in w["message"] and w["severity"] == "caution"
    assert lines[0] == f"warning: {board.NO_AUTO_RESET_HINT}" and any("Connecting" in ln for ln in lines[1:])
    assert env["result"]["reset_happened"] is True and env["result"]["port_kind"] == "usb_cdc_app"
    assert {"board-esp-usb-tinyusb-pid", "board-observed-2026-11-06-usb-cdc-app"} <= {s["id"] for s in env["sources"]}


def test_detect_failed_connect_on_unlisted_port_also_gets_the_hint(fake_tools, hw_on, pty_port, monkeypatch):
    bf.mock_comports(monkeypatch, [])
    fake_tools.scenario("board-esptool-no-serial-data.json")
    env = _detect(pty_port.name)
    assert env["error"]["code"] == "tool_failed" and env["error"]["hint"] == board.NO_AUTO_RESET_HINT
    assert not any(w["code"] == "no_auto_reset" for w in env["warnings"])


def test_detect_failed_connect_on_uart_bridge_gets_bootloader_hint(fake_tools, hw_on, pty_port, monkeypatch):
    bf.mock_comports(monkeypatch, [(pty_port.name, 0x10C4, 0xEA60, "CP2102N USB to UART")])
    fake_tools.scenario("board-esptool-no-serial-data.json")
    env = _detect(pty_port.name)
    assert env["error"]["code"] == "tool_failed" and env["error"]["hint"] == board.BOOTLOADER_HINT


def test_detect_busy_port(fake_tools, hw_on, pty_port, monkeypatch):
    bf.mock_comports(monkeypatch, [(pty_port.name, 0x303A, 0x1001, "USB JTAG/serial debug unit")])
    fake_tools.scenario("board-esptool-busy.json")
    env = _detect(pty_port.name)
    assert env["error"]["code"] == "port_busy"


def test_detect_timeout_kills_process_group(fake_tools, hw_on, pty_port, monkeypatch, tmp_path):
    bf.mock_comports(monkeypatch, [(pty_port.name, 0x303A, 0x1001, "USB JTAG/serial debug unit")])
    pid_file = tmp_path / "child.pid"
    fake_tools.scenario("board-esptool-timeout.json", **{"flash-id": {"child_pid_file": str(pid_file)}})
    monkeypatch.setattr(board, "DETECT_TIMEOUT_S", 1.5)
    t0 = time.monotonic()
    env = _detect(pty_port.name)
    assert time.monotonic() - t0 < 10
    assert env["error"]["code"] == "timeout"
    child = int(pid_file.read_text())
    for _ in range(50):
        try:
            os.kill(child, 0)
        except ProcessLookupError:
            break
        time.sleep(0.1)
    else:
        pytest.fail("esptool's child process survived the timeout")


def test_detect_tool_missing(hw_on, pty_port, monkeypatch, tmp_path):
    bf.mock_comports(monkeypatch, [])
    empty = tmp_path / "empty-bin"
    empty.mkdir()
    monkeypatch.setenv("PATH", str(empty))
    env = _detect(pty_port.name)
    assert env["error"]["code"] == "tool_missing"
    monkeypatch.setenv("CIRCUIT_BENCH_SETTINGS_JSON", json.dumps({"esptool_path": str(tmp_path / "nope" / "esptool")}))
    env = _detect(pty_port.name)
    assert env["error"]["code"] == "tool_missing" and "esptool_path" in env["error"]["message"]


def test_detect_hardware_off_is_sim_only_without_cli(fake_tools, monkeypatch):
    fake_tools.scenario("board-esptool-s3.json")
    for port in ("/dev/ttyACM0", "/dev/ttyUSB0"):
        env = _detect(port)
        assert env["error"]["code"] == "sim_only"
    monkeypatch.setenv("CIRCUIT_BENCH_HW", "on")
    monkeypatch.setenv("CIRCUIT_BENCH_SETTINGS_JSON", json.dumps({"hardware_access": False}))
    assert _detect("/dev/ttyACM0")["error"]["code"] == "sim_only"
    assert fake_tools.calls() == []


def test_detect_bad_inputs(fake_tools, hw_on, monkeypatch):
    bf.mock_comports(monkeypatch, [])
    assert _detect("--port")["error"]["code"] == "invalid_args"
    assert _detect("socket://10.0.0.1:2217")["error"]["code"] == "invalid_args"
    assert _detect("/dev/pts/cb-missing", before="whatever")["error"]["code"] == "invalid_args"
    assert _detect("/dev/pts/cb-missing")["error"]["code"] == "port_not_found"
    assert fake_tools.calls() == []


def test_detect_through_provider(fake_tools):
    board.register_provider("sim://", bf.TestProvider())
    env = _detect("sim://test-s3")
    assert env["ok"] and env["simulated"] is True and env["result"]["simulated"] is True
    assert env["result"]["port"] == "sim://test-s3" and env["result"]["variant_suggestion"] == "n16r8"
    assert "(simulated)" in env["summary"]
    assert fake_tools.calls() == []


@pytest.mark.parametrize(("lines", "expect"), [
    (["Chip type:          ESP32-S3 (QFN56) (revision v0.2)",
      "Features:           Wi-Fi, BT 5 (LE), Dual Core + LP Core, 240MHz, Embedded Flash 8MB (GD), Embedded PSRAM 2MB (AP_3v3)",
      "Detected flash size: 8MB"],
     {"psram_mb": 2, "embedded_flash_mb": 8, "variant": "n8r2?", "chip_id": "esp32s3"}),
    (["Chip type:          ESP32-S3 (QFN56) (revision v0.2)", "Features:           Wi-Fi, Embedded PSRAM 8MB",
      "Detected flash size: Unknown"],
     {"psram_mb": 8, "psram_vendor": None, "variant": None, "flash_size": None}),
    (["Chip type:          ESP32-S3 in Secure Download Mode"], {"chip_id": "esp32s3", "features": []}),
    (["Chip type:          ESP32-D0WD-V3 (revision v3.1)", "Features:           Wi-Fi, BT, Dual Core, 240MHz",
      "MAC:                AA:BB:CC:DD:EE:F0", "Detected flash size: 4MB"],
     {"chip_id": "esp32", "mac": "aa:bb:cc:dd:ee:f0", "variant": None}),  # chip register
])
def test_parse_flash_id_variants(lines, expect):
    parsed = board.parse_flash_id(lines)
    for key, value in expect.items():
        if key == "variant":
            assert board.variant_suggestion(parsed) == value
        else:
            assert parsed[key] == value, key


@pytest.mark.parametrize("flash_mb", [4, 8, 16])
@pytest.mark.parametrize("psram_mb", [None, 2, 8])
def test_variant_suggestion_is_a_known_variant_once_the_mark_is_dropped(flash_mb, psram_mb):
    """The trailing "?" only marks the guess unverified (no octal/quad PSRAM in esptool's output). The bare id is a
    variant set_board accepts; the marked one is not, so the desktop drops it before set_board (09.11.2026)."""
    from circuit_bench.bench_core import project
    parsed = {"chip_id": "esp32s3", "flash_size": f"{flash_mb}MB", "psram_mb": psram_mb}
    guess = board.variant_suggestion(parsed)
    assert guess.endswith("?") and guess.count("?") == 1
    assert project._variant("esp32s3", guess[:-1])[0] == guess[:-1]
    with pytest.raises(contracts.BenchError, match="unknown module variant"):
        project._variant("esp32s3", guess)
