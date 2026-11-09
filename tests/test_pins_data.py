"""Checked-in pin data (no corpus needed), cross-checked by hand against the Espressif sources."""
import json
from pathlib import Path

import pytest

from circuit_bench.bench_core import boards, pins, sources
from circuit_bench.bench_core.contracts import MODES, RULE_SEVERITIES

ROOT = Path(__file__).resolve().parent.parent
PINS_DIR = ROOT / "circuit_bench" / "data" / "pins"
MANIFEST = json.loads((ROOT / "tests" / "corpus" / "pins.json").read_text(encoding="utf-8"))
CHIPS = ("esp32", "esp32s3", "esp32c3")


def data(chip):
    return json.loads((PINS_DIR / f"{chip}.json").read_text(encoding="utf-8"))


def source_ids(obj):
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k == "source_id" and v is not None:
                yield v
            yield from source_ids(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from source_ids(v)


def test_exactly_the_three_chips():
    # the pin data also covers esp32s2/esp32c6 (tests/test_cpins_data.py)
    assert set(CHIPS) <= set(pins.chips())


@pytest.mark.parametrize("chip", CHIPS)
def test_every_source_id_exists(chip):
    ids = set(source_ids(data(chip)))
    assert ids
    for i in ids:
        assert sources.get(i)["retrieved"]


@pytest.mark.parametrize("chip", CHIPS)
def test_every_rule_has_existing_source_and_valid_shape(chip):
    d = data(chip)
    nums = {g["num"] for g in d["gpios"]}
    seen = set()
    for r in d["rules"]:
        assert r["id"] not in seen and r["id"].split(".")[0] in {"esp32": "esp32", "esp32s3": "s3", "esp32c3": "c3"}[chip]
        seen.add(r["id"])
        assert sources.get(r["source_id"])["url"].startswith("https://")
        assert r["severity"] in RULE_SEVERITIES
        assert r["modes"] == ["*"] or set(r["modes"]) <= set(MODES)
        assert set(r["when"]) <= {"psram", "wifi", "variant"}
        assert r["pins"] and set(r["pins"]) <= nums and r["pins"] == sorted(r["pins"])
        assert r["evidence"].strip() and r["message"].strip() and r["title"].strip()
        if r.get("unverified"):
            assert r["severity"] == "info" and "unverified" in r["message"]


@pytest.mark.parametrize("chip", CHIPS)
def test_generated_from_pins_commit_and_manifest_hashes(chip):
    g = data(chip)["generated_from"]
    assert g["repo"] == "espressif/esp-idf" and g["tag"] == "v6.1"
    assert g["tag_object"] == "4dc1c65503e98e9a6b4c3c5646237280ba79829b"
    assert len(g["commit"]) == 40
    # S2 and S3 share byte-identical files (adc_channel.h, touch .inc): key on hash and source id
    by_hash = {(f["sha256"], f["source_id"]): f for f in MANIFEST["files"]}
    assert g["files"][0]["path"] == f"docs/en/api-reference/peripherals/gpio/{chip}.inc"
    for f in g["files"]:
        assert len(f["sha256"]) == 64 and (f["sha256"], f["source_id"]) in by_hash, f
        if "path" in f and "repo" not in f:
            assert by_hash[(f["sha256"], f["source_id"])]["url"].endswith(f"/{g['commit']}/{f['path']}")


def ranges(*rs):
    return [n for a, b in rs for n in range(a, b + 1)]


# values from the Espressif sources (checked by hand 2026-11-05) against the generated data
@pytest.mark.parametrize("chip, gpios", [
    ("esp32", ranges((0, 19), (21, 23), (25, 27), (32, 39))),
    ("esp32s3", ranges((0, 21), (26, 48))),
    ("esp32c3", ranges((0, 21))),
])
def test_gpio_lists_match_quellen(chip, gpios):
    d = data(chip)
    assert [g["num"] for g in d["gpios"]] == gpios
    assert d["gpio_count"] == len(gpios)


@pytest.mark.parametrize("chip, adc1, adc2", [
    ("esp32", ranges((32, 39)), {0: 1, 2: 2, 4: 0, 12: 5, 13: 4, 14: 6, 15: 3, 25: 8, 26: 9, 27: 7}),
    ("esp32s3", ranges((1, 10)), {n: n - 11 for n in range(11, 21)}),
    ("esp32c3", ranges((0, 4)), {5: 0}),
])
def test_adc_matches_quellen(chip, adc1, adc2):
    d = data(chip)
    assert sorted(g["num"] for g in d["gpios"] if g["adc"] and g["adc"]["unit"] == 1) == adc1
    assert {g["num"]: g["adc"]["channel"] for g in d["gpios"] if g["adc"] and g["adc"]["unit"] == 2} == adc2
    if chip == "esp32s3":
        assert {g["num"]: g["adc"]["channel"] for g in d["gpios"] if g["adc"] and g["adc"]["unit"] == 1} == \
            {n: n - 1 for n in adc1}


@pytest.mark.parametrize("chip, rule, expected", [
    ("esp32", "esp32.strapping", [0, 2, 5, 12, 15]),
    ("esp32", "esp32.spi_flash", [6, 7, 8, 9, 10, 11]),
    ("esp32", "esp32.psram_16_17", [16, 17]),
    ("esp32", "esp32.jtag", [12, 13, 14, 15]),
    ("esp32", "esp32.input_only", [34, 35, 36, 37, 38, 39]),
    ("esp32", "esp32.no_pulls", [34, 35, 36, 37, 38, 39]),
    ("esp32", "esp32.uart0", [1, 3]),
    ("esp32", "esp32.adc2_wifi", [0, 2, 4, 12, 13, 14, 15, 25, 26, 27]),
    ("esp32", "esp32.gpio36_39_irq", [36, 39]),
    ("esp32s3", "s3.strapping", [0, 3, 45, 46]),
    ("esp32s3", "s3.spi_flash", [26, 27, 28, 29, 30, 31, 32]),
    ("esp32s3", "s3.octal_psram", [33, 34, 35, 36, 37]),
    ("esp32s3", "s3.usb_jtag", [19, 20]),
    ("esp32s3", "s3.uart0", [43, 44]),
    ("esp32s3", "s3.pad_jtag", [39, 40, 41, 42]),
    ("esp32s3", "s3.adc2_wifi", list(range(11, 21))),
    ("esp32c3", "c3.strapping", [2, 8, 9]),
    ("esp32c3", "c3.spi_flash", [12, 13, 14, 15, 16, 17]),
    ("esp32c3", "c3.usb_jtag", [18, 19]),
    ("esp32c3", "c3.uart0", [20, 21]),
])
def test_rule_pins_match_quellen_and_wp(chip, rule, expected):
    assert next(r for r in data(chip)["rules"] if r["id"] == rule)["pins"] == expected


def test_rule_severities_and_conditions_per_wp():
    def rule(chip, rid):
        return next(r for r in data(chip)["rules"] if r["id"] == rid)
    sev = {(c, r["id"]): r["severity"] for c in CHIPS for r in data(c)["rules"]}
    assert sev[("esp32", "esp32.strapping")] == "caution" and sev[("esp32", "esp32.spi_flash")] == "blocked"
    assert sev[("esp32", "esp32.jtag")] == "caution" and sev[("esp32", "esp32.uart0")] == "caution"
    assert sev[("esp32", "esp32.adc2_wifi")] == "blocked" and sev[("esp32", "esp32.gpio36_39_irq")] == "info"
    assert rule("esp32", "esp32.adc2_wifi")["when"] == {"wifi": True} and rule("esp32", "esp32.adc2_wifi")["modes"] == ["adc"]
    assert set(rule("esp32", "esp32.input_only")["modes"]) >= {"out", "pwm", "uart_tx", "spi_mosi", "spi_sck", "spi_cs"}
    assert rule("esp32", "esp32.no_pulls")["modes"] == ["in_pullup", "in_pulldown"]
    assert rule("esp32s3", "s3.octal_psram")["when"] == {"psram": "octal"}
    assert sev[("esp32s3", "s3.octal_psram")] == "blocked" and sev[("esp32s3", "s3.spi_flash")] == "blocked"
    assert sev[("esp32s3", "s3.usb_jtag")] == "caution" and sev[("esp32s3", "s3.uart0")] == "caution"
    assert sev[("esp32s3", "s3.pad_jtag")] == "info" and sev[("esp32s3", "s3.adc2_wifi")] == "info"
    assert rule("esp32s3", "s3.uart0")["source_id"] == "devkitc1-s3-v1.1" == rule("esp32s3", "s3.pad_jtag")["source_id"]
    assert "relevant only if pad JTAG is used" in rule("esp32s3", "s3.pad_jtag")["message"]
    assert rule("esp32s3", "s3.adc2_wifi")["unverified"] is True
    assert sev[("esp32c3", "c3.strapping")] == "caution" and sev[("esp32c3", "c3.spi_flash")] == "blocked"
    assert sev[("esp32c3", "c3.usb_jtag")] == "caution"
    # GPIO16/17 only with the WROVER PSRAM; C3 UART0 from the DevKitM-1 guide
    assert sev[("esp32", "esp32.psram_16_17")] == "blocked"
    assert rule("esp32", "esp32.psram_16_17")["when"] == {"psram": "spi"}
    assert rule("esp32", "esp32.psram_16_17")["source_id"] == "devkitc-esp32-v4"
    assert rule("esp32", "esp32.spi_flash")["when"] == {} and rule("esp32", "esp32.spi_flash")["source_id"] == \
        "idf-v6.1-gpio-esp32"
    assert sev[("esp32c3", "c3.uart0")] == "caution" and rule("esp32c3", "c3.uart0")["source_id"] == "devkitm1-c3-v1"


def test_esp32_input_only_and_pulls_flags():
    d = data("esp32")
    assert sorted(g["num"] for g in d["gpios"] if g["input_only"]) == list(range(34, 40))
    assert sorted(g["num"] for g in d["gpios"] if not g["internal_pulls"]) == list(range(34, 40))
    for chip in ("esp32s3", "esp32c3"):
        assert not any(g["input_only"] or not g["internal_pulls"] for g in data(chip)["gpios"])


def test_s3_variants_with_datasheet_source():
    v = {x["id"]: x for x in data("esp32s3")["variants"]}
    assert list(v) == ["n4", "n8", "n16", "n4r2", "n8r2", "n16r2", "n4r8", "n8r8", "n16r8"]  # ordering-code order
    assert (v["n8"]["flash_mb"], v["n8"]["psram"], v["n8"]["psram_mb"]) == (8, None, 0)
    assert (v["n8r2"]["flash_mb"], v["n8r2"]["psram"], v["n8r2"]["psram_mb"]) == (8, "quad", 2)
    assert (v["n16r8"]["flash_mb"], v["n16r8"]["psram"], v["n16r8"]["psram_mb"]) == (16, "octal", 8)
    for x in v.values():
        assert x["source_id"] == "ds-esp32-s3-wroom-1" and x["evidence"].startswith(x["module"])
    assert data("esp32c3")["variants"] == []


def test_esp32_variants_with_ordering_table_source():
    """WROVER-E (8 MB flash, 8 MB PSRAM) and WROOM-32E (4 MB, no PSRAM) from the DevKitC V4 ordering table;
    the standard module of the DevKitC V4 comes last (desktop default)."""
    v = {x["id"]: x for x in data("esp32")["variants"]}
    assert list(v) == ["wrover-e", "wroom-32e"]
    assert (v["wroom-32e"]["module"], v["wroom-32e"]["flash_mb"], v["wroom-32e"]["psram"], v["wroom-32e"]["psram_mb"]) \
        == ("ESP32-WROOM-32E", 4, None, 0)
    assert (v["wrover-e"]["module"], v["wrover-e"]["flash_mb"], v["wrover-e"]["psram"], v["wrover-e"]["psram_mb"]) \
        == ("ESP32-WROVER-E", 8, "spi", 8)
    for x in v.values():
        assert x["source_id"] == "devkitc-esp32-v4-ordering" and x["module"] in x["evidence"]
        assert x["label"] == x["module"].removeprefix("ESP32-")
    assert data("esp32")["variants"][-1]["id"] == boards.load("esp32-devkitc-v4")["module"]["variant"]
    # the only PSRAM-dependent ESP32 rule meets exactly the WROVER-E
    psram_rules = [r for r in data("esp32")["rules"] if "psram" in r["when"]]
    assert [r["id"] for r in psram_rules] == ["esp32.psram_16_17"]
    assert [x["id"] for x in v.values() if x["psram"] == psram_rules[0]["when"]["psram"]] == ["wrover-e"]


def test_s3_gpio35_functions_per_contract_example():
    g = next(g for g in data("esp32s3")["gpios"] if g["num"] == 35)
    assert set(g["functions"]) == {"SPIIO6", "GPIO35", "FSPID", "SUBSPID"}
    assert (g["rtc"], g["adc"], g["input_only"], g["internal_pulls"]) == (False, None, False, True)


def test_devkit_gpios_exist_in_s3_data():
    nums = {g["num"] for g in data("esp32s3")["gpios"]}
    on_board = boards.broken_out("esp32-s3-devkitc-1")
    assert on_board <= nums
    assert nums - on_board == set(range(26, 35))  # SPI flash/PSRAM 26-32 and 33/34 are not on the headers


def test_load_returns_copy_without_internal_keys():
    a = pins.load("ESP32-S3")
    a["gpios"].clear()
    b = pins.load("esp32s3")
    assert b["gpios"] and not any(k.startswith("_") for k in b)


def test_pin_json_is_canonical():
    for chip in CHIPS:
        text = (PINS_DIR / f"{chip}.json").read_text(encoding="utf-8")
        assert text == json.dumps(json.loads(text), indent=1, ensure_ascii=False) + "\n"
