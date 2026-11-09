"""Test kit of the module engine tests (project builders, finding helpers); excerpt parsing lives in
tests/excerpts.py.

API:
- ``project(chip="esp32s3", assignments=(), parts=(), options=None, devkit=None)`` -> kwargs for modcheck.run
- ``mod(ref, module, conn=None, address=None, facts=None, variant=None, qty=None)`` -> a parts[] entry
- ``run(catalog=None, electrical=None, **project)`` -> modcheck.ModReport (catalog/electrical None = the runtime
  singletons; pass ``mod_fixtures.catalog()`` / ``mod_fixtures.ESP`` for synthetic tests; ``only=(rule ids)``)
- ``codes(report)`` -> set of warning codes; ``by_rule(report, rule_id)`` -> list of warnings/checks
Extras:
- ``i2c(sda=8, scl=9, net="SDA0", scl_net=None)`` -> the two assignments of an I²C bus (nets SDA0/SCL0)
- ``assign(mode, pin, net=None, role=None)`` -> one assignment
- ``findings(report, rule_id=None, status=None)`` -> modcheck.Finding objects (everything, also passed)
- ``check_of(report, rule_id)`` -> the check dict of a rule or None
- ``temp_rule(rule_id, fn)`` -> context manager that registers a rule for the duration of a test
- ``patch_runtime(monkeypatch, catalog=None, electrical=None, sources=None)`` -> makes pins.check (which uses the
  singletons) see a synthetic catalog, ESP values and extra sources (e.g. ``mod_fixtures.SOURCES``)
"""
from __future__ import annotations

import contextlib
from collections.abc import Callable, Iterator, Mapping
from typing import Any

from circuit_bench.bench_core import modcheck


def assign(mode: str, pin: int, net: str | None = None, role: str | None = None) -> dict[str, Any]:
    out: dict[str, Any] = {"mode": mode, "pin": pin}
    if net is not None:
        out["net"] = net
    if role is not None:
        out["role"] = role
    return out


def i2c(sda: int = 8, scl: int = 9, net: str = "SDA0", scl_net: str | None = None) -> list[dict[str, Any]]:
    return [assign("i2c_sda", sda, net, "SDA"), assign("i2c_scl", scl, scl_net or net.replace("SDA", "SCL"), "SCL")]


def mod(ref: str, module: str, conn: Mapping[str, str] | None = None, address: str | None = None,
        facts: Mapping[str, Any] | None = None, variant: str | None = None, qty: int | None = None) -> dict[str, Any]:
    out: dict[str, Any] = {"ref": ref, "kind": "module", "value": module, "module": module}
    if variant is not None:
        out["variant"] = variant
    if conn is not None:
        out["conn"] = dict(conn)
    if address is not None:
        out["address"] = address
    if facts is not None:
        out["facts"] = dict(facts)
    if qty is not None:
        out["qty"] = qty
    return out


def project(chip: str = "esp32s3", assignments: Any = (), parts: Any = (), options: Mapping[str, Any] | None = None,
            devkit: str | None = None) -> dict[str, Any]:
    return {"chip": chip, "assignments": list(assignments), "parts": list(parts),
            "options": dict(options) if options is not None else None, "devkit": devkit}


def run(catalog: Any = None, electrical: Any = None, **proj: Any) -> modcheck.ModReport | None:
    only = proj.pop("only", None)
    return modcheck.run(**project(**proj), catalog=catalog, electrical=electrical, only=only)


def codes(report: modcheck.ModReport | None) -> set[str]:
    return set() if report is None else {w["code"] for w in report.warnings}


def by_rule(report: modcheck.ModReport | None, rule_id: str) -> list[dict[str, Any]]:
    """Warnings and checks of one rule (warnings first)."""
    if report is None:
        return []
    return ([w for w in report.warnings if w["code"] == modcheck.warning_code(rule_id)]
            + [c for c in report.checks if c["id"] == modcheck.check_id(rule_id)])


def findings(report: modcheck.ModReport | None, rule_id: str | None = None,
             status: str | None = None) -> list[modcheck.Finding]:
    if report is None:
        return []
    return [f for f in report.findings if (rule_id is None or f.rule_id == rule_id)
            and (status is None or f.status == status)]


def check_of(report: modcheck.ModReport | None, rule_id: str) -> dict[str, Any] | None:
    if report is None:
        return None
    return next((c for c in report.checks if c["id"] == modcheck.check_id(rule_id)), None)


@contextlib.contextmanager
def temp_rule(rule_id: str, fn: Callable[[modcheck.Ctx], list[modcheck.Finding]]) -> Iterator[None]:
    modcheck.rule(rule_id)(fn)
    try:
        yield
    finally:
        modcheck.unregister(rule_id)


def patch_runtime(monkeypatch: Any, catalog: Any = None, electrical: Any = None,
                  sources: Mapping[str, Mapping[str, Any]] | None = None) -> None:
    from circuit_bench.bench_core import electrical as el
    from circuit_bench.bench_core import modules
    from circuit_bench.bench_core import sources as src
    if catalog is not None:
        monkeypatch.setattr(modules, "catalog", lambda: catalog)
    if electrical is not None:
        values = dict(electrical)
        monkeypatch.setattr(el, "get", lambda chip: dict(values) if chip == values.get("chip") else None)
    if sources is not None:
        base = src.all_sources()
        extra = {k: {kk: vv for kk, vv in v.items() if kk in ("id", "title", "url", "retrieved", "note")}
                 for k, v in sources.items()}
        merged = {**base, **extra}
        monkeypatch.setattr(src, "_load", lambda: merged)
