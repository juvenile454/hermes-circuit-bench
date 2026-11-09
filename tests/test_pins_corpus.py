"""Citation and reproducibility tests against the pinned corpus (marker `corpus`, skip without it).

Fetch the corpus with `scripts/fetch_corpus.py pins` (lands in tests/.corpus).
"""
import hashlib
import importlib.util
import json
import re
from pathlib import Path

import pytest

from circuit_bench.bench_core import boards

ROOT = Path(__file__).resolve().parent.parent
CORPUS = ROOT / "tests" / ".corpus"
MANIFEST = json.loads((ROOT / "tests" / "corpus" / "pins.json").read_text(encoding="utf-8"))
ENTRIES = {e["source_id"]: e for e in MANIFEST["files"]}
CHIPS = ("esp32", "esp32s3", "esp32c3")
_missing = [e["path"] for e in MANIFEST["files"] if not (CORPUS / e["path"]).is_file()]
pytestmark = [pytest.mark.corpus,
              pytest.mark.skipif(bool(_missing), reason=f"corpus missing ({len(_missing)} files): scripts/fetch_corpus.py pins")]


def gen_module():
    spec = importlib.util.spec_from_file_location("gen_pins_under_test", ROOT / "scripts" / "gen_pins.py")
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


def test_corpus_hashes_match_manifest():
    for e in MANIFEST["files"]:
        assert hashlib.sha256((CORPUS / e["path"]).read_bytes()).hexdigest() == e["sha256"], e["path"]


@pytest.mark.parametrize("chip", CHIPS)
def test_rule_evidence_is_quoted_verbatim_from_the_corpus(chip):
    for rule in data(chip)["rules"]:
        assert rule["evidence"] in text_of(rule["source_id"]), rule["id"]


@pytest.mark.parametrize("chip", CHIPS)
def test_variant_evidence_is_quoted_verbatim_from_the_corpus(chip):
    for v in data(chip)["variants"]:
        assert v["evidence"] in text_of(v["source_id"]), v["id"]


def _ordering_rows():
    """Rows of the ESP32-DevKitC V4 ordering list-table, parsed here independently of the generator."""
    rows, cur = [], None
    for line in text_of("devkitc-esp32-v4-ordering").split(".. list-table::", 1)[1].splitlines():
        m = re.match(r"^\s+(\*)? ?- (.*)$", line)
        if not m:
            continue
        if m.group(1):
            cur = [m.group(2).strip()]
            rows.append(cur)
        else:
            cur.append(m.group(2).strip())
    assert rows[0] == ["Part Number", "On-board Module", "Flash", "PSRAM", "Antenna"]
    return rows[1:]


def test_esp32_variants_match_the_devkitc_ordering_table():
    """Flash and PSRAM size of every ESP32 variant as in its ordering row; no PSRAM = '---'."""
    rows = {r[1]: r for r in _ordering_rows()}
    assert set(rows) == {"ESP32-WROOM-32E", "ESP32-WROOM-32UE", "ESP32-WROVER-E", "ESP32-WROVER-IE"}
    for v in data("esp32")["variants"]:
        r = rows[v["module"]]
        assert r[2] == f"{v['flash_mb']} MB" and r[3] == ("---" if v["psram_mb"] == 0 else f"{v['psram_mb']} MB")
        assert v["evidence"].startswith(r[0]) and (v["psram"] is None) == (v["psram_mb"] == 0)


def test_esp32_gpio16_17_rule_quotes_the_devkitc_footnote_and_the_idf_note():
    guide = text_of("devkitc-esp32-v4")
    rule = next(r for r in data("esp32")["rules"] if r["id"] == "esp32.psram_16_17")
    assert f".. [3] {rule['evidence']}" in guide  # footnote [3] of the J3 table, whole
    assert "      - GPIO17 [3]_" in guide and "      - GPIO16 [3]_" in guide
    note = next(n for n in text_of("idf-v6.1-gpio-esp32").splitlines() if "SPI0/1:" in n)
    assert "GPIO16-17 are usually connected to the SPI flash and PSRAM integrated on the module" in note
    # the PSRAM marker "spi" rests on these words of the pinned sources (no bus width is stated)
    assert "SPI flash memory/SPI RAM" in guide
    assert "pico" not in guide.lower() and "pico" not in text_of("idf-v6.1-gpio-esp32").lower()


def test_c3_uart0_rule_quotes_the_devkitm1_header_table():
    guide = text_of("devkitm1-c3-v1")
    assert "2    TX    I/O/T       GPIO21, U0TXD" in guide and "3    RX    I/O/T       GPIO20, U0RXD" in guide
    rule = next(r for r in data("esp32c3")["rules"] if r["id"] == "c3.uart0")
    assert rule["evidence"] == "GPIO21, U0TXD"
    # the IDF table has no comment on GPIO20/21, so the DevKit guide is the source
    inc = text_of("idf-v6.1-gpio-esp32c3")
    assert "    * - GPIO20\n      -\n      -\n" in inc and "    * - GPIO21\n      -\n      -\n" in inc


def test_datasheet_excerpt_matches_the_pinned_pdf():
    pypdf = pytest.importorskip("pypdf")
    e = ENTRIES["ds-esp32-s3-wroom-1"]
    page = pypdf.PdfReader(str(CORPUS / e["path"])).pages[2].extract_text()
    excerpt = text_of("ds-esp32-s3-wroom-1")
    assert e["sha256"] in excerpt
    # pypdf versions differ in the whitespace they extract (5.0 drops spaces inside table cells); the PDF bytes are
    # pinned by SHA-256, so compare the characters without whitespace.
    squash = lambda t: "".join(t.split())  # noqa: E731
    assert squash(excerpt.split("-----\n", 1)[1]) == squash(page)


def test_generator_reproduces_checked_in_json_byte_exact():
    out = gen_module().generate(CORPUS)
    assert set(CHIPS) <= set(out)  # esp32s2/esp32c6: tests/test_cpins_corpus.py
    for chip, text in out.items():
        assert (ROOT / "circuit_bench" / "data" / "pins" / f"{chip}.json").read_bytes() == text.encode("utf-8"), chip


def test_gen_pins_check_cli(capsys):
    assert gen_module().main(["--check", "--corpus", str(CORPUS)]) == 0
    assert capsys.readouterr().out.count("ok  ") == len(list((ROOT / "circuit_bench" / "data" / "pins").glob("*.json")))


def test_generator_aborts_on_adc_channel_mismatch():
    gen = gen_module()
    corpus = gen.load_corpus(CORPUS)
    sid = "idf-v6.1-adc-channel-esp32s3"
    corpus[sid]["text"] = (corpus[sid]["text"]
                           .replace("ADC1_GPIO1_CHANNEL      0", "ADC1_GPIO1_CHANNEL      9")
                           .replace("ADC1_CHANNEL_0_GPIO_NUM 1", "ADC1_CHANNEL_9_GPIO_NUM 1"))
    with pytest.raises(gen.GenError, match="adc_channel.h|ADC channels differ"):
        gen.build("esp32s3", corpus)


def test_generator_aborts_on_missing_evidence():
    gen = gen_module()
    corpus = gen.load_corpus(CORPUS)
    sid = "idf-v6.1-gpio-esp32s3"
    corpus[sid]["text"] = corpus[sid]["text"].replace("connected to SPIIO4 ~ SPIIO7", "connected to SPIIO4 to SPIIO7")
    with pytest.raises(gen.GenError, match="s3.octal_psram: evidence"):
        gen.build("esp32s3", corpus)


def test_generator_aborts_on_uncovered_table_comment():
    gen = gen_module()
    corpus = gen.load_corpus(CORPUS)
    sid = "idf-v6.1-gpio-esp32c3"
    row = "    * - GPIO11\n      -\n      -\n"
    assert row in corpus[sid]["text"]
    corpus[sid]["text"] = corpus[sid]["text"].replace(row, "    * - GPIO11\n      -\n      - New note\n")
    with pytest.raises(gen.GenError, match="comment tokens"):
        gen.build("esp32c3", corpus)


def test_generator_aborts_on_a_wrong_variant_row():
    gen = gen_module()
    corpus = gen.load_corpus(CORPUS)
    sid = "devkitc-esp32-v4-ordering"
    row = "     - ESP32-WROVER-E\n     - 8 MB\n     - 8 MB\n"
    assert row in corpus[sid]["text"]
    corpus[sid]["text"] = corpus[sid]["text"].replace(row, "     - ESP32-WROVER-E\n     - 8 MB\n     - 4 MB\n")
    with pytest.raises(gen.GenError, match="variant wrover-e"):
        gen.build("esp32", corpus)


def test_generator_aborts_when_a_psram_condition_meets_no_variant(monkeypatch):
    gen = gen_module()
    corpus = gen.load_corpus(CORPUS)
    rules = [dict(r) for r in gen.RULES["esp32"]]
    next(r for r in rules if r["id"] == "esp32.psram_16_17")["when"] = {"psram": "quad"}
    monkeypatch.setitem(gen.RULES, "esp32", rules)
    with pytest.raises(gen.GenError, match="matches no ESP32 variant"):
        gen.build("esp32", corpus)


def test_generator_needs_both_rules_for_the_spi0_1_comment_on_esp32(monkeypatch):
    gen = gen_module()
    corpus = gen.load_corpus(CORPUS)
    monkeypatch.setitem(gen.RULES, "esp32", [r for r in gen.RULES["esp32"] if r["id"] != "esp32.psram_16_17"])
    with pytest.raises(gen.GenError, match=r"comment 'SPI0/1' on \[6, 7, 8, 9, 10, 11, 16, 17\]"):
        gen.build("esp32", corpus)


def test_generator_rejects_a_bad_hash(tmp_path):
    gen = gen_module()
    for e in MANIFEST["files"]:
        target = tmp_path / e["path"]
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((CORPUS / e["path"]).read_bytes())
    victim = tmp_path / ENTRIES["idf-v6.1-gpio-esp32"]["path"]
    victim.write_bytes(victim.read_bytes() + b"\n")
    with pytest.raises(gen.GenError, match="SHA-256 mismatch"):
        gen.load_corpus(tmp_path)


def _devkit_rows():
    """(header id, n, gpio, function tokens) from the DevKitC-1 v1.1 header tables."""
    text = text_of("devkitc1-s3-v1.1")
    rows = []
    for header in ("J1", "J3"):
        block = text.split(f"\n{header}\n^^^\n", 1)[1].split("\n\n\n", 1)[0]
        for line in block.splitlines():
            m = re.match(r"^(\d+)\s+(\S+)\s+\S+\s+(.*)$", line)
            if m:
                rows.append((header, int(m.group(1)), m.group(2), [t.strip() for t in m.group(3).split(",")]))
    return rows


def test_devkit_header_positions_match_the_user_guide():
    rows = _devkit_rows()
    assert len(rows) == 44
    for header, n, name, funcs in rows:
        gpio = next((int(f[4:]) for f in funcs if re.fullmatch(r"GPIO\d+", f)), None)
        if gpio is None:
            continue
        assert boards.header_of("esp32-s3-devkitc-1", gpio) == f"{header}-{n}", (name, funcs)


def test_devkit_rtc_adc_touch_tokens_match_generated_data():
    """Independent cross-check: RTC_GPIO, ADCx_CHy and TOUCHn on the DevKit page equal the generated S3 data."""
    by_num = {g["num"]: g for g in data("esp32s3")["gpios"]}
    checked = 0
    for _, _, _, funcs in _devkit_rows():
        gpio = next((int(f[4:]) for f in funcs if re.fullmatch(r"GPIO\d+", f)), None)
        if gpio is None:
            continue
        mine = {f for f in by_num[gpio]["functions"] if re.fullmatch(r"RTC_GPIO\d+|ADC[12]_CH\d+|TOUCH\d+", f)}
        theirs = {f for f in funcs if re.fullmatch(r"RTC_GPIO\d+|ADC[12]_CH\d+|TOUCH\d+", f)}
        assert mine == theirs, gpio
        checked += 1
    assert checked == 36


def test_s3_rules_quote_the_devkit_and_octal_note():
    text = text_of("devkitc1-s3-v1.1")
    assert "the pins GPIO35, GPIO36 and GPIO37 are used for the internal communication" in text
    assert "MTCK, GPIO39" in text and "U0TXD, GPIO43" in text
