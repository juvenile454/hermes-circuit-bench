"""sim._offline_ready knows the package schema of espressif32 8.0.0 (unified toolchains,
framework-arduinoespressif32-<mcu>-libs), espressif32 6.9.0 stays as before, both can be installed side by side
(platforms/espressif32 = 8.0.0, platforms/espressif32@6.9.0); sim._framework_dir picks the framework folder the
pinned platform asks for.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from circuit_bench.bench_core import sim

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "circuit_bench" / "data" / "examples" / "laser-trigger"
CORPUS = ROOT / "tests" / ".corpus" / "platformio" / "platform-espressif32"

# the parts of espressif32 8.0.0 platform.json that decide (pio-esp32-8.0.0-platform-json; versions as shipped except
# the build-date suffixes of the toolchains, which are synthetic here: '+cb-synthetic')
PACKAGES_8 = {
    "toolchain-riscv32-esp": {"type": "toolchain", "owner": "platformio", "version": "14.2.0+cb-synthetic"},
    "toolchain-xtensa-esp-elf": {"type": "toolchain", "owner": "platformio", "version": "14.2.0+cb-synthetic"},
    "toolchain-esp32ulp": {"type": "toolchain", "optional": True, "owner": "platformio", "version": "~1.23800.0"},
    "tool-xtensa-esp-elf-gdb": {"type": "debugger", "owner": "espressif", "version": "~12.1.0"},
    "tool-riscv32-esp-elf-gdb": {"type": "debugger", "owner": "espressif", "version": "~12.1.0"},
    "framework-arduinoespressif32": {"type": "framework", "optional": True, "owner": "platformio", "version": "~4.30312.0"},
    "framework-arduinoespressif32-esp32-libs": {"type": "framework", "optional": True, "owner": "platformio",
                                                "version": "~3.3.12"},
    "framework-arduinoespressif32-esp32c3-libs": {"type": "framework", "optional": True, "owner": "platformio",
                                                  "version": "~3.3.12"},
    "framework-arduinoespressif32-esp32c6-libs": {"type": "framework", "optional": True, "owner": "platformio",
                                                  "version": "~3.3.12"},
    "framework-arduinoespressif32-esp32s2-libs": {"type": "framework", "optional": True, "owner": "platformio",
                                                  "version": "~3.3.12"},
    "framework-arduinoespressif32-esp32s3-libs": {"type": "framework", "optional": True, "owner": "platformio",
                                                  "version": "~3.3.12"},
    "framework-espidf": {"type": "framework", "optional": True, "owner": "platformio", "version": "~4.60100.0"},
    "tool-esptool": {"type": "uploader", "owner": "platformio", "version": "~2.50400.0"},
    "tool-dfuutil-arduino": {"type": "uploader", "optional": True, "owner": "platformio", "version": "~1.11.0"},
    "tool-openocd-esp32": {"type": "debugger", "optional": True, "owner": "platformio", "version": "~2.1100.0"},
    "tool-esp-rom-elfs": {"optional": True, "owner": "platformio", "version": "0.0.1+cb-synthetic"},
}
# the parts of espressif32 6.9.0 platform.json that decide (pio-esp32-6.9.0-platform-json; '+cb-synthetic' as above)
PACKAGES_6 = {
    "toolchain-xtensa-esp32": {"type": "toolchain", "owner": "espressif", "version": "8.4.0+2021r2-patch5"},
    "toolchain-xtensa-esp32s2": {"type": "toolchain", "optional": True, "owner": "espressif",
                                 "version": "8.4.0+2021r2-patch5"},
    "toolchain-xtensa-esp32s3": {"type": "toolchain", "optional": True, "owner": "espressif",
                                 "version": "8.4.0+2021r2-patch5"},
    "toolchain-riscv32-esp": {"type": "toolchain", "optional": True, "owner": "espressif",
                              "version": "8.4.0+2021r2-patch5"},
    "toolchain-xtensa-esp-elf": {"type": "toolchain", "optional": True, "owner": "platformio",
                                 "version": "13.2.0+cb-synthetic"},
    "tool-xtensa-esp-elf-gdb": {"type": "debugger", "optional": True, "owner": "espressif", "version": "~12.1.0"},
    "tool-riscv32-esp-elf-gdb": {"type": "debugger", "optional": True, "owner": "espressif", "version": "~12.1.0"},
    "framework-arduinoespressif32": {"type": "framework", "optional": True, "owner": "platformio", "version": "~3.20017.0"},
    "tool-esptoolpy": {"type": "uploader", "owner": "platformio", "version": "~1.40501.0"},
    "tool-dfuutil-arduino": {"type": "uploader", "optional": True, "owner": "platformio", "version": "~1.11.0"},
}
FRAMEWORKS = {"arduino": {"package": "framework-arduinoespressif32"}, "espidf": {"package": "framework-espidf"}}
INSTALLED_8 = {  # as installed for espressif32 8.0.0
    "toolchain-xtensa-esp-elf": "14.2.0+cb-synthetic", "toolchain-riscv32-esp": "14.2.0+cb-synthetic",
    "tool-xtensa-esp-elf-gdb": "12.1.0+cb-synthetic", "tool-riscv32-esp-elf-gdb": "12.1.0+cb-synthetic",
    "framework-arduinoespressif32": "4.30312.261024", "framework-arduinoespressif32-esp32c6-libs": "3.3.12",
    "tool-esptool": "2.50400.0", "tool-scons": "4.41101.0",
}
INSTALLED_6 = {  # suffixed folders, as after installing 8.0.0 next to 6.9.0
    "framework-arduinoespressif32@3.20017.241212+sha.dcc1105b": ("framework-arduinoespressif32",
                                                                 "3.20017.241212+sha.dcc1105b"),
    "toolchain-riscv32-esp@8.4.0+2021r2-patch5": ("toolchain-riscv32-esp", "8.4.0+2021r2-patch5"),
    "toolchain-xtensa-esp32": ("toolchain-xtensa-esp32", "8.4.0+2021r2-patch5"),
    "toolchain-xtensa-esp32s2": ("toolchain-xtensa-esp32s2", "8.4.0+2021r2-patch5"),
    "toolchain-xtensa-esp32s3": ("toolchain-xtensa-esp32s3", "8.4.0+2021r2-patch5"),
    "tool-esptoolpy": ("tool-esptoolpy", "1.40501.0"),
}
BOARDS = {"esp32-c6-devkitc-1": "esp32c6", "esp32-s2-saola-1": "esp32s2", "wt32-eth01": "esp32",
          "esp32-s3-devkitc-1": "esp32s3", "esp32-c3-devkitm-1": "esp32c3"}


def platform(core: Path, version: str, packages: dict, folder: str = "espressif32") -> Path:
    plat = core / "platforms" / folder
    (plat / "boards").mkdir(parents=True)
    (plat / "platform.json").write_text(json.dumps({"name": "espressif32", "version": version, "packages": packages,
                                                    "frameworks": FRAMEWORKS}), encoding="utf-8")
    for b, mcu in BOARDS.items():
        (plat / "boards" / f"{b}.json").write_text(json.dumps({"build": {"mcu": mcu}}), encoding="utf-8")
    return plat


def package(core: Path, folder: str, name: str, version: str) -> None:
    d = core / "packages" / folder
    d.mkdir(parents=True)
    (d / "package.json").write_text(json.dumps({"name": name, "version": version}), encoding="utf-8")


def side_by_side(core: Path, installed8: dict | None = None) -> Path:
    platform(core, "8.0.0", PACKAGES_8)
    platform(core, "6.9.0", PACKAGES_6, "espressif32@6.9.0")
    for name, ver in (INSTALLED_8 if installed8 is None else installed8).items():
        package(core, name, name, ver)
    for folder, (name, ver) in INSTALLED_6.items():
        package(core, folder, name, ver)
    return core


@pytest.fixture
def core(tmp_path, monkeypatch):
    c = tmp_path / "pio-core"
    monkeypatch.setenv("PLATFORMIO_CORE_DIR", str(c))
    for key in ("PLATFORMIO_PACKAGES_DIR", "PLATFORMIO_PLATFORMS_DIR"):
        monkeypatch.delenv(key, raising=False)
    return c


def project(tmp_path: Path, version: str, board_id: str, extra: str = "") -> Path:
    d = tmp_path / f"p-{board_id}-{version}"
    (d / "src").mkdir(parents=True)
    (d / "platformio.ini").write_text(f"[env:e]\nplatform = espressif32@{version}\nboard = {board_id}\n"
                                      f"framework = arduino\n{extra}", encoding="utf-8")
    return d


def test_c6_on_8_0_0_is_ready(core, tmp_path):
    side_by_side(core)
    assert sim._offline_ready(project(tmp_path, "8.0.0", "esp32-c6-devkitc-1"), "e") == (True, [])


def test_missing_libs_package_is_named(core, tmp_path):
    side_by_side(core, {k: v for k, v in INSTALLED_8.items() if k != "framework-arduinoespressif32-esp32c6-libs"})
    assert sim._offline_ready(project(tmp_path, "8.0.0", "esp32-c6-devkitc-1"), "e") == (
        False, ["framework-arduinoespressif32-esp32c6-libs"])
    # the S2 libs were never installed: an S2 env on 8.0.0 is not ready
    assert sim._offline_ready(project(tmp_path, "8.0.0", "esp32-s2-saola-1"), "e") == (
        False, ["framework-arduinoespressif32-esp32s2-libs"])


@pytest.mark.parametrize("gone", sorted(k for k in INSTALLED_8 if k != "tool-scons"))
def test_each_8_0_0_package_counts(core, tmp_path, gone):
    """Unified toolchains: a C6 (RISC-V) Arduino build on 8.0.0 needs the Xtensa toolchain and both GDBs, too
    (not optional in platform.json, not removed by platform.py for arduino)."""
    side_by_side(core, {k: v for k, v in INSTALLED_8.items() if k != gone})
    assert sim._offline_ready(project(tmp_path, "8.0.0", "esp32-c6-devkitc-1"), "e") == (False, [gone])


def test_unknown_libs_mcu_is_not_ready(core, tmp_path):
    side_by_side(core)
    d = project(tmp_path, "8.0.0", "esp32-c6-devkitc-1", "board_build.mcu = esp32h2\n")
    ready, missing = sim._offline_ready(d, "e")
    assert ready is False and "esp32h2" in missing[0]


def test_6_9_0_side_by_side_stays_ready(core, tmp_path):
    side_by_side(core)
    fw = tmp_path / "laser"
    shutil.copytree(EXAMPLE, fw, ignore=shutil.ignore_patterns(".pio"))
    assert sim._offline_ready(fw, "s3") == (True, [])
    assert sim._offline_ready(project(tmp_path, "6.9.0", "wt32-eth01"), "e") == (True, [])
    assert sim._offline_ready(project(tmp_path, "6.9.0", "esp32-s2-saola-1", "board_upload.flash_size = 8MB\n"),
                              "e") == (True, [])
    # 6.9.0 has no Arduino for the C6 board in reality; with this synthetic board list the 6.x rules apply
    assert sim._offline_ready(project(tmp_path, "6.9.0", "esp32-c6-devkitc-1"), "e") == (True, [])


def test_6_9_0_needs_its_own_framework_version(core, tmp_path):
    """The plain framework folder is 4.30312 (8.0.0): without the @3.20017 folder 6.9.0 is not ready."""
    side_by_side(core)
    shutil.rmtree(core / "packages" / "framework-arduinoespressif32@3.20017.241212+sha.dcc1105b")
    assert sim._offline_ready(project(tmp_path, "6.9.0", "wt32-eth01"), "e") == (False, ["framework-arduinoespressif32"])


def test_mcu_lists_come_from_the_register():
    from circuit_bench.bench_core import chips
    assert set(sim._XTENSA_MCUS) == {chips.get(c)["pio_mcu"] for c in chips.ids() if chips.arch(c) == "xtensa"}
    assert set(sim._RISCV_MCUS) == {"esp32s2", "esp32s3", "esp32c3", "esp32c6"}  # 6.9.0 platform.py list


def test_synthetic_manifests_match_the_pinned_corpus():
    for version, packages in (("v8.0.0", PACKAGES_8), ("v6.9.0", PACKAGES_6)):
        path = CORPUS / version / "platform.json"
        if not path.is_file():
            pytest.skip("corpus missing (scripts/fetch_corpus.py)")
        real = json.loads(path.read_text(encoding="utf-8"))
        assert real["frameworks"]["arduino"]["package"] == "framework-arduinoespressif32"
        for name, spec in packages.items():
            assert bool(real["packages"][name].get("optional")) == bool(spec.get("optional")), (version, name)
            if "cb-synthetic" not in spec["version"]:
                assert real["packages"][name]["version"] == spec["version"], (version, name)
    text = (CORPUS / "v8.0.0" / "platform.py").read_text(encoding="utf-8")
    assert 'self.packages["framework-arduinoespressif32-%s-libs" % mcu]["optional"] = False' in text


def test_8_0_0_corpus_manifest_drives_the_check(core, tmp_path):
    """The real pinned platform.json of 8.0.0 (not the synthetic subset) gives the same answer."""
    path = CORPUS / "v8.0.0" / "platform.json"
    if not path.is_file():
        pytest.skip("corpus missing (scripts/fetch_corpus.py)")
    real = json.loads(path.read_text(encoding="utf-8"))
    plat = platform(core, "8.0.0", real["packages"])
    (plat / "platform.json").write_text(json.dumps(real), encoding="utf-8")
    for name in INSTALLED_8:
        spec = (real["packages"].get(name) or {}).get("version", "")
        ver = spec.lstrip("~^") if spec else INSTALLED_8[name]
        package(core, name, name, ver)
    assert sim._offline_ready(project(tmp_path, "8.0.0", "esp32-c6-devkitc-1"), "e") == (True, [])


def test_framework_dir_follows_the_pinned_platform(core, tmp_path):
    side_by_side(core)
    want6 = core / "packages" / "framework-arduinoespressif32@3.20017.241212+sha.dcc1105b"
    assert sim._framework_dir() == str(want6)  # the example pins 6.9.0
    assert sim._framework_dir(core=core) == str(want6)
    assert sim._framework_dir(project(tmp_path, "8.0.0", "esp32-c6-devkitc-1")) == str(
        core / "packages" / "framework-arduinoespressif32")
    # nothing fits: the folder without suffix
    shutil.rmtree(want6)
    assert sim._framework_dir() == str(core / "packages" / "framework-arduinoespressif32")
    shutil.rmtree(core / "platforms")
    assert sim._framework_dir() == str(core / "packages" / "framework-arduinoespressif32")


def test_crash_runner_uses_the_resolved_framework(core, tmp_path):
    side_by_side(core)
    run = sim.crash_runner()
    table = sim._data("decode.json")["addresses"]
    addr = next(a for a, v in table.items() if "{framework}" in v)
    out = run(["xtensa-esp32s3-elf-addr2line", "-pfiaC", "-e", "/x/.pio/build/s3/firmware.elf", addr])["out_tail"]
    assert "framework-arduinoespressif32@3.20017.241212+sha.dcc1105b/" in out[0]
