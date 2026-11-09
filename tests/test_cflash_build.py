"""board.build(..., chip=) checks the env before pio starts (chip_mismatch, platform_too_old,
platform_unpinned). PlatformIO folders are synthetic (PLATFORMIO_CORE_DIR in tmp_path) with board manifests that
carry only the decisive fields (build.mcu, frameworks as in the pinned espressif32 6.9.0/7.1.3/8.0.0 board JSONs).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
import board_fixtures as bf
from board_fixtures import *  # noqa: F403

from circuit_bench.bench_core import board, contracts

BOARDS = {"esp32-c6-devkitc-1": "esp32c6", "esp32-s3-devkitc-1": "esp32s3", "esp32-s2-saola-1": "esp32s2",
          "wt32-eth01": "esp32", "esp32-c3-devkitm-1": "esp32c3"}


def fake_platform(core: Path, version: str, folder: str = "espressif32") -> Path:
    plat = core / "platforms" / folder
    (plat / "boards").mkdir(parents=True)
    (plat / "platform.json").write_text(json.dumps({"name": "espressif32", "version": version, "packages": {}}),
                                        encoding="utf-8")
    for b, mcu in BOARDS.items():
        (plat / "boards" / f"{b}.json").write_text(json.dumps({"build": {"mcu": mcu}}), encoding="utf-8")
    return plat


@pytest.fixture
def core(tmp_path, monkeypatch):
    c = tmp_path / "pio-core"
    monkeypatch.setenv("PLATFORMIO_CORE_DIR", str(c))
    for key in ("PLATFORMIO_PACKAGES_DIR", "PLATFORMIO_PLATFORMS_DIR", "PLATFORMIO_BOARDS_DIR"):
        monkeypatch.delenv(key, raising=False)
    fake_platform(c, "8.0.0")
    fake_platform(c, "6.9.0", "espressif32@6.9.0")
    return c


def fw(tmp_path: Path, ini: str) -> Path:
    d = tmp_path / "fw"
    (d / "src").mkdir(parents=True, exist_ok=True)
    (d / "platformio.ini").write_text(ini, encoding="utf-8")
    (d / "src" / "main.cpp").write_text("void setup() {}\nvoid loop() {}\n", encoding="utf-8")
    return d


def ini(platform="espressif32@8.0.0", board_id="esp32-c6-devkitc-1", framework="arduino", extra=""):
    return f"[env:e]\nplatform = {platform}\nboard = {board_id}\nframework = {framework}\n{extra}"


def test_c6_on_7_1_3_is_platform_too_old_without_pio(fake_tools, core, tmp_path):
    fake_tools.scenario("board-pio-build-ok.json")
    env = board.build(fw(tmp_path, ini(platform="espressif32@7.1.3")), "e", chip="esp32c6")
    assert contracts.validate_envelope(env) == []
    assert env["error"]["code"] == "platform_too_old" and env["ok"] is False
    assert env["error"]["hint"] == "pin platform = espressif32@8.0.0 (or newer)"
    assert "7.1.3" in env["error"]["message"] and "8.0.0" in env["error"]["message"]
    assert fake_tools.calls() == []  # pio never ran


@pytest.mark.parametrize("platform", ["espressif32@6.9.0", "platformio/espressif32 @ ~7.1.3", "espressif32@^7.0.0",
                                      "espressif32@<8.0.0"])
def test_older_ranges_are_too_old(fake_tools, core, tmp_path, platform):
    fake_tools.scenario("board-pio-build-ok.json")
    env = board.build(fw(tmp_path, ini(platform=platform)), "e", chip="esp32c6")
    assert env["error"]["code"] == "platform_too_old", platform
    assert fake_tools.calls() == []


def test_open_range_uses_the_installed_match(fake_tools, core, tmp_path):
    """>=7.0.0 with 8.0.0 installed builds; with only 7.1.3 installed pio would take that one: too old."""
    fake_tools.scenario("board-pio-build-ok.json")
    d = fw(tmp_path, ini(platform="espressif32@>=7.0.0"))
    assert board.build(d, "e", chip="esp32c6")["ok"]
    import shutil
    shutil.rmtree(core / "platforms" / "espressif32")
    fake_platform(core, "7.1.3")
    env = board.build(d, "e", chip="esp32c6")
    assert env["error"]["code"] == "platform_too_old" and "installed match: 7.1.3" in env["error"]["message"]


@pytest.mark.parametrize("platform", ["espressif32@8.0.0", "espressif32 @ ^8.0.0", "espressif32@>=8.0.0"])
def test_c6_on_8_0_0_builds(fake_tools, core, tmp_path, platform):
    fake_tools.scenario("board-pio-build-ok.json")
    env = board.build(fw(tmp_path, ini(platform=platform)), "e", chip="esp32c6")
    assert contracts.validate_envelope(env) == [] and env["ok"], env["error"]
    assert [c["argv"][0] for c in fake_tools.calls("pio")] == ["run", "project"]
    (chk,) = [c for c in env["checks"] if c["id"] == "board.build.chip"]
    assert chk["status"] == "passed" and "esp32c6" in chk["detail"]
    assert not any(w["code"] == "platform_unpinned" for w in env["warnings"])
    assert {"pio-esp32-8.0.0-board-c6", "cflash-pio-boards-dir"} <= {s["id"] for s in env["sources"]}


def test_newer_pin_not_installed_builds_without_the_mcu_check(fake_tools, core, tmp_path):
    """8.1.0 is new enough; it is not installed, so the board manifest (MCU) is unknown: info, no claim, no refusal."""
    fake_tools.scenario("board-pio-build-ok.json")
    env = board.build(fw(tmp_path, ini(platform="espressif32@8.1.0")), "e", chip="esp32c6")
    assert env["ok"] and not any(c["id"] == "board.build.chip" for c in env["checks"])
    assert any(w["code"] == "chip_unchecked" and w["severity"] == "info" for w in env["warnings"])


def test_env_mcu_s3_on_a_c6_project_is_chip_mismatch(fake_tools, core, tmp_path):
    fake_tools.scenario("board-pio-build-ok.json")
    env = board.build(fw(tmp_path, ini(board_id="esp32-s3-devkitc-1")), "e", chip="esp32c6")
    assert contracts.validate_envelope(env) == []
    assert env["error"]["code"] == "chip_mismatch"
    assert "esp32s3" in env["error"]["message"] and "esp32c6" in env["error"]["message"]  # names both
    assert fake_tools.calls() == []


def test_board_build_mcu_override_and_project_boards(fake_tools, core, tmp_path):
    fake_tools.scenario("board-pio-build-ok.json")
    d = fw(tmp_path, ini(board_id="esp32-s3-devkitc-1", extra="board_build.mcu = esp32c6\n"))
    assert board.build(d, "e", chip="esp32c6")["ok"]  # board_build.mcu wins over the manifest
    d = fw(tmp_path, ini(board_id="my-c6"))
    (d / "boards").mkdir()
    (d / "boards" / "my-c6.json").write_text(json.dumps({"build": {"mcu": "esp32s2"}}), encoding="utf-8")
    env = board.build(d, "e", chip="esp32c6")
    assert env["error"]["code"] == "chip_mismatch" and "esp32s2" in env["error"]["message"]


def test_installed_version_decides_the_board_manifest(fake_tools, core, tmp_path):
    """The manifest comes from the platform version the env pins (espressif32@6.9.0 here)."""
    (core / "platforms" / "espressif32@6.9.0" / "boards" / "esp32-c6-devkitc-1.json").write_text(
        json.dumps({"build": {"mcu": "esp32c3"}}), encoding="utf-8")  # synthetic: only to tell the folders apart
    fake_tools.scenario("board-pio-build-ok.json")
    env = board.build(fw(tmp_path, ini(platform="espressif32@6.9.0", framework="espidf")), "e", chip="esp32c6")
    assert env["error"]["code"] == "chip_mismatch" and "esp32c3" in env["error"]["message"]
    assert board.build(fw(tmp_path, ini(framework="espidf")), "e", chip="esp32c6")["ok"]


def test_unpinned_platform_only_warns(fake_tools, core, tmp_path):
    fake_tools.scenario("board-pio-build-ok.json")
    env = board.build(fw(tmp_path, ini(platform="espressif32")), "e", chip="esp32c6")
    assert env["ok"], env["error"]
    (w,) = [w for w in env["warnings"] if w["code"] == "platform_unpinned"]
    assert w["severity"] == "caution" and "pin platform = espressif32@8.0.0 (or newer)" in w["message"]
    assert "installed: espressif32 8.0.0" in w["message"]
    url = "https://github.com/pioarduino/platform-espressif32/releases/download/55.03.30/platform-espressif32.zip"
    env = board.build(fw(tmp_path, ini(platform=url)), "e", chip="esp32c6")
    assert env["ok"] and any(w["code"] == "platform_unpinned" for w in env["warnings"])


def test_floor_applies_only_to_arduino_and_to_chips_with_a_floor(fake_tools, core, tmp_path):
    fake_tools.scenario("board-pio-build-ok.json")
    # ESP-IDF on 6.9.0: the board JSON lists espidf, no Arduino floor
    assert board.build(fw(tmp_path, ini(platform="espressif32@6.9.0", framework="espidf")), "e", chip="esp32c6")["ok"]
    # S2, WT32 (esp32), S3 have no floor: 6.9.0 with Arduino stays fine, no unpinned warning either
    for b, chip in (("esp32-s2-saola-1", "esp32s2"), ("wt32-eth01", "esp32"), ("esp32-s3-devkitc-1", "esp32s3")):
        env = board.build(fw(tmp_path, ini(platform="espressif32@6.9.0", board_id=b)), "e", chip=chip)
        assert env["ok"] and not any(w["code"] == "platform_unpinned" for w in env["warnings"]), b
        env = board.build(fw(tmp_path, ini(platform="espressif32", board_id=b)), "e", chip=chip)
        assert env["ok"] and not any(w["code"] == "platform_unpinned" for w in env["warnings"]), b


def test_unreadable_env_is_not_refused(fake_tools, core, tmp_path):
    fake_tools.scenario("board-pio-build-ok.json")
    d = fw(tmp_path, "[platformio]\nextra_configs = more.ini\n" + ini())
    env = board.build(d, "e", chip="esp32c6")
    assert env["ok"] and any(w["code"] == "chip_unchecked" and w["severity"] == "info" for w in env["warnings"])
    assert not any(c["id"] == "board.build.chip" for c in env["checks"])  # nothing claimed
    env = board.build(fw(tmp_path, ini(board_id="not-installed-board")), "e", chip="esp32c6")
    assert env["ok"] and any(w["code"] == "chip_unchecked" for w in env["warnings"])
    env = board.build(fw(tmp_path, ini(board_id="${sysenv.CB_BOARD}")), "e", chip="esp32c6")
    assert env["ok"] and any(w["code"] == "chip_unchecked" for w in env["warnings"])


def test_without_chip_nothing_changes(fake_tools, core, tmp_path):
    fake_tools.scenario("board-pio-build-ok.json")
    env = board.build(fw(tmp_path, ini(platform="espressif32@7.1.3", board_id="esp32-s3-devkitc-1")), "e")
    assert env["ok"] and not any(c["id"] == "board.build.chip" for c in env["checks"])
    assert not any(w["code"] in ("platform_unpinned", "chip_unchecked") for w in env["warnings"])


def test_extends_and_env_defaults(fake_tools, core, tmp_path):
    fake_tools.scenario("board-pio-build-ok.json")
    text = ("[env]\nframework = arduino\n\n[c6base]\nplatform = espressif32@7.1.3\nboard = esp32-c6-devkitc-1\n\n"
            "[env:e]\nextends = c6base\n")
    assert board.build(fw(tmp_path, text), "e", chip="esp32c6")["error"]["code"] == "platform_too_old"


def test_precheck_runs_before_a_provider_build(fake_tools, core, tmp_path):
    prov = bf.TestProvider()
    board.register_provider("sim://", prov)
    d = fw(tmp_path, ini(board_id="esp32-s3-devkitc-1"))
    env = board.build(d, "e", port="sim://test-s3", chip="esp32c6")
    assert env["error"]["code"] == "chip_mismatch"
    env = board.build(d, "e", port="sim://test-s3", chip="esp32s3")
    assert env["ok"] and env["simulated"] is True
    assert any(c["id"] == "board.build.chip" for c in env["checks"])


@pytest.mark.parametrize(("req", "version", "ok"), [
    ("8.0.0", "8.0.0", True), ("8.0.0", "8.0.1", False), ("~6.9.0", "6.9.4", True), ("~6.9.0", "6.10.0", False),
    ("^6.9.0", "6.12.0", True), ("^6.9.0", "7.0.0", False), (">=8.0.0", "8.0.0", True), (">=7,<8", "7.1.3", True),
    (">=7,<8", "8.0.0", False), (None, "1.0.0", True), ("foo", "1.0.0", False), ("8.0.0", "x", False),
])
def test_version_matches(req, version, ok):
    assert board.version_matches(version, req) is ok


def test_parse_platform():
    assert board.parse_platform("platformio/espressif32 @ ^6.9.0") == {
        "raw": "platformio/espressif32 @ ^6.9.0", "name": "espressif32", "requirements": "^6.9.0", "external": False}
    assert board.parse_platform("espressif32")["requirements"] is None
    assert board.parse_platform("https://github.com/x/platform-espressif32.git")["external"] is True
    assert board.parse_platform("")["name"] is None


def test_installed_platform_picks_the_highest_match(core):
    assert board.installed_platform("6.9.0")[1]["version"] == "6.9.0"
    assert board.installed_platform(None)[1]["version"] == "8.0.0"
    assert board.installed_platform("~6.9.0")[0].name == "espressif32@6.9.0"
    assert board.installed_platform("7.1.3") is None
