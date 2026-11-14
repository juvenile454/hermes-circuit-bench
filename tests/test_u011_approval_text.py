"""Paths in approval texts (flash, build): control characters, line breaks and Unicode direction marks are shown as
``\\uXXXX``; a long path is shortened in the middle to at most 120 characters; the text then ends with
``(path shortened)``. The ``rule_key`` still uses the full path."""
import json
import sys
import types

import pytest

from circuit_bench import hooks, tools
from circuit_bench.bench_core import project

REAL = "/dev/ttyCB0"
SHA = "b" * 64
MAC = "aa:bb:cc:dd:ee:ff"
SUFFIX = "(path shortened)"
MAX = 120


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


def ready(fw_dir):
    assert project.create("laser-trigger", "Laser trigger", "esp32s3", "n16r8")["ok"]
    env = project.update("laser-trigger", 1, [
        {"op": "set_detected", "port": REAL, "mac": MAC, "chip": "ESP32-S3 (QFN56)"},
        {"op": "set_firmware", "dir": str(fw_dir), "env": "s3"},
        {"op": "set_build", "ok": True, "elf_sha256": SHA}], by="ui", trusted=True)
    assert env["ok"], env
    return env["result"]["project"]


def raw_controls(text):
    return [c for c in text if ord(c) < 0x20 or 0x7f <= ord(c) < 0xa0 or c in "\u2028\u2029\u200e\u200f\u061c"
            or 0x202a <= ord(c) <= 0x202e or 0x2066 <= ord(c) <= 0x2069]


# --------------------------------------------------------------------------------------------- the function

def test_plain_short_path_is_unchanged():
    assert hooks.approval_path("/home/user/fw") == ("/home/user/fw", False)


@pytest.mark.parametrize(("raw", "shown"), [
    ("/w/a\nb", "/w/a\\u000ab"),
    ("/w/a\rb", "/w/a\\u000db"),
    ("/w/a\tb", "/w/a\\u0009b"),
    ("/w/a\x1bb", "/w/a\\u001bb"),
    ("/w/a\x7fb", "/w/a\\u007fb"),
    ("/w/a\x85b", "/w/a\\u0085b"),
    ("/w/a\u2028b", "/w/a\\u2028b"),
    ("/w/a\u202eb", "/w/a\\u202eb"),
    ("/w/a\u2066b\u2069", "/w/a\\u2066b\\u2069"),
    ("/w/a\u200fb", "/w/a\\u200fb"),
    ("/w/a\u061cb", "/w/a\\u061cb"),
])
def test_control_line_break_and_direction_characters_are_visible(raw, shown):
    text, changed = hooks.approval_path(raw)
    assert text == shown and changed is True
    assert raw_controls(text) == []


def test_long_path_is_shortened_in_the_middle_and_keeps_the_last_part():
    path = "/home/user/" + "/".join(f"level{i:02d}" for i in range(30)) + "/my-firmware"
    text, changed = hooks.approval_path(path)
    assert changed is True and len(text) <= MAX
    assert text.startswith("/home/user/level00")
    assert text.endswith("/my-firmware") and "…" in text
    assert "level15" not in text


def test_a_long_last_part_is_shortened_in_the_middle_too():
    last = "x" * 100 + "y" * 100
    text, changed = hooks.approval_path("/home/user/" + "d/" * 40 + last)
    assert changed is True and len(text) <= MAX
    assert text.startswith("/home/user/d/")
    name = text.rsplit("/", 1)[1]
    assert name.startswith("x" * 30) and name.endswith("y" * 30) and "…" in name


@pytest.mark.parametrize("length", [MAX, MAX + 1, MAX + 2, 300])
def test_the_shown_path_is_never_longer_than_the_limit(length):
    for path in ("/" + "a" * (length - 1), "/home/user/" + "b" * (length - 11),
                 "/home/user/" + "/".join(["c" * 9] * 40)[: length - 11], "/" + "\u200b" * (length - 1),
                 "/w/" + "\u202e" * (length - 6) + "/fw", "/" + "e\u2028" * (length // 2)):
        text, changed = hooks.approval_path(path)
        assert len(text) <= MAX, (len(path), text)
        assert changed is (len(path) > MAX or any(len(t) > 1 for t in hooks._visible(path)))


def test_exactly_the_limit_plus_one_is_shortened():
    path = "/" + "a" * MAX
    text, changed = hooks.approval_path(path)
    assert changed is True and len(text) <= MAX and "…" in text
    assert text.startswith("/" + "a" * 50) and text.endswith("a" * 50)


def test_a_single_part_of_300_characters_keeps_start_and_end():
    name = "start-" + "m" * 288 + "-end00"
    text, changed = hooks.approval_path("/" + name)
    assert changed is True and len(text) <= MAX and text.count("…") == 1
    assert text.startswith("/start-mmm") and text.endswith("mmm-end00")


def test_a_path_of_escapes_only_is_cut_between_whole_escapes():
    text, changed = hooks.approval_path("/" + "\u200b" * 300)
    assert changed is True and len(text) <= MAX
    head, tail = text.split("…")
    assert head == "/" + "\\u200b" * ((len(head) - 1) // 6)
    assert tail == "\\u200b" * (len(tail) // 6) and tail


def test_long_folders_in_front_of_a_long_last_part_keep_their_start():
    path = "/home/user/" + "/".join(f"level{i:02d}" for i in range(30)) + "/" + "n" * 200
    text, _ = hooks.approval_path(path)
    assert len(text) <= MAX and text.startswith("/home/user/level00")
    assert text.count("…") == 2 and text.endswith("n" * 30)


def test_the_rule_key_uses_the_full_path_of_a_long_last_part(tmp_path):
    d = fw(tmp_path, "n" * 200)
    dec = decide({"action": "build", "project_dir": str(d), "env": "s3"})
    assert dec["action"] == "approve" and dec["message"].endswith(SUFFIX)
    assert dec["rule_key"] == hooks.build_rule_key(str(d.resolve()), "s3")
    assert "n" * 200 not in dec["message"]


def test_escapes_are_never_cut_in_half():
    path = "/w/" + "\u202e" * 60 + "/fw"
    text, changed = hooks.approval_path(path)
    assert changed is True and text.endswith("/fw")
    head = text.split("…")[0]
    assert head == "/w/" + "\\u202e" * ((len(head) - 3) // 6)


def test_exactly_the_limit_is_not_shortened():
    path = "/" + "a" * (MAX - 1)
    assert hooks.approval_path(path) == (path, False)


# --------------------------------------------------------------------------------------------- flash and build texts

def test_flash_text_shows_direction_characters_and_says_so(tmp_path):
    """The project refuses control characters in its firmware folder; direction marks still get through to here."""
    d = fw(tmp_path, "fw\u202eevil\u2066")
    ready(d)
    dec = decide({"action": "flash", "project": "laser-trigger", "elf_sha256": SHA})
    assert dec["action"] == "approve"
    msg = dec["message"]
    assert raw_controls(msg) == []
    assert "fw\\u202eevil\\u2066" in msg
    assert msg.endswith(SUFFIX)
    assert dec["rule_key"] == hooks.flash_rule_key(REAL, MAC, SHA)


def test_flash_text_shortens_a_long_folder(tmp_path):
    d = fw(tmp_path / ("deep/" * 30).strip("/"), "my-fw")
    ready(d)
    msg = decide({"action": "flash", "project": "laser-trigger", "elf_sha256": SHA})["message"]
    shown = msg.split(' Firmware folder: "', 1)[1].removesuffix(" " + SUFFIX).removesuffix('"')
    assert len(shown) <= MAX and shown.endswith("/my-fw") and "…" in shown
    assert msg.endswith(SUFFIX)


def test_flash_text_with_a_plain_folder_has_no_suffix(short_tmp):
    d = fw(short_tmp, "fw")
    ready(d)
    msg = decide({"action": "flash", "project": "laser-trigger", "elf_sha256": SHA})["message"]
    assert msg.endswith(f' Firmware folder: "{d}"') and SUFFIX not in msg


def test_build_text_shortens_and_escapes_but_the_rule_key_uses_the_full_path(tmp_path):
    d = fw(tmp_path / ("deep/" * 30).strip("/"), "fw\u202e\nx")
    dec = decide({"action": "build", "project_dir": str(d), "env": "s3"})
    assert dec["action"] == "approve"
    msg = dec["message"]
    assert raw_controls(msg) == []
    assert msg.startswith("Build env s3 with PlatformIO?")
    shown = msg.split(' Folder: "', 1)[1].removesuffix(" " + SUFFIX).removesuffix('"')
    assert len(shown) <= MAX and shown.endswith("/fw\\u202e\\u000ax") and "…" in shown
    assert msg.endswith(SUFFIX)
    assert dec["rule_key"] == hooks.build_rule_key(str(d.resolve()), "s3")


def test_build_text_with_a_plain_folder_is_unchanged(short_tmp):
    d = fw(short_tmp, "fw")
    msg = decide({"action": "build", "project_dir": str(d), "env": "s3"})["message"]
    assert msg.startswith("Build env s3 with PlatformIO?") and msg.endswith(f' Folder: "{d.resolve()}"')
    assert SUFFIX not in msg


# --------------------------------------------------------------------------------------------- spaces and invisible letters

INVISIBLE = ["\u00a0", *(chr(c) for c in range(0x2000, 0x200b)), "\u202f", "\u205f", "\u3000",
             "\u034f", "\u115f", "\u1160", "\u3164", "\uffa0", "\u2800"]


def esc(ch):
    return f"\\u{ord(ch):04x}"


@pytest.mark.parametrize("ch", INVISIBLE, ids=[f"U+{ord(c):04X}" for c in INVISIBLE])
def test_space_variants_and_invisible_letters_are_visible(ch):
    text, changed = hooks.approval_path(f"/w/fw{ch}")
    assert text == f"/w/fw{esc(ch)}" and changed is True
    assert hooks._shown(f"s3{ch}") == f"s3{esc(ch)}"  # env, chip, MAC and port go through _shown
    assert ch not in text


def test_the_normal_space_stays():
    assert hooks.approval_path("/w/my fw") == ("/w/my fw", False)
    assert hooks._shown("ESP32-S3 (QFN56)") == "ESP32-S3 (QFN56)"


@pytest.mark.parametrize("ch", INVISIBLE, ids=[f"U+{ord(c):04X}" for c in INVISIBLE])
def test_flash_text_shows_them_in_the_folder(short_tmp, ch):
    """A chip text with such a character is not a known chip: that flash is blocked (chip_mismatch) before any
    question, so only the folder can carry one into a flash question."""
    d = fw(short_tmp, f"my{ch}fw")
    ready(d)
    dec = decide({"action": "flash", "project": "laser-trigger", "elf_sha256": SHA})
    assert dec["action"] == "approve", dec
    msg = dec["message"]
    assert ch not in msg
    assert msg.startswith(f"Flash firmware s3 to ESP32-S3 (QFN56) (MAC {MAC}) on {REAL}?")
    assert f'Firmware folder: "{short_tmp}/my{esc(ch)}fw"' in msg
    assert msg.endswith(SUFFIX)
    assert dec["rule_key"] == hooks.flash_rule_key(REAL, MAC, SHA)


@pytest.mark.parametrize("ch", INVISIBLE, ids=[f"U+{ord(c):04X}" for c in INVISIBLE])
def test_build_text_shows_them_and_the_rule_key_uses_the_full_path(short_tmp, ch):
    d = fw(short_tmp, f"my fw{ch}x")
    dec = decide({"action": "build", "project_dir": str(d), "env": "s3"})
    assert dec["action"] == "approve", dec
    assert ch not in dec["message"]
    assert dec["message"].startswith("Build env s3 with PlatformIO?")
    assert f'Folder: "{short_tmp}/my fw{esc(ch)}x"' in dec["message"]
    assert dec["message"].endswith(SUFFIX)
    assert dec["rule_key"] == hooks.build_rule_key(str(d.resolve()), "s3")
