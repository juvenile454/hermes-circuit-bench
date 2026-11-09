"""Build safety with the real PlatformIO (marker toolchain, CB_TOOLCHAIN_TESTS=1).

Never uploads: copies of the example firmware under tmp_path, PLATFORMIO_BUILD_DIR in tmp_path, `pio run` only with
the explicit build targets (the example has no `targets` option; with -t the ini's targets would not run anyway).
- targets: board.build runs `pio run -t checkprogsize -t buildprog`; the size lines still reach parse_sizes; the images
  exist; nothing but the build targets ran;
- config: `pio project config --json-output` resolves extra_configs/extends and runs no extra_scripts;
- packages: the packages the example needs are found offline in the real core folder.
"""
import json
import os
import shutil
from pathlib import Path

import pytest

from circuit_bench.bench_core import board, clitools, sim, storage

pytestmark = pytest.mark.toolchain

EXAMPLE = Path(__file__).resolve().parents[1] / "circuit_bench" / "data" / "examples" / "laser-trigger"
REAL_HOME = storage.real_home()
PIO = REAL_HOME / ".local" / "bin" / "pio"
CORE = REAL_HOME / ".platformio"


@pytest.fixture
def real_pio(tmp_path, monkeypatch):
    if os.environ.get("CB_TOOLCHAIN_TESTS") != "1" or not PIO.is_file() or not (CORE / "platforms" / "espressif32").is_dir():
        pytest.skip("needs CB_TOOLCHAIN_TESTS=1, ~/.local/bin/pio and espressif32")
    monkeypatch.setenv("PLATFORMIO_CORE_DIR", str(CORE))
    monkeypatch.setenv("PLATFORMIO_BUILD_DIR", str(tmp_path / "build"))
    monkeypatch.setenv("CIRCUIT_BENCH_SETTINGS_JSON", json.dumps({"pio_path": str(PIO)}))
    work = tmp_path / "example-fw"
    shutil.copytree(EXAMPLE, work, ignore=shutil.ignore_patterns(".pio"))
    assert "targets" not in (work / "platformio.ini").read_text(encoding="utf-8")  # the example has no ini targets
    return work


def test_build_with_explicit_targets_keeps_the_size_lines(real_pio, tmp_path, monkeypatch):
    seen = []
    real_run = clitools.run

    def spy(argv, **kw):
        seen.append(list(argv))
        return real_run(argv, **kw)

    monkeypatch.setattr(clitools, "run", spy)
    env = board.build(real_pio, "s3")
    assert env["ok"], env["error"]
    r = env["result"]
    runs = [a for a in seen if a[1:2] == ["run"]]
    assert len(runs) == 1 and clitools.pio_targets(runs[0]) == ["checkprogsize", "buildprog"]
    assert all(clitools.touches_hardware(a) is False for a in seen)
    assert 0 < r["ram_pct"] < 100 and 0 < r["flash_pct"] < 100 and r["ram_total"] and r["flash_total"]
    out = tmp_path / "build" / "s3"
    assert set(r["images"]) == {"firmware.bin", "bootloader.bin", "partitions.bin"}
    assert r["images"]["firmware.bin"] == board.sha256_file(out / "firmware.bin")
    assert r["elf_sha256"] == board.sha256_file(out / "firmware.elf")


def test_project_config_runs_no_extra_scripts(real_pio, tmp_path):
    marker = tmp_path / "extra-script-ran"
    (real_pio / "marker.py").write_text(f"open({str(marker)!r}, 'w').write('ran')\n", encoding="utf-8")
    (real_pio / "more.ini").write_text("[env:s3]\nupload_flags = --erase-all\n", encoding="utf-8")
    ini = real_pio / "platformio.ini"
    text = ini.read_text(encoding="utf-8").replace("[platformio]\n", "[platformio]\nextra_configs = more.ini\n")
    ini.write_text(text + "extra_scripts = pre:marker.py\n", encoding="utf-8")
    cfg = board.project_config(real_pio)
    env_s3 = dict(next(opts for name, opts in cfg if name == "env:s3"))
    assert env_s3["upload_flags"] == ["--erase-all"] and env_s3["extra_scripts"] == ["pre:marker.py"]
    assert not marker.exists()
    err = board._upload_config_refusal(cfg, "s3")
    assert err is not None and "erase" in err.message


def test_example_packages_are_installed_offline(real_pio):
    ready, missing = sim._offline_ready(real_pio, "s3")
    assert ready, missing
