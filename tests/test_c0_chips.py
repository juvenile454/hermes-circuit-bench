"""Chip register, its citations and the chip/board/variant contracts.

Citation tests (marker `corpus`) read the pinned files of tests/corpus/chips.json; they skip without the corpus.
"""
import json
import re
from pathlib import Path

import pytest

from circuit_bench.bench_core import boards, chips, pins, sources
from circuit_bench.bench_core.contracts import ERROR_CODES, BenchError

ROOT = Path(__file__).resolve().parent.parent
CORPUS = ROOT / "tests" / ".corpus"
MANIFEST = json.loads((ROOT / "tests" / "corpus" / "chips.json").read_text(encoding="utf-8"))
FILES = {e["source_id"]: e for e in MANIFEST["files"]}
_missing = [e["path"] for e in MANIFEST["files"] if not (CORPUS / e["path"]).is_file()]
corpus = [pytest.mark.corpus, pytest.mark.skipif(bool(_missing), reason="corpus missing: scripts/fetch_corpus.py chips")]


def text(source_id: str) -> str:
    return (CORPUS / FILES[source_id]["path"]).read_text(encoding="utf-8")


# --- register shape and API -----------------------------------------------------------------------------------------
def test_register_ids_and_order():
    assert chips.ids() == ["esp32", "esp32s2", "esp32s3", "esp32c3", "esp32c6"]
    assert chips.ids_text() == "esp32, esp32s2, esp32s3, esp32c3, esp32c6"


def test_pin_data_chips_are_registered():
    # the pin data may lag behind the register here; equality is checked in tests/test_c1_lead.py
    assert set(pins.chips()) <= set(chips.ids())


def test_api():
    assert chips.arch("esp32c6") == "riscv" and chips.arch("esp32s2") == "xtensa"
    assert chips.toolchain_prefix("esp32s2") == "xtensa-esp32s2-elf"
    assert chips.toolchain_prefix("esp32c6") == chips.toolchain_prefix("esp32c3") == "riscv32-esp-elf"
    assert chips.by_esptool_name("ESP32-C6") == "esp32c6"
    assert chips.by_esptool_name("ESP32") == "esp32"
    assert chips.by_esptool_name("ESP32-H2") is None and chips.by_esptool_name(None) is None
    assert chips.by_pio_mcu("ESP32S2") == "esp32s2" and chips.by_pio_mcu("esp32h2") is None
    assert chips.arduino_platform_min("esp32c6") == "8.0.0"
    assert chips.arduino_platform_min("esp32s3") is None
    assert chips.xtensa_prefixes() == ("xtensa-esp32-elf", "xtensa-esp32s2-elf", "xtensa-esp32s3-elf")
    assert chips.riscv_prefixes() == ("riscv32-esp-elf",)
    with pytest.raises(BenchError) as e:
        chips.get("esp32h2")
    assert e.value.code == "unknown_chip"


def test_get_returns_a_copy():
    c = chips.get("esp32")
    c["esptool_names"].append("X")
    assert chips.get("esp32")["esptool_names"] == ["ESP32"]


def test_every_cited_source_exists():
    for cid in chips.ids():
        c = chips.get(cid)
        for key, sid in c["source_ids"].items():
            assert key in c, (cid, key)
            for s in ([sid] if isinstance(sid, str) else sid):
                sources.get(s)
        assert {"arch", "toolchain_prefix", "esptool_names", "pio_mcu"} <= c["source_ids"].keys(), cid
        assert (c["arduino_platform_min"] is None) == ("arduino_platform_min" not in c["source_ids"]), cid


# --- citations against the pinned files -----------------------------------------------------------------------------
@pytest.mark.parametrize("cid", chips.ids())
@pytest.mark.corpus
def test_arch_from_kconfig(cid):
    if _missing:
        pytest.skip("corpus missing")
    block = re.search(rf"config IDF_TARGET_{cid.upper()}\n(.*?)\n\n", text("idf-v6.1-kconfig"), re.S)
    assert block, cid
    assert f"default \"y\" if IDF_TARGET=\"{cid}\"" in block.group(1)
    assert f"select IDF_TARGET_ARCH_{chips.arch(cid).upper()}" in block.group(1)


@pytest.mark.parametrize("cid", chips.ids())
@pytest.mark.corpus
def test_toolchain_prefix_from_cmake(cid):
    if _missing:
        pytest.skip("corpus missing")
    sid = chips.get(cid)["source_ids"]["toolchain_prefix"]
    assert f"set(_CMAKE_TOOLCHAIN_PREFIX {chips.toolchain_prefix(cid)}-)" in text(sid)


@pytest.mark.parametrize("cid", chips.ids())
@pytest.mark.corpus
def test_esptool_names(cid):
    if _missing:
        pytest.skip("corpus missing")
    sid = chips.get(cid)["source_ids"]["esptool_names"]
    names = re.findall(r'^    CHIP_NAME = "([^"]+)"$', text(sid), re.M)
    assert names == chips.get(cid)["esptool_names"]


@pytest.mark.parametrize("cid", chips.ids())
@pytest.mark.corpus
def test_pio_mcu(cid):
    if _missing:
        pytest.skip("corpus missing")
    sid = chips.get(cid)["source_ids"]["pio_mcu"]
    assert json.loads(text(sid))["build"]["mcu"] == chips.get(cid)["pio_mcu"]


@pytest.mark.corpus
def test_c6_arduino_floor_from_the_board_json():
    if _missing:
        pytest.skip("corpus missing")
    fw = {v: json.loads(text(f"pio-esp32-{v}-board-c6"))["frameworks"] for v in ("6.9.0", "7.1.3", "8.0.0")}
    assert fw == {"6.9.0": ["espidf"], "7.1.3": ["espidf"], "8.0.0": ["arduino", "espidf"]}
    assert chips.arduino_platform_min("esp32c6") == "8.0.0"


@pytest.mark.corpus
def test_other_chips_build_with_arduino_on_the_pinned_6_9_0():
    if _missing:
        pytest.skip("corpus missing")
    for sid in ("pio-esp32-6.9.0-board-s2-saola-1", "pio-esp32-6.9.0-board-wt32-eth01", "pio-esp32-6.9.0-board-s3",
                "pio-esp32-6.9.0-board-c3"):
        assert "arduino" in json.loads(text(sid))["frameworks"], sid


# --- contracts --------------------------------------------------------------------------------------------------------
def test_new_error_codes():
    assert {"chip_mismatch", "platform_too_old"} <= ERROR_CODES
    BenchError("chip_mismatch", "x")


def test_pin_kinds():
    assert boards.PIN_KINDS == ("gpio", "power", "ground", "reset", "nc", "signal")


def test_layout_passes_optional_keys_through(monkeypatch):
    b = boards.load("esp32-devkitc-v4")
    b.update({"buttons": [], "warnings": [{"id": "x.w", "severity": "danger", "message": "m", "source_id": "s"}],
              "connectors": [{"kind": "rj45", "label": "LAN"}], "ethernet": {"phy": "LAN8720A"}, "flash_hint": "h"})
    monkeypatch.setattr(boards, "_read", lambda board_id: b)
    out = boards.layout("esp32-devkitc-v4")
    assert out["buttons"] == [] and out["warnings"][0]["severity"] == "danger"
    assert out["connectors"] == [{"kind": "rj45", "label": "LAN"}] and out["ethernet"] == {"phy": "LAN8720A"}
    assert out["flash_hint"] == "h"
    assert boards.warnings_of("esp32-devkitc-v4")[0]["id"] == "x.w"


def test_existing_layouts_unchanged():
    for bid in ("esp32-devkitc-v4", "esp32-s3-devkitc-1", "esp32-c3-devkitm-1"):
        out = boards.layout(bid)
        assert not {"warnings", "connectors", "ethernet", "flash_hint"} & out.keys(), bid
        assert boards.warnings_of(bid) == []
