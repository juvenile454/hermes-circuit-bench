"""Doctor and /health show the toolchain of every chip in the register.

``toolchains: {<chip>: {"addr2line": bool, "prefix": "..."}}`` sits next to the existing ``addr2line`` field
(doctor: per chip with path, /health: bool). A missing toolchain is an ``info`` warning, never a failure of its own.
"""
import json
import os
import sys
import types
from pathlib import Path

import board_fixtures as bf
import pytest
import test_api_support as sup
from board_fixtures import fake_tools  # noqa: F401 - fixture
from test_api_support import *  # noqa: F403

from circuit_bench.bench_core import chips, contracts, doctor

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "desktop-src" / "fixtures"
FAKE_A2L = bf.FAKES_BIN / "xtensa-esp32s3-elf-addr2line"
MISSING_TEXT = "build once for this chip; pio installs its toolchain"


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setitem(sys.modules, "circuit_bench.bench_core.sim", None)
    cfg = types.ModuleType("hermes_cli.config")
    cfg.load_config = dict
    pkg = types.ModuleType("hermes_cli")
    pkg.config = cfg
    monkeypatch.setitem(sys.modules, "hermes_cli", pkg)
    monkeypatch.setitem(sys.modules, "hermes_cli.config", cfg)
    monkeypatch.delenv("HERMES_YOLO_MODE", raising=False)


def _only_toolchains(monkeypatch, tmp_path, on_path=(), in_packages=()):
    """PATH holds only the fake pio/esptool and the given ``<prefix>-addr2line`` names (symlinks to the fake);
    ``in_packages``: (package folder, prefix) pairs under a temporary PlatformIO core dir."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name in ("pio", "esptool"):
        (bin_dir / name).symlink_to(bf.FAKES_BIN / name)
    for prefix in on_path:
        (bin_dir / f"{prefix}-addr2line").symlink_to(FAKE_A2L)
    core = tmp_path / "pio-core"
    for package, prefix in in_packages:
        folder = core / "packages" / package / "bin"
        folder.mkdir(parents=True, exist_ok=True)
        (folder / f"{prefix}-addr2line").symlink_to(FAKE_A2L)
    monkeypatch.setenv("PATH", str(bin_dir))
    monkeypatch.setenv("PLATFORMIO_CORE_DIR", str(core))


def test_toolchains_cover_every_chip_of_the_register(monkeypatch, tmp_path):
    _only_toolchains(monkeypatch, tmp_path, on_path=("riscv32-esp-elf",))
    tc = doctor.toolchains()
    assert list(tc) == chips.ids() and len(tc) == 5
    for chip, info in tc.items():
        assert info == {"addr2line": info["addr2line"], "prefix": chips.toolchain_prefix(chip)}, chip
    riscv = {c for c in chips.ids() if chips.arch(c) == "riscv"}
    assert {c for c, v in tc.items() if v["addr2line"]} == riscv  # esp32c3 and esp32c6 share riscv32-esp-elf


def test_toolchain_from_platformio_packages(monkeypatch, tmp_path):
    """Packages of both schemes: 6.9.0 per chip, 8.0.0 unified; versioned @-folders count as well."""
    _only_toolchains(monkeypatch, tmp_path, in_packages=(
        ("toolchain-xtensa-esp-elf", "xtensa-esp32s2-elf"),
        ("toolchain-xtensa-esp32@8.4.0+2021r2-patch5", "xtensa-esp32-elf")))
    tc = doctor.toolchains()
    assert tc["esp32s2"]["addr2line"] is True and tc["esp32"]["addr2line"] is True
    assert tc["esp32s3"]["addr2line"] is False and tc["esp32c6"]["addr2line"] is False
    assert doctor.find_addr2line("esp32s2").endswith("toolchain-xtensa-esp-elf/bin/xtensa-esp32s2-elf-addr2line")


def test_doctor_names_five_chips_and_marks_the_missing_ones(monkeypatch, tmp_path):
    _only_toolchains(monkeypatch, tmp_path, on_path=("riscv32-esp-elf", "xtensa-esp32s3-elf"))
    env = doctor.run()
    assert contracts.validate_envelope(env) == [] and env["ok"] is True
    tools = env["result"]["tools"]
    assert set(tools["toolchains"]) == set(chips.ids())
    assert set(tools["addr2line"]) == set(chips.ids())  # existing field: path + version per chip
    assert tools["addr2line"]["esp32s3"]["path"].endswith("xtensa-esp32s3-elf-addr2line")
    assert tools["addr2line"]["esp32s2"]["path"] is None
    st = {c["id"]: c for c in env["checks"]}
    assert st["doctor.addr2line"]["status"] == "passed"
    missing = [w for w in env["warnings"] if w["code"] == "toolchain_missing"]
    assert len(missing) == 1 and missing[0]["severity"] == "info"
    assert MISSING_TEXT in missing[0]["message"]
    msg = missing[0]["message"]
    assert "esp32 (xtensa-esp32-elf)" in msg and "esp32s2 (xtensa-esp32s2-elf)" in msg
    assert "esp32c6" not in msg and "esp32s3" not in msg
    assert len(json.dumps(env).encode()) <= contracts.MAX_RESULT_BYTES


def test_doctor_without_any_toolchain_keeps_the_old_warning(monkeypatch, tmp_path):
    _only_toolchains(monkeypatch, tmp_path)
    env = doctor.run()
    st = {c["id"]: c["status"] for c in env["checks"]}
    assert st["doctor.addr2line"] == "failed"
    codes = [w["code"] for w in env["warnings"]]
    assert "addr2line_missing" in codes and "toolchain_missing" not in codes
    assert all(v == {"addr2line": False, "prefix": chips.toolchain_prefix(c)}
               for c, v in env["result"]["tools"]["toolchains"].items())


def test_doctor_with_all_toolchains_has_no_missing_warning(monkeypatch, tmp_path):
    _only_toolchains(monkeypatch, tmp_path, on_path=tuple({chips.toolchain_prefix(c) for c in chips.ids()}))
    env = doctor.run()
    assert all(v["addr2line"] for v in env["result"]["tools"]["toolchains"].values())
    assert not [w for w in env["warnings"] if w["code"] in ("toolchain_missing", "addr2line_missing")]


def test_health_has_toolchains_next_to_addr2line(api, fake_tools, monkeypatch, tmp_path):  # noqa: F811
    fake_tools.scenario({"--version": {"stdout": "PlatformIO Core, version 6.2.0\n"},
                         "version": {"stdout": "esptool v5.6.0\n"}})
    monkeypatch.setenv("PLATFORMIO_CORE_DIR", str(tmp_path / "no-core"))
    env = api.ok(api.get("/health"))
    tools = env["result"]["tools"]
    assert isinstance(tools["addr2line"], bool)  # the old field stays (any toolchain found)
    assert list(tools["toolchains"]) == chips.ids()
    assert all(set(v) == {"addr2line", "prefix"} for v in tools["toolchains"].values())
    assert tools["toolchains"]["esp32c6"]["prefix"] == "riscv32-esp-elf"
    assert tools["addr2line"] is any(v["addr2line"] for v in tools["toolchains"].values())
    missing = [w for w in env["warnings"] if w["code"] == "toolchain_missing"]
    found = [v["addr2line"] for v in tools["toolchains"].values()]
    if any(found) and not all(found):
        assert len(missing) == 1 and missing[0]["severity"] == "info" and MISSING_TEXT in missing[0]["message"]


def test_doctor_route_has_toolchains(api):
    env = api.get("/doctor").json()
    assert env["action"] == "doctor.run" and set(env["result"]["tools"]["toolchains"]) == set(chips.ids())


@pytest.mark.parametrize("name", ["doctor", "health"])
def test_fixtures_name_every_chip(name):
    env = json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))
    tc = env["result"]["tools"]["toolchains"]
    assert list(tc) == chips.ids()
    assert all(v["prefix"] == chips.toolchain_prefix(c) for c, v in tc.items())
    assert isinstance(env["result"]["tools"]["addr2line"], dict if name == "doctor" else bool)


def test_doctor_route_copy_uses_the_same_register():
    rc = sup.route_module("chips")
    assert rc.ids() == chips.ids()
    assert os.path.samefile(rc.CHIPS_FILE, chips.CHIPS_FILE)
