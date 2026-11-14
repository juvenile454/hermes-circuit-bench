"""A prog_path or flash image path in PlatformIO's metadata that is no usable path ends with an error code of the list
(elf_missing for the ELF, tool_failed for a flash image), never with a raw exception, and never reaches esptool. The
fake pio/esptool and a pty port stand in for PlatformIO, esptool and the board (nothing reaches a real device)."""
from __future__ import annotations

import json

import pytest
import board_fixtures as bf
from board_fixtures import *  # noqa: F403

from circuit_bench.bench_core import board, contracts


@pytest.fixture
def fw(tmp_path):
    d = tmp_path / "fw"
    (d / "src").mkdir(parents=True)
    (d / "platformio.ini").write_text("[env:s3]\nplatform = espressif32@6.9.0\nboard = esp32-s3-devkitc-1\n"
                                      "framework = arduino\n", encoding="utf-8")
    (d / "src" / "main.cpp").write_text("void setup() {}\nvoid loop() {}\n", encoding="utf-8")
    return d


@pytest.fixture
def port(hw_on, pty_port, monkeypatch):
    bf.mock_comports(monkeypatch, [(pty_port.name, 0x303A, 0x1001, "USB JTAG/serial debug unit")])
    return pty_port.name


def _scenario(fake_tools, prog_path=None, images=None):
    data = json.loads((bf.SCENARIOS / "board-pio-flash-ok.json").read_text(encoding="utf-8"))
    entry = data["metadata"]["json"]["{env}"]
    if prog_path is not None:
        entry["prog_path"] = prog_path
    if images is not None:
        entry["extra"]["flash_images"] = images(entry["extra"]["flash_images"])
    fake_tools.scenario(data)


def _built(fake_tools, fw):
    fake_tools.scenario("board-pio-flash-ok.json")
    env = board.build(fw, "s3")
    assert env["ok"], env["error"]
    return env["result"]


def _flash(fw, port, r):
    return board.flash(fw, "s3", port, expected_elf_sha256=r["elf_sha256"], guard=lambda: None,
                       expected_images=r["images"])


def _refused(env, code):
    assert contracts.validate_envelope(env) == [], env
    assert env["ok"] is False and env["error"]["code"] == code, env["error"]


class PathLike:
    """An os.PathLike whose ``__fspath__`` returns ``value`` (also something that is not text)."""

    def __init__(self, value):
        self.value = value

    def __fspath__(self):
        return self.value


NOT_TEXT = [123, True, ["{project_dir}/.pio/build/{env}/firmware.elf"], {"p": "{project_dir}/.pio/build/{env}/f.elf"}]
ROOT = ["/", "/.", "//", "/x/..", "/../..", "{project_dir}/" + "../" * 40]


@pytest.mark.parametrize("prog", NOT_TEXT, ids=["int", "bool", "list", "dict"])
def test_prog_path_that_is_not_text_is_elf_missing_in_the_flash(fake_tools, fw, port, prog):
    r = _built(fake_tools, fw)
    _scenario(fake_tools, prog_path=prog)
    _refused(_flash(fw, port, r), "elf_missing")
    assert fake_tools.calls("esptool") == []


@pytest.mark.parametrize("prog", ROOT)
def test_prog_path_that_normalises_to_the_root_is_elf_missing_in_the_flash(fake_tools, fw, port, prog):
    r = _built(fake_tools, fw)
    _scenario(fake_tools, prog_path=prog)
    _refused(_flash(fw, port, r), "elf_missing")
    assert fake_tools.calls("esptool") == []


@pytest.mark.parametrize("prog", NOT_TEXT, ids=["int", "bool", "list", "dict"])
def test_prog_path_that_is_not_text_is_elf_missing_in_the_build(fake_tools, fw, prog):
    _scenario(fake_tools, prog_path=prog)
    _refused(board.build(fw, "s3"), "elf_missing")


def test_prog_path_with_a_nul_character_is_elf_missing(fake_tools, fw, port):
    r = _built(fake_tools, fw)
    _scenario(fake_tools, prog_path="{project_dir}/.pio/build/{env}/firmware\u0000.elf")
    _refused(_flash(fw, port, r), "elf_missing")
    assert fake_tools.calls("esptool") == []


@pytest.mark.parametrize("value", [123, ["x"], {"p": 1}, b"/tmp/firmware.elf"], ids=["int", "list", "dict", "bytes"])
def test_prog_path_object_with_a_bad_fspath_is_elf_missing(fake_tools, fw, port, monkeypatch, value):
    """A metadata reader that hands over path objects: one whose __fspath__ gives no text."""
    r = _built(fake_tools, fw)
    real = board.metadata
    monkeypatch.setattr(board, "metadata", lambda *a, **kw: {**real(*a, **kw), "prog_path": PathLike(value)})
    _refused(_flash(fw, port, r), "elf_missing")
    assert fake_tools.calls("esptool") == []


@pytest.mark.parametrize("value", [123, ["x"], b"/tmp/bootloader.bin"], ids=["int", "list", "bytes"])
def test_flash_image_object_with_a_bad_fspath_is_tool_failed(fake_tools, fw, port, monkeypatch, value):
    r = _built(fake_tools, fw)
    real = board.metadata

    def meta(*a, **kw):
        m = real(*a, **kw)
        return {**m, "flash_images": [dict(m["flash_images"][0], path=PathLike(value)), *m["flash_images"][1:]]}

    monkeypatch.setattr(board, "metadata", meta)
    _refused(_flash(fw, port, r), "tool_failed")
    assert fake_tools.calls("esptool") == []


def test_flash_image_path_with_a_nul_character_is_a_missing_image(fake_tools, fw, port):
    r = _built(fake_tools, fw)
    _scenario(fake_tools, images=lambda items: [dict(items[0], path=items[0]["path"] + "\u0000x"), *items[1:]])
    _refused(_flash(fw, port, r), "elf_missing")
    assert fake_tools.calls("esptool") == []


def test_a_proper_prog_path_still_flashes(fake_tools, fw, port):
    r = _built(fake_tools, fw)
    env = _flash(fw, port, r)
    assert env["ok"], env["error"]
    assert len([c for c in fake_tools.calls("esptool") if "write-flash" in c["argv"]]) == 1
