"""Tools together with the simulated board.

The demo project and the sim:// provider through the tools: demo, detect, build, flash, monitor, crash decode.
"""
import json
import sys
import types

import pytest

from circuit_bench import tools
from circuit_bench.bench_core import contracts, project, runtime, sim


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    cfg = types.ModuleType("hermes_cli.config")
    cfg.load_config = dict
    pkg = types.ModuleType("hermes_cli")
    pkg.config = cfg
    monkeypatch.setitem(sys.modules, "hermes_cli", pkg)
    monkeypatch.setitem(sys.modules, "hermes_cli.config", cfg)
    yield
    b = runtime.peek("broker")
    if b is not None:
        b.shutdown()


@pytest.fixture
def host():
    return tools.Host(hook_active=False)  # sim:// needs no hook


def call(host, name, **args):
    out = tools.make_handlers(host)[name](args)
    env = json.loads(out)
    assert contracts.validate_envelope(env) == [], env
    assert len(out.encode("utf-8")) <= tools.MAX_BYTES
    return env


def test_demo_through_the_tool_is_idempotent(host):
    env = call(host, "bench_project", action="demo")
    assert env["ok"] and env["action"] == "sim.demo" and env["simulated"] is True, env
    p = env["result"]  # sim.demo answers with a short form (< 8 kB); the whole project comes from project.get
    assert p["id"] == "laser-trigger" and p["simulated"] is True and p["board"]["variant"] and p["port"] == "sim://esp32s3-n16r8"
    rev = project.get("laser-trigger")["result"]["rev"]
    assert call(host, "bench_project", action="demo")["ok"]
    assert project.get("laser-trigger")["result"]["rev"] == rev
    assert not any(a["verdict"] == "blocked" for a in p["assignments"])


def test_sim_chain_through_the_tools(host):
    assert call(host, "bench_project", action="demo")["ok"]
    ports = [p["device"] for p in call(host, "bench_board", action="ports")["result"]["ports"]]
    port = next(p for p in ports if p.startswith("sim://"))
    env = call(host, "bench_board", action="detect", port=port, project="laser-trigger")
    assert env["ok"] and env["simulated"], env
    env = call(host, "bench_board", action="build", project="laser-trigger")
    assert env["ok"] and env["simulated"], env
    env = call(host, "bench_board", action="flash", project="laser-trigger")
    assert env["ok"] and env["simulated"], env
    env = call(host, "bench_board", action="monitor", port=port, seconds=8)
    assert env["ok"] and env["simulated"], env
    panics = env["result"]["panics"]
    if panics:
        env = call(host, "bench_crash", action="decode", log_ref=panics[0]["log_ref"], project="laser-trigger")
        assert env["ok"], env
        assert project.get("laser-trigger")["result"]["project"]["debug"]["last_panic"]


def test_crash_decode_uses_the_sim_runner(host, monkeypatch):
    assert call(host, "bench_project", action="demo")["ok"]
    used = []
    real = sim.crash_runner

    def spy(project_dir=None):
        used.append(1)
        return real(project_dir)

    monkeypatch.setattr(sim, "crash_runner", spy)
    log = ("Guru Meditation Error: Core  1 panic'ed (StoreProhibited). Exception was unhandled.\n"
           "Backtrace: 0x42001d67:0x3fcebe50 0x42003a1d:0x3fcebe70\n")
    env = call(host, "bench_crash", action="decode", log=log, project="laser-trigger")
    assert used == [1] and env["ok"], env
    assert env["simulated"] is True  # crash.decode reads run.simulated
