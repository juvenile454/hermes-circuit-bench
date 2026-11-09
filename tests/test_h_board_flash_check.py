"""GET /board/flash/check?project=<id>&port=<p> answers whether a flash would be
refused, without a port, a tool or a pio query (guard.check_flash(via="route", precheck=True))."""
import json

import pytest
import test_api_support as sup
from board_fixtures import fake_tools  # noqa: F401 - fixture
from test_api_support import api  # noqa: F401 - fixture

from circuit_bench.bench_core import contracts, guard

REAL = "/dev/ttyACM-cb-fake0"
MAC = "02:00:00:00:00:01"
SHA = "b" * 64


@pytest.fixture
def quiet(api, fake_tools, monkeypatch):  # noqa: F811
    """No port lookup, no CLI, no pio metadata, no serial port: any of them fails the test. (The port list itself
    may be polled by the route's port watcher while hardware access is on; that is not the check route.)"""
    sup.mock_ports(monkeypatch, [(REAL, 0x303A, 0x1001, "USB JTAG/serial debug unit", "TEST0001")])
    board = sup.route_module("board")
    for name in ("metadata", "project_config", "image_info", "_port_lookup", "_port_info", "detect", "flash", "build"):
        monkeypatch.setattr(board, name, lambda *a, _n=name, **k: pytest.fail(f"board.{_n} ran"))
    monkeypatch.setattr(sup.route_module("clitools"), "run", lambda *a, **k: pytest.fail("clitools.run ran"))
    sp = sup.route_module("serialport")
    monkeypatch.setattr(sp, "open_port", lambda *a, **k: pytest.fail("serial port opened"))
    real = sp._realpath
    monkeypatch.setattr(sp, "_realpath", lambda p: p if p == REAL else real(p))
    yield
    assert fake_tools.calls() == []


def _settings(monkeypatch, **values):
    monkeypatch.setenv("CIRCUIT_BENCH_SETTINGS_JSON", json.dumps(values))


def _check(api, **params):  # noqa: F811
    resp = api.get("/board/flash/check", params=params)
    body = resp.json()
    assert contracts.validate_envelope(body) == [], body
    return resp.status_code, body


def _ready_project(api, pid="bench-chk", port=REAL, chip="ESP32-S3 (QFN56) (revision v0.2)", detect=True,  # noqa: F811
                   build=True):
    api.create(pid)
    fw = sup.write_firmware(api_tmp(api) / pid)
    api.apply(pid, {"op": "set_firmware", "dir": str(fw), "env": "s3"})
    ops = []
    if detect:
        ops.append({"op": "set_detected", "port": port, "mac": MAC, "chip": chip,
                    "usb_id": {"vid": "303a", "pid": "1001", "serial": "TEST0001"}})
    if build:
        ops.append({"op": "set_build", "ok": True, "elf_sha256": SHA, "elf": ".pio/build/s3/firmware.elf",
                    "chip": "esp32s3"})
    if ops:
        api.record(pid, *ops)
    return pid


def api_tmp(api):  # noqa: F811
    from circuit_bench.bench_core import storage
    d = storage.data_dir() / "fw-check"
    d.mkdir(exist_ok=True)
    return d


def _refusal(body, code):
    assert body["ok"] is True and body["action"] == "board.flash_check", body
    r = body["result"]
    assert r["ready"] is False and r["refusal"]["code"] == code, r
    assert set(r["refusal"]) == {"code", "message", "hint"}
    return r["refusal"]


def test_flash_disabled(api, quiet, monkeypatch):  # noqa: F811
    _settings(monkeypatch, hardware_access=True, allow_flash=False)
    monkeypatch.setenv("CIRCUIT_BENCH_HW", "on")
    pid = _ready_project(api)
    status, body = _check(api, project=pid, port=REAL)
    assert status == 200
    _refusal(body, "flash_disabled")


def test_hardware_off_is_sim_only(api, quiet, monkeypatch):  # noqa: F811
    _settings(monkeypatch, allow_flash=True)
    pid = _ready_project(api)
    _refusal(_check(api, project=pid, port=REAL)[1], "sim_only")


def test_chip_mismatch(api, quiet, monkeypatch):  # noqa: F811
    _settings(monkeypatch, hardware_access=True, allow_flash=True)
    monkeypatch.setenv("CIRCUIT_BENCH_HW", "on")
    pid = _ready_project(api, chip="ESP32-C3 (QFN32) (revision v0.4)")
    _refusal(_check(api, project=pid, port=REAL)[1], "chip_mismatch")


@pytest.mark.parametrize("detect, build", [(False, False), (True, False), (False, True)])
def test_not_confirmed_without_detect_or_build(api, quiet, monkeypatch, detect, build):  # noqa: F811
    _settings(monkeypatch, hardware_access=True, allow_flash=True)
    monkeypatch.setenv("CIRCUIT_BENCH_HW", "on")
    pid = _ready_project(api, detect=detect, build=build)
    params = {"project": pid, "port": REAL} if not detect else {"project": pid}
    ref = _refusal(_check(api, **params)[1], "not_confirmed")
    assert "detect" in (ref["hint"] or "")


def test_ready_for_an_approved_real_board_without_confirm(api, quiet, monkeypatch):  # noqa: F811
    _settings(monkeypatch, hardware_access=True, allow_flash=True)
    monkeypatch.setenv("CIRCUIT_BENCH_HW", "on")
    pid = _ready_project(api)
    for params in ({"project": pid, "port": REAL}, {"project": pid}):  # the port defaults to the detected one
        status, body = _check(api, **params)
        assert status == 200 and body["ok"] is True
        assert body["result"] == {"ready": True, "refusal": None}
        assert body["simulated"] is False
    # a port other than the detected one is not ready (the flash would refuse it)
    api.record(pid, {"op": "set_detected", "port": "/dev/ttyACM-cb-fake1", "mac": MAC, "chip": "ESP32-S3"})
    _refusal(_check(api, project=pid, port=REAL)[1], "not_confirmed")


def test_ready_on_a_simulated_board_and_sim_without_build(api, quiet, monkeypatch):  # noqa: F811
    pid = _ready_project(api, port="sim://test-s3")
    status, body = _check(api, project=pid)
    assert status == 200 and body["result"] == {"ready": True, "refusal": None} and body["simulated"] is True
    pid2 = _ready_project(api, pid="bench-chk2", port="sim://test-s3", build=False)
    _refusal(_check(api, project=pid2)[1], "not_confirmed")
    assert api.provider.flashed == []


def test_bad_requests_are_errors(api, quiet):  # noqa: F811
    status, body = _check(api)
    assert status == 400 and body["error"]["code"] == "invalid_args"
    status, body = _check(api, project="nope")
    assert status == 404 and body["error"]["code"] == "project_not_found"
    pid = _ready_project(api, detect=False, build=False)
    status, body = _check(api, project=pid, port="/etc/passwd")
    assert status == 400 and body["error"]["code"] == "invalid_args"


def test_precheck_skips_only_the_confirm_comparison(monkeypatch):
    monkeypatch.setenv("CIRCUIT_BENCH_HW", "on")
    proj = {"id": "p", "board": {"chip": "esp32s3", "detected": {"port": REAL, "mac": MAC, "chip": "ESP32-S3"}},
            "firmware": {"last_build": {"ok": True, "elf_sha256": SHA}}}
    monkeypatch.setattr("circuit_bench.bench_core.serialport._realpath", lambda p: p)
    cfg = {"hardware_access": True, "allow_flash": True}
    assert guard.check_flash(via="route", settings=cfg, project=proj, port=REAL, cron=False)["error"]["code"] == \
        "not_confirmed"
    assert guard.check_flash(via="route", settings=cfg, project=proj, port=REAL, cron=False, precheck=True) is None
    proj["firmware"]["last_build"] = None
    assert guard.check_flash(via="route", settings=cfg, project=proj, port=REAL, cron=False,
                             precheck=True)["error"]["code"] == "not_confirmed"
