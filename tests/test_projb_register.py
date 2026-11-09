"""register() wiring, HOOK_ACTIVE, the /bench command and the bundled esp32-bench skill."""
import inspect
import json
import re
import sys
import types
from pathlib import Path

import pytest

import circuit_bench
from circuit_bench import commands, hooks, schemas, tools
from circuit_bench.bench_core import project

SKILL = Path(circuit_bench.__file__).resolve().parent / "skills" / "esp32-bench" / "SKILL.md"
VIEWS = {"pins", "calc", "wire", "solder", "flash", "crash"}  # the Bench views


class FakeCtx:
    def __init__(self, *, hook_fails=False, cron=None, with_cron=True, with_skill=True):
        self.tools, self.hooks, self.commands, self.skills = {}, {}, {}, {}
        self.hook_fails = hook_fails
        self.cron_value = cron
        if not with_cron:
            self.current_cron_execution = None
        if not with_skill:
            self.register_skill = None

    def register_tool(self, name, toolset, schema, handler, check_fn=None, requires_env=None, is_async=False,
                      description="", emoji="", override=False):
        self.tools[name] = {"toolset": toolset, "schema": schema, "handler": handler, "emoji": emoji}

    def register_hook(self, hook_name, callback):
        if self.hook_fails:
            raise RuntimeError("hooks disabled")
        self.hooks.setdefault(hook_name, []).append(callback)

    def register_command(self, name, handler, description="", args_hint="", argument_mode=None):
        self.commands[name] = {"handler": handler, "description": description, "args_hint": args_hint}

    def register_skill(self, name, path, description="", frontmatter=None):
        self.skills[name] = {"path": Path(path), "description": description, "frontmatter": frontmatter}

    def current_cron_execution(self):
        return self.cron_value


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    monkeypatch.setattr(hooks, "HOOK_ACTIVE", False)
    monkeypatch.setitem(sys.modules, "circuit_bench.bench_core.sim", None)
    cfg = types.ModuleType("hermes_cli.config")
    cfg.load_config = dict
    pkg = types.ModuleType("hermes_cli")
    pkg.config = cfg
    monkeypatch.setitem(sys.modules, "hermes_cli", pkg)
    monkeypatch.setitem(sys.modules, "hermes_cli.config", cfg)
    monkeypatch.delenv("HERMES_YOLO_MODE", raising=False)
    monkeypatch.delenv("HERMES_CRON_SESSION", raising=False)


def test_register_everything():
    ctx = FakeCtx()
    circuit_bench.register(ctx)
    assert list(ctx.tools) == list(schemas.NAMES)
    for name, t in ctx.tools.items():
        assert t["toolset"] == "circuit-bench" and t["schema"]["name"] == name and t["emoji"]
        params = inspect.signature(t["handler"]).parameters.values()
        assert inspect.Parameter.VAR_KEYWORD in [p.kind for p in params]  # Hermes filters kwargs by signature
    assert list(ctx.hooks) == ["pre_tool_call"] and hooks.HOOK_ACTIVE is True
    assert list(ctx.commands) == ["bench"] and ctx.commands["bench"]["args_hint"] == "[doctor|ports|projects]"
    assert list(ctx.skills) == ["esp32-bench"]
    skill = ctx.skills["esp32-bench"]
    assert skill["path"] == SKILL and skill["description"].startswith("Use when")
    assert skill["frontmatter"]["name"] == "esp32-bench"


def test_handlers_answer_json_with_dispatch_kwargs():
    ctx = FakeCtx()
    circuit_bench.register(ctx)
    out = ctx.tools["bench_project"]["handler"]({"action": "list"}, task_id="t", session_id="s", user_task="u")
    assert json.loads(out)["action"] == "project.list"


def _ready_real_project(tmp_path, monkeypatch):
    monkeypatch.setenv("CIRCUIT_BENCH_HW", "on")
    monkeypatch.setenv("CIRCUIT_BENCH_SETTINGS_JSON", json.dumps({"allow_flash": True}))
    fw = tmp_path / "fw"
    fw.mkdir()
    (fw / "platformio.ini").write_text("[env:s3]\n", encoding="utf-8")
    assert project.create("p1", "P1", "esp32s3", "n16r8")["ok"]
    assert project.update("p1", 1, [{"op": "set_detected", "port": "/dev/ttyCB0", "mac": "aa:bb:cc:dd:ee:ff",
                                     "chip": "ESP32-S3 (QFN56) (revision v0.2)"},  # chip check
                                    {"op": "set_firmware", "dir": str(fw), "env": "s3"},
                                    {"op": "set_build", "ok": True, "elf_sha256": "d" * 64}], by="ui", trusted=True)["ok"]


def test_missing_hook_refuses_real_boards(tmp_path, monkeypatch, caplog):
    from circuit_bench.bench_core import board
    monkeypatch.setattr(board, "flash", lambda *a, **k: pytest.fail("board.flash ran without the hook"))
    _ready_real_project(tmp_path, monkeypatch)
    ctx = FakeCtx(hook_fails=True)
    circuit_bench.register(ctx)
    assert ctx.hooks == {} and hooks.HOOK_ACTIVE is False
    assert "approval hook not registered" in caplog.text
    env = json.loads(ctx.tools["bench_board"]["handler"]({"action": "flash", "project": "p1"}))
    assert env["error"]["code"] == "not_confirmed" and "hook" in env["error"]["message"]
    for action in ("detect", "monitor"):
        env = json.loads(ctx.tools["bench_board"]["handler"]({"action": action, "port": "/dev/ttyCB0", "seconds": 1}))
        assert env["error"]["code"] == "not_confirmed", action


def test_cron_is_bound_from_the_context(tmp_path, monkeypatch):
    _ready_real_project(tmp_path, monkeypatch)
    ctx = FakeCtx(cron=types.SimpleNamespace(job_id="j1"))
    circuit_bench.register(ctx)
    hook = ctx.hooks["pre_tool_call"][0]
    d = hook(tool_name="bench_board", args={"action": "flash", "project": "p1"})
    assert d["action"] == "block" and "cron" in d["message"]
    env = json.loads(ctx.tools["bench_board"]["handler"]({"action": "flash", "project": "p1"}))
    assert env["error"]["code"] == "unattended_blocked"
    ctx.cron_value = None
    assert hook(tool_name="bench_board", args={"action": "flash", "project": "p1", "elf_sha256": "d" * 12})["action"] == "approve"


def test_older_core_without_cron_and_skill(monkeypatch):
    ctx = FakeCtx(with_cron=False, with_skill=False)
    circuit_bench.register(ctx)
    assert len(ctx.tools) == 7 and ctx.skills == {}
    monkeypatch.setenv("HERMES_CRON_SESSION", "true")
    d = ctx.hooks["pre_tool_call"][0](tool_name="bench_board", args={"action": "detect", "port": "/dev/ttyCB0"})
    assert d["action"] == "block"


def test_optional_surfaces_never_stop_the_tools():
    ctx = FakeCtx()

    def bad(*a, **k):
        raise ValueError("nope")

    ctx.register_command = bad
    ctx.register_skill = bad
    circuit_bench.register(ctx)
    assert len(ctx.tools) == 7 and hooks.HOOK_ACTIVE is True


def test_skill_frontmatter_parser():
    meta = circuit_bench.skill_frontmatter(SKILL.read_text(encoding="utf-8"))
    assert meta["name"] == "esp32-bench" and meta["version"] == "0.1.0"
    assert circuit_bench.skill_frontmatter("no frontmatter") == {}
    assert circuit_bench.skill_frontmatter("---\nname: x\n") == {}  # not closed
    assert circuit_bench.skill_frontmatter("\ufeff---\nname: 'x'\n# c\n  nested: y\n---\n") == {"name": "x"}


# --------------------------------------------------------------------------------------------- skill

def test_skill_contents():
    text = SKILL.read_text(encoding="utf-8")
    assert len(text.splitlines()) <= 120
    assert text.isascii() or all(ord(c) < 0x2500 or c in "→…" for c in text)
    for name in schemas.NAMES:
        assert f"`{name}" in text, name
    assert "PLAN → CALC → WIRE → SOLDER → FLASH → DEBUG" in text
    assert "passed" in text and "sources" in text and "rule of thumb" in text
    for word in ("mains", "Laser", "Li-ion", "approve", "tool_search", "tool_call", "Desktop", "simulated"):
        assert word.lower() in text.lower(), word
    directives = re.findall(r'::bench\{project="([^"]+)" view="([^"]+)"\}', text)
    assert directives and all(view in VIEWS for _, view in directives)
    assert all(pid == "laser-trigger" for pid, _ in directives)
    listed = set(re.findall(r"`(\w+)`", text.split("`view` is one of", 1)[1].split("(", 1)[0]))
    assert listed == VIEWS


# --------------------------------------------------------------------------------------------- /bench

def test_bench_without_projects():
    out = commands.make_command()("")
    assert "Projects: none yet" in out and "Hardware access: off" in out and "Agent flashing: off" in out
    assert commands.USAGE in out and "bench_board" in out


def test_bench_subcommands(monkeypatch):
    assert project.create("laser-trigger", "Laser trigger", "esp32s3", "n16r8")["ok"]
    bench = commands.make_command()
    assert "laser-trigger: Laser trigger (esp32s3 N16R8), rev 1" in bench("projects")
    ports = bench("ports")  # hardware off: only the simulated board is listed
    assert ports.startswith("Ports: 1 port: sim://esp32s3-n16r8 (simulated)") and "hardware access is off" in ports
    out = bench("doctor")
    assert out.startswith("Doctor:") and "[ok  ] data_dir" in out
    assert bench("PROJECTS extra words") == bench("projects")
    assert bench("format c:").startswith("Unknown /bench option 'format'")
    monkeypatch.setenv("HERMES_YOLO_MODE", "1")
    assert "Approvals are off or YOLO is on" in bench("")


def test_bench_never_raises(monkeypatch):
    monkeypatch.setattr(commands, "overview", lambda: 1 / 0)
    assert "failed (ZeroDivisionError)" in commands.make_command()("")
    assert "Usage" in commands.make_command()(None)  # type: ignore[arg-type]


def test_bench_with_damaged_data_folder(monkeypatch):
    from circuit_bench.bench_core import storage

    def broken():
        from circuit_bench.bench_core.contracts import BenchError
        raise BenchError("dependency_missing", "no data folder")

    monkeypatch.setattr(storage, "data_dir", broken)
    out = commands.make_command()("projects")
    assert "unavailable" in out


def test_tools_names_in_command_text():
    assert commands.TOOLS == ", ".join(schemas.NAMES)
    assert tools.DEFAULT_ACTION.keys() == set(schemas.NAMES)


def test_register_and_handlers_without_schemdraw_and_pyserial(monkeypatch):
    """Leitplanke 9: Hermes does not install missing dependencies; the plugin must load and answer anyway."""
    import builtins
    import importlib
    real_import = builtins.__import__

    def guarded(name, *a, **kw):
        if name.split(".")[0] in ("schemdraw", "serial"):
            raise ImportError(f"blocked for test: {name}")
        return real_import(name, *a, **kw)

    for name in list(sys.modules):
        if name == "circuit_bench" or name.startswith("circuit_bench."):
            monkeypatch.delitem(sys.modules, name)
    monkeypatch.setitem(sys.modules, "circuit_bench.bench_core.sim", None)
    monkeypatch.setattr(builtins, "__import__", guarded)
    fresh = importlib.import_module("circuit_bench")
    ctx = FakeCtx()
    fresh.register(ctx)
    assert len(ctx.tools) == 7 and "pre_tool_call" in ctx.hooks
    env = json.loads(ctx.tools["bench_schematic"]["handler"]({"action": "render", "block": "led",
                                                              "params": {"r_series": "270"}}))
    assert env["error"]["code"] == "dependency_missing"
    env = json.loads(ctx.tools["bench_board"]["handler"]({"action": "ports"}))
    assert env["ok"] is True
    assert "dependencies: missing" in ctx.commands["bench"]["handler"]("doctor")
