"""Family rules ``net``: W5500, NEO-6M, NEO-M8N, SD card (SPI), SIM800L.

- ``mod.net.sim800_vbat``: SIM800L VBAT 3.4–4.4 V, abs max 4.5 V (Hardware Design V1.01 p. 53); below 3.4 V and
  above 4.4 V the module powers itself down (p. 24); transmit bursts draw up to 2 A (p. 20, p. 55). Above abs max
  (the 5 V rail) -> failed/danger; outside the operating range (the 3.3 V rail) -> failed/caution; in range but the
  rail's current limit (``options.rail_limits`` / board value) below the burst peak -> failed/caution. Supply
  findings (``supply=True``): a breakout without ``facts.regulator == "none"`` is capped by the severity cap. The two
  range findings carry ``supersedes = ("mod.supply_range",)``: one cause, one warning (the generic finding on the
  same module folds into this one).
- ``mod.net.sim800_vih``: the SIM800L I/O runs in its 2.8 V domain. An ESP pin that drives RXD pushes 3.3 V, above
  the serial port's VIH maximum 3.1 V (p. 28, Table 10); one that drives RESET pushes 3.3 V, above its VIH maximum
  2.0 V (p. 25). SIMCom recommends a resistor matching circuit for a 3.3 V UART (p. 29) -> failed/caution;
  ``facts.level_shifter`` -> passed. The two maxima are the top of the documented VIH ranges, not absolute maximum
  ratings (the document has none for the digital pins), so they are kept here instead of ``io.v_in_max`` (which
  ``mod.level_in`` treats as a damage limit); tests/test_mod_net.py pins them to the excerpt lines.
- ``mod.net.sd_spi_init_400k``: hint (info) for every SD card whose SCLK reaches an ESP pin: hold CS high for ≥ 74
  clocks, CMD0, then clock at 100–400 kHz until ACMD41 reports ready (Simplified Spec v6.00 p. 221, p. 94); the
  Default Speed limit afterwards comes from the catalog entry's ``f_max_hz``.
- W5500 current (about 130 mA at 100 Mbit/s) is no family rule: ``current`` in the catalog feeds the generic
  ``mod.power_budget`` (tests/test_mod_net.py checks the rail sums).
Supply ranges and currents come from the catalog entry (data/modules/net.json).
"""
from __future__ import annotations

from collections.abc import Mapping

from . import modcheck

Ctx, Finding, Instance, fmt, rule = modcheck.Ctx, modcheck.Finding, modcheck.Instance, modcheck.fmt, modcheck.rule

_EPS = 1e-9
SIM800 = "sim800l"
SUPPLY_RANGE = "mod.supply_range"  # generic range rule; sim800_vbat findings supersede it on the same ref
SDCARD = "sdcard"
# Top of the documented VIH ranges (SIM800L(MT6261) Hardware Design V1.01): serial port Table 10, p. 28
# "VIH 2.1 - 3.1  V"; RESET p. 25 "VIH 1.5 1.8 2.0 V". (signal, volts, page, what)
SIM800_VIH_MAX: dict[str, tuple[float, int, str]] = {
    "uart_rx": (3.1, 28, "serial-port VIH maximum"),
    "reset_in": (2.0, 25, "RESET VIH maximum"),
}
# SD Physical Layer Simplified Specification v6.00 p. 94: "Issue continuous clock in the frequency range of
# 100 KHz-400 KHz." (ACMD41 initialisation); p. 221: 74 clocks with CS high before CMD0.
SD_INIT_HZ = (100_000.0, 400_000.0)


def _supply_pin(inst: Instance) -> str | None:
    cur = inst.module.get("current")
    if isinstance(cur, Mapping) and isinstance(cur.get("supply"), str):
        return cur["supply"]
    sup = inst.module.get("supplies")
    return next(iter(sup), None) if isinstance(sup, Mapping) and sup else None


def _rail_limit(ctx: Ctx, net: str) -> tuple[float | None, str | None]:
    for e in ctx.rail_sums:
        if e.get("net") == net and isinstance(e.get("limit"), int | float):
            return float(e["limit"]), e.get("limit_source")
    lim = ctx.rail_limits.get(net)
    return (float(lim), "user") if isinstance(lim, int | float) else (None, None)


def _covers_supply_range(f: Finding) -> Finding:
    """The VBAT finding names the cause and the fix; the generic range finding on the same ref folds into it."""
    f.supersedes = (SUPPLY_RANGE,)
    return f


@rule("mod.net.sim800_vbat")
def sim800_vbat(ctx: Ctx) -> list[Finding]:
    rid = "mod.net.sim800_vbat"
    out: list[Finding] = []
    for inst in ctx.instances:
        if inst.module_id != SIM800:
            continue
        pin = _supply_pin(inst)
        spec = (inst.module.get("supplies") or {}).get(pin) if pin else None
        spec = spec if isinstance(spec, Mapping) else {}
        lo, hi, absmax = (ctx.fv(spec.get(k), inst) for k in ("min", "max", "abs_max"))
        net = ctx.net_of(inst, pin) if pin else None
        v = ctx.volts(net) if net else None
        cur = inst.module.get("current") if isinstance(inst.module.get("current"), Mapping) else {}
        peak_f = cur.get("peak") or cur.get("max")
        peak = ctx.fv(peak_f, inst)
        who = f"{ctx.label(inst)} {pin}"
        if v is None or lo is None or hi is None:
            out.append(Finding(rid, "not_checked", None, f"{who}: supply voltage unknown, VBAT range and 2 A bursts "
                               "not checked (name the rail voltage in options.rails).", [inst.ref]))
            continue
        burst = f"bursts up to {fmt(peak, 'A')}" if peak is not None else "transmit bursts"
        feed = (f"Feed {fmt(lo, 'V')}–{fmt(hi, 'V')} from a regulator rated for {burst} (or one Li-ion cell) with "
                "≥ 100 µF low-ESR next to VBAT")
        if absmax is not None and v > absmax + _EPS:
            out.append(_covers_supply_range(ctx.finding(
                rid, "failed", "danger",
                f"{who} on {net} = {fmt(v, 'V')}: above the absolute maximum {fmt(absmax, 'V')}, the SIM800L can be "
                f"damaged. {feed}.", inst, source_id=ctx.src(inst, spec.get("abs_max")), supply=True)))
        elif v > hi + _EPS or v < lo - _EPS:
            side = "above" if v > hi else "below"
            out.append(_covers_supply_range(ctx.finding(
                rid, "failed", "caution",
                f"{who} on {net} = {fmt(v, 'V')}: {side} the VBAT range {fmt(lo, 'V')}–{fmt(hi, 'V')}; the module "
                f"powers itself down (under-/over-voltage power down) and {burst} make the rail sag further. "
                f"{feed}.", inst, source_id=ctx.src(inst, spec.get("min" if side == "below" else "max")), supply=True)))
        else:
            limit, origin = _rail_limit(ctx, str(net))
            if peak is not None and limit is not None and limit < peak - _EPS:
                out.append(ctx.finding(
                    rid, "failed", "caution",
                    f"{who} on {net} = {fmt(v, 'V')}: in range, but the rail limit {fmt(limit, 'A')} ({origin}) is "
                    f"below the {fmt(peak, 'A')} transmit burst; the voltage drop can reset the module. Use a "
                    "supply rated for the burst and ≥ 100 µF low-ESR at VBAT.",
                    inst, source_id=ctx.src(inst, peak_f), supply=True))
            else:
                extra = f"; the supply must deliver {burst}" if limit is None else \
                    f"; rail limit {fmt(limit, 'A')} covers the {fmt(peak, 'A')} burst"
                out.append(Finding(rid, "passed", None, f"{who} on {net} = {fmt(v, 'V')}: within "
                                   f"{fmt(lo, 'V')}–{fmt(hi, 'V')}{extra}.", [inst.ref], [ctx.src(inst, spec.get('min'))]))
    return out


def _esp_driven(ctx: Ctx, net: str | None) -> bool:
    return bool(net) and bool((ctx.nets.get(net) or {}).get("gpios"))


@rule("mod.net.sim800_vih")
def sim800_vih(ctx: Ctx) -> list[Finding]:
    rid = "mod.net.sim800_vih"
    out: list[Finding] = []
    for inst in ctx.instances:
        if inst.module_id != SIM800:
            continue
        driven = [(p["name"], *SIM800_VIH_MAX[p["signal"]]) for p in inst.module.get("pins") or []
                  if isinstance(p, Mapping) and p.get("signal") in SIM800_VIH_MAX
                  and _esp_driven(ctx, inst.conn.get(p["name"]))]
        if not driven:
            continue
        names = ", ".join(n for n, *_ in driven)
        if (inst.facts or {}).get("level_shifter") is True:
            out.append(Finding(rid, "passed", None, f"{ctx.label(inst)} {names}: level shifter declared "
                               "(facts.level_shifter, user).", [inst.ref]))
            continue
        vdd = (ctx.esp or {}).get("vdd")
        if not isinstance(vdd, int | float):
            out.append(Finding(rid, "not_checked", None, f"{ctx.label(inst)} {names}: ESP supply unknown, the 2.8 V "
                               "input levels are not checked.", [inst.ref]))
            continue
        over = [(n, lim, page, what) for n, lim, page, what in driven if vdd > lim + _EPS]
        if not over:
            out.append(Finding(rid, "passed", None, f"{ctx.label(inst)} {names}: ESP high {fmt(vdd, 'V')} within "
                               "the VIH ranges.", [inst.ref], [ctx.src(inst)]))
            continue
        parts = "; ".join(f"{n}: ESP high {fmt(vdd, 'V')} is above the {what} {fmt(lim, 'V')} (p. {page})"
                          for n, lim, page, what in over)
        reset = any(what.startswith("RESET") for _, _, _, what in over)
        out.append(ctx.finding(
            rid, "failed", "caution",
            f"{ctx.label(inst)} runs its I/O at 2.8 V. {parts}. SIMCom recommends a resistor matching circuit for "
            "a 3.3 V UART (Hardware Design Fig. 21) or a level shifter"
            + ("; RESET idles at 1.8 V: drive it open-drain (pull low only)." if reset else "."),
            inst, source_id=ctx.src(inst)))
    return out


@rule("mod.net.sd_spi_init_400k")
def sd_spi_init_400k(ctx: Ctx) -> list[Finding]:
    rid = "mod.net.sd_spi_init_400k"
    out: list[Finding] = []
    lo, hi = SD_INIT_HZ
    for inst in ctx.instances:
        if inst.module_id != SDCARD:
            continue
        sck = ctx.pins_with(inst, "spi_sck")
        if not sck or not _esp_driven(ctx, inst.conn.get(sck[0])):
            continue
        spi = next((it for it in inst.module.get("interfaces") or []
                    if isinstance(it, Mapping) and it.get("type") == "spi"), {})
        fmax = ctx.fv(spi.get("f_max_hz"), inst)
        after = f", then at most {fmt(fmax, 'Hz')} (Default Speed)" if fmax is not None else ""
        out.append(ctx.finding(
            rid, "failed", "info",
            f"{ctx.label(inst)}: initialise the card slowly: CS high for at least 74 clocks after power-up, CMD0 "
            f"with CS low to enter SPI mode, then {fmt(lo, 'Hz')}–{fmt(hi, 'Hz')} until ACMD41 reports ready"
            f"{after}. Arduino/ESP-IDF SD drivers do this; a hand-written driver must too.",
            inst, source_id=ctx.src(inst, spi.get("f_max_hz")), chip_fact=False))
    return out
