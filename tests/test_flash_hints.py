"""Hints of flash refusals and of the monitor's panic warning name the next tool call and its project.

Simulated board (sim://) and, for real boards, only fakes: fake esptool/pio, pty ports, mocked port lists,
synthetic MACs.
"""
import json
import sys
import types
from pathlib import Path

import board_fixtures as bf
import pytest
import test_api_support as sup
from board_fixtures import fake_tools, hw_on, pty_port  # noqa: F401 - fixtures

from circuit_bench import hooks, tools
from circuit_bench.bench_core import board, contracts, project, runtime

sim = pytest.importorskip("circuit_bench.bench_core.sim")


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
    monkeypatch.setattr(sim, "TIME_SCALE", 0.0)
    yield
    b = runtime.peek("broker")
    if b is not None:
        b.shutdown()


TASK = "t"  # the task id Hermes passes to the hook and the handler alike


def call(host, name, **args):
    env = json.loads(tools.make_handlers(host)[name](args, task_id=TASK))
    assert contracts.validate_envelope(env) == [], env
    return env


@pytest.fixture
def host():
    return tools.Host(hook_active=False)  # sim:// needs no hook


@pytest.fixture
def demo(host):
    env = call(host, "bench_project", action="demo")
    assert env["ok"], env
    return env["result"]["id"]


def _refused(env, code):
    assert env["ok"] is False and env["error"]["code"] == code, env
    return env["error"]["hint"]


def test_flash_without_project(host):
    hint = _refused(call(host, "bench_board", action="flash"), "not_confirmed")
    assert hint == "pass project; run bench_board detect and build with it first"


def test_flash_without_detection(host, demo):
    assert not (project.get(demo)["result"]["project"]["board"].get("detected"))
    hint = _refused(call(host, "bench_board", action="flash", project=demo), "not_confirmed")
    assert hint == f"run bench_board detect with project {demo}, then build"


def test_flash_without_build(host, demo):
    assert call(host, "bench_board", action="detect", port=sim.PORT, project=demo)["ok"]
    hint = _refused(call(host, "bench_board", action="flash", project=demo), "not_confirmed")
    assert hint == f"run bench_board build with project {demo} first"


def _detected_and_built(host, pid):
    assert call(host, "bench_board", action="detect", port=sim.PORT, project=pid)["ok"]
    env = call(host, "bench_board", action="build", project=pid)
    assert env["ok"], env
    return env["result"]["elf_sha256"]


def test_flash_with_another_elf_sha256(host, demo):
    _detected_and_built(host, demo)
    hint = _refused(call(host, "bench_board", action="flash", project=demo, elf_sha256="0" * 64), "elf_mismatch")
    assert hint == f"run bench_board build with project {demo} again, then flash with its elf_sha256"


def test_sim_firmware_changed_after_the_build(host, demo):
    sha = _detected_and_built(host, demo)
    main = Path(project.get(demo)["result"]["project"]["firmware"]["dir"]) / "src" / "main.cpp"
    main.write_text(main.read_text(encoding="utf-8") + "\n// changed after the build\n", encoding="utf-8")
    hint = _refused(call(host, "bench_board", action="flash", project=demo, elf_sha256=sha), "elf_mismatch")
    assert hint == f"run bench_board build with project {demo} again, then flash with its elf_sha256"


def _approved_real_flash(fake_tools, pty_port, monkeypatch, tmp_path, pid):  # noqa: F811
    """A project on a pty 'board' with a fake build and the approval hook's yes; returns (host, args, build)."""
    monkeypatch.setenv("CIRCUIT_BENCH_SETTINGS_JSON", json.dumps({"allow_flash": True}))
    bf.mock_comports(monkeypatch, [(pty_port.name, 0x303A, 0x1001, "USB JTAG/serial debug unit")])
    fw = sup.write_firmware(tmp_path / "fw")
    fake_tools.scenario("board-pio-flash-ok.json")
    built = board.build(fw, "s3")
    assert built["ok"], built["error"]
    assert project.create(pid, "Hints", "esp32s3", "n16r8", "esp32-s3-devkitc-1", by="agent")["ok"]
    upd = project.update(pid, 1, [
        {"op": "set_detected", "port": pty_port.name, "mac": "aa:bb:cc:dd:ee:ff",
         "chip": "ESP32-S3 (QFN56) (revision v0.2)"},
        {"op": "set_firmware", "dir": str(fw), "env": "s3"}, {"op": "set_build", **built["result"]}],
        by="ui", trusted=True)
    assert upd["ok"], upd
    host = tools.Host(hook_active=True)
    args = {"action": "flash", "project": pid, "elf_sha256": built["result"]["elf_sha256"]}
    assert hooks.decide(host, "bench_board", args, TASK)["action"] == "approve"
    return host, args, Path(built["result"]["elf_path"])


def test_real_elf_changed_after_the_approval(fake_tools, hw_on, pty_port, monkeypatch, tmp_path):  # noqa: F811
    host, args, elf = _approved_real_flash(fake_tools, pty_port, monkeypatch, tmp_path, "hints-changed")
    elf.write_text("FAKE-ELF build 2 (changed after approval)\n", encoding="utf-8")
    env = call(host, "bench_board", **args)
    hint = _refused(env, "elf_mismatch")
    assert hint == "run bench_board build with project hints-changed again, then flash with its elf_sha256"
    assert "changed after the approved build" in env["error"]["message"]  # the bench_core message stays
    assert not any("write-flash" in c["argv"] for c in fake_tools.calls())


def test_real_build_output_incomplete(fake_tools, hw_on, pty_port, monkeypatch, tmp_path):  # noqa: F811
    host, args, elf = _approved_real_flash(fake_tools, pty_port, monkeypatch, tmp_path, "hints-missing")
    elf.with_suffix(".bin").unlink()
    env = call(host, "bench_board", **args)
    hint = _refused(env, "elf_missing")
    assert hint == "run bench_board build with project hints-missing again: the build output is incomplete"
    assert not any("write-flash" in c["argv"] for c in fake_tools.calls())


def test_monitor_panic_warning_asks_for_the_project(host, demo):
    sha = _detected_and_built(host, demo)
    assert call(host, "bench_board", action="flash", project=demo, elf_sha256=sha)["ok"]
    env = call(host, "bench_board", action="monitor", port=sim.PORT, seconds=5)
    assert env["ok"], env
    panic = env["result"]["panics"][0]
    warns = [w["message"] for w in env["warnings"] if w["code"] == "panic_detected"]
    assert warns and warns[0].endswith(f"decode it with bench_crash (log_ref {panic['log_ref']}, and project for the ELF)")
