"""Nets and wiring tables for the schematic blocks.

Pure data, no schemdraw: every block is a fixed circuit with named part pins. Board endpoints come from
``boards`` (DevKit header pins, e.g. GPIO14 -> "J1-20 · IO14"); without a DevKit the endpoints keep
chip-level names ("GPIO14", "3V3", "5V", "GND").

Node names:
- part pins: ``R1.1``/``R1.2`` (resistor), ``D1.A``/``D1.K`` (LED anode/cathode), ``Q1.B``/``Q1.C``/``Q1.E``
  (NPN base/collector/emitter), ``SW1.1``/``SW1.2`` (push button), ``J2.1``/``J2.2`` (off-board connector)
- board pins: ``J1-20`` (header-pin), shown as ``J1-20 · IO14`` in the wiring table

Each wire is one physical connection. Per net the wires form a spanning tree over the net's nodes
(``check_netlist`` verifies that).

Multi-GPIO blocks: ``module_plan`` (a catalog module with its required parts) and
``level_plan`` (BSS138 channels after NXP AN10441) resolve every pin to a net and give the rows the drawing needs;
their nets are wired by ``_Wiring``: every node of a net goes to the net's endpoint (board pin, rail, placeholder),
the near pin of a required part to the module pin it serves. Module pins are ``U1.SDI`` (the datasheet name), the
MOSFET pins ``Q1.G``/``Q1.D``/``Q1.S``, capacitors ``C1.1``/``C1.2``. An unassigned GPIO is the placeholder
``GPIO`` (node ``GPIO_<net>``), an off-board net (``VMOT``, ``HV1``) its own endpoint.
"""
from __future__ import annotations

import math
import re
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

from . import boards, modspec, modules
from .contracts import BenchError, format_si

SEP = " · "  # U+00B7, as in the contract example "J1-20 · IO14"
RAILS = ("3V3", "5V")
GROUND = "GND"
PIN_NAMES: dict[str, tuple[str, ...]] = {
    "resistor": ("1", "2"),
    "led": ("A", "K"),
    "transistor": ("B", "C", "E"),
    "switch": ("1", "2"),
    "connector": ("1", "2"),
    "capacitor": ("1", "2"),
    "ceramic": ("1", "2"),
    "electrolytic": ("1", "2"),
    "film": ("1", "2"),
}
MOSFET_PINS = ("G", "D", "S")


@dataclass(frozen=True)
class Endpoint:
    """A board-side connection point: ``node`` goes into nets, ``display`` into the wiring table and the SVG."""

    node: str
    display: str
    source_id: str | None = None


@dataclass(frozen=True)
class Part:
    ref: str
    kind: str
    value: str
    pins: tuple[str, ...] = ()  # own pin names (modules, MOSFETs); empty: PIN_NAMES of the kind

    @property
    def pin_names(self) -> tuple[str, ...]:
        return self.pins or PIN_NAMES[self.kind]

    def pin(self, name: str) -> str:
        if name not in self.pin_names:
            raise ValueError(f"{self.kind} has no pin {name!r}")
        return f"{self.ref}.{name}"

    def as_dict(self) -> dict[str, str]:
        return {"ref": self.ref, "kind": self.kind, "value": self.value}


@dataclass
class Netlist:
    parts: list[Part]
    nets: list[tuple[str, list[str]]]
    wires: list[tuple[str, str, str]]  # (from node, to node, net)
    display: dict[str, str]
    source_ids: list[str]

    def as_result(self) -> dict[str, Any]:
        show = self.display.get
        return {
            "nets": [{"name": name, "nodes": list(nodes)} for name, nodes in self.nets],
            "parts": [p.as_dict() for p in self.parts],
            "wiring": [{"from": show(a, a), "to": show(b, b), "net": net} for a, b, net in self.wires],
        }


# --------------------------------------------------------------------------- board endpoints

def _pin_entries(board: Mapping[str, Any]) -> list[tuple[int, str, dict[str, Any]]]:
    out = []
    for hi, header in enumerate(board["headers"]):
        for pin in header["pins"]:
            out.append((hi, header["id"], pin))
    return out


def _nearest(entries: list[tuple[int, str, dict[str, Any]]], match, near: tuple[int, int] | None) -> tuple[str, dict[str, Any]] | None:
    """Pin closest to ``near`` = (header index, pin number): same header first, then smallest distance, then lower number."""
    cands = [(hi, hid, p) for hi, hid, p in entries if match(p)]
    if not cands:
        return None
    if near is None:
        _hi, hid, p = cands[0]
        return hid, p
    nh, nn = near

    def key(c):
        hi, _hid, p = c
        return (0 if hi == nh else 1, abs(p["n"] - nn) if hi == nh else 0, hi, p["n"])

    _hi, hid, p = min(cands, key=key)
    return hid, p


class Board:
    """Board endpoints for one render: the signal GPIO plus rails and ground on demand."""

    def __init__(self, devkit: str | None, gpio: int | None):
        self.devkit = devkit
        self.gpio = gpio
        self._board = boards.load(devkit) if devkit else None
        self._near: tuple[int, int] | None = None
        if devkit and self._board is not None and gpio is not None:
            hdr = boards.header_of(devkit, gpio)
            if hdr is None:
                raise BenchError("unknown_pin", f"GPIO{gpio} is not broken out on {devkit}",
                                 "choose a GPIO that is on a header pin (see board.layout)")
            hid, n = hdr.split("-")
            idx = [h["id"] for h in self._board["headers"]].index(hid)
            self._near = (idx, int(n))
            self._signal = Endpoint(hdr, f"{hdr}{SEP}IO{gpio}", self._board["source_id"])
        elif gpio is not None:
            self._signal = Endpoint(f"GPIO{gpio}", f"GPIO{gpio}")
        else:
            self._signal = Endpoint("GPIO", "GPIO")

    @property
    def title(self) -> str | None:
        return self._board["title"] if self._board else None

    def signal(self) -> Endpoint:
        return self._signal

    def rail(self, name: str) -> Endpoint:
        """'3V3', '5V' or 'GND'."""
        if name not in (*RAILS, GROUND):
            raise ValueError(name)
        if self._board is None:
            return Endpoint(name, name)
        if name == GROUND:
            def match(p):
                return p.get("kind") == "ground"
        else:
            def match(p):
                return p.get("kind") == "power" and p.get("label") == name
        found = _nearest(_pin_entries(self._board), match, self._near)
        if found is None:
            raise BenchError("rule_data_missing", f"{self.devkit} has no {name} pin in its header data",
                             "check data/boards/ for this board")
        hid, pin = found
        node = f"{hid}-{pin['n']}"
        return Endpoint(node, f"{node}{SEP}{pin['label']}", self._board["source_id"])

    def gpio_endpoint(self, num: int) -> Endpoint:
        """Any GPIO of the board (multi-GPIO blocks): its header pin on a DevKit, else ``GPIO<n>``."""
        if num == self.gpio:
            return self._signal
        if self._board is None or self.devkit is None:
            return Endpoint(f"GPIO{num}", f"GPIO{num}")
        hdr = boards.header_of(self.devkit, num)
        if hdr is None:
            raise BenchError("unknown_pin", f"GPIO{num} is not broken out on {self.devkit}",
                             "choose a GPIO that is on a header pin (see board.layout)")
        return Endpoint(hdr, f"{hdr}{SEP}IO{num}", self._board["source_id"])

    def supply(self, net: str) -> Endpoint:
        """3V3, 5V and GND from the board; any other rail or net is an off-board endpoint of its own name."""
        return self.rail(net) if net in (*RAILS, GROUND) else off_board(net)


def placeholder(net: str) -> Endpoint:
    """An unassigned GPIO on ``net`` (one node per net, shown as ``GPIO`` like the old blocks)."""
    return Endpoint(f"GPIO_{net}", "GPIO")


def off_board(net: str) -> Endpoint:
    return Endpoint(net, net)


# --------------------------------------------------------------------------- blocks

def _stem(net: str) -> str:
    return net[:-3] if net.endswith("_EN") and len(net) > 3 else net


class _Builder:
    def __init__(self, board: Board):
        self.board = board
        self.parts: list[Part] = []
        self.nets: list[tuple[str, list[str]]] = []
        self.wires: list[tuple[str, str, str]] = []
        self.display: dict[str, str] = {}
        self.source_ids: list[str] = []

    def part(self, ref: str, kind: str, value: str) -> Part:
        p = Part(ref, kind, value)
        self.parts.append(p)
        return p

    def endpoint(self, ep: Endpoint) -> str:
        self.display[ep.node] = ep.display
        if ep.source_id and ep.source_id not in self.source_ids:
            self.source_ids.append(ep.source_id)
        return ep.node

    def net(self, name: str, wires: Iterable[tuple[str, str]]) -> None:
        wires = list(wires)
        nodes: list[str] = []
        for a, b in wires:
            for n in (a, b):
                if n not in nodes:
                    nodes.append(n)
        self.nets.append((name, nodes))
        self.wires.extend((a, b, name) for a, b in wires)

    def done(self) -> Netlist:
        return Netlist(self.parts, self.nets, self.wires, self.display, self.source_ids)


def connector_ref(devkit: str | None) -> str:
    """First J<n> that is not a header of the DevKit (S3-DevKitC-1 uses J1 and J3, so J2)."""
    taken = {h["id"] for h in boards.load(devkit)["headers"]} if devkit else set()
    n = 1
    while f"J{n}" in taken:
        n += 1
    return f"J{n}"


def led(p: Mapping[str, Any], board: Board, values: Mapping[str, str]) -> Netlist:
    b = _Builder(board)
    r1 = b.part("R1", "resistor", values["r_series"])
    d1 = b.part("D1", "led", p["led"])
    sig = b.endpoint(board.signal())
    net = p["net"]
    if p["active"] == "high":  # GPIO -> R1 -> D1 -> GND
        gnd = b.endpoint(board.rail(GROUND))
        b.net(net, [(sig, r1.pin("1"))])
        b.net(f"{_stem(net)}_A", [(r1.pin("2"), d1.pin("A"))])
        b.net(GROUND, [(d1.pin("K"), gnd)])
    else:  # +3.3 V -> D1 -> R1 -> GPIO (GPIO sinks the current)
        v33 = b.endpoint(board.rail("3V3"))
        b.net("3V3", [(v33, d1.pin("A"))])
        b.net(f"{_stem(net)}_K", [(d1.pin("K"), r1.pin("2"))])
        b.net(net, [(sig, r1.pin("1"))])
    return b.done()


def npn_low_side(p: Mapping[str, Any], board: Board, values: Mapping[str, str]) -> Netlist:
    b = _Builder(board)
    r1 = b.part("R1", "resistor", values["r_base"])
    r2 = b.part("R2", "resistor", values["r_pulldown"])
    q1 = b.part("Q1", "transistor", p["transistor"])
    j = b.part(connector_ref(board.devkit), "connector", p["load"])
    sig = b.endpoint(board.signal())
    supply = b.endpoint(board.rail(p["supply"]))
    gnd = b.endpoint(board.rail(GROUND))
    stem = _stem(p["net"])
    b.net(p["net"], [(sig, r1.pin("1"))])
    b.net(f"{stem}_BASE", [(r1.pin("2"), q1.pin("B")), (r2.pin("1"), q1.pin("B"))])
    b.net(f"{stem}_LOW", [(q1.pin("C"), j.pin("2"))])
    b.net(p["supply"], [(supply, j.pin("1"))])
    b.net(GROUND, [(r2.pin("2"), q1.pin("E")), (q1.pin("E"), gnd)])
    return b.done()


def button_pullup(p: Mapping[str, Any], board: Board, values: Mapping[str, str]) -> Netlist:
    b = _Builder(board)
    r1 = b.part("R1", "resistor", values["r_pullup"])
    sw = b.part("SW1", "switch", p["button"])
    sig = b.endpoint(board.signal())
    v33 = b.endpoint(board.rail("3V3"))
    gnd = b.endpoint(board.rail(GROUND))
    b.net("3V3", [(v33, r1.pin("1"))])
    b.net(p["net"], [(sig, r1.pin("2")), (r1.pin("2"), sw.pin("1"))])
    b.net(GROUND, [(sw.pin("2"), gnd)])
    return b.done()


def divider(p: Mapping[str, Any], board: Board, values: Mapping[str, str]) -> Netlist:
    b = _Builder(board)
    top, bottom = p.get("_refs") or ("R1", "R2")  # the project's refs (schematic._divider_from_project)
    r1 = b.part(top, "resistor", values["r1"])
    r2 = b.part(bottom, "resistor", values["r2"])
    j = b.part(connector_ref(board.devkit), "connector", p["source"])
    sig = b.endpoint(board.signal())
    gnd = b.endpoint(board.rail(GROUND))
    b.net(p["input_net"], [(j.pin("1"), r1.pin("1"))])
    b.net(p["net"], [(sig, r1.pin("2")), (r1.pin("2"), r2.pin("1"))])
    b.net(GROUND, [(j.pin("2"), r2.pin("2")), (r2.pin("2"), gnd)])
    return b.done()


BUILDERS = {"led": led, "npn_low_side": npn_low_side, "button_pullup": button_pullup, "divider": divider}


def build(block: str, params: Mapping[str, Any], board: Board, values: Mapping[str, str]) -> Netlist:
    """Netlist for a validated block. ``values`` holds the display strings of the part values ("1 kΩ")."""
    return BUILDERS[block](params, board, values)


def _root(parent: dict[str, str], x: str) -> str:
    while parent[x] != x:
        x = parent[x]
    return x


def check_netlist(nl: Netlist) -> list[str]:
    """Structural problems (empty = fine): unknown pins, pins on two nets, unused pins, wires that do not
    form a spanning tree per net."""
    problems: list[str] = []
    part_pins = {p.pin(n) for p in nl.parts for n in p.pin_names}
    seen: dict[str, str] = {}
    for name, nodes in nl.nets:
        if len(nodes) < 2:
            problems.append(f"net {name} has fewer than two nodes")
        for n in nodes:
            if "." in n and n not in part_pins:
                problems.append(f"net {name}: unknown part pin {n}")
            if n in seen:
                problems.append(f"{n} is on nets {seen[n]} and {name}")
            seen[n] = name
    problems += [f"part pin {n} is not connected" for n in sorted(part_pins - seen.keys())]
    names = [n for n, _ in nl.nets]
    if len(set(names)) != len(names):
        problems.append("duplicate net names")
    for name, nodes in nl.nets:
        edges = [(a, b) for a, b, net in nl.wires if net == name]
        if len(edges) != len(nodes) - 1:
            problems.append(f"net {name}: {len(edges)} wires for {len(nodes)} nodes")
        parent = {n: n for n in nodes}
        for a, b in edges:
            if a not in parent or b not in parent:
                problems.append(f"net {name}: wire {a} -> {b} leaves the net")
                continue
            parent[_root(parent, a)] = _root(parent, b)
        if len({_root(parent, n) for n in nodes}) > 1:
            problems.append(f"net {name} is not connected")
    return problems


# --------------------------------------------------------------------------- multi-GPIO blocks

ESP_SIGNALS = frozenset(s for s, modes in modspec.SIGNAL_MODES.items() if modes)  # a GPIO drives or reads the pin
RIGHT_SIGNALS = ("supply", "power_out", "gnd")  # drawn on the right side of the module box, in this order
SIGNAL_NET = {"i2c_sda": "SDA", "i2c_scl": "SCL", "spi_sck": "SCK", "spi_cs": "CS", "spi_sdi": "MOSI",
              "spi_sdo": "MISO"}  # default net name when exactly one pin carries the signal
RESISTOR_CODES = ("pullup", "pulldown", "termination")
CAPACITOR_CODES = ("decoupling", "bulk_cap")
CAP_KINDS = ("ceramic", "electrolytic", "film", "capacitor")
_GPIO_NET = re.compile(r"^GPIO(\d{1,3})$")
# logic outputs of a module (digital_out, open_drain_out, led_data_out, analog_out); power_out feeds a load, not a GPIO
OUT_SIGNALS = frozenset(s for s in modspec.SIGNALS if s.endswith("_out") and s != "power_out")
I2C_CALC_KEY = "*i2c"  # pullup_values key of a stored i2c_pullup calculation (no net name has a "*")
GPIO_DRIVE_MODES = frozenset({"out", "pwm", "spi_mosi", "spi_sck", "spi_cs", "uart_tx"})  # the ESP pin drives the net
_UP_HINT = {"i2c_sda": "bench_calc i2c_pullup", "i2c_scl": "bench_calc i2c_pullup"}


def fmt_si(value: float, unit: str) -> str:
    """'4.7 kΩ', '100 nF' (same style as schematic.format_ohms)."""
    num, _, rest = format_si(value, unit, 4).partition(" ")
    if "." in num:
        num = num.rstrip("0").rstrip(".")
    return f"{num} {rest}".strip()


def rail_name(volts: float, rails: Mapping[str, float]) -> str:
    """Net of a supply voltage: 3V3 / 5V, else a project rail with that voltage, else '1V8', '12V5', '12V'."""
    for net in (*RAILS, *sorted(n for n in rails if n not in (*RAILS, GROUND))):
        v = rails.get(net)
        if v is not None and abs(v - volts) < 1e-9:
            return net
    whole, frac = int(volts), round((volts - int(volts)) * 100)
    frac_txt = f"{frac:02d}".rstrip("0")
    return f"{whole}V{frac_txt}"


@dataclass
class Passive:
    """A required part on a row: ``near`` pin on the row's net, ``far`` pin on ``net`` (its own port)."""

    part: Part
    near: str
    far: str
    net: str
    end: Endpoint
    port: str  # rail | ground | open (off-board net label) | net (the net of another row, end.node = its pin)
    volts: float | None


@dataclass
class Row:
    """One drawn module pin: box side, net, the port at the end of its line and the parts hanging on it."""

    pin: str
    signal: str
    side: str  # left | right
    net: str
    node: str
    end: Endpoint
    port: str  # gpio | rail | ground | open
    volts: float | None = None
    gpio: int | None = None
    passives: list[Passive] = field(default_factory=list)


@dataclass
class ModulePlan:
    module: Part
    rows: list[Row]
    netlist: Netlist
    board: Board
    gpios: dict[str, int]  # module pin -> GPIO
    assumptions: list[tuple[str, str, str]]
    notes: list[tuple[str, str, str, list[str]]]  # warnings: (code, severity, text, source ids)
    source_ids: list[str]
    shorts: list[tuple[str, list[str], str]] = field(default_factory=list)  # (net, what, severity), see _shorts
    nc: list[str] = field(default_factory=list)  # unconnected module outputs: drawn as NC, on no net


class _Wiring:
    """Nets in drawing order; every node wires to its net's first node (the endpoint) unless ``to`` is given."""

    def __init__(self, board: Board):
        self.b = _Builder(board)
        self.order: list[str] = []
        self.nodes: dict[str, list[str]] = {}
        self.edges: dict[str, list[tuple[str, str]]] = {}

    def join(self, net: str, node: str | Endpoint, to: str | None = None) -> str:
        name = self.b.endpoint(node) if isinstance(node, Endpoint) else node
        if net not in self.nodes:
            self.order.append(net)
            self.nodes[net], self.edges[net] = [name], []
            return name
        if name not in self.nodes[net]:
            self.edges[net].append((to or self.nodes[net][0], name))
            self.nodes[net].append(name)
        return name

    def done(self, parts: list[Part]) -> Netlist:
        self.b.parts = parts
        for net in self.order:
            self.b.nets.append((net, list(self.nodes[net])))
            self.b.wires.extend((a, c, net) for a, c in self.edges[net])
        return self.b.done()


def _bad(message: str, hint: str | None = None) -> BenchError:
    return BenchError("invalid_args", message, hint)


def _supply_range(entry: Mapping[str, Any], pin: str) -> tuple[float | None, float | None]:
    spec = (entry.get("supplies") or {}).get(pin)
    if not isinstance(spec, Mapping):
        return None, None
    return modules.value(spec.get("min"), {}), modules.value(spec.get("max"), {})


def _select(entry: Mapping[str, Any]) -> tuple[list[str], Mapping[str, Any], str | None]:
    """(select pins, map, default address) of the I²C interface; ``select.pins`` with comma keys is accepted too."""
    for it in entry.get("interfaces") or []:
        sel = it.get("select") if isinstance(it, Mapping) else None
        if isinstance(sel, Mapping) and isinstance(sel.get("map"), Mapping):
            pins = sel.get("pins") if isinstance(sel.get("pins"), list) else [sel.get("pin")]
            return [p for p in pins if isinstance(p, str)], sel["map"], it.get("default")
    return [], {}, None


def module_plan(entry: Mapping[str, Any], *, devkit: str | None, ref: str = "U1", value: str | None = None,
                conn: Mapping[str, Any] | None = None, gpios: Mapping[str, int] | None = None,
                address: str | None = None, facts: Mapping[str, Any] | None = None,
                rails: Mapping[str, float] | None = None, pin_net: Mapping[int, str] | None = None,
                r_pullup: float | None = None, driven: Mapping[str, tuple[str, bool]] | None = None,
                pin_mode: Mapping[int, str] | None = None,
                pullup_values: Mapping[str, tuple[str, str]] | None = None,
                pullups_present: Mapping[str, str] | None = None,
                board_pins: Mapping[str, str] | None = None,
                new_ref: Callable[[str], str] | None = None) -> ModulePlan:
    """Rows and netlist of a catalog module (``modules.Catalog.get``): pins to nets, required parts from
    ``requires[]``. Nets per pin, in this order: ``conn`` (``GPIO<n>`` = the project net of that GPIO), ``gpios``
    (module pin -> GPIO), ``tie``, then defaults: supply pins on 3V3 (else 5V) when the data's range holds it, gnd
    pins on GND, the address-select pin per the select map (``address``, else the interface default), signals on
    ``SDA``/``SCL``/… or the pin name. ``pin_net``: GPIO -> project net.

    Project context (all optional): ``driven`` {net: (driver such as "U1.1Y", push-pull)} of other project parts:
    an input on such a net without a GPIO gets a net label, not a GPIO placeholder. ``pin_mode`` {GPIO: assignment
    mode}: GPIOs that drive (out, pwm, SPI/UART outputs) count as drivers. ``pullup_values`` {net or "*i2c": (value,
    reason)} label pull-ups that have no value in the data (project resistor or stored i2c_pullup calculation).
    Module outputs (``*_out``) without a GPIO are a net label when connected, else NC (not drawn as a net).
    ``shorts``: nets with several GPIOs or several push-pull drivers (a short; schematic.netlist fails).

    On-board parts: ``facts.onboard`` (user-confirmed) drops the drawn decoupling capacitors
    (``decoupling``), pull-ups (``pullups``, as does a ``facts.pullups`` value) and the reset pin's GPIO placeholder
    (``reset_rc``: an unconnected ``reset_in`` pin is not drawn); each is named as an assumption "on the board
    (user-confirmed)". ``pullups_present`` {net: why}: the bus already has pull-ups elsewhere in the project (project
    resistors, another board, another module's schematic): not drawn again. ``board_pins`` {pin: why}: pins the
    breakout board wires itself (a bare-chip ``tie`` of a module variant, e.g. VBAT at the coin-cell holder): not
    drawn unless conn or gpios name them. ``new_ref("R")`` gives the refs of the drawn parts (default R1, R2, …)."""
    conn = {k: v for k, v in (conn or {}).items() if isinstance(k, str)}
    gpios = dict(gpios or {})
    facts = dict(facts or {})
    rails = {**modspec.FIXED_RAILS, **(rails or {})}
    pin_net = dict(pin_net or {})
    driven = dict(driven or {})
    pin_mode = dict(pin_mode or {})
    pullup_values = dict(pullup_values or {})
    pullups_present = dict(pullups_present or {})
    onboard = {str(x) for x in facts.get("onboard") or [] if isinstance(x, str)}
    if new_ref is None:
        counters = {"R": 0, "C": 0}

        def new_ref(prefix: str) -> str:
            counters[prefix] += 1
            return f"{prefix}{counters[prefix]}"
    net_gpio: dict[str, int] = {}
    for num, net in sorted(pin_net.items()):
        net_gpio.setdefault(net, num)
    src = entry["source_ids"][0]
    pins = [p for p in entry.get("pins") or [] if isinstance(p, Mapping) and p.get("signal") != "nc"]
    assumptions: list[tuple[str, str, str]] = []
    on_board: dict[str, str] = {}  # module pin -> why it is not drawn (the board wires it)
    for name, why in (board_pins or {}).items():
        on_board.setdefault(name, why)
    if "reset_rc" in onboard:
        for q in pins:
            if q.get("signal") == "reset_in":
                on_board.setdefault(q["name"], "facts.onboard lists reset_rc: the board's RC network drives it; "
                                               "not drawn as a GPIO")
    on_board = {n: w for n, w in on_board.items() if n not in conn and n not in gpios
                and any(q["name"] == n for q in pins)}
    for name, why in on_board.items():
        assumptions.append((f"{ref}.{name}", "on the board (user-confirmed)" if "facts" in why else "on the board",
                            why))
    pins = [q for q in pins if q["name"] not in on_board]
    by_name = {p["name"]: p for p in pins}
    power = {n for n, p in by_name.items() if p.get("signal") in ("supply", "gnd")}
    notes: list[tuple[str, str, str, list[str]]] = []
    nc = [p["name"] for p in entry.get("pins") or [] if isinstance(p, Mapping) and p.get("signal") == "nc"]
    if nc:
        assumptions.append(("nc_pins", ", ".join(nc), "not connected per the module data; not drawn"))
    sig_count: dict[str, int] = {}
    for p in pins:
        sig_count[p["signal"]] = sig_count.get(p["signal"], 0) + 1
    sel_pins, sel_map, sel_default = _select(entry)
    want_addr = address or sel_default
    gpio_of: dict[str, int] = {}  # module pin -> GPIO
    nets: dict[str, str] = {}

    def value_net(v: Any, seen: frozenset[str]) -> str | None:
        if not isinstance(v, str) or not v.strip():
            return None
        v = v.strip()
        if m := _GPIO_NET.match(v):
            return pin_net.get(int(m.group(1)), v)
        if v in power and v in by_name:
            return v if v in seen else net_of(v, seen)
        return v

    def default_net(name: str) -> str:
        p = by_name[name]
        sig = p.get("signal")
        if sig == "gnd":
            return GROUND
        if sig == "supply":
            lo, hi = _supply_range(entry, name)
            for rail in RAILS:
                if lo is not None and hi is not None and lo <= rails[rail] <= hi:
                    assumptions.append((f"{ref}.{name}", rail, (f"not connected in the project; {rail} lies in the "
                                        f"supply range {fmt_si(lo, 'V')} to {fmt_si(hi, 'V')} of the module data")))
                    return rail
            notes.append(("module_supply_open", "caution", (f"{ref}.{name}: no supply net given and none of 3V3/5V "
                          "lies in the documented range; connect it per the datasheet."), [src]))
            return f"{ref}_{name}"
        if name in sel_pins and want_addr:
            idx = sel_pins.index(name)
            for key, addr in sel_map.items():
                keys = str(key).split(",")
                if len(keys) == len(sel_pins) and str(addr).lower() == str(want_addr).lower():
                    target = keys[idx].strip()
                    how = "the chosen address" if address else "the default address of the module data"
                    assumptions.append((f"{ref}.{name}", target, f"{name} to {target} selects {addr} ({how})"))
                    return value_net(target, frozenset({name})) or target
        if sig in ESP_SIGNALS and sig in SIGNAL_NET and sig_count.get(sig) == 1:
            return SIGNAL_NET[sig]
        if sig in ESP_SIGNALS:
            return name.upper()
        return f"{ref}_{name}"

    def net_of(name: str, seen: frozenset[str] = frozenset()) -> str:
        if name in nets:
            return nets[name]
        seen = seen | {name}
        p = by_name[name]
        net = None
        if name in conn:
            raw = conn[name]
            if isinstance(raw, str) and (m := _GPIO_NET.match(raw.strip())):
                gpio_of[name] = int(m.group(1))
            net = value_net(raw, seen)
        elif name in gpios:
            gpio_of[name] = gpios[name]
            net = pin_net.get(gpios[name])
            if net is None:
                net = default_net(name)
        elif isinstance(p.get("tie"), str):
            net = value_net(p["tie"], seen)
        if net is None:
            net = default_net(name)
        nets[name] = net
        return net

    for name in by_name:
        net_of(name)
    for name, net in nets.items():  # a net the project assigns to a GPIO carries that GPIO
        if name not in gpio_of and net in net_gpio and by_name[name].get("signal") not in ("supply", "gnd"):
            gpio_of[name] = net_gpio[net]
    taken: dict[int, str] = {}
    for name, num in gpio_of.items():
        other = taken.get(num)
        if other is not None and nets[other] != nets[name]:
            raise _bad(f"GPIO{num} is given for {other} and {name} on different nets",
                       "one GPIO per signal; check params.gpios and the part's conn")
        taken.setdefault(num, name)
    explicit = set(conn) | set(gpios) | {n for n, q in by_name.items() if isinstance(q.get("tie"), str)}
    nc_out = [n for n in by_name if n not in gpio_of and n not in explicit and by_name[n].get("signal") in OUT_SIGNALS
              and nets[n] not in driven and nets[n] not in rails and sum(1 for v in nets.values() if v == nets[n]) == 1]
    if nc_out:
        why = ("module outputs without a connection in the project: drawn as NC; wire one to a GPIO input "
               "(params.gpios or the part's conn) if you read it")
        assumptions.append(("nc_outputs", ", ".join(nc_out), why))
    left = [n for n in by_name if by_name[n].get("signal") not in RIGHT_SIGNALS and n not in nc_out]
    right = sorted((n for n in by_name if by_name[n].get("signal") in RIGHT_SIGNALS),
                   key=lambda n: RIGHT_SIGNALS.index(by_name[n]["signal"]))
    first = next((gpio_of[n] for n in left + right if n in gpio_of), None)
    board = Board(devkit, first)
    kind = kind_of(entry)
    title = value or (str(entry.get("title") or "").split() or [str(entry["id"]).upper()])[0].strip(",;:")
    module = Part(ref, kind, title[:24] or str(entry["id"]).upper(), tuple(left + right))

    def port_for(net: str, name: str | None) -> tuple[Endpoint, str, float | None, int | None]:
        if name is not None and name in gpio_of:
            return board.gpio_endpoint(gpio_of[name]), "gpio", None, gpio_of[name]
        if net == GROUND:
            return board.rail(GROUND), "ground", 0.0, None
        if net in rails and rails[net] > 0:
            return board.supply(net), "rail", rails[net], None
        if name is not None and by_name[name].get("signal") in OUT_SIGNALS:
            return off_board(net), "open", None, None  # a module output feeds a net, never "from GPIO"
        if name is not None and net in driven and not driven[net][0].startswith(f"{ref}."):
            assumptions.append((f"{ref}.{name}", net, f"driven by {driven[net][0]} on {net}; connected by the net name"))
            return off_board(net), "open", None, None
        if name is not None and by_name[name].get("signal") in ESP_SIGNALS:
            return placeholder(net), "gpio", None, None
        return off_board(net), "open", None, None

    rows: list[Row] = []
    for side, names in (("left", left), ("right", right)):
        for name in names:
            end, port, volts, num = port_for(nets[name], name)
            rows.append(Row(name, by_name[name]["signal"], side, nets[name], module.pin(name), end, port, volts, num))
    shorts = _shorts(rows, by_name, ref, driven, pin_mode, pin_net, entry.get("io"))
    row_of = {r.pin: r for r in rows}
    parts: list[Part] = [module]
    skip_pullups = facts.get("pullups") not in (None, "none", "unknown") or "pullups" in onboard
    if skip_pullups:
        value_ = str(facts["pullups"]) if facts.get("pullups") not in (None, "none", "unknown") else \
            "on the board (user-confirmed)"
        why = "on the board (user-confirmed: facts.pullups / facts.onboard); not drawn"
        assumptions.append(("pullups", value_, why))
    skip_decoupling = "decoupling" in onboard
    skipped_bus: dict[str, str] = {}
    drew_pullup = False
    for req in entry.get("requires") or []:
        if not isinstance(req, Mapping):
            continue
        code = req.get("code")
        rsrc = req.get("source_id") or src
        req_pins = [p for p in req.get("pins") or [] if p in row_of and by_name[p].get("signal") != "gnd"]
        if code not in RESISTOR_CODES + CAPACITOR_CODES:
            what = f"{code.replace('_', ' ')}" + (f" on {', '.join(req_pins)}" if req_pins else "")
            extra = f" ({req['note']})" if isinstance(req.get("note"), str) else ""
            notes.append(("module_requires", "caution", f"{ref} needs a {what}{extra}; not drawn in this block.",
                          [rsrc]))
            continue
        if code == "pullup" and skip_pullups:
            continue
        if code == "decoupling" and skip_decoupling:
            assumptions.append((f"{ref}.decoupling", "on the board (user-confirmed)",
                                "facts.onboard lists decoupling; the capacitor"
                                + (f" on {', '.join(req_pins)}" if req_pins else "") + " is not drawn"))
            continue
        to = req.get("to")
        pairs: list[tuple[str, str]] = []
        if code == "termination" and not to and len(req_pins) == 2:
            pairs.append((req_pins[0], nets[req_pins[1]]))
        else:
            if isinstance(to, str) and to in by_name:
                far_net = nets[to]
            elif isinstance(to, str) and to.strip():
                far_net = value_net(to, frozenset()) or to.strip()
            elif code == "pullup":
                dom = (entry.get("io") or {}).get("domain")
                sup = dom if dom in by_name else next((n for n in right if by_name[n]["signal"] == "supply"), None)
                far_net = nets[sup] if sup else "3V3"
            else:
                far_net = GROUND
            pairs.extend((p, far_net) for p in req_pins)
        for pin, far_net in pairs:
            row = row_of[pin]
            if far_net == row.net:
                continue
            if code == "pullup" and row.net in pullups_present:
                skipped_bus.setdefault(row.net, pullups_present[row.net])
                continue
            if code in RESISTOR_CODES:
                pref, pkind = new_ref("R"), "resistor"
                drew_pullup = drew_pullup or code == "pullup"
                val = _ohms_text(req.get("value"))
                if val is None and code in ("pullup", "pulldown") and r_pullup is not None:
                    val = fmt_si(r_pullup, "Ω")
                    assumptions.append((pref, val, f"{code} value from params.r_pullup"))
                elif val is None and code == "pullup" and row.net in pullup_values:  # the resistor the project has on this net
                    val, why = pullup_values[row.net]
                    assumptions.append((pref, val, why))
                elif (val is None and code == "pullup" and row.signal in ("i2c_sda", "i2c_scl")
                      and I2C_CALC_KEY in pullup_values):
                    val, why = pullup_values[I2C_CALC_KEY]
                    assumptions.append((pref, val, why))
                if val is None:
                    val = "R"
                    hint = _UP_HINT.get(row.signal, "bench_calc")
                    note = f"; {req['note']}" if isinstance(req.get("note"), str) else ""
                    assumptions.append((pref, "R", (f"{code} on {pin}: no value in the module data, size it with "
                                        f"{hint}{note}")))
            else:
                pref = new_ref("C")
                pkind = req.get("kind") if req.get("kind") in CAP_KINDS else "capacitor"
                val = _farad_text(req.get("value"))
                if val is None:
                    val = "C"
                    assumptions.append((pref, "C", f"{code} on {pin}: no value in the module data"))
            part = Part(pref, pkind, val)
            parts.append(part)
            other = next((r for r in rows if r.net == far_net and r.port in ("gpio", "open")), None)
            if other is not None:  # the net of another pin (termination): connected by its name
                end, port, volts = Endpoint(other.node, far_net), "net", None
            else:
                end, port, volts, _num = port_for(far_net, None)
            row.passives.append(Passive(part, part.pin("1"), part.pin("2"), far_net, end, port, volts))
    if drew_pullup and facts.get("pullups") == "unknown":
        why = ("facts.pullups is unknown: the board may carry pull-ups already; measure SDA/SCL to VCC before you "
               "fit the drawn ones")
        assumptions.append(("pullups", "unknown", why))
    for net, why in skipped_bus.items():
        assumptions.append((f"pullup.{net}", "present", f"{why}; one set per bus, not drawn again"))
    w = _Wiring(board)
    for row in rows:
        w.join(row.net, row.end)
        w.join(row.net, row.node)
        for pa in row.passives:
            w.join(row.net, pa.near, to=row.node)
            if pa.port == "net":
                continue  # joined below, once that row's net exists
            w.join(pa.net, pa.end)
            w.join(pa.net, pa.far)
    for row in rows:
        for pa in row.passives:
            if pa.port == "net":
                w.join(pa.net, pa.far, to=pa.end.node)
    nl = w.done(parts)
    srcs = [src, *(s for s in nl.source_ids if s != src)]
    for h in entry.get("hazards") or []:
        if isinstance(h, Mapping) and isinstance(h.get("text"), str):
            sev = "danger" if h.get("code") in ("mains", "laser", "li_ion") else "caution"
            notes.append(("module_hazard", sev, f"{ref} ({h.get('code')}): {h['text']}", [h.get("source_id") or src]))
    return ModulePlan(module, rows, nl, board, dict(gpio_of), assumptions, notes, srcs, shorts, nc_out)


BUS_SIGNALS = frozenset(sig for sig in modspec.SIGNALS if sig.split("_")[0] in ("i2c", "spi", "uart", "i2s"))


def kind_of(entry: Mapping[str, Any]) -> str:
    return entry.get("kind") if entry.get("kind") in modspec.KINDS else "module"


def push_pull(pin: Mapping[str, Any], io: Any) -> bool:
    """True if a module output pin drives both levels: ``output: push_pull``, or no ``output`` and the module's
    ``io.outputs`` is push_pull (same reading as the rule mod.pin_role)."""
    if pin.get("signal") not in OUT_SIGNALS | {"uart_tx", "spi_sdo"}:
        return False
    if pin.get("output") is not None:
        return pin.get("output") == "push_pull"
    return isinstance(io, Mapping) and io.get("outputs") == "push_pull" and pin.get("signal") != "open_drain_out"


def _shorts(rows: list[Row], by_name: Mapping[str, Mapping[str, Any]], ref: str,
            driven: Mapping[str, tuple[str, bool]], pin_mode: Mapping[int, str],
            pin_net: Mapping[int, str], io: Any = None) -> list[tuple[str, list[str], str]]:
    """Nets the drawing shorts, as (net, what, severity) in row order:
    - two or more ESP GPIOs on one net (rows, or project assignments with that net): danger;
    - two or more push-pull drivers (driving GPIOs, push-pull module outputs here and in the project): danger;
    - two different bus signals of the module (SCK and MOSI, SDA and SCL) on one net: danger with a driver on the
      net, else caution. Rails and GND are never counted."""
    out: list[tuple[str, list[str], str]] = []
    for net in dict.fromkeys(r.net for r in rows if r.port not in ("rail", "ground")):
        on = [r for r in rows if r.net == net]
        gpios = sorted({*(r.gpio for r in on if r.gpio is not None), *(n for n, v in pin_net.items() if v == net)})
        drivers = [f"GPIO{n}" for n in gpios if pin_mode.get(n) in GPIO_DRIVE_MODES]
        drivers += [f"{ref}.{r.pin}" for r in on if push_pull(by_name[r.pin], io)]
        ext = driven.get(net)
        if ext is not None and ext[1] and not ext[0].startswith(f"{ref}."):
            drivers.append(ext[0])
        bus = list(dict.fromkeys(r.signal for r in on if r.signal in BUS_SIGNALS))
        if len(gpios) > 1:
            out.append((net, [f"GPIO{n}" for n in gpios], "danger"))
        elif len(drivers) > 1:
            out.append((net, drivers, "danger"))
        elif len(bus) > 1:
            pins = [f"{ref}.{r.pin}" for r in on if r.signal in BUS_SIGNALS]
            out.append((net, pins, "danger" if gpios or drivers else "caution"))
    return out


def ohms_text(value: Any) -> str | None:
    """Resistance text ("1.80 kΩ") of a value such as "1k8" or 1800; None if it is no resistance."""
    if value is None:
        return None
    from . import units
    try:
        v, unit = units.parse(value)
    except BenchError:
        return None
    if unit not in (None, "Ω") or not math.isfinite(v) or v <= 0:
        return None
    return fmt_si(v, "Ω")


def _ohms_text(value: Any) -> str | None:
    from . import units
    if value is None:
        return None
    try:
        v, unit = units.parse(value)
    except BenchError:
        return str(value)[:12]
    if unit not in (None, "Ω") or not math.isfinite(v) or v <= 0:
        return str(value)[:12]
    return fmt_si(v, "Ω")


def _farad_text(value: Any) -> str | None:
    from . import units
    if value is None:
        return None
    try:
        v, unit = units.parse(value)
    except BenchError:
        return str(value)[:12]
    if unit != "F" or not math.isfinite(v) or v <= 0:
        return str(value)[:12]
    return fmt_si(v, "F")


# --------------------------------------------------------------------------- level shifter (NXP AN10441)

@dataclass
class Channel:
    n: int
    lv: str  # net on the low-voltage side (source, GPIO)
    hv: str  # net on the high-voltage side (drain)
    lv_end: Endpoint
    hv_end: Endpoint
    gpio: int | None
    q: Part
    r_lv: Part
    r_hv: Part


@dataclass
class LevelPlan:
    channels: list[Channel]
    low: str
    high: str
    low_v: float
    high_v: float
    low_end: Endpoint
    high_end: Endpoint
    netlist: Netlist
    board: Board


def level_plan(*, devkit: str | None, channels: int, low_v: float, high_v: float, r_value: str, mosfet: str,
               gpios: Mapping[int, int] | None = None, names: Mapping[int, str] | None = None,
               rails: Mapping[str, float] | None = None, pin_net: Mapping[int, str] | None = None) -> LevelPlan:
    """BSS138 channels after AN10441: gate on the lower supply, source on the low side (the GPIO), drain on the high
    side, a pull-up on each side. ``gpios``: channel -> GPIO; ``names``: channel -> signal name (nets ``SDA`` and
    ``SDA_5V``), else ``LV<n>``/``HV<n>``; a GPIO with a project net (``pin_net``) names the low side."""
    rails = {**modspec.FIXED_RAILS, **(rails or {})}
    pin_net = dict(pin_net or {})
    gpios = dict(gpios or {})
    first = next((gpios[n] for n in range(1, channels + 1) if n in gpios), None)
    board = Board(devkit, first)
    low, high = rail_name(low_v, rails), rail_name(high_v, rails)
    low_end, high_end = board.supply(low), board.supply(high)
    w = _Wiring(board)
    parts: list[Part] = []
    chans: list[Channel] = []
    used: set[str] = {low, high, GROUND}
    names = dict(names or {})
    for n in range(1, channels + 1):
        num = gpios.get(n)
        lv = names.get(n) or (pin_net.get(num) if num is not None else None) or f"LV{n}"
        hv = f"{lv}_{high}" if lv != f"LV{n}" else f"HV{n}"
        if lv in used or hv in used:
            lv, hv = f"LV{n}", f"HV{n}"
        used.update((lv, hv))
        q = Part(f"Q{n}", "transistor", mosfet, MOSFET_PINS)
        r_lv = Part(f"R{2 * n - 1}", "resistor", r_value)
        r_hv = Part(f"R{2 * n}", "resistor", r_value)
        parts += [q, r_lv, r_hv]
        lv_end = board.gpio_endpoint(num) if num is not None else placeholder(lv)
        hv_end = off_board(hv)
        chans.append(Channel(n, lv, hv, lv_end, hv_end, num, q, r_lv, r_hv))
    for c in chans:
        w.join(c.lv, c.lv_end)
        w.join(c.lv, c.q.pin("S"))
        w.join(c.lv, c.r_lv.pin("1"))
        w.join(c.hv, c.hv_end)
        w.join(c.hv, c.q.pin("D"))
        w.join(c.hv, c.r_hv.pin("1"))
        w.join(low, low_end)
        w.join(low, c.q.pin("G"))
        w.join(low, c.r_lv.pin("2"))
        w.join(high, high_end)
        w.join(high, c.r_hv.pin("2"))
    return LevelPlan(chans, low, high, low_v, high_v, low_end, high_end, w.done(parts), board)
