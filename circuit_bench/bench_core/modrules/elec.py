"""Generic electrical rules.

Rules (warning code; strongest severity before the severity cap):
- ``mod.supply_range`` (``mod_supply_range``): rail voltage of every ``supplies[pin]`` against min/max (caution) and
  abs_max (danger); supply pins on one net with the same verdict form one finding. A supply pin on GND is "not
  powered" (caution). A supply pin on an ESP GPIO net is no rail: not_checked (info), danger only when the module's
  abs_max lies below the ESP's VDD.
- ``mod.level_in`` (``mod_level_in``): the ESP drives a module input (``SIGNAL_DIRECTION`` "in"; on open-drain /
  I²C / 1-Wire lines the high level is the pull-up voltage, checked only when it is known). Module VIH above the
  ESP's VDD -> caution "not recognised" (a too-low level cannot damage the input, so never danger); ESP VOH < VIH <=
  VDD -> caution "outside the guaranteed levels"; ESP VOL above the module's VIL -> caution; the high level above
  the module's ``v_in_max`` -> danger. ``facts.level_shifter`` -> passed with a hint. No VIH -> not_checked (info
  when the module runs above the ESP's VDD, else silent).
- ``mod.level_out`` (``mod_level_out``): the module drives an ESP net. Push-pull high = the module's I/O domain
  voltage above the ESP's input maximum -> danger (output type not in the data -> caution); below the ESP's VIH ->
  caution. Open-drain / I²C / 1-Wire: the pull-up voltage (resistor parts between the net and a rail,
  ``facts.pullups_to``, internal pull-ups, the supply of a breakout whose pull-ups are not confirmed) above the
  ESP's input maximum -> danger; not known -> caution "confirm the pull-up voltage". ``analog_out``: the ADC range is
  not in the ESP data -> not_checked; an analog output whose supply exceeds the ESP input maximum -> caution.
- ``mod.power_budget`` (``mod_power_budget``): per rail Σ typ/max/peak (``ctx.rail_sums``) against the rail limit
  (``options.rail_limits`` / board value): max or peak above the limit -> caution; without a limit only the sums
  (not_checked without a warning). Only rails count: the currents of module signal inputs are no GPIO load. A module
  powered from a GPIO is compared with the ESP's typical source current (caution, a typical figure) and the
  cumulative IO output maximum (danger).
- ``mod.required_parts`` (``mod_required_parts``): every ``requires[]`` entry is met by a plain part of the matching
  kind whose ``conn`` touches the nets (pull-up / pull-down: resistor between the signal net and ``to``; decoupling /
  bulk_cap: capacitor between each supply net and ``to`` (GND); flyback: diode across the load nets; termination:
  resistor across them; series_resistor: resistor from the pin's net to another signal net), by another module
  (level shifter, regulator) or by ``facts`` (``pullups`` other than "none"/"unknown", ``level_shifter``,
  ``regulator`` "3V3"); else caution with value and page, info when the evidence or note calls it a recommendation.
- ``mod.hazard`` (``mod_hazard``): ``hazards[]`` per module id and code: mains, laser and li_ion -> danger (product
  safety rule, never capped by the source class; mains is never modelled as allowed), the rest ->
  caution (capped).

Severity cap: findings built from module data go through ``ctx.finding`` (class B -> info; a breakout
(``kind`` "module") without ``facts.regulator == "none"`` -> caution with the "confirm" text). Findings that rest only
on user parts / user facts and the ESP's datasheet values (a pull-up resistor to 5 V) are not capped by the module.
Values are compared as given: a value whose ``conditions`` name a supply voltage the project does not meet is not
used (not_checked), never interpolated. Behind a confirmed 3.3 V regulator (``facts.regulator == "3V3"``) the chip
side of a breakout (and of a chip entry whose board the user describes) counts as at most 3.3 V; a supply above it
that the chip would not tolerate becomes an info "behind the board regulator (user-confirmed)".

Supply conditions are read only for supply names (the module's supply pins, ``SUPPLY_WORDS``), never for
other quantities (VCE, VO, VOL), load-current test points ("IOH = -3 mA at VDD 4.5 V") or text in parentheses. A VOH
given at a load of 1 mA or more that lies below the ESP's VIH is only an info (an ESP input draws µA). ``io.domain_v``
(fixed internal I/O voltage) replaces the supply voltage in the level rules. ``facts.pullups_to`` may be a module pin
(resolved through ``conn``), a net or a number in V. An open-drain net pulled above a module input's ``v_in_max`` is
danger for every module on that net (mod.level_in). A known rail sum above the limit stays caution even when parts
lack current data; otherwise the text names the known sum and the parts without data.

Pull-ups and current budget:
- ``mod.pullup_parallel`` (``mod_pullup_parallel``): per I²C line all pull-ups in parallel (resistor parts to a rail,
  ``facts.pullups`` values of the modules on the line, valued internal pull-ups). R_eff below R_min =
  (V_pull-up − V_OL) / I_OL (calc.i2c_pullup, NXP UM10204: 0.4 V at 3 mA) -> caution "remove pull-ups"; above
  R_max for Standard-mode at the estimated C_b -> info; between the Fast- and Standard-mode R_max -> passed with a
  note. A pull-up without a value (breakout without facts.pullups, facts.onboard "pullups", "unknown") -> not_checked.
- ``mod.power_budget``: ``facts.i_max`` (user, the whole part including qty) replaces the catalog max / peak and
  is named "(user)"; a part with a peak but no max counts with its peak; only consumers without max and peak are
  named (no part that feeds the rail through power_out, no discrete part).
- ``facts.level_shifter`` counts in mod.level_out as in mod.level_in: the ESP side of the board is 3.3 V (passed,
  user-confirmed). A 5 V pull-up danger suggests only a level shifter when a module on the line needs VIH > 3.3 V.
"""
from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from typing import Any

from .. import units
from ..contracts import BenchError
from . import modcheck

Ctx, Finding, Instance, fmt, rule, fvalue = (
    modcheck.Ctx, modcheck.Finding, modcheck.Instance, modcheck.fmt, modcheck.rule, modcheck.fvalue)

_EPS = 1e-9  # volts / amps; values are compared as given, never interpolated
REGULATED_V = 3.3  # facts.regulator == "3V3": the chip side of the breakout runs at 3.3 V at most
SIGNAL_DIRECTION: Mapping[str, str] = modcheck.modspec.SIGNAL_DIRECTION
OUTPUT_TYPES: tuple[str, ...] = modcheck.modspec.OUTPUT_TYPES
RESISTOR_KINDS = frozenset({"resistor"})
CAPACITOR_KINDS = frozenset({"capacitor", "ceramic", "electrolytic", "film"})
DIODE_KINDS = frozenset({"diode"})
DANGER_HAZARDS = frozenset({"mains", "laser", "li_ion"})  # same split as tools.HAZARD_DANGER
HAZARD_TAIL = {
    "mains": "Circuit Bench covers low voltage only: never connect mains to this project.",
    "laser": "Laser: follow the laser safety rules; never look into the beam.",
    "li_ion": "Li-ion cell: use a protected cell and the specified charger; never short or overcharge it.",
}
# "only a recommendation" (info): optional / recommended / suggested, but not "the recommended value is …"
_RECOMMEND = re.compile(r"\b(optional\w*|not required|(?:recommend|suggest)\w*(?!\s+values?\b))\b", re.IGNORECASE)
_STRONG = re.compile(r"\b(?:strongly|highly)\s+recommend\w*", re.IGNORECASE)  # never only a hint
_OPTIONAL = re.compile(r"\b(optional\w*|not required)\b", re.IGNORECASE)  # bulk_cap: only these make it a hint
_GPIO_NET = re.compile(r"^GPIO(\d{1,3})$")
# supply condition of a value (volts only, never °C), read only for supply names (the module's supply pins or the
# usual supply words below): "VDDIO 1.2–3.6 V", "VCC = 4.5 V to 5.5 V", "VCC = 4.5 V", "V+ = 5 V ±10 %",
# "1.9 V < VDD < 3.6 V", "VDDIO ≥ 1.62 V". Not supply conditions: other quantities ("VCE = 2 V", "VO = 0.4 V",
# "VOL = 0.4 V"), the test point of a load current ("IOH = −3.0 mA at VDD 4.5 V") and text in parentheses (another
# row or column of the table).
_NUM = r"(\d+(?:[.,]\d+)?)"
_NAME = r"([A-Za-z][A-Za-z0-9_]*\+?)"
_COND_RANGE = re.compile(r"\b" + _NAME + r"\s*(?:=\s*)?" + _NUM + r"\s*V?\s*(?:–|—|-|to|\.\.\.?|…)\s*" + _NUM
                         + r"\s*V\b")
_COND_BETWEEN = re.compile(_NUM + r"\s*V\s*(?:<|≤|<=)\s*" + _NAME + r"\s*(?:<|≤|<=)\s*" + _NUM + r"\s*V\b")
_COND_CMP = re.compile(r"\b" + _NAME + r"\s*(≥|>=|>|≤|<=|<)\s*" + _NUM + r"\s*V\b")
_COND_EQ = re.compile(r"\b" + _NAME + r"\s*=?\s*" + _NUM + r"\s*V\b(?:\s*±\s*" + _NUM + r"\s*%)?")
_COND_LOAD_AT = re.compile(r"(?:[µu]A|mA|\bA)\s+at\s+(?:[A-Za-z][A-Za-z0-9_]*\+?\s*=?\s*)?\d+(?:[.,]\d+)?\s*V\b")
_PARENS = re.compile(r"\([^()]*\)")
# supply words a condition may use for the chip's supply when the module names its pins differently
SUPPLY_WORDS = frozenset({"VDD", "VCC", "VIO", "VDDIO", "VCCIO", "VDDI", "V+", "VBAT", "VS", "VIN", "VCCA", "VCCB",
                          "VLOGIC", "DVDD", "AVDD", "PVDD", "VDDA", "VDDD", "VM", "VSUP"})
# load current of a VOH value: "IO = -8 mA", "IOH = 8 mA", "at -2.5 mA", "2 mA output current"
_LOAD_I = re.compile(r"(\d+(?:[.,]\d+)?)\s*(mA|µA|uA)\b")
LOADED_VOH_A = 1e-3  # a VOH given at >= 1 mA load: an ESP input (µA) sees a higher level


# --- helpers ------------------------------------------------------------------------------------------------------
def _uniq(items: Iterable[Any]) -> list[Any]:
    out: list[Any] = []
    for x in items:
        if x not in out:
            out.append(x)
    return out


def _pins(inst: Instance) -> list[Mapping[str, Any]]:
    return [p for p in inst.module.get("pins") or [] if isinstance(p, Mapping) and isinstance(p.get("name"), str)]


def _io(inst: Instance) -> Mapping[str, Any]:
    io = inst.module.get("io")
    return io if isinstance(io, Mapping) else {}


def _esp_src(ctx: Ctx) -> list[str]:
    return [s for s in (ctx.esp or {}).get("source_ids") or [] if isinstance(s, str)]


def _esp_v(ctx: Ctx, key: str) -> float | None:
    v = (ctx.esp or {}).get(key)
    return float(v) if isinstance(v, int | float) and not isinstance(v, bool) else None


def _sids(*groups: Any) -> list[str]:
    out: list[str] = []
    for g in groups:
        for s in ([g] if isinstance(g, str) or g is None else g):
            if isinstance(s, str) and s and s not in out:
                out.append(s)
    return out


def _gpio_text(ctx: Ctx, net: str) -> str:
    pins = ", ".join(f"GPIO{g}" for g in _uniq((ctx.nets.get(net) or {}).get("gpios") or []))
    return f"{net} ({pins})" if pins and pins != net else net


def _esp_net(ctx: Ctx, net: str | None) -> bool:
    return bool(net) and bool((ctx.nets.get(net) or {}).get("gpios"))


def _regulated(inst: Instance) -> bool:
    """The user confirmed a 3.3 V regulator on the board (``facts.regulator``), for a breakout or a chip entry."""
    return (inst.facts or {}).get("regulator") == "3V3"


def _supply_v(ctx: Ctx, inst: Instance) -> dict[str, float]:
    """{supply pin: volts the chip sees}: the rail voltage, behind a confirmed 3.3 V regulator at most 3.3 V."""
    sv = ctx.supply_volts(inst)
    if _regulated(inst):
        sv = {k: min(v, REGULATED_V) for k, v in sv.items()}
    return sv


def _domain_v(inst: Instance) -> float | None:
    """``io.domain_v``: the fixed internal voltage of the logic pins (F with an absolute ``value`` in V); None when
    absent or invalid (``modspec.domain_v_problems``)."""
    io = _io(inst)
    if "domain_v" not in io or modcheck.modspec.domain_v_problems(dict(io)):
        return None
    return float(io["domain_v"]["value"])


def _io_sv(ctx: Ctx, inst: Instance) -> dict[str, float]:
    """Supply volts for the I/O values: with ``io.domain_v`` the domain pin stands for the internal voltage."""
    sv = _supply_v(ctx, inst)
    dvv, dom = _domain_v(inst), _io(inst).get("domain")
    if dvv is not None and isinstance(dom, str):
        sv = {**sv, dom: dvv}
    return sv


def _domain(ctx: Ctx, inst: Instance, *, internal: bool = True) -> tuple[float | None, str | None]:
    """(I/O domain volts, its name): ``io.domain_v`` (fixed internal I/O voltage), ``io.domain``, else the only
    supply voltage of the instance. ``internal=False`` skips ``io.domain_v`` (supply conditions)."""
    dvv = _domain_v(inst) if internal else None
    if dvv is not None:
        return dvv, "internal I/O"
    sv = _supply_v(ctx, inst)
    dom = _io(inst).get("domain")
    if isinstance(dom, str):
        return sv.get(dom), dom
    if len(_uniq(sv.values())) == 1:
        name = next(iter(sv))
        return sv[name], name
    return None, None


def _max_supply(ctx: Ctx, inst: Instance) -> float | None:
    sv = _supply_v(ctx, inst)
    return max(sv.values()) if sv else None


def _norm(name: str) -> str:
    return name.replace("_", "").upper()


def _strip_parens(text: str) -> str:
    for _ in range(4):  # nested parentheses: innermost first
        text, n = _PARENS.subn(" ", text)
        if not n:
            break
    return text


def _cond_ok(ctx: Ctx, inst: Instance, f: Any) -> tuple[bool, str]:
    """Does the project meet the supply condition in F's ``conditions``? (ok, reason when not). Only names of supplies
    count: the module's supply pins (``supplies``, pins with signal supply) and ``SUPPLY_WORDS`` (then the I/O domain
    voltage); text in parentheses and the supply of a load-current test point are skipped."""
    cond = f.get("conditions") if isinstance(f, Mapping) else None
    if not isinstance(cond, str) or not cond:
        return True, ""
    own = {_norm(p["name"]) for p in _pins(inst) if p.get("signal") == "supply"}
    own |= {_norm(k) for k in inst.module.get("supplies") or {} if isinstance(k, str)}
    sv = {_norm(k): v for k, v in _supply_v(ctx, inst).items()}
    dv, _ = _domain(ctx, inst, internal=False)
    miss = object()

    def volts(name: str) -> Any:
        n = _norm(name)
        if n in own:
            return sv.get(n, dv)
        return dv if n in SUPPLY_WORDS else miss

    def num(s: str) -> float:
        return float(s.replace(",", "."))

    rest = _COND_LOAD_AT.sub(" ", _strip_parens(cond))
    checks: list[tuple[str, Any, float, float]] = []  # (text, volts, lo, hi)
    for rx in (_COND_RANGE, _COND_BETWEEN, _COND_CMP, _COND_EQ):
        for m in rx.finditer(rest):
            if rx is _COND_BETWEEN:
                name, lo, hi = m.group(2), num(m.group(1)), num(m.group(3))
            elif rx is _COND_RANGE:
                name, lo, hi = m.group(1), num(m.group(2)), num(m.group(3))
            elif rx is _COND_CMP:
                name, op, x = m.group(1), m.group(2), num(m.group(3))
                lo, hi = (x, float("inf")) if op in ("≥", ">=", ">") else (float("-inf"), x)
            else:
                name, x = m.group(1), num(m.group(2))
                tol = num(m.group(3)) / 100 * x if m.group(3) else 1e-6
                lo, hi = x - tol, x + tol
            v = volts(name)
            if v is miss:
                continue
            checks.append((m.group(0).strip(), v, lo, hi))
            rest = rest.replace(m.group(0), " ")
    for text, v, lo, hi in checks:
        if v is None:
            return False, f"the value holds for {text} and the supply voltage is unknown"
        if not lo - _EPS <= v <= hi + _EPS:
            return False, f"the value holds for {text} only, the project runs at {fmt(v, 'V')}"
    return True, ""


def _level(ctx: Ctx, inst: Instance, key: str) -> tuple[float | None, Any, str]:
    """(volts, F, reason) of io[key] at the voltages the chip sees; volts None with a reason when unusable."""
    f = _io(inst).get(key)
    if f is None:
        return None, None, "not in the module data"
    ok, why = _cond_ok(ctx, inst, f)
    if not ok:
        return None, f, f"{why} (no value for this supply; never interpolated)"
    v = fvalue(f, _io_sv(ctx, inst))
    return v, f, "" if v is not None else "its supply voltage is unknown"


def _load_current(f: Any) -> float | None:
    """The largest load current (A) named in F's ``conditions`` (\"IO = -8 mA\"), None without one."""
    cond = f.get("conditions") if isinstance(f, Mapping) else None
    if not isinstance(cond, str):
        return None
    amps = [float(m.group(1).replace(",", ".")) * (1e-3 if m.group(2) == "mA" else 1e-6)
            for m in _LOAD_I.finditer(_strip_parens(cond))]
    return max(amps) if amps else None


def _output_type(inst: Instance, pin: Mapping[str, Any]) -> str | None:
    if pin.get("signal") == "open_drain_out":
        return "open_drain"
    t = pin.get("output") or _io(inst).get("outputs")
    return t if t in OUTPUT_TYPES else None


def _part_nets(ctx: Ctx, part: Mapping[str, Any]) -> list[str]:
    """Nets of a plain part's ``conn`` (``GPIO<n>`` = the net of the assignment on n)."""
    first: dict[int, str] = {}
    for a in ctx.assignments:
        first.setdefault(a["pin"], a["net"])
    out = []
    conn = part.get("conn")
    for v in (conn.values() if isinstance(conn, Mapping) else []):
        if isinstance(v, str) and v.strip():
            v = v.strip()
            m = _GPIO_NET.match(v)
            out.append(first.get(int(m.group(1)), v) if m else v)
    return out


def _plain_parts(ctx: Ctx, kinds: frozenset[str]) -> list[tuple[str, list[str]]]:
    out = []
    for p in ctx.parts:
        if isinstance(p.get("module"), str) and p["module"].strip():
            continue
        if str(p.get("kind") or "").lower() in kinds and isinstance(p.get("ref"), str):
            out.append((p["ref"], _part_nets(ctx, p)))
    return out


def _same_rail(ctx: Ctx, a: str | None, b: str | None) -> bool:
    if a is None or b is None:
        return False
    if a == b:
        return True
    va, vb = ctx.volts(a), ctx.volts(b)
    return va is not None and vb is not None and va > 0 and abs(va - vb) < 1e-9


def _signal_net(ctx: Ctx, net: str) -> bool:
    """A net that carries a signal (an ESP pin or a module signal pin), not a supply rail."""
    if _esp_net(ctx, net):
        return True
    for ref, pin in (ctx.nets.get(net) or {}).get("pins") or []:
        inst = next((i for i in ctx.instances if i.ref == ref), None)
        sig = next((p.get("signal") for p in _pins(inst) if p["name"] == pin), None) if inst else None
        if sig not in (None, "supply", "gnd", "power_out"):
            return True
    return False


# --- mod.supply_range ---------------------------------------------------------------------------------------------
def _range(lo: float | None, hi: float | None) -> str:
    if lo is not None and hi is not None:
        return f"{fmt(lo, 'V')}–{fmt(hi, 'V')}"
    return f"max {fmt(hi, 'V')}" if hi is not None else f"min {fmt(lo, 'V')}"


def _verdict(ctx: Ctx, inst: Instance, spec: Mapping[str, Any], v: float) -> tuple[str, str | None, str, Any]:
    """(status, severity, text after "<pins> on <net> = <V>", F cited) for one supply pin on a known rail."""
    lo, hi, absmax = (ctx.fv(spec.get(k), inst) for k in ("min", "max", "abs_max"))
    if absmax is not None and v > absmax + _EPS:
        return "failed", "danger", f"exceeds the absolute maximum {fmt(absmax, 'V')}: the chip can be damaged", \
            spec.get("abs_max")
    if hi is not None and v > hi + _EPS:
        return "failed", "caution", f"is above the operating range {_range(lo, hi)}", spec.get("max")
    if lo is not None and v < lo - _EPS:
        return "failed", "caution", f"is below the operating range {_range(lo, hi)}", spec.get("min")
    if lo is None and hi is None and absmax is None:
        return "not_checked", None, "no supply range in the module data", None
    if lo is None and hi is None:
        return "passed", None, f"below the absolute maximum {fmt(absmax, 'V')}", spec.get("abs_max")
    return "passed", None, f"within {_range(lo, hi)}", spec.get("max") or spec.get("min")


@rule("mod.supply_range")
def supply_range(ctx: Ctx) -> list[Finding]:
    """Every ``supplies[pin]`` of every instance against the voltage of its rail. Supply pins on the same net with
    the same verdict (VDDIO tied to VDD) form one finding."""
    rid = "mod.supply_range"
    out: list[Finding] = []
    vdd = _esp_v(ctx, "vdd")
    for inst in ctx.instances:
        supplies = inst.module.get("supplies")
        if not isinstance(supplies, Mapping):
            continue
        groups: dict[tuple[Any, ...], list[str]] = {}
        for pin, spec in supplies.items():
            if not isinstance(spec, Mapping):
                continue
            net = ctx.net_of(inst, pin)
            v = ctx.volts(net)
            if net is None:
                key: tuple[Any, ...] = ("open", None, None, None, None)
            elif net == "GND" and "min" not in spec:
                # no minimum in the data: 0 V is an allowed mode (e.g. DS18B20 parasite power, VDD to GND); the
                # family rule judges it (ambient.py)
                key = ("passed", net, None, "0 V is allowed by the data (no minimum supply)", None)
            elif net == "GND":
                key = ("gnd", net, "caution", None, ctx.src(inst, spec.get("min")))
            elif v is None and _esp_net(ctx, net):
                absmax = ctx.fv(spec.get("abs_max"), inst)
                if absmax is not None and vdd is not None and vdd > absmax + _EPS:
                    key = ("gpio_over", net, "danger", absmax, ctx.src(inst, spec.get("abs_max")))
                else:
                    key = ("gpio", net, None, None, None)
            elif v is None:
                key = ("unknown", net, None, None, None)
            else:
                status, sev, text, f = _verdict(ctx, inst, spec, v)
                if status == "failed" and _regulated(inst) and inst.module.get("kind") != "module" \
                        and v > REGULATED_V + _EPS:
                    # chip entry on a board whose 3.3 V regulator the user confirmed (GY-BME280 at 5 V): the chip
                    # sees at most 3.3 V; a breakout gets the same through the severity cap (regulator_3v3)
                    s2, _, t2, f2 = _verdict(ctx, inst, spec, REGULATED_V)
                    if s2 == "passed":
                        key = ("regulated", net, "info", t2, ctx.src(inst, f2) if f2 is not None else None)
                        groups.setdefault(key, []).append(pin)
                        continue
                key = (status, net, sev, text, ctx.src(inst, f) if f is not None else None)
            groups.setdefault(key, []).append(pin)
        for (status, net, sev, text, src), pins in groups.items():
            who = f"{ctx.label(inst)} {', '.join(pins)}"
            if status == "open":
                out.append(Finding(rid, "not_checked", None, f"{who}: not connected, supply not checked.", [inst.ref]))
            elif status == "regulated":
                out.append(Finding(rid, "failed", "info", f"{who} on {net} = {fmt(ctx.volts(net), 'V')}: behind the "
                                   f"board regulator (user-confirmed, facts.regulator) the chip sees at most "
                                   f"{fmt(REGULATED_V, 'V')}, {text}; confirm the regulator if unsure.", [inst.ref],
                                   [src] if src else []))
            elif status == "gnd":
                out.append(ctx.finding(rid, "failed", "caution", f"{who} on GND: the supply pin is not powered.",
                                       inst, source_id=src, chip_fact=False))
            elif status == "gpio_over":
                out.append(ctx.finding(rid, "failed", "danger", f"{who} powered from {_gpio_text(ctx, net)}: the ESP "
                                       f"drives up to {fmt(vdd, 'V')}, above the absolute maximum {fmt(text, 'V')}.",
                                       inst, source_id=src, supply=True, source_ids=_sids(src, _esp_src(ctx))))
            elif status == "gpio":
                out.append(Finding(rid, "not_checked", "info", f"{who} powered from {_gpio_text(ctx, net)}: a GPIO is "
                                   "not a rail, its high level depends on the load (see mod.power_budget).",
                                   [inst.ref]))
            elif status == "unknown":
                out.append(Finding(rid, "not_checked", "info",
                                   f"{who} on net {net} with unknown voltage: supply not checked (name the rail "
                                   "voltage in options.rails).", [inst.ref]))
            elif status == "failed":
                out.append(ctx.finding(rid, "failed", sev, f"{who} on {net} = {fmt(ctx.volts(net), 'V')} {text}.",
                                       inst, source_id=src, supply=True))
            else:
                out.append(Finding(rid, status, None, f"{who} on {net} = {fmt(ctx.volts(net), 'V')}: {text}.",
                                   [inst.ref], [src] if src else []))
    return out


# --- pull-ups on a net (level rules) ------------------------------------------------------------------------------
def _pullups(ctx: Ctx, net: str) -> list[dict[str, Any]]:
    """Everything that can pull ``net`` high: [{ref, how, volts, bound, inst}]. ``volts`` = the known pull-up voltage;
    ``bound`` = an upper bound (the supply of a breakout whose pull-ups are not confirmed); ``inst`` = the instance
    whose module data the entry rests on (None: a user part or user fact)."""
    out: list[dict[str, Any]] = []
    for ref, nets in _plain_parts(ctx, RESISTOR_KINDS):
        if net not in nets:
            continue
        for other in nets:
            if other in (net, "GND"):
                continue
            v = ctx.volts(other)
            if v is not None:
                if v > 0:
                    out.append({"ref": ref, "how": f"{ref} to {other}", "volts": v, "inst": None})
            elif not _signal_net(ctx, other):  # a series resistor leads to another signal net
                out.append({"ref": ref, "how": f"{ref} to {other}", "volts": None, "inst": None})
    for inst in ctx.instances:
        on = [p for p in _pins(inst) if inst.conn.get(p["name"]) == net]
        for p in on:
            ip = p.get("internal_pull")
            if ip == "up" or (isinstance(ip, Mapping) and "up" in ip):
                dv, dom = _domain(ctx, inst)
                out.append({"ref": inst.ref, "how": f"{inst.ref} {p['name']} internal pull-up to {dom or 'its supply'}",
                            "volts": dv, "inst": inst})
        od = [p for p in on if SIGNAL_DIRECTION.get(str(p.get("signal"))) in ("bidir_od", "out_od")
              or _output_type(inst, p) == "open_drain"]
        facts = inst.facts or {}
        if not od or facts.get("pullups") == "none":
            continue
        to = facts.get("pullups_to")
        if isinstance(to, str) and to.strip():  # user fact: counts for a breakout and for a chip entry alike
            v, label = _pullups_to(ctx, inst, to.strip())
            out.append({"ref": inst.ref, "how": f"{inst.ref} board pull-ups to {label} (user)", "volts": v,
                        "inst": None})
            continue
        if facts.get("level_shifter") is True:  # user-confirmed: the ESP side of the board's shifter is 3.3 V
            out.append({"ref": inst.ref, "how": f"{inst.ref} level shifter pull-ups on its ESP side "
                        f"(user-confirmed, {fmt(REGULATED_V, 'V')})", "volts": None, "bound": REGULATED_V,
                        "inst": inst, "regulated": True, "shifter": True})
            continue
        if inst.module.get("kind") != "module" and not (_has_pullups(facts) or facts.get("pullups") == "unknown"):
            continue  # a bare chip brings no pull-ups unless the user says its board has some (facts.pullups)
        raw = ctx.supply_volts(inst)  # board pull-ups may sit on VIN even behind a regulator
        bound = max(raw.values()) if raw else None
        what = (
            f"board pull-ups {facts.get('pullups') or 'present'} (user)" if _has_pullups(facts) else
            "board pull-ups unknown (facts.pullups)" if facts.get("pullups") == "unknown" else "possible board pull-ups")
        out.append({"ref": inst.ref, "how": f"{inst.ref} {what} (up to its supply {fmt(bound, 'V')})",
                    "volts": None, "bound": bound, "inst": inst, "regulated": _regulated(inst)})
    return out


def _pullups_to(ctx: Ctx, inst: Instance, to: str) -> tuple[float | None, str]:
    """(volts, label) of ``facts.pullups_to``: a pin of the module (its net), a net / rail name, or a number in V."""
    if to in {p["name"] for p in _pins(inst)}:
        net = inst.conn.get(to)
        v = ctx.volts(net)
        return v, f"{to} ({net} = {fmt(v, 'V')})" if v is not None else f"{to} ({net or 'not connected'})"
    v = ctx.volts(to)
    if v is not None:
        return v, to
    m = re.fullmatch(r"(\d+(?:[.,]\d+)?)\s*[Vv]?", to)
    if m:
        v = float(m.group(1).replace(",", "."))
        return v, fmt(v, "V")
    return None, to


def _pullup_volts(ctx: Ctx, net: str) -> float | None:
    """The high level of an open-drain net when every pull-up voltage is known and they agree (else None)."""
    pus = _pullups(ctx, net)
    known = _uniq(p["volts"] for p in pus if p.get("volts") is not None)
    if not pus or len(known) != 1 or any(p.get("volts") is None for p in pus):
        return None
    return known[0]


# --- mod.level_in -------------------------------------------------------------------------------------------------
def _in_verdict(ctx: Ctx, inst: Instance, high: float, high_txt: str, driven: bool
                ) -> tuple[str, str | None, str, list[Any]]:
    """(status, severity, text, cited Fs) for a module input whose high level is ``high``. ``driven``: the ESP drives
    the line push-pull (its VOH/VOL apply)."""
    vmax, fmax, _ = _level(ctx, inst, "v_in_max")
    if vmax is not None and high > vmax + _EPS:
        return "failed", "danger", (f"{high_txt} {fmt(high, 'V')} exceeds the module's input maximum "
                                    f"{fmt(vmax, 'V')}: the input can be damaged; use a level shifter"), [fmax]
    vih, fvih, why = _level(ctx, inst, "vih")
    if vih is None:
        return "not_checked", None, f"input level not checked: VIH {why}", [fvih]
    voh, vdd = _esp_v(ctx, "voh"), _esp_v(ctx, "vdd")
    if vih > high + _EPS:
        return "failed", "caution", (f"needs VIH {fmt(vih, 'V')}, above the {high_txt} {fmt(high, 'V')}: the signal is "
                                     "not recognised; use a level shifter"), [fvih]
    if driven and voh is not None and vih > voh + _EPS:
        return "failed", "caution", (f"needs VIH {fmt(vih, 'V')}, above the ESP's guaranteed VOH {fmt(voh, 'V')} "
                                     f"(high up to {fmt(vdd, 'V')}): outside the guaranteed levels"), [fvih]
    vil, fvil, _ = _level(ctx, inst, "vil")
    vol = _esp_v(ctx, "vol")
    if driven and vil is not None and vol is not None and vol > vil + _EPS:
        return "failed", "caution", (f"VIL {fmt(vil, 'V')} lies below the ESP's VOL {fmt(vol, 'V')}: the low level is "
                                     "outside the guaranteed levels"), [fvil]
    ref_v = f"the ESP's VOH {fmt(voh, 'V')}" if driven and voh is not None else f"the {high_txt} {fmt(high, 'V')}"
    return "passed", None, f"VIH {fmt(vih, 'V')} ≤ {ref_v}", [fvih]


@rule("mod.level_in")
def level_in(ctx: Ctx) -> list[Finding]:
    """ESP -> module input levels (ESP push-pull: high VOH..VDD; open-drain line: high = the pull-up voltage)."""
    rid = "mod.level_in"
    jobs: list[tuple[Instance, str, str, str]] = []  # (inst, pin, net, direction)
    off_esp: list[tuple[Instance, str, str]] = []  # open-drain module pins on nets without an ESP pin
    for inst in ctx.instances:
        for p in _pins(inst):
            d = SIGNAL_DIRECTION.get(str(p.get("signal")))
            net = inst.conn.get(p["name"])
            if d in ("in", "bidir_od") and net is not None and _esp_net(ctx, net):
                jobs.append((inst, p["name"], net, d))
            elif d == "bidir_od" and net is not None and ctx.volts(net) is None:
                off_esp.append((inst, p["name"], net))
    groups: dict[tuple[Any, ...], list[str]] = {}
    for inst, pin, net in off_esp:  # e.g. the 5 V side of a level shifter: only the damage check (silent else)
        key = _od_over_key(ctx, inst, net)
        if key is not None:
            groups.setdefault(key, []).append(pin)
    if not jobs:
        return _level_in_findings(ctx, groups) if groups else []
    vdd = _esp_v(ctx, "vdd")
    if vdd is None or _esp_v(ctx, "voh") is None:
        return [Finding(rid, "not_checked", "info", f"No DC characteristics (VOH) for chip {ctx.chip}: the input "
                        "levels of the modules are not checked.", _uniq(i.ref for i, *_ in jobs)),
                *_level_in_findings(ctx, groups)]
    for inst, pin, net, d in jobs:
        if (inst.facts or {}).get("level_shifter") is True:
            key: tuple[Any, ...] = (inst.ref, "shifter", None, "", ())
        elif d == "in":
            status, sev, text, fs = _in_verdict(ctx, inst, vdd, "ESP high", True)
            if status == "not_checked":
                dv, _ = _domain(ctx, inst)
                sev = "info" if dv is not None and dv > vdd + _EPS else None
            key = (inst.ref, status, sev, text, tuple(ctx.src(inst, f) for f in fs if f is not None))
        else:  # open-drain line: the ESP only pulls low; high = the pull-up voltage, checked when known
            vpu = _pullup_volts(ctx, net)
            if vpu is None:
                key = _od_over_key(ctx, inst, net)
                if key is None:
                    continue
            else:
                status, sev, text, fs = _in_verdict(ctx, inst, vpu, f"pull-up voltage on {net}", False)
                key = (inst.ref, status, None if status == "not_checked" else sev, text,
                       tuple(ctx.src(inst, f) for f in fs if f is not None))
        groups.setdefault(key, []).append(pin)
    return _level_in_findings(ctx, groups)


def _od_over_key(ctx: Ctx, inst: Instance, net: str) -> tuple[Any, ...] | None:
    """Group key for a danger finding when the highest known pull-up on an open-drain net exceeds the module's input
    maximum (the pull-ups disagree or are partly unknown); None when nothing known exceeds it."""
    tops = [p["volts"] for p in _pullups(ctx, net) if p.get("volts") is not None]
    vmax, fmax, _ = _level(ctx, inst, "v_in_max")
    if not tops or vmax is None or max(tops) <= vmax + _EPS:
        return None
    text = (f"pull-up voltage on {net} {fmt(max(tops), 'V')} exceeds the module's input maximum {fmt(vmax, 'V')}: "
            "the input can be damaged; pull up to a lower rail or use a level shifter")
    return inst.ref, "failed", "danger", text, (ctx.src(inst, fmax),)


def _level_in_findings(ctx: Ctx, groups: Mapping[tuple[Any, ...], list[str]]) -> list[Finding]:
    rid = "mod.level_in"
    out: list[Finding] = []
    for (ref, status, sev, text, srcs), pins in groups.items():
        inst = ctx.instance(ref)
        who = f"{ctx.label(inst)} {', '.join(pins)}"
        src = srcs[0] if srcs else ctx.src(inst)
        sids = _sids(src, _esp_src(ctx))
        if status == "shifter":
            out.append(Finding(rid, "passed", None, f"{who}: level shifter on the board (facts.level_shifter, user).",
                               [ref], sids))
        elif sev is not None:
            out.append(ctx.finding(rid, status, sev, f"{who}: {text}.", inst, source_id=src, source_ids=sids))
        else:
            out.append(Finding(rid, status, None, f"{who}: {text}.", [ref], sids))
    return out


# --- mod.level_out ------------------------------------------------------------------------------------------------
def _push_pull(ctx: Ctx, inst: Instance, pin: Mapping[str, Any], net: str) -> tuple[str, str | None, str, Any]:
    """(status, severity, text, cited F) for a module output that drives an ESP net."""
    vmax, vih = _esp_v(ctx, "v_in_max"), _esp_v(ctx, "vih")
    otype = _output_type(inst, pin)
    dv, dom = _domain(ctx, inst)
    behind = " (behind the board's 3.3 V regulator, user)" if _regulated(inst) else ""
    if dv is None:
        top = _max_supply(ctx, inst)
        if top is not None and vmax is not None and top > vmax + _EPS:
            return "failed", "caution", (f"I/O domain not in the module data; its supply reaches {fmt(top, 'V')}, "
                                         f"above the ESP input maximum {fmt(vmax, 'V')}: confirm the output level"), None
        if top is not None:
            return "passed", None, f"every supply ≤ {fmt(top, 'V')}, within the ESP input maximum {fmt(vmax, 'V')}", None
        return "not_checked", None, "output level not checked: the module's supply voltage is unknown", None
    if (inst.facts or {}).get("level_shifter") is True and vmax is not None and dv > vmax + _EPS:
        # the user confirms a level shifter on the board: its ESP side is 3.3 V (same semantics as mod.level_in)
        return "passed", None, (f"level shifter on the board (facts.level_shifter, user-confirmed): the ESP side is "
                                f"taken as {fmt(REGULATED_V, 'V')}, the board runs at {fmt(dv, 'V')}"), None
    if vmax is not None and dv > vmax + _EPS:
        if otype in ("push_pull", "tristate"):
            return "failed", "danger", (f"push-pull high = {dom} {fmt(dv, 'V')}{behind} exceeds the ESP input maximum "
                                        f"{fmt(vmax, 'V')} on {_gpio_text(ctx, net)}: the GPIO can be damaged; use a "
                                        "level shifter or a divider"), None
        return "failed", "caution", (f"output type not in the module data; if it drives high it reaches {dom} "
                                     f"{fmt(dv, 'V')}, above the ESP input maximum {fmt(vmax, 'V')}"), None
    if vih is not None and dv < vih - _EPS:
        return "failed", "caution", (f"high level at most {dom} {fmt(dv, 'V')}{behind}, below the ESP's VIH "
                                     f"{fmt(vih, 'V')}: the ESP does not reliably read high"), None
    voh, fvoh, _ = _level(ctx, inst, "voh")
    if vih is not None and voh is not None and voh < vih - _EPS:
        load = _load_current(fvoh)
        if load is not None and load >= LOADED_VOH_A - _EPS:
            return "failed", "info", (f"module VOH {fmt(voh, 'V')} is specified at a {fmt(load, 'A')} load and lies "
                                      f"below the ESP's VIH {fmt(vih, 'V')}; an ESP input draws almost no current, so "
                                      f"the real high level is higher (towards {dom} {fmt(dv, 'V')}): hint only"), fvoh
        return "failed", "caution", (f"module VOH {fmt(voh, 'V')} lies below the ESP's VIH {fmt(vih, 'V')}: outside "
                                     "the guaranteed levels"), fvoh
    return "passed", None, f"high level ≤ {fmt(dv, 'V')}{behind}, within the ESP input maximum {fmt(vmax, 'V')}", fvoh


def _high_vih(ctx: Ctx, net: str) -> str:
    """\"U2 (VIH 3.50 V)\": the modules on ``net`` whose input needs more than 3.3 V for a high (then a 3.3 V
    pull-up is no fix); empty when none."""
    out = []
    for inst in ctx.instances:
        if net not in [inst.conn.get(p["name"]) for p in _pins(inst)
                       if SIGNAL_DIRECTION.get(str(p.get("signal"))) in ("in", "bidir_od")]:
            continue
        vih, _, _ = _level(ctx, inst, "vih")
        if vih is not None and vih > REGULATED_V + _EPS:
            out.append(f"{inst.ref} (VIH {fmt(vih, 'V')})")
    return ", ".join(out)


def _od_net(ctx: Ctx, net: str, vmax: float, vih: float | None, esp: list[str]) -> Finding:
    """Verdict on the pull-ups of one open-drain / I²C / 1-Wire net that reaches the ESP."""
    rid = "mod.level_out"
    pus = _pullups(ctx, net)
    where = _gpio_text(ctx, net)

    def capped(sev: str, msg: str, items: list[dict[str, Any]]) -> Finding:
        insts = [p["inst"] for p in items if p.get("inst") is not None]
        refs = _uniq(p["ref"] for p in items)
        if insts and len(insts) == len(items):  # rests on module data only: capped by those modules
            srcs = [ctx.src(i) for i in insts]
            return ctx.finding(rid, "failed", sev, msg, insts, source_id=srcs, refs=refs, source_ids=_sids(srcs, esp))
        return ctx.finding(rid, "failed", sev, msg, None, source_id=esp[0] if esp else None, refs=refs,
                           source_ids=esp)

    over = [p for p in pus if p.get("volts") is not None and p["volts"] > vmax + _EPS]
    if over:
        v = max(p["volts"] for p in over)
        needs = _high_vih(ctx, net)
        fix = (f"use a level shifter (bench_schematic level_shifter / PCA9306): {needs} needs a high level above "
               f"{fmt(REGULATED_V, 'V')}" if needs else "pull up to 3V3 or use a level shifter")
        return capped("danger", f"{where}: pulled up to {fmt(v, 'V')} ({'; '.join(p['how'] for p in over)}), above the "
                      f"ESP input maximum {fmt(vmax, 'V')}: the GPIO can be damaged; {fix}.", over)
    unsure = [p for p in pus if p.get("volts") is None
              and not (p.get("bound") is not None and p["bound"] <= vmax + _EPS)]
    if unsure:
        sev = "info" if all(p.get("regulated") for p in unsure) else "caution"  # 3.3 V board: likely fine
        return capped(sev, f"{where}: pull-up voltage unknown ({'; '.join(p['how'] for p in unsure)}): confirm "
                      f"the pull-up voltage is at most {fmt(vmax, 'V')} (facts.pullups_to or a pull-up part).", unsure)
    known = [p for p in pus if p.get("volts") is not None]
    if known and vih is not None and min(p["volts"] for p in known) < vih - _EPS:
        low = min(p["volts"] for p in known)
        return capped("caution", f"{where}: pulled up to {fmt(low, 'V')}, below the ESP's VIH {fmt(vih, 'V')}: the "
                      "ESP does not reliably read high.", [p for p in known if p["volts"] == low])
    refs = _uniq(r for r, _ in (ctx.nets.get(net) or {}).get("pins") or [])
    if pus:
        top = max(p["volts"] if p.get("volts") is not None else p["bound"] for p in pus)
        shift = [p["ref"] for p in pus if p.get("shifter")]
        note = f" (level shifter on {', '.join(shift)}, facts.level_shifter, user-confirmed)" if shift else ""
        return Finding(rid, "passed", None, f"{where}: pull-ups at most {fmt(top, 'V')}{note}, within the ESP input "
                       f"maximum {fmt(vmax, 'V')}.", refs, esp)
    return Finding(rid, "passed", None, f"{where}: no pull-up to a rail above {fmt(vmax, 'V')} (pull-ups: see "
                   "mod.required_parts).", refs, esp)


@rule("mod.level_out")
def level_out(ctx: Ctx) -> list[Finding]:
    """Module -> ESP net: push-pull highs, the pull-ups of open-drain / I²C / 1-Wire nets, analog outputs."""
    rid = "mod.level_out"
    pp: list[tuple[Instance, Mapping[str, Any], str]] = []
    od_nets: list[str] = []
    analog: list[tuple[Instance, Mapping[str, Any], str]] = []
    for inst in ctx.instances:
        for p in _pins(inst):
            d = SIGNAL_DIRECTION.get(str(p.get("signal")))
            net = inst.conn.get(p["name"])
            if net is None or not _esp_net(ctx, net):
                continue
            if d in ("bidir_od", "out_od") or (d == "out" and _output_type(inst, p) == "open_drain"):
                od_nets.append(net)
            elif d == "out":
                pp.append((inst, p, net))
            elif d == "analog":
                analog.append((inst, p, net))
    od_nets = _uniq(od_nets)
    if not (pp or od_nets or analog):
        return []
    vmax = _esp_v(ctx, "v_in_max")
    if vmax is None:
        refs = _uniq([i.ref for i, *_ in pp + analog] + [r for n in od_nets for r, _ in ctx.nets[n]["pins"]])
        return [Finding(rid, "not_checked", "info", f"No DC characteristics (input maximum) for chip {ctx.chip}: the "
                        "output levels of the modules are not checked.", refs)]
    esp = _esp_src(ctx)
    out: list[Finding] = []
    groups: dict[tuple[Any, ...], list[str]] = {}
    for inst, p, net in pp:
        status, sev, text, f = _push_pull(ctx, inst, p, net)
        groups.setdefault((inst.ref, status, sev, text, ctx.src(inst, f) if f is not None else None), []).append(
            p["name"])
    for (ref, status, sev, text, src), pins in groups.items():
        inst = ctx.instance(ref)
        msg = f"{ctx.label(inst)} {', '.join(pins)}: {text}."
        src = src or ctx.src(inst)
        if sev is None:
            out.append(Finding(rid, status, None, msg, [ref], _sids(src, esp)))
        else:
            out.append(ctx.finding(rid, status, sev, msg, inst, source_id=src, source_ids=_sids(src, esp)))
    vih = _esp_v(ctx, "vih")
    out += [_od_net(ctx, net, vmax, vih, esp) for net in od_nets]
    for inst, p, net in analog:
        top = _max_supply(ctx, inst)
        who = f"{ctx.label(inst)} {p['name']}"
        if top is not None and top > vmax + _EPS:
            out.append(ctx.finding(rid, "failed", "caution", f"{who}: the analog output can reach its supply "
                                   f"{fmt(top, 'V')}, above the ESP input maximum {fmt(vmax, 'V')} on "
                                   f"{_gpio_text(ctx, net)}: confirm its range or use a divider.", inst,
                                   source_id=ctx.src(inst), source_ids=_sids(ctx.src(inst), esp)))
        else:
            out.append(Finding(rid, "not_checked", None, f"{who}: the analog level against the ADC range is not checked "
                               "(no ADC range in the ESP data).", [inst.ref], esp))
    return out


# --- mod.pullup_parallel ------------------------------------------------------------------------------------------
I2C_SIGNALS = ("i2c_sda", "i2c_scl")
FAST_MODE_HZ = 400_000.0  # I²C Fast-mode (NXP UM10204)


def _ohms(v: Any) -> float | None:
    """A resistance (number in Ω or text such as "4k7", "10 kΩ"); None when unreadable."""
    if v is None or isinstance(v, bool):
        return None
    try:
        r, unit = units.parse(v)
    except (BenchError, ValueError, TypeError):
        return None
    return r if unit in (None, "Ω") and r == r and r > 0 else None


def _i2c_pullups(ctx: Ctx, net: str) -> tuple[list[dict[str, Any]], list[str]]:
    """([{ref, ohms, volts, src}], [unknown: "U1 board pull-ups (facts.pullups)"]) of every pull-up on an I²C net:
    resistor parts to a rail, ``facts.pullups`` of the modules on the net (``facts.onboard`` pullups or a breakout
    without a value = unknown) and valued internal pull-ups of module pins."""
    known: list[dict[str, Any]] = []
    unknown: list[str] = []
    values = {p.get("ref"): p.get("value") for p in ctx.parts if not p.get("module")}
    for ref, nets in _plain_parts(ctx, RESISTOR_KINDS):
        if net not in nets:
            continue
        rails = [n for n in nets if n not in (net, "GND") and (ctx.volts(n) or 0) > 0]
        if not rails:
            continue  # a series resistor or a pull-down: no pull-up
        r = _ohms(values.get(ref))
        if r is None:
            unknown.append(f"{ref} (no value)")
        else:
            known.append({"ref": ref, "ohms": r, "volts": max(ctx.volts(n) or 0.0 for n in rails), "src": None})
    for inst in ctx.instances:
        on = [p for p in _pins(inst) if inst.conn.get(p["name"]) == net]
        if not on:
            continue
        for p in on:
            ip = p.get("internal_pull")
            if isinstance(ip, Mapping) and isinstance(ip.get("up"), Mapping):
                r, (dv, _) = ctx.fv(ip["up"], inst), _domain(ctx, inst)
                if r:
                    known.append({"ref": inst.ref, "ohms": r, "volts": dv, "src": ctx.src(inst, ip["up"])})
            elif ip == "up":
                unknown.append(f"{inst.ref} {p['name']} internal pull-up (no value)")
        if not any(p.get("signal") in I2C_SIGNALS for p in on):
            continue
        facts = inst.facts or {}
        if facts.get("pullups") == "none":
            continue
        r = _ohms(facts.get("pullups"))
        if r is None:
            if facts.get("pullups") == "unknown" or _onboard(facts, "pullups") or inst.module.get("kind") == "module":
                unknown.append(f"{inst.ref} board pull-ups")
            continue
        to = facts.get("pullups_to")
        if isinstance(to, str) and to.strip():
            v = _pullups_to(ctx, inst, to.strip())[0]
        elif facts.get("level_shifter") is True or _regulated(inst):
            v = REGULATED_V
        else:
            v = _max_supply(ctx, inst)
        known.append({"ref": inst.ref, "ohms": r, "volts": v, "src": None})
    return known, unknown


def _bus_mode(ctx: Ctx, net: str) -> tuple[str, int]:
    """(UM10204 mode for R_max, I²C targets on the net): "fast" when every rated device allows 400 kHz."""
    hz, n = [], 0
    for inst in ctx.instances:
        if not any(inst.conn.get(p["name"]) == net and p.get("signal") in I2C_SIGNALS for p in _pins(inst)):
            continue
        n += inst.qty
        f = ctx.fv((modcheck.i2c_iface(inst.module) or {}).get("f_max_hz"))
        if f:
            hz.append(f)
    return ("fast" if hz and min(hz) >= FAST_MODE_HZ - _EPS else "standard"), max(1, n)


@rule("mod.pullup_parallel")
def pullup_parallel(ctx: Ctx) -> list[Finding]:
    """All pull-ups of one I²C line in parallel against the UM10204 window (calc.i2c_pullup): below R_min the
    ESP / devices cannot pull the line to a valid low with 3 mA (caution); above R_max for the bus clock only a hint."""
    from .. import calc  # the one formula (R_min / R_max), no second copy here

    rid = "mod.pullup_parallel"
    nets = _uniq(inst.conn[p["name"]] for inst in ctx.instances for p in _pins(inst)
                 if p.get("signal") in I2C_SIGNALS and inst.conn.get(p["name"])
                 and ctx.volts(inst.conn[p["name"]]) is None)
    groups: dict[tuple[Any, ...], tuple[list[str], list[str]]] = {}  # (status, sev, text, srcs) -> (nets, refs)
    for net in nets:
        known, unknown = _i2c_pullups(ctx, net)
        if not known and not unknown:
            continue  # no pull-up at all: mod.required_parts
        refs = _uniq([k["ref"] for k in known] + [u.split()[0] for u in unknown])
        par = " ‖ ".join(fmt(k["ohms"], "Ω") for k in known)
        r_eff = 1.0 / sum(1.0 / k["ohms"] for k in known) if known else None
        volts = [k["volts"] for k in known if k["volts"] is not None]
        if r_eff is None or not volts:
            why = f"pull-ups unknown ({', '.join(unknown[:3])})" if unknown else "pull-up voltage unknown"
            key: tuple[Any, ...] = ("not_checked", None,
                                    f"{why}: the parallel value is not checked (facts.pullups).", ())
            groups.setdefault(key, ([], []))[0].append(net)
            groups[key][1].extend(refs)
            continue
        mode, n = _bus_mode(ctx, net)
        win = {m: calc.i2c_pullup(max(volts), devices=n, mode=m) for m in ("standard", mode)}
        if not all(e.get("ok") for e in win.values()):
            continue
        res = win["standard"]["result"]
        r_min, r_max, cb = res["r_min"]["value"], res["r_max"]["value"], res["inputs"]["c_bus"]["value"]
        r_fast = win[mode]["result"]["r_max"]["value"] if mode == "fast" else None
        eff = f"{par} = {fmt(r_eff, 'Ω')}" if len(known) > 1 else f"{par}"
        vtxt = (f"pull-up {fmt(max(volts), 'V')}; UM10204: V_OL {calc.I2C_V_OL:g} V at "
                f"{calc.I2C_I_OL * 1e3:g} mA")
        srcs = tuple(_sids([k["src"] for k in known], calc.NXP))
        cbt = f"C_b {fmt(cb, 'F')} estimated"
        if r_eff < r_min - _EPS:
            more = f"; more unknown: {', '.join(unknown[:2])}" if unknown else ""
            what = "parallel" if len(known) > 1 else "pull-up"
            text = (f"{what} {eff} is below R_min {fmt(r_min, 'Ω')} ({vtxt}): the bus may not reach a valid low; "
                    f"remove pull-ups (one set per bus){more}.")
            key = ("failed", "caution", text, srcs)
        elif unknown:
            text = (f"known pull-ups {eff} (R_min {fmt(r_min, 'Ω')}); unknown: {', '.join(unknown[:3])}: the "
                    "parallel value is not checked (facts.pullups).")
            key = ("not_checked", None, text, srcs)
        elif r_eff > r_max + _EPS:  # too weak even for Standard-mode (100 kHz): a hint, the estimate is rough
            text = (f"pull-ups {eff} are above R_max {fmt(r_max, 'Ω')} even for Standard-mode ({cbt}): edges may "
                    "rise too slowly; use a lower value; hint only.")
            key = ("failed", "info", text, (*srcs, calc.RULE))
        elif r_fast is not None and r_eff > r_fast + _EPS:
            text = (f"pull-ups {eff} within R_min {fmt(r_min, 'Ω')} – R_max {fmt(r_max, 'Ω')} (Standard-mode, "
                    f"{cbt}); for Fast-mode (400 kHz) R_max is {fmt(r_fast, 'Ω')}: keep 100 kHz or use a lower value.")
            key = ("passed", None, text, (*srcs, calc.RULE))
        else:
            top = r_fast if r_fast is not None else r_max
            text = (f"pull-ups {eff} within R_min {fmt(r_min, 'Ω')} – R_max {fmt(top, 'Ω')} "
                    f"({calc.I2C_MODES[mode]['label']}, {cbt}).")
            key = ("passed", None, text, (*srcs, calc.RULE))
        groups.setdefault(key, ([], []))[0].append(net)
        groups[key][1].extend(refs)
    return [Finding(rid, status, sev, f"{', '.join(where)}: {text}", _uniq(refs), list(srcs))
            for (status, sev, text, srcs), (where, refs) in groups.items()]


# --- mod.power_budget ---------------------------------------------------------------------------------------------
def fact_amps(v: Any) -> float | None:
    """``facts.i_max`` in A: a number (A) or a text such as "2.2A" / "350 mA"; None when absent or unreadable."""
    if v is None or isinstance(v, bool):
        return None
    try:
        a = units.parse_quantity(v, "A") if isinstance(v, str) else float(v)
    except (BenchError, ValueError, TypeError):
        return None
    return a if a == a and a > 0 else None


def instance_draw(ctx: Ctx, inst: Instance) -> dict[str, Any]:
    """The current one instance draws: {net, typ, max, peak, user}. Catalog values × qty; ``facts.i_max`` (the
    user's measured / confirmed maximum of the whole part, qty included, e.g. from bench_calc led_strip) replaces
    max and peak and caps typ (``user`` = that value)."""
    raw = inst.module.get("current")
    cur: Mapping[str, Any] = raw if isinstance(raw, Mapping) else {}
    supply_pins = ctx.pins_with(inst, "supply")
    pin = cur.get("supply") if isinstance(cur.get("supply"), str) else (supply_pins[0] if supply_pins else None)
    net = inst.conn.get(pin) if pin else None
    sv = ctx.supply_volts(inst)
    typ, mx, pk = (fvalue(cur.get(k), sv) for k in ("typ", "max", "peak"))
    q = inst.qty
    typ, mx, pk = (None if x is None else x * q for x in (typ, mx, pk))
    user = fact_amps((inst.facts or {}).get("i_max"))
    if user is not None:
        mx = pk = user
        typ = None if typ is None else min(typ, user)
    pk = pk if pk is not None else mx
    return {"net": net, "typ": typ, "max": mx, "peak": pk, "user": user}


def _consumer(inst: Instance, net: str) -> bool:
    """A part that draws from ``net`` (not one that feeds it through a power_out pin, no discrete part)."""
    if str(inst.module.get("category") or "").startswith("discrete."):
        return False
    return not any(p.get("signal") == "power_out" and inst.conn.get(p["name"]) == net for p in _pins(inst))


def floored(d: Mapping[str, Any]) -> dict[str, Any]:
    """typ / max / peak of one draw for a sum: a part without max (and peak) counts its typ there, since its maximum
    is at least its typical current. The sum stays a lower bound (the part is listed in ``missing``), but max is
    never below typ."""
    mx = d["max"] if d["max"] is not None else d["typ"]
    return {"typ": d["typ"], "max": mx, "peak": d["peak"] if d["peak"] is not None else mx}


def _net_sums(on: list[Instance], draws: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    """Σ typ / max / peak of the parts on one rail (floored) and the consumers without a maximum or peak current."""
    e: dict[str, Any] = {"i_typ": None, "i_max": None, "i_peak": None, "missing": []}
    for inst in on:
        d = draws[inst.ref]
        f = floored(d)
        for k in ("typ", "max", "peak"):
            if f[k] is not None:
                e[f"i_{k}"] = (e[f"i_{k}"] or 0.0) + f[k]
        if d["max"] is None and d["peak"] is None and _consumer(inst, d["net"]):
            e["missing"].append(inst.ref)
    return e


def _sums_text(e: Mapping[str, Any]) -> str:
    parts = [f"{k} {fmt(e[f'i_{k}'], 'A')}" for k in ("typ", "max", "peak") if e.get(f"i_{k}") is not None]
    return ", ".join(parts) if parts else "no current data"


def _user_text(on: list[Instance], draws: Mapping[str, Mapping[str, Any]]) -> str:
    users = [f"{i.ref} {fmt(draws[i.ref]['user'], 'A')}" for i in on if draws[i.ref]["user"] is not None]
    return f" ({', '.join(users)} from facts.i_max, user)" if users else ""


def _missing_text(ctx: Ctx, refs: list[str]) -> str:
    """\"U3\", \"LED (150 × ws2812b)\": the parts without a maximum current, with their quantity."""
    out = []
    for ref in refs:
        inst = next((i for i in ctx.instances if i.ref == ref), None)
        out.append(f"{ref} ({inst.qty} × {inst.module_id})" if inst is not None and inst.qty > 1 else ref)
    return ", ".join(out)


def _lacking(ctx: Ctx, missing: list[str], draws: Mapping[str, Mapping[str, Any]]) -> str:
    """\"U3 has no current data\" / \"U4 has only a typical current\" for the consumers without a maximum."""
    out = []
    for refs, what in (([r for r in missing if draws[r]["typ"] is None], "no current data"),
                       ([r for r in missing if draws[r]["typ"] is not None], "only a typical current")):
        if refs:
            out.append(f"{_missing_text(ctx, refs)} {'has' if len(refs) == 1 else 'have'} {what}")
    return "; ".join(out)


def _gpio_power(ctx: Ctx, net: str, on: list[Instance], e: Mapping[str, Any], miss: str) -> Finding:
    rid = "mod.power_budget"
    where, refs, esp = _gpio_text(ctx, net), [i.ref for i in on], _esp_src(ctx)
    total = e.get("i_peak") if e.get("i_peak") is not None else e.get("i_max")
    ioh, tot_max = _esp_v(ctx, "ioh"), _esp_v(ctx, "i_out_total_max")
    srcs = [ctx.src(i) for i in on]
    if total is not None and tot_max is not None and total > tot_max + _EPS:
        return ctx.finding(rid, "failed", "danger", f"{where} powers {', '.join(refs)} with {fmt(total, 'A')}, above the "
                           f"ESP's cumulative IO output maximum {fmt(tot_max, 'A')}.", on, source_id=srcs,
                           chip_fact=False, source_ids=_sids(srcs, esp))
    if total is not None and ioh is not None and total > ioh + _EPS:
        return ctx.finding(rid, "failed", "caution", f"{where} powers {', '.join(refs)} with {fmt(total, 'A')}, above the "
                           f"ESP's typical source current {fmt(ioh, 'A')} (a typical figure, not a limit): the high "
                           "level sags; power the module from a rail.", on, source_id=srcs, chip_fact=False,
                           source_ids=_sids(srcs, esp))
    typ = f" ({fmt(ioh, 'A')})" if ioh is not None else ""
    return Finding(rid, "not_checked", "info", f"{where} powers {', '.join(refs)} ({_sums_text(e)}): the ESP datasheet "
                   f"gives the source current only as a typical value{typ}.{miss}", refs, _sids(srcs, esp))


@rule("mod.power_budget")
def power_budget(ctx: Ctx) -> list[Finding]:
    """Σ typ / max / peak per rail against its limit; a module powered from a GPIO against the ESP's IO current.
    ``facts.i_max`` (user) goes before the catalog values; only consumers without any maximum / peak count as
    "no current data"."""
    rid = "mod.power_budget"
    out: list[Finding] = []
    draws = {i.ref: instance_draw(ctx, i) for i in ctx.instances}
    for rs in ctx.rail_sums:
        net = rs["net"]
        on = [i for i in ctx.instances if draws[i.ref]["net"] == net]
        if not on:
            continue
        e = {**rs, **_net_sums(on, draws)}
        refs = [i.ref for i in on]
        missing = list(e.get("missing") or [])
        miss = f" No maximum current in the data for {', '.join(missing)}." if missing else ""
        board = " Breakouts may draw more than their chip (LEDs, regulator)." if any(
            i.module.get("kind") == "module" and draws[i.ref]["user"] is None for i in on) else ""
        head = f"{net}: {_sums_text(e)}{_user_text(on, draws)}"
        if _esp_net(ctx, net):
            out.append(_gpio_power(ctx, net, on, e, miss))
            continue
        limit = e.get("limit")
        if limit is None:
            out.append(Finding(rid, "not_checked", None, f"{head}; no rail limit known (options.rail_limits).{miss}",
                               refs, []))
            continue
        lim_src = e.get("limit_source")
        lim_txt = f"the rail limit {fmt(limit, 'A')} ({'user' if lim_src == 'user' else lim_src or 'board'})"
        esp_note = " The ESP's own current is not included." if net == "3V3" else ""
        lsids = [lim_src] if isinstance(lim_src, str) and lim_src != "user" else []
        hit = None
        for key, what in (("max", "maximum"), ("peak", "peak")):
            total = e.get(f"i_{key}")
            if total is None or total <= limit + _EPS:
                continue
            with_v = [i for i in on if draws[i.ref][key] is not None]
            # a user value (facts.i_max) is sure; catalog values only where their source allows a caution
            sure = [i for i in with_v if draws[i.ref]["user"] is not None
                    or ctx.cap("caution", i, ctx.src(i), chip_fact=False) == "caution"]
            hint = ("brownouts or resets are likely; use a stronger or separate supply" if key == "max" else
                    "short peaks can cause brownouts; add bulk capacitance or a stronger supply")
            msg = f"{head}: the {what} current {fmt(total, 'A')} exceeds {lim_txt}: {hint}.{esp_note}{miss}"
            if sum(draws[i.ref][key] for i in sure) > limit + _EPS:
                srcs = [ctx.src(i) for i in sure if draws[i.ref]["user"] is None]
                hit = Finding(rid, "failed", "caution", msg, refs, _sids(srcs, lsids))
            else:
                cat = [i for i in with_v if draws[i.ref]["user"] is None]
                srcs = [ctx.src(i) for i in cat]
                hit = ctx.finding(rid, "failed", "caution", msg, cat, source_id=srcs, chip_fact=False, refs=refs,
                                  source_ids=_sids(srcs, lsids))
            break
        if hit is not None:
            out.append(hit)
        elif missing:
            led = " (LED chains: bench_calc led_strip)" if any(
                str(i.module.get("category")) == "led.addressable" for i in on if i.ref in missing) else ""
            known = _sums_text(e) if any(e.get(f"i_{k}") is not None for k in ("typ", "max", "peak")) else "0 A"
            out.append(Finding(rid, "not_checked", "info", f"{net}: {known} known; {_lacking(ctx, missing, draws)}, "
                               f"so the budget against {lim_txt} is not checked{led}; measure the current and set "
                               f"facts.i_max.{esp_note}", refs, lsids))
        else:
            out.append(Finding(rid, "passed", None, f"{head}: within {lim_txt}.{esp_note}{board}", refs,
                               _sids([ctx.src(i) for i in on if draws[i.ref]["user"] is None], lsids)))
    return out


# --- mod.required_parts -------------------------------------------------------------------------------------------
def _req_to(inst: Instance, req: Mapping[str, Any], default: str | None) -> str | None:
    """The net ``to`` stands for: a pin name of the module -> that pin's net, else the net / rail name itself."""
    to = req.get("to")
    if not isinstance(to, str) or not to:
        return default
    return inst.conn.get(to) if to in {p["name"] for p in _pins(inst)} else to


def _between(ctx: Ctx, kinds: frozenset[str], a: str, b: str | None) -> list[str]:
    """Refs of plain parts of ``kinds`` with one end on ``a`` and one on ``b`` (b None: any rail other than GND)."""
    hits = []
    for ref, nets in _plain_parts(ctx, kinds):
        if a not in nets:
            continue
        others = [n for n in nets if n != a]
        ok = (any(ctx.volts(n) is not None and n != "GND" for n in others) if b is None
              else any(_same_rail(ctx, n, b) for n in others))
        if ok:
            hits.append(ref)
    return hits


def _modules_on(ctx: Ctx, net: str, categories: tuple[str, ...], skip: str) -> list[str]:
    return [i.ref for i in ctx.instances if i.ref != skip and str(i.module.get("category")) in categories
            and net in i.conn.values()]


def _esp_safe_rails(ctx: Ctx) -> list[str]:
    """Rails whose voltage an ESP input reads as high and tolerates (VIH ≤ V ≤ v_in_max), 3V3 first."""
    lo, hi = _esp_v(ctx, "vih"), _esp_v(ctx, "v_in_max")
    if lo is None or hi is None:
        return []
    return sorted((n for n, v in ctx.rails.items() if lo - _EPS <= v <= hi + _EPS), key=lambda n: (n != "3V3", n))


def _has_pullups(facts: Mapping[str, Any]) -> bool:
    return facts.get("pullups") not in (None, "none", "unknown", "") or _onboard(facts, "pullups")


def _onboard(facts: Mapping[str, Any], what: str) -> bool:
    """facts.onboard (user-confirmed parts on a breakout board: decoupling, pullups, reset_rc, protection)."""
    ob = facts.get("onboard")
    return isinstance(ob, list | tuple) and what in ob


def _met(ctx: Ctx, inst: Instance, req: Mapping[str, Any]) -> tuple[str, str]:
    """('met' | 'missing' | 'confirm' | 'open' | 'unknown', text) for one ``requires[]`` entry."""
    code = req.get("code")
    pins = [p for p in req.get("pins") or [] if isinstance(p, str)]
    nets = {p: inst.conn.get(p) for p in pins}
    open_ = [p for p, n in nets.items() if n is None]
    facts = inst.facts or {}
    if open_ and code != "xshut_per_device":
        return "open", f"{', '.join(open_)} not connected"
    if code in ("pullup", "pulldown"):
        to = _req_to(inst, req, "GND" if code == "pulldown" else None)
        if code == "pullup" and _has_pullups(facts):
            what = facts.get("pullups") if facts.get("pullups") not in (None, "none", "unknown", "") else "present"
            return "met", f"board pull-ups {what} (facts.pullups/onboard, user-confirmed)"
        lacking, by = [], []
        safe = _esp_safe_rails(ctx) if code == "pullup" and (ctx.volts(to) or 0) > (_esp_v(ctx, "v_in_max") or 99) \
            else []
        for p, n in nets.items():
            got = _between(ctx, RESISTOR_KINDS, n, to)
            if not got and safe and _esp_net(ctx, n):  # on an ESP pin a pull-up to 3V3 is the safe choice
                got = [r for rail in safe for r in _between(ctx, RESISTOR_KINDS, n, rail)]
            if code == "pullup":  # a bus needs one set of pull-ups: another board on the net may bring them
                got += [i.ref for i in ctx.instances if i.ref != inst.ref and n in i.conn.values()
                        and _has_pullups(i.facts or {})]
            (by if got else lacking).append((p, n, got))
        if not lacking:
            got_by = "by " + ", ".join(_uniq(r for *_, g in by for r in g))
            if code == "pullup" and facts.get("pullups") == "unknown":
                return "confirm_met", (f"{got_by}, but the board's own pull-ups are unknown (facts.pullups): measure "
                                       "them; the parallel value must stay ≥ R_min (bench_calc i2c_pullup)")
            return "met", got_by
        if code == "pullup" and facts.get("pullups") == "unknown":
            return "confirm", ("facts.pullups is unknown: measure the board before adding pull-ups; the parallel value "
                               "with the board's pull-ups must stay ≥ R_min")
        where = ", ".join(f"{p} ({n})" for p, n, _ in lacking)
        esp_pin = safe and any(_esp_net(ctx, n) for _, n, _ in lacking)
        alt = f" (on an ESP pin: to {safe[0]}, max {fmt(_esp_v(ctx, 'v_in_max'), 'V')})" if esp_pin else ""
        return "missing", f"no {code.replace('pull', 'pull-')} resistor from {where} to {to or 'the supply'}{alt}"
    if code in ("decoupling", "bulk_cap"):
        if code == "decoupling" and _onboard(facts, "decoupling"):
            return "met", "decoupling on the board (facts.onboard, user-confirmed)"
        to = _req_to(inst, req, "GND")
        sup = _uniq(n for n in nets.values() if n not in ("GND", to))
        lacking = [n for n in sup if not _between(ctx, CAPACITOR_KINDS, n, to)]
        if not lacking:
            return "met", "by a capacitor on " + ", ".join(sup)
        return "missing", f"no capacitor between {', '.join(lacking)} and {to}"
    if code in ("flyback", "termination"):
        ends = _uniq([n for n in nets.values() if n] + ([_req_to(inst, req, None)] if req.get("to") else []))
        if len(ends) < 2:
            return "unknown", "the data names fewer than two nets; requirement not checked"
        kinds = DIODE_KINDS if code == "flyback" else RESISTOR_KINDS
        hit = [ref for ref, pn in _plain_parts(ctx, kinds) if ends[0] in pn and ends[1] in pn]
        what = "diode" if code == "flyback" else "resistor"
        return ("met", f"by {', '.join(hit)}") if hit else ("missing", f"no {what} across {ends[0]} and {ends[1]}")
    if code == "series_resistor":
        lacking = [f"{p} ({n})" for p, n in nets.items()
                   if not any(n in pn and any(o != n and _signal_net(ctx, o) for o in pn)
                              for _, pn in _plain_parts(ctx, RESISTOR_KINDS))]
        return ("met", "by a series resistor") if not lacking else (
            "missing", f"no series resistor at {', '.join(lacking)}")
    if code == "level_shifter":
        if facts.get("level_shifter") is True:
            return "met", "level shifter on the board (facts.level_shifter, user)"
        hits = _uniq(r for n in nets.values() if n for r in _modules_on(ctx, n, ("logic.level_shifter",), inst.ref))
        return ("met", f"by {', '.join(hits)}") if hits else (
            "missing", "no level shifter on " + (", ".join(_uniq(n for n in nets.values() if n)) or "the signals"))
    if code == "regulator":
        if facts.get("regulator") == "3V3":
            return "met", "3.3 V regulator on the board (facts.regulator, user)"
        hits = _uniq(r for n in nets.values() if n for r in _modules_on(ctx, n, ("power.ldo", "power.buck"), inst.ref))
        return ("met", f"by {', '.join(hits)}") if hits else ("missing", "no regulator on the supply")
    if code == "xshut_per_device":
        same = [i for i in ctx.instances if i.module_id == inst.module_id]
        if len(same) < 2:
            return "met", "single device"
        for p in pins:
            ns = [i.conn.get(p) for i in same]
            if None in ns or len(set(ns)) != len(ns):
                return "missing", f"{len(same)} devices need their own {p} net each"
        return "met", f"each device has its own {', '.join(pins)} net"
    return "unknown", f"requirement {code!r} is not checked"


def _only_hint(code: str, hint: str) -> bool:
    """The datasheet calls the part a mere recommendation (info). \"strongly / highly recommended\" never; a bulk
    capacitor (current bursts) only when the text says optional / not required."""
    if _STRONG.search(hint):
        return False
    return bool((_OPTIONAL if code == "bulk_cap" else _RECOMMEND).search(hint))


@rule("mod.required_parts")
def required_parts(ctx: Ctx) -> list[Finding]:
    """``requires[]`` of every instance: met by a part (kind + conn on the nets), another module or facts."""
    rid = "mod.required_parts"
    out: list[Finding] = []
    for inst in ctx.instances:
        for req in inst.module.get("requires") or []:
            if not isinstance(req, Mapping):
                continue
            code = str(req.get("code"))
            status, text = _met(ctx, inst, req)
            pins = ", ".join(p for p in req.get("pins") or [] if isinstance(p, str))
            src = ctx.src(inst, req)
            sids = [src] if src else []
            who = f"{ctx.label(inst)} {code}" + (f" ({pins})" if pins else "")
            if status == "met":
                out.append(Finding(rid, "passed", None, f"{who}: {text}.", [inst.ref], sids))
            elif status == "confirm_met":
                out.append(Finding(rid, "failed", "info", f"{who}: {text}.", [inst.ref], sids))
            elif status == "open":
                out.append(Finding(rid, "not_checked", None, f"{who}: {text}, requirement not checked.", [inst.ref],
                                   sids))
            elif status == "unknown":
                out.append(Finding(rid, "not_checked", "info", f"{who}: {text}.", [inst.ref], sids))
            else:
                hint = " ".join(str(req[k]) for k in ("evidence", "note") if isinstance(req.get(k), str))
                recommended = status == "missing" and _only_hint(code, hint)
                sev = "info" if status == "confirm" or recommended else "caution"
                val = f" {req['value']}" if isinstance(req.get("value"), str) else ""
                calc = " (value: bench_calc i2c_pullup)" if code == "pullup" and not val else ""
                page = f", datasheet p. {req['page']}" if isinstance(req.get("page"), int) else ""
                tail = "; recommended" if recommended else ""
                out.append(ctx.finding(rid, "failed", sev, f"{who}: {text}; add{val} {req.get('kind') or code}{calc} "
                                       f"({code}{page}{tail}).", inst, source_id=src))
    return out


# --- mod.hazard ---------------------------------------------------------------------------------------------------
@rule("mod.hazard")
def hazard(ctx: Ctx) -> list[Finding]:
    """``hazards[]``: one finding per module id and hazard code with every ref."""
    rid = "mod.hazard"
    groups: dict[tuple[str, str], list[Instance]] = {}
    first: dict[tuple[str, str], Mapping[str, Any]] = {}
    for inst in ctx.instances:
        for h in inst.module.get("hazards") or []:
            if isinstance(h, Mapping) and isinstance(h.get("code"), str):
                key = (inst.module_id, h["code"])
                groups.setdefault(key, []).append(inst)
                first.setdefault(key, h)
    out: list[Finding] = []
    for (mid, code), insts in groups.items():
        h = first[(mid, code)]
        refs = [i.ref for i in insts]
        page = f" (datasheet p. {h['page']})" if isinstance(h.get("page"), int) else ""
        text = str(h.get("text") or code).rstrip(".")
        msg = f"{', '.join(refs)} ({mid}): {text}{page}." + (f" {HAZARD_TAIL[code]}" if code in HAZARD_TAIL else "")
        srcs = [ctx.src(i, h) for i in insts]
        if code in DANGER_HAZARDS:  # safety notice (product rule): never lowered by the source class or the board
            out.append(Finding(rid, "failed", "danger", msg, refs, _sids(srcs)))
        else:
            out.append(ctx.finding(rid, "failed", "caution", msg, insts, source_id=srcs, chip_fact=False))
    return out
