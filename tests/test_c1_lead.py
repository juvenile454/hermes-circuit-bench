"""Seams between chip register, pin data, board layouts, tools and routes.

Register = pin data, board layouts against the pin data and its variants, combined pin checks on the new DevKits, the
board warnings in GET /projects/{id}, and the project chip/DevKit handed from tools and routes to board.build/detect/
flash (build pre-check, flash_hint).
"""
import json
import sys
import types

import pytest
import test_api_support as sup  # noqa: F401
from test_api_support import *  # noqa: F403

from circuit_bench import hooks, tools
from circuit_bench.bench_core import board, boards, chips, contracts, guard, pins

NEW = ("esp32-s2-devkitc-1", "esp32-c6-devkitc-1", "esp32-c6-devkitm-1", "wt32-eth01")


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


TASK = "t"  # the task id Hermes passes to the hook and the handler alike


def call(host, name, **args):
    env = json.loads(tools.make_handlers(host)[name](args, task_id=TASK))
    assert contracts.validate_envelope(env) == [], env
    return env


def verdicts(env):
    return {a["pin"]: a["verdict"] for a in env["result"]["pins"]}


# --- data seams -----------------------------------------------------------------------------------------------------
def test_register_equals_pin_data():
    assert sorted(chips.ids()) == pins.chips()


@pytest.mark.parametrize("board_id", NEW)
def test_new_board_variant_and_chip_exist_in_the_pin_data(board_id):
    b = boards.load(board_id)
    variants = [v["id"] for v in pins.load(b["chip"]).get("variants", [])]
    assert b["module"]["variant"] in [None, *variants], (board_id, variants)
    assert b["chip"] in chips.ids()


def test_wt32_gpio0_blocked_on_board_and_gpio17_caution_without_variant():
    env = pins.check("esp32", [{"role": "A", "mode": "out", "pin": 0}, {"role": "B", "mode": "out", "pin": 17},
                               {"role": "C", "mode": "out", "pin": 4}], devkit="wt32-eth01")
    assert env["ok"], env
    assert verdicts(env) == {0: "blocked", 17: "caution", 4: "ok"}


def test_wt32_pin_not_on_the_headers_is_flagged():
    env = pins.check("esp32", [{"role": "A", "mode": "out", "pin": 13}], devkit="wt32-eth01")
    assert verdicts(env)[13] != "ok"  # GPIO13 is not broken out on the WT32-ETH01


def test_c6_devkitc_gpio14_and_gpio10_with_the_module_variant():
    env = pins.check("esp32c6", [{"role": "A", "mode": "out", "pin": 14}, {"role": "B", "mode": "out", "pin": 10}],
                     variant="wroom-1", devkit="esp32-c6-devkitc-1")
    assert verdicts(env) == {14: "blocked", 10: "ok"}
    env = pins.check("esp32c6", [{"role": "A", "mode": "out", "pin": 10}, {"role": "B", "mode": "out", "pin": 14}],
                     variant="mini-1", devkit="esp32-c6-devkitm-1")
    assert verdicts(env)[10] == "blocked" and verdicts(env)[14] != "blocked"


def test_s2_devkitc_gpio46_out_blocked_and_gpio18_led():
    env = pins.check("esp32s2", [{"role": "A", "mode": "out", "pin": 46}, {"role": "B", "mode": "out", "pin": 18}],
                     devkit="esp32-s2-devkitc-1")
    assert verdicts(env) == {46: "blocked", 18: "caution"}


# --- tools/routes hand the project chip and DevKit down ---------------------------------------------------------------
def _wt32_project(host, pid="lead-wt32"):
    env = call(host, "bench_project", action="create", id=pid, title="WT32", chip="esp32", devkit="wt32-eth01")
    assert env["ok"], env
    return pid


def test_route_get_project_repeats_the_board_danger_warning(api, host):
    pid = _wt32_project(host)
    env = api.ok(api.get(f"/projects/{pid}"))
    assert [w["code"] for w in env["warnings"] if w["severity"] == "danger"] == ["wt32.power_exclusive"]
    assert any(s["id"] == "ds-wt32-eth01-v1.4" or s["id"].startswith("wiki-wt32") for s in env["sources"])


def test_tool_detect_hands_the_devkit_to_board_detect(host, monkeypatch):
    pid = _wt32_project(host)
    seen = {}

    def fake_detect(port, **kw):
        seen.update(kw)
        return contracts.fail("board.detect", "timeout", "no serial data", "adapter: " + json.dumps(kw))

    monkeypatch.setattr(board, "detect", fake_detect)
    monkeypatch.setattr(guard, "check_serial", lambda **kw: None)
    assert hooks.decide(host, "bench_board", {"action": "detect", "port": "/dev/ttyUSB7"}, TASK)["action"] == "approve"
    env = call(host, "bench_board", action="detect", port="/dev/ttyUSB7", project=pid)
    assert seen.get("devkit") == "wt32-eth01"
    assert env["error"]["code"] == "timeout"
    text, _ = board.flash_hint("wt32-eth01")
    assert "USB-to-UART adapter" in text


# --- stale build after a chip change, board warnings, the GPIO46 reason, detect on another chip ---------------------------
REAL = "/dev/ttyUSB7"


def _armed(monkeypatch):
    monkeypatch.setenv("CIRCUIT_BENCH_HW", "on")
    monkeypatch.setenv("CIRCUIT_BENCH_SETTINGS_JSON", json.dumps({"allow_flash": True}))


def _flash_ready(pid, chip_name, build_chip=None):
    from circuit_bench.bench_core import project
    rev = project.get(pid)["result"]["rev"]
    build = {"op": "set_build", "ok": True, "elf_sha256": "a" * 64, "elf": ".pio/build/s3/firmware.elf"}
    if build_chip:
        build["chip"] = build_chip
    env = project.update(pid, rev, [{"op": "set_detected", "port": REAL, "mac": "aa:bb:cc:dd:ee:ff",
                                     "chip": chip_name}, build], by="ui", trusted=True)
    assert env["ok"], env


def test_r_c1_chip_change_drops_the_last_build(host):
    from circuit_bench.bench_core import project
    assert call(host, "bench_project", action="create", id="rc1", title="t", chip="esp32s3", variant="n16r8")["ok"]
    _flash_ready("rc1", "ESP32-S3", build_chip="esp32s3")
    assert project.get("rc1")["result"]["project"]["firmware"]["last_build"]["chip"] == "esp32s3"
    rev = project.get("rc1")["result"]["rev"]
    assert project.update("rc1", rev, [{"op": "set_board", "chip": "esp32c6"}], by="agent")["ok"]
    p = project.get("rc1")["result"]["project"]
    assert p["firmware"]["last_build"] is None and p["board"]["detected"] is None


def test_r_c1_build_for_another_chip_is_refused_by_the_flash_guard(host, monkeypatch):
    _armed(monkeypatch)
    assert call(host, "bench_project", action="create", id="rc1b", title="t", chip="esp32c6")["ok"]
    _flash_ready("rc1b", "ESP32-C6", build_chip="esp32s3")  # a stale S3 build record on a C6 project
    from circuit_bench.bench_core import project
    proj = project.get("rc1b")["result"]["project"]
    env = guard.check_flash(via="tool", settings={"allow_flash": True}, project=proj, port=REAL, cron=False)
    assert env is not None and env["error"]["code"] == "chip_mismatch" and "last build" in env["error"]["message"]
    # the same build recorded for the right chip passes this check
    _flash_ready("rc1b", "ESP32-C6", build_chip="esp32c6")
    proj = project.get("rc1b")["result"]["project"]
    assert guard.check_flash(via="tool", settings={"allow_flash": True}, project=proj, port=REAL, cron=False) is None


def test_r_c1_build_result_names_the_checked_chip(tmp_path, monkeypatch):
    out = board._with_precheck(contracts.envelope("board.build", "built", {"ok": True, "elf_sha256": "a" * 64}),
                               {"warnings": [], "source_ids": [], "mcu": "esp32c6"}, "esp32c6")
    assert out["result"]["chip"] == "esp32c6"
    unchecked = board._with_precheck(contracts.envelope("board.build", "built", {"ok": True}),
                                     {"warnings": [], "source_ids": [], "mcu": None}, "esp32c6")
    assert "chip" not in unchecked["result"]


def test_r_c3_route_create_and_set_board_repeat_the_danger_warning(api):
    env = api.ok(api.post("/projects", {"id": "rc3", "title": "t", "chip": "esp32", "devkit": "wt32-eth01"}))
    assert "wt32.power_exclusive" in [w["code"] for w in env["warnings"]]
    env = api.ok(api.post("/projects", {"id": "rc3b", "title": "t", "chip": "esp32"}))
    rev = env["result"]["rev"]
    env = api.ok(api.patch("/projects/rc3b", {"expected_rev": rev, "ops": [{"op": "set_board", "devkit": "wt32-eth01"}]}))
    assert "wt32.power_exclusive" in [w["code"] for w in env["warnings"]]


@pytest.mark.parametrize("mode", ["in_pulldown", "i2c_sda", "out"])
def test_r_c8_gpio46_reason_is_the_fixed_pull_down(mode):
    env = pins.check("esp32s2", [{"role": "A", "mode": mode, "pin": 46}])
    p = env["result"]["pins"][0]
    assert p["verdict"] == "blocked" and "s2.input_only" in p["rule_ids"]


def test_r_c9_route_detect_warns_on_another_chip(api):
    resp = api.post("/projects", {"id": "rc9", "title": "t", "chip": "esp32c6"})
    assert resp.status_code == 200, resp.json()
    env = api.post("/board/detect", {"port": "sim://test-s3", "project": "rc9"}).json()
    job = api.wait_job(env["result"]["job_id"])
    warns = job["result"]["result"]["warnings"]
    assert [w["severity"] for w in warns if w["code"] == "chip_mismatch"] == ["caution"], warns
