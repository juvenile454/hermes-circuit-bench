"""Module check engine; rules live in modrules/*.py.

Rule files: modrules/bus.py, modrules/elec.py and
modrules/<family>.py (one per module family). Rules are pure functions ``(ctx: Ctx) -> list[Finding]`` registered with
``@rule("mod.<name>")`` / ``@rule("mod.<family>.<name>")``; modrules/__init__.py imports every module in the package
in sorted order (auto-discovery), so adding a file needs no edit elsewhere. Rule files import the engine with
``from . import modcheck`` (re-exported by modrules/__init__.py; bench_core never uses ``from ..``).

Inputs of ``run`` (all plain data, no I/O except the catalog/electrical singletons when not given):
- ``chip``: chip id (bench_core.chips), ``assignments``: [{role?, mode, pin, net?}] as in pins.check,
- ``parts``: the project's ``parts[]`` (entries with ``module`` are module instances; others with ``conn`` are
  plain parts that can satisfy ``requires[]``), ``options``: the project's options (``rails``, ``rail_limits``,
  ``logic_v``), ``devkit``: board id or None.
- ``catalog``: duck-typed ``has(id)`` / ``get(id, variant)`` (-> entry with ``_class``), optional ``resolve_id``
  and ``sources`` ({id: {..., "class"}}); None = ``modules.catalog()``. If that fails (not built, broken data),
  every module counts as unknown (finding ``mod.unknown``), never a crash.
- ``electrical``: a Mapping = {chip: values} or the values themselves (shape of ``electrical.get``), or an object
  with ``get(chip)`` and optionally ``boards()``; None = the ``electrical`` module. Errors -> ``Ctx.esp = None``.

Net model: an assignment sits on net ``net`` or, without one, ``GPIO<pin>``; module pins sit on
``conn[pin]`` or their ``tie`` (resolved against the instance: ``"VDD"`` = the net of the module's VDD pin);
``"GND"``, ``"3V3"``, ``"5V"`` and ``options.rails`` names are rails with a known voltage. ``GPIO<n>`` in ``conn``
means the net of the assignment on pin n (its ``net`` if set). An I²C bus = the SDA net of an ``i2c_sda``
assignment plus the SCL net of an ``i2c_scl`` assignment on the same chip bus; devices join a bus through their
``i2c_sda`` pin's net. Mux channels (``interfaces[].mux_channels``) open sub-segments: segment id
``"<mux ref>.<channel>"``; ``Ctx.visible(seg_a, seg_b)`` says whether devices on two segments can collide.

Resolution details:
- A ``conn``/``tie`` value is, in this order: ``GPIO<n>`` (net of the first assignment on GPIO n, else the net
  ``GPIO<n>``), a rail name (fixed rails win over ``options.rails``), the name of one of the module's own
  ``supply``/``gnd`` pins (-> that pin's net; a cycle ends at the literal name), the role of an assignment (-> its
  net; not when the name is itself an assignment's net), else a literal net name. Plain parts: same without tie.
- Address in effect (``Instance.address``, origin in ``Instance.address_from``): ``"explicit"`` = ``parts[].address``;
  ``"select"`` = the net of ``select.pin`` equals the net a ``select.map`` key stands for (several pins: ``select.pins``
  and comma-separated keys, one target per pin, all must match). A map key that names one of
  the module's pins stands for that pin's net (``"VDDIO"``, ``"SDA"``); any other key is a net / rail name
  (``"GND"``). Second pass: two rails with the same known voltage > 0 V match. ``"default"`` = ``default`` (else the
  first of ``addresses``) when the select pin is open or matches no key. No I²C interface -> None.
- SCL pairing of a bus: most devices with SDA on the bus and SCL on an ``i2c_scl`` net; tie -> the name with
  SDA replaced by SCL; else the SCL assignment at the same position.
- ``mux_channels``: ``[{"channel": "0", "sda": "SD0", "scl": "SC0"}, …]`` (also accepted: ``{"0": {"sda", "scl"}}``
  or ``{"0": ["SD0", "SC0"]}``; pin names of the mux). Devices whose SDA net is the channel's SDA net sit on segment
  ``"<mux ref>.<channel>"``; nested muxes nest segments. ``visible``: same segment, or one is an ancestor of the
  other (``main`` sees all); two different channels never see each other.
- Rails (result ``rails``): every supply net of a module instance and every net with a limit, without GND. Current
  per instance from ``current`` (``supply`` pin, else its first supply pin) × ``qty``: ``i_typ`` = Σ typ,
  ``i_max`` = Σ max, ``i_peak`` = Σ (peak, else max); ``missing`` = refs on the rail without ``max``.
  ``limit``: ``options.rail_limits`` (``limit_source`` "user"), for 3V3 else the DevKit value from
  ``electrical.boards()`` (``limit_source`` = its source id).

Severity cap: ``Ctx.cap(severity, inst, source_id=None)`` lowers a severity by the source class (B ->
info) and, for ``kind == "module"`` facts outside the bare chip (supply/level on a breakout without
``facts.regulator == "none"``), to ``caution``. Rules call it for every finding they build from module data.
Details: the class is that of ``source_id`` (catalog ``sources``, else ``sources.all_sources()``), else the entry's
``_class``; unknown -> treated as B. ``chip_fact=False`` = the finding does not depend on the board (no breakout
cap). ``supply=True`` marks a supply finding: ``facts.regulator == "3V3"`` then caps to info. ``Ctx.finding(...)``
applies the cap and appends the standard reason text (e.g. "confirm the breakout's regulator").

Output of ``run``: ``ModReport`` with
- ``result``: {"buses": [...], "rails": [...], "counts": {"modules", "findings", "shown", "danger", "caution",
  "info"}},
- ``checks``: contracts.check(...) dicts, one per rule that produced or evaluated something
  (id ``modules.<rule without "mod.">``), status passed / failed / not_checked, plus ``refs`` and ``source_ids``.
  failed = at least one failed finding with severity caution/danger; else not_checked = a not_checked finding or a
  failed finding capped to info; else passed. A rule returning [] adds no check.
- ``warnings``: contracts.warning(...) dicts (code ``mod_<rule without "mod.", dots -> _>``, plus ``refs``), one
  per failed / not_checked finding that has a severity, at most ``modspec.MAX_FINDINGS_SHOWN`` sorted by severity
  (danger, caution, info), then rule id, then refs,
- ``source_ids``: every source id the shown findings cite (order kept, no duplicates), then those of the checks,
- ``findings``: every Finding (tests; not part of the answer).
Without module instances ``run`` returns None and pins.check is byte-identical to before (regression test).
Compaction: ``shrink(report, level)`` (SHRINK_LEVELS) drops passed check details first, folds the passed checks into
one summary check ``modules``, then cuts warnings, texts, refs and device lists; failed / not_checked checks keep
their reason until the last levels. pins.check takes the first level whose whole envelope fits ``contracts.MAX_RESULT_BYTES`` (``result.modules.compact`` = level > 0).

Rule author API (see also tests/modkit.py): ``ctx.instances`` (Instance: ref, module_id, module, conn, address,
address_from, facts, qty), ``ctx.net_of``, ``ctx.volts``, ``ctx.supply_volts``, ``ctx.level``, ``ctx.fv``,
``ctx.src``, ``ctx.pins_with``, ``ctx.placement`` ({ref: (bus id, segment id)}), ``ctx.buses``, ``ctx.nets``,
``ctx.rail_sums``, ``ctx.esp``, ``ctx.finding``; texts via ``fmt(value, unit)``.
"""
from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any, NamedTuple

from . import modspec
from .contracts import check as mk_check
from .contracts import format_si
from .contracts import warning as mk_warning

RULES: dict[str, Callable[[Ctx], list[Finding]]] = {}

_GENERIC_ID = re.compile(r"^mod\.([a-z][a-z0-9_]{1,40})$")
_FAMILY_ID = re.compile(r"^mod\.([a-z]{2,13})\.([a-z][a-z0-9_]{1,40})$")
_GPIO_NET = re.compile(r"^GPIO(\d{1,3})$")
_PIN_TEXT = re.compile(r"^(?:gpio|io)?\s*(\d{1,3})$", re.IGNORECASE)
_ADDR_TEXT = re.compile(r"^0x([0-9a-f]{1,2})$")
_STATUSES = ("failed", "passed", "not_checked")
_HARD = ("caution", "danger")
MAX_MESSAGE_CHARS = 300  # one warning text; the whole answer stays below contracts.MAX_RESULT_BYTES
MAX_DETAIL_CHARS = 200  # one check detail
MAX_CHECK_REFS = 8
MAX_CHECK_SOURCES = 3
CAP_TEXT = {
    "unverified": "Unverified: the source is not a manufacturer document (class B).",
    "breakout_supply": "Breakout board: confirm the breakout's regulator (facts.regulator).",
    "breakout": "Breakout board: the board may differ from the chip; confirm with facts.",
    "regulator_3v3": "The breakout has a 3.3 V regulator (facts.regulator): hint only.",
}


def _valid_rule_id(rule_id: Any) -> bool:
    if not isinstance(rule_id, str):
        return False
    if _GENERIC_ID.match(rule_id):
        return True
    m = _FAMILY_ID.match(rule_id)
    return bool(m and modspec.WP_RE.match(m.group(1)))


def rule(rule_id: str) -> Callable[[Callable[[Ctx], list[Finding]]], Callable[[Ctx], list[Finding]]]:
    """Register a rule. ``rule_id`` = ``mod.<name>`` or ``mod.<family>.<name>``; a duplicate id raises ValueError."""
    if not _valid_rule_id(rule_id):
        raise ValueError(f"bad rule id {rule_id!r}: expected mod.<name> or mod.<wp>.<name> (lower case)")
    if rule_id in RULES:
        raise ValueError(f"duplicate rule id {rule_id!r}")

    def deco(fn: Callable[[Ctx], list[Finding]]) -> Callable[[Ctx], list[Finding]]:
        if rule_id in RULES:
            raise ValueError(f"duplicate rule id {rule_id!r}")
        RULES[rule_id] = fn
        return fn

    return deco


def unregister(rule_id: str) -> None:
    """Remove a rule (tests only: temporary rules, see tests/modkit.temp_rule)."""
    RULES.pop(rule_id, None)


def warning_code(rule_id: str) -> str:
    return modspec.WARNING_PREFIX + rule_id[len(modspec.RULE_PREFIX):].replace(".", "_")


def check_id(rule_id: str) -> str:
    return modspec.CHECK_PREFIX + rule_id[len(modspec.RULE_PREFIX):]


def fmt(value: float | None, unit: str, digits: int = 3) -> str:
    """'3.30 V', '714 µA'; None -> 'unknown'."""
    return "unknown" if value is None else format_si(value, unit, digits)


@dataclass
class Finding:
    rule_id: str  # mod.<name> / mod.<family>.<name>
    status: str  # "failed" | "passed" | "not_checked"  (contracts.CHECK_STATUSES without "skipped")
    severity: str | None  # "info" | "caution" | "danger"; None for passed
    message: str  # English, values with units ("5.0 V on SDA, BME280 VDDIO max 3.6 V")
    refs: list[str] = field(default_factory=list)  # part refs and/or GPIO names
    source_ids: list[str] = field(default_factory=list)
    # rule ids this finding covers on the same refs (one cause -> one warning). This finding failed:
    # their failed findings on a shared ref are folded in (hidden as warnings, the strongest severity moves here).
    # This finding passed: their findings on a shared ref drop to info (e.g. relay contacts on low-voltage rails).
    # This finding is not_checked: their not_checked findings on a shared ref are folded (one open question).
    supersedes: tuple[str, ...] = ()


@dataclass
class Instance:
    ref: str
    module_id: str
    variant: str | None
    module: dict[str, Any]  # catalog entry with the variant applied (modules.Catalog.get)
    conn: dict[str, str]  # module pin -> net, ties resolved
    address: str | None  # I²C address in effect (explicit, from the select pin, or the default)
    facts: dict[str, Any]
    qty: int = 1
    address_from: str | None = None  # "explicit" | "select" | "default" | None (no I²C interface)


@dataclass
class Ctx:
    chip: str
    devkit: str | None
    esp: dict[str, Any] | None  # electrical.get(chip) or None (then level rules report not_checked)
    instances: list[Instance]
    parts: list[dict[str, Any]]  # every project part (plain parts with conn included)
    assignments: list[dict[str, Any]]  # normalised {role, mode, pin, net} with net filled ("GPIO<n>" default)
    nets: dict[str, dict[str, Any]]  # net -> {"gpios": [pin], "modes": [mode], "pins": [(ref, pin name)], "volts"}
    rails: dict[str, float]  # net -> volts (fixed rails + options.rails)
    rail_limits: dict[str, float]  # net -> A (options.rail_limits)
    buses: list[dict[str, Any]]  # result "buses" entries, segments with devices
    options: dict[str, Any] = field(default_factory=dict)
    unknown: list[dict[str, Any]] = field(default_factory=list)  # [{ref, module, variant}] not in the catalog
    placement: dict[str, tuple[str, str]] = field(default_factory=dict)  # ref -> (bus id, segment id)
    rail_sums: list[dict[str, Any]] = field(default_factory=list)  # result "rails" entries
    parents: dict[str, str] = field(default_factory=dict)  # segment id -> parent segment id ("main" has none)
    catalog: Any = field(default=None, repr=False)
    _classes: dict[str, str | None] = field(default_factory=dict, repr=False)

    # --- lookups ------------------------------------------------------------------------------------------------
    def instance(self, ref: str) -> Instance:
        for inst in self.instances:
            if inst.ref == ref:
                return inst
        raise KeyError(ref)

    def net_of(self, inst: Instance, pin: str) -> str | None:
        return inst.conn.get(pin)

    def volts(self, net: str | None) -> float | None:
        """Voltage of a rail net, or None for a signal net / unknown net."""
        return None if net is None else self.rails.get(net)

    def supply_volts(self, inst: Instance) -> dict[str, float]:
        """{supply pin name: volts} for the instance's supply pins on known rails."""
        names = [p["name"] for p in _pins(inst.module) if p.get("signal") == "supply"]
        names += [k for k in (inst.module.get("supplies") or {}) if k not in names]
        out = {}
        for name in names:
            v = self.volts(inst.conn.get(name))
            if v is not None:
                out[name] = v
        return out

    def level(self, inst: Instance, key: str) -> float | None:
        """io[key] of the instance resolved to volts (modules.value with supply_volts); None if not given."""
        io = inst.module.get("io")
        f = io.get(key) if isinstance(io, Mapping) else None
        sv = self.supply_volts(inst)
        if isinstance(io, Mapping) and "domain_v" in io and not modspec.domain_v_problems(dict(io)):
            # fixed internal I/O voltage (e.g. SIM800L 2.8 V): io values relative to the domain use it
            sv = {**sv, str(io.get("domain") or "VDD"): float(io["domain_v"]["value"])}
        return fvalue(f, sv)

    def fv(self, f: Any, inst: Instance | None = None) -> float | None:
        """A cited number F resolved to a float (``rel``/``rel_offset`` against the instance's supplies)."""
        return fvalue(f, self.supply_volts(inst) if inst is not None else {})

    def src(self, inst: Instance, f: Any = None) -> str | None:
        """Source id of an F (its ``source_id``), else the module's first source."""
        if isinstance(f, Mapping) and isinstance(f.get("source_id"), str):
            return f["source_id"]
        ids = inst.module.get("source_ids") or []
        return ids[0] if ids and isinstance(ids[0], str) else None

    def pins_with(self, inst: Instance, signal: str) -> list[str]:
        """Names of the instance's pins with ``signal`` (data order)."""
        return [p["name"] for p in _pins(inst.module) if p.get("signal") == signal]

    def label(self, inst: Instance) -> str:
        return f"{inst.ref} ({inst.module_id})"

    def visible(self, seg_a: str, seg_b: str) -> bool:
        """Devices on two segments of one bus can collide: same segment, or one is an ancestor of the other."""
        if seg_a == seg_b:
            return True
        return seg_a in self._ancestors(seg_b) or seg_b in self._ancestors(seg_a)

    def _ancestors(self, seg: str) -> list[str]:
        out, cur = [], seg
        while cur != "main" and cur in self.parents and len(out) < 32:
            cur = self.parents[cur]
            out.append(cur)
        if "main" not in out and seg != "main":
            out.append("main")
        return out

    # --- severity cap -------------------------------------------------------------------------------------------
    def source_class(self, source_id: str | None, inst: Instance | None = None) -> str | None:
        if source_id:
            if source_id not in self._classes:
                self._classes[source_id] = _lookup_class(self.catalog, source_id)
            cls = self._classes[source_id]
            if cls in modspec.CLASS_MAX_SEVERITY:
                return cls
        if inst is not None and inst.module.get("_class") in modspec.CLASS_MAX_SEVERITY:
            return inst.module["_class"]
        return None

    def cap_reason(self, severity: str, inst: Instance | None, source_id: str | None = None, *,
                   chip_fact: bool = True, supply: bool = False) -> tuple[str, str | None]:
        """(capped severity, reason key of CAP_TEXT or None)."""
        rank = modspec.SEVERITY_RANK
        out, why = severity, None
        if inst is not None or source_id:
            cls = self.source_class(source_id, inst) or "B"  # unknown class: as unverified
            limit = modspec.CLASS_MAX_SEVERITY[cls]
            if rank[out] > rank[limit]:
                out, why = limit, "unverified"
        if inst is not None and chip_fact and inst.module.get("kind") == "module" \
                and inst.module.get("module_datasheet") is not True:
            reg = (inst.facts or {}).get("regulator")
            if reg != "none":
                target, tag = ("info", "regulator_3v3") if reg == "3V3" and supply else (
                    "caution", "breakout_supply" if supply else "breakout")
                if rank[out] >= rank[target]:  # equal: the finding stands, but says what to confirm
                    out, why = target, tag
        return out, why

    def cap(self, severity: str, inst: Instance | None, source_id: str | None = None, *, chip_fact: bool = True,
            supply: bool = False) -> str:
        return self.cap_reason(severity, inst, source_id, chip_fact=chip_fact, supply=supply)[0]

    def finding(self, rule_id: str, status: str, severity: str | None, message: str, inst: Any = None, *,
                source_id: Any = None, refs: Iterable[str] | None = None, source_ids: Iterable[str] | None = None,
                chip_fact: bool = True, supply: bool = False) -> Finding:
        """A Finding with the cap applied. ``inst``: Instance, list of Instances (the weakest cap wins: a finding
        is only as sure as its least sure fact) or None; ``source_id``: one id or a list aligned with ``inst``.
        refs default to the instances' refs, source_ids to the given source ids."""
        insts = [] if inst is None else list(inst) if isinstance(inst, list | tuple) else [inst]
        sids = list(source_id) if isinstance(source_id, list | tuple) else [source_id] * max(1, len(insts))
        sev, why = severity, None
        if severity is not None and status != "passed":
            rank = modspec.SEVERITY_RANK
            best: tuple[str, str | None] | None = None
            for i, it in enumerate(insts or [None]):
                s, w = self.cap_reason(severity, it, sids[i] if i < len(sids) else None, chip_fact=chip_fact,
                                       supply=supply)
                if best is None or rank[s] < rank[best[0]] or (rank[s] == rank[best[0]] and w and not best[1]):
                    best = (s, w)
            sev, why = best or (severity, None)
        if why:
            message = f"{message} {CAP_TEXT[why]}"
        return Finding(rule_id, status, sev, message,
                       list(refs) if refs is not None else [it.ref for it in insts],
                       list(source_ids) if source_ids is not None else _uniq(s for s in sids if s))


@dataclass
class ModReport:
    result: dict[str, Any]
    checks: list[dict[str, Any]]
    warnings: list[dict[str, Any]]
    source_ids: list[str]
    findings: list[Finding] = field(default_factory=list)


# --- helpers ------------------------------------------------------------------------------------------------------
def _uniq(items: Iterable[Any]) -> list[Any]:
    out: list[Any] = []
    for x in items:
        if x not in out:
            out.append(x)
    return out


def _pins(module: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    return [p for p in module.get("pins") or [] if isinstance(p, Mapping) and isinstance(p.get("name"), str)]


def _num(x: Any) -> float | None:
    if isinstance(x, bool) or not isinstance(x, int | float):
        return None
    return float(x)


def _local_value(f: Any, supplies_v: Mapping[str, float]) -> float | None:
    if not isinstance(f, Mapping):
        return _num(f)
    if "value" in f:
        return _num(f["value"])
    of = f.get("of")
    base = supplies_v.get(of) if isinstance(of, str) else None
    rel, off = _num(f.get("rel")), _num(f.get("rel_offset"))
    if rel is not None:
        return None if base is None else rel * base
    if off is not None:
        return None if base is None else base + off
    return None


def fvalue(f: Any, supplies_v: Mapping[str, float]) -> float | None:
    """modules.value (the loader's contract); the local copy of the same rule until the loader exists."""
    if f is None:
        return None
    try:
        from . import modules
        v = modules.value(f, supplies_v)
        return _num(v)
    except NotImplementedError:
        return _local_value(f, supplies_v)
    except Exception:  # noqa: BLE001 - broken data counts as missing
        return None


def norm_address(v: Any) -> str | None:
    """0x3C, '0x3c', 60 -> '0x3c'; anything else None."""
    if isinstance(v, int) and not isinstance(v, bool):
        n = v
    elif isinstance(v, str) and _ADDR_TEXT.match(v.strip().lower()):
        n = int(v.strip().lower(), 16)
    else:
        return None
    return f"0x{n:02x}" if 0 <= n < 128 else None


def addresses(iface: Mapping[str, Any]) -> list[str]:
    """``addresses`` of an I²C interface (plain list or F with a list value), normalised."""
    a = iface.get("addresses")
    if isinstance(a, Mapping):
        a = a.get("value")
    if not isinstance(a, list | tuple):
        return []
    return _uniq(x for x in (norm_address(v) for v in a) if x)


def i2c_iface(module: Mapping[str, Any]) -> dict[str, Any] | None:
    for it in module.get("interfaces") or []:
        if isinstance(it, Mapping) and it.get("type") == "i2c":
            return dict(it)
    return None


def mux_channels(iface: Mapping[str, Any] | None) -> list[tuple[str, str, str | None]]:
    """[(channel, sda pin, scl pin)] of a mux interface (formats: see module docstring)."""
    mc = (iface or {}).get("mux_channels")
    if isinstance(mc, Mapping) and "value" in mc and not isinstance(mc.get("value"), str):
        mc = mc["value"]
    rows: list[tuple[Any, Any]] = []
    if isinstance(mc, list | tuple):
        for i, x in enumerate(mc):
            if isinstance(x, Mapping):
                rows.append((x.get("channel", x.get("id", i)), x))
            else:
                rows.append((i, x))
    elif isinstance(mc, Mapping):
        rows = list(mc.items())
    out = []
    for ch, x in rows:
        if isinstance(x, Mapping):
            sda, scl = x.get("sda"), x.get("scl")
        elif isinstance(x, list | tuple) and x:
            sda, scl = x[0], x[1] if len(x) > 1 else None
        else:
            continue
        if isinstance(sda, str) and sda:
            out.append((str(ch), sda, scl if isinstance(scl, str) else None))
    return out


def _lookup_class(catalog: Any, source_id: str) -> str | None:
    srcs = getattr(catalog, "sources", None)
    if isinstance(srcs, Mapping) and isinstance(srcs.get(source_id), Mapping):
        return srcs[source_id].get("class")
    try:
        from . import sources
        return (sources.all_sources().get(source_id) or {}).get("class")
    except Exception:  # noqa: BLE001
        return None


def _default_catalog() -> Any:
    try:
        from . import modules
        return modules.catalog()
    except Exception:  # noqa: BLE001 - NotImplementedError, broken data: modules count as unknown
        return None


def _esp_values(chip: str, electrical: Any) -> dict[str, Any] | None:
    try:
        if isinstance(electrical, Mapping):  # {chip: values} or the values of this chip
            got = electrical.get(chip) if isinstance(electrical.get(chip), Mapping) else electrical
            return dict(got) if got else None
        if electrical is None:
            from . import electrical as el
            electrical = el
        got = electrical.get(chip)
        return dict(got) if isinstance(got, Mapping) else None
    except Exception:  # noqa: BLE001 - no data yet: level rules report not_checked
        return None


def _board_limit(devkit: str | None, electrical: Any) -> tuple[float, str | None] | None:
    if not devkit or isinstance(electrical, Mapping):
        return None
    try:
        if electrical is None:
            from . import electrical as el
            electrical = el
        f = (electrical.boards().get(devkit) or {}).get("rail_3v3_limit")
    except Exception:  # noqa: BLE001
        return None
    v = fvalue(f, {})
    if v is None:
        return None
    return v, f.get("source_id") if isinstance(f, Mapping) else None


def _norm_assignments(assignments: Any) -> list[dict[str, Any]]:
    out = []
    for a in assignments or []:
        if not isinstance(a, Mapping):
            continue
        pin = a.get("pin")
        m = _PIN_TEXT.match(pin.strip()) if isinstance(pin, str) else None
        if m:
            pin = int(m.group(1))
        if isinstance(pin, bool) or not isinstance(pin, int):
            continue
        net = a.get("net")
        net = net.strip() if isinstance(net, str) and net.strip() else f"GPIO{pin}"
        out.append({"role": a.get("role"), "mode": a.get("mode"), "pin": pin, "net": net})
    return out


def _rails(options: Mapping[str, Any]) -> dict[str, float]:
    rails = dict(modspec.FIXED_RAILS)
    extra = options.get("rails")
    if isinstance(extra, Mapping):
        for net, v in extra.items():
            n = _num(v)
            if isinstance(net, str) and net not in rails and n is not None and 0 <= n <= modspec.MAX_RAIL_V:
                rails[net] = n
    return rails


def _rail_limits(options: Mapping[str, Any]) -> dict[str, float]:
    out = {}
    lim = options.get("rail_limits")
    if isinstance(lim, Mapping):
        for net, v in lim.items():
            n = _num(v)
            if isinstance(net, str) and n is not None and n > 0:
                out[net] = n
    return out


class _Resolver:
    """conn/tie of one instance -> {pin: net} (rules in the module docstring)."""

    def __init__(self, module: Mapping[str, Any], conn: Mapping[str, Any], rails: Mapping[str, float],
                 pin_net: Mapping[int, str], role_net: Mapping[str, str] | None = None):
        self.pins = {p["name"]: p for p in _pins(module)}
        self.power = {n for n, p in self.pins.items() if p.get("signal") in ("supply", "gnd")}
        self.conn = {k: v for k, v in conn.items() if isinstance(k, str)}
        self.rails, self.pin_net, self.role_net = rails, pin_net, role_net or {}

    @staticmethod
    def roles(items: list[dict[str, Any]]) -> dict[str, str]:
        """role -> net of its assignment (``net``, else ``GPIO<pin>``): a conn value that names a role sits on that
        assignment's net (net convention: one net per signal line; without ``net`` the role name is the net). A
        role name that is also the net of some assignment stays that net."""
        nets = {a["net"] for a in items}
        out: dict[str, str] = {}
        for a in items:
            r = a.get("role")
            if isinstance(r, str) and r.strip() and r.strip() not in nets:
                out.setdefault(r.strip(), a["net"])
        return out

    @staticmethod
    def signal(v: str, rails: Mapping[str, float], pin_net: Mapping[int, str], role_net: Mapping[str, str]) -> str:
        """``GPIO<n>`` -> net of the assignment on pin n; a rail stays; a role name -> its assignment's net."""
        m = _GPIO_NET.match(v)
        if m:
            return pin_net.get(int(m.group(1)), v)
        if v in rails:
            return v
        return role_net.get(v, v)

    def value(self, v: Any, seen: frozenset[str]) -> str | None:
        if not isinstance(v, str) or not v.strip():
            return None
        v = v.strip()
        if _GPIO_NET.match(v) or v in self.rails:
            return self.signal(v, self.rails, self.pin_net, self.role_net)
        if v in self.power:
            return v if v in seen else self.pin(v, seen)
        return self.signal(v, self.rails, self.pin_net, self.role_net)

    def pin(self, name: str, seen: frozenset[str] = frozenset()) -> str | None:
        seen = seen | {name}
        if name in self.conn:
            return self.value(self.conn[name], seen)
        tie = self.pins.get(name, {}).get("tie")
        return self.value(tie, seen) if isinstance(tie, str) else None

    def all(self) -> dict[str, str]:
        out = {}
        for name in self.pins:
            net = self.pin(name)
            if net is not None:
                out[name] = net
        return out


def _address(inst: Instance, iface: Mapping[str, Any] | None, explicit: Any, rails: Mapping[str, float]
             ) -> tuple[str | None, str | None]:
    if iface is None:
        return None, None
    a = norm_address(explicit)
    if a:
        return a, "explicit"
    sel = iface.get("select")
    if isinstance(sel, Mapping) and isinstance(sel.get("map"), Mapping):
        multi = isinstance(sel.get("pins"), list)
        sel_pins = [x for x in sel["pins"] if isinstance(x, str)] if multi else (
            [sel["pin"]] if isinstance(sel.get("pin"), str) else [])
        nets = [inst.conn.get(sp) for sp in sel_pins]
        if sel_pins and all(n is not None for n in nets):
            names = {p["name"] for p in _pins(inst.module)}

            def knet_of(key: str) -> str | None:
                knet = inst.conn.get(key) if key in names else None
                if knet is None and (key not in names or key in rails):
                    knet = key
                return knet

            def same(knet: str | None, net: str, loose: bool) -> bool:
                if knet == net:
                    return True
                v = rails.get(net)
                return loose and bool(v) and knet in rails and abs(rails[knet] - v) < 1e-9

            keyed = []
            for key, addr in sel["map"].items():
                keys = key.split(",") if multi and isinstance(key, str) else [key]
                if len(keys) == len(nets):
                    keyed.append(([knet_of(k.strip()) for k in keys], norm_address(addr)))
            for loose in (False, True):  # exact nets first, then rails with the same voltage
                for knets, addr in keyed:
                    if addr and all(same(k, n, loose) for k, n in zip(knets, nets, strict=True)):
                        return addr, "select"
    d = norm_address(iface.get("default")) or next(iter(addresses(iface)), None)
    return d, "default" if d else None


def _pair_scl(sda: str, scl_nets: list[str], idx: int, devs: list[tuple[Instance, str | None]]) -> str | None:
    votes: dict[str, int] = {}
    for _, scl in devs:
        if scl in scl_nets:
            votes[scl] = votes.get(scl, 0) + 1
    if votes:
        best = max(votes.values())
        top = [n for n in scl_nets if votes.get(n) == best]
        if len(top) == 1:
            return top[0]
        scl_nets = top
    for a, b in (("SDA", "SCL"), ("sda", "scl"), ("SD", "SC")):
        if a in sda and sda.replace(a, b) in scl_nets:
            return sda.replace(a, b)
    if votes:
        return scl_nets[0]
    return scl_nets[idx] if idx < len(scl_nets) else (scl_nets[0] if len(scl_nets) == 1 else None)


def _f_hz(module: Mapping[str, Any]) -> float | None:
    it = i2c_iface(module)
    return fvalue(it.get("f_max_hz"), {}) if it else None


def _buses(instances: list[Instance], items: list[dict[str, Any]]
           ) -> tuple[list[dict[str, Any]], dict[str, tuple[str, str]], dict[str, str]]:
    sda_nets = _uniq(a["net"] for a in items if a["mode"] == "i2c_sda")
    scl_nets = _uniq(a["net"] for a in items if a["mode"] == "i2c_scl")
    pin_of = {}
    for a in items:
        pin_of.setdefault((a["mode"], a["net"]), a["pin"])
    lines: dict[str, tuple[str | None, str | None]] = {}
    for inst in instances:
        sda = next((p["name"] for p in _pins(inst.module) if p.get("signal") == "i2c_sda"), None)
        scl = next((p["name"] for p in _pins(inst.module) if p.get("signal") == "i2c_scl"), None)
        lines[inst.ref] = (inst.conn.get(sda) if sda else None, inst.conn.get(scl) if scl else None)
    placed: dict[str, tuple[str, str]] = {}
    parents: dict[str, str] = {}
    buses = []
    for idx, sda in enumerate(sda_nets):
        bus_id = f"i2c:{sda}"
        devs = [(i, lines[i.ref][1]) for i in instances if lines[i.ref][0] == sda]
        scl = _pair_scl(sda, scl_nets, idx, devs)
        segments = []
        queue: list[tuple[str, str, str | None]] = [("main", sda, None)]
        seen_nets = {sda}
        while queue:
            seg_id, net, parent = queue.pop(0)
            members = [i for i in instances if lines[i.ref][0] == net and i.ref not in placed]
            seg: dict[str, Any] = {"id": seg_id}
            if parent is not None:
                seg["parent"] = parent
                parents[seg_id] = parent
            seg["devices"] = [{"ref": i.ref, "module": i.module_id, "address": i.address} for i in members]
            segments.append(seg)
            for i in members:
                placed[i.ref] = (bus_id, seg_id)
            for i in members:
                for ch, ch_sda, _ in mux_channels(i2c_iface(i.module)):
                    ch_net = i.conn.get(ch_sda)
                    if ch_net and ch_net not in seen_nets:
                        seen_nets.add(ch_net)
                        queue.append((f"{i.ref}.{ch}", ch_net, seg_id))
        on_bus = [i for i in instances if placed.get(i.ref, ("",))[0] == bus_id]
        hz = [h for h in (_f_hz(i.module) for i in on_bus) if h]
        buses.append({"id": bus_id, "type": "i2c",
                      "gpios": {"SDA": pin_of.get(("i2c_sda", sda)),
                                "SCL": pin_of.get(("i2c_scl", scl)) if scl else None},
                      "nets": {"SDA": sda, "SCL": scl}, "segments": segments,
                      "f_max_hz": int(min(hz)) if hz else None})
    return buses, placed, parents


def _round(x: float | None) -> float | None:
    return None if x is None else float(f"{x:.6g}")


def _rail_sums(ctx: Ctx, board_limit: tuple[float, str | None] | None) -> list[dict[str, Any]]:
    from .modrules import elec  # lazy: the rule file imports this module
    sums: dict[str, dict[str, Any]] = {}

    def entry(net: str) -> dict[str, Any]:
        if net not in sums:
            sums[net] = {"net": net, "volts": ctx.rails.get(net), "i_typ": None, "i_max": None, "i_peak": None,
                         "limit": None, "limit_source": None, "missing": []}
        return sums[net]

    def add(e: dict[str, Any], key: str, v: float | None) -> None:
        if v is not None:
            e[key] = (e[key] or 0.0) + v

    for inst in ctx.instances:
        supply_pins = ctx.pins_with(inst, "supply")
        for name in supply_pins:
            net = inst.conn.get(name)
            if net and net != "GND":
                entry(net)
        d = elec.instance_draw(ctx, inst)  # same draw as mod.power_budget: facts.i_max, peak counts
        net = d["net"]
        if not net or net == "GND" or not elec._consumer(inst, net):
            continue
        e = entry(net)
        f = elec.floored(d)  # max never below typ (lower bound, part stays in missing)
        add(e, "i_typ", f["typ"])
        add(e, "i_max", f["max"])
        add(e, "i_peak", f["peak"])
        if d["max"] is None and d["peak"] is None:
            e["missing"].append(inst.ref)
    for net in ctx.rail_limits:
        entry(net)
    out = []
    for net in sorted(sums, key=lambda n: (ctx.rails.get(n) is None, -(ctx.rails.get(n) or 0.0), n)):
        e = sums[net]
        for k in ("i_typ", "i_max", "i_peak"):
            e[k] = _round(e[k])
        if net in ctx.rail_limits:
            e["limit"], e["limit_source"] = ctx.rail_limits[net], "user"
        elif net == "3V3" and board_limit is not None:
            e["limit"], e["limit_source"] = board_limit
        if not e["missing"]:
            del e["missing"]
        out.append(e)
    return out


# --- context ------------------------------------------------------------------------------------------------------
def build_ctx(*, chip: str, assignments: list[Mapping[str, Any]], parts: list[Mapping[str, Any]],
              options: Mapping[str, Any] | None = None, devkit: str | None = None, catalog: Any = None,
              electrical: Any = None) -> Ctx | None:
    """The Ctx for the rules, or None when no part names a module."""
    parts_l = [dict(p) for p in parts or [] if isinstance(p, Mapping)]
    mod_parts = [p for p in parts_l if isinstance(p.get("module"), str) and p["module"].strip()]
    if not mod_parts:
        return None
    opts = dict(options) if isinstance(options, Mapping) else {}
    cat = catalog if catalog is not None else _default_catalog()
    rails = _rails(opts)
    items = _norm_assignments(assignments)
    pin_net: dict[int, str] = {}
    for a in items:
        pin_net.setdefault(a["pin"], a["net"])
    role_net = _Resolver.roles(items)

    instances: list[Instance] = []
    unknown: list[dict[str, Any]] = []
    for n, p in enumerate(mod_parts):
        raw_ref = p.get("ref")
        ref = raw_ref if isinstance(raw_ref, str) and raw_ref else f"U{n + 1}"
        mid = p["module"].strip()
        variant = p.get("variant") if isinstance(p.get("variant"), str) else None
        entry = None
        try:
            if cat is not None and cat.has(mid):
                entry = cat.get(mid, variant)
        except Exception:  # noqa: BLE001 - unknown variant, broken entry
            entry = None
        if not isinstance(entry, Mapping):
            unknown.append({"ref": ref, "module": mid, "variant": variant})
            continue
        entry = dict(entry)
        try:
            resolved = cat.resolve_id(mid) if hasattr(cat, "resolve_id") else entry.get("id", mid)
        except Exception:  # noqa: BLE001
            resolved = entry.get("id", mid)
        raw_conn, raw_qty = p.get("conn"), p.get("qty")
        conn: Mapping[str, Any] = raw_conn if isinstance(raw_conn, Mapping) else {}
        qty = raw_qty if isinstance(raw_qty, int) and not isinstance(raw_qty, bool) else 1
        inst = Instance(ref=ref, module_id=str(resolved or mid), variant=variant, module=entry,
                        conn=_Resolver(entry, conn, rails, pin_net, role_net).all(), address=None,
                        facts=dict(p["facts"]) if isinstance(p.get("facts"), Mapping) else {}, qty=max(1, qty))
        inst.address, inst.address_from = _address(inst, i2c_iface(entry), p.get("address"), rails)
        instances.append(inst)

    nets: dict[str, dict[str, Any]] = {}

    def net(name: str) -> dict[str, Any]:
        if name not in nets:
            nets[name] = {"gpios": [], "modes": [], "pins": [], "volts": rails.get(name)}
        return nets[name]

    for a in items:
        net(a["net"])["gpios"].append(a["pin"])
        net(a["net"])["modes"].append(a["mode"])
    for inst in instances:
        for pin, name in inst.conn.items():
            net(name)["pins"].append((inst.ref, pin))
    for p in parts_l:
        if p in mod_parts or not isinstance(p.get("conn"), Mapping) or not isinstance(p.get("ref"), str):
            continue
        for pin, v in p["conn"].items():
            if isinstance(v, str) and v.strip():
                net(_Resolver.signal(v.strip(), rails, pin_net, role_net))["pins"].append((p["ref"], str(pin)))

    buses, placed, parents = _buses(instances, items)
    ctx = Ctx(chip=chip, devkit=devkit, esp=_esp_values(chip, electrical), instances=instances, parts=parts_l,
              assignments=items, nets=nets, rails=rails, rail_limits=_rail_limits(opts), buses=buses, options=opts,
              unknown=unknown, placement=placed, parents=parents, catalog=cat)
    ctx.rail_sums = _rail_sums(ctx, _board_limit(devkit, electrical))
    return ctx


# --- engine rule: modules missing from the catalog ----------------------------------------------------------------
@rule("mod.unknown")
def _rule_unknown(ctx: Ctx) -> list[Finding]:
    out = []
    for u in ctx.unknown:
        what = f"module {u['module']}" + (f" variant {u['variant']}" if u["variant"] else "")
        out.append(Finding("mod.unknown", "failed", "caution",
                           f"{u['ref']}: {what} is not in the catalog; its pins are not checked. List modules with "
                           f"bench_pins action=modules.", [u["ref"]]))
    return out


# --- run ----------------------------------------------------------------------------------------------------------
def _clip(text: str, n: int) -> str:
    return text if len(text) <= n else text[: n - 1] + "…"


def _validated(rule_id: str, out: Any) -> list[Finding]:
    if not isinstance(out, list | tuple):
        raise TypeError(f"rule returned {type(out).__name__}, expected a list of Finding")
    res = []
    for f in out:
        if not isinstance(f, Finding):
            raise TypeError(f"rule returned {type(f).__name__}, expected Finding")
        if f.status not in _STATUSES:
            raise ValueError(f"bad status {f.status!r}")
        if f.severity is not None and f.severity not in modspec.SEVERITY_RANK:
            raise ValueError(f"bad severity {f.severity!r}")
        if f.status == "failed" and f.severity is None:
            raise ValueError("a failed finding needs a severity")
        res.append(Finding(rule_id, f.status, f.severity, str(f.message), [str(r) for r in f.refs],
                           [s for s in f.source_ids if isinstance(s, str)],
                           tuple(str(x) for x in f.supersedes if x != rule_id)))
    return res


def _apply_supersedes(by_rule: dict[str, list[Finding]]) -> set[int]:
    """Fold findings that another rule covers (Finding.supersedes). Returns the ids of the covered findings (kept
    in checks and ``findings``, never shown as warnings); mutates severities in place."""
    covered: set[int] = set()
    for fs in list(by_rule.values()):
        for f in fs:
            if not f.supersedes:
                continue
            mine = set(f.refs)
            for rid in f.supersedes:
                for g in by_rule.get(rid, []):
                    if id(g) in covered or not mine & set(g.refs) or g.status == "passed":
                        continue
                    if f.status == "not_checked" and g.status == "not_checked":  # same open question once
                        f.source_ids = _uniq([*f.source_ids, *g.source_ids])
                        covered.add(id(g))
                    elif f.status == "failed":
                        if modspec.SEVERITY_RANK[g.severity or "info"] > modspec.SEVERITY_RANK[f.severity or "info"]:
                            f.severity = g.severity
                        f.source_ids = _uniq([*f.source_ids, *g.source_ids])
                        covered.add(id(g))
                    elif f.status == "passed" and g.severity in _HARD:
                        g.severity = "info"
    return covered


def _check_of(rule_id: str, fs: list[Finding]) -> dict[str, Any]:
    hard = [f for f in fs if f.status == "failed" and f.severity in _HARD]
    open_ = [f for f in fs if f.status == "not_checked" or (f.status == "failed" and f not in hard)]
    status, pick = ("failed", hard) if hard else ("not_checked", open_) if open_ else ("passed", fs)
    # the strongest reason first: the detail is clipped from the end
    pick = sorted(pick, key=lambda f: -modspec.SEVERITY_RANK.get(f.severity or "", -1))
    texts = _uniq(f.message for f in pick)
    detail = texts[0] if len(texts) == 1 else f"{len(pick)} findings: " + "; ".join(t.rstrip(".") for t in texts)
    c = mk_check(check_id(rule_id), status, _clip(detail, MAX_DETAIL_CHARS))
    c["refs"] = _uniq(r for f in pick for r in f.refs)[:MAX_CHECK_REFS]
    c["source_ids"] = _uniq(s for f in pick for s in f.source_ids)[:MAX_CHECK_SOURCES]
    return c


def findings_of(by_rule: Mapping[str, list[Finding]], covered: set[int], fs: list[Finding]) -> list[Finding]:
    """The findings that cover any of ``fs`` (for the check detail "covered by …")."""
    mine = [g for g in fs if id(g) in covered]
    if not mine:
        return []
    rid = mine[0].rule_id
    return [f for lst in by_rule.values() for f in lst if rid in f.supersedes and f.status == "failed"
            and any(set(f.refs) & set(g.refs) for g in mine)]


def _sort_key(f: Finding) -> tuple[Any, ...]:
    return (-modspec.SEVERITY_RANK[f.severity or "info"], f.rule_id, tuple(f.refs), f.message)


def run(*, chip: str, assignments: list[Mapping[str, Any]], parts: list[Mapping[str, Any]],
        options: Mapping[str, Any] | None = None, devkit: str | None = None, catalog: Any = None,
        electrical: Any = None, only: tuple[str, ...] | None = None) -> ModReport | None:
    """Run every registered rule (or the ids in ``only``); a rule that raises is reported as not_checked
    ("rule error: …"), never as a crash."""
    ctx = build_ctx(chip=chip, assignments=assignments, parts=parts, options=options, devkit=devkit,
                    catalog=catalog, electrical=electrical)
    if ctx is None:
        return None
    from . import modrules as _modrules
    modrules: Any = _modrules
    modrules.load()
    ids = [r for r in sorted(RULES) if only is None or r in only]
    findings: list[Finding] = []
    checks: list[dict[str, Any]] = []
    for name, err in sorted(modrules.LOAD_ERRORS.items()):
        checks.append(mk_check(modspec.CHECK_PREFIX + "rules", "not_checked",
                               _clip(f"rule file {name} failed to load: {err}", MAX_DETAIL_CHARS)))
    by_rule: dict[str, list[Finding]] = {}
    for rid in ids:
        try:
            fs = _validated(rid, RULES[rid](ctx))
        except Exception as e:  # noqa: BLE001 - a broken rule must not break pins.check
            fs = [Finding(rid, "not_checked", None, _clip(f"rule error: {type(e).__name__}: {e}", 160))]
        if fs:
            by_rule[rid] = fs
    covered = _apply_supersedes(by_rule)
    for rid, fs in by_rule.items():
        findings += fs
        c = _check_of(rid, fs)
        by = _uniq(warning_code(f.rule_id) for f in findings_of(by_rule, covered, fs))
        if by and all(id(f) in covered for f in fs if f.status != "passed"):
            c["detail"] = _clip(f"covered by {', '.join(by)}", MAX_DETAIL_CHARS)
        checks.append(c)
    eligible = sorted((f for f in findings if f.status in ("failed", "not_checked") and f.severity
                       and id(f) not in covered), key=_sort_key)
    shown = eligible[: modspec.MAX_FINDINGS_SHOWN]
    warnings = []
    for f in shown:
        w = mk_warning(warning_code(f.rule_id), f.severity or "info", _clip(f.message, MAX_MESSAGE_CHARS),
                       _uniq(f.source_ids))
        w["refs"] = list(f.refs)
        warnings.append(w)
    source_ids = _uniq([s for w in warnings for s in w["source_ids"]] + [s for c in checks for s in
                                                                           c.get("source_ids", [])])
    counts = {"modules": len(ctx.instances) + len(ctx.unknown), "findings": len(eligible), "shown": len(shown)}
    for sev in ("danger", "caution", "info"):
        counts[sev] = sum(f.severity == sev for f in eligible)
    result = {"buses": ctx.buses, "rails": ctx.rail_sums, "counts": counts}
    return ModReport(result=result, checks=checks, warnings=warnings, source_ids=source_ids, findings=findings)


# --- compaction (the whole pins.check answer stays below contracts.MAX_RESULT_BYTES) -------------------------------
class ShrinkLevel(NamedTuple):
    """One compaction level. ``passed``: what passed checks keep ("detail" clipped to ``detail``, "bare" = no
    detail, "fold" = one summary check ``modules``); ``fold``: the statuses of the other checks that go into the
    summary too (only on the last levels). failed / not_checked checks keep their own detail up to ``detail``; from
    the first "fold" level a check whose reason is a shown warning folds as well (the warning carries the text)."""
    shown: int  # warnings shown (every danger stays)
    message: int  # characters per warning text
    detail: int  # characters per failed / not_checked check detail
    refs: int  # refs per check
    devices: int | None  # devices listed per bus segment (None = all)
    passed: str  # "detail" | "bare" | "fold"
    fold: tuple[str, ...] = ()  # further statuses folded into the summary check


# the reasons (failed / not_checked details) stay longest: passed details go first, then the passed checks fold
# into one summary line, then warnings and texts shrink; only the last levels fold the open checks
SHRINK_LEVELS: tuple[ShrinkLevel, ...] = (
    ShrinkLevel(modspec.MAX_FINDINGS_SHOWN, MAX_MESSAGE_CHARS, MAX_DETAIL_CHARS, MAX_CHECK_REFS, None, "detail"),
    ShrinkLevel(modspec.MAX_FINDINGS_SHOWN, MAX_MESSAGE_CHARS, MAX_DETAIL_CHARS, 6, None, "bare"),
    ShrinkLevel(modspec.MAX_FINDINGS_SHOWN, MAX_MESSAGE_CHARS, MAX_DETAIL_CHARS, 4, None, "fold"),
    ShrinkLevel(modspec.MAX_FINDINGS_SHOWN, 220, 160, 4, 16, "fold"),
    ShrinkLevel(modspec.MAX_FINDINGS_SHOWN, 180, 120, 3, 8, "fold"),
    ShrinkLevel(10, 160, 100, 2, 4, "fold"),
    ShrinkLevel(8, 140, 80, 2, 0, "fold"),
    ShrinkLevel(6, 120, 80, 1, 0, "fold"),
    ShrinkLevel(4, 100, 60, 1, 0, "fold", ("not_checked",)),
    ShrinkLevel(1, 90, 40, 0, 0, "fold", ("not_checked", "failed")),  # last resort: buses and rails drop to counts
)
MAX_HIDDEN_LISTED = 12  # result.counts.hidden: "<code> <refs>" of findings cut by the compaction, dangers first


def _summary_check(folded: list[dict[str, Any]]) -> dict[str, Any]:
    """One check ``modules`` for the folded module checks: worst status, ids grouped by status."""
    groups = {st: [c["id"][len(modspec.CHECK_PREFIX):] for c in folded if c["status"] == st]
              for st in ("failed", "not_checked", "passed")}
    status = "failed" if groups["failed"] else "not_checked" if groups["not_checked"] else "passed"
    detail = "; ".join(f"{st.replace('_', ' ')}: {', '.join(ids)}" for st, ids in groups.items() if ids)
    return {"id": "modules", "status": status, "detail": detail}


def shrink(report: ModReport, level: int) -> ModReport:
    """A smaller copy of ``report`` (level 0 = unchanged; see SHRINK_LEVELS). From level 1 the checks cite only the
    sources of the shown warnings; ``result.compact`` = the level used, ``counts.shown`` stays true, segments that
    list fewer devices than they hold carry ``more`` (the number left out). Passed checks lose their detail first and
    then fold into one summary check ``modules``; failed / not_checked checks keep their reason (a shown warning:
    "see warning <code>") until the last levels."""
    if level <= 0:
        return report
    last = level >= len(SHRINK_LEVELS) - 1
    lv = SHRINK_LEVELS[min(level, len(SHRINK_LEVELS) - 1)]
    # every danger stays visible down to the last level (they are sorted first); cut texts, not dangers
    dangers = sum(w["severity"] == "danger" for w in report.warnings)
    n = max(lv.shown, dangers)  # pins.check drops from the end if even that is too large
    warnings = []
    for w in report.warnings[:n]:
        w = dict(w)
        w["message"] = _clip(w["message"], lv.message)
        warnings.append(w)
    hidden = [f"{w['code']} {','.join(w.get('refs') or [])}".strip() for w in report.warnings[n:]]
    keep = _uniq(sid for w in warnings for sid in w["source_ids"])
    shown = {w["code"] for w in warnings}
    checks, folded = [], []
    fold = {*lv.fold, *(("passed",) if lv.passed == "fold" else ())}
    for c in report.checks:
        c = dict(c)
        is_mod = c["id"].startswith(modspec.CHECK_PREFIX)
        code = warning_code("mod." + c["id"][len(modspec.CHECK_PREFIX):]) if is_mod else None
        pointer = code in shown and c["status"] != "passed"  # the shown warning carries the reason
        if is_mod and (c["status"] in fold or (pointer and lv.passed == "fold")):
            folded.append(c)
            continue
        if c["status"] == "passed" and lv.passed == "bare":
            c["detail"] = ""
        elif pointer:  # its check only points to it
            c["detail"] = f"see warning {code}"
            c.pop("source_ids", None)  # the warning cites them
        else:
            c["detail"] = _clip(c["detail"], lv.detail)
        if "refs" in c:
            c["refs"] = c["refs"][:lv.refs]
        if "source_ids" in c:
            c["source_ids"] = [sid for sid in c["source_ids"] if sid in keep]
        checks.append(c)
    if folded:  # one summary line instead of one check per rule
        checks.append(_summary_check(folded))
    result = dict(report.result)
    result["counts"] = {**result["counts"], "shown": len(warnings)}
    if hidden:
        result["counts"]["hidden"] = hidden[:MAX_HIDDEN_LISTED]
    devs = lv.devices
    if last:  # the warnings carry what matters; bus and rail details are in the full report (desktop, project)
        result["buses"] = [{**{k: b[k] for k in ("id", "type", "gpios", "nets") if k in b}, "segments": [],
                            "more": sum(len(sg["devices"]) + sg.get("more", 0) for sg in b.get("segments", []))}
                           for b in result["buses"]]
        result["rails"] = [{k: r.get(k) for k in ("net", "volts", "i_max", "limit") if k in r}
                           for r in result["rails"]]
        devs = None
    if devs is not None:
        buses = []
        for b in result["buses"]:
            b = dict(b)
            segs = []
            for seg in b["segments"]:
                seg = dict(seg)
                if len(seg["devices"]) > devs:
                    seg["more"] = len(seg["devices"]) - devs
                    seg["devices"] = seg["devices"][:devs]
                segs.append(seg)
            b["segments"] = segs
            buses.append(b)
        result["buses"] = buses
    result["compact"] = level
    return ModReport(result=result, checks=checks, warnings=warnings, source_ids=keep, findings=report.findings)
