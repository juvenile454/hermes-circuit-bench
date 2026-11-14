"""Every Unicode Default_Ignorable_Code_Point (variation selectors, Khmer and Mongolian invisible letters, tag
characters, ...) is shown as ``\\uXXXX`` in approval texts: two folders that differ only in such a character give
different questions. The rule key keeps using the full path."""
import json
import sys
import types

import pytest

from circuit_bench import hooks, tools
from circuit_bench.bench_core import project

REAL = "/dev/ttyCB0"
SHA = "c" * 64
MAC = "aa:bb:cc:dd:ee:01"

# one character of each range of the property list, the first and the last of the larger ranges, and reserved ones
SAMPLES = ["\u00ad", "\u034f", "\u061c", "\u115f", "\u17b4", "\u17b5", "\u180b", "\u180d", "\u180e", "\u180f",
           "\u200b", "\u200d", "\u2060", "\u2064", "\u2065", "\u206f", "\u3164", "\ufe00", "\ufe0f", "\ufeff",
           "\uffa0", "\ufff0", "\ufff8", "\U0001bca0", "\U0001d173", "\U0001d17a", "\U000e0000", "\U000e0001",
           "\U000e0020", "\U000e007f", "\U000e0100", "\U000e01ef", "\U000e0fff"]
# neighbours outside the property: they stay as they are
NOT_IGNORABLE = ["\u17b3", "\u17b6", "\u180a", "\u1810", "\u2028", "\ufe10", "\ufff9", "\U000e1000", "\u00ae"]


def esc(ch):
    return f"\\u{ord(ch):04x}" if ord(ch) <= 0xFFFF else f"\\U{ord(ch):08x}"


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
    cb = hooks.make_pre_tool_call(tools.Host(hook_active=True))
    return cb(tool_name="bench_board", args=args, task_id="t", session_id="s", tool_call_id="c")


def fw(parent, name):
    d = parent / name
    d.mkdir(parents=True)
    (d / "platformio.ini").write_text("[env:s3]\nplatform = espressif32\n", encoding="utf-8")
    return d


def flash_question(pid, folder):
    assert project.create(pid, "Hidden", "esp32s3", "n16r8")["ok"]
    env = project.update(pid, 1, [
        {"op": "set_detected", "port": REAL, "mac": MAC, "chip": "ESP32-S3 (QFN56)"},
        {"op": "set_firmware", "dir": str(folder), "env": "s3"},
        {"op": "set_build", "ok": True, "elf_sha256": SHA}], by="ui", trusted=True)
    assert env["ok"], env
    dec = decide({"action": "flash", "project": pid, "elf_sha256": SHA})
    assert dec["action"] == "approve", dec
    return dec


@pytest.mark.parametrize("ch", SAMPLES, ids=[f"U+{ord(c):04X}" for c in SAMPLES])
def test_default_ignorable_characters_are_visible_in_a_path(ch):
    from circuit_bench.bench_core import shown
    assert shown.is_default_ignorable(ch)
    text, changed = hooks.approval_path(f"/w/fw{ch}x")
    assert text == f"/w/fw{esc(ch)}x" and changed is True
    assert hooks._shown(f"s3{ch}") == f"s3{esc(ch)}"


@pytest.mark.parametrize("ch", NOT_IGNORABLE, ids=[f"U+{ord(c):04X}" for c in NOT_IGNORABLE])
def test_neighbours_of_the_ranges_are_no_default_ignorables(ch):
    from circuit_bench.bench_core import shown
    assert not shown.is_default_ignorable(ch)


def test_the_ranges_are_sorted_and_do_not_overlap():
    from circuit_bench.bench_core import shown
    ranges = shown.DEFAULT_IGNORABLE
    assert all(lo <= hi for lo, hi in ranges)
    assert all(a[1] < b[0] for a, b in zip(ranges, ranges[1:], strict=False))
    assert sum(hi - lo + 1 for lo, hi in ranges) == 4174  # the code point count of the Unicode 18.0.0 list


@pytest.mark.parametrize("ch", ["\ufe0f", "\U000e0100", "\u17b4", "\u180b", "\u180f"],
                         ids=["U+FE0F", "U+E0100", "U+17B4", "U+180B", "U+180F"])
def test_two_folders_that_differ_only_in_such_a_character_give_different_build_questions(short_tmp, ch):
    plain = fw(short_tmp, "blink")
    marked = fw(short_tmp, f"blink{ch}")
    a = decide({"action": "build", "project_dir": str(plain), "env": "s3"})
    b = decide({"action": "build", "project_dir": str(marked), "env": "s3"})
    assert a["action"] == b["action"] == "approve"
    assert a["message"] != b["message"]
    assert ch not in b["message"] and esc(ch) in b["message"]
    assert b["rule_key"] == hooks.build_rule_key(str(marked.resolve()), "s3") != a["rule_key"]


@pytest.mark.parametrize("ch", ["\ufe0f", "\U000e0100", "\u17b5", "\u180d"], ids=["U+FE0F", "U+E0100", "U+17B5",
                                                                                 "U+180D"])
def test_two_folders_that_differ_only_in_such_a_character_give_different_flash_questions(short_tmp, ch):
    a = flash_question("plain", fw(short_tmp, "blink"))
    b = flash_question("marked", fw(short_tmp, f"blink{ch}"))
    assert a["message"] != b["message"]
    assert ch not in b["message"] and esc(ch) in b["message"]
