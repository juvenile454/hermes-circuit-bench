"""Before a real flash the computed PlatformIO configuration (`pio project config --json-output`) is
checked: upload_protocol = custom, upload_command and erase flags (also from extra_configs/extends/[env]) refuse."""
import json

import pytest
import board_fixtures as bf
from board_fixtures import *  # noqa: F403

from circuit_bench.bench_core import board

BASE = "[env:s3]\nplatform = espressif32@6.9.0\nboard = esp32-s3-devkitc-1\nframework = arduino\n"


def _project(tmp_path, ini=BASE, extra=None):
    d = tmp_path / "fw"
    (d / "src").mkdir(parents=True, exist_ok=True)
    (d / "platformio.ini").write_text(ini, encoding="utf-8")
    (d / "src" / "main.cpp").write_text("void setup() {}\nvoid loop() {}\n", encoding="utf-8")
    for name, text in (extra or {}).items():
        (d / name).write_text(text, encoding="utf-8")
    return d


def _flash(fake_tools, d, port):
    fake_tools.scenario("board-pio-flash-ok.json")
    env = board.build(d, "s3")
    assert env["ok"], env["error"]
    r = env["result"]
    return board.flash(d, "s3", port, expected_elf_sha256=r["elf_sha256"], guard=lambda: None,
                       expected_images=r["images"])


@pytest.mark.parametrize(("ini", "extra", "needle"), [
    ("[platformio]\nextra_configs = more.ini\n" + BASE, {"more.ini": "[env:s3]\nupload_protocol = custom\n"},
     "upload_protocol = custom"),
    (BASE + "upload_command = $PYTHONEXE my_uploader.py $SOURCE\n", None, "upload_command"),
    ("[platformio]\nextra_configs = flags.ini\n" + BASE,  # the text check of platformio.ini cannot see this one
     {"flags.ini": "[env]\nupload_flags =\n    --before=default_reset\n    --erase-all\n"}, "erase"),
    ("[base]\nupload_flags = -e\n" + BASE + "extends = base\n", None, "erase"),
])
def test_effective_config_refuses_custom_upload_and_erase(fake_tools, tmp_path, hw_on, pty_port, monkeypatch, ini,
                                                          extra, needle):
    bf.mock_comports(monkeypatch, [(pty_port.name, 0x303A, 0x1001, "USB JTAG/serial debug unit")])
    d = _project(tmp_path, ini, extra)
    env = _flash(fake_tools, d, pty_port.name)
    assert env["ok"] is False and env["error"]["code"] == "invalid_args" and needle in env["error"]["message"]
    assert "Circuit Bench writes the built images itself" in env["error"]["hint"]
    assert not any("write-flash" in c["argv"] or "upload" in c["argv"] for c in fake_tools.calls())
    assert ["project", "config", "--json-output", "-d", str(d.resolve())] in [c["argv"] for c in fake_tools.calls("pio")]


def test_plain_config_flashes(fake_tools, tmp_path, hw_on, pty_port, monkeypatch):
    bf.mock_comports(monkeypatch, [(pty_port.name, 0x303A, 0x1001, "USB JTAG/serial debug unit")])
    env = _flash(fake_tools, _project(tmp_path, BASE + "upload_flags = --before=default_reset\n"), pty_port.name)
    assert env["ok"], env["error"]


def test_unreadable_config_refuses(fake_tools, tmp_path, hw_on, pty_port, monkeypatch):
    bf.mock_comports(monkeypatch, [(pty_port.name, 0x303A, 0x1001, "USB JTAG/serial debug unit")])
    d = _project(tmp_path)
    data = json.loads((bf.SCENARIOS / "board-pio-flash-ok.json").read_text(encoding="utf-8"))
    data["config"] = {"rc": 1, "stdout": "InvalidProjectConfError: broken\n"}
    fake_tools.scenario(data)
    r = board.build(d, "s3")["result"]
    env = board.flash(d, "s3", pty_port.name, expected_elf_sha256=r["elf_sha256"], guard=lambda: None)
    assert env["ok"] is False and env["error"]["code"] == "tool_failed"
    data["config"] = {"rc": 0, "stdout": "no json here\n"}
    fake_tools.scenario(data)
    env = board.flash(d, "s3", pty_port.name, expected_elf_sha256=r["elf_sha256"], guard=lambda: None)
    assert env["error"]["code"] == "tool_failed"
    assert not any("write-flash" in c["argv"] or "upload" in c["argv"] for c in fake_tools.calls())


def test_config_check_against_the_real_output_shape():
    """The shape PlatformIO Core 6.2.0 prints (observed offline: lists for multi-value options)."""
    real = [["platformio", [["default_envs", ["s3"]], ["extra_configs", ["more.ini"]]]],
            ["env:s3", [["extends", ["base"]], ["platform", "espressif32@6.9.0"], ["upload_command", "echo $SOURCE"],
                        ["upload_protocol", "custom"], ["upload_flags", ["--erase-all"]]]]]
    def message(env):
        err = board._upload_config_refusal(real, env)
        return err.message if err is not None else None

    assert "upload_protocol" in message("s3")
    real[1][1] = [o for o in real[1][1] if o[0] != "upload_protocol"]
    assert "upload_command" in message("s3")
    real[1][1] = [o for o in real[1][1] if o[0] != "upload_command"]
    assert "erase" in message("s3")
    real[1][1] = [o for o in real[1][1] if o[0] != "upload_flags"]
    assert message("s3") is None
    assert "no [env:c3]" in message("c3")
