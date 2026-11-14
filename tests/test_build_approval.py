"""A simulated build that would start PlatformIO is asked like a real one; crash decoding never starts ``pio``;
argument errors name the next step. PlatformIO never starts here: ``clitools.run`` and ``board.build`` are tripwires
wherever a build could happen."""
import json
import os
import sys
import types

import board_fixtures as bf
import pytest

from circuit_bench import hooks, tools
from circuit_bench.bench_core import board, clitools, contracts, project, serialport, sim

SIM = "sim://test-s3"
SHA = "a" * 64


class Recording(bf.TestProvider):
    """A provider without ``build_runs_pio`` (the method is optional) that records its builds."""

    def __init__(self):
        super().__init__()
        self.builds: list[tuple] = []

    def build(self, project_dir, env):
        self.builds.append((project_dir, env))
        return super().build(project_dir, env)


class Asking(Recording):
    def build_runs_pio(self, project_dir, env):
        return True


class Raising(Recording):
    def build_runs_pio(self, project_dir, env):
        raise RuntimeError("prediction failed")


@pytest.fixture(autouse=True)
def _isolation(monkeypatch):
    import circuit_bench.bench_core as core

    def no_port_list():
        raise AssertionError("test called the real serial port list")

    monkeypatch.setattr(board, "_comports", no_port_list)
    monkeypatch.delattr(core, "sim", raising=False)
    monkeypatch.setitem(sys.modules, "circuit_bench.bench_core.sim", None)  # a TestProvider plays sim://
    cfg = types.ModuleType("hermes_cli.config")
    cfg.load_config = lambda: {"approvals": {"mode": "manual"}}
    pkg = types.ModuleType("hermes_cli")
    pkg.config = cfg
    monkeypatch.setitem(sys.modules, "hermes_cli", pkg)
    monkeypatch.setitem(sys.modules, "hermes_cli.config", cfg)
    monkeypatch.delenv("HERMES_YOLO_MODE", raising=False)
    monkeypatch.delenv("HERMES_CRON_SESSION", raising=False)
    yield
    from circuit_bench.bench_core import runtime
    b = runtime.peek("broker")
    if b is not None:
        b.shutdown()


def hook_host():
    return tools.Host(hook_active=True)


def cron_host():
    return tools.Host(cron=lambda: True, hook_active=True)


def no_hook_host():
    return tools.Host(hook_active=False)


def fw_dir(tmp_path, name="fw"):
    d = tmp_path / name
    d.mkdir(exist_ok=True)
    (d / "platformio.ini").write_text("[env:s3]\nplatform = espressif32\n", encoding="utf-8")
    (d / "src").mkdir(exist_ok=True)
    (d / "src" / "main.cpp").write_text("void setup() {}\nvoid loop() {}\n", encoding="utf-8")
    return d


def args_sim(d):
    return {"action": "build", "project_dir": str(d), "env": "s3", "port": SIM}


def decide(host, args):
    cb = hooks.make_pre_tool_call(host)
    return cb(tool_name="bench_board", args=args, task_id="t", session_id="s", tool_call_id="c")


def call(host, name, **args):
    env = json.loads(tools.make_handlers(host)[name](args, task_id="t"))  # the task id of decide()
    assert contracts.validate_envelope(env) == [], env
    return env


# --------------------------------------------------------------------------------------------- sim build approval

def test_sim_build_without_pio_never_asks(tmp_path):
    d = fw_dir(tmp_path)
    board.register_provider("sim://", Recording())  # no build_runs_pio: the simulated build runs no script
    args = args_sim(d)
    assert decide(hook_host(), args) is None
    assert decide(cron_host(), args) is None
    assert call(cron_host(), "bench_board", **args)["ok"] is True
    assert call(no_hook_host(), "bench_board", **args)["ok"] is True


def test_sim_build_that_starts_pio_asks(short_tmp):
    d = fw_dir(short_tmp)
    board.register_provider("sim://", Asking())
    d1 = decide(hook_host(), args_sim(d))
    assert d1["action"] == "approve"
    assert d1["rule_key"] == hooks.build_rule_key(str(d.resolve()), "s3")
    assert d1["message"].endswith(f'The board is simulated; the build is a real offline build. Folder: "{d.resolve()}"')
    assert d1["message"].startswith("Build env s3 with PlatformIO?")


def test_sim_build_that_starts_pio_shares_the_rule_key_with_a_real_build(tmp_path):
    d = fw_dir(tmp_path)
    board.register_provider("sim://", Asking())
    sim_key = decide(hook_host(), args_sim(d))["rule_key"]
    real = decide(hook_host(), {"action": "build", "project_dir": str(d), "env": "s3"})
    assert real["action"] == "approve" and real["rule_key"] == sim_key
    assert "real offline build." not in real["message"]


def test_sim_build_that_starts_pio_is_refused_in_cron_and_without_hook(tmp_path):
    d = fw_dir(tmp_path)
    prov = Asking()
    board.register_provider("sim://", prov)
    args = args_sim(d)
    blocked = decide(cron_host(), args)
    assert blocked["action"] == "block" and tools.BUILD_CRON_MSG in blocked["message"]
    env = call(cron_host(), "bench_board", **args)
    assert env["ok"] is False and env["error"]["code"] == "unattended_blocked"
    assert call(no_hook_host(), "bench_board", **args)["error"]["code"] == "not_confirmed"
    assert prov.builds == []  # the provider was never called


def test_sim_build_that_starts_pio_runs_after_the_hook(tmp_path):
    d = fw_dir(tmp_path)
    prov = Asking()
    board.register_provider("sim://", prov)
    host = hook_host()
    assert decide(host, args_sim(d))["action"] == "approve"
    env = call(host, "bench_board", **args_sim(d))
    assert env["ok"] is True and env["simulated"] is True
    assert prov.builds == [(str(d.resolve()), "s3")]


def test_provider_error_means_ask(tmp_path):
    d = fw_dir(tmp_path)
    board.register_provider("sim://", Raising())
    assert decide(hook_host(), args_sim(d))["action"] == "approve"
    assert board.build_runs_pio(d, "s3", SIM) is True


def test_build_runs_pio_by_port(tmp_path):
    d = fw_dir(tmp_path)
    board.register_provider("sim://", Recording())
    assert board.build_runs_pio(d, "s3") is True  # no port
    assert board.build_runs_pio(d, "s3", "/dev/ttyCB0") is True  # a real port
    assert board.build_runs_pio(d, "s3", SIM) is False  # provider without the method


def test_sim_project_asks_like_an_explicit_sim_port(short_tmp):
    d = fw_dir(short_tmp)
    board.register_provider("sim://", Asking())
    assert project.create("laser-trigger", "Laser trigger", "esp32s3", "n16r8")["ok"]
    ops = [{"op": "set_firmware", "dir": str(d), "env": "s3"},
           {"op": "set_detected", "port": SIM, "mac": "aa:bb:cc:dd:ee:ff", "chip": "ESP32-S3 (QFN56)"}]
    assert project.update("laser-trigger", 1, ops, by="ui", trusted=True)["ok"]
    d1 = decide(hook_host(), {"action": "build", "project": "laser-trigger"})
    assert d1["action"] == "approve" and 'the build is a real offline build. Folder: "' in d1["message"]


def test_simboard_prediction_and_build_share_one_condition(monkeypatch, tmp_path):
    d = fw_dir(tmp_path)
    monkeypatch.setattr(sim, "TIME_SCALE", 0.0)
    ran = []
    monkeypatch.setattr(sim.SimBoard, "_real_build", lambda self, pdir, env, crash: ran.append((pdir, env)) or
                        {"ok": True, "real": True})
    monkeypatch.setattr(sim, "_real_build_ready", lambda pdir, env: (True, []))
    board_ = sim.SimBoard()
    assert board_.build_runs_pio(str(d), "s3") is True
    assert board_.build(str(d), "s3") == {"ok": True, "real": True}
    assert ran == [(d.resolve(), "s3")]
    monkeypatch.setattr(sim, "_real_build_ready", lambda pdir, env: (False, ["x"]))
    ran.clear()
    assert board_.build_runs_pio(str(d), "s3") is False
    res = board_.build(str(d), "s3")
    assert ran == [] and res["simulated"] is True and res["result"]["toolchain"] == "simulated"


def test_simboard_prediction_is_false_for_a_bad_folder_or_env(tmp_path):
    d = fw_dir(tmp_path)
    board_ = sim.SimBoard()
    assert board_.build_runs_pio(str(tmp_path / "nowhere"), "s3") is False
    assert board_.build_runs_pio(str(d), "nope") is False


def test_real_build_ready_needs_pio_and_the_switch(monkeypatch, tmp_path):
    d = fw_dir(tmp_path)
    monkeypatch.setattr(sim, "_real_build_wanted", lambda: False)
    monkeypatch.setattr(sim, "_pio", lambda: "/x/pio")
    assert sim._real_build_ready(d, "s3") == (False, [])
    monkeypatch.setattr(sim, "_real_build_wanted", lambda: True)
    monkeypatch.setattr(sim, "_pio", lambda: None)
    assert sim._real_build_ready(d, "s3") == (False, [])
    monkeypatch.setattr(sim, "_pio", lambda: "/x/pio")
    monkeypatch.setattr(sim, "_offline_ready", lambda pdir, env: (False, ["espressif32"]))
    assert sim._real_build_ready(d, "s3") == (False, ["espressif32"])
    monkeypatch.setattr(sim, "_offline_ready", lambda pdir, env: (True, []))
    assert sim._real_build_ready(d, "s3") == (True, [])


# --------------------------------------------------------------------------------------------- crash decode

def _log():
    return (os.path.join(os.path.dirname(__file__), "fixtures", "crash", "arduino_timestamps.log"))


def _read_log():
    with open(_log(), encoding="utf-8") as f:
        return f.read()


def mk_real_project(host, d):
    env = call(host, "bench_project", action="create", id="laser-trigger", title="Laser trigger", chip="esp32s3",
               variant="n16r8", devkit="esp32-s3-devkitc-1")
    assert env["ok"], env
    env = call(host, "bench_project", action="set_firmware", id="laser-trigger", firmware_dir=str(d), env="s3")
    assert env["ok"], env


def test_crash_decode_with_project_never_starts_pio(tmp_path, monkeypatch):
    fake = tmp_path / "fakebin"
    fake.mkdir()
    for name in ("esptool", "pio"):
        (fake / name).symlink_to(bf.FAKES_BIN / name)
    monkeypatch.setenv("PATH", f"{fake}{os.pathsep}{os.environ['PATH']}")
    fake_tools = bf.FakeTools(fake)
    fake_tools.scenario("board-pio-build-ok.json")
    d = fw_dir(tmp_path)
    mk_real_project(hook_host(), d)
    host = hook_host()
    assert decide(host, {"action": "build", "project": "laser-trigger"})["action"] == "approve"
    env = call(host, "bench_board", action="build", project="laser-trigger")
    assert env["ok"] and env["simulated"] is False, env
    before = len(fake_tools.calls("pio"))
    assert before >= 1
    for host in (hook_host(), cron_host()):
        env = call(host, "bench_crash", action="decode", log=_read_log(), project="laser-trigger")
        assert env["ok"], env
        assert len(fake_tools.calls("pio")) == before  # no `pio project metadata`, no other pio call


def test_crash_decode_without_stored_build_warns_and_never_starts_pio(tmp_path, monkeypatch):
    def trip(*a, **k):
        raise AssertionError("no process may start")

    monkeypatch.setattr(clitools, "run", trip)
    d = fw_dir(tmp_path)
    mk_real_project(hook_host(), d)
    ref = serialport.write_artifact("panic", _read_log().splitlines())
    env = call(hook_host(), "bench_crash", action="decode", log_ref=ref, project="laser-trigger")
    assert env["ok"], env
    (w,) = [w for w in env["warnings"] if w["code"] == "elf_lookup_failed"]
    assert w["severity"] == "info"
    assert w["message"] == ("no ELF from the project: no successful build is stored; run bench_board build with "
                            "project laser-trigger, or pass elf")


def test_crash_decode_with_deleted_elf_warns(tmp_path, monkeypatch):
    def trip(*a, **k):
        raise AssertionError("no process may start")

    monkeypatch.setattr(clitools, "run", trip)
    d = fw_dir(tmp_path)
    mk_real_project(hook_host(), d)
    ops = [{"op": "set_build", "ok": True, "elf_sha256": SHA, "elf": ".pio/build/s3/firmware.elf"}]
    assert project.update("laser-trigger", 2, ops, by="ui", trusted=True)["ok"]
    assert not (d / ".pio").exists()  # the ELF of the last build is gone
    env = call(hook_host(), "bench_crash", action="decode", log=_read_log(), project="laser-trigger")
    assert env["ok"] and any(w["code"] in ("elf_lookup_failed", "elf_missing") for w in env["warnings"]), env


def test_tools_never_ask_pio_for_metadata():
    import inspect
    assert "metadata(" not in inspect.getsource(tools)


def test_last_build_elf():
    fw = {"dir": "/work/fw", "env": "s3"}
    assert project.last_build_elf({}) is None
    assert project.last_build_elf({"firmware": fw}) is None
    assert project.last_build_elf({"firmware": {**fw, "last_build": {"ok": False, "elf": "a.elf"}}}) is None
    assert project.last_build_elf({"firmware": {**fw, "last_build": {"ok": True}}}) is None
    assert project.last_build_elf({"firmware": {**fw, "last_build": {"ok": True, "elf": "b/a.elf"}}}) == "/work/fw/b/a.elf"
    assert project.last_build_elf({"firmware": {**fw, "last_build": {"ok": True, "elf": "/abs/a.elf"}}}) == "/abs/a.elf"


# --------------------------------------------------------------------------------------------- hints

HINT_CASES = [
    ("bench_board", {"action": "build"}, "pass project"),
    ("bench_board", {"action": "build", "project_dir": "/x"}, "NAME of an [env:NAME]"),
    ("bench_project", {"action": "set_firmware", "id": "x", "firmware_dir": "/x"}, "NAME of an [env:NAME]"),
    ("bench_board", {"action": "detect"}, "bench_board ports"),
    ("bench_board", {"action": "monitor"}, "sim://esp32s3-n16r8"),
    ("bench_solder", {"action": "plan"}, "pass project (its parts list) or bom"),
    ("bench_calc", {"action": "led"}, "pass them inside inputs: {v_supply, v_f, i_f, series}"),
    ("bench_calc", {"action": "led", "inputs": {"v_supply": "3V3", "v_f": "2V", "i_f": "10mA", "colour": "red"}},
     "parameters: v_supply, v_f, i_f, series"),  # an unknown name inside inputs: the hint lists the names only
]


@pytest.mark.parametrize("name,args,word", HINT_CASES)
def test_argument_errors_name_the_next_step(name, args, word):
    err = call(hook_host(), name, **args)["error"]
    assert err["code"] == "invalid_args" and word in err["hint"]
