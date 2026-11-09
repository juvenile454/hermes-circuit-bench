import json
import sys
import types
from pathlib import Path

import pytest

from circuit_bench.bench_core import runtime, settings, storage
from circuit_bench.bench_core.contracts import BenchError


def test_data_dir_uses_plugin_storage(tmp_path):
    d = storage.data_dir()
    assert d == tmp_path / "hhome" / "plugin-data" / "circuit-bench"
    assert d.is_dir() and (d.stat().st_mode & 0o777) == 0o700


def test_data_dir_env_fallback_outside_hermes(tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, "plugins", None)  # import plugins -> ImportError
    monkeypatch.delitem(sys.modules, "plugins.plugin_storage")
    assert storage.data_dir() == tmp_path / "data"
    monkeypatch.delenv("CIRCUIT_BENCH_DATA_DIR")
    with pytest.raises(BenchError) as e:
        storage.data_dir()
    assert e.value.code == "dependency_missing"


def test_dev_guard_refuses_live_hermes_home(monkeypatch):
    live = storage.real_home() / ".hermes" / "plugin-data" / "circuit-bench"
    with pytest.raises(BenchError):
        storage.check_dev_guard(live)
    storage.check_dev_guard(storage.real_home() / ".hermes" / "cache" / "scratch" / "x")  # allowed
    monkeypatch.setenv("CIRCUIT_BENCH_DEV_GUARD", "0")
    storage.check_dev_guard(live)  # guard off: no error


def test_sub_dir(tmp_path):
    p = storage.sub_dir("projects", "demo")
    assert p.is_dir() and p.parent.name == "projects"


def test_settings_defaults_and_coercion(monkeypatch):
    assert settings.load()["allow_flash"] is False
    monkeypatch.setenv("CIRCUIT_BENCH_SETTINGS_JSON", json.dumps(
        {"allow_flash": "true", "default_baud": "9600", "monitor_max_seconds": 0, "pio_path": " /x/pio ", "bogus": 1}))
    monkeypatch.setenv("CIRCUIT_BENCH_HW", "on")
    s = settings.load()
    assert s["allow_flash"] is True and s["default_baud"] == 9600
    assert s["monitor_max_seconds"] == 120  # out of range -> default
    assert s["pio_path"] == "/x/pio" and "bogus" not in s
    assert settings.hardware_enabled(s) is True


def test_hw_switch_overrides(monkeypatch):
    monkeypatch.setenv("CIRCUIT_BENCH_SETTINGS_JSON", json.dumps({"hardware_access": True}))
    assert settings.load()["hardware_access"] is False  # conftest sets CIRCUIT_BENCH_HW=off
    assert settings.hardware_enabled() is False
    monkeypatch.setenv("CIRCUIT_BENCH_HW", "on")
    monkeypatch.setenv("CIRCUIT_BENCH_SETTINGS_JSON", json.dumps({"hardware_access": False}))
    assert settings.hardware_enabled() is False


def test_settings_from_hermes_config(monkeypatch):
    monkeypatch.delenv("CIRCUIT_BENCH_SETTINGS_JSON")
    cfg = types.ModuleType("hermes_cli.config")
    cfg.load_config = lambda: {"plugins": {"entries": {"circuit-bench": {"settings": {"allow_flash": True}}}}}
    monkeypatch.setitem(sys.modules, "hermes_cli", types.ModuleType("hermes_cli"))
    monkeypatch.setitem(sys.modules, "hermes_cli.config", cfg)
    assert settings.load()["allow_flash"] is True


def _fake_hermes(monkeypatch, plugin_settings):
    cfg = types.ModuleType("hermes_cli.config")
    cfg.load_config = lambda: {"plugins": {"entries": {"circuit-bench": {"settings": plugin_settings}}}}
    monkeypatch.setitem(sys.modules, "hermes_cli", types.ModuleType("hermes_cli"))
    monkeypatch.setitem(sys.modules, "hermes_cli.config", cfg)


def test_settings_json_ignored_inside_hermes_without_dev_guard(monkeypatch):
    """A leftover CIRCUIT_BENCH_SETTINGS_JSON must not replace the user's settings in a real Hermes."""
    _fake_hermes(monkeypatch, {"allow_flash": False, "default_baud": 9600})
    monkeypatch.setenv("CIRCUIT_BENCH_SETTINGS_JSON", json.dumps({"allow_flash": True, "hardware_access": True}))
    monkeypatch.setenv("CIRCUIT_BENCH_DEV_GUARD", "1")  # development: the test switch counts
    assert settings.load()["allow_flash"] is True and settings.env_settings_ignored() is False
    monkeypatch.delenv("CIRCUIT_BENCH_DEV_GUARD")  # product run inside Hermes: ignored, Hermes' config applies
    s = settings.load()
    assert s["allow_flash"] is False and s["default_baud"] == 9600
    assert settings.env_settings_allowed() is False and settings.env_settings_ignored() is True
    monkeypatch.setenv("CIRCUIT_BENCH_DEV_GUARD", "0")
    assert settings.load()["allow_flash"] is False


def test_settings_json_counts_outside_hermes(monkeypatch):
    import builtins
    real_import = builtins.__import__

    def no_hermes(name, *a, **kw):
        if name.split(".")[0] == "hermes_cli":
            raise ImportError("no Hermes here")
        return real_import(name, *a, **kw)

    monkeypatch.delitem(sys.modules, "hermes_cli", raising=False)
    monkeypatch.delitem(sys.modules, "hermes_cli.config", raising=False)
    monkeypatch.setattr(builtins, "__import__", no_hermes)
    monkeypatch.delenv("CIRCUIT_BENCH_DEV_GUARD")
    monkeypatch.setenv("CIRCUIT_BENCH_SETTINGS_JSON", json.dumps({"allow_flash": True}))
    assert settings.load()["allow_flash"] is True and settings.env_settings_ignored() is False


def test_doctor_warns_about_ignored_settings_json(monkeypatch):
    from circuit_bench.bench_core import doctor
    _fake_hermes(monkeypatch, {})
    monkeypatch.delenv("CIRCUIT_BENCH_DEV_GUARD")
    monkeypatch.setenv("CIRCUIT_BENCH_SETTINGS_JSON", json.dumps({"allow_flash": True}))
    env = doctor.run()
    warn = next(w for w in env["warnings"] if w["code"] == "settings_env_ignored")
    assert warn["severity"] == "caution" and "CIRCUIT_BENCH_SETTINGS_JSON" in warn["message"]
    monkeypatch.setenv("CIRCUIT_BENCH_DEV_GUARD", "1")
    assert "settings_env_ignored" not in {w["code"] for w in doctor.run()["warnings"]}


def test_runtime_shared_across_package_copies():
    import importlib.util

    made = []
    a = runtime.get("broker", lambda: made.append(1) or object())
    path = Path(runtime.__file__)
    spec = importlib.util.spec_from_file_location("cb_copy_runtime", path)
    copy = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(copy)
    assert copy is not runtime
    assert copy.get("broker", lambda: made.append(2) or object()) is a
    assert made == [1]
    runtime.reset()
    assert runtime.peek("broker") is None
