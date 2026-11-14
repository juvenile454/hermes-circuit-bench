"""Board identity of a flash (USB identity, stop at a foreign MAC line, check after the
write) and no flash without the complete image set. Only fakes: fake esptool/pio, pty ports, mocked port lists,
synthetic MACs (02:00:00:00:00:xx) and serial numbers (TEST000x)."""
import json
import os
import sys
import time
import types

import board_fixtures as bf
import pytest
from board_fixtures import *  # noqa: F403

from circuit_bench import hooks, tools
from circuit_bench.bench_core import board, contracts, project, serialport

MAC = "02:00:00:00:00:01"
FOREIGN = "02:00:00:00:00:02"
USB = {"vid": "303a", "pid": "1001", "serial": "TEST0001"}
HEADER = ("esptool v5.6.0\nConnected to ESP32-S3 on {port}:\nChip type:          ESP32-S3 (QFN56) (revision v0.2)\n"
          "Features:           Wi-Fi, BT 5 (LE), Dual Core + LP Core, 240MHz\nCrystal frequency:  40MHz\n")
STUB = "\nUploading stub flasher...\nRunning stub flasher...\nStub flasher running.\n\nConfiguring flash size...\n"
WRITE = ("Flash will be erased from 0x00010000 to 0x0004ffff...\n"
         "Writing at 0x00010000 [=====>     ] 52.3%\nWrote 263488 bytes (169392 compressed) at 0x00010000 in 3.9 seconds.\n")


def mac_line(mac):
    return f"{'MAC:':<20}{mac}\n"  # esptool 5.6.0 pads the label to 20 characters


def verified(n=4):
    return "Hash of data verified.\n" * n + "\nHard resetting via RTS pin...\n"


@pytest.fixture
def fw(tmp_path):
    d = tmp_path / "fw"
    (d / "src").mkdir(parents=True)
    (d / "platformio.ini").write_text("[env:s3]\nplatform = espressif32@6.9.0\nboard = esp32-s3-devkitc-1\n"
                                      "framework = arduino\n", encoding="utf-8")
    (d / "src" / "main.cpp").write_text("void setup() {}\nvoid loop() {}\n", encoding="utf-8")
    return d


def _built(fake_tools, fw, **steps):
    fake_tools.scenario("board-pio-flash-ok.json", **steps)
    env = board.build(fw, "s3")
    assert env["ok"], env["error"]
    return env["result"]


def _ports(monkeypatch, pty_port, serial: str | None = "TEST0001"):
    return bf.mock_comports(monkeypatch, [(pty_port.name, 0x303A, 0x1001, "USB JTAG/serial debug unit", serial)])


def _expected(pty_port, mac=MAC, usb=USB):
    out = {"port": pty_port.name, "mac": mac, "chip": "ESP32-S3 (QFN56) (revision v0.2)"}
    if usb is not None:
        out["usb_id"] = dict(usb)
    return out


def _flash(fw, pty_port, build, expected, **kw):
    return board.flash(fw, "s3", pty_port.name, expected_elf_sha256=build["elf_sha256"], guard=lambda: None,
                       expected_images=build.get("images"), expected_board=expected, **kw)


def _checks(env):
    return {c["id"]: c["status"] for c in env["checks"]}


def _new_project(pid="hb-id", detected=None):
    env = project.create(pid, "Identity", "esp32s3", "n16r8", "esp32-s3-devkitc-1", by="agent")
    assert env["ok"], env
    if detected is not None:
        upd = project.update(pid, 1, [{"op": "set_detected", **detected}], by="ui", trusted=True)
        assert upd["ok"], upd
        return upd["result"]["project"]
    return env["result"]["project"]


# ------------------------------------------------------------------------------------------------ A1a usb_id

def test_detect_reports_usb_id_and_the_project_stores_it(fake_tools, hw_on, pty_port, monkeypatch):
    _ports(monkeypatch, pty_port)
    fake_tools.scenario("board-esptool-s3.json")
    env = board.detect(pty_port.name)
    assert env["ok"], env["error"]
    assert env["result"]["usb_id"] == USB
    proj = _new_project(detected=env["result"])
    assert proj["board"]["detected"]["usb_id"] == USB
    again = project.get("hb-id")
    assert again["ok"] and again["result"]["project"]["board"]["detected"]["usb_id"] == USB  # stored form loads
    # the public port list stays as it was (fixture ports.json): no serial number in it
    listed = board.ports()["result"]["ports"]
    assert listed and set(listed[0]) == {"device", "vid", "pid", "description", "kind", "likely_esp", "simulated"}


def test_detect_without_serial_number_has_no_usb_id(fake_tools, hw_on, pty_port, monkeypatch):
    _ports(monkeypatch, pty_port, serial=None)
    fake_tools.scenario("board-esptool-s3.json")
    env = board.detect(pty_port.name)
    assert env["ok"] and env["result"]["usb_id"] is None
    proj = _new_project(detected=env["result"])
    assert "usb_id" not in proj["board"]["detected"]  # stored only when set (C3)


def test_old_project_without_usb_id_loads_unchanged():
    """A project stored before USB identities were recorded has no board.detected.usb_id: it must not become project_damaged."""
    _new_project(detected={"port": "/dev/ttyACM0", "mac": MAC, "chip": "ESP32-S3 (QFN56)",
                           "at": "2026-11-06T21:41:07Z"})
    path = project.path("hb-id") / "project.json"
    stored = json.loads(path.read_text(encoding="utf-8"))
    assert "usb_id" not in stored["board"]["detected"]
    before = path.read_bytes()
    env = project.get("hb-id")
    assert env["ok"], env["error"]
    assert env["result"]["project"]["board"]["detected"]["mac"] == MAC
    assert path.read_bytes() == before


@pytest.mark.parametrize("bad", [{"vid": "303", "pid": "1001", "serial": "TEST0001"},
                                 {"vid": "303a", "pid": "10011", "serial": "TEST0001"},
                                 {"vid": "zz3a", "pid": "1001", "serial": "TEST0001"},
                                 {"vid": "303a", "pid": "1001", "serial": ""},
                                 {"vid": "303a", "pid": "1001", "serial": "x" * 65},
                                 {"vid": "303a", "pid": "1001", "serial": "TEST\n0001"},
                                 {"vid": "303a", "pid": "1001"}, "303a:1001", ["303a"]])
def test_bad_usb_id_is_refused(bad):
    _new_project()
    env = project.update("hb-id", 1, [{"op": "set_detected", "port": "/dev/ttyACM0", "mac": MAC, "usb_id": bad}],
                         by="ui", trusted=True)
    assert env["error"]["code"] == "invalid_args" and "usb_id" in env["error"]["message"]


def test_usb_id_is_normalised_to_lower_case_hex():
    proj = _new_project(detected={"port": "/dev/ttyACM0", "mac": MAC,
                                  "usb_id": {"vid": "303A", "pid": "1001", "serial": "TEST0001"}})
    assert proj["board"]["detected"]["usb_id"] == USB
    assert project.get("hb-id")["ok"]


def test_other_serial_number_on_the_same_port_refuses_before_any_tool(fake_tools, fw, hw_on, pty_port, monkeypatch):
    build = _built(fake_tools, fw)
    _ports(monkeypatch, pty_port, serial="TEST0002")
    fake_tools.log.unlink()
    env = _flash(fw, pty_port, build, _expected(pty_port))
    assert contracts.validate_envelope(env) == []
    assert env["error"]["code"] == "not_confirmed"
    assert f"the USB device on {pty_port.name} is not the one detected" in env["error"]["message"]
    assert "TEST0001" in env["error"]["message"] and "TEST0002" in env["error"]["message"]
    assert "detect" in env["error"]["hint"]
    assert fake_tools.calls("esptool") == [] and fake_tools.calls("pio") == []
    # the port is gone from the list (another device, unplugged): refused as well
    bf.mock_comports(monkeypatch, [])
    env = _flash(fw, pty_port, build, _expected(pty_port))
    assert env["error"]["code"] == "not_confirmed" and fake_tools.calls("esptool") == []


def test_same_usb_identity_or_none_recorded_flashes(fake_tools, fw, hw_on, pty_port, monkeypatch):
    _ports(monkeypatch, pty_port)
    build = _built(fake_tools, fw, **{"write-flash": {"stdout": HEADER + mac_line(MAC) + STUB + WRITE + verified()}})
    env = _flash(fw, pty_port, build, _expected(pty_port))
    assert env["ok"], env["error"]
    assert _checks(env)["board.flash.board_identity"] == "passed"
    env = _flash(fw, pty_port, build, _expected(pty_port, usb=None))  # older detection: only the MAC is compared
    assert env["ok"] and _checks(env)["board.flash.board_identity"] == "passed"


# ------------------------------------------------------------------------------------------------ A1b stop

def test_foreign_mac_stops_esptool_before_it_writes(fake_tools, fw, hw_on, pty_port, monkeypatch, tmp_path):
    _ports(monkeypatch, pty_port)
    marker, pid_file = tmp_path / "written.marker", tmp_path / "esptool.pid"
    build = _built(fake_tools, fw, **{"write-flash": {"stdout": "", "phases": [
        {"pid_file": str(pid_file), "stdout": HEADER + mac_line(FOREIGN) + STUB, "sleep": 2},
        {"touch": str(marker), "stdout": WRITE + verified()}]}})
    t0 = time.monotonic()
    env = _flash(fw, pty_port, build, _expected(pty_port))
    took = time.monotonic() - t0
    assert contracts.validate_envelope(env) == []
    assert env["ok"] is False and env["error"]["code"] == "not_confirmed", env
    assert env["error"]["message"] == (f"esptool reported MAC {FOREIGN}, the approved board is {MAC}; "
                                       "stopped before writing")
    assert env["error"]["hint"].startswith("detect the board again")
    r = env["result"]
    assert r["written"] is False and r["ok"] is False and r["mac"] == FOREIGN and r["port"] == pty_port.name
    assert r["duration_s"] < 1.5, r["duration_s"]
    assert took < 1.5 + 5.0  # pio config/metadata and image-info fakes ran before; the write run itself is short
    pid = int(pid_file.read_text())
    assert bf.wait_for(lambda: not _alive(pid), timeout=10), "esptool survived the stop"
    assert not marker.exists()
    assert not any(w["code"] == "board_identity" for w in env["warnings"])
    assert not serialport.pause_path(pty_port.name).exists()


def _alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    try:  # a zombie child of the test process counts as gone
        with open(f"/proc/{pid}/stat", encoding="utf-8") as f:
            return f.read().split(")")[-1].split()[0] != "Z"
    except OSError:
        return False


def test_foreign_mac_after_a_write_line_is_danger(fake_tools, fw, hw_on, pty_port, monkeypatch, tmp_path):
    _ports(monkeypatch, pty_port)
    build = _built(fake_tools, fw, **{"write-flash": {"stdout": "", "phases": [
        {"stdout": HEADER + WRITE + mac_line(FOREIGN), "sleep": 2}, {"stdout": verified()}]}})
    env = _flash(fw, pty_port, build, _expected(pty_port))
    assert env["error"]["code"] == "not_confirmed"
    assert env["result"]["written"] is True and env["result"]["mac"] == FOREIGN
    danger = [w for w in env["warnings"] if w["code"] == "board_identity"]
    assert danger and danger[0]["severity"] == "danger"
    assert env["result"]["duration_s"] < 1.5


def test_no_mac_line_flashes_unchecked(fake_tools, fw, hw_on, pty_port, monkeypatch):
    """Secure Download Mode prints no MAC: the flash runs, identity not_checked plus a caution."""
    _ports(monkeypatch, pty_port)
    build = _built(fake_tools, fw, **{"write-flash": {"stdout": HEADER + STUB + WRITE + verified()}})
    env = _flash(fw, pty_port, build, _expected(pty_port))
    assert env["ok"], env["error"]
    assert _checks(env)["board.flash.board_identity"] == "not_checked"
    warn = [w for w in env["warnings"] if w["code"] == "board_identity_unchecked"]
    assert warn and warn[0]["severity"] == "caution"
    assert env["result"]["mac"] is None


def test_matching_mac_passes_and_base_mac_is_ignored(fake_tools, fw, hw_on, pty_port, monkeypatch):
    _ports(monkeypatch, pty_port)
    c6 = mac_line(MAC) + f"{'BASE MAC:':<20}{FOREIGN}\n" + f"{'MAC_EXT:':<20}ff:fe\n"
    build = _built(fake_tools, fw, **{"write-flash": {"stdout": HEADER + c6 + STUB + WRITE + verified()}})
    env = _flash(fw, pty_port, build, _expected(pty_port, mac=MAC.upper()))
    assert env["ok"], env["error"]
    assert _checks(env)["board.flash.board_identity"] == "passed" and env["result"]["mac"] == MAC
    assert not any(w["code"].startswith("board_identity") for w in env["warnings"])


def test_expected_board_without_mac_refuses_before_any_tool(fake_tools, fw, hw_on, pty_port, monkeypatch):
    _ports(monkeypatch, pty_port)
    build = _built(fake_tools, fw)
    fake_tools.log.unlink()
    env = _flash(fw, pty_port, build, {"port": pty_port.name, "mac": None})
    assert env["error"]["code"] == "not_confirmed" and fake_tools.calls() == []


# ------------------------------------------------------------------------------------------------ A3

def test_metadata_without_flash_images_is_elf_missing_without_esptool(fake_tools, fw, hw_on, pty_port, monkeypatch):
    _ports(monkeypatch, pty_port)
    data = fake_tools.scenario("board-pio-flash-ok.json")
    data["metadata"]["json"]["{env}"].pop("extra")
    fake_tools.scenario(data)
    build = board.build(fw, "s3")["result"]
    env = _flash(fw, pty_port, build, _expected(pty_port))
    assert env["error"]["code"] == "elf_missing"
    assert env["error"]["message"] == ("pio project metadata lists no bootloader or partition table; "
                                       "Circuit Bench writes only complete image sets")
    assert "board_build.partitions" in env["error"]["hint"]
    assert fake_tools.calls("esptool") == []  # not even image-info
    assert not any(w["code"] == "app_only" for w in env["warnings"])


# ------------------------------------------------------------------------------------------------ callers

@pytest.fixture
def no_hermes(monkeypatch):
    cfg = types.ModuleType("hermes_cli.config")
    cfg.load_config = lambda: {"approvals": {"mode": "manual"}}
    pkg = types.ModuleType("hermes_cli")
    pkg.config = cfg
    monkeypatch.setitem(sys.modules, "hermes_cli", pkg)
    monkeypatch.setitem(sys.modules, "hermes_cli.config", cfg)
    monkeypatch.delenv("HERMES_YOLO_MODE", raising=False)
    monkeypatch.delenv("HERMES_CRON_SESSION", raising=False)


def test_agent_flash_passes_the_detection_and_stores_a_refused_flash(fake_tools, fw, hw_on, pty_port, monkeypatch,
                                                                     no_hermes):
    """tools._flash hands project.board.detected to board.flash; a refusal after esptool started is stored as
    last_flash ok:false with the MAC esptool read."""
    monkeypatch.setenv("CIRCUIT_BENCH_SETTINGS_JSON", json.dumps({"allow_flash": True}))
    _ports(monkeypatch, pty_port)
    build = _built(fake_tools, fw, **{"write-flash": {"stdout": "", "phases": [
        {"stdout": HEADER + WRITE + mac_line(FOREIGN), "sleep": 2}, {"stdout": verified()}]}})
    _new_project("hb-agent")
    upd = project.update("hb-agent", 1, [
        {"op": "set_detected", "port": pty_port.name, "mac": MAC, "chip": "ESP32-S3 (QFN56) (revision v0.2)",
         "usb_id": USB},
        {"op": "set_firmware", "dir": str(fw), "env": "s3"}, {"op": "set_build", **build}], by="ui", trusted=True)
    assert upd["ok"], upd
    host = tools.Host(hook_active=True)
    args = {"action": "flash", "project": "hb-agent", "elf_sha256": build["elf_sha256"]}
    assert hooks.decide(host, "bench_board", args, "t")["action"] == "approve"
    seen = {}
    real_flash = board.flash

    def spy(*a, **kw):
        seen.update(kw)
        return real_flash(*a, **kw)

    monkeypatch.setattr(board, "flash", spy)
    env = json.loads(tools.make_handlers(host)["bench_board"](args, task_id="t"))
    assert seen["expected_board"]["mac"] == MAC and seen["expected_board"]["usb_id"] == USB
    assert env["error"]["code"] == "not_confirmed", env
    assert any(w["code"] == "board_identity" and w["severity"] == "danger" for w in env["warnings"])
    last = project.get("hb-agent")["result"]["project"]["firmware"]["last_flash"]
    assert last["ok"] is False and last["mac"] == FOREIGN and last["port"] == pty_port.name
