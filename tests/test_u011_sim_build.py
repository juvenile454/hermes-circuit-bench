"""A simulated build that does not start PlatformIO compiles nothing, so it does not warn that the env's MCU could not
be checked (``chip_unchecked``). A build that starts pio (no port, a real port, or a provider that runs pio) keeps
the pre-check unchanged. PlatformIO folders are synthetic (PLATFORMIO_CORE_DIR in tmp_path)."""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pytest
import board_fixtures as bf
from board_fixtures import *  # noqa: F403

from circuit_bench.bench_core import board, contracts


class PioProvider(bf.TestProvider):
    """A provider whose build starts pio (like the simulator with an installed toolchain)."""

    __test__ = False

    def build_runs_pio(self, project_dir, env):
        return True


class NoPioProvider(bf.TestProvider):
    __test__ = False

    def build_runs_pio(self, project_dir, env):
        return False


@pytest.fixture
def core(tmp_path, monkeypatch):
    c = tmp_path / "pio-core"
    monkeypatch.setenv("PLATFORMIO_CORE_DIR", str(c))
    for key in ("PLATFORMIO_PACKAGES_DIR", "PLATFORMIO_PLATFORMS_DIR", "PLATFORMIO_BOARDS_DIR"):
        monkeypatch.delenv(key, raising=False)
    plat = c / "platforms" / "espressif32"
    (plat / "boards").mkdir(parents=True)
    (plat / "platform.json").write_text(json.dumps({"name": "espressif32", "version": "6.9.0", "packages": {}}),
                                        encoding="utf-8")
    (plat / "boards" / "esp32-s3-devkitc-1.json").write_text(json.dumps({"build": {"mcu": "esp32s3"}}),
                                                             encoding="utf-8")
    return c


def fw(tmp_path: Path, board_id: str, platform: str = "espressif32@6.9.0") -> Path:
    d = tmp_path / "fw"
    (d / "src").mkdir(parents=True, exist_ok=True)
    (d / "platformio.ini").write_text(f"[env:s3]\nplatform = {platform}\nboard = {board_id}\nframework = arduino\n",
                                      encoding="utf-8")
    (d / "src" / "main.cpp").write_text("void setup() {}\nvoid loop() {}\n", encoding="utf-8")
    return d


def _codes(env):
    return [w["code"] for w in env.get("warnings", [])]


@pytest.mark.parametrize("provider", [bf.TestProvider, NoPioProvider])
def test_simulated_build_without_pio_has_no_chip_unchecked(fake_tools, core, tmp_path, provider):
    """The board is not in an installed platform: the MCU is unknown, but nothing is built, so nothing to warn."""
    board.register_provider("sim://", provider())
    d = fw(tmp_path, "not-installed-board")
    assert board.build_runs_pio(d, "s3", "sim://test-s3") is False
    env = board.build(d, "s3", port="sim://test-s3", chip="esp32s3")
    assert contracts.validate_envelope(env) == [] and env["ok"] is True and env["simulated"] is True
    assert "chip_unchecked" not in _codes(env)
    assert not any(c["id"] == "board.build.chip" for c in env["checks"])  # nothing claimed either
    assert fake_tools.calls() == []


def test_simulated_build_without_pio_drops_every_chip_unchecked_reason(fake_tools, core, tmp_path):
    board.register_provider("sim://", bf.TestProvider())
    d = fw(tmp_path, "${sysenv.CB_BOARD}")
    assert "chip_unchecked" not in _codes(board.build(d, "s3", port="sim://test-s3", chip="esp32s3"))
    (d / "platformio.ini").write_text("[platformio]\nextra_configs = more.ini\n[env:s3]\nboard = esp32-s3-devkitc-1\n",
                                      encoding="utf-8")
    assert "chip_unchecked" not in _codes(board.build(d, "s3", port="sim://test-s3", chip="esp32s3"))


def test_simulated_build_without_pio_still_refuses_a_wrong_chip(fake_tools, core, tmp_path):
    board.register_provider("sim://", bf.TestProvider())
    env = board.build(fw(tmp_path, "esp32-s3-devkitc-1"), "s3", port="sim://test-s3", chip="esp32c6")
    assert env["ok"] is False and env["error"]["code"] == "chip_mismatch"


def test_simulated_build_without_pio_keeps_other_warnings(fake_tools, core, tmp_path):
    """Only chip_unchecked is about the skipped compile; platform_unpinned still tells the user about the ini."""
    board.register_provider("sim://", bf.TestProvider())
    shutil.rmtree(core / "platforms" / "espressif32" / "boards")
    env = board.build(fw(tmp_path, "esp32-c6-devkitc-1", platform="espressif32"), "s3", port="sim://test-s3",
                      chip="esp32c6")
    assert env["ok"] is True
    assert "platform_unpinned" in _codes(env) and "chip_unchecked" not in _codes(env)


def test_simulated_build_with_pio_keeps_the_pre_check(fake_tools, core, tmp_path):
    board.register_provider("sim://", PioProvider())
    d = fw(tmp_path, "not-installed-board")
    assert board.build_runs_pio(d, "s3", "sim://test-s3") is True
    env = board.build(d, "s3", port="sim://test-s3", chip="esp32s3")
    assert env["ok"] is True and "chip_unchecked" in _codes(env)
    (w,) = [w for w in env["warnings"] if w["code"] == "chip_unchecked"]
    assert w["severity"] == "info" and "is unknown" in w["message"]


def test_real_build_keeps_the_pre_check(fake_tools, core, tmp_path):
    fake_tools.scenario("board-pio-build-ok.json")
    env = board.build(fw(tmp_path, "not-installed-board"), "s3", chip="esp32s3")
    assert env["ok"] is True and "chip_unchecked" in _codes(env)
    assert [c["argv"][0] for c in fake_tools.calls("pio")][:1] == ["run"]


def test_the_simulator_without_a_toolchain_has_no_chip_unchecked(core, tmp_path, monkeypatch):
    """The product path: sim://esp32s3-n16r8 with no installed board manifest (tests: simulated build, no pio)."""
    monkeypatch.delitem(sys.modules, "circuit_bench.bench_core.sim")  # undo the board isolation for this test
    from circuit_bench.bench_core import sim
    monkeypatch.setattr(sim, "TIME_SCALE", 0.0)
    shutil.rmtree(core / "platforms")
    d = tmp_path / "laser-trigger"
    shutil.copytree(sim.EXAMPLES_DIR / "laser-trigger", d)
    assert board.build_runs_pio(d, "s3", sim.PORT) is False
    env = board.build(d, "s3", port=sim.PORT, chip="esp32s3")
    assert contracts.validate_envelope(env) == [] and env["ok"] is True and env["simulated"] is True
    assert "chip_unchecked" not in _codes(env)
    assert any(c["id"] == "sim.build.compile" and c["status"] == "skipped" for c in env["checks"])


def test_provider_that_fails_the_prediction_keeps_the_warning(fake_tools, core, tmp_path):
    """When in doubt (the prediction raises) the build counts as starting pio: the warning stays."""

    class Broken(bf.TestProvider):
        __test__ = False

        def build_runs_pio(self, project_dir, env):
            raise RuntimeError("broken")

    board.register_provider("sim://", Broken())
    env = board.build(fw(tmp_path, "not-installed-board"), "s3", port="sim://test-s3", chip="esp32s3")
    assert "chip_unchecked" in _codes(env)
