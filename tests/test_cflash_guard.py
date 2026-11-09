"""guard.check_flash refuses a wrong or unknown chip (chip_mismatch); the board's
``flash_hint`` replaces the generic BOOT/RESET hints on connection errors.

The flash_hint board is synthetic (a tmp data/boards folder); the real WT32-ETH01 layout is used only when it is
present.
"""
from __future__ import annotations

import copy
import functools
import json

import pytest
import board_fixtures as bf
from board_fixtures import *  # noqa: F403

from circuit_bench.bench_core import board, boards, contracts, guard

REAL = "/dev/ttyACM0"
SIM = "sim://esp32s3-n16r8"
MAC = "aa:bb:cc:dd:ee:ff"
SHA = "3f9a5c0d21e8b47a6c13f0e2d9b8a7c6e5f4d3c2b1a09f8e7d6c5b4a39281706"
ON = {"allow_flash": True, "approve_serial": True, "hardware_access": True}
HINT = ("This board has no BOOT/RESET buttons and no auto-reset: tie IO0 to GND, power-cycle, flash, then "
        "release IO0 (synthetic test hint)")


def _project(chip="esp32s3", detected_chip="ESP32-S3 (QFN56) (revision v0.2)", port=REAL, devkit=None):
    det = {"port": port, "mac": MAC, "chip": detected_chip, "description": None, "features": [],
           "flash_size": "16MB", "variant_suggestion": None, "at": "2026-11-06T21:41:07Z",
           "simulated": port.startswith("sim://")}
    return {"id": "chip-test", "rev": 3,
            "board": {"chip": chip, "module": None, "variant": None, "devkit": devkit, "detected": det},
            "firmware": {"dir": "/srv/fw", "env": "e", "last_flash": None,
                         "last_build": {"ok": True, "at": "2026-11-06T21:38:52Z", "ram_pct": 5.6, "flash_pct": 7.9,
                                        "elf": "x.elf", "elf_sha256": SHA}}}


def _flash(project, **kw):
    args = {"via": "tool", "settings": ON, "project": project, "port": REAL, "confirm": None, "cron": False} | kw
    return guard.check_flash(**args)


@pytest.fixture
def no_hermes(monkeypatch):
    monkeypatch.delenv("HERMES_YOLO_MODE", raising=False)
    monkeypatch.setitem(__import__("sys").modules, "hermes_cli", None)


@pytest.fixture
def hint_board(tmp_path, monkeypatch):
    """A synthetic board without buttons and with a flash_hint, in a temporary data/boards folder."""
    d = tmp_path / "boards"
    d.mkdir()
    (d / "cb-test-nobuttons.json").write_text(json.dumps({
        "id": "cb-test-nobuttons", "title": "Synthetic board without buttons", "revision": None, "chip": "esp32",
        "source_id": "board-esp32-s3-devkitc-1-v1.1", "headers": [], "onboard": [], "usb": [], "buttons": [],
        "flash_hint": HINT}), encoding="utf-8")
    (d / "cb-test-plain.json").write_text(json.dumps({
        "id": "cb-test-plain", "title": "Synthetic board", "chip": "esp32s3", "source_id": "x", "headers": []}),
        encoding="utf-8")
    monkeypatch.setattr(boards, "BOARDS_DIR", d)
    boards.clear_cache()
    yield "cb-test-nobuttons"
    boards.clear_cache()


# --------------------------------------------------------------------------------------------- guard

def test_c6_project_with_a_detected_s3_is_refused(hw_on, no_hermes):
    res = _flash(_project(chip="esp32c6"))
    assert res is not None and contracts.validate_envelope(res) == []
    assert res["error"]["code"] == "chip_mismatch" and res["action"] == "board.flash"
    assert "esp32s3" in res["error"]["message"] and "esp32c6" in res["error"]["message"]  # names both
    assert "esp32c6" in res["error"]["hint"] and "detect again" in res["error"]["hint"]
    route = _flash(_project(chip="esp32c6"), via="route", confirm={"port": REAL, "mac": MAC, "elf_sha256": SHA})
    assert route["error"]["code"] == "chip_mismatch"


@pytest.mark.parametrize("detected", ["ESP32-S3 (QFN56) (revision v0.2)", "ESP32-S3", "ESP32-S3 in Secure Download Mode"])
def test_s3_project_with_a_detected_s3_is_fine(hw_on, no_hermes, detected):
    assert _flash(_project(detected_chip=detected)) is None
    assert _flash(_project(detected_chip=detected), via="route",
                  confirm={"port": REAL, "mac": MAC, "elf_sha256": SHA}) is None


@pytest.mark.parametrize(("chip", "detected"), [("esp32", "ESP32-D0WD-V3 (revision v3.1)"),
                                                 ("esp32s2", "ESP32-S2 (revision v0.0)"),
                                                 ("esp32c6", "ESP32-C6 (QFN40) (revision v0.1)")])
def test_new_chips_pass_when_they_match(hw_on, no_hermes, chip, detected):
    assert _flash(_project(chip=chip, detected_chip=detected)) is None


@pytest.mark.parametrize("detected", ["ESP32-H2 (revision v0.1)", "Unknown ESP32 (revision v3.1)", None, ""])
def test_unknown_or_missing_chip_name_is_refused(hw_on, no_hermes, detected):
    res = _flash(_project(detected_chip=detected))
    assert res["error"]["code"] == "chip_mismatch" and "unknown" in res["error"]["message"]
    assert res["error"]["hint"] == "connect the board and detect again"


def test_earlier_refusals_keep_their_codes(hw_on, no_hermes):
    p = _project(chip="esp32c6")
    assert _flash(p, settings={**ON, "allow_flash": False})["error"]["code"] == "flash_disabled"
    p2 = copy.deepcopy(p)
    p2["firmware"]["last_build"] = None
    assert _flash(p2)["error"]["code"] == "not_confirmed"
    assert _flash(p, via="route", confirm=None)["error"]["code"] == "not_confirmed"
    assert _flash(p, port="/dev/ttyACM1")["error"]["code"] == "not_confirmed"


def test_sim_port_is_exempt(no_hermes):
    """sim:// reports an ESP32-S3; a C6 project on the sim board stays flashable (nothing physical is written)."""
    assert _flash(_project(chip="esp32c6", port=SIM), port=SIM) is None
    assert _flash(_project(chip="esp32c6", detected_chip=None, port=SIM), port=SIM) is None


def test_board_flash_runs_no_cli_on_chip_mismatch(fake_tools, hw_on, no_hermes, tmp_path, pty_port, monkeypatch):
    bf.mock_comports(monkeypatch, [(pty_port.name, 0x303A, 0x1001, "USB JTAG/serial debug unit")])
    d = tmp_path / "fw"
    (d / "src").mkdir(parents=True)
    (d / "platformio.ini").write_text("[env:e]\nplatform = espressif32@8.0.0\nboard = esp32-c6-devkitc-1\n"
                                      "framework = arduino\n", encoding="utf-8")
    gate = functools.partial(guard.check_flash, via="tool", settings=ON, port=pty_port.name, cron=False,
                             project=_project(chip="esp32c6", port=pty_port.name))
    env = board.flash(d, "e", pty_port.name, expected_elf_sha256=SHA, guard=gate)
    assert env["error"]["code"] == "chip_mismatch" and fake_tools.calls() == []


# --------------------------------------------------------------------------------------------- flash_hint

def test_flash_hint_lookup(hint_board):
    assert board.flash_hint(hint_board) == (HINT, [])
    assert board.flash_hint("cb-test-plain") == (None, [])
    assert board.flash_hint("no-such-board") == (None, [])
    assert board.flash_hint(None) == (None, [])
    assert boards.layout(hint_board)["flash_hint"] == HINT and boards.layout(hint_board)["buttons"] == []


def test_detect_connection_error_uses_the_flash_hint(fake_tools, hw_on, pty_port, monkeypatch, hint_board):
    bf.mock_comports(monkeypatch, [(pty_port.name, 0x10C4, 0xEA60, "CP2102N USB to UART")])
    fake_tools.scenario("board-esptool-no-serial-data.json")
    env = board.detect(pty_port.name, devkit=hint_board)
    assert contracts.validate_envelope(env) == []
    assert env["error"]["code"] == "tool_failed" and env["error"]["hint"] == HINT
    # without the devkit (or with a board without flash_hint) the generic hint stays
    assert board.detect(pty_port.name)["error"]["hint"] == board.BOOTLOADER_HINT
    assert board.detect(pty_port.name, devkit="cb-test-plain")["error"]["hint"] == board.BOOTLOADER_HINT


def test_detect_timeout_uses_the_flash_hint(fake_tools, hw_on, pty_port, monkeypatch, hint_board):
    bf.mock_comports(monkeypatch, [(pty_port.name, 0x10C4, 0xEA60, "CP2102N USB to UART")])
    monkeypatch.setattr(board, "DETECT_TIMEOUT_S", 0.5)
    fake_tools.scenario({"flash-id": {"rc": 0, "stdout": "Connecting...\n", "sleep": 5}})
    env = board.detect(pty_port.name, devkit=hint_board)
    assert env["error"]["code"] == "timeout" and env["error"]["hint"] == HINT


def test_flash_connection_error_uses_the_flash_hint(fake_tools, hw_on, pty_port, monkeypatch, tmp_path, hint_board):
    bf.mock_comports(monkeypatch, [(pty_port.name, 0x303A, 0x4001, "TinyUSB CDC")])
    d = tmp_path / "fw"
    (d / "src").mkdir(parents=True)
    (d / "platformio.ini").write_text("[env:s3]\nplatform = espressif32@6.9.0\nboard = esp32-s3-devkitc-1\n"
                                      "framework = arduino\n", encoding="utf-8")
    fake_tools.scenario("board-pio-flash-no-serial-data.json")
    sha = board.build(d, "s3")["result"]["elf_sha256"]
    env = board.flash(d, "s3", pty_port.name, expected_elf_sha256=sha, guard=lambda: None, devkit=hint_board)
    assert contracts.validate_envelope(env) == []
    assert env["error"]["code"] == "tool_failed" and env["error"]["hint"] == HINT
    env = board.flash(d, "s3", pty_port.name, expected_elf_sha256=sha, guard=lambda: None)
    assert env["error"]["hint"] == board.NO_AUTO_RESET_HINT


def test_real_wt32_layout_hint_if_present(fake_tools, hw_on, pty_port, monkeypatch):
    if "wt32-eth01" not in boards.ids():
        pytest.skip("data/boards/wt32-eth01.json is missing")
    hint, _ = board.flash_hint("wt32-eth01")
    if hint is None:
        pytest.skip("wt32-eth01 has no flash_hint yet")
    bf.mock_comports(monkeypatch, [(pty_port.name, 0x10C4, 0xEA60, "CP2102N USB to UART")])
    fake_tools.scenario("board-esptool-no-serial-data.json")
    assert board.detect(pty_port.name, devkit="wt32-eth01")["error"]["hint"] == hint
