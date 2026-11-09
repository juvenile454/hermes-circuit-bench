"""Citation and reproducibility tests of the S2/C6 pin data and the S3 module variants against the pinned
corpus (marker `corpus`, skipped without it; scripts/fetch_corpus.py pins)."""
import importlib.util
import json
import re
from pathlib import Path

import pytest

from circuit_bench.bench_core import chips

ROOT = Path(__file__).resolve().parent.parent
CORPUS = ROOT / "tests" / ".corpus"
MANIFEST = json.loads((ROOT / "tests" / "corpus" / "pins.json").read_text(encoding="utf-8"))
ENTRIES = {e["source_id"]: e for e in MANIFEST["files"]}
NEW = ("esp32s2", "esp32c6")
_missing = [e["path"] for e in MANIFEST["files"] if not (CORPUS / e["path"]).is_file()]
pytestmark = [pytest.mark.corpus,
              pytest.mark.skipif(bool(_missing), reason=f"corpus missing ({len(_missing)} files): scripts/fetch_corpus.py pins")]


def gen_module():
    spec = importlib.util.spec_from_file_location("gen_pins_cpins_corpus", ROOT / "scripts" / "gen_pins.py")
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def text_of(source_id):
    e = ENTRIES[source_id]
    if e.get("excerpt"):
        return (ROOT / "tests" / "corpus" / e["excerpt"]).read_text(encoding="utf-8")
    return (CORPUS / e["path"]).read_text(encoding="utf-8")


def data(chip):
    return json.loads((ROOT / "circuit_bench" / "data" / "pins" / f"{chip}.json").read_text(encoding="utf-8"))


def notes_of(chip):
    return gen_module().parse_notes(text_of(f"idf-v6.1-gpio-{chip}"))


# --- citations ---------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("chip", NEW + ("esp32s3",))
def test_rule_and_variant_evidence_verbatim_in_the_corpus(chip):
    for r in data(chip)["rules"]:
        assert r["evidence"] in text_of(r["source_id"]), r["id"]
    for v in data(chip)["variants"]:
        assert v["evidence"] in text_of(v["source_id"]), v["id"]


@pytest.mark.parametrize("chip", NEW)
def test_idf_rules_quote_the_footnotes_of_the_gpio_table(chip):
    notes = "\n".join(notes_of(chip))
    for r in data(chip)["rules"]:
        if r["source_id"] == f"idf-v6.1-gpio-{chip}":
            assert r["evidence"] in notes, r["id"]


def test_c6_footnotes_include_the_tab_indented_bullets_and_both_variant_notes():
    notes = notes_of("esp32c6")
    assert len(notes) == 5
    assert notes[1].startswith("SPI0/1: GPIO24 ~ GPIO30") and notes[2].startswith("USB-JTAG: GPIO12 and GPIO13")
    assert "GPIO10 ~ GPIO11 are not led out to any chip pins" in notes[3] and notes[3].startswith(
        "For chip variants with an SiP flash built in")
    assert notes[4] == "For chip variants without an in-package flash, GPIO14 is not led out to any chip pins."


def test_s2_gpi_strapping_comment_uses_the_full_width_semicolon():
    assert "      - GPI；Strapping pin\n" in text_of("idf-v6.1-gpio-esp32s2")
    assert "GPI: GPIO46 is fixed to pull-down and is input only." in notes_of("esp32s2")


def test_s2_devkit_rules_quote_whole_header_cells():
    guide = text_of("devkitc1-s2")
    for cell in ("U0TXD, GPIO43, CLK_OUT1", "U0RXD, GPIO44, CLK_OUT2",
                 "RTC_GPIO19, GPIO19, U1RTS, ADC2_CH8, CLK_OUT2, USB_D-",
                 "RTC_GPIO20, GPIO20, U1CTS, ADC2_CH9, CLK_OUT1, USB_D+"):
        assert f"     - {cell}\n" in guide, cell
    assert "ESP32-S2 full-speed USB OTG interface" in guide
    caps = text_of("idf-v6.1-soccaps-esp32s2")
    assert re.search(r"^#define SOC_USB_OTG_SUPPORTED\s+1$", caps, flags=re.M)
    assert "SOC_USB_SERIAL_JTAG_SUPPORTED" not in caps  # USB OTG only, so no s2.usb_jtag rule
    # the IDF table has no comment on GPIO19/20/43/44: the DevKit guide is the source
    inc = text_of("idf-v6.1-gpio-esp32s2")
    for n in (19, 20, 43, 44):
        assert re.search(rf"\* - GPIO{n}\n(      -.*\n){{2}}      -\n", inc), n


def test_s2_adc2_wifi_line_is_for_the_s2():
    line = next(x for x in text_of("idf-v6.1-adc-oneshot").splitlines() if "ADC2 is also used by Wi-Fi" in x)
    assert line.strip().startswith(":esp32 or esp32s2 or esp32s3: - ADC2 is also used by Wi-Fi.")


def test_c6_uart0_quotes_the_devkitc1_header_table():
    guide = text_of("devkitc1-c6-v1.2")
    assert "2     TX         I/O/T   U0TXD, GPIO16, FSPICS0" in guide
    assert "3     RX         I/O/T   U0RXD, GPIO17, FSPICS1" in guide
    inc = text_of("idf-v6.1-gpio-esp32c6")
    assert "    * - GPIO16\n      -\n      -\n      -\n" in inc and "    * - GPIO17\n      -\n      -\n      -\n" in inc


def test_c6_has_one_adc_unit_no_touch_no_psram():
    caps = gen_module().parse_defines(text_of("idf-v6.1-soccaps-esp32c6"))
    assert caps["SOC_ADC_PERIPH_NUM"] == "(1U)"
    assert "SOC_TOUCH_SENSOR_SUPPORTED" not in caps and "SOC_SPIRAM_SUPPORTED" not in caps
    assert "ADC2" not in text_of("idf-v6.1-adc-channel-esp32c6")


def test_c6_variants_rest_on_the_module_datasheets():
    """WROOM-1 carries the ESP32-C6 (no in-package flash) and leads out IO10/IO11, not IO14; MINI-1 carries the
    ESP32-C6FH4/FH8 (in-package flash) and leads out IO14, not IO10/IO11."""
    gen = gen_module()
    wroom = gen.parse_module_excerpt(text_of("ds-esp32-c6-wroom-1"))
    mini = gen.parse_module_excerpt(text_of("ds-esp32-c6-mini-1"))
    assert (wroom["module"], wroom["chips"], wroom["in_package_flash"]) == ("ESP32-C6-WROOM-1", ["ESP32-C6"], False)
    assert (mini["module"], mini["chips"], mini["in_package_flash"]) == \
        ("ESP32-C6-MINI-1", ["ESP32-C6FH4", "ESP32-C6FH8"], True)
    assert {10, 11} <= wroom["ios"] and 14 not in wroom["ios"]
    assert 14 in mini["ios"] and not {10, 11} & mini["ios"]
    v = {x["id"]: x for x in data("esp32c6")["variants"]}
    assert v["wroom-1"]["module"] == wroom["module"] and v["mini-1"]["module"] == mini["module"]
    rules = {r["id"]: r for r in data("esp32c6")["rules"]}
    assert rules["c6.sip_flash"]["when"] == {"variant": "mini-1"} and rules["c6.sip_flash"]["pins"] == [10, 11]
    assert rules["c6.no_sip_flash"]["when"] == {"variant": "wroom-1"} and rules["c6.no_sip_flash"]["pins"] == [14]


def test_s3_variant_evidence_is_a_whole_row_and_the_1u_row_matches():
    rows = text_of("ds-esp32-s3-wroom-1").splitlines()
    for v in data("esp32s3")["variants"]:
        assert v["evidence"] in rows, v["id"]
        u = v["evidence"].replace("ESP32-S3-WROOM-1-", "ESP32-S3-WROOM-1U-", 1)
        assert u in rows, v["id"]  # same memory, external antenna only
        psram = "-" if not v["psram"] else f"{v['psram_mb']} MB ({v['psram'].capitalize()} SPI)"
        assert v["evidence"].startswith(f"{v['module']} {v['flash_mb']} MB (Quad SPI) {psram} ")


def test_s3_n16r16va_left_out_without_evidence():
    excerpt = text_of("ds-esp32-s3-wroom-1")
    assert "ESP32-S3-WROOM-1-N16R16VA7 16 MB (Quad SPI) 16 MB (Octal SPI) –40 ~65" in excerpt
    assert "VA" not in excerpt.replace("N16R16VA7", "")  # neither "VA" nor footnote 7 is explained in the excerpt
    assert "n16r16va" not in {v["id"] for v in data("esp32s3")["variants"]}


# --- generator -----------------------------------------------------------------------------------------------------------
def test_generator_reproduces_all_pin_files_byte_exact():
    out = gen_module().generate(CORPUS)
    assert list(out) == chips.ids()
    for chip, text in out.items():
        assert (ROOT / "circuit_bench" / "data" / "pins" / f"{chip}.json").read_bytes() == text.encode("utf-8"), chip


def test_gen_pins_check_cli_all_ok(capsys):
    assert gen_module().main(["--check", "--corpus", str(CORPUS)]) == 0
    out = capsys.readouterr().out
    assert out.count("ok  ") == len(chips.ids()) and "DIFF" not in out and "EXTRA" not in out


def _corpus(gen):
    return gen.load_corpus(CORPUS)


def test_generator_aborts_when_the_mini_1_chip_loses_its_in_package_flash():
    gen = gen_module()
    corpus = _corpus(gen)
    sid = "ds-esp32-c6-mini-1"
    corpus[sid]["text"] = corpus[sid]["text"].replace("The flash is integrated in the chip’s package", "The flash")
    with pytest.raises(gen.GenError, match="in-package flash footnote"):
        gen.build("esp32c6", corpus)


def test_generator_aborts_when_a_not_led_out_pin_is_in_the_module_table():
    gen = gen_module()
    corpus = _corpus(gen)
    sid = "ds-esp32-c6-wroom-1"
    corpus[sid]["text"] = corpus[sid]["text"].replace("NC 22 — NC", "IO14 22 I/O/T GPIO14")
    with pytest.raises(gen.GenError, match=r"variant wroom-1: \[14\] are led out"):
        gen.build("esp32c6", corpus)


def test_generator_aborts_when_variant_rules_and_variant_pins_disagree(monkeypatch):
    gen = gen_module()
    corpus = _corpus(gen)
    rules = [dict(r) for r in gen.RULES["esp32c6"] if r["id"] != "c6.no_sip_flash"]
    monkeypatch.setitem(gen.RULES, "esp32c6", rules)
    with pytest.raises(gen.GenError, match="variant wroom-1: rules with when.variant cover"):
        gen.build("esp32c6", corpus)


def test_generator_aborts_on_a_missing_also_quote():
    gen = gen_module()
    corpus = _corpus(gen)
    sid = "devkitc1-s2"
    corpus[sid]["text"] = corpus[sid]["text"].replace("U0RXD, GPIO44, CLK_OUT2", "U0RXD, GPIO44")
    with pytest.raises(gen.GenError, match="s2.uart0: quote not found"):
        gen.build("esp32s2", corpus)


def test_generator_aborts_on_a_gpi_pin_that_soc_caps_lets_drive():
    gen = gen_module()
    corpus = _corpus(gen)
    sid = "idf-v6.1-soccaps-esp32s2"
    corpus[sid]["text"] = corpus[sid]["text"].replace("& ~(0ULL | BIT46))", "& ~(0ULL))")
    with pytest.raises(gen.GenError, match="GPI pins"):
        gen.build("esp32s2", corpus)


def test_generator_aborts_on_an_s2_adc_channel_mismatch():
    gen = gen_module()
    corpus = _corpus(gen)
    sid = "idf-v6.1-gpio-esp32s2"
    corpus[sid]["text"] = corpus[sid]["text"].replace("    * - GPIO21\n      -\n", "    * - GPIO21\n      - ADC2_CH9\n")
    with pytest.raises(gen.GenError, match="ADC channels differ"):
        gen.build("esp32s2", corpus)


def test_generator_aborts_on_a_wrong_s3_1u_row():
    gen = gen_module()
    corpus = _corpus(gen)
    sid = "ds-esp32-s3-wroom-1"
    corpus[sid]["text"] = corpus[sid]["text"].replace("ESP32-S3-WROOM-1U-N4R8 4 MB (Quad SPI) 8 MB (Octal SPI)",
                                                      "ESP32-S3-WROOM-1U-N4R8 4 MB (Quad SPI) 2 MB (Quad SPI)")
    with pytest.raises(gen.GenError, match="variant n4r8: no WROOM-1U row"):
        gen.build("esp32s3", corpus)


def test_generator_aborts_on_an_uncovered_c6_comment():
    gen = gen_module()
    corpus = _corpus(gen)
    sid = "idf-v6.1-gpio-esp32c6"
    row = "    * - GPIO14\n      -\n      -\n      -\n"
    assert row in corpus[sid]["text"]
    corpus[sid]["text"] = corpus[sid]["text"].replace(row, "    * - GPIO14\n      -\n      -\n      - New note\n")
    with pytest.raises(gen.GenError, match="comment tokens"):
        gen.build("esp32c6", corpus)
