"""Generic bus rules.

Rules, warning codes and severities (every finding cites the module data it rests on: ``ctx.src``; caps via
``ctx.finding``, address and role facts with ``chip_fact=False`` because they do not depend on the breakout):

Bus topology (``_topology``): like ``modcheck._buses``, but a bridge is transparent. Bridges (``_bridge_pairs``): a
part without mux channels with exactly two SDA (two SCL) pins (PCA9306 SDA1/SDA2) and, in category
``logic.level_shifter``, the pin pairs A<n>/B<n> (TXS0108E, TXB0104, SN74LVC1T45/8T245) and S/D (BSS138). Devices
behind a bridge sit on the bus segment in front of it; buffers (nA -> nY: 74AHCT125, 74LVC125A) are no bridge.

- ``mod.address_conflict`` (``mod_address_conflict``): the same 7-bit address on segments that see each other
  (a segment sees its ancestors, ``main`` sees every mux channel, two channels never see each other) ->
  failed/caution (the bus cannot reach both devices, damage is not proven; same reasoning as
  pin_role); the text names the way out (address pin with the free addresses, a second bus, an I²C mux). Equal
  addresses on different channels -> passed with the hint to select one channel at a time. A device on the bus
  without address data -> not_checked/info.
- ``mod.address_reserved`` (``mod_address_reserved``): a device's address hits ``interfaces[].reserved`` of another
  device on a visible segment (PCA9685 All-Call 0x70 against a TCA9548A at 0x70) -> failed/caution (as above). A
  device without address next to a reserving one -> not_checked (no warning; mod.address_conflict reports it).
- ``mod.address_select`` (``mod_address_select``): ``select.pin`` / ``select.pins`` (multi-pin, comma keys) against
  the nets: a ``must_connect`` select pin is open -> failed/caution; ``parts[].address`` contradicts the select-pin
  nets (or an open pin's default) -> failed/caution; ``address`` not in ``addresses`` -> failed/caution; a select pin
  on a net that ``select.map`` does not name -> not_checked/info (address assumed = default). refs = the module ref
  (family rules supersede it there, e.g. env.bme680_sdo_float).
- ``mod.bus_speed`` (``mod_bus_speed``): the smallest ``f_max_hz`` on the bus is its clock limit, with the parts that
  set it. Below I²C Fast-mode (400 kHz, NXP UM10204) -> failed/info; devices without ``f_max_hz`` -> not_checked
  (no warning); else passed. Bridges without an I²C interface set no limit.
- ``mod.pin_role`` (``mod_pin_role``): the module pin's signal does not fit the ESP modes on its net
  (``modspec.SIGNAL_MODES``; UART not crossed, SDA/SCL or MOSI/MISO swapped) -> failed/caution (nothing works, no
  damage proven); a push-pull module output against an ESP output -> failed/danger (two drivers short the supply when
  the levels differ). Behind a bridge the ESP modes of the far side count (caution only). Level-shifter channel pins
  (non-bus signals on a bridge pair) pass either direction. A pin with an unknown signal -> not_checked.
- ``mod.net_shared_signals`` (``mod_net_shared_signals``): two ESP assignments with different bus lines (SDA/SCL,
  SCK/MOSI/MISO/CS) on one net, or one module whose different bus-line pins share a net -> failed/danger (the lines
  are shorted); MOSI+MISO (SDI+SDO) only -> failed/caution (3-wire SPI does this on purpose). Supersedes
  ``mod.pin_role`` on the same refs (one cause, one warning).
- ``mod.spi_cs`` (``mod_spi_cs``): two SPI devices on one chip-select net -> failed/danger when they also share a
  data-out (SDO/MISO) net (both drive it at once), else failed/caution; CS tied to a rail on a shared SPI bus (always
  or never selected; CS assumed active low unless ``active_low`` is false) -> failed/caution; CS open or no CS pin in
  the data -> not_checked (no warning; mod.unconnected reports the open pin).
- ``mod.unconnected`` (``mod_unconnected``): supply/GND pin without net, a ``must_connect`` pin open, an input of a
  half-wired interface open, a floating single input (no ``tie``, no ``internal_pull``), no signal pin connected at
  all, a mux channel with only one line wired -> failed/caution; a receive-only UART (module RX open) or an open
  mode-select pin of a breakout board (kind ``module``: the board often wires it) -> failed/info. An input net with
  no ESP assignment counts as defined (``_defined``, through series resistors and level-shifter channels) by a rail
  (pull-up/pull-down), an ESP pin, a module supply/GND pin or another module's signal pin / an active part; else ->
  failed/caution "Typo in the net name?". An I²C pin needs a bus net, a mux channel net or a net behind a bridge. A
  module output nobody reads -> failed/info (no typo text). Project mistakes: a ref used twice, a ``conn`` value that
  is no text (or a ``conn`` that is no map) -> failed/caution instead of silently open pins. No pin list ->
  not_checked.
"""
from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import replace
from typing import Any

from . import modcheck

Ctx, Finding, Instance, addresses, fmt, i2c_iface, norm_address, rule = (
    modcheck.Ctx, modcheck.Finding, modcheck.Instance, modcheck.addresses, modcheck.fmt, modcheck.i2c_iface,
    modcheck.norm_address, modcheck.rule)
SIGNAL_MODES: Mapping[str, tuple[str, ...]] = modcheck.modspec.SIGNAL_MODES
SIGNAL_DIRECTION: Mapping[str, str] = modcheck.modspec.SIGNAL_DIRECTION

FAST_MODE_HZ = 400_000.0  # I²C Fast-mode, NXP UM10204 (source nxp-um10204)
I2C_SPEC_SOURCE = "nxp-um10204"
# ESP modes that drive the net push-pull (I²C on the ESP is open drain, inputs and ADC do not drive)
ESP_DRIVES = frozenset({"out", "pwm", "uart_tx", "spi_mosi", "spi_sck", "spi_cs"})
PASSIVE_KINDS = frozenset({"resistor", "capacitor", "inductor", "ferrite"})  # plain parts that drive no signal
GROUPS: dict[str, tuple[str, ...]] = {  # signals that only work together (one interface)
    "i2c": ("i2c_sda", "i2c_scl"),
    "spi": ("spi_sck", "spi_cs", "spi_sdi", "spi_sdo"),
    "uart": ("uart_rx", "uart_tx"),
    "i2s": ("i2s_bclk", "i2s_ws", "i2s_din", "i2s_dout"),
}
GROUP_OF = {sig: g for g, sigs in GROUPS.items() for sig in sigs}
POWER = ("supply", "gnd")
NO_PIN_CHECK = frozenset({"nc", "power_out", "analog_in", "addr_select"})  # open is fine / checked elsewhere
SINGLE_INPUTS = frozenset({"digital_in", "pwm_in", "led_data_in", "reset_in", "enable_in", "onewire"})
MAX_MAP_SHOWN = 4
MAX_ALTS_SHOWN = 2  # other addresses named per device in mod.address_conflict (the message stays short)
LEVEL_SHIFTER = "logic.level_shifter"  # catalog category of level shifters and buffers
_A_SIDE = re.compile(r"^A(\d*)$")  # A<n> pairs with B<n> on a level shifter
_GPIO_TEXT = re.compile(r"^GPIO(\d{1,3})$")
MAX_REACH = 64  # nets/segments followed through resistors, bridges and muxes (guard against odd projects)
MAX_PASSED_REFS = 8
MAX_LINK_DEPTH = 4  # resistor/bridge hops when looking for what defines a net
# ESP bus modes that must never share one net with another of them (each line needs its own net)
LINE_NAMES = {"i2c_sda": "SDA", "i2c_scl": "SCL", "spi_sck": "SCK", "spi_mosi": "MOSI", "spi_miso": "MISO",
              "spi_cs": "CS", "spi_sdi": "SDI", "spi_sdo": "SDO"}
ESP_LINES = frozenset({"i2c_sda", "i2c_scl", "spi_sck", "spi_mosi", "spi_miso", "spi_cs"})
MODULE_LINES = frozenset({"i2c_sda", "i2c_scl", "spi_sck", "spi_sdi", "spi_sdo", "spi_cs"})
THREE_WIRE = ({"spi_mosi", "spi_miso"}, {"spi_sdi", "spi_sdo"})  # data in + out on one net: 3-wire SPI


# --- helpers ------------------------------------------------------------------------------------------------------
def _uniq(items: Iterable[Any]) -> list[Any]:
    out: list[Any] = []
    for x in items:
        if x not in out:
            out.append(x)
    return out


def _pins(module: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    return [p for p in module.get("pins") or [] if isinstance(p, Mapping) and isinstance(p.get("name"), str)]


def _iface_source(ctx: Ctx, inst: Instance) -> str | None:
    """Source of the interface's address data: ``addresses`` F, else the module's first source."""
    it = i2c_iface(inst.module) or {}
    return ctx.src(inst, it.get("addresses"))


def _select(it: Mapping[str, Any]) -> tuple[list[str], dict[str, Any]] | None:
    """(select pins, map) of an I²C interface: ``select.pin`` or ``select.pins`` (multi-pin, comma keys)."""
    sel = it.get("select")
    if not isinstance(sel, Mapping) or not isinstance(sel.get("map"), Mapping):
        return None
    if isinstance(sel.get("pins"), list):
        pins = [p for p in sel["pins"] if isinstance(p, str)]
    else:
        pins = [sel["pin"]] if isinstance(sel.get("pin"), str) else []
    return (pins, dict(sel["map"])) if pins else None


def _map_text(pins: list[str], smap: Mapping[str, Any]) -> str:
    rows = []
    for key, addr in smap.items():
        a = norm_address(addr)
        if not a or not isinstance(key, str):
            continue
        keys = [k.strip() for k in key.split(",")] if len(pins) > 1 else [key]
        rows.append((" ".join(f"{p}={k}" for p, k in zip(pins, keys, strict=False)) if len(pins) > 1 else key, a))
    text = ", ".join(f"{k} → {a}" for k, a in rows[:MAX_MAP_SHOWN])
    return text + (", …" if len(rows) > MAX_MAP_SHOWN else "")


def _key_for(pins: list[str], smap: Mapping[str, Any], addr: str) -> str | None:
    """'SDO to VDDIO' / 'A1 to GND, A0 to VDD': the select connection that gives ``addr``."""
    for key, a in smap.items():
        if norm_address(a) == addr and isinstance(key, str):
            keys = [k.strip() for k in key.split(",")] if len(pins) > 1 else [key]
            return ", ".join(f"{p} to {k}" for p, k in zip(pins, keys, strict=False))
    return None


def _alternatives(inst: Instance, used: set[str]) -> list[str]:
    """Other addresses of the interface, with the select-pin connection that sets each when the data has one."""
    it = i2c_iface(inst.module) or {}
    sel = _select(it)
    out = []
    for a in addresses(it):
        if a == inst.address or a in used:
            continue
        how = _key_for(sel[0], sel[1], a) if sel else None
        out.append(f"{a} ({how})" if how else a)
    return out


def _labels(insts: list[Instance]) -> str:
    """'U1, U9 (bme280), U3 (mpu6050)': refs grouped by module, order kept."""
    groups: dict[str, list[str]] = {}
    for i in insts:
        groups.setdefault(i.module_id, []).append(i.ref)
    return ", ".join(f"{', '.join(refs)} ({mid})" for mid, refs in groups.items())


def _where(bus_id: str, segs: Iterable[str]) -> str:
    s = _uniq(segs)
    if s == ["main"]:
        return f"bus {bus_id}"
    if len(s) == 1:
        return f"bus {bus_id} segment {s[0]}"
    return f"bus {bus_id} across segments {', '.join(s)} (a segment sees the segments above it)"


def _on_net(ctx: Ctx, net: str) -> str:
    """'SDA0 (GPIO8)' or 'GPIO8' when the net is named after its GPIO."""
    g = "/".join(f"GPIO{n}" for n in _uniq(ctx.nets.get(net, {}).get("gpios") or []))
    return net if not g or g == net else f"{net} ({g})"


# --- bridges (level shifters, I²C buffers) and the bus topology through them --------------------------------------
def _bridge_pairs(inst: Instance) -> list[tuple[str, str]]:
    """Two-way channel pairs of a bridge: a part without mux channels with exactly two SDA (and two SCL) pins
    (PCA9306 SDA1/SDA2, SCL1/SCL2), and in category ``logic.level_shifter`` A<n>/B<n> (TXS0108E, TXB0104,
    SN74LVC1T45/8T245: auto or DIR-set direction) and S/D (BSS138). Buffers (nA -> nY) are no bridge: their output
    pin drives the far net and their input is a plain input."""
    pins = [p for p in _pins(inst.module)]
    names = {p["name"] for p in pins}
    out: list[tuple[str, str]] = []
    if not modcheck.mux_channels(i2c_iface(inst.module)):
        for sig in ("i2c_sda", "i2c_scl"):
            same = [p["name"] for p in pins if p.get("signal") == sig]
            if len(same) == 2:
                out.append((same[0], same[1]))
    if inst.module.get("category") == LEVEL_SHIFTER:
        for n in sorted(names):
            m = _A_SIDE.match(n)
            if m and f"B{m.group(1)}" in names:
                out.append((n, f"B{m.group(1)}"))
        if {"S", "D"} <= names:
            out.append(("S", "D"))
    return _uniq(out)


def _plain_net(ctx: Ctx, v: Any) -> str | None:
    """Net of a plain part's conn value, resolved like the engine does (GPIO<n> -> the assigned net)."""
    if not isinstance(v, str) or not v.strip():
        return None
    v = v.strip()
    m = _GPIO_TEXT.match(v)
    if m:
        for a in ctx.assignments:
            if a.get("pin") == int(m.group(1)):
                return str(a["net"])
    return v


class _Graph:
    """Nets joined by resistors (two-terminal plain parts) and by bridge channels, the pins on bridge channels."""

    def __init__(self, ctx: Ctx):
        self.resistors: dict[str, list[str]] = {}
        self.bridges: dict[str, list[str]] = {}
        self.bridge_pins: set[tuple[str, str]] = set()
        for p in ctx.parts:
            conn = p.get("conn")
            if p.get("module") or p.get("kind") != "resistor" or not isinstance(conn, Mapping):
                continue
            nets = [n for n in (_plain_net(ctx, v) for v in conn.values()) if n]
            if len(nets) == 2 and nets[0] != nets[1]:
                self.resistors.setdefault(nets[0], []).append(nets[1])
                self.resistors.setdefault(nets[1], []).append(nets[0])
        for inst in ctx.instances:
            for a, b in _bridge_pairs(inst):
                self.bridge_pins |= {(inst.ref, a), (inst.ref, b)}
                na, nb = inst.conn.get(a), inst.conn.get(b)
                if na and nb and na != nb and na not in ctx.rails and nb not in ctx.rails:
                    self.bridges.setdefault(na, []).append(nb)
                    self.bridges.setdefault(nb, []).append(na)

    def through_bridges(self, nets: Iterable[str]) -> list[str]:
        """The nets plus every net behind a bridge channel (transitively), order kept."""
        out = _uniq(nets)
        i = 0
        while i < len(out) and len(out) < MAX_REACH:
            for n in self.bridges.get(out[i], []):
                if n not in out:
                    out.append(n)
            i += 1
        return out


def _topology(ctx: Ctx, graph: _Graph | None = None) -> list[dict[str, Any]]:
    """Per bus of ``ctx.buses``: ``devices`` [(Instance, segment id)], ``parents`` {segment: parent} and the I²C
    nets ``sda``/``scl``. Like ``modcheck._buses``, but a bridge (level shifter, PCA9306) is transparent: devices
    behind it sit on the bridge's segment, muxes behind it open their channels."""
    g = graph or _Graph(ctx)
    lines = {}
    for inst in ctx.instances:
        sda = next((p["name"] for p in _pins(inst.module) if p.get("signal") == "i2c_sda"), None)
        lines[id(inst)] = inst.conn.get(sda) if sda else None
    placed: set[int] = set()
    out = []
    for bus in ctx.buses:
        devices: list[tuple[Instance, str]] = []
        parents: dict[str, str] = {}
        sda_nets: list[str] = []
        scl_nets: list[str] = g.through_bridges([bus["nets"]["SCL"]] if bus["nets"].get("SCL") else [])
        queue: list[tuple[str, str]] = [("main", bus["nets"]["SDA"])]
        while queue:
            seg, net = queue.pop(0)
            nets = [n for n in g.through_bridges([net]) if n not in sda_nets]
            sda_nets += nets
            members = [i for i in ctx.instances if lines[id(i)] in nets and id(i) not in placed]
            for i in members:
                placed.add(id(i))
                devices.append((i, seg))
            for i in members:
                for ch, ch_sda, ch_scl in modcheck.mux_channels(i2c_iface(i.module)):
                    ch_net = i.conn.get(ch_sda)
                    if ch_net and ch_net not in sda_nets and len(parents) < MAX_REACH:
                        child = f"{i.ref}.{ch}"
                        parents[child] = seg
                        queue.append((child, ch_net))
                    if ch_scl and i.conn.get(ch_scl):
                        scl_nets += [n for n in g.through_bridges([i.conn[ch_scl]]) if n not in scl_nets]
        out.append({"bus": bus, "devices": devices, "parents": parents, "sda": sda_nets, "scl": scl_nets})
    return out


def _seg_visible(topo: Mapping[str, Any], a: str, b: str) -> bool:
    """Like ``Ctx.visible`` on the bridge-aware segments: same segment or one an ancestor of the other."""
    def up(seg: str) -> list[str]:
        chain, cur = [], seg
        while cur in topo["parents"] and len(chain) < MAX_REACH:
            cur = topo["parents"][cur]
            chain.append(cur)
        return chain
    return a == b or a in up(b) or b in up(a)


def _segments(topo: Mapping[str, Any]) -> list[tuple[str, list[Instance]]]:
    segs: dict[str, list[Instance]] = {"main": []}
    for seg in topo["parents"]:
        segs.setdefault(seg, [])
    for inst, seg in topo["devices"]:
        segs.setdefault(seg, []).append(inst)
    return list(segs.items())


# --- mod.address_conflict ------------------------------------------------------------------------------------------
@rule("mod.address_conflict")
def address_conflict(ctx: Ctx) -> list[Finding]:
    out: list[Finding] = []
    for topo in _topology(ctx):
        bus, devs = topo["bus"], topo["devices"]
        if not devs:
            continue
        for inst, seg in devs:
            if inst.address is None and i2c_iface(inst.module) is not None:  # no interface: a passive bridge
                out.append(Finding("mod.address_conflict", "not_checked", "info",
                                   f"{ctx.label(inst)}: no I²C address in the module data; address conflicts on "
                                   f"{_where(bus['id'], [seg])} not checked.", [inst.ref],
                                   [s for s in [ctx.src(inst)] if s]))
        known = [(i, s) for i, s in devs if i.address]
        by_addr: dict[str, list[tuple[Instance, str]]] = {}
        for i, s in known:
            by_addr.setdefault(i.address or "", []).append((i, s))
        clashed: set[str] = set()
        separated: list[tuple[str, list[tuple[Instance, str]]]] = []
        clashes: list[tuple[str, list[tuple[Instance, str]]]] = []
        for addr in sorted(by_addr):
            members = by_addr[addr]
            if len(members) < 2:
                continue
            parent = list(range(len(members)))

            def find(x: int, parent: list[int] = parent) -> int:
                while parent[x] != x:
                    x = parent[x]
                return x
            hidden = False
            for a in range(len(members)):
                for b in range(a + 1, len(members)):
                    if _seg_visible(topo, members[a][1], members[b][1]):
                        parent[find(b)] = find(a)
                    else:
                        hidden = True
            comps: dict[int, list[tuple[Instance, str]]] = {}
            for n, m in enumerate(members):
                comps.setdefault(find(n), []).append(m)
            for comp in comps.values():
                if len(comp) > 1:
                    clashes.append((addr, comp))
                    clashed |= {i.ref for i, _ in comp}
            if hidden:
                separated.append((addr, members))
        for addr, comp in clashes:
            insts = [i for i, _ in comp]
            alts: dict[str, list[str]] = {}
            for i, s in comp:
                used = {d.address for d, ds in known if d.address and _seg_visible(topo, s, ds)}
                x = _alternatives(i, used)
                if x:
                    alts.setdefault(", ".join(x[:MAX_ALTS_SHOWN]) + (", …" if len(x) > MAX_ALTS_SHOWN else ""),
                                    []).append(i.ref)
            hint = (" Fix: address pin (" + "; ".join(f"{', '.join(refs)}: {x}" for x, refs in alts.items())
                    + "), a second I²C bus or behind an I²C mux." if alts else
                    " No other address: use a second I²C bus or put one behind an I²C mux.")
            out.append(ctx.finding("mod.address_conflict", "failed", "caution",
                                   f"{_labels(insts)} answer at the same address {addr} on "
                                   f"{_where(bus['id'], [s for _, s in comp])}.{hint}",
                                   insts, source_id=[_iface_source(ctx, i) for i in insts], chip_fact=False))
        for seg_id, seg_insts in _segments(topo):
            sdevs = [i for i in seg_insts if i.address]
            if not sdevs or any(i.ref in clashed for i in sdevs):
                continue
            out.append(Finding("mod.address_conflict", "passed", None,
                               f"{len(sdevs)} device(s) on {_where(bus['id'], [seg_id])}, addresses unique "
                               f"({', '.join(sorted({i.address or '' for i in sdevs}))}).", [i.ref for i in sdevs]))
        for addr, members in separated:
            hidden_refs = [i for i, s in members if i.ref not in clashed]
            if len(hidden_refs) < 2:
                continue
            out.append(Finding("mod.address_conflict", "passed", None,
                               f"{', '.join(f'{i.ref} ({s})' for i, s in members if i.ref not in clashed)} share "
                               f"{addr} on bus {bus['id']} behind different mux channels: no conflict while only one "
                               "of these channels is selected at a time.", [i.ref for i in hidden_refs]))
    return out


# --- mod.address_reserved ------------------------------------------------------------------------------------------
def _reserved(inst: Instance) -> list[str]:
    it = i2c_iface(inst.module) or {}
    r = it.get("reserved")
    if isinstance(r, Mapping):
        r = r.get("value")
    if not isinstance(r, list | tuple):
        return []
    return _uniq(a for a in (norm_address(x) for x in r) if a)


@rule("mod.address_reserved")
def address_reserved(ctx: Ctx) -> list[Finding]:
    out: list[Finding] = []
    for topo in _topology(ctx):
        bus, devs = topo["bus"], topo["devices"]
        for holder, hseg in devs:
            res = _reserved(holder)
            if not res:
                continue
            hit = False
            for other, oseg in devs:
                if other is holder or not _seg_visible(topo, hseg, oseg):
                    continue
                where = _where(bus["id"], [hseg, oseg])
                if other.address is None:
                    if i2c_iface(other.module) is None:
                        continue  # no I²C interface: a passive bridge (level shifter, buffer)
                    out.append(Finding("mod.address_reserved", "not_checked", None,
                                       f"{ctx.label(other)} has no I²C address in the module data: the reserved "
                                       f"address(es) {', '.join(res)} of {holder.ref} are not checked against it.",
                                       [holder.ref, other.ref]))
                    hit = True
                    continue
                if other.address in res:
                    hit = True
                    out.append(ctx.finding(
                        "mod.address_reserved", "failed", "caution",
                        f"{ctx.label(other)} at {other.address} on {where}: {ctx.label(holder)} also answers to "
                        f"{other.address} (reserved, e.g. all-call). Fix: another address for {other.ref} (address "
                        f"pin), a second I²C bus or an I²C mux, or disable that address in {holder.ref}.",
                        [holder, other], source_id=[ctx.src(holder), _iface_source(ctx, other)], chip_fact=False))
            if not hit:
                out.append(Finding("mod.address_reserved", "passed", None,
                                   f"{ctx.label(holder)} reserves {', '.join(res)}: no other device on "
                                   f"{_where(bus['id'], [hseg])} uses it.", [holder.ref],
                                   [s for s in [ctx.src(holder)] if s]))
    return out


# --- mod.address_select --------------------------------------------------------------------------------------------
@rule("mod.address_select")
def address_select(ctx: Ctx) -> list[Finding]:
    out: list[Finding] = []
    rid = "mod.address_select"
    for inst in ctx.instances:
        it = i2c_iface(inst.module)
        if it is None:
            continue
        addrs = addresses(it)
        sel = _select(it)
        explicit = inst.address if inst.address_from == "explicit" else None
        src = _iface_source(ctx, inst)
        label = ctx.label(inst)
        if explicit is not None and addrs and explicit not in addrs:
            out.append(ctx.finding(rid, "failed", "caution",
                                   f"{label}: address {explicit} is not one of the module's addresses "
                                   f"({', '.join(addrs)}).", inst, source_id=src, chip_fact=False))
            continue
        if sel is None:
            if explicit is None:
                continue  # fixed address or no select data: nothing to compare
            if not addrs:
                out.append(Finding(rid, "not_checked", "info",
                                   f"{label}: address {explicit} is set, but the module data lists no addresses; "
                                   "not checked.", [inst.ref], [s for s in [src] if s]))
            else:
                out.append(Finding(rid, "passed", None, f"{label}: address {explicit} is one of "
                                   f"{', '.join(addrs)} (no select pin in the data).", [inst.ref],
                                   [s for s in [src] if s]))
            continue
        pins, smap = sel
        spec = {p["name"]: p for p in _pins(inst.module)}
        nets = {p: inst.conn.get(p) for p in pins}
        open_pins = [p for p in pins if nets[p] is None]
        must_open = [p for p in open_pins if (spec.get(p) or {}).get("must_connect")]
        options = _map_text(pins, smap)
        derived, origin = modcheck._address(inst, it, None, ctx.rails)  # the engine's own select resolution
        conn_text = ", ".join(f"{p} on {nets[p]}" for p in pins if nets[p] is not None)
        if must_open:
            out.append(ctx.finding(rid, "failed", "caution",
                                   f"{label}: {', '.join(must_open)} must be connected to set the I²C address "
                                   f"({options}); an open select pin leaves the address undefined.",
                                   inst, source_id=src, chip_fact=False))
            continue
        if origin == "select":
            if explicit is not None and explicit != derived:
                how = _key_for(pins, smap, explicit)
                out.append(ctx.finding(rid, "failed", "caution",
                                       f"{label}: address {explicit} is set, but {conn_text} selects {derived}. "
                                       f"Set the address to {derived}" + (f" or connect {how}." if how else "."),
                                       inst, source_id=src, chip_fact=False))
            else:
                out.append(Finding(rid, "passed", None, f"{label}: {conn_text} selects {derived}"
                                   + (" as set." if explicit else "."), [inst.ref], [s for s in [src] if s]))
            continue
        if open_pins:
            if explicit is not None and explicit != derived:
                how = _key_for(pins, smap, explicit)
                out.append(ctx.finding(rid, "failed", "caution",
                                       f"{label}: address {explicit} is set, but {', '.join(open_pins)} "
                                       f"{'is' if len(open_pins) == 1 else 'are'} open (default {derived})"
                                       + (f"; connect {how}." if how else "."),
                                       inst, source_id=src, chip_fact=False))
            else:
                out.append(Finding(rid, "passed", None, f"{label}: {', '.join(open_pins)} open, default address "
                                   f"{derived}.", [inst.ref], [s for s in [src] if s]))
            continue
        out.append(Finding(rid, "not_checked", "info",
                           f"{label}: {conn_text} is not in the select map ({options}); address not checked "
                           f"(assumed {derived}). A select pin on a GPIO or another net follows its level.",
                           [inst.ref], [s for s in [src] if s]))
    return out


# --- mod.bus_speed ----------------------------------------------------------------------------------------------
@rule("mod.bus_speed")
def bus_speed(ctx: Ctx) -> list[Finding]:
    out: list[Finding] = []
    rid = "mod.bus_speed"
    for topo in _topology(ctx):
        bus, devs = topo["bus"], topo["devices"]
        if not devs:
            continue
        rated: list[tuple[Instance, str, float, Any]] = []
        missing: list[Instance] = []
        for inst, seg in devs:
            if i2c_iface(inst.module) is None:
                continue  # no I²C interface: a passive bridge (level shifter) sets no clock limit
            f = (i2c_iface(inst.module) or {}).get("f_max_hz")
            hz = ctx.fv(f)
            if hz and hz > 0:
                rated.append((inst, seg, hz, f))
            else:
                missing.append(inst)
        if not rated and not missing:
            continue
        if not rated:
            out.append(Finding(rid, "not_checked", None,
                               f"Bus {bus['id']}: no clock limit (f_max_hz) in the module data of "
                               f"{_labels(missing)}; bus speed not checked.", [i.ref for i in missing]))
            continue
        low = min(hz for _, _, hz, _ in rated)
        limiters = [(i, s, f) for i, s, hz, f in rated if hz == low]
        segs = _uniq(s for _, s, _ in limiters if s != "main")
        on_ch = f" (on {', '.join(segs)}: applies while that channel is selected)" if segs else ""
        text = (f"Bus {bus['id']}: the devices allow at most {fmt(low, 'Hz')}, limited by "
                f"{_labels([i for i, _, _ in limiters])}{on_ch}")
        miss = f" No f_max_hz data for {', '.join(i.ref for i in missing)}." if missing else ""
        sids = _uniq(s for s in (ctx.src(i, f) for i, _, f in limiters) if s)
        refs = [i.ref for i, _, _ in limiters]
        if low < FAST_MODE_HZ:
            out.append(Finding(rid, "failed", "info",
                               f"{text}, below I²C Fast-mode ({fmt(FAST_MODE_HZ, 'Hz')}): set the I²C clock to at "
                               f"most {fmt(low, 'Hz')}.{miss}", refs, [*sids, I2C_SPEC_SOURCE]))
        elif missing:
            out.append(Finding(rid, "not_checked", None, f"{text}.{miss}", refs + [i.ref for i in missing], sids))
        else:
            out.append(Finding(rid, "passed", None, f"{text}.", refs, sids))
    return out


# --- mod.pin_role --------------------------------------------------------------------------------------------------
def _push_pull(inst: Instance, pin: Mapping[str, Any]) -> bool:
    if pin.get("output") == "push_pull":
        return True
    io = inst.module.get("io")
    return pin.get("output") is None and isinstance(io, Mapping) and io.get("outputs") == "push_pull" \
        and SIGNAL_DIRECTION.get(str(pin.get("signal"))) == "out"


def _role_text(sig: str, modes: list[str], allowed: tuple[str, ...]) -> str:
    if sig in ("uart_rx", "uart_tx") and sig in modes:
        return "UART not crossed: module RX goes to ESP TX (uart_tx), module TX to ESP RX (uart_rx)"
    if sig in ("i2c_sda", "i2c_scl") and ({"i2c_sda", "i2c_scl"} - {sig}) & set(modes):
        return "SDA and SCL swapped"
    if (sig == "spi_sdi" and "spi_miso" in modes) or (sig == "spi_sdo" and "spi_mosi" in modes):
        return "MOSI/MISO swapped: module SDI (data in) goes to ESP MOSI, module SDO (data out) to ESP MISO"
    return f"expected ESP mode {' or '.join(allowed)}"


@rule("mod.pin_role")
def pin_role(ctx: Ctx) -> list[Finding]:
    out: list[Finding] = []
    rid = "mod.pin_role"
    graph = _Graph(ctx)
    for inst in ctx.instances:
        good: list[str] = []
        bad = 0
        for p in _pins(inst.module):
            name, sig = p["name"], p.get("signal")
            if not isinstance(sig, str) or sig not in SIGNAL_MODES:
                out.append(Finding(rid, "not_checked", None, f"{ctx.label(inst)} {name}: signal {sig!r} is not "
                                   "known; pin role not checked.", [inst.ref]))
                continue
            allowed = SIGNAL_MODES[sig]
            net = inst.conn.get(name)
            if not allowed or net is None:
                continue
            if (inst.ref, name) in graph.bridge_pins and sig not in GROUP_OF:
                good.append(name)  # a level-shifter channel passes either direction: no role to check
                continue
            modes = _uniq(m for m in ctx.nets.get(net, {}).get("modes", []) if isinstance(m, str))
            via = None
            if not modes and net not in ctx.rails:  # behind a bridge: the ESP modes on its other side
                for far in graph.through_bridges([net])[1:]:
                    far_modes = [m for m in ctx.nets.get(far, {}).get("modes", []) if isinstance(m, str)]
                    if far_modes:
                        modes, via = _uniq(far_modes), far
                        break
            if not modes:
                continue  # no ESP pin on the net: mod.unconnected
            if any(m in allowed for m in modes):
                good.append(name)
                continue
            bad += 1
            mod_drives = SIGNAL_DIRECTION.get(sig) in ("out", "out_od")
            esp_drives = [m for m in modes if m in ESP_DRIVES]
            sev = "caution"
            why = ""
            if mod_drives and esp_drives and via is None:
                if _push_pull(inst, p):
                    sev = "danger"
                    why = (" Both sides drive the net: the push-pull output and the ESP output short the supply "
                           "through both drivers when the levels differ.")
                else:
                    why = " Both sides may drive the net (output against output)."
            where = _on_net(ctx, net) if via is None else f"{net} (through a level shifter to {_on_net(ctx, via)})"
            out.append(ctx.finding(rid, "failed", sev,
                                   f"{ctx.label(inst)} {name} ({sig}) on {where}, ESP mode "
                                   f"{', '.join(modes)}: {_role_text(sig, modes, allowed)}.{why}",
                                   inst, source_id=ctx.src(inst), chip_fact=False))
        if good and not bad:
            out.append(Finding(rid, "passed", None, f"{ctx.label(inst)}: {', '.join(good)} fit the ESP modes on "
                               "their nets.", [inst.ref], [s for s in [ctx.src(inst)] if s]))
    return out


# --- mod.net_shared_signals ----------------------------------------------------------------------------------------
def _lines_text(sigs: list[str]) -> str:
    names = [LINE_NAMES.get(s, s) for s in sigs]
    return " and ".join(names) if len(names) < 3 else ", ".join(names[:-1]) + " and " + names[-1]


def _share_severity(sigs: set[str]) -> tuple[str, str]:
    """(severity, why). Data in + out on one net is only right for 3-wire (half-duplex) SPI: caution."""
    if sigs in THREE_WIRE:
        return "caution", ("only 3-wire (half-duplex) SPI joins data in and out on one line; in normal 4-wire SPI "
                           "the outputs drive against each other. Unless the device runs in 3-wire mode, give each "
                           "line its own net")
    return "danger", "that shorts the lines; give each line its own net"


@rule("mod.net_shared_signals")
def net_shared_signals(ctx: Ctx) -> list[Finding]:
    """Different bus lines (SDA/SCL, SCK/MOSI/MISO/CS) on one net, at the ESP or at one module."""
    out: list[Finding] = []
    rid = "mod.net_shared_signals"
    by_net: dict[str, Finding] = {}
    for net, info in ctx.nets.items():
        if net in ctx.rails:
            continue
        modes = _uniq(m for m in info.get("modes", []) if m in ESP_LINES)
        if len(modes) < 2:
            continue
        sev, why = _share_severity(set(modes))
        gpios = [f"GPIO{n}" for n in _uniq(info.get("gpios") or [])]
        names = [LINE_NAMES[m] for m in modes]
        f = Finding(rid, "failed", sev,
                    f"{_lines_text(modes)} share net {net} ({', '.join(gpios)}): {why}, e.g. "
                    f"{' / '.join(f'{net.upper()}_{n}' for n in names[:3])}.", gpios,
                    supersedes=("mod.pin_role",))
        by_net[net] = f
        out.append(f)
    checked: list[str] = []
    for inst in ctx.instances:
        nets: dict[str, list[str]] = {}
        for p in _pins(inst.module):
            sig, net = p.get("signal"), inst.conn.get(p["name"])
            if sig in MODULE_LINES and net and net not in ctx.rails:
                nets.setdefault(net, []).append(p["name"])
        bad = False
        for net, pin_names in nets.items():
            sigs = _uniq(next(str(p.get("signal")) for p in _pins(inst.module) if p["name"] == n) for n in pin_names)
            if len(sigs) < 2:
                continue
            bad = True
            if net in by_net:
                if inst.ref not in by_net[net].refs:
                    by_net[net].refs.append(inst.ref)
                continue
            sev, why = _share_severity(set(sigs))
            out.append(replace(ctx.finding(rid, "failed", sev,
                                           f"{ctx.label(inst)} {' and '.join(pin_names[:4])} ({_lines_text(sigs)}) "
                                           f"share net {net}: {why}.", inst, source_id=ctx.src(inst),
                                           chip_fact=False), supersedes=("mod.pin_role",)))
        if nets and not bad:
            checked.append(inst.ref)
    esp_lines = any(m in ESP_LINES for i in ctx.nets.values() for m in i.get("modes", []))
    if not out and (checked or esp_lines):
        out.append(Finding(rid, "passed", None, "Every bus line (SDA, SCL, SCK, MOSI, MISO, CS) has its own net.",
                           checked[:MAX_PASSED_REFS]))
    return out


# --- mod.spi_cs ----------------------------------------------------------------------------------------------------
def _is_spi(inst: Instance) -> bool:
    return any(isinstance(it, Mapping) and it.get("type") == "spi" for it in inst.module.get("interfaces") or []) \
        or any(str(p.get("signal", "")).startswith("spi_") for p in _pins(inst.module))


def _nets(ctx: Ctx, inst: Instance, signal: str) -> set[str]:
    return {n for n in (inst.conn.get(p) for p in ctx.pins_with(inst, signal)) if n}


@rule("mod.spi_cs")
def spi_cs(ctx: Ctx) -> list[Finding]:
    out: list[Finding] = []
    rid = "mod.spi_cs"
    spi = [i for i in ctx.instances if _is_spi(i)]
    by_net: dict[str, list[Instance]] = {}
    for inst in spi:
        cs_pins = ctx.pins_with(inst, "spi_cs")
        if not cs_pins:
            out.append(Finding(rid, "not_checked", None, f"{ctx.label(inst)}: no chip-select pin in the module "
                               "data; SPI chip select not checked.", [inst.ref]))
            continue
        for cs in cs_pins:
            net = inst.conn.get(cs)
            if net is None:
                out.append(Finding(rid, "not_checked", None, f"{ctx.label(inst)} {cs} is not connected; chip "
                                   "select not checked (see mod.unconnected).", [inst.ref]))
            elif inst not in by_net.setdefault(net, []):
                by_net[net].append(inst)
    ok: list[str] = []
    for net, insts in by_net.items():
        if len(insts) > 1:
            sdo = [_nets(ctx, i, "spi_sdo") for i in insts]
            shared = sorted({n for a in range(len(sdo)) for b in range(a + 1, len(sdo)) for n in sdo[a] & sdo[b]})
            if shared:
                msg = (f"{_labels(insts)} share the chip-select net {net}: both are selected at once and drive the "
                       f"data-out net {', '.join(shared)} together (bus contention). Give each device its own CS.")
                sev = "danger"
            else:
                msg = (f"{_labels(insts)} share the chip-select net {net}: both are selected at once and receive "
                       "every transfer. Give each device its own CS.")
                sev = "caution"
            out.append(ctx.finding(rid, "failed", sev, msg, insts, source_id=[ctx.src(i) for i in insts],
                                   chip_fact=False))
            continue
        inst = insts[0]
        v = ctx.volts(net)
        if v is not None:
            cs = next(p for p in _pins(inst.module) if p.get("signal") == "spi_cs" and inst.conn.get(p["name"]) == net)
            active_low = cs.get("active_low", True) is not False
            always = (v == 0) == active_low
            sck = _nets(ctx, inst, "spi_sck")
            others = [o for o in spi if o.ref != inst.ref and _nets(ctx, o, "spi_sck") & sck]
            if not always or others:
                state = "always selected" if always else "never selected"
                tail = (f" and answers to every transfer meant for {', '.join(o.ref for o in others)} on the shared "
                        "SPI bus" if always else ": the ESP cannot talk to it")
                out.append(ctx.finding(rid, "failed", "caution",
                                       f"{ctx.label(inst)} {cs['name']} is tied to {net}: the device is {state}{tail}"
                                       f" (CS {'active low' if active_low else 'active high'}).",
                                       inst, source_id=ctx.src(inst), chip_fact=False))
                continue
        ok.append(f"{inst.ref} on {net}")
    if ok:
        out.append(Finding(rid, "passed", None, f"{len(ok)} SPI device(s), each with its own chip select "
                           f"({', '.join(ok)}).", [x.split(" ")[0] for x in ok]))
    return out


# --- mod.unconnected -----------------------------------------------------------------------------------------------
def _i2c_nets(ctx: Ctx, graph: _Graph) -> dict[str, set[str]]:
    """{signal: nets} of the I²C lines: the buses' SDA/SCL nets, the channel nets of placed muxes and every net
    behind a bridge (level shifter, PCA9306) on them."""
    out: dict[str, set[str]] = {"i2c_sda": set(), "i2c_scl": set()}
    for topo in _topology(ctx, graph):
        out["i2c_sda"] |= set(topo["sda"])
        out["i2c_scl"] |= set(topo["scl"])
    return out


def _bridged(ctx: Ctx, inst: Instance, sig: str, net: str) -> bool:
    """The net is the far side of an I²C bridge (a part with two or more ``sig`` pins: mux, level shifter, buffer):
    a bridge sits on it next to ``inst``, or ``inst`` is the bridge and another part's ``sig`` pin sits on it."""
    own = len(ctx.pins_with(inst, sig)) > 1
    for other in ctx.instances:
        if other.ref == inst.ref:
            continue
        names = ctx.pins_with(other, sig)
        if (own or len(names) > 1) and any(other.conn.get(n) == net for n in names):
            return True
    return False


def _defined(ctx: Ctx, inst: Instance, net: str, kinds: Mapping[str, Any], graph: _Graph) -> bool:
    """Something sets the level of ``net``, followed through series resistors and level-shifter channels (at most
    MAX_LINK_DEPTH hops): an ESP assignment, a rail (pull-up/pull-down resistor), a supply or ground pin of any
    module (also the own one, e.g. EN tied to VREF2), a signal pin of another module that is no bridge channel, or a
    plain part that is not passive (LED, button, servo)."""
    sigs = {i.ref: {p["name"]: p.get("signal") for p in _pins(i.module)} for i in ctx.instances}
    seen, frontier = {net}, [net]
    for depth in range(MAX_LINK_DEPTH + 1):
        nxt: list[str] = []
        for n in frontier:
            if depth and (n in ctx.rails or ctx.nets.get(n, {}).get("modes")):
                return True
            for ref, pin in ctx.nets.get(n, {}).get("pins", []):
                if ref in sigs:
                    sig = sigs[ref].get(pin)
                    if sig in POWER:
                        return True
                    if (ref, pin) in graph.bridge_pins or ref == inst.ref or sig in ("nc", None):
                        continue
                    return True
                if kinds.get(ref) not in PASSIVE_KINDS:
                    return True
            for m in graph.resistors.get(n, []) + graph.bridges.get(n, []):
                if m not in seen and len(seen) < MAX_REACH:
                    seen.add(m)
                    nxt.append(m)
        frontier = nxt
        if not frontier:
            break
    return False


def _read(ctx: Ctx, inst: Instance, pin: str, net: str, graph: _Graph) -> bool:
    """Something besides the pin itself sits on the net of a module output: another part's pin or a link."""
    if graph.resistors.get(net) or graph.bridges.get(net):
        return True
    return any((ref, p) != (inst.ref, pin) for ref, p in ctx.nets.get(net, {}).get("pins", []))


def _project_input(ctx: Ctx) -> list[Finding]:
    """Project mistakes the engine would otherwise drop silently: refs used twice, conn values that are no net."""
    out: list[Finding] = []
    rid = "mod.unconnected"
    refs: dict[str, list[str]] = {}
    n_mod = 0
    for p in ctx.parts:
        is_mod = isinstance(p.get("module"), str) and p["module"].strip()
        raw = p.get("ref")
        ref = raw if isinstance(raw, str) and raw else (f"U{n_mod + 1}" if is_mod else None)
        n_mod += 1 if is_mod else 0
        what = p["module"].strip() if is_mod else str(p.get("kind") or "part")
        if ref is not None:
            refs.setdefault(ref, []).append(what)
        conn = p.get("conn")
        if conn is None or ref is None:
            continue
        if not isinstance(conn, Mapping):
            out.append(Finding(rid, "failed", "caution", f"{ref} ({what}): conn is a {type(conn).__name__}, not a "
                               "map of pin -> net; none of its pins counts as connected.", [ref]))
            continue
        bad = [(k, v) for k, v in conn.items() if not isinstance(k, str) or (v is not None and not isinstance(v, str))]
        if bad:
            shown = ", ".join(f"{k!s} = {v!r}" for k, v in bad[:4]) + (", …" if len(bad) > 4 else "")
            out.append(Finding(rid, "failed", "caution",
                               f"{ref} ({what}): conn {shown} {'is no net name, so the pin counts' if len(bad) == 1 else 'are no net names, so the pins count'} "
                               "as open. Write each net as text, e.g. \"3V3\", \"GND\" or \"GPIO8\".",
                               [ref]))
    for ref, whats in refs.items():
        if len(whats) > 1:
            out.append(Finding(rid, "failed", "caution",
                               f"Ref {ref} is used by {len(whats)} parts ({', '.join(whats[:4])}): the check cannot "
                               "tell them apart and may mix up their findings. Give every part its own ref.", [ref]))
    return out


@rule("mod.unconnected")
def unconnected(ctx: Ctx) -> list[Finding]:
    out: list[Finding] = []
    rid = "mod.unconnected"
    kinds = {p.get("ref"): p.get("kind") for p in ctx.parts if not p.get("module")}
    graph = _Graph(ctx)
    i2c_nets = _i2c_nets(ctx, graph)
    out += _project_input(ctx)
    for inst in ctx.instances:
        pins = _pins(inst.module)
        label = ctx.label(inst)
        src = ctx.src(inst)
        if not pins:
            out.append(Finding(rid, "not_checked", None, f"{label}: no pin list in the module data; open pins not "
                               "checked.", [inst.ref]))
            continue
        found: list[Finding] = []

        def add(sev: str, msg: str, chip_fact: bool = False, inst: Instance = inst, src: str | None = src,
                found: list[Finding] = found) -> None:
            found.append(ctx.finding(rid, "failed", sev, msg, inst, source_id=src, chip_fact=chip_fact))

        names = {p["name"] for p in pins}
        mux_pins = {x for _, sda, scl in modcheck.mux_channels(i2c_iface(inst.module)) for x in (sda, scl) if x}
        conn = inst.conn
        signal_pins = [p for p in pins if p.get("signal") not in (*POWER, "nc", "power_out", "addr_select",
                                                                  "mode_select") and p["name"] not in mux_pins]
        none_wired = bool(signal_pins) and not any(conn.get(p["name"]) for p in signal_pins)
        if none_wired:
            add("caution", f"{label}: none of its signal pins ({', '.join(p['name'] for p in signal_pins[:6])}) is "
                "connected.")
        groups_used = {GROUP_OF[str(p.get("signal"))] for p in signal_pins
                       if conn.get(p["name"]) and p.get("signal") in GROUP_OF}
        defined: dict[tuple[str, str], list[str]] = {}  # open mode pins with an internal pull: (pull, meaning) -> pins
        for p in pins:
            name, sig = p["name"], p.get("signal")
            if conn.get(name) is not None or not isinstance(sig, str):
                continue
            if isinstance(p.get("tie"), str) and p["tie"] in names:
                continue  # tied to an own pin that is open: that pin is reported
            if sig in POWER:
                add("caution", f"{label} {name} ({sig}) is not connected: the module has no "
                    f"{'supply' if sig == 'supply' else 'ground'} on this pin.")
            elif name in mux_pins or none_wired:
                continue
            elif p.get("must_connect") and sig != "addr_select":
                add("caution", f"{label} {name} ({sig}) must be connected according to the module data.")
            elif sig in NO_PIN_CHECK or SIGNAL_DIRECTION.get(sig) in ("out", "out_od", "analog") \
                    or sig == "led_data_out":
                continue
            elif sig == "mode_select":
                pull = _pull_dir(p.get("internal_pull"))
                if pull:  # open is a defined level (A4988 MS1-MS3): no finding, the passed text says what it means
                    defined.setdefault((pull, _pull_meaning(p.get("note"))), []).append(name)
                elif inst.module.get("kind") == "module":  # a board often wires such pins itself (not at the header)
                    add("info", f"{label} {name} (mode select) is open in the project. A breakout board often sets "
                        "this pin itself; check the board's schematic, else connect it as the datasheet says.")
                else:
                    add("caution", f"{label} {name} (mode select) is open: the operating mode is undefined; connect "
                        "it as the datasheet says.")
            elif sig in GROUP_OF:
                if GROUP_OF[sig] not in groups_used:
                    continue
                if sig == "uart_rx":
                    add("info", f"{label} {name} (uart_rx) is open: receive-only use, the ESP cannot send commands "
                        "to the module.")
                else:
                    add("caution", f"{label} {name} ({sig}) is open while the other {GROUP_OF[sig].upper()} pins "
                        "are connected: the interface is only half wired.")
            elif sig == "reset_in" and "reset_rc" in ((inst.facts or {}).get("onboard") or ()):
                continue  # RC reset on the board (facts.onboard, user-confirmed)
            elif sig in SINGLE_INPUTS and not p.get("internal_pull"):
                add("caution", f"{label} {name} ({sig}) is open: a floating input can switch at random; connect it "
                    "or tie it to its inactive level.", chip_fact=True)
        for ch, sda, scl in modcheck.mux_channels(i2c_iface(inst.module)):
            if scl and bool(conn.get(sda)) != bool(conn.get(scl)):
                add("caution", f"{label} channel {ch}: only {sda if conn.get(sda) else scl} is connected; a channel "
                    "needs both SDx and SCx.")
        for p in pins:
            name, sig = p["name"], p.get("signal")
            net = conn.get(name)
            if net is None or not isinstance(sig, str) or not SIGNAL_MODES.get(sig) or net in ctx.rails:
                continue
            if ctx.nets.get(net, {}).get("modes"):
                continue
            if sig in i2c_nets:
                if net in i2c_nets[sig] or _bridged(ctx, inst, sig, net):
                    continue
            elif SIGNAL_DIRECTION.get(sig) in ("out", "out_od", "analog") and (inst.ref, name) not in \
                    graph.bridge_pins:
                if not _read(ctx, inst, name, net, graph):
                    add("info", f"{label} {name} ({sig}) on net {net}: nothing reads this output (no ESP pin, no "
                        "other part on the net). Fine if it is unused.")
                continue
            elif _defined(ctx, inst, net, kinds, graph):
                continue
            gpio = net[4:] if net.startswith("GPIO") and net[4:].isdigit() else None
            add("caution", f"{label} {name} ({sig}) on net {net}: "
                + (f"GPIO{gpio} has no assignment" if gpio else "no ESP pin is assigned to this net")
                + f" and no other part drives it (expected ESP mode {' or '.join(SIGNAL_MODES[sig])}). "
                "Typo in the net name?")
        out += found or [Finding(rid, "passed", None, f"{label}: required pins connected.", [inst.ref],
                                 [s for s in [src] if s])]
        for (pull, meaning), names_open in defined.items():
            out.append(Finding(rid, "passed", None, f"{label} {', '.join(names_open)} (mode select): open = internal "
                               f"pull-{pull}" + (f" → {meaning}" if meaning else "") + ".", [inst.ref],
                               [s for s in [src] if s]))
    return out


def _pull_dir(ip: Any) -> str | None:
    """"up" / "down" of a pin's ``internal_pull`` ("down" or {"down": F}); None without one."""
    if isinstance(ip, str) and ip in ("up", "down"):
        return ip
    if isinstance(ip, Mapping):
        return next((d for d in ("down", "up") if d in ip), None)
    return None


_PULL_PREFIX = re.compile(r"^\s*internal pull-?(?:up|down)\s*[:,;]?\s*(?:open\s*(?:=|reads)\s*)?", re.IGNORECASE)


def _pull_meaning(note: Any) -> str:
    """What an open pin means, from its note (\"low (full step with all three open)\"); empty without a note."""
    if not isinstance(note, str) or not note.strip():
        return ""
    text = _PULL_PREFIX.sub("", note.strip()).rstrip(".")
    return text if len(text) <= 120 else text[:119].rstrip() + "…"
