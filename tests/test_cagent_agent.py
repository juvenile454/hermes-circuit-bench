"""Chip lists from the register, the chip refusal codes in tools, routes and hook.

Tests that need the pin/board data of the newer chips or the build refusals skip themselves while those are
missing and otherwise run unchanged.
"""
import importlib
import inspect
import json
import re
import sys
import types
from pathlib import Path

import pytest
import test_api_support as sup
from test_api_support import *  # noqa: F403

from circuit_bench import hooks, schemas, tools
from circuit_bench.bench_core import board, chips, contracts, guard, project

ROOT = Path(__file__).resolve().parent.parent
PKG = ROOT / "circuit_bench"
DATA = PKG / "data"
GUARDED = [PKG / "tools.py", PKG / "schemas.py", *sorted((PKG / "dashboard" / "routes").glob("*.py"))]
REAL = "/dev/ttyCB0"  # never exists


def _has(kind: str, name: str) -> bool:
    return (DATA / kind / f"{name}.json").is_file()


def need(*items: tuple[str, str]):
    missing = [f"data/{k}/{n}.json" for k, n in items if not _has(k, n)]
    return pytest.mark.skipif(bool(missing), reason=f"board/chip data missing: {', '.join(missing)}")


def flash_refusals_merged() -> bool:
    """True when board.build refuses old platforms and wrong chips before pio starts."""
    return "platform_too_old" in inspect.getsource(board)


@pytest.fixture(autouse=True)
def _isolation(monkeypatch):
    import circuit_bench.bench_core as core
    monkeypatch.setattr(board, "_comports", lambda: pytest.fail("test read the real serial port list"))
    monkeypatch.delattr(core, "sim", raising=False)
    monkeypatch.setitem(sys.modules, "circuit_bench.bench_core.sim", None)
    cfg = types.ModuleType("hermes_cli.config")
    cfg.load_config = lambda: {"approvals": {"mode": "manual"}}
    pkg = types.ModuleType("hermes_cli")
    pkg.config = cfg
    monkeypatch.setitem(sys.modules, "hermes_cli", pkg)
    monkeypatch.setitem(sys.modules, "hermes_cli.config", cfg)
    monkeypatch.delenv("HERMES_YOLO_MODE", raising=False)
    monkeypatch.delenv("HERMES_CRON_SESSION", raising=False)


@pytest.fixture
def host():
    return tools.Host(hook_active=True)


def call(host, name, **args):
    out = tools.make_handlers(host)[name](args)
    env = json.loads(out)
    assert contracts.validate_envelope(env) == [], env
    assert len(out.encode("utf-8")) <= tools.MAX_BYTES
    return env


# --------------------------------------------------------------------------------------------- literal guard

def _chip_literal(text: str) -> list[str]:
    ids = "|".join(sorted(map(re.escape, chips.ids()), key=len, reverse=True))
    # a chip id as its own token; board ids (esp32-s3-devkitc-1), sim ports (sim://esp32s3-n16r8) and toolchain
    # prefixes (xtensa-esp32s3-elf) are not chip lists
    return re.findall(rf"(?<![\w\-/])(?:{ids})(?![\w\-])", text)


def test_guard_pattern_finds_literals():
    assert _chip_literal('raise _bad(action, "give chip (esp32, esp32s3, esp32c3) or project")') == \
        ["esp32", "esp32s3", "esp32c3"]
    assert _chip_literal('_s("board id, e.g. esp32-s3-devkitc-1") "sim://esp32s3-n16r8" "xtensa-esp32s3-elf"') == []


@pytest.mark.parametrize("path", GUARDED, ids=lambda p: p.name)
def test_no_chip_id_literal(path):
    """Chip lists come from bench_core.chips, never from literals."""
    hits = [(n, line.strip()) for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
            if _chip_literal(line)]
    assert hits == []


def test_schema_chip_descriptions_come_from_the_register():
    want = chips.ids_text()
    for schema in (schemas.PROJECT, schemas.PINS, schemas.CRASH):
        assert want in schema["parameters"]["properties"]["chip"]["description"], schema["name"]
    assert len(json.dumps(list(schemas.ALL))) <= 10000  # budget: tests/test_m0_api_schemas.py


def test_board_description_names_the_new_refusals():
    text = schemas.BOARD["description"]
    assert "chip_mismatch" in text and "platform_too_old" in text


def test_tool_error_text_lists_every_chip(host):
    env = call(host, "bench_pins", action="check", assignments=[{"role": "LED", "mode": "out", "pin": 4}])
    assert env["error"]["code"] == "invalid_args"
    assert chips.ids_text() in env["error"]["message"] + (env["error"].get("hint") or "")


def test_route_error_text_lists_every_chip(api):
    body = api.err(api.post("/pins/check", {"assignments": [{"role": "LED", "mode": "out", "pin": 4}]}), 400,
                   "invalid_args")
    assert chips.ids_text() in body["error"]["message"] + (body["error"].get("hint") or "")


# --------------------------------------------------------------------------------------------- error tables

def test_route_status_of_the_new_codes_is_like_elf_mismatch(api):
    common = importlib.import_module("circuit_bench_api_routes.common")
    assert common.STATUS["chip_mismatch"] == common.STATUS["platform_too_old"] == common.STATUS["elf_mismatch"] == 409
    assert set(common.STATUS) == set(contracts.ERROR_CODES)


def _project_with_firmware(host, tmp_path, pid="cagent-p"):
    env = call(host, "bench_project", action="create", id=pid, title="P", chip="esp32s3", variant="n16r8")
    assert env["ok"], env
    fw = tmp_path / "fw"
    fw.mkdir(exist_ok=True)
    (fw / "platformio.ini").write_text("[env:s3]\nplatform = espressif32\nboard = esp32-s3-devkitc-1\n", encoding="utf-8")
    assert call(host, "bench_project", action="set_firmware", id=pid, firmware_dir=str(fw), env="s3")["ok"]
    return pid


@pytest.mark.parametrize("code", ["platform_too_old", "chip_mismatch"])
def test_tool_build_passes_the_refusal_through(host, tmp_path, monkeypatch, code):
    pid = _project_with_firmware(host, tmp_path)
    hint = "pin platform = espressif32@8.0.0 (or newer)" if code == "platform_too_old" else "check the env's board"
    monkeypatch.setattr(board, "build", lambda *a, **k: contracts.fail("board.build", code, f"refused: {code}", hint))
    env = call(host, "bench_board", action="build", project=pid)
    assert env["ok"] is False and env["error"]["code"] == code and env["error"]["hint"] == hint
    assert project.get(pid)["result"]["project"]["firmware"]["last_build"] is None  # a refusal is no build


def test_tool_build_hands_the_project_chip_to_board_build(host, tmp_path, monkeypatch):
    """chip_mismatch/platform_too_old need the project chip (board.build(..., chip=))."""
    pid = _project_with_firmware(host, tmp_path)
    seen = {}

    def fake_build(project_dir, env, *, timeout=None, port=None, on_line=None, chip=None):
        seen["chip"] = chip
        return contracts.fail("board.build", "platform_too_old", "too old")

    monkeypatch.setattr(board, "build", fake_build)
    call(host, "bench_board", action="build", project=pid)
    assert seen == {"chip": "esp32s3"}


def _ready_for_real_flash(host, tmp_path, pid):
    rev = project.get(pid)["result"]["rev"]
    env = project.update(pid, rev, [
        {"op": "set_detected", "port": REAL, "mac": "aa:bb:cc:dd:ee:ff", "chip": "ESP32-S3 (QFN56)"},
        {"op": "set_build", "ok": True, "elf_sha256": "a" * 64, "elf": ".pio/build/s3/firmware.elf"}],
        by="ui", trusted=True)
    assert env["ok"], env


def test_flash_chip_mismatch_in_tool_and_hook(host, tmp_path, monkeypatch):
    monkeypatch.setenv("CIRCUIT_BENCH_HW", "on")
    monkeypatch.setenv("CIRCUIT_BENCH_SETTINGS_JSON", json.dumps({"allow_flash": True}))
    pid = _project_with_firmware(host, tmp_path)
    _ready_for_real_flash(host, tmp_path, pid)
    monkeypatch.setattr(guard, "check_flash", lambda **kw: contracts.fail(
        "board.flash", "chip_mismatch", "the board is an ESP32-S3, project is set to esp32c6", "detect again"))
    monkeypatch.setattr(board, "flash", lambda *a, **k: pytest.fail("board.flash ran"))
    decision = hooks.decide(host, "bench_board", {"action": "flash", "project": pid, "elf_sha256": "a" * 12})
    assert decision["action"] == "block" and "(chip_mismatch)" in decision["message"]
    env = call(host, "bench_board", action="flash", project=pid, elf_sha256="a" * 12)
    assert env["error"]["code"] == "chip_mismatch"


def test_flash_route_chip_mismatch_is_409(api, monkeypatch):
    api.create("bench-cm")
    api.record("bench-cm", {"op": "set_detected", "port": "sim://esp32s3-n16r8", "mac": "aa:bb:cc:dd:ee:ff",
                            "chip": "ESP32-S3"})
    rc = sup.route_module("contracts")
    monkeypatch.setattr(sup.route_module("guard"), "check_flash", lambda **kw: rc.fail(
        "board.flash", "chip_mismatch", "the board is an ESP32-S3, project is set to esp32c6", "detect again"))
    body = api.err(api.post("/board/flash", {"project": "bench-cm"}), 409, "chip_mismatch")
    assert body["action"] == "board.flash"


# ------------------------------------------------------------------------------------- with the full chip data

@pytest.mark.skipif(not flash_refusals_merged(), reason="board.build has no platform check")
@need(("pins", "esp32c6"))
def test_c6_build_with_platform_713_is_refused_without_pio(host, tmp_path, monkeypatch):
    calls = []
    real_run = board.clitools.run

    def spy(argv, **kw):
        calls.append([str(a) for a in argv])
        return real_run(argv, **kw)

    monkeypatch.setattr(board.clitools, "run", spy)
    env = call(host, "bench_project", action="create", id="c6-old", title="C6", chip="esp32c6")
    assert env["ok"], env
    fw = tmp_path / "c6fw"
    fw.mkdir()
    (fw / "platformio.ini").write_text("[env:c6]\nplatform = espressif32@7.1.3\nboard = esp32-c6-devkitc-1\n"
                                       "board_build.mcu = esp32c6\nframework = arduino\n", encoding="utf-8")
    assert call(host, "bench_project", action="set_firmware", id="c6-old", firmware_dir=str(fw), env="c6")["ok"]
    env = call(host, "bench_board", action="build", project="c6-old")
    assert env["error"]["code"] == "platform_too_old" and "8.0.0" in (env["error"].get("hint") or "")
    assert not [c for c in calls if c[1:2] == ["run"]], calls


@need(("pins", "esp32c6"), ("boards", "esp32-c6-devkitc-1"))
def test_c6_devkitc_gpio9_caution(host):
    env = call(host, "bench_pins", action="check", chip="esp32c6", devkit="esp32-c6-devkitc-1",
               assignments=[{"role": "BTN", "mode": "in_pullup", "pin": 9}])
    assert env["ok"], env
    assert env["result"]["pins"][0]["verdict"] == "caution"


@need(("boards", "wt32-eth01"))
def test_wt32_gpio0_blocked_with_danger_warning(host):
    env = call(host, "bench_pins", action="check", chip="esp32", devkit="wt32-eth01",
               assignments=[{"role": "LED", "mode": "out", "pin": 0}])
    assert env["ok"], env
    assert env["result"]["pins"][0]["verdict"] == "blocked"
    danger = [w for w in env["warnings"] if w["severity"] == "danger"]
    assert danger and any("3V3" in w["message"] and "5V" in w["message"] for w in danger)
    assert len([w["code"] for w in env["warnings"]]) == len({w["code"] for w in env["warnings"]})  # no duplicates
    info = call(host, "bench_pins", action="info", chip="esp32", devkit="wt32-eth01", pin=0)
    assert any(w["severity"] == "danger" for w in info["warnings"])


@need(("boards", "wt32-eth01"))
def test_wt32_route_pins_check_has_the_danger_warning(api):
    env = api.ok(api.post("/pins/check", {"chip": "esp32", "devkit": "wt32-eth01",
                                          "assignments": [{"role": "LED", "mode": "out", "pin": 0}]}))
    assert any(w["severity"] == "danger" for w in env["warnings"])


@need(("boards", "wt32-eth01"))
def test_wt32_project_create_repeats_the_danger_warning(host):
    env = call(host, "bench_project", action="create", id="wt32-p", title="WT32", chip="esp32", devkit="wt32-eth01")
    assert env["ok"], env
    assert any(w["severity"] == "danger" for w in env["warnings"])
    got = call(host, "bench_project", action="get", id="wt32-p")
    assert any(w["severity"] == "danger" for w in got["warnings"])


def test_board_warnings_are_added_once(host, monkeypatch):
    """The board-level warnings join a pins answer once, whether or not bench_core already added them."""
    from circuit_bench.bench_core import boards
    w = {"id": "x.power", "severity": "danger", "message": "Feed either 3V3 or 5V, never both.",
         "source_id": "devkitc1-s3-v1.1"}
    monkeypatch.setattr(boards, "warnings_of", lambda board_id: [dict(w)])
    env = call(host, "bench_pins", action="check", chip="esp32s3", variant="n16r8", devkit="esp32-s3-devkitc-1",
               assignments=[{"role": "LED", "mode": "out", "pin": 4}])
    assert [x["code"] for x in env["warnings"]].count("x.power") == 1
    assert next(x for x in env["warnings"] if x["code"] == "x.power")["source_ids"] == ["devkitc1-s3-v1.1"]
    once = tools.with_board_warnings(env, "esp32-s3-devkitc-1")
    assert [x["code"] for x in once["warnings"]].count("x.power") == 1
    plain = call(host, "bench_pins", action="check", chip="esp32s3", variant="n16r8",
                 assignments=[{"role": "LED", "mode": "out", "pin": 4}])
    assert "x.power" not in [x["code"] for x in plain["warnings"]]  # no devkit, no board warnings


@need(("pins", "esp32s2"))
def test_s2_project_create(host):
    devkit = "esp32-s2-devkitc-1" if _has("boards", "esp32-s2-devkitc-1") else None
    env = call(host, "bench_project", action="create", id="s2-p", title="S2", chip="esp32s2", devkit=devkit)
    assert env["ok"], env
    assert project.get("s2-p")["result"]["project"]["board"]["chip"] == "esp32s2"
