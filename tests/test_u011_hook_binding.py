"""The handler uses a real board (or starts PlatformIO) only after the pre_tool_call hook let exactly this call through:
the hook leaves a grant per task, action and target; the handler of the same task takes it when it starts. One grant,
one handler run; no task id, no grant. Real boards are never touched: board, serial and build calls are fakes."""
import hashlib
import json
import sys
import threading
import types
from pathlib import Path

import board_fixtures as bf
import pytest

from circuit_bench import hooks, tools
from circuit_bench.bench_core import board, contracts, project, serialport

PORT = "/dev/ttyCB0"  # never exists; every board call below is a fake
OTHER_PORT = "/dev/ttyCB1"
SIM = "sim://test-s3"
SHA = "d" * 64
MAC = "aa:bb:cc:dd:ee:ff"
PID = "binding"


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    import circuit_bench.bench_core as core
    cfg = types.ModuleType("hermes_cli.config")
    cfg.value = {"approvals": {"mode": "manual"}}
    cfg.load_config = lambda: cfg.value
    pkg = types.ModuleType("hermes_cli")
    pkg.config = cfg
    monkeypatch.setitem(sys.modules, "hermes_cli", pkg)
    monkeypatch.setitem(sys.modules, "hermes_cli.config", cfg)
    monkeypatch.delenv("HERMES_YOLO_MODE", raising=False)
    monkeypatch.delenv("HERMES_CRON_SESSION", raising=False)
    monkeypatch.setenv("CIRCUIT_BENCH_HW", "on")  # board, serial and build calls are fakes (fixture ``calls``)
    monkeypatch.setenv("CIRCUIT_BENCH_SETTINGS_JSON", json.dumps({"allow_flash": True}))
    monkeypatch.setattr(board, "_comports", lambda: pytest.fail("real serial port list"))
    monkeypatch.delattr(core, "sim", raising=False)
    monkeypatch.setitem(sys.modules, "circuit_bench.bench_core.sim", None)  # a TestProvider plays sim://
    return cfg


@pytest.fixture
def calls(monkeypatch):
    """Fakes for everything that would touch a board or start PlatformIO; records each call."""
    seen: list[tuple] = []

    def detect(port, devkit=None):
        seen.append(("detect", port))
        return contracts.envelope("board.detect", "detected", {"port": port, "mac": MAC, "chip": "ESP32-S3"})

    def monitor(port, seconds, baud=None, reset=False):
        seen.append(("monitor", port))
        return contracts.envelope("serial.monitor", "read", {"port": port, "lines": 0})

    def build(project_dir, env, port=None, chip=None):
        seen.append(("build", str(project_dir), env))
        return contracts.envelope("board.build", "built", {"ok": True, "elf_sha256": SHA})

    def flash(project_dir, env, port, *, expected_elf_sha256, guard, expected_images=None, devkit=None,
              expected_board=None):
        assert guard() is None
        seen.append(("flash", port, expected_elf_sha256))
        return contracts.envelope("board.flash", "flashed", {"ok": True, "port": port, "mac": MAC,
                                                             "elf_sha256": expected_elf_sha256})

    monkeypatch.setattr(board, "detect", detect)
    monkeypatch.setattr(serialport, "monitor", monitor)
    monkeypatch.setattr(board, "build", build)
    monkeypatch.setattr(board, "flash", flash)
    return seen


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def host(clock):
    return tools.Host(hook_active=True, clock=clock)


def hook(host, args, task_id="task-1"):
    cb = hooks.make_pre_tool_call(host)
    return cb(tool_name="bench_board", args=args, task_id=task_id, session_id="s", tool_call_id="call-1",
              turn_id="turn-1")


def run(host, args, **kw):
    env = json.loads(tools.make_handlers(host)["bench_board"](args, **kw))
    assert contracts.validate_envelope(env) == [], env
    return env


def refused(env, code="not_confirmed"):
    return env["ok"] is False and env["error"]["code"] == code


def fw_dir(tmp_path, name="fw"):
    d = tmp_path / name
    d.mkdir(exist_ok=True)
    (d / "platformio.ini").write_text("[env:s3]\nplatform = espressif32\n", encoding="utf-8")
    return d


def flash_ready(tmp_path, pid=PID):
    assert project.create(pid, "Binding", "esp32s3", "n16r8")["ok"]
    env = project.update(pid, 1, [
        {"op": "set_detected", "port": PORT, "mac": MAC, "chip": "ESP32-S3 (QFN56)"},
        {"op": "set_firmware", "dir": str(fw_dir(tmp_path)), "env": "s3"},
        {"op": "set_build", "ok": True, "elf_sha256": SHA}], by="ui", trusted=True)
    assert env["ok"], env
    return {"action": "flash", "project": pid, "elf_sha256": SHA}


def detect_args(port=PORT):
    return {"action": "detect", "port": port}


def monitor_args(port=PORT):
    return {"action": "monitor", "port": port, "seconds": 1}


def build_args(d):
    return {"action": "build", "project_dir": str(d), "env": "s3"}


def all_args(tmp_path):
    return {"detect": detect_args(), "monitor": monitor_args(), "build": build_args(fw_dir(tmp_path)),
            "flash": flash_ready(tmp_path)}


ACTIONS = ("detect", "monitor", "build", "flash")


# --------------------------------------------------------------------------------------------- no grant, no run

@pytest.mark.parametrize("action", ACTIONS)
def test_handler_without_a_hook_pass_is_refused(host, calls, tmp_path, action):
    args = all_args(tmp_path)[action]
    env = run(host, args, task_id="task-1")
    assert refused(env) and "hook" in env["error"]["message"], env
    assert calls == []


@pytest.mark.parametrize("action", ACTIONS)
def test_one_hook_pass_allows_exactly_one_run(host, calls, tmp_path, action):
    args = all_args(tmp_path)[action]
    assert hook(host, args)["action"] == "approve"
    env = run(host, args, task_id="task-1")
    assert env["ok"] is True, env
    assert len(calls) == 1 and calls[0][0] == action
    env = run(host, args, task_id="task-1")  # the grant is used up
    assert refused(env) and len(calls) == 1


@pytest.mark.parametrize("action", ACTIONS)
def test_the_grant_is_used_up_even_when_the_run_is_refused(host, calls, tmp_path, monkeypatch, action):
    args = all_args(tmp_path)[action]
    assert hook(host, args)["action"] == "approve"
    flag = {"cron": True}
    cron_host = tools.Host(cron=lambda: flag["cron"], hook_active=True, clock=host._clock)
    cron_host._grants, cron_host._grant_lock = host._grants, host._grant_lock  # the same grants, now in cron
    assert refused(run(cron_host, args, task_id="task-1"), "unattended_blocked")
    assert refused(run(host, args, task_id="task-1"))
    assert calls == []


# --------------------------------------------------------------------------------------------- task, action, target

@pytest.mark.parametrize("action", ACTIONS)
def test_handler_without_task_id_finds_no_grant(host, calls, tmp_path, action):
    """Like ctx.dispatch_tool or registry.dispatch without arguments: no task id, no grant (left for the task)."""
    args = all_args(tmp_path)[action]
    assert hook(host, args)["action"] == "approve"
    assert refused(run(host, args))
    assert refused(run(host, args, task_id=""))
    assert refused(run(host, args, task_id="   "))
    assert refused(run(host, args, task_id=None))
    assert calls == []
    assert run(host, args, task_id="task-1")["ok"] is True  # still there for the task that passed the hook


@pytest.mark.parametrize("action", ACTIONS)
def test_hook_without_task_id_leaves_no_grant(host, calls, tmp_path, action):
    args = all_args(tmp_path)[action]
    assert hook(host, args, task_id="")["action"] == "approve"
    assert hooks.decide(host, "bench_board", args)["action"] == "approve"  # no task id at all
    assert host._grants == {}
    assert refused(run(host, args, task_id=""))
    assert refused(run(host, args, task_id="task-1"))
    assert calls == []


@pytest.mark.parametrize("action", ACTIONS)
def test_grant_of_another_task_does_not_count(host, calls, tmp_path, action):
    args = all_args(tmp_path)[action]
    assert hook(host, args, task_id="parent")["action"] == "approve"
    assert refused(run(host, args, task_id="child"))
    assert calls == []
    assert run(host, args, task_id="parent")["ok"] is True


def test_grant_for_another_port_does_not_count(host, calls):
    assert hook(host, detect_args(PORT))["action"] == "approve"
    assert refused(run(host, detect_args(OTHER_PORT), task_id="task-1"))
    assert hook(host, monitor_args(PORT))["action"] == "approve"
    assert refused(run(host, monitor_args(OTHER_PORT), task_id="task-1"))
    assert calls == []


def test_grant_for_another_action_does_not_count(host, calls):
    assert hook(host, detect_args())["action"] == "approve"
    assert refused(run(host, monitor_args(), task_id="task-1"))
    assert hook(host, monitor_args())["action"] == "approve"  # a new pass of the task removes the detect grant
    assert refused(run(host, detect_args(), task_id="task-1"))
    assert run(host, monitor_args(), task_id="task-1")["ok"] is True
    assert calls == [("monitor", PORT)]


def test_grant_for_another_build_folder_or_env_does_not_count(host, calls, tmp_path):
    a, b = fw_dir(tmp_path, "a"), fw_dir(tmp_path, "b")
    assert hook(host, build_args(a))["action"] == "approve"
    assert refused(run(host, build_args(b), task_id="task-1"))
    assert hook(host, build_args(a))["action"] == "approve"
    assert refused(run(host, {**build_args(a), "env": "other"}, task_id="task-1"))
    assert calls == []


def test_flash_grant_names_port_board_firmware_and_folder(host, calls, tmp_path):
    args = flash_ready(tmp_path)
    assert hook(host, args)["action"] == "approve"
    rev = project.get(PID)["result"]["rev"]
    other = fw_dir(tmp_path, "other")
    assert project.update(PID, rev, [{"op": "set_firmware", "dir": str(other), "env": "s3"},
                                     {"op": "set_build", "ok": True, "elf_sha256": SHA}], by="ui", trusted=True)["ok"]
    env = run(host, args, task_id="task-1")
    assert refused(env) and "firmware folder changed" in env["error"]["message"]
    assert hook(host, args)["action"] == "approve"
    assert refused(run(host, {**args, "port": OTHER_PORT}, task_id="task-1"))  # another port: another target
    assert calls == []


def test_a_new_hook_pass_replaces_the_old_grant(host, calls):
    for _ in range(3):
        assert hook(host, detect_args())["action"] == "approve"
    assert len(host._grants) == 1
    assert run(host, detect_args(), task_id="task-1")["ok"] is True
    assert refused(run(host, detect_args(), task_id="task-1"))
    assert calls == [("detect", PORT)]


def test_two_tasks_at_the_same_time_do_not_disturb_each_other(host, monkeypatch):
    barrier = threading.Barrier(2, timeout=10)
    seen: list[str] = []

    def detect(port, devkit=None):
        barrier.wait()  # both handlers are inside at the same time
        seen.append(port)
        return contracts.envelope("board.detect", "detected", {"port": port, "mac": MAC, "chip": "ESP32-S3"})

    monkeypatch.setattr(board, "detect", detect)
    assert hook(host, detect_args(), task_id="child-a")["action"] == "approve"
    assert hook(host, detect_args(), task_id="child-b")["action"] == "approve"
    results: dict[str, dict] = {}

    def worker(task):
        results[task] = run(host, detect_args(), task_id=task)

    threads = [threading.Thread(target=worker, args=(t,)) for t in ("child-a", "child-b")]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=20)
    assert results["child-a"]["ok"] is True and results["child-b"]["ok"] is True
    assert seen == [PORT, PORT] and host._grants == {}


# --------------------------------------------------------------------------------------------- lifetime

@pytest.mark.parametrize(("timeout", "ttl"), [
    (None, 360), ("missing", 360), (300, 360), ("300", 360), (200, 260), (30, 120), (0, 120), (-5, 120),
    (5000, 3600), ("abc", 360), ("12.5", 360), ([1], 360), ({"a": 1}, 360),
])
def test_grant_lifetime_follows_the_approval_timeout(_env, timeout, ttl):
    _env.value = {"approvals": {"mode": "manual"} if timeout == "missing" else {"mode": "manual", "timeout": timeout}}
    assert tools.grant_ttl() == ttl


def test_grant_lifetime_without_a_readable_config(_env, monkeypatch):
    monkeypatch.setitem(sys.modules, "hermes_cli", None)  # no Hermes at all
    assert tools.grant_ttl() == 360
    monkeypatch.setitem(sys.modules, "hermes_cli", types.ModuleType("hermes_cli"))  # a Hermes without its reader
    monkeypatch.setitem(sys.modules, "hermes_cli.config", types.ModuleType("hermes_cli.config"))
    assert tools.grant_ttl() == 360


@pytest.mark.parametrize("action", ACTIONS)
def test_an_expired_grant_does_not_count(host, calls, clock, tmp_path, action):
    args = all_args(tmp_path)[action]
    assert hook(host, args)["action"] == "approve"
    clock.now += 360
    assert refused(run(host, args, task_id="task-1"))
    assert calls == []


def test_a_grant_just_before_its_end_counts(host, calls, clock, _env):
    _env.value = {"approvals": {"mode": "manual", "timeout": 100}}  # 160 s
    assert hook(host, detect_args())["action"] == "approve"
    clock.now += 159.5
    assert run(host, detect_args(), task_id="task-1")["ok"] is True


def test_expired_grants_are_removed_when_the_next_is_stored(host, clock):
    assert hook(host, detect_args(PORT))["action"] == "approve"
    clock.now += 400
    assert hook(host, detect_args(OTHER_PORT))["action"] == "approve"
    assert [k[2] for k in host._grants] == [OTHER_PORT]


# --------------------------------------------------------------------------------------------- hook decisions

def test_approve_serial_off_leaves_a_grant_without_asking(host, calls, monkeypatch):
    monkeypatch.setenv("CIRCUIT_BENCH_SETTINGS_JSON", json.dumps({"allow_flash": True, "approve_serial": False}))
    for args in (detect_args(), monitor_args()):
        assert hook(host, args) is None  # nothing to ask
        assert run(host, args, task_id="task-1")["ok"] is True
        assert refused(run(host, args, task_id="task-1"))
    assert [c[0] for c in calls] == ["detect", "monitor"]


@pytest.mark.parametrize("action", ACTIONS)
def test_a_blocked_call_leaves_no_grant(host, calls, tmp_path, monkeypatch, action):
    args = all_args(tmp_path)[action]
    monkeypatch.setenv("HERMES_CRON_SESSION", "1")
    assert hook(host, args)["action"] == "block"
    monkeypatch.delenv("HERMES_CRON_SESSION")
    assert host._grants == {}
    assert refused(run(host, args, task_id="task-1"))
    assert calls == []


def test_deny_leaves_nothing_usable_without_the_task(host, calls, tmp_path):
    """After "deny" Hermes does not start the handler; the grant stays until it expires, but a call without the task
    id (another plugin's ctx.dispatch_tool) or of another task cannot use it."""
    args = all_args(tmp_path)
    for action in ACTIONS:
        assert hook(host, args[action])["action"] == "approve"  # the user then says "deny"
    for action in ACTIONS:
        assert refused(run(host, args[action]))
        assert refused(run(host, args[action], task_id="another-task"))
    assert calls == []


def test_the_hook_reads_the_task_id_from_its_keywords(host, calls):
    cb = hooks.make_pre_tool_call(host)
    assert cb(tool_name="bench_board", args=detect_args(), task_id="kw-task")["action"] == "approve"
    assert run(host, detect_args(), task_id="kw-task")["ok"] is True
    assert cb(tool_name="bench_board", args=detect_args())["action"] == "approve"  # no task id: no grant
    assert refused(run(host, detect_args(), task_id=""))


def test_without_the_hook_registered_the_old_answer_stays(clock, calls, tmp_path):
    nohook = tools.Host(hook_active=False, clock=clock)
    for action, args in all_args(tmp_path).items():
        hook(nohook, args)  # a stray pass must not count while the hook is not registered
        env = run(nohook, args, task_id="task-1")
        assert refused(env) and env["error"]["message"] == tools.NO_HOOK_MSG, action
    assert calls == []


# --------------------------------------------------------------------------------------------- sim://

def test_sim_ports_need_no_grant(clock, calls):
    prov = bf.TestProvider()
    board.register_provider("sim://", prov)
    nohook = tools.Host(hook_active=False, clock=clock)
    env = run(nohook, {"action": "detect", "port": SIM})  # no task id, no hook
    assert env["ok"] is True, env
    assert calls == [("detect", SIM)]  # board.detect is the fake here; the sim port reached it without a grant


class Asking(bf.TestProvider):
    def build_runs_pio(self, project_dir, env):
        return True


class NoPio(bf.TestProvider):
    def build_runs_pio(self, project_dir, env):
        return False


def test_sim_build_that_starts_pio_needs_a_grant(host, calls, tmp_path):
    board.register_provider("sim://", Asking())
    args = {**build_args(fw_dir(tmp_path)), "port": SIM}
    assert refused(run(host, args, task_id="task-1"))
    assert hook(host, args)["action"] == "approve"
    assert run(host, args, task_id="task-1")["ok"] is True
    assert refused(run(host, args, task_id="task-1"))
    assert [c[0] for c in calls] == ["build"]


def test_sim_build_without_pio_needs_no_grant(clock, calls, tmp_path):
    board.register_provider("sim://", NoPio())
    nohook = tools.Host(hook_active=False, clock=clock)
    args = {**build_args(fw_dir(tmp_path)), "port": SIM}
    assert hooks.decide(nohook, "bench_board", args, "task-1") is None
    assert nohook._grants == {}
    assert run(nohook, args)["ok"] is True


def test_build_grants_of_a_sim_and_a_real_target_are_separate(host, calls, tmp_path):
    board.register_provider("sim://", Asking())
    d = fw_dir(tmp_path)
    assert hook(host, {**build_args(d), "port": SIM})["action"] == "approve"
    assert refused(run(host, build_args(d), task_id="task-1"))
    assert calls == []


def test_build_folder_without_platformio_ini_keeps_its_own_error(host, calls, tmp_path):
    d = tmp_path / "empty"
    d.mkdir()
    assert hook(host, build_args(d)) is None  # nothing can build there: nothing asked, no grant
    env = run(host, build_args(d), task_id="task-1")
    assert refused(env, "invalid_args") and "platformio.ini" in env["error"]["message"]
    assert calls == []


# --------------------------------------------------------------------------------------------- unchanged parts

def test_routes_do_not_use_the_tool_grants():
    """Bench UI routes have their own confirmations (``via="route"``); they never look at the hook's grants."""
    root = Path(tools.__file__).resolve().parent / "dashboard"
    text = "\n".join(p.read_text(encoding="utf-8") for p in root.rglob("*.py"))
    assert "tools.Host" not in text and ".take(" not in text and ".grant(" not in text


def test_rule_keys_are_unchanged(host, tmp_path):
    args = flash_ready(tmp_path)
    d = hook(host, args)
    assert d["rule_key"] == "circuit-bench:flash:" + hashlib.sha256(f"{PORT}|{MAC}|{SHA}".encode()).hexdigest()
    assert hook(host, detect_args())["rule_key"] == "circuit-bench:detect:" + hashlib.sha256(PORT.encode()).hexdigest()



# --------------------------------------------------------------------------------------------- one grant per task

def task_grants(host, task="task-1"):
    return [k for k in host._grants if k[0] == task]


def _fails_in_hooks(real):
    """``real``, except when the hook module itself calls it (after its checks): then it raises."""
    def wrapped(*a, **kw):
        if sys._getframe(1).f_globals.get("__name__") == hooks.__name__:
            raise RuntimeError("unreadable")
        return real(*a, **kw)
    return wrapped


def _raises(*a, **kw):
    raise RuntimeError("unreadable")


@pytest.mark.parametrize(("action", "where"), [
    ("flash", "approval_path"), ("build", "approval_path"),
    ("flash", "_shown"), ("build", "_shown"), ("detect", "_port_shown"), ("monitor", "_port_shown"),
    ("detect", "settings"), ("monitor", "settings"),
])
def test_an_internal_error_late_in_the_hook_leaves_no_grant(host, calls, tmp_path, monkeypatch, action, where):
    from circuit_bench.bench_core import settings
    args = all_args(tmp_path)[action]
    assert hook(host, args)["action"] == "approve"  # an earlier pass left a grant (the user then said "deny")
    assert hook(host, detect_args(OTHER_PORT), task_id="task-2")["action"] == "approve"
    with monkeypatch.context() as m:
        if where == "settings":
            m.setattr(settings, "load", _fails_in_hooks(settings.load))
        else:
            m.setattr(hooks, where, _raises)
        d = hook(host, args)
    assert d["action"] == "block" and "approval check failed" in d["message"], d
    assert task_grants(host) == []
    assert refused(run(host, args, task_id="task-1"))
    assert calls == []
    assert task_grants(host, "task-2") != []  # another task keeps its grant


def test_a_build_pass_without_platformio_ini_removes_the_grant_left_after_deny(host, calls, tmp_path):
    d = fw_dir(tmp_path)
    args = build_args(d)
    assert hook(host, args)["action"] == "approve"  # the user says "deny": Hermes does not start the handler
    ini = d / "platformio.ini"
    ini.rename(d / "platformio.off")
    assert hook(host, args) is None  # nothing can build there: nothing asked
    (d / "platformio.off").rename(ini)  # the file is back before the handler starts
    assert task_grants(host) == []
    assert refused(run(host, args, task_id="task-1"))
    assert calls == []  # PlatformIO did not start


def test_every_pass_clears_the_grants_of_its_task(host, calls, tmp_path):
    d = fw_dir(tmp_path)
    assert hook(host, build_args(d))["action"] == "approve"
    assert hook(host, build_args(d), task_id="task-2")["action"] == "approve"
    assert hook(host, detect_args())["action"] == "approve"  # same task, another action and target
    assert refused(run(host, build_args(d), task_id="task-1"))
    assert run(host, build_args(d), task_id="task-2")["ok"] is True  # another task's grant is untouched
    assert run(host, detect_args(), task_id="task-1")["ok"] is True
    assert [c[0] for c in calls] == ["build", "detect"]


def test_a_task_has_at_most_one_unused_grant(host, tmp_path):
    for args in all_args(tmp_path).values():
        assert hook(host, args)["action"] == "approve"
        assert len(task_grants(host)) == 1


BLOCK_ROWS = [(row, a) for row in ("cron", "cron_probe", "cron_probe_fails") for a in ACTIONS] + [
    (row, a) for row in ("hardware_off", "approvals_off", "yolo") for a in ("detect", "monitor", "flash")] + [
    ("allow_flash_off", "flash"), ("flash_without_sha", "flash"), ("flash_sha_not_last_build", "flash"),
    ("flash_bad_sha", "flash"), ("flash_unknown_project", "flash"), ("build_unknown_project", "build"),
    ("serial_bad_port", "detect"), ("serial_bad_port", "monitor"),
]


@pytest.mark.parametrize(("row", "action"), BLOCK_ROWS)
def test_a_blocking_pass_removes_the_old_grant_of_its_task(host, calls, tmp_path, monkeypatch, _env, row, action):
    args = all_args(tmp_path)[action]
    assert hook(host, args)["action"] == "approve"  # left after "deny"
    assert hook(host, detect_args(OTHER_PORT), task_id="task-2")["action"] == "approve"
    passing, blocked_args = host, args
    with monkeypatch.context() as m:
        if row == "cron":
            m.setenv("HERMES_CRON_SESSION", "1")
        elif row.startswith("cron_probe"):
            probe = (lambda: True) if row == "cron_probe" else _raises
            passing = tools.Host(cron=probe, hook_active=True, clock=host._clock)
            passing._grants, passing._grant_lock = host._grants, host._grant_lock  # the same grants
        elif row == "hardware_off":
            m.setenv("CIRCUIT_BENCH_HW", "off")
        elif row == "approvals_off":
            m.setattr(_env, "value", {"approvals": {"mode": "off"}})
        elif row == "yolo":
            m.setenv("HERMES_YOLO_MODE", "1")
        elif row == "allow_flash_off":
            m.setenv("CIRCUIT_BENCH_SETTINGS_JSON", json.dumps({"allow_flash": False}))
        elif row == "flash_without_sha":
            blocked_args = {k: v for k, v in args.items() if k != "elf_sha256"}
        elif row == "flash_sha_not_last_build":
            blocked_args = {**args, "elf_sha256": "e" * 64}
        elif row == "flash_bad_sha":
            blocked_args = {**args, "elf_sha256": "zz"}
        elif row == "flash_unknown_project":
            blocked_args = {**args, "project": "nope"}
        elif row == "build_unknown_project":
            blocked_args = {"action": "build", "project": "nope"}  # a target error on a real target
        elif row == "serial_bad_port":
            blocked_args = {**args, "port": "/dev/./ttyCB0"}
        d = hook(passing, blocked_args)
    assert d is not None and d["action"] == "block", d
    assert task_grants(host) == []
    assert refused(run(host, args, task_id="task-1"))
    assert calls == []
    assert task_grants(host, "task-2") != []  # another task keeps its grant


@pytest.mark.parametrize(("row", "action"), [
    ("sim_port", "detect"), ("sim_port", "monitor"), ("sim_port", "flash"), ("sim_port", "build"),
    ("sim_build_bad_args", "build"), ("no_platformio_ini", "build"), ("bad_port", "detect"), ("bad_port", "monitor"),
])
def test_a_pass_that_needs_no_grant_removes_the_old_grant_of_its_task(host, calls, tmp_path, row, action):
    board.register_provider("sim://", NoPio())
    args = all_args(tmp_path)[action]
    assert hook(host, args)["action"] == "approve"  # left after "deny"
    other = {**args, "port": SIM}
    if row == "sim_build_bad_args":
        other["env"] = "bad env"
    elif row == "no_platformio_ini":
        empty = tmp_path / "empty"
        empty.mkdir()
        other = build_args(empty)
    elif row == "bad_port":
        other = {**args, "port": "  "}  # the handler answers bad ports itself
    assert hook(host, other) is None
    assert host._grants == {}
    assert refused(run(host, args, task_id="task-1"))
    assert calls == []


@pytest.mark.parametrize("approve_serial", [True, False])
def test_a_task_runs_its_calls_one_after_another(host, calls, tmp_path, monkeypatch, approve_serial):
    """What Hermes does: for each call the hook, then the handler."""
    monkeypatch.setenv("CIRCUIT_BENCH_SETTINGS_JSON", json.dumps({"allow_flash": True,
                                                                  "approve_serial": approve_serial}))
    args = all_args(tmp_path)
    for action in ("detect", "build", "flash", "monitor"):
        d = hook(host, args[action])
        if action in ("detect", "monitor") and not approve_serial:
            assert d is None
        else:
            assert d["action"] == "approve", (action, d)
        assert run(host, args[action], task_id="task-1")["ok"] is True, action
        assert host._grants == {}
    assert [c[0] for c in calls] == ["detect", "build", "flash", "monitor"]


# --------------------------------------------------------------------------------------------- hints of the refusals

@pytest.mark.parametrize("action", ("detect", "monitor", "build"))
def test_with_the_hook_but_without_a_pass_the_hint_says_to_call_again(host, calls, clock, tmp_path, action):
    """Reloading the plugin would not help here: the hook is registered, the call only has no pass (expired, another
    task, a handler reached directly)."""
    args = all_args(tmp_path)[action]
    for task in ("task-1", "", None):
        env = run(host, args, task_id=task)
        assert refused(env) and env["error"]["message"] == tools.NO_GRANT_MSG, env
        assert env["error"]["hint"] == f"call bench_board {action} again: Hermes asks the user first; sim:// ports still work"
        assert "reload" not in env["error"]["hint"]
    hook(host, args, task_id="task-1")
    clock.now += tools.grant_ttl() + 1  # the pass expired
    env = run(host, args, task_id="task-1")
    assert refused(env) and env["error"]["hint"].startswith(f"call bench_board {action} again")
    assert calls == []


def test_a_flash_without_a_pass_keeps_its_own_hint(host, calls, tmp_path):
    env = run(host, flash_ready(tmp_path), task_id="task-1")
    assert refused(env) and env["error"]["hint"] == "call bench_board flash again (Hermes asks the user first)"
    assert calls == []


@pytest.mark.parametrize("action", ACTIONS)
def test_without_the_hook_registered_the_hint_says_to_reload(clock, calls, tmp_path, action):
    nohook = tools.Host(hook_active=False, clock=clock)
    env = run(nohook, all_args(tmp_path)[action], task_id="task-1")
    assert refused(env) and env["error"]["hint"] == tools.NO_HOOK_HINT
    assert calls == []
