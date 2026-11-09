"""Shared harness of the module API tests (no tests in here): a synthetic module catalog, a temporary calculator and
a project.update stand-in for the module ops (independent of the real catalog and project code).

- ``FakeCatalog(entries)``: ``has``/``get``/``search`` with the contract shapes of modules.Catalog.
- ``ENTRY``: one synthetic module (``zz_sensor``) with sourced numbers, an I²C interface, a hazard and a variant.
- ``dummy_calc(calckit, contracts, monkeypatch)``: registers ``zz_dummy`` (unit V input + plain number) in the given
  package copy and removes it again at teardown (the action ``calc.zz_dummy`` exists only during the test).
- ``fake_module_update(project_mod, monkeypatch)``: project.update applies add_module/connect/set_rails in memory
  (other ops go to the real function) and records every op list it saw.
"""
from __future__ import annotations

import copy
from typing import Any

DUMMY = "zz_dummy"
SRC = "nxp-um10204"  # an existing source id (data/sources), stands in for a module datasheet

ENTRY: dict[str, Any] = {
    "id": "zz_sensor", "aliases": ["zz-breakout"], "title": "ZZ synthetic I2C sensor", "category": "sensor.environment",
    "manufacturer": "Synthetic", "kind": "module", "source_ids": [SRC, "zz-unknown-source"],
    "supplies": {"VDD": {"min": {"value": 1.71, "unit": "V", "page": 3, "evidence": "VDD 1.71 3.6 V",
                                  "source_id": SRC},
                         "max": {"value": 3.6, "unit": "V", "page": 3, "evidence": "VDD 1.71 3.6 V"}}},
    "io": {"domain": "VDD", "vih": {"rel": 0.7, "of": "VDD", "unit": "V", "evidence": "VIH 0.7 VDD", "page": 4}},
    "pins": [{"name": "SDA", "signal": "i2c_sda"}, {"name": "SCL", "signal": "i2c_scl"},
             {"name": "VDD", "signal": "supply"}, {"name": "GND", "signal": "gnd"}],
    "interfaces": [{"type": "i2c", "addresses": {"value": ["0x44", "0x45"], "evidence": "address 0x44 or 0x45"},
                    "default": "0x44"}],
    "current": {"supply": "VDD", "max": {"value": 0.0005, "unit": "A", "evidence": "IDD 500 uA"}},
    "requires": [{"code": "decoupling", "kind": "ceramic", "value": "100nF", "pins": ["VDD", "GND"]}],
    "hazards": [{"code": "heat", "text": "The heater gets hot.", "source_id": SRC}],
    "variants": [{"id": "b", "title": "Variant B", "overrides": {"title": "ZZ synthetic I2C sensor (B)"}}],
    "notes": [{"text": "Breakouts may add pull-ups.", "verified": False}],
}
OTHER: dict[str, Any] = {
    "id": "zz_display", "title": "ZZ synthetic display", "category": "display.oled", "manufacturer": "Synthetic",
    "kind": "module", "source_ids": [SRC], "pins": [{"name": "VCC", "signal": "supply"}],
    "interfaces": [{"type": "spi"}],
}


def _make_error(code: str, message: str, hint: str | None = None) -> Exception:
    from circuit_bench.bench_core.contracts import BenchError  # any package copy works (serialport.local_error)
    return BenchError(code, message, hint)


class FakeCatalog:
    problems: list[str] = []

    def __init__(self, entries: list[dict[str, Any]] | None = None):
        self.entries = {e["id"]: e for e in (entries if entries is not None else [ENTRY, OTHER])}
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def _resolve(self, key: str) -> str | None:
        for mid, e in self.entries.items():
            if key == mid or key in e.get("aliases", ()):
                return mid
        return None

    def has(self, id_or_alias: str) -> bool:
        return self._resolve(id_or_alias) is not None

    def get(self, id_or_alias: str, variant: str | None = None) -> dict[str, Any]:
        self.calls.append(("get", {"id": id_or_alias, "variant": variant}))
        mid = self._resolve(id_or_alias)
        if mid is None:
            raise _make_error("invalid_args", f"unknown module {id_or_alias!r}",
                              "list modules with bench_pins action=modules")
        e = copy.deepcopy(self.entries[mid])
        if variant is not None:
            v = next((v for v in e.get("variants") or [] if v["id"] == variant), None)
            if v is None:
                raise _make_error("invalid_args", f"unknown variant {variant!r} of {mid}")
            e.update(copy.deepcopy(v["overrides"]))
        return {**e, "_wp": "test", "_class": "A"}

    def search(self, q=None, category=None, interface=None, limit=40, offset=0) -> dict[str, Any]:
        self.calls.append(("search", {"q": q, "category": category, "interface": interface, "limit": limit,
                                      "offset": offset}))
        rows = []
        for e in sorted(self.entries.values(), key=lambda e: (e["category"], e["id"])):
            if q and q.lower() not in f"{e['id']} {e['title']} {' '.join(e.get('aliases', ()))}".lower():
                continue
            if category and e["category"] != category:
                continue
            types_ = [i["type"] for i in e.get("interfaces") or []]
            if interface and interface not in types_:
                continue
            rows.append({"id": e["id"], "title": e["title"], "category": e["category"], "kind": e["kind"],
                         "interfaces": types_, "addresses": [], "supply": None, "class": "A"})
        return {"total": len(rows), "items": rows[offset:offset + limit]}


def dummy_calc(calckit, contracts, monkeypatch) -> None:
    """Register zz_dummy in this package copy (unregistered again by monkeypatch teardown)."""
    monkeypatch.setattr(contracts, "ACTIONS", contracts.ACTIONS | {f"calc.{DUMMY}"})

    @calckit.action(f"calc.{DUMMY}")
    def zz_dummy(v_x, n=2):
        n = calckit.count(n, "n")
        return calckit.envelope(f"calc.{DUMMY}", f"{v_x} × {n}", {"echo": {"v_x": v_x, "n": n}})

    calckit.register(DUMMY, zz_dummy, (("v_x", "V", True, None), ("n", "", False, 2)), title="Dummy",
                     group="basics", summary="A temporary test calculator.")
    entry = calckit.REGISTRY.pop(DUMMY)
    monkeypatch.setitem(calckit.REGISTRY, DUMMY, entry)  # teardown removes the key again


def fake_module_update(project_mod, monkeypatch) -> list[list[dict[str, Any]]]:
    """project.update/get with add_module/connect/set_rails applied in memory (the real ops live in project.py);
    other ops go to the real functions. Returns every op list update() saw."""
    real_update, real_get = project_mod.update, project_mod.get
    seen: list[list[dict[str, Any]]] = []
    state: dict[str, dict[str, Any]] = {}

    def get(pid):
        if pid in state:
            p = copy.deepcopy(state[pid])
            return project_mod.envelope("project.get", "fake", {"rev": p["rev"], "project": p})
        return real_get(pid)

    def update(pid, expected_rev, ops, *, by, trusted=False):
        seen.append(copy.deepcopy(ops))
        if not any(isinstance(o, dict) and o.get("op") in ("add_module", "connect", "set_rails") for o in ops):
            assert pid not in state, "fake: mixing real ops after module ops is not supported"
            return real_update(pid, expected_rev, ops, by=by, trusted=trusted)
        cur = get(pid)
        if not cur["ok"]:
            return cur
        p = copy.deepcopy(cur["result"]["project"])
        for op in ops:
            if op["op"] == "add_module":
                ref = op.get("ref") or f"U{sum(1 for x in p['parts'] if x.get('module')) + 1}"
                p["parts"].append({"ref": ref, "kind": "module", "value": op["module"], "qty": op.get("qty", 1),
                                   **{k: op[k] for k in ("module", "variant", "conn", "address", "facts") if k in op}})
            elif op["op"] == "connect":
                part = next(x for x in p["parts"] if x["ref"] == op["ref"])
                part["conn"] = {**(part.get("conn") or {}), **op["conn"]}
            elif op["op"] == "set_rails":
                p.setdefault("options", {})
                for key in ("rails", "rail_limits"):
                    if key in op:
                        p["options"][key] = op[key]
        p["rev"] = cur["result"]["rev"] + 1
        state[pid] = p
        return project_mod.envelope("project.update", f"rev {p['rev']}",
                                    {"rev": p["rev"], "project": copy.deepcopy(p), "changed": ["parts", "options"]})

    monkeypatch.setattr(project_mod, "update", update)
    monkeypatch.setattr(project_mod, "get", get)
    return seen
