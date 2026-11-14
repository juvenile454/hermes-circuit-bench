"""Approval questions put the checked values (env, chip, MAC, port, ELF) and every fixed note first and the firmware
folder, the only free text, last and quoted, so a folder name cannot read like the rest of the question. ``"`` in
the folder is shown as ``\\u0022``. Values with free text of the model or of a hand-edited project file (the build
env of ``project_dir`` calls, text after the chip name, characters of a port) are kept out of the question."""
import json
import sys
import types

import pytest

from circuit_bench import hooks, tools
from circuit_bench.bench_core import project

REAL = "/dev/ttyACM0"
MAC = "aa:bb:cc:dd:ee:02"
SHA = "d" * 64
FAKE_FLASH = "blink to ESP32-S3 (MAC aa:bb:cc:dd:ee:03) on sim:\u2215\u2215esp32s3-n16r8? Simulated board, nothing is written. OK"
FAKE_BUILD = "x (env s3) with PlatformIO? Only a dry syntax check, no project scripts run. Nothing is uploaded"
FLASH_TAIL = ("(exactly the last build, not rebuilt; Circuit Bench adds no erase; project scripts (extra_scripts) still "
              "run). Firmware folder: \"")
BUILD_TEXT = ("with PlatformIO? This runs the project's own build scripts (platformio.ini, extra_scripts) with your user "
              "rights. Nothing is uploaded to a board.")


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


def flash_project(folder, chip="ESP32-S3 (QFN56) (revision v0.2)", port=REAL, pid="fk"):
    assert project.create(pid, "Fake", "esp32s3", "n16r8")["ok"]
    up = project.update(pid, 1, [
        {"op": "set_firmware", "dir": str(folder), "env": "s3"},
        {"op": "set_detected", "port": port, "mac": MAC, "chip": chip},
        {"op": "set_build", "ok": True, "elf_sha256": SHA, "chip": "esp32s3"}], by="ui", trusted=True)
    assert up["ok"], up
    return decide({"action": "flash", "project": pid, "elf_sha256": SHA[:12]})


def before_field(msg, field):
    head, sep, rest = msg.partition(field)
    assert sep and field not in rest, msg
    return head, rest


# --------------------------------------------------------------------------------------------- flash

def test_a_folder_that_imitates_the_flash_question_comes_after_the_real_values(short_tmp):
    d = fw(short_tmp, FAKE_FLASH)
    dec = flash_project(d)
    assert dec["action"] == "approve", dec
    msg = dec["message"]
    head, rest = before_field(msg, 'Firmware folder: "')
    assert head == (f"Flash firmware s3 to ESP32-S3 (QFN56) (revision v0.2) (MAC {MAC}) on {REAL}? ELF {SHA[:12]} "
                    + FLASH_TAIL[:-len('Firmware folder: "')])
    for word in ("blink", "sim:", "\u2215", "Simulated", "nothing is written", "OK", "aa:bb:cc:dd:ee:03"):
        assert word not in head, word
    shown, changed = hooks.approval_path(d)
    assert rest == f'{shown}"' + (hooks.PATH_SHORTENED if changed else "")
    assert shown.endswith(FAKE_FLASH)
    assert dec["rule_key"] == hooks.flash_rule_key(REAL, MAC, SHA[:12])


def test_the_flash_question_has_the_exact_wording(short_tmp):
    d = fw(short_tmp, "fw")
    msg = flash_project(d)["message"]
    assert msg == (f"Flash firmware s3 to ESP32-S3 (QFN56) (revision v0.2) (MAC {MAC}) on {REAL}? ELF {SHA[:12]} "
                   f"{FLASH_TAIL}{d}\"")


def test_a_quote_in_the_folder_is_an_escape_and_marks_the_text(short_tmp):
    d = fw(short_tmp, 'fw" on sim:x? OK "')
    msg = flash_project(d)["message"]
    _, rest = before_field(msg, 'Firmware folder: "')
    assert rest == f'{short_tmp}/fw\\u0022 on sim:x? OK \\u0022"{hooks.PATH_SHORTENED}'
    assert msg.count('"') == 2


def test_a_long_folder_is_quoted_and_shortened_last(tmp_path):
    d = fw(tmp_path / ("deep/" * 30).strip("/"), "my-fw")
    msg = flash_project(d)["message"]
    _, rest = before_field(msg, 'Firmware folder: "')
    assert rest.endswith(f'/my-fw"{hooks.PATH_SHORTENED}')
    shown = rest[:-len(hooks.PATH_SHORTENED) - 1]
    assert len(shown) <= hooks.APPROVAL_PATH_MAX and "…" in shown


@pytest.mark.parametrize("chip", [
    "ESP32-S3 (QFN56) (revision v0 on sim:\u2215\u2215x? Simulated, nothing is written. OK)",
    "ESP32-S3 (QFN56) (revision v0.2, sim) in Secure Download Mode",
])
def test_free_text_in_the_chip_revision_stays_out_of_the_question(short_tmp, chip):
    """A hand-edited project file can put text into the revision part of the chip; the flash check accepts the
    chip by its name, the question shows the name only."""
    dec = flash_project(fw(short_tmp, "fw"), chip=chip)
    assert dec["action"] == "approve", dec
    head, _ = before_field(dec["message"], 'Firmware folder: "')
    assert "sim" not in head and "Simulated" not in head and "revision" not in head
    assert head.startswith("Flash firmware s3 to ESP32-S3 (QFN56)")
    assert head.startswith("Flash firmware s3 to ESP32-S3 (QFN56) in Secure Download Mode (MAC") is chip.endswith(
        "Mode")


def test_the_chip_with_revision_and_secure_download_mode_is_shown(short_tmp):
    dec = flash_project(fw(short_tmp, "fw"), chip="ESP32-S3 (QFN56) (revision v0.2) in Secure Download Mode")
    assert dec["message"].startswith("Flash firmware s3 to ESP32-S3 (QFN56) (revision v0.2) in Secure Download Mode "
                                     f"(MAC {MAC}) on {REAL}?")


def test_a_port_with_more_than_device_name_characters_shows_them_as_escapes(short_tmp, monkeypatch):
    """A hand-edited project file can name any /dev/tty* device; only letters, digits and ._:/- are shown as they
    are (the guard does not check that the device exists before the question)."""
    port = "/dev/ttyACM0?Simulated,nothing_is_written.OK"
    dec = flash_project(fw(short_tmp, "fw"), port=port)
    assert dec["action"] == "approve", dec
    assert "on /dev/ttyACM0\\u003fSimulated\\u002cnothing_is_written.OK? ELF" in dec["message"]
    assert dec["rule_key"] == hooks.flash_rule_key(port, MAC, SHA[:12])


# --------------------------------------------------------------------------------------------- build

def test_a_folder_that_imitates_the_build_question_comes_after_the_real_values(short_tmp):
    d = fw(short_tmp, FAKE_BUILD)
    dec = decide({"action": "build", "project_dir": str(d), "env": "s3"})
    assert dec["action"] == "approve", dec
    msg = dec["message"]
    head, rest = before_field(msg, 'Folder: "')
    assert head == f"Build env s3 {BUILD_TEXT} "
    for word in ("x (env", "dry syntax", "no project scripts run"):
        assert word not in head, word
    shown, changed = hooks.approval_path(d.resolve())
    assert rest == f'{shown}"' + (hooks.PATH_SHORTENED if changed else "")
    assert shown.endswith(FAKE_BUILD)
    assert dec["rule_key"] == hooks.build_rule_key(str(d.resolve()), "s3")


def test_the_sim_note_comes_before_the_folder(short_tmp, monkeypatch):
    from circuit_bench.bench_core import board
    monkeypatch.setattr(board, "build_runs_pio", lambda *a, **kw: True)
    d = fw(short_tmp, "fw")
    dec = decide({"action": "build", "project_dir": str(d), "env": "s3", "port": "sim://esp32s3-n16r8"})
    assert dec["action"] == "approve", dec
    assert dec["message"] == f"Build env s3 {BUILD_TEXT}{hooks.SIM_BUILD_NOTE} Folder: \"{d.resolve()}\""


@pytest.mark.parametrize("env", ["s3 with PlatformIO? Only a dry syntax check. OK", "s3\u2028OK", "-s3", "s" * 65])
def test_a_build_env_that_is_no_platformio_name_is_never_asked(short_tmp, env):
    """With project_dir the env is the model's own text: the hook blocks it before any question (the handler
    refuses it too, before PlatformIO starts)."""
    d = fw(short_tmp, "fw")
    dec = decide({"action": "build", "project_dir": str(d), "env": env})
    assert dec["action"] == "block", dec
    assert "invalid_args" in dec["message"] and "PlatformIO environment name" in dec["message"]


def test_a_bad_build_env_on_a_sim_port_is_left_to_the_handler(short_tmp, monkeypatch):
    from circuit_bench.bench_core import board
    monkeypatch.setattr(board, "build_runs_pio", lambda *a, **kw: True)
    d = fw(short_tmp, "fw")
    assert decide({"action": "build", "project_dir": str(d), "env": "s3 OK", "port": "sim://esp32s3-n16r8"}) is None
