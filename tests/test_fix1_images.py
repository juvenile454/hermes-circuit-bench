"""The build records the SHA-256 of firmware.bin (and bootloader.bin, partitions.bin); the flash writes
only exactly those images."""
import json
from pathlib import Path

import pytest
import board_fixtures as bf
from board_fixtures import *  # noqa: F403

from circuit_bench.bench_core import board, project, storage

SHA = "a" * 64


@pytest.fixture
def fw(tmp_path):
    d = tmp_path / "fw"
    (d / "src").mkdir(parents=True)
    (d / "platformio.ini").write_text("[env:s3]\nplatform = espressif32@6.9.0\nboard = esp32-s3-devkitc-1\n"
                                      "framework = arduino\n", encoding="utf-8")
    (d / "src" / "main.cpp").write_text("void setup() {}\nvoid loop() {}\n", encoding="utf-8")
    return d


def _scenario(fake_tools, extra=True):
    data = json.loads((bf.SCENARIOS / "board-pio-flash-ok.json").read_text(encoding="utf-8"))
    if extra:
        data["run"]["write_files"]["{project_dir}/.pio/build/{env}/bootloader.bin"] = "FAKE-BOOT\n"
        data["run"]["write_files"]["{project_dir}/.pio/build/{env}/partitions.bin"] = "FAKE-PART\n"
    fake_tools.scenario(data)


def _build(fake_tools, fw, extra=True):
    _scenario(fake_tools, extra)
    env = board.build(fw, "s3")
    assert env["ok"], env["error"]
    return env["result"]


def test_build_records_the_image_hashes(fake_tools, fw):
    r = _build(fake_tools, fw)
    out = fw / ".pio" / "build" / "s3"
    assert r["images"] == {name: board.sha256_file(out / name) for name in ("bootloader.bin", "firmware.bin", "partitions.bin")}
    assert _build(fake_tools, fw, extra=False)["images"].keys() >= {"firmware.bin"}


def test_project_keeps_images_and_old_projects_stay_valid(fake_tools, fw):
    assert project.create("img", "Images", "esp32s3", "n16r8")["ok"]
    r = _build(fake_tools, fw)
    upd = project.update("img", 1, [{"op": "set_firmware", "dir": str(fw), "env": "s3"}, {"op": "set_build", **r}],
                         by="agent", trusted=True)
    assert upd["ok"], upd["error"]
    stored = upd["result"]["project"]["firmware"]["last_build"]
    assert stored["images"] == r["images"] and project.validate(upd["result"]["project"]) == []
    old = dict(upd["result"]["project"])
    old["firmware"] = {**old["firmware"], "last_build": {k: v for k, v in stored.items() if k != "images"}}
    assert project.validate(old) == []  # projects built before image recording have no images
    for bad in ({"firmware.bin": "x"}, {"../x.bin": SHA}, {"firmware.elf": SHA}, ["firmware.bin"]):
        env = project.update("img", upd["result"]["rev"], [{"op": "set_build", "ok": True, "elf_sha256": SHA,
                                                             "images": bad}], by="agent", trusted=True)
        assert env["error"]["code"] == "invalid_args", bad


def test_flash_refuses_a_changed_image(fake_tools, fw, hw_on, pty_port, monkeypatch):
    bf.mock_comports(monkeypatch, [(pty_port.name, 0x303A, 0x1001, "USB JTAG/serial debug unit")])
    r = _build(fake_tools, fw)
    out = fw / ".pio" / "build" / "s3"
    for name in ("firmware.bin", "bootloader.bin", "partitions.bin"):
        original = (out / name).read_bytes()
        (out / name).write_bytes(b"swapped after the build\n")  # newer mtime: the old age check would pass
        env = board.flash(fw, "s3", pty_port.name, expected_elf_sha256=r["elf_sha256"], guard=lambda: None,
                          expected_images=r["images"])
        assert env["error"]["code"] == "elf_mismatch" and name in env["error"]["message"], name
        assert "rebuild" in env["error"]["hint"]
        (out / name).write_bytes(original)
    (out / "partitions.bin").unlink()
    env = board.flash(fw, "s3", pty_port.name, expected_elf_sha256=r["elf_sha256"], guard=lambda: None,
                      expected_images=r["images"])
    assert env["error"]["code"] == "elf_mismatch" and "missing" in env["error"]["message"]
    assert not any("write-flash" in c["argv"] for c in fake_tools.calls())


def test_flash_with_matching_images_uploads(fake_tools, fw, hw_on, pty_port, monkeypatch):
    bf.mock_comports(monkeypatch, [(pty_port.name, 0x303A, 0x1001, "USB JTAG/serial debug unit")])
    r = _build(fake_tools, fw)
    env = board.flash(fw, "s3", pty_port.name, expected_elf_sha256=r["elf_sha256"], guard=lambda: None,
                      expected_images=r["images"])
    assert env["ok"], env["error"]
    (write,) = [c for c in fake_tools.calls("esptool") if "write-flash" in c["argv"]]
    snap = storage.data_dir() / "tmp"  # esptool reads private copies of the checked images
    assert [(Path(a).parent.parent, Path(a).name) for a in write["argv"] if a.endswith(".bin")] == [
        (snap, "bootloader.bin"), (snap, "partitions.bin"), (snap, "boot_app0.bin"), (snap, "firmware.bin")]
    env = board.flash(fw, "s3", pty_port.name, expected_elf_sha256=r["elf_sha256"], guard=lambda: None,
                      expected_images={"bootloader.bin": r["images"]["bootloader.bin"]})
    assert env["error"]["code"] == "elf_mismatch" and "firmware.bin" in env["error"]["message"]
