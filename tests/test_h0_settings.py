"""Unknown setting values fall back to the safe value, and the doctor names them."""
import json

import pytest

from circuit_bench.bench_core import doctor, settings

TRUE = [True, "true", "TRUE", " on ", "yes", "1", 1]
FALSE = [False, "false", "Off", "no", "0", 0]
JUNK = ["maybe", "enabled", "", 2, -1, 0.5, [], {}, "truee"]


def _load(monkeypatch, values):
    monkeypatch.setenv("CIRCUIT_BENCH_SETTINGS_JSON", json.dumps(values))
    monkeypatch.setenv("CIRCUIT_BENCH_HW", "on")
    return settings.load()


@pytest.mark.parametrize("key", ["allow_flash", "approve_serial", "hardware_access"])
@pytest.mark.parametrize("value", TRUE)
def test_true_words(monkeypatch, key, value):
    assert _load(monkeypatch, {key: value})[key] is True
    assert settings.invalid_keys() == []


@pytest.mark.parametrize("key", ["allow_flash", "approve_serial", "hardware_access"])
@pytest.mark.parametrize("value", FALSE)
def test_false_words(monkeypatch, key, value):
    assert _load(monkeypatch, {key: value})[key] is False
    assert settings.invalid_keys() == []


@pytest.mark.parametrize("value", JUNK)
def test_junk_falls_back_to_the_safe_value(monkeypatch, value):
    s = _load(monkeypatch, {"hardware_access": value, "allow_flash": value, "approve_serial": value})
    assert s["hardware_access"] is False  # default is True: an unreadable value must not open the hardware
    assert s["allow_flash"] is False
    assert s["approve_serial"] is True
    assert settings.hardware_enabled(s) is False
    assert settings.invalid_keys() == ["allow_flash", "approve_serial", "hardware_access"]


def test_null_counts_as_not_set(monkeypatch):
    s = _load(monkeypatch, {"hardware_access": None, "allow_flash": None})
    assert s["hardware_access"] is True and s["allow_flash"] is False and settings.invalid_keys() == []


def test_invalid_numbers_are_listed(monkeypatch):
    s = _load(monkeypatch, {"default_baud": "fast", "monitor_max_seconds": 0, "pio_path": 3})
    assert s["default_baud"] == 115200 and s["monitor_max_seconds"] == 120 and s["pio_path"] == ""
    assert settings.invalid_keys() == ["default_baud", "monitor_max_seconds", "pio_path"]


def test_hw_switch_still_wins(monkeypatch):
    monkeypatch.setenv("CIRCUIT_BENCH_SETTINGS_JSON", json.dumps({"hardware_access": "yes"}))
    monkeypatch.setenv("CIRCUIT_BENCH_HW", "off")
    assert settings.load()["hardware_access"] is False and settings.hardware_enabled() is False


def _doctor_settings(env):
    return next(c for c in env["checks"] if c["id"] == "doctor.settings")


def test_doctor_names_invalid_settings(monkeypatch):
    _load(monkeypatch, {"hardware_access": "maybe"})
    env = doctor.run()
    assert env["ok"] is True
    chk = _doctor_settings(env)
    assert chk["status"] == "failed" and "hardware_access" in chk["detail"]
    warn = next(w for w in env["warnings"] if w["code"] == "settings_invalid")
    assert warn["severity"] == "caution" and "hardware_access" in warn["message"]
    assert env["result"]["hardware"]["hardware_access"] is False


def test_doctor_settings_passed(monkeypatch):
    _load(monkeypatch, {"hardware_access": True})
    env = doctor.run()
    assert _doctor_settings(env)["status"] == "passed"
    assert "settings_invalid" not in {w["code"] for w in env["warnings"]}
