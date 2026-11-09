"""board.detect knows ESP32-S2, ESP32-C6 and the ESP32-D0WD-V3 of the WT32-ETH01.

The esptool outputs are synthetic (tests/fakes/scenarios/cflash-esptool-*.json) in the esptool v5.6.0 format; the
chip names come from targets/<chip>.py (CHIP_NAME, get_chip_description) in the pinned corpus.
"""
from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest
import board_fixtures as bf
from board_fixtures import *  # noqa: F403

from circuit_bench.bench_core import board, chips, contracts

ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / "tests" / ".corpus"
MANIFEST = ROOT / "tests" / "corpus" / "chips.json"


def _scenario_lines(name: str) -> list[str]:
    data = json.loads((bf.SCENARIOS / name).read_text(encoding="utf-8"))
    return data["flash-id"]["stdout"].replace("{port}", "/dev/ttyUSB0").splitlines()


@pytest.mark.parametrize(("scenario", "chip_id", "chip"), [
    ("cflash-esptool-s2.json", "esp32s2", "ESP32-S2 (revision v0.0)"),
    ("cflash-esptool-c6.json", "esp32c6", "ESP32-C6 (QFN40) (revision v0.1)"),
    ("cflash-esptool-wt32.json", "esp32", "ESP32-D0WD-V3 (revision v3.1)"),
    ("board-esptool-s3.json", "esp32s3", "ESP32-S3 (QFN56) (revision v0.2)"),
    ("board-esptool-c3.json", "esp32c3", "ESP32-C3 (QFN32) (revision v0.4)"),
])
def test_parser_maps_through_the_register(scenario, chip_id, chip):
    parsed = board.parse_flash_id(_scenario_lines(scenario))
    assert parsed["chip"] == chip and parsed["chip_id"] == chip_id
    assert board.variant_suggestion(parsed) == (parsed["chip_id"] == "esp32s3" and "n16r8?" or None)


def test_unknown_chip_name_gives_none():
    parsed = board.parse_flash_id(_scenario_lines("cflash-esptool-unknown.json"))
    assert parsed["chip_name"] == "ESP32-H2" and parsed["chip_id"] is None
    # "Chip type:" alone (no Connected line), unknown and look-alike names
    for text in ("ESP32-H2 (revision v0.1)", "ESP32-C61 (revision v0.1)", "Unknown ESP32 (revision v3.1)",
                 "ESP32-C6X (QFN40) (revision v0.1)", "ESP8266EX", "", None, 5):
        assert board.chip_from_esptool(text) is None, text


@pytest.mark.parametrize(("text", "chip_id"), [
    ("ESP32", "esp32"), ("ESP32-S2", "esp32s2"), ("ESP32-C6", "esp32c6"),
    ("ESP32-D0WD-V3 (revision v3.1)", "esp32"), ("ESP32-D0WD-V3", "esp32"), ("ESP32-PICO-V3-02 (revision v3.0)", "esp32"),
    ("ESP32-S2FNR2 (revision v0.0)", "esp32s2"), ("ESP32-C6FH4 (QFN32) (revision v0.2)", "esp32c6"),
    ("ESP32-S3 in Secure Download Mode", "esp32s3"), ("ESP32-S3 (QFN56)", "esp32s3"),
    (" ESP32-C3 (QFN32) (revision v0.4) ", "esp32c3"),
])
def test_chip_from_esptool(text, chip_id):
    assert board.chip_from_esptool(text) == chip_id


def test_description_table_matches_the_pinned_esptool_sources():
    """ESPTOOL_DESCRIPTIONS = the string literals of get_chip_description() in esptool v5.6.0 targets/<chip>.py
    (without the 'Unknown ...' fallbacks); CHIP_NAME per target equals the register's esptool_names."""
    if not MANIFEST.is_file() or not CORPUS.is_dir():
        pytest.skip("corpus missing (scripts/fetch_corpus.py)")
    files = {e["source_id"]: e for e in json.loads(MANIFEST.read_text(encoding="utf-8"))["files"]}
    assert set(board.ESPTOOL_DESCRIPTIONS) == {n for c in chips.ids() for n in chips.get(c)["esptool_names"]}
    for cid in chips.ids():
        entry = files[f"esptool-5.6.0-target-{cid}"]
        path = CORPUS / entry["path"]
        if not path.is_file():
            pytest.skip(f"corpus file missing: {entry['path']}")
        tree = ast.parse(path.read_text(encoding="utf-8"))
        names, literals = set(), set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign) and any(getattr(t, "id", None) == "CHIP_NAME" for t in node.targets):
                names.add(getattr(node.value, "value", None))
            if isinstance(node, ast.FunctionDef) and node.name == "get_chip_description":
                literals |= {n.value for n in ast.walk(node) if isinstance(n, ast.Constant) and isinstance(n.value, str)
                             and n.value.startswith(("ESP32", "ESP8")) and not n.value.startswith("Unknown")}
        (name,) = names
        assert board.chip_from_esptool(name) == cid
        assert set(board.ESPTOOL_DESCRIPTIONS[name]) == literals, cid
        for text in literals:
            assert board.chip_from_esptool(f"{text} (revision v1.0)") == cid


@pytest.mark.parametrize(("scenario", "chip_id", "mac"), [
    ("cflash-esptool-s2.json", "esp32s2", "aa:bb:cc:dd:ee:01"),
    ("cflash-esptool-c6.json", "esp32c6", "aa:bb:cc:ff:fe:dd:ee:02"),
    ("cflash-esptool-wt32.json", "esp32", "aa:bb:cc:dd:ee:03"),
])
def test_detect_new_chips_with_the_fake_esptool(fake_tools, hw_on, pty_port, monkeypatch, scenario, chip_id, mac):
    # port kinds unchanged: a CP2102 bridge stays cp210x, the S2's own USB port is not special-cased
    bf.mock_comports(monkeypatch, [(pty_port.name, 0x10C4, 0xEA60, "CP2102N USB to UART")])
    fake_tools.scenario(scenario)
    env = board.detect(pty_port.name)
    assert contracts.validate_envelope(env) == [] and env["ok"], env
    r = env["result"]
    assert r["chip_id"] == chip_id and r["mac"] == mac and r["variant_suggestion"] is None
    assert r["port_kind"] == "cp210x"
    assert f"esptool-5.6.0-target-{chip_id}" in {s["id"] for s in env["sources"]}
    assert not any(w["code"] == "chip_unknown" for w in env["warnings"])


def test_detect_unknown_chip_warns(fake_tools, hw_on, pty_port, monkeypatch):
    bf.mock_comports(monkeypatch, [(pty_port.name, 0x303A, 0x1001, "USB JTAG/serial debug unit")])
    fake_tools.scenario("cflash-esptool-unknown.json")
    env = board.detect(pty_port.name)
    assert contracts.validate_envelope(env) == [] and env["ok"]
    assert env["result"]["chip_id"] is None
    (w,) = [w for w in env["warnings"] if w["code"] == "chip_unknown"]
    assert w["severity"] == "caution" and "refused" in w["message"]


def test_s2_otg_port_kind_stays_unknown():
    """No source for the S2's own USB-OTG IDs, so such a port is not an ESP kind (303a:0002 = S2 ROM CDC)."""
    assert board.classify_usb(0x303A, 0x0002)["kind"] == "unknown"
    assert board.classify_usb(0x10C4, 0xEA60)["kind"] == "cp210x"
