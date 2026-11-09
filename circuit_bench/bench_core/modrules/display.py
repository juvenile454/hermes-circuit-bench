"""Family rules ``display``: OLED controllers, HD44780, MAX7219, TM1637.

Every rule reads the catalog entries of data/modules/display.json and the project nets only; sources are the
display datasheets in data/sources/mod-display.json (pages in the messages).

- ``mod.display.sh1106_vs_ssd1306`` (info): an SSD1306 may in fact be an SH1106 (1.3" modules).
- ``mod.display.oled_two_per_bus`` (caution): more than two 0x3C/0x3D OLED controllers on one visible bus path;
  complements ``mod.address_conflict`` with the fix (second bus or mux), since no third address exists.
- ``mod.display.hd44780_rw_gnd`` (danger/caution): R/W of an HD44780 on a GPIO, open or high while VCC is above
  the ESP's input maximum: reading drives DB0–DB7 to VCC.
- ``mod.display.max7219_vih`` (caution): VIH 3.5 V at V+ = 5 V ±10 % against the ESP's output high; other V+ ->
  not_checked (the datasheet gives no threshold there; no interpolation). It supersedes the generic ``mod.level_in``
  on the same chip (one cause, one warning); the data's VIH ``conditions`` name 4.5–5.5 V so the generic rule also
  stays silent outside that range.
- ``mod.display.tm1637_not_i2c`` (caution): CLK/DIO of a TM1637 on an I²C net.
"""
from __future__ import annotations

from typing import Any

from . import modcheck

Ctx, Finding, Instance, fmt, rule = modcheck.Ctx, modcheck.Finding, modcheck.Instance, modcheck.fmt, modcheck.rule

SRC_SSD1306 = "mod-display-ssd1306-ds"
SRC_SH1106 = "mod-display-sh1106-ds"
SRC_HD44780 = "mod-display-hd44780-ds"
SRC_MAX7219 = "mod-display-max7219-ds"
SRC_TM1637_EN = "mod-display-tm1637-en"

OLED_ADDRESSES = frozenset({"0x3c", "0x3d"})  # SA0 = 0 / 1 (SSD1306 p. 19, SH1106 p. 13, SSD1309 p. 19)
HD_DATA_PINS = tuple(f"DB{i}" for i in range(8))
MAX7219_INPUTS = ("DIN", "CLK", "LOAD")
MAX7219_VIH_RANGE = (4.5, 5.5)  # "V+ = 5V ±10%" (MAX7219 p. 3): VIH 3.5 V holds only there


def _of(ctx: Ctx, module_id: str) -> list[Instance]:
    return [i for i in ctx.instances if i.module_id == module_id]


def _gpios(ctx: Ctx, net: str | None) -> list[int]:
    return list((ctx.nets.get(net) or {}).get("gpios") or []) if net else []


def _gpio_text(pins: list[int]) -> str:
    return ", ".join(f"GPIO{p}" for p in sorted(set(pins)))


def _is_oled(inst: Instance) -> bool:
    if inst.module.get("category") != "display.oled":
        return False
    it = modcheck.i2c_iface(inst.module)
    return bool(it) and set(modcheck.addresses(it)) == OLED_ADDRESSES


# --- SSD1306 vs SH1106 ---------------------------------------------------------------------------------------------
@rule("mod.display.sh1106_vs_ssd1306")
def sh1106_vs_ssd1306(ctx: Ctx) -> list[Finding]:
    out = []
    for inst in _of(ctx, "ssd1306"):
        out.append(ctx.finding(
            "mod.display.sh1106_vs_ssd1306", "failed", "info",
            f"{ctx.label(inst)}: 1.3\" 128x64 OLED modules often carry an SH1106 (132-column RAM, same addresses "
            "0x3C/0x3D; SH1106 datasheet p. 1). If the image is shifted or garbled, use module sh1106 and an "
            "SH1106 driver.", inst, source_id=SRC_SH1106, chip_fact=False))
    return out


# --- more than two OLEDs on one bus path ---------------------------------------------------------------------------
def _path(ctx: Ctx, seg: str) -> list[str]:
    """The segment and its ancestors up to ``main`` (devices on this path all see each other)."""
    out, cur = [seg], seg
    while cur != "main" and len(out) < 33:
        cur = ctx.parents.get(cur, "main")
        out.append(cur)
    return out


@rule("mod.display.oled_two_per_bus")
def oled_two_per_bus(ctx: Ctx) -> list[Finding]:
    oleds = [i for i in ctx.instances if _is_oled(i) and i.ref in ctx.placement]
    if not oleds:
        return []
    groups: list[tuple[str, str, list[Instance]]] = []
    for bus in ctx.buses:
        on_bus = [i for i in oleds if ctx.placement[i.ref][0] == bus["id"]]
        for seg in (s["id"] for s in bus.get("segments") or []):
            path = set(_path(ctx, seg))
            members = [i for i in on_bus if ctx.placement[i.ref][1] in path]
            if members:
                groups.append((bus["id"], seg, members))
    out: list[Finding] = []
    reported: list[frozenset[str]] = []
    # largest groups first, so a subset (e.g. "main" alone) is not reported again
    for bus_id, seg, members in sorted(groups, key=lambda g: -sum(i.qty for i in g[2])):
        n = sum(i.qty for i in members)
        refs = frozenset(i.ref for i in members)
        if n <= 2 or any(refs <= r for r in reported):
            continue
        reported.append(refs)
        where = bus_id if seg == "main" else f"{bus_id} (segment {seg})"
        out.append(ctx.finding(
            "mod.display.oled_two_per_bus", "failed", "caution",
            f"{n} OLED controllers ({', '.join(ctx.label(i) for i in members)}) on {where}: SSD1306/SH1106/SSD1309 "
            "offer only 0x3C and 0x3D (SA0), so at most two fit on one bus path. Put the others on a second I²C "
            "bus or behind an I²C mux.", members, source_id=[ctx.src(i) for i in members], chip_fact=False))
    if not out:
        out.append(Finding("mod.display.oled_two_per_bus", "passed", None,
                           "At most two 0x3C/0x3D OLED controllers per bus path.", [i.ref for i in oleds],
                           [SRC_SSD1306]))
    return out


# --- HD44780 R/W -------------------------------------------------------------------------------------------------
@rule("mod.display.hd44780_rw_gnd")
def hd44780_rw_gnd(ctx: Ctx) -> list[Finding]:
    rid = "mod.display.hd44780_rw_gnd"
    out = []
    for inst in _of(ctx, "hd44780"):
        rw = ctx.net_of(inst, "RW")
        db_gpios = [g for p in HD_DATA_PINS for g in _gpios(ctx, ctx.net_of(inst, p))]
        vcc = ctx.supply_volts(inst).get("VCC")
        vmax = (ctx.esp or {}).get("v_in_max")
        if rw is not None and ctx.volts(rw) == 0:
            out.append(Finding(rid, "passed", None, f"{ctx.label(inst)}: R/W on {rw}: write-only, DB pins are "
                               "inputs.", [inst.ref], [SRC_HD44780]))
            continue
        rw_gpios = _gpios(ctx, rw)
        rw_high = rw is None or (not rw_gpios and (ctx.volts(rw) or 0) > 0)  # open (internal pull-up) or tied high
        if not rw_gpios and not rw_high:
            out.append(Finding(rid, "not_checked", None, f"{ctx.label(inst)}: R/W on net {rw}, neither GND nor an "
                               "ESP GPIO.", [inst.ref], [SRC_HD44780]))
            continue
        if not db_gpios:
            out.append(Finding(rid, "passed", None, f"{ctx.label(inst)}: no data pin on an ESP GPIO.", [inst.ref],
                               [SRC_HD44780]))
            continue
        if vcc is None or vmax is None:
            why = "VCC unknown" if vcc is None else f"no electrical data for {ctx.chip}"
            out.append(Finding(rid, "not_checked", None, f"{ctx.label(inst)}: {why}; R/W should go to GND.",
                               [inst.ref], [SRC_HD44780]))
            continue
        over = vcc > vmax and not (inst.facts or {}).get("level_shifter")
        db_text = _gpio_text(db_gpios)
        if rw_high:
            what = "R/W is open: its internal pull-up selects read (p. 54)" if rw is None else \
                f"R/W is tied to {rw}: always read"
            if over:
                msg = (f"{ctx.label(inst)}: {what}, so the HD44780 drives DB0–DB7 up to VCC {fmt(vcc, 'V')} into "
                       f"{db_text} (ESP input max {fmt(vmax, 'V')}). Tie R/W to GND.")
                out.append(ctx.finding(rid, "failed", "danger", msg, inst, source_id=SRC_HD44780))
            else:
                out.append(ctx.finding(rid, "failed", "caution",
                                       f"{ctx.label(inst)}: {what}; the display never accepts data. Tie R/W to GND.",
                                       inst, source_id=SRC_HD44780))
            continue
        if over:
            msg = (f"{ctx.label(inst)}: R/W on {_gpio_text(rw_gpios)} at VCC {fmt(vcc, 'V')}: every read (R/W high, "
                   f"e.g. busy-flag polling) makes the HD44780 drive DB0–DB7 up to {fmt(vcc, 'V')} into {db_text} "
                   f"(ESP input max {fmt(vmax, 'V')}). Tie R/W to GND (write-only) or level-shift the data bus.")
            out.append(ctx.finding(rid, "failed", "danger", msg, inst, source_id=SRC_HD44780))
        else:
            reason = "a level shifter is confirmed (facts.level_shifter)" if vcc > vmax else \
                f"VCC {fmt(vcc, 'V')} is within the ESP input max {fmt(vmax, 'V')}"
            out.append(Finding(rid, "passed", None, f"{ctx.label(inst)}: R/W on a GPIO, {reason}.", [inst.ref],
                               [SRC_HD44780]))
    return out


# --- MAX7219 VIH -------------------------------------------------------------------------------------------------
@rule("mod.display.max7219_vih")
def max7219_vih(ctx: Ctx) -> list[Finding]:
    rid = "mod.display.max7219_vih"
    out = []
    for inst in _of(ctx, "max7219"):
        driven = {p: _gpios(ctx, ctx.net_of(inst, p)) for p in MAX7219_INPUTS}
        driven = {p: g for p, g in driven.items() if g}
        if not driven:
            continue
        refs = [inst.ref]
        vplus = ctx.supply_volts(inst).get("V+")
        esp: dict[str, Any] = ctx.esp or {}
        vih = ctx.level(inst, "vih")
        if vplus is None:
            out.append(Finding(rid, "not_checked", None, f"{ctx.label(inst)}: V+ unknown.", refs, [SRC_MAX7219]))
            continue
        lo, hi = MAX7219_VIH_RANGE
        if not lo <= vplus <= hi:
            out.append(Finding(rid, "not_checked", None,
                               f"{ctx.label(inst)}: V+ {fmt(vplus, 'V')}: the datasheet gives VIH only for V+ = 5 V "
                               "±10 % (4.5–5.5 V, p. 3); no threshold for this supply.", refs, [SRC_MAX7219]))
            continue
        if vih is None or esp.get("voh") is None or esp.get("vdd") is None:
            out.append(Finding(rid, "not_checked", None, f"{ctx.label(inst)}: VIH or ESP output levels unknown.",
                               refs, [SRC_MAX7219]))
            continue
        pins = ", ".join(f"{p} on {_gpio_text(g)}" for p, g in driven.items())
        if (inst.facts or {}).get("level_shifter"):
            out.append(Finding(rid, "passed", None, f"{ctx.label(inst)}: level shifter confirmed for {pins}.", refs,
                               [SRC_MAX7219]))
        elif vih > esp["voh"]:
            beyond = "above the ESP supply" if vih > esp["vdd"] else "above the ESP's guaranteed output high"
            msg = (f"{ctx.label(inst)} at V+ {fmt(vplus, 'V')}: VIH {fmt(vih, 'V')} (V+ = 5 V ±10 %, p. 3) is {beyond} "
                   f"(VOH min {fmt(esp['voh'], 'V')}, VDD {fmt(esp['vdd'], 'V')}); {pins} are out of spec. Use a "
                   "5 V-input buffer such as 74AHCT125 between the ESP and DIN/CLK/LOAD.")
            out.append(ctx.finding(rid, "failed", "caution", msg, inst, source_id=SRC_MAX7219))
        else:
            out.append(Finding(rid, "passed", None, f"{ctx.label(inst)}: VIH {fmt(vih, 'V')} ≤ ESP VOH "
                               f"{fmt(esp['voh'], 'V')}.", refs, [SRC_MAX7219]))
    for f in out:
        f.supersedes = ("mod.level_in",)  # same VIH on the same chip; this rule names the V+ range and the fix
    return out


# --- TM1637 is not I²C -------------------------------------------------------------------------------------------
def _i2c_nets(ctx: Ctx) -> set[str]:
    nets = {n for n, d in ctx.nets.items() if {"i2c_sda", "i2c_scl"} & set(d.get("modes") or [])}
    for bus in ctx.buses:
        nets |= {n for n in (bus.get("nets") or {}).values() if n}
    for inst in ctx.instances:
        for p in ctx.pins_with(inst, "i2c_sda") + ctx.pins_with(inst, "i2c_scl"):
            if inst.conn.get(p):
                nets.add(inst.conn[p])
    return nets


@rule("mod.display.tm1637_not_i2c")
def tm1637_not_i2c(ctx: Ctx) -> list[Finding]:
    rid = "mod.display.tm1637_not_i2c"
    insts = _of(ctx, "tm1637")
    if not insts:
        return []
    i2c = _i2c_nets(ctx)
    out = []
    for inst in insts:
        nets = {p: ctx.net_of(inst, p) for p in ("CLK", "DIO")}
        if not any(nets.values()):
            continue
        hit = {p: n for p, n in nets.items() if n in i2c}
        if hit:
            on = ", ".join(f"{p} on {n}" for p, n in hit.items())
            out.append(ctx.finding(
                rid, "failed", "caution",
                f"{ctx.label(inst)}: {on}, an I²C net. The TM1637 two-wire bus is not I²C (no slave address, "
                "V2.4 p. 3): sharing it disturbs the I²C devices and the display. Give CLK and DIO their own GPIOs.",
                inst, source_id=SRC_TM1637_EN, chip_fact=False))
        else:
            out.append(Finding(rid, "passed", None, f"{ctx.label(inst)}: CLK/DIO off the I²C nets.", [inst.ref],
                               [SRC_TM1637_EN]))
    return out
