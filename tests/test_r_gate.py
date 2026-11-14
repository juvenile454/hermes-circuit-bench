"""Build approval: ``bench_board build`` on a real (offline) target asks through the pre_tool_call hook, is refused in
cron and refused by the handler without the hook; simulated builds that start no PlatformIO (the TestProvider has no
``build_runs_pio``) stay unchanged. PlatformIO never starts here:
``clitools.run`` and ``board.build`` are tripwires wherever a real build could happen."""
import hashlib
import json
import sys
import types

import board_fixtures as bf
import pytest

from circuit_bench import hooks, tools
from circuit_bench.bench_core import board, clitools, contracts, project

SIM = "sim://test-s3"
REAL = "/dev/ttyCB0"  # never exists


@pytest.fixture(autouse=True)
def _isolation(monkeypatch):
    import circuit_bench.bench_core as core

    def no_port_list():
        raise AssertionError("test called the real serial port list")

    def no_process(*a, **k):
        raise AssertionError("clitools.run must not start a process in these tests")

    monkeypatch.setattr(board, "_comports", no_port_list)
    monkeypatch.setattr(clitools, "run", no_process)
    monkeypatch.delattr(core, "sim", raising=False)
    monkeypatch.setitem(sys.modules, "circuit_bench.bench_core.sim", None)  # TestProvider plays sim://
    cfg = types.ModuleType("hermes_cli.config")
    cfg.load_config = lambda: {"approvals": {"mode": "manual"}}
    pkg = types.ModuleType("hermes_cli")
    pkg.config = cfg
    monkeypatch.setitem(sys.modules, "hermes_cli", pkg)
    monkeypatch.setitem(sys.modules, "hermes_cli.config", cfg)
    monkeypatch.delenv("HERMES_YOLO_MODE", raising=False)
    monkeypatch.delenv("HERMES_CRON_SESSION", raising=False)
    board.register_provider("sim://", bf.TestProvider())


@pytest.fixture
def built(monkeypatch):
    """board.build replaced: records what the handler would build, never runs pio."""
    calls = []

    def fake_build(project_dir, env, **kw):
        calls.append((project_dir, env, kw.get("port")))
        return contracts.fail("board.build", "tool_missing", "pio not found (test)")

    monkeypatch.setattr(board, "build", fake_build)
    return calls


@pytest.fixture
def no_build(monkeypatch):
    def trip(*a, **k):
        raise AssertionError("board.build must not run")

    monkeypatch.setattr(board, "build", trip)


def fw_dir(tmp_path, name="fw"):
    d = tmp_path / name
    d.mkdir(exist_ok=True)
    (d / "platformio.ini").write_text("[env:s3]\nplatform = espressif32\n[env:c3]\nplatform = espressif32\n",
                                      encoding="utf-8")
    return d


def mk(pid="laser-trigger", fw=None, env="s3", detected=None):
    assert project.create(pid, "Laser trigger", "esp32s3", "n16r8")["ok"]
    ops = []
    if fw is not None:
        ops.append({"op": "set_firmware", "dir": str(fw), "env": env})
    if detected is not None:
        ops.append({"op": "set_detected", "port": detected, "mac": "aa:bb:cc:dd:ee:ff", "chip": "ESP32-S3 (QFN56)"})
    if ops:
        assert project.update(pid, 1, ops, by="ui", trusted=True)["ok"]


def decide(args, host=None):
    cb = hooks.make_pre_tool_call(host or tools.Host(hook_active=True))
    return cb(tool_name="bench_board", args=args, task_id="t", session_id="s", tool_call_id="c")


def call(host, **args):
    out = tools.make_handlers(host)["bench_board"](args, task_id="t")  # the task id of decide()
    env = json.loads(out)
    assert contracts.validate_envelope(env) == [], env
    return env


def key(folder, env):
    return "circuit-bench:build:" + hashlib.sha256(f"{folder}|{env}".encode()).hexdigest()


# --------------------------------------------------------------------------------------------- build_target

def test_build_target_real_and_sim(tmp_path):
    d = fw_dir(tmp_path)
    t = tools.build_target({"action": "build", "project_dir": str(d), "env": "s3"})
    assert (t.project, t.dir, t.env, t.port, t.simulated) == (None, d.resolve(), "s3", None, False)
    t = tools.build_target({"action": "build", "project_dir": str(d), "env": "s3", "port": REAL})
    assert t.port is None and t.simulated is False  # a real port is dropped: offline real build
    t = tools.build_target({"action": "build", "project_dir": str(d), "env": "s3", "port": SIM})
    assert t.port == SIM and t.simulated is True
    mk(fw=d, detected=SIM)
    t = tools.build_target({"action": "build", "project": "laser-trigger"})
    assert t.project["id"] == "laser-trigger" and t.dir == d.resolve() and t.port == SIM and t.simulated


# --------------------------------------------------------------------------------------------- hook

def test_sim_build_gets_no_directive(tmp_path, no_build):
    d = fw_dir(tmp_path)
    assert decide({"action": "build", "project_dir": str(d), "env": "s3", "port": SIM}) is None
    mk(fw=d, detected=SIM)
    assert decide({"action": "build", "project": "laser-trigger"}) is None  # sim port from the detection
    mk("demo-like", fw=d)
    project.update("demo-like", 2, [{"op": "set_detected", "port": "sim://test-c3", "mac": "aa:bb:cc:dd:ee:00",
                                     "chip": "ESP32-S3"}], by="ui", trusted=True)
    assert decide({"action": "build", "project": "demo-like"}) is None


def test_real_build_asks_with_exact_rule_key(short_tmp, no_build):
    d = fw_dir(short_tmp)
    d_res = d.resolve()
    want = {"action": "approve",
            "message": "Build env s3 with PlatformIO? This runs the project's own build scripts "
                       "(platformio.ini, extra_scripts) with your user rights. Nothing is uploaded to a board. "
                       f"Folder: \"{d_res}\"",
            "rule_key": key(str(d_res), "s3")}
    assert decide({"action": "build", "project_dir": str(d), "env": "s3"}) == want
    assert hooks.build_rule_key(str(d_res), "s3") == want["rule_key"]
    assert decide({"action": "build", "project_dir": str(d), "env": "s3", "port": REAL}) == want
    mk(fw=d)  # a project without a sim board builds for real too
    assert decide({"action": "build", "project": "laser-trigger"}) == want


def test_same_folder_same_key_other_env_other_key(tmp_path, no_build):
    d = fw_dir(tmp_path)
    link = tmp_path / "link"
    link.symlink_to(d, target_is_directory=True)
    (tmp_path / "sub").mkdir()
    base = decide({"action": "build", "project_dir": str(d), "env": "s3"})["rule_key"]
    assert decide({"action": "build", "project_dir": str(link), "env": "s3"})["rule_key"] == base
    assert decide({"action": "build", "project_dir": str(tmp_path / "sub" / ".." / "fw"), "env": "s3"})["rule_key"] == base
    other = decide({"action": "build", "project_dir": str(d), "env": "c3"})
    assert other["action"] == "approve" and other["rule_key"] != base and other["message"].startswith("Build env c3 with")
    assert decide({"action": "build", "project_dir": str(fw_dir(tmp_path, "fw2")), "env": "s3"})["rule_key"] != base


def test_cron_blocks_the_real_build(tmp_path, monkeypatch, no_build):
    d = fw_dir(tmp_path)
    args = {"action": "build", "project_dir": str(d), "env": "s3"}
    d1 = decide(args, tools.Host(cron=lambda: True, hook_active=True))
    assert d1["action"] == "block"
    assert tools.BUILD_CRON_MSG in d1["message"]
    assert tools.BUILD_CRON_MSG == ("scheduled jobs (cron) cannot run real builds: a build runs the firmware "
                                    "project's own PlatformIO scripts")
    monkeypatch.setenv("HERMES_CRON_SESSION", "1")
    assert decide(args)["action"] == "block"
    # a sim build that starts no pio is unchanged in cron: no directive (see test_build_approval.py for the pio case)
    assert decide({**args, "port": SIM}) is None


def test_contradicting_project_dir_blocks_with_the_handler_text(tmp_path, no_build):
    d = fw_dir(tmp_path)
    other = fw_dir(tmp_path, "other")
    mk(fw=d)
    args = {"action": "build", "project": "laser-trigger", "project_dir": str(other)}
    handler = call(tools.Host(hook_active=True), **args)
    assert handler["error"]["code"] == "invalid_args"
    d1 = decide(args)
    assert d1["action"] == "block" and handler["error"]["message"] in d1["message"]
    d2 = decide({"action": "build", "project": "laser-trigger", "env": "c3"})
    assert d2["action"] == "block" and "give either project or env" in d2["message"]
    mk("nofw")
    d3 = decide({"action": "build", "project": "nofw"})
    assert d3["action"] == "block" and "has no firmware folder" in d3["message"]
    d4 = decide({"action": "build", "env": "s3"})
    assert d4["action"] == "block" and "project_dir is required" in d4["message"]


def test_exception_in_build_target_blocks(tmp_path, monkeypatch, no_build):
    def boom(args):
        raise RuntimeError("unexpected")

    monkeypatch.setattr(tools, "build_target", boom)
    d1 = decide({"action": "build", "project_dir": str(fw_dir(tmp_path)), "env": "s3"})
    assert d1["action"] == "block" and "RuntimeError" in d1["message"]


# --------------------------------------------------------------------------------------------- handler

def test_handler_refuses_real_build_in_cron(tmp_path, monkeypatch, no_build):
    d = fw_dir(tmp_path)
    env = call(tools.Host(cron=lambda: True, hook_active=True), action="build", project_dir=str(d), env="s3")
    assert env["error"]["code"] == "unattended_blocked" and "cron" in env["error"]["message"]
    monkeypatch.setenv("HERMES_CRON_SESSION", "1")
    mk(fw=d)
    env = call(tools.Host(hook_active=True), action="build", project="laser-trigger")
    assert env["error"]["code"] == "unattended_blocked"


def test_handler_refuses_real_build_without_hook(tmp_path, no_build):
    env = call(tools.Host(hook_active=False), action="build", project_dir=str(fw_dir(tmp_path)), env="s3")
    assert env == tools._no_hook("board.build")
    assert env["error"]["code"] == "not_confirmed" and "hook" in env["error"]["message"]


def test_handler_builds_exactly_the_target(tmp_path, built):
    d = fw_dir(tmp_path)
    link = tmp_path / "link"
    link.symlink_to(d, target_is_directory=True)
    host = tools.Host(hook_active=True)
    assert decide({"action": "build", "project_dir": str(link), "env": "s3", "port": REAL}, host)["action"] == "approve"
    env = call(host, action="build", project_dir=str(link), env="s3", port=REAL)
    assert env["error"]["code"] == "tool_missing"
    assert built == [(d.resolve(), "s3", None)]


def test_sim_build_unchanged_without_hook_and_in_cron(tmp_path):
    d = fw_dir(tmp_path)
    for host in (tools.Host(hook_active=False), tools.Host(cron=lambda: True, hook_active=False)):
        env = call(host, action="build", project_dir=str(d), env="s3", port=SIM)
        assert env["ok"] and env["simulated"], env


def test_bench_board_description_mentions_build_approval():
    from circuit_bench import schemas
    desc = schemas.BOARD["description"]
    assert "Real builds, flashes and ports need approval." in desc and len(desc) <= 500


def test_folder_without_platformio_ini_gets_no_question(tmp_path, no_build):
    """Nothing can build there: no approval question; the handler refuses before pio starts."""
    d = tmp_path / "empty"
    d.mkdir()
    assert decide({"action": "build", "project_dir": str(d), "env": "s3"}) is None
    env = call(tools.Host(hook_active=True), action="build", project_dir=str(d), env="s3")
    assert env["ok"] is False
