"""guard.check_flash / check_serial decision table, approvals bypass, board.flash integration.

The guard never touches hardware: ports here are only strings. Hardware-on cases set CIRCUIT_BENCH_HW=on for the
decision logic; the conftest audit hook still refuses any real serial device or tool.
"""
from __future__ import annotations

import functools
import os
import sys
import types
from pathlib import Path

import pytest

from circuit_bench.bench_core import contracts, guard

REAL = "/dev/ttyACM0"
SIM = "sim://esp32s3-n16r8"
MAC = "aa:bb:cc:dd:ee:ff"
SHA = "3f9a5c0d21e8b47a6c13f0e2d9b8a7c6e5f4d3c2b1a09f8e7d6c5b4a39281706"
ON = {"allow_flash": True, "approve_serial": True, "hardware_access": True}


def _project(port=REAL, mac=MAC, sha=SHA, build_ok=True, detected=True):
    det = {"port": port, "mac": mac, "chip": "ESP32-S3", "description": None, "features": [], "flash_size": "16MB",
           "variant_suggestion": "n16r8", "at": "2026-11-06T21:41:07Z", "simulated": port.startswith("sim://")}
    return {"id": "laser-trigger", "rev": 3,
            "board": {"chip": "esp32s3", "module": "wroom-1", "variant": "n16r8", "devkit": None,
                      "detected": det if detected else None},
            "firmware": {"dir": "/srv/fw", "env": "s3", "last_flash": None,
                         "last_build": None if sha is None else {"ok": build_ok, "at": "2026-11-06T21:38:52Z",
                                                                 "ram_pct": 5.6, "flash_pct": 7.9, "elf": "x.elf",
                                                                 "elf_sha256": sha}}}


CONFIRM = {"port": REAL, "mac": MAC, "elf_sha256": SHA}


@pytest.fixture
def hw_on(monkeypatch):
    monkeypatch.setenv("CIRCUIT_BENCH_HW", "on")


@pytest.fixture
def hermes_config(monkeypatch):
    """Fake public hermes_cli.config; set .value to the dict load_config returns (or an exception to raise)."""
    state = types.SimpleNamespace(value={}, calls=0)
    mod = types.ModuleType("hermes_cli.config")

    def load_config():
        state.calls += 1
        if isinstance(state.value, BaseException):
            raise state.value
        return state.value

    mod.load_config = load_config
    pkg = types.ModuleType("hermes_cli")
    pkg.config = mod
    monkeypatch.setitem(sys.modules, "hermes_cli", pkg)
    monkeypatch.setitem(sys.modules, "hermes_cli.config", mod)
    monkeypatch.delenv("HERMES_YOLO_MODE", raising=False)
    return state


def _flash(**kw):
    args = {"via": "tool", "settings": ON, "project": _project(), "port": REAL, "confirm": None, "cron": False} | kw
    return guard.check_flash(**args)


def _serial(**kw):
    args = {"via": "tool", "settings": ON, "port": REAL, "cron": False} | kw
    return guard.check_serial(**args)


def _refused(res, code, action="board.flash"):
    assert res is not None, "expected a refusal"
    assert res["ok"] is False and res["action"] == action and res["error"]["code"] == code, res["error"]
    assert contracts.validate_envelope(res) == []
    return res


# --------------------------------------------------------------------------------------------- is_sim

@pytest.mark.parametrize("port, sim", [(SIM, True), (" sim://x", True), ("sim://", True), (REAL, False),
                                       ("COM3", False), ("SIM://x", False), ("socket://sim", False), (None, False),
                                       (3, False), ("", False)])
def test_is_sim(port, sim):
    assert guard.is_sim(port) is sim


# --------------------------------------------------------------------------------------------- check_flash table

def test_flash_ok_tool_and_route(hw_on, hermes_config):
    assert _flash() is None
    assert _flash(via="route", confirm=CONFIRM) is None
    assert _flash(via="route", confirm={"port": REAL, "mac": MAC.upper(), "elf_sha256": SHA.upper()}) is None
    assert _flash(project={"ok": True, "action": "project.get", "result": {"project": _project(), "rev": 3}}) is None


def test_cron_is_blocked_first(hw_on, hermes_config):
    for kw in ({}, {"port": SIM}, {"settings": {"allow_flash": False}}, {"via": "route", "confirm": CONFIRM},
               {"cron": None}, {"cron": 1}, {"cron": "no"}):
        res = _refused(_flash(**({"cron": True} | kw)), "unattended_blocked")
        assert "cron" in res["error"]["message"]


def test_sim_port_needs_no_approval(monkeypatch, hermes_config):
    # hardware off (conftest), flash off, no detection, no build, bypass active: a sim port is still fine
    monkeypatch.setenv("HERMES_YOLO_MODE", "1")
    assert _flash(port=SIM, settings={"allow_flash": False, "hardware_access": False}, project=None) is None
    assert _flash(port=SIM, via="route", confirm=None, project=None, settings=None) is None


def test_hardware_off_is_sim_only(monkeypatch, hermes_config):
    res = _refused(_flash(), "sim_only")  # conftest: CIRCUIT_BENCH_HW=off
    assert "CIRCUIT_BENCH_HW=off" in res["error"]["hint"]  # the variable is named only when it is set
    monkeypatch.setenv("CIRCUIT_BENCH_HW", "on")
    res = _refused(_flash(settings=ON | {"hardware_access": False}), "sim_only")
    assert "CIRCUIT_BENCH_HW" not in res["error"]["hint"] and "'Access real hardware'" in res["error"]["hint"]
    _refused(_flash(via="route", confirm=CONFIRM, settings=ON | {"hardware_access": False}), "sim_only")


def test_bypass_blocks_agent_flashes_on_real_ports(hw_on, hermes_config, monkeypatch):
    hermes_config.value = {"approvals": {"mode": "off"}}
    res = _refused(_flash(), "unattended_blocked")
    assert res["error"]["message"] == guard.BYPASS_FLASH_MSG and "cannot flash real boards" in res["error"]["message"]
    assert res["error"]["hint"] == "flash from the Bench UI (it always asks) or turn approvals on"
    assert _flash(via="route", confirm=CONFIRM) is None  # the Bench UI asks itself
    assert _flash(port=SIM) is None
    # bypass comes before allow_flash
    _refused(_flash(settings=ON | {"allow_flash": False}), "unattended_blocked")
    hermes_config.value = {"approvals": {"mode": "manual"}}
    monkeypatch.setenv("HERMES_YOLO_MODE", "true")
    _refused(_flash(), "unattended_blocked")


@pytest.mark.parametrize("value", [False, "false", "no", None, "1", 1, "true"])
def test_allow_flash_must_be_true(hw_on, hermes_config, value):
    res = _refused(_flash(settings=ON | {"allow_flash": value}), "flash_disabled")
    assert "allow_flash" in res["error"]["message"]
    _refused(_flash(via="route", confirm=CONFIRM, settings=ON | {"allow_flash": value}), "flash_disabled")


def test_allow_flash_missing_from_settings(hw_on, hermes_config):
    _refused(_flash(settings={"hardware_access": True}), "flash_disabled")


def test_settings_none_loads_the_plugin_settings(hw_on, hermes_config, monkeypatch):
    _refused(_flash(settings=None), "flash_disabled")  # defaults: allow_flash false
    monkeypatch.setenv("CIRCUIT_BENCH_SETTINGS_JSON", '{"allow_flash": true}')
    assert _flash(settings=None) is None
    _refused(_flash(settings=["allow_flash"]), "invalid_args")


@pytest.mark.parametrize("proj, needle", [
    (None, "no bench project"),
    ("laser-trigger", "no bench project"),
    ({"ok": False, "action": "project.get", "result": None}, "no bench project"),
    (_project(detected=False), "not detected"),
    ({"board": {}}, "not detected"),
    (_project(port="/dev/ttyACM1"), "not on /dev/ttyACM0"),
    (_project(port=SIM), "not on /dev/ttyACM0"),
    (_project(mac=None), "no MAC"),
    (_project(mac=""), "no MAC"),
    (_project(sha=None), "no successful build"),
    (_project(sha=""), "no successful build"),
    (_project(build_ok=False), "no successful build"),
])
def test_missing_or_other_detection_or_build(hw_on, hermes_config, proj, needle):
    for via, confirm in (("tool", None), ("route", CONFIRM)):
        res = _refused(_flash(project=proj, via=via, confirm=confirm), "not_confirmed")
        assert needle in res["error"]["message"]
        assert res["error"]["hint"] == "run detect and build first"


@pytest.mark.parametrize("confirm", [
    None, {}, "yes", {"port": REAL, "mac": MAC}, {"port": "/dev/ttyACM1", "mac": MAC, "elf_sha256": SHA},
    {"port": REAL, "mac": "aa:bb:cc:dd:ee:00", "elf_sha256": SHA}, {"port": REAL, "mac": MAC, "elf_sha256": "0" * 64},
    {"port": REAL, "mac": MAC, "elf_sha256": None},
])
def test_route_needs_the_exact_confirmation(hw_on, hermes_config, confirm):
    _refused(_flash(via="route", confirm=confirm), "not_confirmed")


def test_tool_ignores_confirm(hw_on, hermes_config):
    assert _flash(confirm={"port": "other"}) is None


@pytest.mark.parametrize("kw, code", [({"via": "ui"}, "invalid_args"), ({"via": None}, "invalid_args"),
                                      ({"port": ""}, "invalid_args"), ({"port": None}, "invalid_args")])
def test_bad_arguments_refuse(hw_on, hermes_config, kw, code):
    _refused(_flash(**kw), code)


def test_unexpected_failure_refuses(hw_on, hermes_config, monkeypatch):
    def boom(*a, **kw):
        raise RuntimeError("x")

    monkeypatch.setattr(guard._settings, "hardware_enabled", boom)
    res = _refused(_flash(), "not_confirmed")
    assert "RuntimeError" in res["error"]["message"]
    _refused(_serial(), "not_confirmed", "serial.open")


def test_decision_order(hw_on, hermes_config):
    """cron -> sim -> hardware off -> bypass (tool) -> allow_flash -> detection/build/confirm."""
    hermes_config.value = {"approvals": {"mode": "off"}}
    worst = {"settings": {"allow_flash": False, "hardware_access": False}, "project": None}
    assert _flash(cron=True, port=SIM, **worst)["error"]["code"] == "unattended_blocked"
    assert _flash(port=SIM, **worst) is None
    assert _flash(**worst)["error"]["code"] == "sim_only"
    assert _flash(settings={"allow_flash": False}, project=None)["error"]["code"] == "unattended_blocked"
    hermes_config.value = {}
    assert _flash(settings={"allow_flash": False}, project=None)["error"]["code"] == "flash_disabled"
    assert _flash(project=None)["error"]["code"] == "not_confirmed"


# --------------------------------------------------------------------------------------------- check_serial table

def test_serial_table(monkeypatch, hermes_config):
    act = "serial.open"
    _refused(_serial(cron=True), "unattended_blocked", act)
    _refused(_serial(cron=True, port=SIM), "unattended_blocked", act)
    assert _serial(port=SIM, settings={"hardware_access": False}) is None
    _refused(_serial(), "sim_only", act)  # CIRCUIT_BENCH_HW=off from conftest
    monkeypatch.setenv("CIRCUIT_BENCH_HW", "on")
    _refused(_serial(settings={"hardware_access": False}), "sim_only", act)
    assert _serial() is None
    assert _serial(via="route") is None
    assert _serial(settings={"allow_flash": False, "approve_serial": False}) is None  # no build or flash relation
    hermes_config.value = {"approvals": {"mode": "OFF "}}
    res = _refused(_serial(), "unattended_blocked", act)
    assert res["error"]["message"] == guard.BYPASS_SERIAL_MSG and "cannot open real serial ports" in res["error"]["message"]
    _refused(_serial(settings=ON | {"approve_serial": "maybe"}), "unattended_blocked", act)  # unclear counts as on
    assert _serial(settings=ON | {"approve_serial": False}) is None  # without the prompt there is nothing to bypass
    assert _serial(via="route") is None
    assert _serial(port=SIM) is None
    _refused(_serial(via="hook"), "invalid_args", act)


# --------------------------------------------------------------------------------------------- approvals_bypassed

@pytest.mark.parametrize("yolo, bypass", [("1", True), ("true", True), ("YES", True), (" on ", True), ("0", False),
                                          ("", False), ("off", False), ("false", False)])
def test_yolo_env(monkeypatch, hermes_config, yolo, bypass):
    monkeypatch.setenv("HERMES_YOLO_MODE", yolo)
    assert guard.approvals_bypassed() is bypass


@pytest.mark.parametrize("cfg, bypass", [
    ({}, False), ({"approvals": None}, False), ({"approvals": {}}, False), ({"approvals": {"mode": "manual"}}, False),
    ({"approvals": {"mode": "smart"}}, False), ({"approvals": {"mode": "off"}}, True),
    ({"approvals": {"mode": " Off\n"}}, True), ({"approvals": {"mode": False}}, True),  # YAML 1.1: bare off
    ({"approvals": {"mode": True}}, False), ({"approvals": {"mode": None}}, False),
    ({"approvals": "off"}, True), (["approvals"], True), (None, True),  # unreadable: fail closed
])
def test_approval_mode_from_hermes_config(hermes_config, cfg, bypass):
    hermes_config.value = cfg
    assert guard.approvals_bypassed() is bypass
    assert hermes_config.calls == 1


@pytest.mark.parametrize("key", ["single_query_mode", "unattended_mode"])
@pytest.mark.parametrize("value, bypass", [
    ("approve", True), ("APPROVE ", True), ("allow", True), ("yes", True), ("off", True),  # Hermes' approve words
    (True, False), (False, False),  # YAML bools: Hermes reads str(True) = "true" -> deny
    ("deny", False), ("manual", False), ("", False), (None, False), (0, False),
])
def test_auto_approve_modes_count_as_bypass(hermes_config, key, value, bypass):
    """-q runs (single_query_mode) and webhooks/API sessions (unattended_mode) approve plugin approvals
    without a human when set to an approve-like value; a plugin cannot tell the session, so it blocks always."""
    hermes_config.value = {"approvals": {"mode": "manual", key: value}}
    assert guard.approvals_bypassed() is bypass


def test_auto_approve_mode_blocks_agent_flash_not_the_route(hw_on, hermes_config):
    hermes_config.value = {"approvals": {"mode": "manual", "single_query_mode": "approve"}}
    _refused(_flash(), "unattended_blocked")
    assert _flash(via="route", confirm=CONFIRM) is None  # the Bench UI asks in its own dialog
    hermes_config.value = {"approvals": {"unattended_mode": "allow"}}
    _refused(_flash(), "unattended_blocked")
    hermes_config.value = {"approvals": {"single_query_mode": "deny", "unattended_mode": "deny"}}
    assert _flash() is None


def test_config_errors_fail_closed(hermes_config):
    hermes_config.value = RuntimeError("broken yaml")
    assert guard.approvals_bypassed() is True


def test_no_hermes_means_no_bypass(monkeypatch):
    monkeypatch.delenv("HERMES_YOLO_MODE", raising=False)
    monkeypatch.setitem(sys.modules, "hermes_cli.config", None)  # import raises ImportError
    assert guard.approvals_bypassed() is False
    monkeypatch.setenv("HERMES_YOLO_MODE", "1")
    assert guard.approvals_bypassed() is True


def test_given_config_is_not_reloaded(hermes_config):
    assert guard.approvals_bypassed({"approvals": {"mode": "off"}}) is True
    assert guard.approvals_bypassed({"approvals": {"mode": "manual"}}) is False
    assert hermes_config.calls == 0


def test_only_public_hermes_imports():
    src = guard.__file__
    text = Path(src).read_text(encoding="utf-8")
    assert "tools.approval" not in text and "tui_gateway" not in text
    assert "from hermes_cli.config import load_config" in text


@pytest.mark.hermes
def test_real_hermes_config_in_a_temporary_home(monkeypatch):
    """Real Hermes checkout (marker hermes): the public load_config path, HERMES_HOME from the conftest tmp dir."""
    pytest.importorskip("hermes_cli.config")
    monkeypatch.delenv("HERMES_YOLO_MODE", raising=False)
    home = Path(os.environ["HERMES_HOME"])
    assert "/.hermes/" not in str(home) or "/cache/scratch/" in str(home)
    assert guard.approvals_bypassed() is False  # default approvals.mode
    (home / "config.yaml").write_text("approvals:\n  mode: off\n", encoding="utf-8")  # YAML 1.1: false
    assert guard.approvals_bypassed() is True
    (home / "config.yaml").write_text('approvals:\n  mode: "manual"\n', encoding="utf-8")
    assert guard.approvals_bypassed() is False
    (home / "config.yaml").write_text('approvals:\n  mode: "off"\n', encoding="utf-8")
    assert guard.approvals_bypassed() is True


# --------------------------------------------------------------------------------------------- board.flash integration

def test_works_as_zero_argument_guard_for_board_flash(hermes_config, monkeypatch, tmp_path):
    from circuit_bench.bench_core import board

    calls = []

    def counting(**kw):
        calls.append(kw)
        return guard.check_flash(**kw)

    # real port, hardware on: the guard refuses (allow_flash false) before any tool or port is touched
    monkeypatch.setenv("CIRCUIT_BENCH_HW", "on")
    pdir = tmp_path / "fw"
    pdir.mkdir()
    (pdir / "platformio.ini").write_text("[env:s3]\nplatform = espressif32\n", encoding="utf-8")
    check = functools.partial(counting, via="tool", settings={"allow_flash": False}, project=_project(), port=REAL,
                              confirm=None, cron=False)
    res = board.flash(pdir, "s3", REAL, expected_elf_sha256=SHA, guard=check)
    assert len(calls) == 1
    assert res["ok"] is False and res["action"] == "board.flash" and res["error"]["code"] == "flash_disabled"
    res = board.flash(pdir, "s3", REAL, expected_elf_sha256=SHA,
                      guard=functools.partial(guard.check_flash, via="tool", settings=ON, project=_project(), port=REAL,
                                              cron=True))
    assert res["error"]["code"] == "unattended_blocked"


def test_check_serial_reports_the_callers_action(monkeypatch):
    monkeypatch.setenv("CIRCUIT_BENCH_HW", "on")
    res = guard.check_serial(via="tool", settings={"hardware_access": True}, port="/dev/ttyACM-cb-fake0", cron=True,
                             action="serial.monitor")
    assert res is not None and res["action"] == "serial.monitor" and res["error"]["code"] == "unattended_blocked"
