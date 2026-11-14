"""The esp32-bench skill knows every DevKit, every chip, the WT32 and C6 notes and the chip refusals.
Size and format follow hermes-agent-skill-authoring."""
import re
from pathlib import Path

from circuit_bench import skill_frontmatter
from circuit_bench.bench_core import chips

ROOT = Path(__file__).resolve().parent.parent
SKILL = ROOT / "circuit_bench" / "skills" / "esp32-bench" / "SKILL.md"
BOARDS = ROOT / "circuit_bench" / "data" / "boards"
NEW_DEVKITS = ("esp32-s2-devkitc-1", "esp32-c6-devkitc-1", "esp32-c6-devkitm-1", "wt32-eth01")


def _text() -> str:
    return SKILL.read_text(encoding="utf-8")


def test_every_devkit_id_of_data_boards_is_in_the_skill():
    text = _text()
    ids = sorted(p.stem for p in BOARDS.glob("*.json"))
    assert ids  # the folder is read dynamically: new layouts must reach the skill
    assert [i for i in ids if f"`{i}`" not in text] == []


def test_the_new_devkits_are_in_the_skill():
    text = _text()
    assert [i for i in NEW_DEVKITS if f"`{i}`" not in text] == []


def test_every_chip_of_the_register_is_in_the_skill():
    text = _text()
    assert [c for c in chips.ids() if f"`{c}`" not in text] == []


def test_wt32_notes():
    text = _text()
    wt32 = text[text.index("WT32-ETH01"):]
    for phrase in ("no USB", "USB-to-UART adapter", "IO0", "GND", "EN", "3V3 **or** 5V", "never both", "GPIO0"):
        assert phrase in wt32, phrase


def test_c6_needs_platform_8():
    assert "espressif32@8.0.0" in _text()


def test_refusals_listed_with_explanation():
    text = _text()
    refusals = text[text.index("If a flash is refused"):]
    for code in ("flash_disabled", "not_confirmed", "elf_mismatch", "unattended_blocked", "sim_only",
                 "chip_mismatch", "platform_too_old"):
        assert f"`{code}`" in refusals, code
    assert "set_board" in refusals and "detect" in refusals  # chip_mismatch: what to do


def test_not_verified_on_hardware_sentence():
    assert "C3, S2 and C6 are checked offline only" in _text() and "WT32-ETH01 was tested on a real board" in _text()


def test_format_and_size():
    text = _text()
    meta = skill_frontmatter(text)
    assert meta["name"] == "esp32-bench" and re.fullmatch(r"[a-z0-9-]{1,64}", meta["name"])
    desc = meta["description"]
    assert desc.startswith("Use when") and desc.endswith(".") and len(desc) <= 60
    assert len(text.splitlines()) <= 120 and len(text) <= 9200
