"""Module catalog: data/modules/*.json, validated, indexed by id and alias.

- ``Catalog.from_dir(path)`` reads every ``*.json`` (sorted), validates it against ``modspec`` and the sources
  (``sources.all_sources()``) and the excerpts (``tests/corpus/excerpts`` is NOT available at runtime: the runtime
  loader checks structure and source ids only; ``evidence`` ⊂ excerpt is a test, see tests/excerpts.py and
  tests/test_m0_modules_data.py).
- ``Catalog.from_entries(modules, *, sources=None)`` builds a catalog from dicts (tests, synthetic catalogs in
  tests/mod_fixtures.py). ``sources``: {id: {..., "class": "A"}}; None = take sources.all_sources().
- Invalid entries: ``Catalog.problems`` lists them ("<file>: <id>: <text>"); ``catalog()`` (the runtime singleton)
  keeps the valid entries and drops broken ones, tests assert ``problems == []``.
- Lookup: ``get(id_or_alias, variant=None)`` returns a deep copy with the variant's ``overrides`` applied (flat
  per top-level key: an override replaces the whole key), plus ``"_wp"`` (file stem) and ``"_class"`` (strongest =
  first source's class). Unknown -> BenchError invalid_args, hint "list modules with bench_pins action=modules".
- ``search(q=None, category=None, interface=None, limit=40, offset=0)`` -> {"total", "items": [compact rows]}:
  row = {id, title, category, kind, interfaces: [type], addresses: [hex], supply: "1.71–3.6 V" | None, class}.
  q matches id, aliases, title, manufacturer (case-insensitive substring); ordering: category, then id.
- ``families()`` -> sorted wp names; ``categories()`` -> sorted categories present.
- ``value(F, supplies_v)`` resolves a cited number: plain ``value``; ``rel`` × V(of); ``rel_offset`` + V(of).
  ``supplies_v``: {supply pin name: volts}. Missing supply -> None.
"""
from __future__ import annotations

import copy
import json
import math
import re
from collections.abc import Mapping
from functools import lru_cache
from pathlib import Path
from typing import Any

from . import modspec as ms
from .contracts import BenchError

MODULES_DIR = Path(__file__).resolve().parent.parent / "data" / "modules"

ALIAS_RE = re.compile(r"^[a-z0-9][a-z0-9_.+-]{1,47}$")  # lower case; lookups are case-insensitive
VARIANT_RE = re.compile(r"^[a-z0-9][a-z0-9_.-]{0,31}$")
CLASS_RANK = {"A": 3, "A1": 3, "A2": 2, "B": 1}  # source_ids[0] must have the highest rank (``_class``)
_NOT_OVERRIDABLE = frozenset({"id", "aliases", "variants"})
_V_KEYS = ("vih", "vil", "voh", "vol", "v_in_max")
_I2C_ONLY = ("addresses", "default", "select", "reserved", "mux_channels")
_HINT = "list modules with bench_pins action=modules"


def _num(x: Any) -> bool:
    return isinstance(x, int | float) and not isinstance(x, bool) and math.isfinite(x)


def _text(x: Any) -> bool:
    return isinstance(x, str) and bool(x.strip())


def evidence_parts(ev: Any) -> list[str] | None:
    """``evidence`` as a list of line parts (a string or a non-empty list of strings); None if malformed."""
    if _text(ev):
        return [ev]
    if isinstance(ev, list) and ev and all(_text(e) for e in ev):
        return list(ev)
    return None


class _Checker:
    """Structural validation of one entry: closed lists, units, F structure, references, source ids, caps."""

    def __init__(self, m: Mapping[str, Any], sources: Mapping[str, Mapping[str, Any]]):
        self.m = m
        self.sources = sources
        self.out: list[str] = []
        sids = m.get("source_ids")
        self.sids = [s for s in sids if isinstance(s, str)] if isinstance(sids, list) else []
        pins = m.get("pins") if isinstance(m.get("pins"), list) else []
        self.pin_names = [p["name"] for p in pins if isinstance(p, Mapping) and _text(p.get("name"))]
        self.supply_pins = {p["name"] for p in pins if isinstance(p, Mapping) and _text(p.get("name"))
                            and p.get("signal") == "supply"}

    def bad(self, text: str) -> None:
        self.out.append(text)

    def keys(self, obj: Any, allowed: frozenset[str], where: str) -> bool:
        if not isinstance(obj, Mapping):
            self.bad(f"{where}: expected an object")
            return False
        extra = sorted(set(obj) - allowed)
        if extra:
            self.bad(f"{where}: unknown keys {extra}")
        return True

    def cls(self, sid: str | None) -> str | None:
        return (self.sources.get(sid) or {}).get("class") if sid else None

    def cited(self, obj: Mapping[str, Any], where: str, *, required: bool) -> str | None:
        """Check evidence/page/source_id of a quoted item; returns the cited source id (or None)."""
        has = "evidence" in obj
        if not has:
            if required:
                self.bad(f"{where}: evidence (line of the excerpt) and page are required")
            for k in ("page", "source_id"):
                if k in obj:
                    self.bad(f"{where}: {k} without evidence")
            return None
        if evidence_parts(obj["evidence"]) is None:
            self.bad(f"{where}: evidence must be a non-empty string or a non-empty list of strings")
        page = obj.get("page")
        if not (isinstance(page, int) and not isinstance(page, bool) and page >= 1):
            self.bad(f"{where}: page must be a PDF page number >= 1")
        sid = obj.get("source_id")
        if sid is None:
            if len(self.sids) != 1:
                self.bad(f"{where}: source_id is required (the module has {len(self.sids)} sources)")
                return None
            return self.sids[0]
        if sid not in self.sids:
            self.bad(f"{where}: source_id {sid!r} is not in the module's source_ids")
        return sid if isinstance(sid, str) else None

    def f(self, obj: Any, where: str, *, unit: str | None = None, absolute: bool = False,
          addresses: bool = False) -> None:
        """A cited number F."""
        if not self.keys(obj, ms.F_KEYS, where):
            return
        kinds = [k for k in ("value", "rel", "rel_offset") if k in obj]
        if len(kinds) != 1:
            self.bad(f"{where}: exactly one of value / rel / rel_offset (got {kinds or 'none'})")
        kind = kinds[0] if kinds else None
        if addresses:
            v = obj.get("value")
            if kind != "value" or not isinstance(v, list) or not v or not all(
                    isinstance(a, str) and ms.I2C_ADDR_RE.fullmatch(a) for a in v) or len(set(v)) != len(v):
                self.bad(f"{where}: value must be a list of distinct 7-bit addresses like '0x76'")
            if "unit" in obj or "of" in obj:
                self.bad(f"{where}: an address list has no unit / of")
        else:
            if kind and not _num(obj[kind]):
                self.bad(f"{where}: {kind} must be a finite number")
            if obj.get("unit") not in ms.UNITS:
                self.bad(f"{where}: unit {obj.get('unit')!r} not in {list(ms.UNITS)}")
            elif unit and obj["unit"] != unit:
                self.bad(f"{where}: unit must be {unit!r} (SI base unit), got {obj['unit']!r}")
            if kind in ("rel", "rel_offset"):
                if absolute:
                    self.bad(f"{where}: {kind} is not allowed here (absolute value expected)")
                if obj.get("unit") != "V":
                    self.bad(f"{where}: {kind} needs unit 'V'")
                if obj.get("of") not in self.supply_pins:
                    self.bad(f"{where}: of must name a supply pin of the module ({sorted(self.supply_pins)}), "
                             f"got {obj.get('of')!r}")
            elif "of" in obj:
                self.bad(f"{where}: of is only allowed with rel / rel_offset")
        if "conditions" in obj and not isinstance(obj["conditions"], str):
            self.bad(f"{where}: conditions must be a string")
        sid = self.cited(obj, where, required=True)
        if not addresses and self.cls(sid) == "B":
            self.bad(f"{where}: class B source {sid!r} cannot back a hard value (use notes with verified: false)")

    # --- sections -------------------------------------------------------------------------------------------------
    def run(self) -> list[str]:
        m = self.m
        if not self.keys(m, ms.MODULE_KEYS, "entry"):
            return self.out
        missing = sorted(ms.MODULE_REQUIRED - set(m))
        if missing:
            self.bad(f"missing keys {missing}")
        if not (isinstance(m.get("id"), str) and ms.MODULE_ID_RE.fullmatch(m["id"])):
            self.bad(f"id must match {ms.MODULE_ID_RE.pattern}")
        aliases = m.get("aliases", [])
        if not isinstance(aliases, list) or not all(isinstance(a, str) and ALIAS_RE.fullmatch(a) for a in aliases):
            self.bad(f"aliases must be a list of names matching {ALIAS_RE.pattern}")
        elif len(set(aliases)) != len(aliases) or m.get("id") in aliases:
            self.bad("aliases must be distinct and differ from the id")
        for k in ("title", "manufacturer"):
            if k in m and not _text(m[k]):
                self.bad(f"{k} must be a non-empty string")
        if "category" in m and m["category"] not in ms.CATEGORIES:
            self.bad(f"category {m['category']!r} not in modspec.CATEGORIES")
        if "kind" in m and m["kind"] not in ms.KINDS:
            self.bad(f"kind {m['kind']!r} not in {list(ms.KINDS)}")
        if "module_datasheet" in m and (not isinstance(m["module_datasheet"], bool) or m.get("kind") != "module"):
            self.bad("module_datasheet must be true/false and only on kind 'module'")
        self.source_ids(m.get("source_ids"))
        self.pins(m.get("pins"))
        if "supplies" in m:
            self.supplies(m["supplies"])
        if "io" in m:
            self.io(m["io"])
        if "interfaces" in m:
            self.interfaces(m["interfaces"])
        if "current" in m:
            self.current(m["current"])
        for key, fn in (("requires", self.require), ("hazards", self.hazard), ("notes", self.note)):
            if key in m:
                if not isinstance(m[key], list):
                    self.bad(f"{key} must be a list")
                    continue
                for i, item in enumerate(m[key]):
                    fn(item, f"{key}[{i}]")
        return self.out

    def source_ids(self, sids: Any) -> None:
        if "source_ids" not in self.m:
            return
        if not isinstance(sids, list) or not sids or not all(isinstance(s, str) for s in sids):
            self.bad("source_ids must be a non-empty list of source ids")
            return
        if len(set(sids)) != len(sids):
            self.bad("source_ids must be distinct")
        for s in sids:
            if s not in self.sources:
                self.bad(f"unknown source id {s!r}")
        ranks = [CLASS_RANK[c] for c in (self.cls(s) for s in sids) if c in CLASS_RANK]
        first = CLASS_RANK.get(self.cls(sids[0]) or "")
        if first is not None and ranks and first < max(ranks):
            self.bad("source_ids[0] must be the strongest source (class A/A1 > A2 > B)")

    def pins(self, pins: Any) -> None:
        if "pins" not in self.m:
            return
        if not isinstance(pins, list) or not pins:
            self.bad("pins must be a non-empty list")
            return
        seen: set[str] = set()
        for i, p in enumerate(pins):
            where = f"pins[{i}]"
            if not self.keys(p, ms.PIN_KEYS, where):
                continue
            name = p.get("name")
            if not _text(name):
                self.bad(f"{where}: name must be a non-empty string")
            elif name in seen:
                self.bad(f"{where}: duplicate pin name {name!r}")
            else:
                seen.add(name)
                where = f"pins[{name}]"
            if p.get("signal") not in ms.SIGNALS:
                self.bad(f"{where}: signal {p.get('signal')!r} not in modspec.SIGNALS")
            for k in ("tie", "note"):
                if k in p and not _text(p[k]):
                    self.bad(f"{where}: {k} must be a non-empty string")
            for k in ("must_connect", "active_low"):
                if k in p and not isinstance(p[k], bool):
                    self.bad(f"{where}: {k} must be true/false")
            if "output" in p and p["output"] not in ms.OUTPUT_TYPES:
                self.bad(f"{where}: output {p['output']!r} not in {list(ms.OUTPUT_TYPES)}")
            if "internal_pull" in p:
                ip = p["internal_pull"]
                if ip in ("up", "down"):
                    pass
                elif isinstance(ip, Mapping) and len(ip) == 1 and next(iter(ip)) in ("up", "down"):
                    d = next(iter(ip))
                    self.f(ip[d], f"{where}.internal_pull.{d}", unit="Ω", absolute=True)
                else:
                    self.bad(f"{where}: internal_pull must be 'up', 'down' or {{'up'|'down': F (Ω)}}")

    def supplies(self, sup: Any) -> None:
        if not isinstance(sup, Mapping) or not sup:
            self.bad("supplies must be a non-empty object {supply pin: {min, max, abs_max, typ}}")
            return
        for pin, spec in sup.items():
            where = f"supplies.{pin}"
            if pin not in self.supply_pins:
                self.bad(f"{where}: {pin!r} is not a pin with signal 'supply'")
            if not self.keys(spec, ms.SUPPLY_KEYS, where):
                continue
            if not spec:
                self.bad(f"{where}: empty")
            for k, fv in spec.items():
                if k in ms.SUPPLY_KEYS:
                    self.f(fv, f"{where}.{k}", unit="V", absolute=True)
            vals = [value(spec.get(k), {}) for k in ("min", "typ", "max", "abs_max")]
            known = [v for v in vals if v is not None]
            if known != sorted(known):
                self.bad(f"{where}: expected min <= typ <= max <= abs_max")

    def io(self, io: Any) -> None:
        if not self.keys(io, ms.IO_KEYS, "io"):
            return
        if "domain" in io and io["domain"] not in self.supply_pins:
            self.bad(f"io.domain {io['domain']!r} is not a supply pin of the module")
        for k in _V_KEYS:
            if k in io:
                self.f(io[k], f"io.{k}", unit="V")
        if "outputs" in io and io["outputs"] not in ms.OUTPUT_TYPES:
            self.bad(f"io.outputs {io['outputs']!r} not in {list(ms.OUTPUT_TYPES)}")
        if "five_v_tolerant" in io and not isinstance(io["five_v_tolerant"], bool):
            self.bad("io.five_v_tolerant must be true/false")
        for m in ms.domain_v_problems(io):
            self.bad(m)

    def interfaces(self, ifs: Any) -> None:
        if not isinstance(ifs, list):
            self.bad("interfaces must be a list")
            return
        for i, it in enumerate(ifs):
            where = f"interfaces[{i}]"
            if not self.keys(it, ms.INTERFACE_KEYS, where):
                continue
            t = it.get("type")
            if t not in ms.INTERFACE_TYPES:
                self.bad(f"{where}: type {t!r} not in {list(ms.INTERFACE_TYPES)}")
            if t != "i2c":
                for k in _I2C_ONLY:
                    if k in it:
                        self.bad(f"{where}: {k} is only allowed on i2c interfaces")
            addrs: list[str] = []
            if "addresses" in it:
                self.f(it["addresses"], f"{where}.addresses", addresses=True)
                v = it["addresses"].get("value") if isinstance(it["addresses"], Mapping) else None
                addrs = [a for a in v if isinstance(a, str)] if isinstance(v, list) else []
            if "default" in it and it["default"] not in addrs:
                self.bad(f"{where}: default {it['default']!r} is not in addresses {addrs}")
            if "select" in it:
                sel = it["select"]
                # one pin: {"pin": "SDO", "map": {net: address}}; several pins (A0..An): {"pins": ["A2", "A1", "A0"],
                # "map": {"GND,GND,VDD": address}}, one comma-separated target per pin in the order of "pins"
                multi = isinstance(sel, Mapping) and set(sel) == {"pins", "map"}
                if not (isinstance(sel, Mapping) and (set(sel) == {"pin", "map"} or multi)
                        and isinstance(sel["map"], Mapping) and sel["map"]):
                    self.bad(f"{where}: select must be {{'pin': <pin>, 'map': {{net: address}}}} or "
                             f"{{'pins': [<pin>, ...], 'map': {{'net,net,...': address}}}}")
                else:
                    sel_pins = sel["pins"] if multi else [sel["pin"]]
                    if not (isinstance(sel_pins, list) and sel_pins and len(set(map(str, sel_pins))) == len(sel_pins)):
                        self.bad(f"{where}: select.pins must be a list of distinct pin names")
                        sel_pins = []
                    for sp in sel_pins:
                        if sp not in self.pin_names:
                            self.bad(f"{where}: select.{'pins' if multi else 'pin'} {sp!r} is not a pin of the module")
                    for net, a in sel["map"].items():
                        parts_ = net.split(",") if multi and isinstance(net, str) else [net]
                        if not all(_text(x) for x in parts_) or a not in addrs:
                            self.bad(f"{where}: select.map {net!r} -> {a!r}: target must be one of addresses {addrs}")
                        elif multi and len(parts_) != len(sel_pins):
                            self.bad(f"{where}: select.map key {net!r} needs one target per pin {sel_pins}")
            if "reserved" in it:
                r = it["reserved"]
                if not (isinstance(r, list) and all(isinstance(a, str) and ms.I2C_ADDR_RE.fullmatch(a) for a in r)):
                    self.bad(f"{where}: reserved must be a list of 7-bit addresses")
            if "mux_channels" in it:
                mc = it["mux_channels"]
                ok = isinstance(mc, list) and mc and all(
                    isinstance(c, list) and len(c) == 2 and all(x in self.pin_names for x in c) for c in mc)
                if not ok:
                    self.bad(f"{where}: mux_channels must be a list of [SDx, SCx] pin name pairs of the module")
            if "f_max_hz" in it:
                self.f(it["f_max_hz"], f"{where}.f_max_hz", unit="Hz", absolute=True)
            if "mode" in it and it["mode"] not in (0, 1, 2, 3):
                self.bad(f"{where}: mode must be an SPI mode 0..3")
            if "lsb_first" in it and not isinstance(it["lsb_first"], bool):
                self.bad(f"{where}: lsb_first must be true/false")
            if "baud_default" in it and not (isinstance(it["baud_default"], int) and not isinstance(
                    it["baud_default"], bool) and it["baud_default"] > 0):
                self.bad(f"{where}: baud_default must be a positive integer")
            if "note" in it and not _text(it["note"]):
                self.bad(f"{where}: note must be a non-empty string")

    def current(self, cur: Any) -> None:
        if not self.keys(cur, ms.CURRENT_KEYS, "current"):
            return
        if "supply" in cur and cur["supply"] not in self.supply_pins:
            self.bad(f"current.supply {cur['supply']!r} is not a supply pin of the module")
        for k in ("typ", "max", "peak", "sleep"):
            if k in cur:
                self.f(cur[k], f"current.{k}", unit="A", absolute=True)
        if "note" in cur and not _text(cur["note"]):
            self.bad("current.note must be a non-empty string")

    def require(self, r: Any, where: str) -> None:
        if not self.keys(r, ms.REQUIRE_KEYS, where):
            return
        if r.get("code") not in ms.REQUIRE_CODES:
            self.bad(f"{where}: code {r.get('code')!r} not in {list(ms.REQUIRE_CODES)}")
        for k in ("kind", "value", "to", "note"):
            if k in r and not _text(r[k]):
                self.bad(f"{where}: {k} must be a non-empty string")
        if "pins" in r and not (isinstance(r["pins"], list) and r["pins"] and all(p in self.pin_names for p in r["pins"])):
            self.bad(f"{where}: pins must name pins of the module")
        sid = self.cited(r, where, required=True)
        if self.cls(sid) == "B":
            self.bad(f"{where}: class B source {sid!r} cannot back a requirement (use notes with verified: false)")

    def hazard(self, h: Any, where: str) -> None:
        if not self.keys(h, ms.HAZARD_KEYS, where):
            return
        if h.get("code") not in ms.HAZARD_CODES:
            self.bad(f"{where}: code {h.get('code')!r} not in {list(ms.HAZARD_CODES)}")
        if not _text(h.get("text")):
            self.bad(f"{where}: text (English) is required")
        self.cited(h, where, required=False)

    def note(self, n: Any, where: str) -> None:
        if not self.keys(n, ms.NOTE_KEYS, where):
            return
        if not _text(n.get("text")):
            self.bad(f"{where}: text is required")
        if "verified" in n and not isinstance(n["verified"], bool):
            self.bad(f"{where}: verified must be true/false")
        if "evidence" not in n and n.get("verified") is not False:
            self.bad(f"{where}: a note without evidence needs \"verified\": false")
        self.cited(n, where, required=False)


def apply_variant(entry: Mapping[str, Any], variant: Mapping[str, Any]) -> dict[str, Any]:
    """The entry with the variant's ``overrides`` applied (flat per top-level key), deep-copied."""
    out = copy.deepcopy(dict(entry))
    for k, v in (variant.get("overrides") or {}).items():
        out[k] = copy.deepcopy(v)
    return out


def validate_module(m: Mapping[str, Any], sources: Mapping[str, Mapping[str, Any]]) -> list[str]:
    """Problems of one catalog entry (structure, closed lists, units, F, references, source ids, class caps); the
    variants are checked with their overrides applied. Excerpt quotes are checked by the tests, not here."""
    out = _Checker(m, sources).run()
    if not isinstance(m, Mapping) or "variants" not in m:
        return out
    vs = m["variants"]
    if not isinstance(vs, list):
        return [*out, "variants must be a list"]
    seen: set[str] = set()
    for i, v in enumerate(vs):
        where = f"variants[{i}]"
        if not isinstance(v, Mapping) or set(v) - ms.VARIANT_KEYS:
            out.append(f"{where}: expected {{id, title, overrides}}")
            continue
        vid = v.get("id")
        if not (isinstance(vid, str) and VARIANT_RE.fullmatch(vid)) or vid in seen:
            out.append(f"{where}: id must match {VARIANT_RE.pattern} and be unique")
            continue
        seen.add(vid)
        if not _text(v.get("title")):
            out.append(f"variants[{vid}]: title is required")
        ov = v.get("overrides")
        if not isinstance(ov, Mapping) or not ov:
            out.append(f"variants[{vid}]: overrides must be a non-empty object")
            continue
        bad = sorted(set(ov) - (ms.MODULE_KEYS - _NOT_OVERRIDABLE))
        if bad:
            out.append(f"variants[{vid}]: overrides cannot set {bad}")
            continue
        eff = apply_variant({k: x for k, x in m.items() if k != "variants"}, v)
        base = set(_Checker({k: x for k, x in m.items() if k != "variants"}, sources).run())
        out.extend(f"variants[{vid}]: {p}" for p in _Checker(eff, sources).run() if p not in base)
    return out


def _fmt_v(x: float) -> str:
    return f"{x:g}"


def supply_text(entry: Mapping[str, Any]) -> str | None:
    """'1.71–3.6 V' for the main supply (current.supply, else the first in supplies); None without values."""
    sup = entry.get("supplies")
    if not isinstance(sup, Mapping) or not sup:
        return None
    cur = entry.get("current") if isinstance(entry.get("current"), Mapping) else {}
    pin = cur.get("supply") if cur.get("supply") in sup else next(iter(sup))
    spec = sup.get(pin) if isinstance(sup.get(pin), Mapping) else {}
    lo, hi = value(spec.get("min"), {}), value(spec.get("max"), {})
    if lo is not None and hi is not None:
        return f"{_fmt_v(lo)}–{_fmt_v(hi)} V"
    if hi is not None:
        return f"≤{_fmt_v(hi)} V"
    if lo is not None:
        return f"≥{_fmt_v(lo)} V"
    return None


def addresses(entry: Mapping[str, Any]) -> list[str]:
    out: list[str] = []
    for it in entry.get("interfaces") or []:
        f = it.get("addresses") if isinstance(it, Mapping) else None
        for a in (f.get("value") if isinstance(f, Mapping) else None) or []:
            if a not in out:
                out.append(a)
    return out


class Catalog:
    problems: list[str]

    def __init__(self, sources: Mapping[str, Mapping[str, Any]]):
        self.problems = []
        self._sources = {k: dict(v) for k, v in sources.items()}
        self._entries: dict[str, dict[str, Any]] = {}
        self._wp: dict[str, str] = {}
        self._index: dict[str, str] = {}  # lower-case id / alias -> id

    @staticmethod
    def _default_sources() -> dict[str, dict[str, Any]]:
        from . import sources
        return sources.all_sources()

    @classmethod
    def from_dir(cls, path: Path = MODULES_DIR) -> Catalog:
        cat = cls(cls._default_sources())
        for file in sorted(Path(path).glob("*.json")) if Path(path).is_dir() else []:
            label = file.name
            try:
                doc = json.loads(file.read_text(encoding="utf-8"))
            except (OSError, ValueError) as e:
                cat.problems.append(f"{label}: -: not readable JSON ({e})")
                continue
            file_problems = []
            if not isinstance(doc, dict):
                cat.problems.append(f"{label}: -: expected an object {{schema, wp, note, modules}}")
                continue
            if set(doc) - ms.FILE_KEYS:
                file_problems.append(f"unknown keys {sorted(set(doc) - ms.FILE_KEYS)}")
            if doc.get("schema") != ms.SCHEMA:
                file_problems.append(f"schema must be {ms.SCHEMA}")
            if not ms.WP_RE.fullmatch(file.stem):
                file_problems.append(f"file name {file.stem!r} does not match {ms.WP_RE.pattern}")
            if doc.get("wp") != file.stem:
                file_problems.append(f"wp {doc.get('wp')!r} differs from the file name {file.stem!r}")
            if not isinstance(doc.get("modules"), list):
                file_problems.append("modules must be a list")
            if file_problems:
                cat.problems.extend(f"{label}: -: {p}" for p in file_problems)
                continue
            cat._add(label, file.stem, doc["modules"])
        return cat

    @classmethod
    def from_entries(cls, modules: list[Mapping[str, Any]], *, sources: Mapping[str, Mapping[str, Any]] | None = None,
                     wp: str = "test") -> Catalog:
        cat = cls(cls._default_sources() if sources is None else sources)
        cat._add(f"{wp}.json", wp, list(modules))
        return cat

    def _add(self, label: str, wp: str, modules: list[Any]) -> None:
        for i, m in enumerate(modules):
            mid = m.get("id") if isinstance(m, Mapping) and isinstance(m.get("id"), str) else f"#{i}"
            found = validate_module(m, self._sources) if isinstance(m, Mapping) else ["expected an object"]
            if not found:
                names = [m["id"], *m.get("aliases", [])]
                for n in names:
                    owner = self._index.get(n.lower())
                    if owner is not None:
                        found.append(f"{'id' if n == m['id'] else 'alias'} {n!r} is already used by "
                                     f"{owner!r} ({self._wp[owner]}.json)")
            if found:
                self.problems.extend(f"{label}: {mid}: {p}" for p in found)
                continue
            self._entries[mid] = copy.deepcopy(dict(m))
            self._wp[mid] = wp
            for n in [mid, *m.get("aliases", [])]:
                self._index[n.lower()] = mid

    def ids(self) -> list[str]:
        return sorted(self._entries)

    def has(self, id_or_alias: str) -> bool:
        return isinstance(id_or_alias, str) and id_or_alias.strip().lower() in self._index

    def resolve_id(self, id_or_alias: str) -> str:
        if not self.has(id_or_alias):
            raise BenchError("invalid_args", f"unknown module {id_or_alias!r}", _HINT)
        return self._index[id_or_alias.strip().lower()]

    def source_class(self, source_id: str | None) -> str | None:
        return (self._sources.get(source_id) or {}).get("class") if source_id else None

    def get(self, id_or_alias: str, variant: str | None = None) -> dict[str, Any]:
        mid = self.resolve_id(id_or_alias)
        entry = self._entries[mid]
        if variant:
            vs = {v["id"]: v for v in entry.get("variants", [])}
            if variant not in vs:
                raise BenchError("invalid_args", f"unknown variant {variant!r} of module {mid!r}",
                                 f"variants of {mid}: {', '.join(vs) or 'none'}")
            out = apply_variant(entry, vs[variant])
        else:
            out = copy.deepcopy(entry)
        out["_wp"] = self._wp[mid]
        out["_class"] = self.source_class(out["source_ids"][0])
        return out

    def _row(self, mid: str) -> dict[str, Any]:
        e = self._entries[mid]
        return {"id": mid, "title": e["title"], "category": e["category"], "kind": e["kind"],
                "interfaces": [it["type"] for it in e.get("interfaces", [])], "addresses": addresses(e),
                "supply": supply_text(e), "class": self.source_class(e["source_ids"][0])}

    def search(self, q: str | None = None, category: str | None = None, interface: str | None = None,
               limit: int = 40, offset: int = 0) -> dict[str, Any]:
        needle = q.strip().lower() if isinstance(q, str) and q.strip() else None
        hits = []
        for mid, e in self._entries.items():
            if category and not (e["category"] == category or e["category"].startswith(f"{category}.")):
                continue
            if interface and interface not in {it["type"] for it in e.get("interfaces", [])}:
                continue
            if needle and not any(needle in s.lower() for s in (mid, *e.get("aliases", []), e["title"],
                                                                 e["manufacturer"])):
                continue
            hits.append(mid)
        hits.sort(key=lambda i: (self._entries[i]["category"], i))
        offset = max(0, int(offset or 0))
        limit = max(0, int(limit if limit is not None else 40))
        return {"total": len(hits), "items": [self._row(i) for i in hits[offset:offset + limit]]}

    def families(self) -> list[str]:
        return sorted(set(self._wp.values()))

    def categories(self) -> list[str]:
        return sorted({e["category"] for e in self._entries.values()})


@lru_cache(maxsize=1)
def catalog() -> Catalog:
    return Catalog.from_dir(MODULES_DIR)


def clear_cache() -> None:
    catalog.cache_clear()


def value(f: Mapping[str, Any] | None, supplies_v: Mapping[str, float]) -> float | None:
    if not isinstance(f, Mapping):
        return None
    if "value" in f:
        return float(f["value"]) if _num(f["value"]) else None
    for kind in ("rel", "rel_offset"):
        if kind in f:
            v = supplies_v.get(f.get("of")) if f.get("of") is not None else None
            if not _num(f[kind]) or v is None:
                return None
            return f[kind] * float(v) if kind == "rel" else float(v) + f[kind]
    return None
