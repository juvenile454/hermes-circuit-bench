"""The isolation of tests/conftest.py itself."""
import os
import subprocess
import sys
from pathlib import Path

import pytest

from conftest import HardwareAccessRefused


def test_env_is_isolated(tmp_path):
    assert os.environ["HOME"] == str(tmp_path / "home")
    assert os.environ["HERMES_HOME"] == str(tmp_path / "hhome")
    assert os.environ["CIRCUIT_BENCH_HW"] == "off"
    assert os.environ["CIRCUIT_BENCH_DEV_GUARD"] == "1"
    assert os.environ["PATH"].split(os.pathsep)[0].endswith("tests/fakes/bin")
    assert not any(k.startswith("ESPTOOL_") for k in os.environ)


@pytest.mark.parametrize("dev", ["/dev/ttyACM0", "/dev/ttyUSB0", "/dev/serial/by-id/x", "/dev/cu.usbserial"])
def test_serial_devices_refused(dev):
    with pytest.raises(HardwareAccessRefused):
        open(dev, "rb")
    with pytest.raises(HardwareAccessRefused):
        os.open(dev, os.O_RDONLY)


@pytest.mark.parametrize("argv", [
    ["esptool", "flash-id"],
    ["/usr/bin/pio", "run", "-t", "upload"],
    ["xtensa-esp32s3-elf-addr2line", "-e", "x"],
    [sys.executable, "-m", "esptool", "chip-id"],
])
def test_real_tools_refused(argv):
    with pytest.raises(HardwareAccessRefused):
        subprocess.run(argv, check=False)


def test_toolchain_mode_allows_offline_only(monkeypatch):
    monkeypatch.setenv("CB_TOOLCHAIN_TESTS", "1")
    with pytest.raises(HardwareAccessRefused):
        subprocess.run(["/nonexistent/pio", "run", "-t", "upload"], check=False)
    with pytest.raises(HardwareAccessRefused):  # without -t pio runs the `targets` of platformio.ini
        subprocess.run(["/nonexistent/pio", "run", "-d", "x"], check=False)
    with pytest.raises(FileNotFoundError):  # allowed by the hook, then simply missing
        subprocess.run(["/nonexistent/pio", "run", "-d", "x", "-t", "checkprogsize", "-t", "buildprog"], check=False)
    with pytest.raises(FileNotFoundError):
        subprocess.run(["/nonexistent/riscv32-esp-elf-addr2line", "-e", "x"], check=False)


def test_fakes_are_allowed():
    fake = Path(__file__).resolve().parent / "fakes" / "bin" / "cb-fake-tool"
    assert subprocess.run([str(fake), "x"], check=False, timeout=30).returncode == 0
