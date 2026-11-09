"""Offline builds with the real toolchain (marker toolchain, CB_TOOLCHAIN_TESTS=1).

Offline builds of the synthetic seeds of tests/cflash_fixtures.py (WT32-ETH01 and S2 on espressif32 6.9.0, C6 on
8.0.0) through ``board.build(..., chip=)``; output only under the pytest temporary folder. Skips with the reason when
pio, the platform or a package is missing (never downloads).
"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

import cflash_fixtures as cf
from cflash_fixtures import cflash_seed  # noqa: F401  (fixture)
from circuit_bench.bench_core import board, chips, sim

pytestmark = pytest.mark.toolchain


def _need() -> None:
    if os.environ.get("CB_TOOLCHAIN_TESTS") != "1":
        pytest.skip("set CB_TOOLCHAIN_TESTS=1 (run: CB_TOOLCHAIN_TESTS=1 pytest -m toolchain)")
    if not (cf.PIO_CORE / "platforms").is_dir():
        pytest.skip(f"no PlatformIO platforms in {cf.PIO_CORE}")


@pytest.fixture
def real_core(monkeypatch):
    monkeypatch.setenv("PLATFORMIO_CORE_DIR", str(cf.PIO_CORE))
    for key in ("PLATFORMIO_PLATFORMS_DIR", "PLATFORMIO_PACKAGES_DIR", "PLATFORMIO_BOARDS_DIR"):
        monkeypatch.delenv(key, raising=False)


@pytest.mark.parametrize("seed", sorted(cf.SEEDS))
def test_offline_ready_on_the_installed_platforms(tmp_path, real_core, seed):
    _need()
    ready = sim._offline_ready(cf.write_seed(tmp_path, seed), cf.ENV)
    if not ready[0]:
        pytest.skip(f"not installed: {ready[1]}")
    assert ready == (True, [])


def test_laser_example_stays_ready_on_6_9_0(tmp_path, real_core):
    _need()
    fw = tmp_path / "laser"
    shutil.copytree(sim.EXAMPLES_DIR / "laser-trigger", fw, ignore=shutil.ignore_patterns(".pio"))
    assert sim._offline_ready(fw, "s3") == (True, [])
    fwdir = Path(sim._framework_dir(fw))
    assert fwdir.is_dir() and board.semver(__import__("json").loads((fwdir / "package.json").read_text())["version"]) \
        < (4, 0, 0)  # the 3.20017 framework of 6.9.0, not the 4.30312 of 8.0.0


def test_c6_arduino_on_the_real_6_9_0_is_refused_before_pio(tmp_path, real_core, monkeypatch):
    _need()
    calls = []
    real_run = board.clitools.run
    monkeypatch.setattr(board.clitools, "run", lambda argv, **kw: calls.append(argv) or real_run(argv, **kw))
    d = cf.write_seed(tmp_path, "c6")
    ini = d / "platformio.ini"
    ini.write_text(ini.read_text(encoding="utf-8").replace("espressif32@8.0.0", "espressif32@6.9.0"), encoding="utf-8")
    env = board.build(d, cf.ENV, chip="esp32c6")
    assert env["error"]["code"] == "platform_too_old" and calls == []


@pytest.mark.parametrize("seed", sorted(cf.SEEDS))
def test_seed_builds_offline(cflash_seed, seed, tmp_path):  # noqa: F811
    _need()
    built = cflash_seed(seed)
    chip = built["chip"]
    env = built["build"]
    assert any(c["id"] == "board.build.chip" and c["status"] == "passed" for c in env["checks"]), env["checks"]
    assert not any(w["code"] in ("platform_unpinned", "chip_unchecked") for w in env["warnings"])
    elf = built["elf"]
    assert elf.is_file() and elf.is_relative_to(built["project"].parent / "build")  # PLATFORMIO_BUILD_DIR in tmp
    assert not (built["project"] / ".pio" / "build").exists()  # output only in PLATFORMIO_BUILD_DIR
    assert cf._elf_machine(elf) == cf.ELF_MACHINE[chips.arch(chip)]
    a2l = Path(built["addr2line"])
    assert a2l.name == f"{chips.toolchain_prefix(chip)}-addr2line" and a2l.is_file()
    nm = a2l.with_name(f"{chips.toolchain_prefix(chip)}-nm")
    syms = subprocess.run([str(nm), "-C", str(elf)], capture_output=True, text=True, timeout=60, check=True).stdout
    addr = next(line.split()[0] for line in syms.splitlines() if line.endswith(" cb_fixture_store(unsigned char*, unsigned int)"))
    res = board.clitools.run([str(a2l), "-pfiaC", "-e", str(elf), f"0x{addr}"], timeout=60, hardware=False, tail=10)
    assert res["rc"] == 0 and "cb_fixture_store(unsigned char*, unsigned int) at " in res["out_tail"][0]
    assert "/src/main.cpp:" in res["out_tail"][0]
