"""pre_tool_call hook decisions for bench_board (table in circuit_bench/hooks.py)."""
import hashlib
import json
import sys
import types

import pytest

from circuit_bench import hooks, tools
from circuit_bench.bench_core import project

REAL = "/dev/ttyCB0"
SHA = "b" * 64
MAC = "aa:bb:cc:dd:ee:ff"


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    cfg = types.ModuleType("hermes_cli.config")
    cfg.value = {"approvals": {"mode": "manual"}}
    cfg.load_config = lambda: cfg.value
    pkg = types.ModuleType("hermes_cli")
    pkg.config = cfg
    monkeypatch.setitem(sys.modules, "hermes_cli", pkg)
    monkeypatch.setitem(sys.modules, "hermes_cli.config", cfg)
    monkeypatch.delenv("HERMES_YOLO_MODE", raising=False)
    monkeypatch.delenv("HERMES_CRON_SESSION", raising=False)
    monkeypatch.setenv("CIRCUIT_BENCH_HW", "on")  # the hook only decides; nothing here runs a tool
    settings(monkeypatch, allow_flash=True)
    return cfg


def settings(monkeypatch, **values):
    monkeypatch.setenv("CIRCUIT_BENCH_SETTINGS_JSON", json.dumps(values))


@pytest.fixture
def ready(tmp_path):
    """Project with a detected real board and a successful build."""
    fw = tmp_path / "fw"
    fw.mkdir()
    (fw / "platformio.ini").write_text("[env:s3]\n", encoding="utf-8")
    assert project.create("laser-trigger", "Laser trigger", "esp32s3", "n16r8")["ok"]
    env = project.update("laser-trigger", 1, [
        {"op": "set_detected", "port": REAL, "mac": MAC.upper(), "chip": "ESP32-S3 (QFN56)"},
        {"op": "set_firmware", "dir": str(fw), "env": "s3"},
        {"op": "set_build", "ok": True, "elf_sha256": SHA}], by="ui", trusted=True)
    assert env["ok"]
    return env["result"]["project"]


def decide(args, host=None, tool="bench_board"):
    return hooks.make_pre_tool_call(host or tools.Host(hook_active=True))(tool_name=tool, args=args, task_id="t",
                                                                           session_id="s", tool_call_id="c")


def flash(**extra):
    return {"action": "flash", "project": "laser-trigger", "elf_sha256": SHA, **extra}


def test_flash_ok_asks_with_board_details(ready):
    d = decide(flash())
    assert d["action"] == "approve"
    assert d["message"].startswith(f"Flash firmware s3 from {ready['firmware']['dir']} to ESP32-S3 (QFN56) (MAC {MAC}) on {REAL}?")
    assert f"ELF {SHA}" in d["message"]
    assert d["rule_key"] == "circuit-bench:flash:" + hashlib.sha256(f"{REAL}|{MAC}|{SHA}".encode()).hexdigest()
    assert decide(flash(port=REAL)) == d
    short = decide(flash(elf_sha256=SHA[:12].upper()))  # a prefix of 12+ hex digits names the build too
    assert short["action"] == "approve" and f"ELF {SHA[:12]} " in short["message"]
    assert short["rule_key"] == "circuit-bench:flash:" + hashlib.sha256(f"{REAL}|{MAC}|{SHA[:12]}".encode()).hexdigest()


def test_rule_key_changes_with_the_firmware(ready):
    first = decide(flash())["rule_key"]
    project.update("laser-trigger", ready["rev"], [{"op": "set_build", "ok": True, "elf_sha256": "c" * 64}], by="ui", trusted=True)
    assert decide(flash(elf_sha256="c" * 64))["rule_key"] != first


def test_flash_needs_the_elf_sha256_of_the_last_build(ready):
    """The approval is bound to the firmware the model names; it must be the last build."""
    d = decide(flash(elf_sha256=None))
    assert d["action"] == "block" and "pass elf_sha256 from the last bench_board build" in d["message"]
    d = decide({"action": "flash", "project": "laser-trigger"})
    assert d["action"] == "block" and "elf_sha256" in d["message"]
    d = decide(flash(elf_sha256="c" * 64))
    assert d["action"] == "block" and "elf_mismatch" in d["message"]
    assert "run bench_board build with project" in d["message"] and "then flash with its elf_sha256" in d["message"]
    for bad in ("b" * 11, "xyz" * 5, 12345678901234, "b" * 65):
        d = decide(flash(elf_sha256=bad))
        assert d["action"] == "block" and "invalid_args" in d["message"], bad


@pytest.mark.parametrize(("change", "needle"), [
    ({"allow_flash": False}, "allow_flash"),
    ({"hardware_access": False}, "sim_only"),
])
def test_flash_blocked_by_settings(ready, monkeypatch, change, needle):
    settings(monkeypatch, **{"allow_flash": True, **change})
    d = decide(flash())
    assert d["action"] == "block" and needle in d["message"]


def test_flash_blocked_without_detection_or_build(monkeypatch):
    assert project.create("laser-trigger", "Laser trigger", "esp32s3", "n16r8")["ok"]
    d = decide(flash())
    assert d["action"] == "block" and "not_confirmed" in d["message"]
    project.update("laser-trigger", 1, [{"op": "set_detected", "port": REAL, "mac": MAC}], by="ui", trusted=True)
    d = decide(flash())
    assert d["action"] == "block" and "build" in d["message"]
    d = decide(flash(port="/dev/ttyCB9"))  # another port than the detected one
    assert d["action"] == "block" and "not_confirmed" in d["message"]


def test_flash_blocked_without_or_with_unknown_project():
    assert decide({"action": "flash", "port": REAL})["action"] == "block"
    assert decide(flash())["action"] == "block"  # project does not exist


def test_cron_blocks(ready):
    cron_host = tools.Host(cron=lambda: True, hook_active=True)
    for args in (flash(), {"action": "detect", "port": REAL}, {"action": "monitor", "port": REAL}):
        d = decide(args, cron_host)
        assert d["action"] == "block" and "cron" in d["message"], args


@pytest.mark.parametrize("bypass", ["yolo", "mode_off"])
def test_bypass_blocks_real_ports(ready, monkeypatch, _env, bypass):
    if bypass == "yolo":
        monkeypatch.setenv("HERMES_YOLO_MODE", "1")
    else:
        _env.value = {"approvals": {"mode": "off"}}
    for args in (flash(), {"action": "detect", "port": REAL}, {"action": "monitor", "port": REAL}):
        d = decide(args)
        assert d["action"] == "block" and "unattended_blocked" in d["message"], args
        assert "Bench UI" in d["message"]


def test_serial_approval(ready, monkeypatch):
    for action in ("detect", "monitor"):
        d = decide({"action": action, "port": REAL, "seconds": 5})
        assert d["action"] == "approve" and REAL in d["message"] and "reset" in d["message"]
        assert d["rule_key"] == f"circuit-bench:{action}:" + hashlib.sha256(REAL.encode()).hexdigest()
    settings(monkeypatch, approve_serial=False)
    assert decide({"action": "detect", "port": REAL}) is None
    monkeypatch.setenv("CIRCUIT_BENCH_HW", "off")
    d = decide({"action": "monitor", "port": REAL})
    assert d["action"] == "block" and "sim_only" in d["message"]


def test_detect_and_monitor_have_separate_rule_keys(ready):
    """An "always" for the monitor (stored by Hermes under its rule_key) must not cover detect."""
    det = decide({"action": "detect", "port": REAL})["rule_key"]
    mon = decide({"action": "monitor", "port": REAL, "seconds": 5})["rule_key"]
    assert det.startswith("circuit-bench:detect:") and mon.startswith("circuit-bench:monitor:") and det != mon
    assert decide({"action": "monitor", "port": "/dev/ttyCB9"})["rule_key"] != mon  # per port


def test_sim_ports_get_no_directive(ready):
    project.update("laser-trigger", ready["rev"], [{"op": "set_detected", "port": "sim://esp32s3-n16r8"}], by="ui", trusted=True)
    assert decide(flash()) is None
    assert decide(flash(port="sim://esp32s3-n16r8")) is None
    for action in ("detect", "monitor"):
        assert decide({"action": action, "port": "sim://esp32s3-n16r8"}) is None
    cron_host = tools.Host(cron=lambda: True, hook_active=True)
    assert decide(flash(), cron_host) is None  # the handler refuses cron flashes itself


@pytest.mark.parametrize("args", [
    {"action": "ports"}, {"action": "build", "project": "laser-trigger", "port": "sim://x"}, {"action": "nope"}, {}, None, [], "flash",
    {"action": "detect"}, {"action": "monitor", "port": 5}, {"action": "detect", "port": "  "},
])
def test_no_directive(args):
    assert decide(args) is None


def test_other_tools_are_ignored(ready):
    for tool in ("bench_project", "terminal", "tool_call", ""):
        assert decide(flash(), tool=tool) is None


def test_internal_error_blocks_real_calls(ready, monkeypatch):
    from circuit_bench.bench_core import guard

    def boom(**kw):
        raise RuntimeError("secret")

    monkeypatch.setattr(guard, "check_flash", boom)
    monkeypatch.setattr(guard, "check_serial", boom)
    for args in (flash(), {"action": "detect", "port": REAL}):
        d = decide(args)
        assert d["action"] == "block" and "RuntimeError" in d["message"] and "secret" not in d["message"]


def test_hook_accepts_any_keywords():
    import inspect
    cb = hooks.make_pre_tool_call(tools.Host())
    kinds = [p.kind for p in inspect.signature(cb).parameters.values()]
    assert inspect.Parameter.VAR_KEYWORD in kinds
    assert cb(tool_name="bench_board", args={"action": "ports"}, middleware_trace=[], turn_id="x") is None
