"""A simulated build runs the real pio only when the platform AND every package the build needs
are installed (no downloads); otherwise it stays simulated with an assumption naming what is missing."""
import json
import shutil
from pathlib import Path

import pytest

from circuit_bench.bench_core import sim

EXAMPLE = Path(__file__).resolve().parents[1] / "circuit_bench" / "data" / "examples" / "laser-trigger"
# the parts of espressif32 6.9.0 platform.json that decide (versions as shipped)
PACKAGES = {
    "toolchain-xtensa-esp32": {"type": "toolchain", "owner": "espressif", "version": "8.4.0+2021r2-patch5"},
    "toolchain-xtensa-esp32s3": {"type": "toolchain", "optional": True, "owner": "espressif",
                                 "version": "8.4.0+2021r2-patch5"},
    "toolchain-riscv32-esp": {"type": "toolchain", "optional": True, "owner": "espressif",
                              "version": "8.4.0+2021r2-patch5"},
    "toolchain-esp32ulp": {"type": "toolchain", "optional": True, "owner": "platformio", "version": "~1.23800.0"},
    "framework-arduinoespressif32": {"type": "framework", "optional": True, "owner": "platformio", "version": "~3.20017.0"},
    "framework-espidf": {"type": "framework", "optional": True, "owner": "platformio", "version": "~3.50301.0"},
    "tool-esptoolpy": {"type": "uploader", "owner": "platformio", "version": "~1.40501.0"},
    "tool-dfuutil-arduino": {"type": "uploader", "optional": True, "owner": "platformio", "version": "~1.11.0"},
    "tool-openocd-esp32": {"type": "debugger", "optional": True, "owner": "platformio", "version": "~2.1100.0"},
}
INSTALLED = {"framework-arduinoespressif32": "3.20017.241212+sha.dcc1105b", "tool-esptoolpy": "1.40501.0",
             "toolchain-riscv32-esp": "8.4.0+2021r2-patch5", "toolchain-xtensa-esp32s3": "8.4.0+2021r2-patch5",
             "tool-scons": "4.41101.0"}


def fake_core(core: Path, installed: dict[str, str] | None = None, version: str = "6.9.0") -> Path:
    plat = core / "platforms" / "espressif32"
    (plat / "boards").mkdir(parents=True)
    (plat / "platform.json").write_text(json.dumps({
        "name": "espressif32", "version": version, "packages": PACKAGES,
        "frameworks": {"arduino": {"package": "framework-arduinoespressif32"},
                       "espidf": {"package": "framework-espidf"}}}), encoding="utf-8")
    for board, mcu in (("esp32-s3-devkitc-1", "esp32s3"), ("esp32-c3-devkitm-1", "esp32c3")):
        (plat / "boards" / f"{board}.json").write_text(json.dumps({"build": {"mcu": mcu}}), encoding="utf-8")
    for name, ver in (INSTALLED if installed is None else installed).items():
        d = core / "packages" / name
        d.mkdir(parents=True)
        (d / "package.json").write_text(json.dumps({"name": name, "version": ver}), encoding="utf-8")
    return core


@pytest.fixture
def fw(tmp_path):
    dst = tmp_path / "fw"
    shutil.copytree(EXAMPLE, dst, ignore=shutil.ignore_patterns(".pio"))
    return dst


@pytest.fixture
def core(tmp_path, monkeypatch):
    c = tmp_path / "pio-core"
    monkeypatch.setenv("PLATFORMIO_CORE_DIR", str(c))
    for key in ("PLATFORMIO_PACKAGES_DIR", "PLATFORMIO_PLATFORMS_DIR"):
        monkeypatch.delenv(key, raising=False)
    return c


def test_everything_installed_is_ready(fw, core):
    fake_core(core)
    assert sim._offline_ready(fw, "s3") == (True, [])


@pytest.mark.parametrize("gone", sorted(INSTALLED))
def test_each_needed_package_counts(fw, core, gone):
    fake_core(core, {k: v for k, v in INSTALLED.items() if k != gone})
    ready, missing = sim._offline_ready(fw, "s3")
    assert ready is False and missing == [gone]


def test_wrong_versions_and_platform(fw, core, tmp_path):
    fake_core(core, {**INSTALLED, "framework-arduinoespressif32": "3.20016.0"})
    assert sim._offline_ready(fw, "s3") == (False, ["framework-arduinoespressif32"])
    shutil.rmtree(core)
    fake_core(core, version="6.8.1")
    assert sim._offline_ready(fw, "s3") == (False, ["espressif32@6.9.0"])


@pytest.mark.parametrize("extra, needle", [
    ("lib_deps = adafruit/Adafruit NeoPixel@^1.12.0\n", "lib_deps"),
    ("platform_packages = framework-arduinoespressif32 @ https://github.com/espressif/arduino-esp32.git\n",
     "platform_packages"),
])
def test_downloads_of_the_project_are_never_ready(fw, core, extra, needle):
    fake_core(core)
    ini = fw / "platformio.ini"
    ini.write_text(ini.read_text(encoding="utf-8") + extra, encoding="utf-8")
    ready, missing = sim._offline_ready(fw, "s3")
    assert ready is False and needle in missing[0]


def test_other_frameworks_boards_and_includes_are_never_ready(fw, core):
    fake_core(core)
    ini = fw / "platformio.ini"
    text = ini.read_text(encoding="utf-8")
    ini.write_text(text.replace("framework = arduino", "framework = arduino, espidf"), encoding="utf-8")
    assert sim._offline_ready(fw, "s3")[0] is False
    ini.write_text(text.replace("board = esp32-s3-devkitc-1", "board = my-custom-board"), encoding="utf-8")
    assert "board my-custom-board" in sim._offline_ready(fw, "s3")[1][0]
    ini.write_text(text.replace("[platformio]\n", "[platformio]\nextra_configs = more.ini\n"), encoding="utf-8")
    assert sim._offline_ready(fw, "s3")[0] is False


def test_c3_needs_the_riscv_toolchain_only(fw, core):
    fake_core(core, {k: v for k, v in INSTALLED.items() if k != "toolchain-xtensa-esp32s3"})
    ini = fw / "platformio.ini"
    ini.write_text(ini.read_text(encoding="utf-8") + "\n[env:c3]\nplatform = espressif32@6.9.0\n"
                   "board = esp32-c3-devkitm-1\nframework = arduino\n", encoding="utf-8")
    assert sim._offline_ready(fw, "c3") == (True, [])
    assert sim._offline_ready(fw, "s3") == (False, ["toolchain-xtensa-esp32s3"])


@pytest.mark.parametrize(("installed", "spec", "ok"), [
    ("3.20017.241212+sha.dcc1105b", "~3.20017.0", True), ("3.20018.0", "~3.20017.0", False),
    ("1.40501.0", "~1.40501.0", True), ("1.7.2", "^1.7.0", True), ("2.0.0", "^1.7.0", False),
    ("8.4.0+2021r2-patch5", "8.4.0+2021r2-patch5", True), ("8.4.0+2021r2-patch4", "8.4.0+2021r2-patch5", False),
    ("13.2.0+20240530", "13.2.0+202****0530", False), ("1.0.0", "https://example.com/x.zip", False),
])
def test_requirement_matching(installed, spec, ok):
    assert sim._satisfies(installed, spec) is ok


def test_build_stays_simulated_and_names_the_missing_packages(fw, core, monkeypatch):
    fake_core(core, {k: v for k, v in INSTALLED.items() if k != "toolchain-xtensa-esp32s3"})
    monkeypatch.setattr(sim, "_real_build_wanted", lambda: True)
    monkeypatch.setattr(sim, "_pio", lambda: "/usr/local/bin/pio")
    monkeypatch.setattr(sim.SimBoard, "_real_build", lambda *a, **k: pytest.fail("pio must not run"))
    monkeypatch.setattr(sim, "_sleep", lambda s: None)
    env = sim.SimBoard().build(str(fw), "s3")
    assert env["ok"] and env["simulated"] and env["result"]["toolchain"] == "simulated"
    a = next(a for a in env["assumptions"] if a["key"] == "packages")
    assert a["value"] == "toolchain-xtensa-esp32s3" and "pio pkg install" in a["reason"]


def test_build_runs_pio_when_everything_is_there(fw, core, monkeypatch):
    fake_core(core)
    monkeypatch.setattr(sim, "_real_build_wanted", lambda: True)
    monkeypatch.setattr(sim, "_pio", lambda: "/usr/local/bin/pio")
    ran = []
    monkeypatch.setattr(sim.SimBoard, "_real_build", lambda self, pdir, env, crash: ran.append(env) or {"ok": True})
    sim.SimBoard().build(str(fw), "s3")
    assert ran == ["s3"]
