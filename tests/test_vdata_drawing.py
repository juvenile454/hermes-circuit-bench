"""Cited ``drawing`` blocks for the six boards besides the S3-DevKitC-1 pilot.

* (a) every board has a drawing and it passes ``boards.drawing_problems``.
* (b) apart from ``drawing`` the board file is unchanged: SHA-256 of the canonical JSON of the original
  without ``drawing``.
* (c) every part of the guide's component table that maps to a DRAWING_KINDS kind is drawn, or excluded here with a
  reason.
* Stricter than test_v0_drawing: each quote is a substring of ONE line of its source; a connector form is only set when
  the quote names it; parts read from a photo name the guide's pinned figure.
"""
import hashlib
import json
from pathlib import Path

import pytest

from circuit_bench.bench_core import boards

ROOT = Path(__file__).resolve().parent.parent
CORPUS = ROOT / "tests" / ".corpus"
FILES: dict[str, list[dict]] = {}
for _name in ("boards", "pins", "wt32", "visual"):
    for _e in json.loads((ROOT / "tests" / "corpus" / f"{_name}.json").read_text(encoding="utf-8"))["files"]:
        FILES.setdefault(_e["source_id"], []).append(_e)

# sha256(json.dumps(board_without_drawing, sort_keys=True)) of the files before the drawing blocks were added.
ORIGINAL_SHA256 = {
    "esp32-devkitc-v4": "71435ec0f1950af4ef74d25755c98c9bc50f6e02c60b4aa692ebd1924e940f56",
    "esp32-c3-devkitm-1": "b79d1eaf703e1420c08a9614343228353b512cc9d55288f88d0ec6925b2ff277",
    "esp32-s2-devkitc-1": "35d99311eb49046b9ab472be3daf33b133e9717f74e031a493d2d22d350e1dcd",
    "esp32-c6-devkitc-1": "49b7e868b93ccce97257d8977d8bae136c67e25217894eaaec1f4ca6dd085e2d",
    "esp32-c6-devkitm-1": "0216c24e53a674ee7822fe701a2941c34d14f68c1affd049b48eb02cb6354cc4",
    "wt32-eth01": "b10c08098ec2ff61959a3c1967335b0e4aa43a58a9ed26de7f288e6f257f4bf0",
}
BOARDS = sorted(ORIGINAL_SHA256)

# Component table of each guide -> (kind, label or usb ref) expected in the drawing.
EXPECTED = {
    "esp32-devkitc-v4": {("power_led", "PWR"), ("bridge_ic", "USB-UART"), ("button", "Boot"), ("usb_port", "UART"),
                         ("button", "EN")},
    "esp32-c3-devkitm-1": {("ldo", "LDO 3V3"), ("power_led", "PWR"), ("button", "Boot"), ("usb_port", "UART"),
                           ("button", "Reset"), ("bridge_ic", "USB-UART"), ("led", "RGB")},
    "esp32-s2-devkitc-1": {("power_led", "PWR"), ("bridge_ic", "USB-UART"), ("usb_port", "USB"), ("button", "Reset"),
                           ("button", "Boot"), ("usb_port", "UART"), ("led", "RGB"), ("ldo", "LDO 3V3")},
    "esp32-c6-devkitc-1": {("ldo", "LDO 3V3"), ("power_led", "PWR"), ("bridge_ic", "USB-UART"), ("usb_port", "USB"),
                           ("button", "Boot"), ("button", "Reset"), ("usb_port", "UART"), ("led", "RGB")},
    "wt32-eth01": {("rj45", "LAN"), ("phy_ic", "LAN8720A")},
}
EXPECTED["esp32-c6-devkitm-1"] = EXPECTED["esp32-c6-devkitc-1"]  # same component table

# Table rows deliberately not in the drawing, with the reason.
EXCLUDED = {
    "esp32-devkitc-v4": {"I/O Connector": "pin headers are drawn from headers[]",
                         "ESP32-WROOM-32E": "the module is drawn from module"},
    "esp32-c3-devkitm-1": {"ESP32-C3-MINI-1 or ESP32-C3-MINI-1U": "module", "Pin Headers": "headers[]"},
    "esp32-s2-devkitc-1": {"On-board module": "module", "Pin Headers": "headers[]"},
    "esp32-c6-devkitc-1": {"ESP32-C6-WROOM-1 or ESP32-C6-WROOM-1U": "module", "Pin Header": "headers[]",
                           "J5": "current-measurement jumper, no DRAWING_KINDS kind"},
    "esp32-c6-devkitm-1": {"ESP32-C6-MINI-1 or ESP32-C6-MINI-1U": "module", "Pin Header": "headers[]",
                           "J5": "current-measurement jumper, no DRAWING_KINDS kind"},
    # LED1/LED3/LED4 are cited in the datasheet, but no pinned figure shows where they sit (positions not readable in
    # the page-7 photo either); the LDO and the 50 MHz oscillator appear only in the page-7 block diagram, which the
    # pinned excerpt does not carry.
    "wt32-eth01": {"LED1": "no readable position, no pinned figure", "LED3": "same", "LED4": "same",
                   "LDO3V3": "not in the pinned excerpt", "50MHz oscillator": "no DRAWING_KINDS kind"},
}
FORM_WORDS = {"micro_usb": "Micro-USB", "usb_c": "Type-C"}


def _drawing(board_id: str) -> dict:
    return boards.load(board_id)["drawing"]


def _key(p: dict) -> tuple[str, str | None]:
    return p["kind"], p.get("ref") if p["kind"] == "usb_port" else p.get("label")


@pytest.mark.parametrize("board_id", BOARDS)
def test_board_has_a_valid_drawing(board_id):
    b = boards.load(board_id)
    assert "drawing" in b
    assert boards.drawing_problems(b) == []
    assert list(b)[-1] == "drawing"


@pytest.mark.parametrize("board_id", BOARDS)
def test_other_keys_unchanged(board_id):
    b = boards.load(board_id)
    b.pop("drawing")
    assert hashlib.sha256(json.dumps(b, sort_keys=True).encode()).hexdigest() == ORIGINAL_SHA256[board_id]


@pytest.mark.parametrize("board_id", BOARDS)
def test_component_table_is_covered(board_id):
    got = [_key(p) for p in _drawing(board_id)["parts"]]
    assert len(got) == len(set(got)), got
    assert set(got) == EXPECTED[board_id]
    assert EXCLUDED[board_id]


@pytest.mark.parametrize("board_id", BOARDS)
def test_connector_form_only_when_the_quote_names_it(board_id):
    for p in _drawing(board_id)["parts"]:
        if p["kind"] != "usb_port":
            continue
        form = p["connector"]
        if form is None:
            assert not any(w in p["quote"] for w in FORM_WORDS.values()), p
        else:
            assert FORM_WORDS[form] in p["quote"], p


@pytest.mark.parametrize("board_id", BOARDS)
def test_photo_positions_name_the_guide_figure(board_id):
    b = boards.load(board_id)
    figures = {Path(e["path"]).name for e in FILES[b["source_id"]] if e["path"].endswith(("-photo.png",
                                                                                           "-overview.png"))}
    for p in _drawing(board_id)["parts"]:
        if board_id == "wt32-eth01":
            # No pinned image for the WT32-ETH01: figure and note go together, so both are absent.
            assert "figure" not in p and "note" not in p, p
        else:
            assert p["source_id"] == b["source_id"] and p["figure"] in figures, p
            assert "not machine-checkable" in p["note"], p


def _lines(source_id: str) -> list[str]:
    out: list[str] = []
    for e in FILES.get(source_id, []):
        if e.get("excerpt"):
            inside = False
            for line in (ROOT / "tests" / "corpus" / e["excerpt"]).read_text(encoding="utf-8").split("\n"):
                if line.startswith("@@ "):
                    inside = True
                elif inside and line:
                    out.append(line)
        elif not e["path"].endswith((".png", ".jpg", ".pdf", ".html")) and (CORPUS / e["path"]).is_file():
            out += (CORPUS / e["path"]).read_text(encoding="utf-8").split("\n")
    return out


def _cited(board_id: str):
    d = _drawing(board_id)
    yield from d["parts"]
    if "module_size_mm" in d:
        yield d["module_size_mm"]


_missing = sorted({e["path"] for b in BOARDS for item in _cited(b) for e in FILES.get(item["source_id"], [])
                   if not e.get("excerpt") and not (CORPUS / e["path"]).is_file()})


@pytest.mark.corpus
@pytest.mark.skipif(bool(_missing), reason=f"corpus missing ({len(_missing)} files): scripts/fetch_corpus.py")
@pytest.mark.parametrize("board_id", BOARDS)
def test_every_quote_sits_on_one_line(board_id):
    for item in _cited(board_id):
        lines = _lines(item["source_id"])
        assert lines and any(item["quote"] in line for line in lines), item
