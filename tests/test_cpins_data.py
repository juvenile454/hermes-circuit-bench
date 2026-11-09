"""Checked-in pin data of ESP32-S2, ESP32-C6 and the S3 module variants (no corpus needed), cross-checked by hand
against the Espressif sources."""
import importlib.util
import json
from pathlib import Path

import pytest

from circuit_bench.bench_core import chips, pins, sources
from circuit_bench.bench_core.contracts import MODES, RULE_SEVERITIES

ROOT = Path(__file__).resolve().parent.parent
PINS_DIR = ROOT / "circuit_bench" / "data" / "pins"
MANIFEST = json.loads((ROOT / "tests" / "corpus" / "pins.json").read_text(encoding="utf-8"))
NEW = {"esp32s2": "s2", "esp32c6": "c6"}


def data(chip):
    return json.loads((PINS_DIR / f"{chip}.json").read_text(encoding="utf-8"))


def ranges(*rs):
    return [n for a, b in rs for n in range(a, b + 1)]


def rule(chip, rid):
    return next(r for r in data(chip)["rules"] if r["id"] == rid)


@pytest.fixture(scope="module")
def gen():
    spec = importlib.util.spec_from_file_location("gen_pins_cpins", ROOT / "scripts" / "gen_pins.py")
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_pin_data_chips_equal_the_register_and_titles_come_from_it(gen):
    assert set(pins.chips()) == set(chips.ids())
    assert gen.CHIPS == {c: chips.title(c) for c in chips.ids()} and list(gen.CHIPS) == chips.ids()
    assert set(gen.RULES) == set(chips.ids())
    for c in chips.ids():
        assert data(c)["title"] == chips.title(c) and data(c)["chip"] == c


@pytest.mark.parametrize("chip", list(NEW))
def test_new_rules_have_existing_sources_and_valid_shape(chip):
    d = data(chip)
    nums = {g["num"] for g in d["gpios"]}
    seen = set()
    for r in d["rules"]:
        assert r["id"] not in seen and r["id"].split(".")[0] == NEW[chip]
        seen.add(r["id"])
        assert sources.get(r["source_id"])["url"].startswith("https://") and sources.get(r["source_id"])["retrieved"]
        assert r["severity"] in RULE_SEVERITIES
        assert r["modes"] == ["*"] or set(r["modes"]) <= set(MODES)
        assert set(r["when"]) <= {"psram", "wifi", "variant"}
        assert r["pins"] and set(r["pins"]) <= nums and r["pins"] == sorted(r["pins"])
        assert r["evidence"].strip() and r["message"].strip() and r["title"].strip()
        if r.get("unverified"):
            assert r["severity"] == "info" and "unverified" in r["message"]
    for v in d["variants"]:
        assert sources.get(v["source_id"])["retrieved"]


@pytest.mark.parametrize("chip", list(NEW))
def test_generated_from_names_commit_and_the_manifest_hash_of_every_file(chip):
    g = data(chip)["generated_from"]
    assert g["repo"] == "espressif/esp-idf" and g["tag"] == "v6.1"
    assert g["commit"] == "fff9895c82d744c7237be8847347bdd1b07c6643"
    assert g["tag_object"] == "4dc1c65503e98e9a6b4c3c5646237280ba79829b"
    assert g["files"][0]["path"] == f"docs/en/api-reference/peripherals/gpio/{chip}.inc"
    # S2 and S3 share byte-identical adc_channel.h and touch .inc files: match on (sha256, source_id)
    pairs = {(e["sha256"], e["source_id"]): e for e in MANIFEST["files"]}
    for f in g["files"]:
        e = pairs[(f["sha256"], f["source_id"])]
        if "path" in f and "repo" not in f:
            assert e["url"].endswith(f"/{g['commit']}/{f['path']}")
        if "excerpt" in f:
            assert f["excerpt"] == f"tests/corpus/{e['excerpt']}" and f["url"] == e["url"]


# --- ESP32-S2 (gpio/esp32s2.inc, soc_caps.h, adc_channel.h, cap_touch_sens/esp32s2.inc) ------------------------------
def test_s2_gpios_adc_touch():
    d = data("esp32s2")
    assert [g["num"] for g in d["gpios"]] == ranges((0, 21), (26, 46)) and d["gpio_count"] == 43
    adc = {g["num"]: (g["adc"]["unit"], g["adc"]["channel"]) for g in d["gpios"] if g["adc"]}
    assert adc == {**{n: (1, n - 1) for n in range(1, 11)}, **{n: (2, n - 11) for n in range(11, 21)}}
    assert {g["num"]: g["touch"] for g in d["gpios"] if g["touch"] is not None} == {n: n for n in range(1, 15)}
    assert d["capabilities"]["touch"] == {"supported": True, "source_id": "idf-v6.1-touch-esp32s2"}
    assert [g["num"] for g in d["gpios"] if g["rtc"]] == ranges((0, 21))
    assert [g["num"] for g in d["gpios"] if g["input_only"]] == [46]
    assert [g["num"] for g in d["gpios"] if not g["internal_pulls"]] == [46]
    g46 = d["gpios"][-1]
    assert g46["tags"] == ["GPI", "Strapping pin"]  # split at the full-width semicolon of the table
    assert next(g for g in d["gpios"] if g["num"] == 1)["functions"] == ["GPIO1", "RTC_GPIO1", "ADC1_CH0", "TOUCH1"]
    assert d["variants"] == []


@pytest.mark.parametrize("rid, sev, pin_list, when, source", [
    ("s2.strapping", "caution", [0, 45, 46], {}, "idf-v6.1-gpio-esp32s2"),
    ("s2.spi_flash", "blocked", list(range(26, 33)), {}, "idf-v6.1-gpio-esp32s2"),
    ("s2.jtag", "caution", [39, 40, 41, 42], {}, "idf-v6.1-gpio-esp32s2"),
    ("s2.input_only", "blocked", [46], {}, "idf-v6.1-gpio-esp32s2"),
    ("s2.usb_otg", "caution", [19, 20], {}, "devkitc1-s2"),
    ("s2.uart0", "caution", [43, 44], {}, "devkitc1-s2"),
    ("s2.adc2_wifi", "info", list(range(11, 21)), {"wifi": True}, "idf-v6.1-adc-oneshot"),
])
def test_s2_rules_per_wp(rid, sev, pin_list, when, source):
    r = rule("esp32s2", rid)
    assert (r["severity"], r["pins"], r["when"], r["source_id"]) == (sev, pin_list, when, source)


def test_s2_rule_ids_and_modes():
    assert [r["id"] for r in data("esp32s2")["rules"]] == [
        "s2.strapping", "s2.spi_flash", "s2.jtag", "s2.input_only", "s2.usb_otg", "s2.uart0", "s2.adc2_wifi"]
    io = rule("esp32s2", "s2.input_only")["modes"]
    # i2c_* and in_pulldown are named so the reason is the fixed pull-down
    assert io == ["out", "pwm", "uart_tx", "spi_mosi", "spi_sck", "spi_cs", "i2c_sda", "i2c_scl", "in_pullup",
                  "in_pulldown"]
    assert rule("esp32s2", "s2.adc2_wifi")["modes"] == ["adc"] and rule("esp32s2", "s2.adc2_wifi")["unverified"] is True


# --- ESP32-C6 ----------------------------------------------------------------------------------------------------------
def test_c6_gpios_adc_lp_no_touch():
    d = data("esp32c6")
    assert [g["num"] for g in d["gpios"]] == ranges((0, 30)) and d["gpio_count"] == 31
    assert {g["num"]: (g["adc"]["unit"], g["adc"]["channel"]) for g in d["gpios"] if g["adc"]} == \
        {n: (1, n) for n in range(7)}
    assert [g["num"] for g in d["gpios"] if g["rtc"]] == ranges((0, 7))  # LP GPIO column
    for g in d["gpios"][:8]:
        assert f"LP_GPIO{g['num']}" in g["functions"] and f"RTC_GPIO{g['num']}" not in g["functions"]
    assert not any(g["touch"] is not None or g["input_only"] or not g["internal_pulls"] for g in d["gpios"])
    assert d["capabilities"]["touch"] == {"supported": False, "source_id": "idf-v6.1-soccaps-esp32c6"}


@pytest.mark.parametrize("rid, sev, pin_list, when, source", [
    ("c6.strapping", "caution", [4, 5, 8, 9, 15], {}, "idf-v6.1-gpio-esp32c6"),
    ("c6.spi_flash", "blocked", list(range(24, 31)), {}, "idf-v6.1-gpio-esp32c6"),
    ("c6.usb_jtag", "caution", [12, 13], {}, "idf-v6.1-gpio-esp32c6"),
    ("c6.uart0", "caution", [16, 17], {}, "devkitc1-c6-v1.2"),
    ("c6.sip_flash", "blocked", [10, 11], {"variant": "mini-1"}, "idf-v6.1-gpio-esp32c6"),
    ("c6.no_sip_flash", "blocked", [14], {"variant": "wroom-1"}, "idf-v6.1-gpio-esp32c6"),
])
def test_c6_rules_per_wp(rid, sev, pin_list, when, source):
    r = rule("esp32c6", rid)
    assert (r["severity"], r["pins"], r["when"], r["source_id"], r["modes"]) == (sev, pin_list, when, source, ["*"])


def test_c6_variants_per_c0_result():
    v = data("esp32c6")["variants"]
    assert [x["id"] for x in v] == ["mini-1", "wroom-1"]  # wroom-1 = standard, last
    mini, wroom = v
    assert (mini["module"], mini["label"], mini["source_id"]) == ("ESP32-C6-MINI-1", "MINI-1", "ds-esp32-c6-mini-1")
    assert (wroom["module"], wroom["label"], wroom["source_id"]) == ("ESP32-C6-WROOM-1", "WROOM-1",
                                                                    "ds-esp32-c6-wroom-1")
    assert "ESP32-C6FH4/ESP32-C6FH8" in mini["evidence"] and "is ESP32-C6, " in wroom["evidence"]
    for x in v:
        assert x["psram"] is None and x["psram_mb"] == 0 and x["flash_mb"] is None
        assert x["label"] == x["module"].removeprefix("ESP32-C6-")
        assert set(x) == {"id", "label", "module", "flash_mb", "psram", "psram_mb", "source_id", "evidence"}


# --- ESP32-S3 module variants (datasheet Table 1-1) --------------------------------------------------------------------
def test_s3_variants_from_the_datasheet_table():
    v = {x["id"]: x for x in data("esp32s3")["variants"]}
    assert list(v) == ["n4", "n8", "n16", "n4r2", "n8r2", "n16r2", "n4r8", "n8r8", "n16r8"]
    assert list(v)[-1] == "n16r8"  # DevKitC-1 standard stays last
    want = {"n4": (4, None, 0), "n8": (8, None, 0), "n16": (16, None, 0), "n4r2": (4, "quad", 2),
            "n8r2": (8, "quad", 2), "n16r2": (16, "quad", 2), "n4r8": (4, "octal", 8), "n8r8": (8, "octal", 8),
            "n16r8": (16, "octal", 8)}
    for vid, x in v.items():
        assert (x["flash_mb"], x["psram"], x["psram_mb"]) == want[vid], vid
        assert x["label"] == vid.upper() and x["module"] == f"ESP32-S3-WROOM-1-{vid.upper()}"
        assert x["source_id"] == "ds-esp32-s3-wroom-1" and x["evidence"].startswith(x["module"] + " ")
    assert "n16r16va" not in v and "h4" not in v
    # every octal variant meets s3.octal_psram, the quad/none variants do not
    assert rule("esp32s3", "s3.octal_psram")["when"] == {"psram": "octal"}
    assert [vid for vid, x in v.items() if x["psram"] == "octal"] == ["n4r8", "n8r8", "n16r8"]


def test_existing_chips_keep_their_rules_and_variants():
    assert [x["id"] for x in data("esp32")["variants"]] == ["wrover-e", "wroom-32e"]
    assert data("esp32c3")["variants"] == []
    assert [r["id"] for r in data("esp32s3")["rules"]] == [
        "s3.strapping", "s3.spi_flash", "s3.octal_psram", "s3.usb_jtag", "s3.uart0", "s3.pad_jtag", "s3.adc2_wifi"]
