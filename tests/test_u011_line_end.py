"""Names checked with a pattern ending in ``$`` and ``re.match`` also accepted a trailing line break (``"s3\\n"``):
``$`` matches right before a final ``\\n``. Every input check uses ``fullmatch`` now; valid names stay valid."""
import json
import sys
import types

import pytest

from circuit_bench import hooks, tools
from circuit_bench.bench_core import board, calckit, events, pins, project, serialport, sim
from circuit_bench.bench_core.contracts import BenchError

VALID_ENVS = ["s3", "esp32-s3-devkitc-1", "a.b:c_d", "_x", "Env_1", "s" * 64]
BAD_ENV = "s3\n"
ENV_REFUSAL = "bad PlatformIO environment name"


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
    monkeypatch.setenv("CIRCUIT_BENCH_HW", "off")
    monkeypatch.setattr(board, "_tool", lambda name: pytest.fail(f"{name} would start"))


def fw(parent, envs=("s3",)):
    d = parent / "fw"
    d.mkdir()
    (d / "platformio.ini").write_text("".join(f"[env:{e}]\nplatform = espressif32\n" for e in envs), encoding="utf-8")
    (d / "src").mkdir()
    (d / "src" / "main.cpp").write_text("void setup() {}\nvoid loop() {}\n", encoding="utf-8")
    return d


def handler(args, host=None):
    return json.loads(tools.make_handlers(host or tools.Host(hook_active=True))["bench_board"](args, task_id="t"))


# --------------------------------------------------------------------------------------------- build env

def test_the_env_rule_refuses_a_trailing_line_break_in_all_three_modules():
    for rx in (board._ENV_RE, project._ENV_RE, sim._ENV_RE):
        assert rx.pattern == board._ENV_RE.pattern  # one rule
    with pytest.raises(BenchError) as e:
        board._check_env(BAD_ENV)
    assert e.value.code == "invalid_args" and ENV_REFUSAL in e.value.message
    for env in VALID_ENVS:
        assert board._check_env(env) == env


def test_the_tool_entrance_strips_the_line_break_and_asks_for_exactly_that_env(short_tmp, monkeypatch):
    """bench_board strips outer whitespace of every text argument: "s3\\n" arrives as "s3", the question names s3
    and the build runs s3, so nothing differs between question and run."""
    monkeypatch.setenv("CIRCUIT_BENCH_HW", "on")  # the hook only decides
    d = fw(short_tmp)
    args = {"action": "build", "project_dir": str(d), "env": BAD_ENV}
    assert tools.build_target(args).env == "s3"
    dec = hooks.decide(tools.Host(hook_active=True), "bench_board", args, "t")
    assert dec["action"] == "approve" and dec["message"].startswith("Build env s3 with PlatformIO?"), dec
    assert dec["rule_key"] == hooks.build_rule_key(str(d.resolve()), "s3")


@pytest.mark.parametrize("env", ["s3\nx", "s3\n\nOK", "s\r3"])
def test_the_hook_blocks_a_build_env_with_a_line_break_inside(short_tmp, monkeypatch, env):
    monkeypatch.setenv("CIRCUIT_BENCH_HW", "on")  # the hook only decides
    dec = hooks.decide(tools.Host(hook_active=True), "bench_board",
                       {"action": "build", "project_dir": str(fw(short_tmp)), "env": env}, "t")
    assert dec is not None and dec["action"] == "block", dec
    assert "invalid_args" in dec["message"] and ENV_REFUSAL in dec["message"]


def test_board_build_refuses_it_before_pio_starts(tmp_path):
    env = board.build(fw(tmp_path), BAD_ENV)
    assert env["ok"] is False and env["error"]["code"] == "invalid_args" and ENV_REFUSAL in env["error"]["message"]


def test_the_simulated_build_refuses_it(tmp_path):
    d = fw(tmp_path)
    env = board.build(d, BAD_ENV, port="sim://esp32s3-n16r8")
    assert env["ok"] is False and env["error"]["code"] == "invalid_args", env
    assert ENV_REFUSAL in env["error"]["message"]
    with pytest.raises(BenchError) as e:
        sim._env(d, BAD_ENV)
    assert ENV_REFUSAL in e.value.message


@pytest.mark.parametrize("env", VALID_ENVS)
def test_valid_env_names_still_pass_every_check(tmp_path, env):
    d = fw(tmp_path, envs=(env,))
    assert board._check_env(env) == env and sim._env(d, env) == env
    assert project.create("p", "P", "esp32s3", "n16r8")["ok"]
    up = project.update("p", 1, [{"op": "set_firmware", "dir": str(d), "env": env}], by="ui", trusted=True)
    assert up["ok"], up
    assert project.get("p")["result"]["project"]["firmware"]["env"] == env


def test_set_firmware_refuses_it(tmp_path):
    assert project.create("p", "P", "esp32s3", "n16r8")["ok"]
    up = project.update("p", 1, [{"op": "set_firmware", "dir": str(fw(tmp_path)), "env": BAD_ENV}], by="ui",
                        trusted=True)
    assert up["ok"] is False and up["error"]["code"] == "invalid_args", up
    assert "set_firmware.env" in up["error"]["message"]


def test_a_project_file_with_such_an_env_does_not_load(tmp_path):
    assert project.create("p", "P", "esp32s3", "n16r8")["ok"]
    assert project.update("p", 1, [{"op": "set_firmware", "dir": str(fw(tmp_path)), "env": "s3"}], by="ui",
                          trusted=True)["ok"]
    file = project.path("p") / "project.json"
    obj = json.loads(file.read_text(encoding="utf-8"))
    obj["firmware"]["env"] = BAD_ENV
    file.write_text(json.dumps(obj), encoding="utf-8")
    got = project.get("p")
    assert got["ok"] is False, got
    assert "firmware.env" in json.dumps(got["error"])
    assert project._ENV_RE.fullmatch(BAD_ENV) is None
    with pytest.raises(BenchError):
        project._text(BAD_ENV, "firmware.env", 64, pattern=project._ENV_RE, multiline=True)  # the pattern alone


# --------------------------------------------------------------------------------------------- other names

def test_a_project_id_with_a_line_break_is_refused():
    for pid in ("demo\n", "laser-trigger\n"):
        env = project.create(pid, "P", "esp32s3", "n16r8")
        assert env["ok"] is False and env["error"]["code"] == "invalid_args", env
        with pytest.raises(BenchError):
            project._check_id(pid)
        with pytest.raises(BenchError):
            sim.copy_example("laser-trigger\n", "p")
    assert project._check_id("laser-trigger") == "laser-trigger"


def test_other_checked_names_refuse_a_trailing_line_break():
    with pytest.raises(BenchError):
        project._iso("2026-11-06T21:41:07Z\n", "at")
    assert project._iso("2026-11-06T21:41:07Z", "at") == "2026-11-06T21:41:07Z"
    with pytest.raises(BenchError) as e:
        serialport.artifact_path("panic-20261114-120000.log\n")
    assert e.value.code == "invalid_args"
    with pytest.raises(BenchError):
        pins._validate_role("LASER\n")
    assert pins._validate_role("LASER") == "LASER"
    with pytest.raises(ValueError, match="invalid event name"):
        events._check_name("project.changed\n")
    with pytest.raises(ValueError, match="calc kind must match"):
        calckit.register("led\n", dict, (), title="t", group="g", summary="s")
    with pytest.raises(BenchError):
        board.register_provider("x://\n", object())
    for port in ("COM3\n", "/dev/ttyACM0\n"):
        with pytest.raises(BenchError):
            serialport.normalize_port(port)
    assert serialport.normalize_port("COM3") == "COM3"
