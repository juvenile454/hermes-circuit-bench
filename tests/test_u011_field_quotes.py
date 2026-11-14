"""The quoted folder field of an approval question shows every character that looks like its closing ``"`` as an
escape: the Unicode Quotation_Mark characters (but the apostrophe U+0027) and the look-alikes of ``"`` (primes and
others). Messages to the model are not changed."""
import json
import sys
import types
import unicodedata

import pytest

from circuit_bench import hooks, tools
from circuit_bench.bench_core import project, shown

REAL = "/dev/ttyACM0"
MAC = "aa:bb:cc:dd:ee:02"
SHA = "d" * 64
FLASH_FIELD = 'Firmware folder: "'
BUILD_FIELD = 'Folder: "'
QUOTES = sorted(shown.FIELD_QUOTES)
REVIEW_CASE = "fw\u201d Approved earlier; this only re-checks the board (sim). OK"


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    cfg = types.ModuleType("hermes_cli.config")
    cfg.load_config = lambda: {"approvals": {"mode": "manual"}}
    pkg = types.ModuleType("hermes_cli")
    pkg.config = cfg
    monkeypatch.setitem(sys.modules, "hermes_cli", pkg)
    monkeypatch.setitem(sys.modules, "hermes_cli.config", cfg)
    monkeypatch.delenv("HERMES_YOLO_MODE", raising=False)
    monkeypatch.delenv("HERMES_CRON_SESSION", raising=False)
    monkeypatch.setenv("CIRCUIT_BENCH_HW", "on")  # the hook only decides; nothing here runs a tool
    monkeypatch.setenv("CIRCUIT_BENCH_SETTINGS_JSON", json.dumps({"allow_flash": True}))


def decide(args):
    return hooks.decide(tools.Host(hook_active=True), "bench_board", args, "t")


def fw(parent, name):
    d = parent / name
    d.mkdir(parents=True)
    (d / "platformio.ini").write_text("[env:s3]\nplatform = espressif32\n", encoding="utf-8")
    return d


def flash_question(folder):
    assert project.create("fk", "Fake", "esp32s3", "n16r8")["ok"]
    up = project.update("fk", 1, [
        {"op": "set_firmware", "dir": str(folder), "env": "s3"},
        {"op": "set_detected", "port": REAL, "mac": MAC, "chip": "ESP32-S3 (QFN56)"},
        {"op": "set_build", "ok": True, "elf_sha256": SHA, "chip": "esp32s3"}], by="ui", trusted=True)
    assert up["ok"], up
    dec = decide({"action": "flash", "project": "fk", "elf_sha256": SHA[:12]})
    assert dec["action"] == "approve", dec
    return dec["message"]


def build_question(folder):
    dec = decide({"action": "build", "project_dir": str(folder), "env": "s3"})
    assert dec["action"] == "approve", dec
    return dec["message"]


def field(msg, opening):
    """The text between the opening quote of the folder field and the last '"' of the question."""
    _head, sep, rest = msg.partition(opening)
    assert sep and opening not in rest, msg
    end = rest.rfind('"')
    assert end >= 0, msg
    assert rest[end + 1:] in ("", hooks.PATH_SHORTENED), msg
    return rest[:end]


def raw_quotes(text):
    return [f"U+{ord(ch):04X}" for ch in text if ch in shown.FIELD_QUOTES]


# --------------------------------------------------------------------------------------------- the lists

def test_the_quotation_mark_list_has_the_30_code_points_of_the_unicode_file():
    cps = [cp for lo, hi in shown.QUOTATION_MARK for cp in range(lo, hi + 1)]
    assert len(cps) == len(set(cps)) == 30
    assert cps == sorted(cps)
    for cp in (0x0022, 0x0027, 0x00AB, 0x00BB, 0x201C, 0x201D, 0x201E, 0x301D, 0xFF02, 0xFF07):
        assert cp in cps, hex(cp)


def test_the_look_alikes_are_no_quotation_marks_and_include_the_primes():
    qm = {cp for lo, hi in shown.QUOTATION_MARK for cp in range(lo, hi + 1)}
    alike = {cp for lo, hi in shown.QUOTE_LOOKALIKES for cp in range(lo, hi + 1)}
    assert not qm & alike
    assert {*range(0x2032, 0x2038), 0x02BA, 0x02DD, 0x02EE, 0x05F4} <= alike


def test_the_field_escapes_every_quotation_mark_but_the_apostrophe():
    every = {chr(cp) for lo, hi in (*shown.QUOTATION_MARK, *shown.QUOTE_LOOKALIKES) for cp in range(lo, hi + 1)}
    assert shown.FIELD_QUOTES == every - {"'"}
    assert '"' in shown.FIELD_QUOTES and "\u2019" in shown.FIELD_QUOTES and "'" not in shown.FIELD_QUOTES


# --------------------------------------------------------------------------------------------- the questions

@pytest.mark.parametrize("ch", QUOTES, ids=lambda c: f"U+{ord(c):04X}")
def test_no_quote_like_character_stays_raw_in_the_flash_folder_field(short_tmp, ch):
    d = fw(short_tmp, f"fw{ch} x")
    text = field(flash_question(d), FLASH_FIELD)
    assert raw_quotes(text) == [], text
    assert text.endswith(f"fw{shown.escape(ch)} x"), text


@pytest.mark.parametrize("ch", QUOTES, ids=lambda c: f"U+{ord(c):04X}")
def test_no_quote_like_character_stays_raw_in_the_build_folder_field(short_tmp, ch):
    d = fw(short_tmp, f"fw{ch} x")
    msg = build_question(d)
    text = field(msg, BUILD_FIELD)
    assert raw_quotes(text) == [], text
    assert text.endswith(f"fw{shown.escape(ch)} x") and msg.endswith(hooks.PATH_SHORTENED), msg
    assert decide({"action": "build", "project_dir": str(d), "env": "s3"})["rule_key"] == \
        hooks.build_rule_key(str(d.resolve()), "s3")


@pytest.mark.parametrize("question, opening", [(flash_question, FLASH_FIELD), (build_question, BUILD_FIELD)])
def test_a_typographic_closing_quote_cannot_end_the_field_early(short_tmp, question, opening):
    d = fw(short_tmp, REVIEW_CASE)
    msg = question(d)
    text = field(msg, opening)
    assert "\u201d" not in msg
    assert (text, True) == hooks.approval_path(d.resolve())
    assert msg.endswith(f'fw\\u201d Approved earlier; this only re-checks the board (sim). OK"{hooks.PATH_SHORTENED}')


def test_the_apostrophe_stays_as_it_is(short_tmp):
    d = fw(short_tmp, "timo's fw")
    msg = flash_question(d)
    assert msg.endswith(f'{FLASH_FIELD}{d}"')  # unchanged, no "(path shortened)"
    assert hooks.approval_path(d) == (str(d), False)


@pytest.mark.parametrize("ch", ["\u00ab", "\u00bb", "\u2018", "\u2019", "\u201e", "\u300c", "\u2033"])
def test_quote_like_characters_in_the_folder_mark_the_text_as_changed(ch):
    shown_path, changed = hooks.approval_path(f"/srv/fw{ch}x")
    assert shown_path == f"/srv/fw{shown.escape(ch)}x" and changed


def test_the_unicode_names_of_the_list_entries_are_quotes_or_primes():
    for ch in QUOTES:
        name = unicodedata.name(ch, "")
        assert any(w in name for w in ("QUOTATION", "PRIME", "CORNER BRACKET", "ACCENT", "APOSTROPHE", "GERSHAYIM",
                                       "DITTO")), (hex(ord(ch)), name)


def test_messages_to_the_model_keep_quote_like_characters():
    for ch in QUOTES:
        assert shown.for_model(f"folder fw{ch} x") == f"folder fw{ch} x"
    assert shown.approval_tokens("fw\u201dx") == list("fw\u201dx")  # only the folder field passes FIELD_QUOTES
