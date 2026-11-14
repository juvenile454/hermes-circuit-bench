"""Every `pio run` of the plugin names its targets (the `targets` option of platformio.ini never runs).

PlatformIO Core 6.2.0 run/cli.py ``process_env``: ``targets = targets or config.get(f"env:{name}", "targets", [])``.
Without ``-t`` a project with ``targets = upload, monitor`` would upload and open the monitor during a "build".
"""
import json
import os
import subprocess
import sys

import pytest
import board_fixtures as bf
from board_fixtures import *  # noqa: F403

from circuit_bench.bench_core import board, clitools, sim
from conftest import HardwareAccessRefused

UPLOAD_INI = ("[env:s3]\nplatform = espressif32@6.9.0\nboard = esp32-s3-devkitc-1\nframework = arduino\n"
              "targets = upload, monitor\n")


@pytest.fixture
def upload_project(tmp_path):
    d = tmp_path / "fw"
    (d / "src").mkdir(parents=True)
    (d / "platformio.ini").write_text(UPLOAD_INI, encoding="utf-8")
    (d / "src" / "main.cpp").write_text("void setup() {}\nvoid loop() {}\n", encoding="utf-8")
    return d


def _run_calls(fake_tools):
    return [c["argv"] for c in fake_tools.calls("pio") if c["argv"][:1] == ["run"]]


def test_build_names_its_targets_even_with_upload_targets_in_the_ini(fake_tools, upload_project):
    fake_tools.scenario("board-pio-build-ok.json")
    env = board.build(upload_project, "s3")
    assert env["ok"], env["error"]
    (argv,) = _run_calls(fake_tools)
    assert clitools.pio_targets(argv) == ["checkprogsize", "buildprog"]
    assert not any(t in argv for t in ("upload", "monitor", "nobuild", "--upload-port"))
    assert clitools.touches_hardware(["pio", *argv]) is False


def test_build_with_hardware_off_never_runs_pio_without_targets(fake_tools, upload_project, monkeypatch):
    """Reproduction of the reported case: HW off, ini with upload targets -> only explicit build targets."""
    monkeypatch.setenv("CIRCUIT_BENCH_HW", "off")
    fake_tools.scenario("board-pio-build-ok.json")
    board.build(upload_project, "s3")
    for argv in _run_calls(fake_tools):
        assert clitools.pio_targets(argv), argv


def test_sim_real_build_names_its_targets(fake_tools, upload_project, monkeypatch):
    """sim.SimBoard._real_build goes through board.build (explicit targets) when PlatformIO is ready offline."""
    monkeypatch.setattr(sim, "_offline_ready", lambda pdir, env: (True, []))
    monkeypatch.setenv("CB_TOOLCHAIN_TESTS", "1")  # real builds wanted; pio itself is the fake
    fake_tools.scenario("board-pio-build-ok.json")
    env = sim.SimBoard().build(str(upload_project), "s3")
    assert env["ok"], env.get("error")
    (argv,) = _run_calls(fake_tools)
    assert clitools.pio_targets(argv) == ["checkprogsize", "buildprog"]


def test_metadata_is_an_explicit_target_run(fake_tools, upload_project):
    """`pio project metadata` runs `pio run --target __idedata` inside PlatformIO (project/helpers.py)."""
    fake_tools.scenario("board-pio-build-ok.json")
    board.metadata(upload_project, "s3")
    (call,) = fake_tools.calls("pio")
    assert call["argv"][:2] == ["project", "metadata"]
    assert clitools.touches_hardware(["pio", *call["argv"]]) is False
    assert clitools.touches_hardware(["pio", "run", "--target", "__idedata", "-e", "s3"]) is False


def test_fake_pio_fails_without_targets(tmp_path):
    """The fake refuses `pio run` without -t (run through python: the audit hook would stop the plain call first)."""
    fake = bf.FAKES_BIN / "pio"
    res = subprocess.run([sys.executable, str(fake), "run", "-d", str(tmp_path), "-e", "s3"], capture_output=True,
                         text=True, check=False, env={**os.environ, "CB_FAKE_SCENARIO": ""}, timeout=30)
    assert res.returncode == 97 and "without -t" in res.stderr
    ok = subprocess.run([sys.executable, str(fake), "run", "-d", str(tmp_path), "-e", "s3", "-t", "buildprog"],
                        capture_output=True, text=True, check=False, env={**os.environ, "CB_FAKE_SCENARIO": ""},
                        timeout=30)
    assert ok.returncode == 0


def test_audit_hook_refuses_pio_run_without_targets():
    fake = str(bf.FAKES_BIN / "pio")
    with pytest.raises(HardwareAccessRefused):
        subprocess.run([fake, "run", "-d", "x"], check=False)
    assert subprocess.run([fake, "run", "-d", "x", "-t", "buildprog"], check=False,
                          capture_output=True, timeout=30).returncode == 0


def test_audit_hook_toolchain_mode_allows_only_build_targets(monkeypatch):
    monkeypatch.setenv("CB_TOOLCHAIN_TESTS", "1")
    for argv in (["/nonexistent/pio", "run", "-d", "x"], ["/nonexistent/pio", "run", "-t", "buildprog", "-t", "program"],
                 ["/nonexistent/pio", "test", "-e", "s3"]):
        with pytest.raises(HardwareAccessRefused):
            subprocess.run(argv, check=False)
    for argv in (["/nonexistent/pio", "run", "-d", "x", "-t", "checkprogsize", "-t", "buildprog"],
                 ["/nonexistent/pio", "project", "config", "--json-output"]):
        with pytest.raises(FileNotFoundError):  # allowed by the hook, then simply missing
            subprocess.run(argv, check=False)


def test_scenario_file_is_json():  # the shared scenario the tests above use
    json.loads((bf.SCENARIOS / "board-pio-build-ok.json").read_text(encoding="utf-8"))
