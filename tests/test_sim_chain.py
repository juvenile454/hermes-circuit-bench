"""The whole sim chain as in scripts/sim_probe.py (the probe's chain() runs here inside the test isolation)."""
from __future__ import annotations

import importlib.util
import os
from pathlib import Path

import pytest

from circuit_bench.bench_core import clitools, project, sim

PROBE = Path(__file__).resolve().parent.parent / "scripts" / "sim_probe.py"


@pytest.fixture
def probe():
    spec = importlib.util.spec_from_file_location("cb_sim_probe", PROBE)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(autouse=True)
def _fast(monkeypatch):
    monkeypatch.setattr(sim, "TIME_SCALE", 0.0)
    yield
    from circuit_bench.bench_core import runtime
    b = runtime.peek("broker")
    if b is not None:
        b.shutdown()


def test_sim_chain_like_the_probe(probe, monkeypatch):
    def no_tools(*a, **kw):
        raise AssertionError("the sim chain must not run a real tool")
    monkeypatch.setattr(clitools, "run", no_tools)
    lines: list[str] = []
    res = probe.chain(lines.append, timeout=20.0)
    names = [s["step"] for s in res["steps"]]
    assert names[:2] == ["sim.demo", "board.detect"]
    assert names.count("board.build") == 2 and names.count("board.flash") == 2 and "crash.decode" in names
    assert all(s["ok"] is True and s["simulated"] is True for s in res["steps"]), res["steps"]
    assert res["panic"]["summary"] == "StoreProhibited · core 1"
    top = res["decode"]["result"]["frames"][0]
    assert (top["file"], top["line"]) == ("src/main.cpp", 44)
    p = res["project"]
    assert p["debug"]["last_panic"]["reason"] == "StoreProhibited" and p["debug"]["last_panic"]["log_ref"]
    assert p["firmware"]["last_build"]["ok"] is True and p["board"]["detected"]["simulated"] is True
    assert sim.board_state()["firmware"] == "fixed"
    assert "     serial: [laser-trigger] boot ok" in lines
    assert any("refused (elf_mismatch)" in line for line in lines)
    assert [e["id"] for e in project.list_projects()["result"]["projects"]] == ["laser-trigger"]


def _isolated_env(probe, tmp: Path):
    """Run _isolate(tmp); return (SystemExit or None, the environment it set). The process environment is restored."""
    saved = dict(os.environ)  # _isolate() changes the process environment on purpose
    try:
        try:
            probe._isolate(tmp, toolchain=False)
            err = None
        except SystemExit as e:
            err = e
        return err, dict(os.environ)
    finally:
        os.environ.clear()
        os.environ.update(saved)


def test_isolate_sets_a_temporary_home_and_checks_it(probe, monkeypatch, tmp_path):
    """_isolate() sets HOME, HERMES_HOME and the data dir under its folder, then checks HERMES_HOME in Python."""
    home = tmp_path / "account"
    monkeypatch.setattr(probe, "_real_home", lambda: home)
    checked = []
    real_check = probe.live_home_refusal
    monkeypatch.setattr(probe, "live_home_refusal", lambda hh, rh: checked.append((hh, rh)) or real_check(hh, rh))
    err, isolated = _isolated_env(probe, tmp_path / "t")
    assert err is None
    hh = str(tmp_path / "t" / "hhome")
    assert checked == [(hh, home)]
    assert isolated["HERMES_HOME"] == hh and isolated["CIRCUIT_BENCH_DATA_DIR"] == str(tmp_path / "t" / "data")
    assert isolated["HOME"] == str(tmp_path / "t" / "home") and "PYTHONPATH" not in isolated
    assert isolated["CIRCUIT_BENCH_HW"] == "off" and isolated["CIRCUIT_BENCH_DEV_GUARD"] == "1"


def test_isolate_refuses_a_folder_inside_the_live_home(probe, monkeypatch, tmp_path):
    """A temporary folder inside <home>/.hermes (outside cache/scratch) is refused before anything runs."""
    home = tmp_path / "account"
    monkeypatch.setattr(probe, "_real_home", lambda: home)
    err, _ = _isolated_env(probe, home / ".hermes" / "tmp" / "t")
    assert err is not None and "is the live Hermes home" in str(err.code)
    err, isolated = _isolated_env(probe, home / ".hermes" / "cache" / "scratch" / "t")
    assert err is None and isolated["HERMES_HOME"] == str(home / ".hermes" / "cache" / "scratch" / "t" / "hhome")


def test_live_home_refusal(probe, tmp_path):
    home = tmp_path / "account"
    live = home / ".hermes"
    scratch = live / "cache" / "scratch"
    (scratch / "hhome-x").mkdir(parents=True)
    other = tmp_path / "elsewhere"
    other.mkdir()
    (other / "link-to-live").symlink_to(live, target_is_directory=True)
    (live / "link-to-other").symlink_to(other, target_is_directory=True)
    refusal = probe.live_home_refusal

    for ok in [scratch, scratch / "hhome-x", scratch / "missing" / "deeper", other, tmp_path / "account-2" / ".hermes",
               home, home / ".hermes-other", live / "link-to-other"]:
        assert refusal(str(ok), home) is None, ok
    for bad in [live, live / "plugins", live / "missing", live / "cache", live / "cache" / "scratch-x",
                scratch / ".." / "x", other / "link-to-live", other / "link-to-live" / "cache"]:
        msg = refusal(str(bad), home)
        assert msg and "is the live Hermes home" in msg, bad
    for unset in [None, ""]:
        msg = refusal(unset, home)
        assert msg and "is not set" in msg and os.path.realpath(live) in msg
    # a relative path is resolved against the working directory, like realpath -m
    cwd = os.getcwd()
    try:
        os.chdir(live)
        assert refusal("sub", home) and refusal("cache/scratch/sub", home) is None
    finally:
        os.chdir(cwd)
