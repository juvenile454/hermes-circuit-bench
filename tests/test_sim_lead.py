"""Sim follow-ups: natural fixes end the simulated crash, sim builds never make pio download a
platform, and a decode through the simulated addr2line is marked simulated."""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from circuit_bench.bench_core import crash, sim

EXAMPLE = Path(__file__).resolve().parents[1] / "circuit_bench" / "data" / "examples" / "laser-trigger"
NULL_WRITE = "  buf[FRAME_VBAT] = (uint8_t)(millivolts / 20);"


@pytest.fixture
def fw(tmp_path):
    dst = tmp_path / "fw"
    shutil.copytree(EXAMPLE, dst)
    return dst


def _edit(fw: Path, old: str, new: str) -> None:
    main = fw / "src" / "main.cpp"
    text = main.read_text(encoding="utf-8")
    assert old in text
    main.write_text(text.replace(old, new, 1), encoding="utf-8")


def test_example_as_shipped_crashes(fw):
    assert sim.demo_crash(fw) is True


@pytest.mark.parametrize("old,new", [
    ("#define DEMO_CRASH 1", "#define DEMO_CRASH 0"),
    (NULL_WRITE, "  if (!buf) return;\n" + NULL_WRITE),
    (NULL_WRITE, "  if (buf == nullptr) {\n    return;\n  }\n" + NULL_WRITE),
    ("static uint8_t *sensor_frame = nullptr;", "static uint8_t *sensor_frame = frame_storage;"),
    ("  Wire.begin(SDA_PIN, SCL_PIN);", "  Wire.begin(SDA_PIN, SCL_PIN);\n  sensor_frame = frame_storage;"),
], ids=["demo-crash-0", "guard-not", "guard-eq", "init", "assign"])
def test_natural_fixes_end_the_crash(fw, old, new):
    _edit(fw, old, new)
    assert sim.demo_crash(fw) is False


@pytest.mark.parametrize("old,new", [
    ("static uint8_t *sensor_frame = nullptr;", "static uint8_t *sensor_frame = NULL;"),
    (NULL_WRITE, "  // if (!buf) return;  (not yet)\n" + NULL_WRITE),
], ids=["still-null", "commented-guard"])
def test_non_fixes_keep_crashing(fw, old, new):
    _edit(fw, old, new)
    assert sim.demo_crash(fw) is True


def _platform(core: Path, version: str) -> None:
    d = core / "platforms" / "espressif32"
    d.mkdir(parents=True)
    (d / "platform.json").write_text(json.dumps({"name": "espressif32", "version": version}), encoding="utf-8")


def test_platform_installed(fw, tmp_path, monkeypatch):
    core = tmp_path / "pio-core"
    monkeypatch.setenv("PLATFORMIO_CORE_DIR", str(core))
    assert sim._platform_installed(fw) == (False, "espressif32@6.9.0")
    _platform(core, "6.8.1")
    assert sim._platform_installed(fw) == (False, "espressif32@6.9.0")
    shutil.rmtree(core)
    _platform(core, "6.9.0")
    assert sim._platform_installed(fw) == (True, "espressif32@6.9.0")


def test_sim_build_without_the_platform_is_simulated(fw, tmp_path, monkeypatch):
    monkeypatch.setenv("PLATFORMIO_CORE_DIR", str(tmp_path / "empty-core"))
    monkeypatch.setattr(sim, "_real_build_wanted", lambda: True)
    monkeypatch.setattr(sim, "_pio", lambda: "/usr/local/bin/pio")
    monkeypatch.setattr(sim.SimBoard, "_real_build", lambda *a, **k: pytest.fail("pio must not run"))
    monkeypatch.setattr(sim, "_sleep", lambda s: None)
    env = sim.SimBoard().build(str(fw), "s3")
    assert env["ok"] and env["simulated"] and env["result"]["toolchain"] == "simulated"
    assert any(a["key"] == "platform" and a["value"] == "espressif32@6.9.0" for a in env["assumptions"])


def test_decode_through_the_sim_runner_is_marked_simulated(fw):
    log = (Path(sim.__file__).resolve().parents[1] / "data" / "sim" / "esp32s3-n16r8" / "panic.log").read_text()
    env = crash.decode(log, elf=str(fw / ".pio" / "build" / "s3" / "firmware.elf"), chip="esp32s3",
                       project_dir=str(fw), run=sim.crash_runner(str(fw)))
    assert env["ok"] and env["simulated"] is True, env["summary"]
    assert any(a["key"] == "addr2line" and a["value"] == "simulated" for a in env["assumptions"])
    assert "write_sensor_buffer" in env["summary"] and "main.cpp:44" in env["summary"]
    plain = crash.decode(log, chip="esp32s3")  # no runner, no ELF: not simulated
    assert plain["simulated"] is False
