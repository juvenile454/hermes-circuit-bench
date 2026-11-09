"""Refusal hints name the setting as the app shows it and give the exact command."""
import re
from pathlib import Path

import pytest

from circuit_bench import tools
from circuit_bench.bench_core import board, clitools, doctor, guard, project, settings
from circuit_bench.bench_core.contracts import BenchError

PLUGIN_YAML = Path(__file__).resolve().parents[1] / "circuit_bench" / "plugin.yaml"


def _label(key):
    text = PLUGIN_YAML.read_text(encoding="utf-8")
    block = text.split(f"\n  {key}:\n", 1)[1]
    return re.search(r'label:\s*"([^"]+)"', block)[1]


def test_labels_come_from_the_config_schema(monkeypatch):
    assert f"'{_label('allow_flash')}'" in settings.FLASH_DISABLED_HINT
    assert "Settings → Plugins → Circuit Bench → Agent settings" in settings.FLASH_DISABLED_HINT
    monkeypatch.delenv("CIRCUIT_BENCH_HW")
    assert f"'{_label('hardware_access')}'" in settings.sim_only_hint()
    assert f"'{_label('pio_path')}'" in settings.tool_hint("pio")
    assert f"'{_label('esptool_path')}'" in settings.tool_hint("esptool")


def test_flash_disabled_names_the_switch(monkeypatch):
    monkeypatch.setenv("CIRCUIT_BENCH_HW", "on")
    res = guard.check_flash(via="tool", settings={"hardware_access": True, "allow_flash": False}, project=None,
                            port="/dev/ttyACM-cb-fake0", cron=False)
    assert res["error"]["code"] == "flash_disabled"
    assert res["error"]["hint"].startswith("turn on 'Allow flashing real boards' in Settings → Plugins → Circuit Bench "
                                           "→ Agent settings")


def test_sim_only_names_the_variable_only_when_it_is_set(monkeypatch):
    monkeypatch.setenv("CIRCUIT_BENCH_HW", "off")
    assert "CIRCUIT_BENCH_HW=off" in settings.sim_only_hint()
    monkeypatch.delenv("CIRCUIT_BENCH_HW")
    hint = settings.sim_only_hint()
    assert "CIRCUIT_BENCH_HW" not in hint and "'Access real hardware' (hardware_access)" in hint
    monkeypatch.setenv("CIRCUIT_BENCH_SETTINGS_JSON", '{"hardware_access": false}')
    with pytest.raises(BenchError) as e:
        clitools.run(["esptool", "flash-id"], timeout=5)
    assert e.value.code == "sim_only" and "CIRCUIT_BENCH_HW" not in e.value.hint
    env = board.detect("/dev/ttyACM-cb-fake0")
    assert env["error"]["code"] == "sim_only" and "'Access real hardware'" in env["error"]["hint"]


def test_tool_missing_says_how_to_install(monkeypatch, tmp_path):
    monkeypatch.setenv("PATH", str(tmp_path))
    monkeypatch.setenv("HOME", str(tmp_path))
    assert "pipx install platformio" in settings.tool_hint("pio") and "PlatformIO Core" in settings.tool_hint("pio")
    assert settings.tool_hint("esptool").startswith("pipx install esptool")
    fw = tmp_path / "fw"
    fw.mkdir()
    (fw / "platformio.ini").write_text("[env:s3]\n", encoding="utf-8")
    env = board.build(fw, "s3")
    assert env["error"]["code"] == "tool_missing" and "pipx install platformio" in env["error"]["hint"]
    with pytest.raises(BenchError) as e:
        board._tool("esptool")
    assert e.value.code == "tool_missing" and "pipx install esptool" in e.value.hint
    with pytest.raises(BenchError) as e:  # the CLI is gone between lookup and start
        clitools.run([str(tmp_path / "no" / "cb-tool")], timeout=5)
    assert e.value.code == "tool_missing"


def test_project_not_found_points_to_the_list():
    env = project.get("ghost")
    assert env["error"]["code"] == "project_not_found" and "bench_project action=list" in env["error"]["hint"]
    env = tools.run_tool("bench_project", {"action": "note", "id": "ghost", "text": "x"}, tools.Host())
    assert "bench_project action=list" in env["error"]["hint"]


def test_serial_group_hint_gives_the_command(monkeypatch):
    assert "usermod -aG dialout $USER" in settings.SERIAL_GROUP_HINT and "log in again" in settings.SERIAL_GROUP_HINT
    assert "sudo" not in settings.SERIAL_GROUP_HINT  # Hermes' install scanner flags a bare `sudo` (sudo_usage, high)
    lines = ["A fatal error occurred: Could not open /dev/ttyACM9, the port is busy or doesn't exist.",
             "([Errno 13] Permission denied: '/dev/ttyACM9')"]
    err = board._esptool_failure(lines, "/dev/ttyACM9", None, 2)
    assert err.hint == settings.SERIAL_GROUP_HINT
    monkeypatch.setattr(doctor, "_groups", lambda: {"group": "dialout", "member": False})
    warn = next(w for w in doctor.run()["warnings"] if w["code"] == "serial_group")
    assert "usermod -aG dialout $USER, then log in again" in warn["message"] and "sudo" not in warn["message"]


def test_write_timeout_in_a_crash_loop_points_to_boot_reset():
    # hardware test: pio upload (esptool 4.5.1) against an ESP32-S3 in a panic reboot loop, nothing written
    lines = ["Uploading .pio/build/s3/firmware.bin", "esptool.py v4.5.1", "Serial port /dev/ttyACM0", "Connecting....",
             "", "A serial exception error occurred: Write timeout",
             ("Note: This error originates from pySerial. It is likely not a problem with esptool, but with the "
              "hardware connection or drivers."), "*** [upload] Error 1",
             "========================= [FAILED] Took 41.27 seconds ========================="]
    err = board._esptool_failure(lines, "/dev/ttyACM0", "usb_serial_jtag", 1)
    assert err.code == "tool_failed" and "write timeout" in str(err)
    assert err.hint == board.WRITE_TIMEOUT_HINT and "hold BOOT, tap RESET" in err.hint and "nothing was written" in err.hint
    # a timeout after data was written is not this case
    err = board._esptool_failure(["Writing at 0x00010000... (10 %)", *lines[5:]], "/dev/ttyACM0", "usb_serial_jtag", 1)
    assert err.hint != board.WRITE_TIMEOUT_HINT
