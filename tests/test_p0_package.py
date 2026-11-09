"""Package-wide rules: lazy third-party imports, bench_core self-contained, manifest vs. settings."""
import builtins
import importlib
import json
import pkgutil
import re
import sys
from pathlib import Path

import pytest

import circuit_bench
from circuit_bench.bench_core import settings

PKG = Path(circuit_bench.__file__).resolve().parent
LAZY = ("schemdraw", "serial")


def _modules():
    for info in pkgutil.walk_packages([str(PKG)], prefix="circuit_bench."):
        yield info.name


def test_every_module_imports_without_schemdraw_and_pyserial(monkeypatch):
    real_import = builtins.__import__

    def guarded(name, *a, **kw):
        if name.split(".")[0] in LAZY:
            raise ImportError(f"blocked for test: {name}")
        return real_import(name, *a, **kw)

    for name in list(sys.modules):
        if name == "circuit_bench" or name.startswith("circuit_bench."):
            monkeypatch.delitem(sys.modules, name)
    monkeypatch.setattr(builtins, "__import__", guarded)
    for name in _modules():
        importlib.import_module(name)


def test_bench_core_uses_no_parent_imports():
    """bench_core never imports outside itself. Its subpackages (calcs/) may go up one
    level only (``from .. import calckit`` stays inside bench_core)."""
    core = PKG / "bench_core"
    bad = []
    for path in core.rglob("*.py"):
        depth = len(path.relative_to(core).parts) - 1  # 0 = bench_core itself, 1 = bench_core/calcs
        up = re.compile(r"\s*from\s+\.{" + str(depth + 2) + ",}")  # more dots than the way back to bench_core
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if up.match(line) or re.match(r"\s*(from|import)\s+circuit_bench\b", line):
                bad.append(f"{path.relative_to(core)}:{n}")
    assert bad == []


def test_manifest_config_schema_matches_settings_defaults():
    yaml = pytest.importorskip("yaml")
    manifest = yaml.safe_load((PKG / "plugin.yaml").read_text(encoding="utf-8"))
    schema = manifest["config_schema"]
    assert set(schema) == set(settings.DEFAULTS)
    for key, spec in schema.items():
        assert spec["default"] == settings.DEFAULTS[key], key
        assert {"bool": bool, "int": int, "str": str}[spec["type"]] is type(settings.DEFAULTS[key]), key
    assert manifest["name"] == circuit_bench.PLUGIN_ID
    assert manifest["requires_hermes"] == ">=0.22.5"


def test_desktop_plugin_is_generated_and_named():
    js = (PKG / "desktop" / "plugin.js").read_text(encoding="utf-8")
    assert js.startswith("// GENERATED from desktop-src/")
    assert "const PLUGIN_ID = 'circuit-bench'" in js and "id: PLUGIN_ID," in js
    assert "const CB_FIXTURES = null" in js  # product build never ships fixtures


def test_no_binaries_in_package():
    bad = []
    for path in PKG.rglob("*"):
        if path.is_file() and "__pycache__" not in path.parts:
            data = path.read_bytes()[:4096]
            if b"\x00" in data:
                bad.append(str(path.relative_to(PKG)))
    assert bad == []


def test_data_json_files_parse():
    for path in (PKG / "data").rglob("*.json"):
        json.loads(path.read_text(encoding="utf-8"))
