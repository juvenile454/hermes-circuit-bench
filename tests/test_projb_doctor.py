"""doctor.run (tools, serial group, ports, dependencies, data folder, hardware switch)."""
import builtins
import json
import os
import sys
import types

import pytest

from circuit_bench.bench_core import contracts, doctor


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setitem(sys.modules, "circuit_bench.bench_core.sim", None)
    cfg = types.ModuleType("hermes_cli.config")
    cfg.load_config = dict
    pkg = types.ModuleType("hermes_cli")
    pkg.config = cfg
    monkeypatch.setitem(sys.modules, "hermes_cli", pkg)
    monkeypatch.setitem(sys.modules, "hermes_cli.config", cfg)
    monkeypatch.delenv("HERMES_YOLO_MODE", raising=False)


def _groups(monkeypatch, name, member):
    grp = types.ModuleType("grp")

    def getgrnam(n):
        if n != name:
            raise KeyError(n)
        return types.SimpleNamespace(gr_gid=4242)

    grp.getgrnam = getgrnam
    monkeypatch.setitem(sys.modules, "grp", grp)
    monkeypatch.setattr(os, "getgroups", lambda: [4242] if member else [1])


def _status(env):
    return {c["id"]: c["status"] for c in env["checks"]}


def test_doctor_with_fake_tools(monkeypatch):
    _groups(monkeypatch, "dialout", True)
    env = doctor.run()
    assert contracts.validate_envelope(env) == [] and env["action"] == "doctor.run"
    st = _status(env)
    assert st["doctor.pio"] == st["doctor.esptool"] == st["doctor.addr2line"] == "passed"  # tests/fakes/bin
    assert st["doctor.serial_group"] == "passed" and st["doctor.data_dir"] == "passed"
    res = env["result"]
    assert res["tools"]["addr2line"]["esp32s3"]["path"].endswith("xtensa-esp32s3-elf-addr2line")
    assert res["hardware"] == {"enabled": False, "env": "off", "hardware_access": False}
    assert all(p["simulated"] for p in res["ports"]["ports"])  # hardware off: at most the sim:// board
    assert res["settings"]["allow_flash"] is False and res["approvals_bypassed"] is False
    assert any(w["code"] == "hardware_off" for w in env["warnings"])
    assert len(json.dumps(env).encode()) <= contracts.MAX_RESULT_BYTES


def test_doctor_reports_problems(monkeypatch, tmp_path):
    _groups(monkeypatch, "uucp", False)
    monkeypatch.setenv("PATH", str(tmp_path))  # no tools at all
    monkeypatch.setenv("HOME", str(tmp_path))
    real_import = builtins.__import__

    def guarded(name, *a, **kw):
        if name.split(".")[0] == "schemdraw":
            raise ImportError("blocked for test")
        return real_import(name, *a, **kw)

    monkeypatch.delitem(sys.modules, "schemdraw", raising=False)
    monkeypatch.setattr(builtins, "__import__", guarded)
    monkeypatch.setenv("HERMES_YOLO_MODE", "1")
    env = doctor.run()
    st = _status(env)
    assert st["doctor.pio"] == st["doctor.esptool"] == st["doctor.addr2line"] == "failed"
    assert st["doctor.serial_group"] == "failed" and st["doctor.dependencies"] == "failed"
    codes = {w["code"] for w in env["warnings"]}
    assert {"pio_missing", "esptool_missing", "addr2line_missing", "serial_group", "dependency_missing",
            "approvals_bypassed"} <= codes
    assert "usermod -aG uucp" in next(w["message"] for w in env["warnings"] if w["code"] == "serial_group")
    assert "failed:" in env["summary"]


def test_doctor_without_serial_groups(monkeypatch):
    _groups(monkeypatch, "wheel", True)
    assert _status(doctor.run())["doctor.serial_group"] == "skipped"


def test_doctor_without_data_folder(monkeypatch):
    monkeypatch.delenv("CIRCUIT_BENCH_DATA_DIR")
    monkeypatch.setitem(sys.modules, "plugins", None)  # not inside Hermes
    env = doctor.run()
    assert _status(env)["doctor.data_dir"] == "failed"
    assert any(w["code"] == "data_dir" and w["severity"] == "danger" for w in env["warnings"])


def test_doctor_never_raises(monkeypatch):
    monkeypatch.setattr(doctor, "_run", lambda: 1 / 0)
    env = doctor.run()
    assert env["error"]["code"] == "tool_failed" and contracts.validate_envelope(env) == []


def test_doctor_runs_no_board_command(monkeypatch):
    from circuit_bench.bench_core import clitools
    seen = []
    real = clitools.run

    def spy(argv, **kw):
        seen.append([os.path.basename(str(argv[0])), *map(str, argv[1:])])
        return real(argv, **kw)

    monkeypatch.setattr(clitools, "run", spy)
    doctor.run()
    assert seen and all(cmd[1:] in (["--version"], ["version"]) for cmd in seen), seen
