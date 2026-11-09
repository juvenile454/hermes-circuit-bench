"""Schematic building blocks: themeable SVG plus nets and a wiring table.

``render(block, params, *, devkit=None, gpio=None, project=None, role=None)`` is the public action
``schematic.render`` and returns the result envelope with
``result = {block, svg, nets, parts, wiring, labels}``. With a project object and a role, the assignment of that role
gives the defaults for the GPIO, the signal net (``assignments[].net``, else the role name) and the DevKit;
explicit arguments win.

SVG rules (the desktop colours it through CSS ``color``):
- every stroke and fill is ``currentColor`` or ``none``; no background, no fixed colours
- labels are ``<text>`` in monospace at fixed positions per block (label sides never change, long texts grow away
  from the drawing); supplies as text ("+5 V", "+3.3 V")
- only a ``viewBox`` (tight around the ink: lines, symbols and label boxes plus ``PAD``) and
  ``preserveAspectRatio="xMidYMid meet"``, no width/height, so the UI can scale the drawing to its area;
  deterministic bytes for equal input
- every label box keeps at least ``MIN_CLEAR`` px from every line (pin markers 1/2, B/C/E, A/K included); the
  check ``schematic.labels_clear`` measures that on the finished SVG
- transparent hit areas ``<rect data-ref="R1" …>`` and ``data-ref``/``data-node`` on labels let the UI link a part
  to its rows in the wiring table
- every element carries its role ``data-kind`` (``wire | body | pin | label | port | junction``);
  wires, junctions, ports and port labels carry their ``data-net`` and part bodies their ``data-ref``. The ink of one
  role is merged per net (wires, ports) or per part (bodies) into one ``<path>``, the leads of a part body are split
  off as wires of the pin's net. The SVG stays valid on its own (one stroke width, ``currentColor``); the desktop
  styles strokes and net colours through these attributes only.

schemdraw draws the symbols (imported lazily; missing -> ``dependency_missing``). The labels are written by this
module, not by schemdraw: schemdraw estimates text width for a proportional font, which would cut monospace labels at
the edge of the viewBox and make the label boxes differ between schemdraw versions.
"""
from __future__ import annotations

import contextlib
import math
import re
import unicodedata
import xml.etree.ElementTree as ET
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from . import modspec, sources, wiring
from .contracts import BenchError, assumption, check, envelope, fail, format_si, warning

ACTION = "schematic.render"
SVG_NS = "http://www.w3.org/2000/svg"

# Geometry: schemdraw's SVG backend uses 72 pt per inch and inches_per_unit (0.5) -> 36 SVG units per drawing unit.
INCHES_PER_UNIT = 0.5
UNIT = 72 * INCHES_PER_UNIT
LINE_WIDTH = 1.5
FONT = "monospace"
FONT_SIZE = 12.0  # labels
PIN_FONT_SIZE = 10.0  # pin markers (1/2, B/C/E, A/K)
CHAR_EM = 0.6  # estimated monospace advance per character (em); the overlap check uses the same estimate
# Estimated label box height (em): one line box. Common monospace fonts have ascent + descent of about 1.13-1.17 em
# (layout estimate, not a measured fact); 1.2 keeps the box at least as tall as the text the browser lays out.
LINE_EM = 1.2
CLEAR = 7.0  # px between a label box and the stroke edge of the nearest line, used when placing labels
MIN_CLEAR = 6.0  # px, the minimum the check schematic.labels_clear accepts
TEXT_MAX = 24
PAD = 4.0  # viewBox margin around the ink (lines, symbols, label boxes), SVG units
# schemdraw symbol sizes in SVG units (identical in schemdraw 0.21 and 0.23; the clearance check measures the result)
ZIGZAG = 9.0  # resistor zigzag half-width (0.25 drawing units)
DOT = 2.7  # junction / terminal dot radius
LED_HALF = 9.0  # LED triangle half-width
VDD_HALF = 6.75  # supply bar half-width
GND_HALF = 9.0  # ground symbol: half-width of its top bar
GND_DROP = 0.4  # drawing units from the ground lead start down to that bar (14.4 px)
MAX_VOLTS = 60.0  # label range only; this plugin is for low voltage (product rule: no mains)

TITLES = {
    "led": "LED with series resistor",
    "npn_low_side": "NPN low-side driver",
    "button_pullup": "Push button with pull-up",
    "divider": "Voltage divider",
    "module": "Module with its required parts",
    "level_shifter": "BSS138 level shifter (AN10441)",
}
SUPPLY_TEXT = {"5V": "+5 V", "3V3": "+3.3 V"}


@dataclass(frozen=True)
class Param:
    """One row of a block's parameter table."""

    name: str
    type: str  # ohm | volt | text | net | choice
    default: Any
    required: bool
    doc: str
    choices: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        d = {"name": self.name, "type": self.type, "default": self.default, "required": self.required, "doc": self.doc}
        if self.choices:
            d["choices"] = list(self.choices)
        return d


# Parameter tables: name, type, default, required. Resistances in ohms (number or text such as "4k7", "10 kΩ").
PARAMS: dict[str, tuple[Param, ...]] = {
    "led": (
        Param("r_series", "ohm", None, True, "series resistor, ohms (size it with bench_calc led)"),
        Param("led", "text", "LED", False, "LED value text, e.g. 'red'"),
        Param("active", "choice", "high", False, "high: GPIO -> R1 -> LED -> GND; low: +3.3 V -> LED -> R1 -> GPIO",
              ("high", "low")),
        Param("net", "net", "LED", False, "signal net name"),
    ),
    "npn_low_side": (
        Param("r_base", "ohm", None, True, "base resistor, ohms (size it with bench_calc npn)"),
        Param("r_pulldown", "ohm", 10_000, False, "base pull-down to GND, ohms"),
        Param("transistor", "text", "2N2222A", False, "NPN transistor part number"),
        Param("load", "text", "load", False, "off-board load on the connector, e.g. 'laser module'"),
        Param("supply", "choice", "5V", False, "load supply pin of the board", ("5V", "3V3")),
        Param("net", "net", "LOAD_EN", False, "signal net name"),
    ),
    "button_pullup": (
        Param("r_pullup", "ohm", 10_000, False, "pull-up to +3.3 V, ohms"),
        Param("button", "text", "push button", False, "switch value text"),
        Param("net", "net", "BUTTON", False, "signal net name"),
    ),
    "divider": (
        Param("r1", "ohm", None, True, "top resistor (input side), ohms (size it with bench_calc divider)"),
        Param("r2", "ohm", None, True, "bottom resistor (to GND), ohms"),
        Param("v_in", "volt", None, False, "nominal input voltage, volts, max. 60 (label only; check with bench_calc)"),
        Param("source", "text", "input", False, "what feeds the input connector, e.g. 'battery'"),
        Param("input_net", "net", "VIN", False, "input net name"),
        Param("net", "net", "VSENSE", False, "ADC net name"),
    ),
    # multi-GPIO blocks; types id (catalog id, part ref, address) and map (objects)
    "module": (
        Param("module", "id", "bme280", False, "catalog module id (bench_pins action=modules); with part the "
              "module of that project part"),
        Param("variant", "id", None, False, "variant id of the module"),
        Param("part", "id", None, False, "project part such as U1 (needs project): module, variant, conn, address "
              "and facts of that part"),
        Param("gpios", "map", None, False, "{signal or pin name: GPIO}, e.g. {\"SDA\": 8, \"SCL\": 9}"),
        Param("conn", "map", None, False, "{module pin: net or GPIO<n>}, like conn of a project part"),
        Param("address", "id", None, False, "I²C address such as 0x77: sets the select pin's net"),
        Param("r_pullup", "ohm", None, False, "value for pull-ups the module data gives no value for (size it with "
              "bench_calc i2c_pullup); without it they are drawn as R"),
        Param("rails", "map", None, False, "{net: volts} extra supply rails such as VMOT or VBAT (low voltage, max. "
              "60 V); a project adds its options.rails"),
    ),
    "level_shifter": (
        Param("channels", "choice", 2, False, "number of BSS138 channels", (1, 2, 3, 4)),
        Param("low_v", "volt", 3.3, False, "low-side supply VDD1, volts: gates and low-side pull-ups"),
        Param("high_v", "volt", 5.0, False, "high-side supply VDD2, volts, at least low_v"),
        Param("r_pullup", "ohm", None, False, "pull-up on each side of a channel, ohms (size it with bench_calc "
              "i2c_pullup); without it they are drawn as R"),
        Param("mosfet", "text", "BSS138", False, "N-channel MOSFET part number"),
        Param("gpios", "map", None, False, "{channel: GPIO} on the low side; channel names such as SDA, SCL "
              "(nets SDA / SDA_5V) or LV1 ... LV4"),
        Param("rails", "map", None, False, "{net: volts} names for low_v/high_v (e.g. VBUS); a project adds its "
              "options.rails"),
    ),
}
BLOCKS = tuple(PARAMS)
MULTI_BLOCKS = ("module", "level_shifter")  # modspec.NEW_BLOCKS: several GPIOs per block
RESERVED_NETS = ("GND", "3V3", "5V")


def blocks() -> list[dict[str, Any]]:
    """Block catalogue with parameter tables (for tool schemas and the UI)."""
    return [{"block": b, "title": TITLES[b], "params": [p.as_dict() for p in PARAMS[b]]} for b in BLOCKS]


# --------------------------------------------------------------------------- values and validation

_OHM_UNIT = re.compile(r"\s*(?:Ω|ohms?)$", re.IGNORECASE)
_OHM_RKM = re.compile(r"(\d+)([RkKM])(\d+)")
_OHM_PLAIN = re.compile(r"(\d+(?:\.\d+)?)\s*([RkKM])?")
_MULT = {"R": 1.0, "k": 1e3, "K": 1e3, "M": 1e6, None: 1.0}
_VOLT = re.compile(r"(\d+(?:\.\d+)?)\s*V?|(\d+)V(\d+)", re.IGNORECASE)
_NET = re.compile(r"[A-Z][A-Z0-9_]{0,23}")
_GPIO = re.compile(r"(?:GPIO|IO)?(\d{1,2})", re.IGNORECASE)
_ID = re.compile(r"[A-Za-z0-9_.+-]{1,40}")
_MAP_NET = re.compile(r"[A-Za-z0-9_+.-]{1,32}")  # project net names (bench_core.project)
_KEY = re.compile(r"[A-Za-z0-9_+.-]{1,24}")
MAX_MAP = 48  # entries of gpios / conn / rails (modspec.MAX_CONN)


def parse_ohms(value: Any) -> float:
    """Ohms from a number or from '4k7', '220R', '10k', '1.5 kΩ', '1M', '470 ohm'. 'm' (milli) is refused."""
    if isinstance(value, bool):
        raise ValueError("not a resistance")
    if isinstance(value, int | float):
        ohms = float(value)
    elif isinstance(value, str):
        s = _OHM_UNIT.sub("", value.strip())
        if m := _OHM_RKM.fullmatch(s):
            ohms = float(f"{m.group(1)}.{m.group(3)}") * _MULT[m.group(2)]
        elif m := _OHM_PLAIN.fullmatch(s):
            ohms = float(m.group(1)) * _MULT[m.group(2)]
        else:
            raise ValueError(f"not a resistance: {value!r}")
    else:
        raise ValueError("not a resistance")
    if not math.isfinite(ohms) or ohms <= 0 or ohms > 1e9:
        raise ValueError(f"resistance out of range: {value!r}")
    return ohms


def parse_volts(value: Any) -> float:
    """Volts from a number or from '12', '12 V', '3.3V', '3V3'. Low voltage only (max. 60 V)."""
    if isinstance(value, bool):
        raise ValueError("not a voltage")
    if isinstance(value, int | float):
        volts = float(value)
    elif isinstance(value, str) and (m := _VOLT.fullmatch(value.strip())):
        volts = float(m.group(1)) if m.group(1) else float(f"{m.group(2)}.{m.group(3)}")
    else:
        raise ValueError(f"not a voltage: {value!r}")
    if not math.isfinite(volts) or volts <= 0 or volts > MAX_VOLTS:
        raise ValueError(f"voltage out of range: {value!r}")
    return volts


def _strip_zeros(text: str) -> str:
    num, _, unit = text.partition(" ")
    if "." in num:
        num = num.rstrip("0").rstrip(".")
    return f"{num} {unit}".strip()


def format_ohms(ohms: float) -> str:
    """'1 kΩ', '4.7 kΩ', '150 Ω', '10 kΩ'."""
    return _strip_zeros(format_si(ohms, "Ω", 4))


def format_volts(volts: float) -> str:
    """'+12 V', '+3.3 V'."""
    return "+" + _strip_zeros(format_si(volts, "V", 4))


def _bad(message: str, hint: str | None = None) -> BenchError:
    return BenchError("invalid_args", message, hint)


def _check_param(block: str, p: Param, value: Any) -> Any:
    where = f"{block}.{p.name}"
    if p.type == "ohm":
        try:
            return parse_ohms(value)
        except ValueError:
            raise _bad(f"{where} must be a resistance in ohms, got {value!r}",
                       "a positive number in ohms or text such as '4k7', '10 kΩ', '220R'") from None
    if p.type == "volt":
        try:
            return parse_volts(value)
        except ValueError:
            raise _bad(f"{where} must be a positive voltage in volts, got {value!r}",
                       "a number in volts or text such as '12 V', '3V3'") from None
    if p.type == "choice":
        if isinstance(value, str) and value.strip().isdigit() and all(isinstance(c, int) for c in p.choices):
            value = int(value.strip())
        if isinstance(value, bool) or value not in p.choices:
            raise _bad(f"{where} must be one of {', '.join(map(str, p.choices))}, got {value!r}")
        return value
    if p.type == "id":
        if not isinstance(value, str) or not _ID.fullmatch(value.strip()):
            raise _bad(f"{where} must be an id such as bme280, U1 or 0x76 (letters, digits, _ . + -; max. 40), "
                       f"got {value!r}")
        return value.strip()
    if p.type == "map":
        return _check_map(where, p.name, value)
    if not isinstance(value, str):
        raise _bad(f"{where} must be text, got {value!r}")
    text = value.strip()
    if p.type == "net":
        text = text.upper()
        if not _NET.fullmatch(text):
            raise _bad(f"{where} must be a net name like LASER_EN (A-Z, 0-9, _; max. 24), got {value!r}")
        if text in RESERVED_NETS:
            raise _bad(f"{where} must not be a supply net ({', '.join(RESERVED_NETS)})")
        return text
    if not text or len(text) > TEXT_MAX or not text.isprintable():
        raise _bad(f"{where} must be 1-{TEXT_MAX} printable characters, got {value!r}")
    return text


def _check_gpio(gpio: Any) -> int | None:
    if gpio is None:
        return None
    if isinstance(gpio, bool):
        raise _bad(f"gpio must be a GPIO number, got {gpio!r}")
    if isinstance(gpio, int):
        num = gpio
    elif isinstance(gpio, str) and (m := _GPIO.fullmatch(gpio.strip())):
        num = int(m.group(1))
    else:
        raise _bad(f"gpio must be a GPIO number such as 14 or 'GPIO14', got {gpio!r}")
    if not 0 <= num <= 63:
        raise _bad(f"gpio out of range: {gpio!r}")
    return num


_MAP_EXAMPLES = {  # (block, map) -> example object for the hint of a wrong type (a list instead of an object)
    ("level_shifter", "gpios"): '{"LV1": 2, "LV2": 1} (channel or signal name: GPIO)',
    ("module", "gpios"): '{"SDA": 8, "SCL": 9} (module pin or signal: GPIO)',
    ("", "gpios"): '{"LV1": 2} (name: GPIO)',
    ("", "conn"): '{"VCC": "3V3", "SDA": "GPIO8"} (module pin: net or GPIO<n>)',
    ("", "rails"): '{"VMOT": 12} (net: volts)',
}


def _check_map(where: str, name: str, value: Any) -> dict[str, Any]:
    """gpios {name: GPIO}, conn {pin: net | GPIO<n> | null}, rails {net: volts} (low voltage only)."""
    if not isinstance(value, Mapping) or len(value) > MAX_MAP:
        example = _MAP_EXAMPLES.get((where.split(".")[0], name), _MAP_EXAMPLES.get(("", name)))
        raise _bad(f"{where} must be an object with at most {MAX_MAP} entries, got {str(value)[:40]!r}",
                   f"for example {example}" if example else None)
    out: dict[str, Any] = {}
    for key, v in value.items():
        if not isinstance(key, str) or not _KEY.fullmatch(key.strip()):
            raise _bad(f"{where}: bad key {str(key)[:30]!r}", "names: letters, digits, _ + . -; max. 24")
        k = key.strip()
        if name == "gpios":
            num = _check_gpio(v)
            if num is None:
                raise _bad(f"{where}.{k} must be a GPIO number such as 8 or 'GPIO8'")
            out[k] = num
        elif name == "conn":
            if v is None:
                continue
            if not isinstance(v, str) or not _MAP_NET.fullmatch(v.strip()):
                raise _bad(f"{where}.{k} must be a net name or GPIO<n>, got {v!r}", "nets: [A-Za-z0-9_+.-]{1,32}")
            out[k] = v.strip()
        else:  # rails
            if not _MAP_NET.fullmatch(k) or k in RESERVED_NETS:
                raise _bad(f"{where}: {k!r} is no extra rail", "GND, 3V3 and 5V are fixed; e.g. VMOT, VBAT")
            try:
                out[k] = parse_volts(v)
            except ValueError:
                raise _bad(f"{where}.{k} must be a voltage above 0 V and up to {_n(MAX_VOLTS)} V, got {v!r}",
                           "low voltage only; never mains") from None
    return out


def validate(block: Any, params: Any) -> tuple[dict[str, Any], list[str]]:
    """Checked parameters with defaults filled in, plus the names that took their default."""
    if block not in PARAMS:
        raise _bad(f"unknown block {block!r}", f"blocks: {', '.join(BLOCKS)}")
    if params is None:
        params = {}
    if not isinstance(params, Mapping):
        raise _bad("params must be an object")
    table = {p.name: p for p in PARAMS[block]}
    unknown = sorted(set(params) - set(table))
    if unknown:
        raise _bad(f"unknown parameter(s) for {block}: {', '.join(map(str, unknown))}",
                   f"parameters: {', '.join(table)}")
    out: dict[str, Any] = {}
    defaulted: list[str] = []
    for name, p in table.items():
        value = params.get(name)
        if value is None:
            if p.required:
                raise _bad(f"{block}.{name} is required", p.doc)
            out[name] = _check_param(block, p, p.default) if p.default is not None else None
            if p.default is not None:
                defaulted.append(name)
        else:
            out[name] = _check_param(block, p, value)
    return out, defaulted


# --------------------------------------------------------------------------- drawing

@dataclass
class _Label:
    text: str
    x: float  # drawing units, y up
    y: float
    halign: str  # left | center | right
    valign: str  # bottom (text above the point) | center | top (text below the point)
    size: float = FONT_SIZE
    attrs: dict[str, str] = field(default_factory=dict)


KINDS = ("wire", "body", "pin", "label", "port", "junction")


@dataclass(frozen=True)
class _Tag:
    """Role of one schemdraw element: ``kind``, its net (wires, ports, junctions) or part ref (bodies), and the pins
    of a body as (anchor point in SVG units, net) for splitting off the leads."""

    kind: str
    net: str | None = None
    ref: str | None = None
    terminals: tuple[tuple[float, float, str], ...] = ()


def _tag_color(index: int) -> str:
    """Unique stand-in colour per element; _finish maps it back to the tag and writes currentColor."""
    return f"#{index + 1:06x}"


@dataclass
class _Sheet:
    d: Any
    elm: Any
    nl: wiring.Netlist | None = None
    labels: list[_Label] = field(default_factory=list)
    hits: list[tuple[str, list[Any]]] = field(default_factory=list)
    tags: list[_Tag] = field(default_factory=list)

    def net_of(self, node: str) -> str:
        nets = self.nl.nets if self.nl is not None else []
        return next(name for name, nodes in nets if node in nodes)

    def add(self, element, kind: str, *, node: str | None = None, ref: str | None = None,
            pins: Mapping[str, str] | None = None):
        """Add a schemdraw element with its role. ``node`` names the net (wire, port, junction) by one of its nodes;
        ``pins`` maps anchor names of a body to part pins (``{"start": "R1.1", "end": "R1.2"}``)."""
        if kind not in KINDS:
            raise ValueError(kind)
        element.color(_tag_color(len(self.tags)))
        placed = self.d.add(element)
        terms = tuple((float(getattr(placed, a)[0]) * UNIT, -float(getattr(placed, a)[1]) * UNIT, self.net_of(n))
                      for a, n in (pins or {}).items())
        self.tags.append(_Tag(kind, self.net_of(node) if node else None, ref, terms))
        return placed

    def text(self, text, x, y, halign="center", valign="center", kind="label", **attrs):
        attrs = {"data-kind": kind, **attrs}
        if "data-node" in attrs and "data-net" not in attrs:
            attrs["data-net"] = self.net_of(attrs["data-node"])
        self.labels.append(_Label(text, float(x), float(y), halign, valign, FONT_SIZE, attrs))

    def port_net(self, ep: wiring.Endpoint, x: float, halign: str) -> None:
        """Net name above the board-pin label of a port (one line box above the label at y = 0)."""
        net = self.net_of(ep.node)
        if net != ep.display:
            self.text(net, x, (LINE_EM * FONT_SIZE / 2 + 1) / UNIT, halign, "bottom", **{"data-net": net})

    def rail_pin(self, ends: Mapping[str, wiring.Endpoint], rail: str, x: float, y: float) -> None:
        """Header pin of a supply or ground port (``J1-21 · 5V``) right of the symbol's bar;
        only with a DevKit (without one the symbol and its text already say all)."""
        ep = ends.get(rail)
        if ep is not None and ep.display != ep.node:
            self.text(ep.display, x, y, "left", "center", **{"data-node": ep.node})

    def pin(self, text, x, y, halign="center", valign="center", pin=""):
        self.labels.append(_Label(text, float(x), float(y), halign, valign, PIN_FONT_SIZE,
                                  {"data-kind": "pin", "data-pin": pin}))

    def hit(self, ref, *elements):
        self.hits.append((ref, list(elements)))


def _part_label(part: wiring.Part) -> str:
    return f"{part.ref} {part.value}"


def _off(ink: float = 0.0) -> float:
    """Drawing units from a line axis to a label box: ``ink`` px of symbol beyond the axis, half the stroke and
    ``CLEAR``. Labels placed with it keep ``CLEAR`` px from the stroke edge."""
    return (ink + LINE_WIDTH / 2 + CLEAR) / UNIT


def _top(element) -> float:
    return float(element.get_bbox(transform=True, includetext=False).ymax)


TWO = ("start", "end")


def _two(part: wiring.Part, a: str, b: str) -> dict[str, str]:
    """Anchors of a two-terminal symbol -> part pins (start = first pin of the drawing direction)."""
    return {"start": part.pin(a), "end": part.pin(b)}


def _draw_led(s: _Sheet, nl: wiring.Netlist, p: Mapping[str, Any], ends: Mapping[str, wiring.Endpoint]) -> None:
    e = s.elm
    r1, d1 = nl.parts
    sig = ends["sig"]
    s.add(e.Dot(open=True).at((0, 0)), "port", node=sig.node)
    s.text(sig.display, -_off(DOT), 0, "right", "center", **{"data-node": sig.node})
    s.port_net(sig, -_off(DOT), "right")
    res = s.add(e.Resistor().at((0, 0)).right().length(3), "body", ref=r1.ref, pins=_two(r1, "1", "2"))
    s.text(_part_label(r1), 1.5, _off(ZIGZAG), "center", "bottom", **{"data-ref": r1.ref})
    s.add(e.Line().at((3, 0)).right().length(1), "wire", node=r1.pin("2"))
    if p["active"] == "high":
        led = s.add(e.LED().at((4, 0)).down().length(3), "body", ref=d1.ref, pins=_two(d1, "A", "K"))  # anode on top
        s.add(e.Ground().at((4, -3)), "port", node=d1.pin("K"))
        s.rail_pin(ends, wiring.GROUND, 4 + _off(GND_HALF), -3 - GND_DROP)
        a_y, k_y, mid = -0.55, -2.45, -1.5
    else:
        led = s.add(e.LED().at((4, 3)).down().length(3), "body", ref=d1.ref, pins=_two(d1, "A", "K"))
        vdd = s.add(e.Vdd().at((4, 3)), "port", node=d1.pin("A"))
        s.text(SUPPLY_TEXT["3V3"], 4, _top(vdd) + _off(), "center", "bottom", **{"data-node": ends["3V3"].node})
        s.rail_pin(ends, "3V3", 4 + _off(VDD_HALF), _top(vdd))
        a_y, k_y, mid = 2.45, 0.55, 1.5
    s.text(_part_label(d1), 4 - _off(LED_HALF), mid, "right", "center", **{"data-ref": d1.ref})
    # A/K beside the leads, clear of the horizontal wire at y=0 and of the LED body
    s.pin("A", 4 - _off(), a_y, "right", "center", pin=d1.pin("A"))
    s.pin("K", 4 - _off(), k_y, "right", "center", pin=d1.pin("K"))
    s.hit(r1.ref, res)
    s.hit(d1.ref, led)


def _draw_npn(s: _Sheet, nl: wiring.Netlist, p: Mapping[str, Any], ends: Mapping[str, wiring.Endpoint]) -> None:
    e = s.elm
    r1, r2, q1, j = nl.parts
    sig = ends["sig"]
    s.add(e.Dot(open=True).at((0, 0)), "port", node=sig.node)
    s.text(sig.display, -_off(DOT), 0, "right", "center", **{"data-node": sig.node})
    s.port_net(sig, -_off(DOT), "right")
    res1 = s.add(e.Resistor().at((0, 0)).right().length(3), "body", ref=r1.ref, pins=_two(r1, "1", "2"))
    s.text(_part_label(r1), 1.5, _off(ZIGZAG), "center", "bottom", **{"data-ref": r1.ref})
    s.add(e.Line().at((3, 0)).right().length(1), "wire", node=q1.pin("B"))
    s.add(e.Dot().at((3, 0)), "junction", node=q1.pin("B"))
    q = s.add(e.BjtNpn(circle=True).anchor("base").at((4, 0)), "body", ref=q1.ref,
              pins={"base": q1.pin("B"), "collector": q1.pin("C"), "emitter": q1.pin("E")})
    res2 = s.add(e.Resistor().at((3, 0)).down().length(3), "body", ref=r2.ref, pins=_two(r2, "1", "2"))
    s.text(_part_label(r2), 3 - _off(ZIGZAG), -1.5, "right", "center", **{"data-ref": r2.ref})
    s.add(e.Ground().at((3, -3)), "port", node=r2.pin("2"))
    cx = float(q.collector[0])
    s.add(e.Line().at(q.emitter).toy(-3), "wire", node=q1.pin("E"))
    s.add(e.Ground().at((cx, -3)), "port", node=q1.pin("E"))
    s.rail_pin(ends, wiring.GROUND, cx + _off(GND_HALF), -3 - GND_DROP)
    qbox = q.get_bbox(transform=True, includetext=False)
    s.text(_part_label(q1), qbox.xmax + _off(), 0, "left", "center", **{"data-ref": q1.ref})
    # B above the base wire between the junction dot and the circle; C/E left of the collector/emitter leads
    s.pin("B", 3.7, _off(), "center", "bottom", pin=q1.pin("B"))
    s.pin("C", cx - _off(), 1.05, "right", "center", pin=q1.pin("C"))
    s.pin("E", cx - _off(), -1.1, "right", "center", pin=q1.pin("E"))
    # off-board load on connector J: pin 2 = low side (collector), pin 1 = supply; the pin numbers sit at the leads,
    # outside the box and clear of both the lead and the box edge
    box_lo, box_hi = 2.3, 3.3
    s.add(e.Line().at(q.collector).toy(box_lo), "wire", node=q1.pin("C"))
    box = s.add(e.Rect(corner1=(cx - 0.6, box_lo), corner2=(cx + 0.6, box_hi)).at((0, 0)).theta(0), "body", ref=j.ref)
    s.add(e.Line().at((cx, box_hi)).toy(3.8), "wire", node=j.pin("1"))
    vdd = s.add(e.Vdd().at((cx, 3.8)), "port", node=j.pin("1"))
    s.text(SUPPLY_TEXT[p["supply"]], cx, _top(vdd) + _off(), "center", "bottom",
           **{"data-node": ends[p["supply"]].node})
    s.rail_pin(ends, p["supply"], cx + _off(VDD_HALF), _top(vdd))
    s.text(_part_label(j), cx + 0.6 + _off(), (box_lo + box_hi) / 2, "left", "center", **{"data-ref": j.ref})
    s.pin("1", cx - _off(), box_hi + _off(), "right", "bottom", pin=j.pin("1"))
    s.pin("2", cx - _off(), box_lo - _off(), "right", "top", pin=j.pin("2"))
    s.hit(r1.ref, res1)
    s.hit(r2.ref, res2)
    s.hit(q1.ref, q)
    s.hit(j.ref, box)


def _draw_button(s: _Sheet, nl: wiring.Netlist, p: Mapping[str, Any], ends: Mapping[str, wiring.Endpoint]) -> None:
    e = s.elm
    r1, sw = nl.parts
    sig = ends["sig"]
    s.add(e.Dot(open=True).at((0, 0)), "port", node=sig.node)
    s.text(sig.display, -_off(DOT), 0, "right", "center", **{"data-node": sig.node})
    s.port_net(sig, -_off(DOT), "right")
    s.add(e.Line().at((0, 0)).right().length(3), "wire", node=sig.node)
    s.add(e.Dot().at((3, 0)), "junction", node=sig.node)
    res = s.add(e.Resistor().at((3, 0)).up().length(3), "body", ref=r1.ref, pins=_two(r1, "2", "1"))
    vdd = s.add(e.Vdd().at((3, 3)), "port", node=r1.pin("1"))
    s.text(SUPPLY_TEXT["3V3"], 3, _top(vdd) + _off(), "center", "bottom", **{"data-node": ends["3V3"].node})
    s.rail_pin(ends, "3V3", 3 + _off(VDD_HALF), _top(vdd))
    s.text(_part_label(r1), 3 + _off(ZIGZAG), 1.5, "left", "center", **{"data-ref": r1.ref})
    btn = s.add(e.Button().at((3, 0)).down().length(3), "body", ref=sw.ref,  # actuator drawn to the right
                pins=_two(sw, "1", "2"))
    s.add(e.Ground().at((3, -3)), "port", node=sw.pin("2"))
    s.rail_pin(ends, wiring.GROUND, 3 + _off(GND_HALF), -3 - GND_DROP)
    left = float(btn.get_bbox(transform=True, includetext=False).xmin)
    s.text(_part_label(sw), left - _off(), -1.5, "right", "center", **{"data-ref": sw.ref})
    s.hit(r1.ref, res)
    s.hit(sw.ref, btn)


def _draw_divider(s: _Sheet, nl: wiring.Netlist, p: Mapping[str, Any], ends: Mapping[str, wiring.Endpoint]) -> None:
    e = s.elm
    r1, r2, j = nl.parts
    sig = ends["sig"]
    box = s.add(e.Rect(corner1=(-0.7, -3.5), corner2=(0, 3.5)).at((0, 0)).theta(0), "body", ref=j.ref)
    s.text(_part_label(j), -0.7 - _off(), 0, "right", "center", **{"data-ref": j.ref})
    # pin numbers inside the box, between the box edges and level with their wire (>= CLEAR from both)
    s.pin("1", -0.35, 3, "center", "center", pin=j.pin("1"))
    s.pin("2", -0.35, -3, "center", "center", pin=j.pin("2"))
    s.add(e.Line().at((0, 3)).right().length(2), "wire", node=j.pin("1"))
    vin = format_volts(p["v_in"]) if p["v_in"] is not None else p["input_net"]
    s.text(vin, _off(), 3 + _off(), "left", "bottom", **{"data-net": s.net_of(j.pin("1"))})
    res1 = s.add(e.Resistor().at((2, 3)).down().length(3), "body", ref=r1.ref, pins=_two(r1, "1", "2"))
    s.text(_part_label(r1), 2 + _off(ZIGZAG), 1.5, "left", "center", **{"data-ref": r1.ref})
    s.add(e.Dot().at((2, 0)), "junction", node=sig.node)
    s.add(e.Line().at((2, 0)).right().length(3), "wire", node=sig.node)
    s.add(e.Dot(open=True).at((5, 0)), "port", node=sig.node)
    s.text(sig.display, 5 + _off(DOT), 0, "left", "center", **{"data-node": sig.node})
    s.port_net(sig, 5 + _off(DOT), "left")
    res2 = s.add(e.Resistor().at((2, 0)).down().length(3), "body", ref=r2.ref, pins=_two(r2, "1", "2"))
    s.text(_part_label(r2), 2 + _off(ZIGZAG), -1.5, "left", "center", **{"data-ref": r2.ref})
    s.add(e.Line().at((0, -3)).right().length(2), "wire", node=j.pin("2"))
    s.add(e.Dot().at((2, -3)), "junction", node=j.pin("2"))
    s.add(e.Ground().at((2, -3)), "port", node=j.pin("2"))
    s.rail_pin(ends, wiring.GROUND, 2 + _off(GND_HALF), -3 - GND_DROP)
    s.hit(r1.ref, res1)
    s.hit(r2.ref, res2)
    s.hit(j.ref, box)


# --------------------------------------------------------------------------- multi-GPIO blocks
# Module: a box with the pins (signals left, supplies right), one line per pin to its port (GPIO pin, rail, GND or
# a net label); every required part in its own column next to the box, above the rows (to a rail or a net label) or
# below them (to GND). Labels of a column grow away from the box; the column pitch fits the widest of them.

ROW = 1.0  # drawing units between pin rows (36 px)
LEAD = 1.0  # box edge -> first parts column
RISE = 0.5  # top (bottom) row -> start of a part body in a column
BODY = 2.0  # length of a required part
BOX_MARGIN = 0.6  # box edge above the first and below the last row
CAP_HALF = 9.0  # capacitor plate half-width (0.25 drawing units)
CH_PITCH = 5.0  # level shifter: drawing units between channels
_PORT_ORDER = {"gpio": 0, "open": 1, "rail": 2, "ground": 3, "nc": 4}  # rows per side: a ground symbol hangs below its row


def _units(px: float) -> float:
    """px -> drawing units, rounded up to a quarter unit (grid)."""
    return math.ceil(px / UNIT * 4) / 4


def _rail_text(net: str, volts: float | None) -> str:
    if net in SUPPLY_TEXT:
        return SUPPLY_TEXT[net]
    return f"{net} {format_volts(volts)}" if volts else net


def _above(s: _Sheet, text: str, x: float, y: float, halign: str, net: str) -> None:
    """A second line above a port label (net or supply), like ``_Sheet.port_net`` at any row."""
    s.text(text, x, y + (LINE_EM * FONT_SIZE / 2 + 1) / UNIT, halign, "bottom", **{"data-net": net})


def _row_port(s: _Sheet, r: wiring.Row, x: float, y: float, out: int) -> None:
    """The end of a pin row: open dot (GPIO, net label), bar (rail) or ground symbol; labels away from the box."""
    e = s.elm
    align = "right" if out < 0 else "left"
    ep = r.end
    if r.port == "ground":
        s.add(e.Ground().at((x, y)), "port", node=r.node)
        if ep.display != ep.node:
            s.text(ep.display, x + out * _off(GND_HALF), y - GND_DROP, align, "center", **{"data-node": ep.node})
        return
    if r.port == "rail":
        s.add(e.Line().at((x, y - VDD_HALF / UNIT)).up().length(2 * VDD_HALF / UNIT), "port", node=r.node)
        tx = x + out * _off()
        if ep.display != ep.node:
            s.text(ep.display, tx, y, align, "center", **{"data-node": ep.node})
            _above(s, _rail_text(r.net, r.volts), tx, y, align, r.net)
        else:
            s.text(_rail_text(r.net, r.volts), tx, y, align, "center", **{"data-node": ep.node})
        return
    s.add(e.Dot(open=True).at((x, y)), "port", node=r.node)
    tx = x + out * _off(DOT)
    s.text(ep.display, tx, y, align, "center", **{"data-node": ep.node})
    if r.net != ep.display:
        _above(s, r.net, tx, y, align, r.net)


def _column_labels(pa: wiring.Passive) -> tuple[list[float], list[float]]:
    """(widths of labels beside the column, widths of labels centred on it)."""
    side = [text_width(_part_label(pa.part), FONT_SIZE)]
    centred: list[float] = []
    if pa.port == "rail":
        centred.append(text_width(_rail_text(pa.net, pa.volts), FONT_SIZE))
    if pa.port in ("rail", "ground") and pa.end.display != pa.end.node:
        side.append(text_width(pa.end.display, FONT_SIZE))
    if pa.port == "open":
        centred.append(text_width(pa.net, FONT_SIZE))
    return side, centred


def _pitch(cols: list[tuple[wiring.Row, wiring.Passive]]) -> float:
    """Column pitch: the widest side label plus clearance to both columns' ink (9 px each), or the widest centred
    label (half of it on each side of a column)."""
    need = 1.5 * UNIT
    ink = max(ZIGZAG, CAP_HALF, VDD_HALF, GND_HALF, DOT)
    for _row, pa in cols:
        side, centred = _column_labels(pa)
        need = max(need, *(w + 2 * (ink + LINE_WIDTH / 2 + CLEAR) for w in side),
                   *(w + 2 * CLEAR for w in centred))
    return _units(need)


def _up(pa: wiring.Passive) -> bool:
    """Parts to a rail or a net label stand above their row, parts to GND hang below it."""
    return pa.port != "ground"


def _reach(pa: wiring.Passive) -> float:
    """Drawing units a required part takes above (below) its row: lead, body, port symbol and the label on top."""
    label = _off() + (LINE_EM * FONT_SIZE + CLEAR + DOT) / UNIT  # up to the junction dot of the row above
    if pa.port == "rail":
        return RISE + BODY + 0.4 + label
    if pa.port == "ground":
        return RISE + BODY + 0.64 + (CLEAR + DOT) / UNIT
    return RISE + BODY + (DOT + LINE_WIDTH) / UNIT + label


def _row_ys(rows: list[wiring.Row]) -> list[float]:
    """y of each row: one ROW apart, more where a part of the row stands above it or of the row before hangs
    below it, so no part column crosses another row's line."""
    ys: list[float] = []
    y = 0.0
    for i, r in enumerate(rows):
        if i:
            need = max([ROW, *(_reach(pa) for pa in r.passives if _up(pa)),
                        *(_reach(pa) for pa in rows[i - 1].passives if not _up(pa))])
            y -= math.ceil(need * 4) / 4
        ys.append(y)
    return ys


def _column(s: _Sheet, pa: wiring.Passive, x: float, y_row: float, out: int) -> None:
    """One required part: junction on its row, lead, the body, its port; labels away from the box."""
    e = s.elm
    align = "right" if out < 0 else "left"
    up = _up(pa)
    sign = 1 if up else -1
    y0 = y_row + sign * RISE
    y1 = y0 + sign * BODY
    s.add(e.Dot().at((x, y_row)), "junction", node=pa.near)
    s.add(e.Line().at((x, y_row)).toy(y0), "wire", node=pa.near)
    cap = pa.part.kind in wiring.CAP_KINDS
    sym = e.Capacitor() if cap else e.Resistor()
    body = s.add((sym.up() if up else sym.down()).at((x, y0)).length(BODY), "body", ref=pa.part.ref,
                 pins={"start": pa.near, "end": pa.far})
    half = CAP_HALF if cap else ZIGZAG
    s.text(_part_label(pa.part), x + out * _off(half), (y0 + y1) / 2, align, "center", **{"data-ref": pa.part.ref})
    if pa.part.kind == "electrolytic":  # polarity: + on the pin at the row (the supply side of a bulk capacitor)
        s.pin("+", x + out * _off(half), y0 + sign * BODY / 4, align, "center", pin=pa.near)
    s.hit(pa.part.ref, body)
    if pa.port == "rail":
        vdd = s.add(e.Vdd().at((x, y1)), "port", node=pa.far)
        s.text(_rail_text(pa.net, pa.volts), x, _top(vdd) + _off(), "center", "bottom",
               **{"data-node": pa.end.node})
        if pa.end.display != pa.end.node:
            s.text(pa.end.display, x + out * _off(VDD_HALF), _top(vdd), align, "center",
                   **{"data-node": pa.end.node})
    elif pa.port == "ground":
        s.add(e.Ground().at((x, y1)), "port", node=pa.far)
        if pa.end.display != pa.end.node:
            s.text(pa.end.display, x + out * _off(GND_HALF), y1 - GND_DROP, align, "center",
                   **{"data-node": pa.end.node})
    else:  # a net label: off-board net, or the net of another row (connected by name)
        s.add(e.Dot(open=True).at((x, y1)), "port", node=pa.far)
        s.text(pa.net, x, y1 + _off(DOT), "center", "bottom", **{"data-node": pa.end.node})


def _draw_module(s: _Sheet, nl: wiring.Netlist, p: Mapping[str, Any], ends: Mapping[str, wiring.Endpoint]) -> None:
    e = s.elm
    plan: wiring.ModulePlan = p["_plan"]
    u = plan.module
    nc_rows = [wiring.Row(n, "nc", "left", "", f"{u.ref}.{n}", wiring.Endpoint("", "NC"), "nc") for n in plan.nc]
    sides = {side: sorted((r for r in [*plan.rows, *nc_rows] if r.side == side), key=lambda r: _PORT_ORDER[r.port])
             for side in ("left", "right")}
    ys = {side: _row_ys(rows) for side, rows in sides.items()}
    y_bot = min([0.0, *ys["left"], *ys["right"]])
    wl = max((text_width(r.pin, PIN_FONT_SIZE) for r in sides["left"]), default=0.0)
    wr = max((text_width(r.pin, PIN_FONT_SIZE) for r in sides["right"]), default=0.0)
    inner = 2 * (LINE_WIDTH / 2 + CLEAR) + wl + wr + 3 * CLEAR
    width = _units(max(inner, text_width(_part_label(u), FONT_SIZE) + 2 * CLEAR, 2 * UNIT))
    box = s.add(e.Rect(corner1=(0, y_bot - BOX_MARGIN), corner2=(width, BOX_MARGIN)).at((0, 0)).theta(0),
                "body", ref=u.ref)
    s.text(_part_label(u), width / 2, BOX_MARGIN + _off(), "center", "bottom", **{"data-ref": u.ref})
    s.hit(u.ref, box)
    for side, out, edge in (("left", -1, 0.0), ("right", 1, width)):
        rows = sides[side]
        width_cols = max([0, *(len(r.passives) for r in rows)])
        pitch = _pitch([(r, pa) for r in rows for pa in r.passives])
        port_x = edge + out * (LEAD + width_cols * pitch if width_cols else 2.0)
        for r, y in zip(rows, ys[side], strict=True):
            if r.port == "nc":  # an unconnected output: pin name in the box, "NC" outside, no line, no net
                s.pin(r.pin, _off(), y, "left", "center", pin=r.node)
                s.text("NC", edge + out * _off(), y, "right" if out < 0 else "left", "center")
                continue
            s.add(e.Line().at((edge, y)).tox(port_x), "wire", node=r.node)
            if side == "left":
                s.pin(r.pin, _off(), y, "left", "center", pin=r.node)
            else:
                s.pin(r.pin, width - _off(), y, "right", "center", pin=r.node)
            _row_port(s, r, port_x, y, out)
            for k, pa in enumerate(r.passives):
                _column(s, pa, edge + out * (LEAD + k * pitch), y, out)


def _draw_level(s: _Sheet, nl: wiring.Netlist, p: Mapping[str, Any], ends: Mapping[str, wiring.Endpoint]) -> None:
    """One BSS138 channel per row after AN10441 Fig. 1: low side (GPIO) left on the source, high side right on the
    drain, the gate on the low supply, a pull-up on each side."""
    e = s.elm
    plan: wiring.LevelPlan = p["_plan"]
    x_lv, x_rl, x_s, x_rh, x_hv = 0.0, 2.0, 4.0, 7.5, 9.5
    rail_y = 2.5
    for i, c in enumerate(plan.channels):
        y = -i * CH_PITCH
        g, d, src = c.q.pin("G"), c.q.pin("D"), c.q.pin("S")
        s.add(e.Dot(open=True).at((x_lv, y)), "port", node=src)
        s.text(c.lv_end.display, x_lv - _off(DOT), y, "right", "center", **{"data-node": c.lv_end.node})
        if c.lv != c.lv_end.display:
            _above(s, c.lv, x_lv - _off(DOT), y, "right", c.lv)
        s.add(e.Line().at((x_lv, y)).tox(x_s), "wire", node=src)
        s.add(e.Dot().at((x_rl, y)), "junction", node=src)
        r_lv = s.add(e.Resistor().at((x_rl, y)).up().length(rail_y), "body", ref=c.r_lv.ref,
                     pins=_two(c.r_lv, "1", "2"))
        s.text(_part_label(c.r_lv), x_rl - _off(ZIGZAG), y + rail_y / 2, "right", "center",
               **{"data-ref": c.r_lv.ref})
        q = s.add(e.NFet().theta(90).flip().anchor("source").at((x_s, y)), "body", ref=c.q.ref,
                  pins={"source": src, "drain": d, "gate": g})
        gx, gy = float(q.gate[0]), float(q.gate[1])
        s.add(e.Line().at((x_rl, y + rail_y)).tox(gx), "wire", node=g)
        s.add(e.Line().at((gx, y + rail_y)).toy(gy), "wire", node=g)
        s.add(e.Dot().at((x_rl, y + rail_y)), "junction", node=g)
        vdd = s.add(e.Vdd().at((x_rl, y + rail_y)), "port", node=g)
        s.text(_rail_text(plan.low, plan.low_v), x_rl, _top(vdd) + _off(), "center", "bottom",
               **{"data-node": plan.low_end.node})
        if plan.low_end.display != plan.low_end.node:
            s.text(plan.low_end.display, x_rl - _off(VDD_HALF), _top(vdd), "right", "center",
                   **{"data-node": plan.low_end.node})
        s.pin("G", gx + _off(), (gy + y + rail_y) / 2, "left", "center", pin=g)
        s.pin("S", (x_s + float(q.drain[0])) / 2 - 0.55, y - _off(), "center", "top", pin=src)
        s.pin("D", (x_s + float(q.drain[0])) / 2 + 0.55, y - _off(), "center", "top", pin=d)
        s.text(_part_label(c.q), gx, y - _off() - (LINE_EM * PIN_FONT_SIZE + 2) / UNIT, "center", "top",
               **{"data-ref": c.q.ref})
        s.add(e.Line().at(q.drain).tox(x_hv), "wire", node=d)
        s.add(e.Dot().at((x_rh, y)), "junction", node=d)
        r_hv = s.add(e.Resistor().at((x_rh, y)).up().length(rail_y), "body", ref=c.r_hv.ref,
                     pins=_two(c.r_hv, "1", "2"))
        s.text(_part_label(c.r_hv), x_rh + _off(ZIGZAG), y + rail_y / 2, "left", "center",
               **{"data-ref": c.r_hv.ref})
        vdd2 = s.add(e.Vdd().at((x_rh, y + rail_y)), "port", node=c.r_hv.pin("2"))
        s.text(_rail_text(plan.high, plan.high_v), x_rh, _top(vdd2) + _off(), "center", "bottom",
               **{"data-node": plan.high_end.node})
        if plan.high_end.display != plan.high_end.node:
            s.text(plan.high_end.display, x_rh + _off(VDD_HALF), _top(vdd2), "left", "center",
                   **{"data-node": plan.high_end.node})
        s.add(e.Dot(open=True).at((x_hv, y)), "port", node=d)
        s.text(c.hv_end.display, x_hv + _off(DOT), y, "left", "center", **{"data-node": c.hv_end.node})
        s.hit(c.r_lv.ref, r_lv)
        s.hit(c.q.ref, q)
        s.hit(c.r_hv.ref, r_hv)


DRAW = {"led": _draw_led, "npn_low_side": _draw_npn, "button_pullup": _draw_button, "divider": _draw_divider,
        "module": _draw_module, "level_shifter": _draw_level}


# --------------------------------------------------------------------------- SVG post-processing

_NUM = re.compile(r"-?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?")
_PATH_TOKEN = re.compile(r"[A-Za-z]|-?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?")
_GEOMETRY = {"path", "circle", "polygon", "polyline", "line", "rect", "ellipse"}
_SHAPE_ATTRS = {
    "path": ("d",), "circle": ("cx", "cy", "r"), "polygon": ("points",), "polyline": ("points",),
    "line": ("x1", "y1", "x2", "y2"), "rect": ("x", "y", "width", "height"), "ellipse": ("cx", "cy", "rx", "ry"),
}


def _n(v: float) -> str:
    s = f"{round(float(v), 2):.2f}".rstrip("0").rstrip(".")
    return "0" if s in ("-0", "") else s


def _round_numbers(text: str) -> str:
    return _NUM.sub(lambda m: _n(float(m.group(0))), text)


def _path_d(d: str) -> str:
    """Rounded, compact path data ("M0,0 L36,0 Z"); only M/L/Z occur in schemdraw's output for these symbols."""
    parts: list[str] = []
    nums: list[float] = []

    def flush() -> None:
        if len(nums) % 2:
            raise RuntimeError("odd number of path coordinates in schemdraw output")
        parts.extend(f"{_n(nums[i])},{_n(nums[i + 1])}" for i in range(0, len(nums), 2))
        nums.clear()

    for tok in _PATH_TOKEN.findall(d):
        if tok.isalpha():
            if tok not in "MLZ":
                raise RuntimeError(f"unsupported path command {tok!r} in schemdraw output")
            flush()
            parts.append(tok)
        else:
            nums.append(float(tok))
    flush()
    return re.sub(r"([MLZ]) (?=-?\d)", r"\1", " ".join(parts))


def _style(el: ET.Element) -> dict[str, str]:
    out = {}
    for decl in (el.get("style") or "").split(";"):
        if ":" in decl:
            k, v = decl.split(":", 1)
            out[k.strip().lower()] = v.strip()
    for k in ("fill", "stroke", "stroke-width", "stroke-linecap", "stroke-linejoin"):
        if el.get(k) is not None:
            out[k] = el.get(k, "")
    return out


def _paint(value: str | None) -> str | None:
    """currentColor for any colour, 'none' for none; the drawing never carries a fixed colour."""
    if value is None:
        return None
    return "none" if value.strip().lower() in ("none", "transparent", "") else "currentColor"


def _copy_shape(src: ET.Element, tag: str, ink: str | None = None) -> ET.Element:
    """Shape with rounded geometry and paint as currentColor/none. ``ink`` is the element's stand-in colour: a fill
    in that colour is a filled symbol part (junction dot, arrow head), any other fill (schemdraw's background for open
    dots) stays unfilled."""
    out = ET.Element(tag)
    for a in _SHAPE_ATTRS[tag]:
        v = src.get(a)
        if v is None:
            continue
        out.set(a, _path_d(v) if a == "d" else _round_numbers(v).strip())
    st = _style(src)
    fill = _paint(st.get("fill"))
    stroke = _paint(st.get("stroke"))
    filled = {"currentcolor", "black", *((ink.lower(),) if ink else ())}
    if fill == "currentColor" and st.get("fill", "").lower() not in filled:
        fill = "none"
    if fill == "currentColor":
        out.set("fill", "currentColor")
    if stroke == "none":
        out.set("stroke", "none")
    width = st.get("stroke-width")
    if width and _n(float(width)) != _n(LINE_WIDTH):
        out.set("stroke-width", _n(float(width)))
    for k in ("stroke-linecap", "stroke-linejoin"):
        if st.get(k) and st[k] != "round":
            out.set(k, st[k])
    return out


def _subpaths(d: str) -> list[tuple[list[str], bool]]:
    """Rounded path data -> [(["x,y", ...], closed)]."""
    out: list[tuple[list[str], bool]] = []
    for cmd, arg in re.findall(r"([MLZ])([^MLZ]*)", d):
        if cmd == "M":
            out.append(([arg.strip()], False))
        elif cmd == "L":
            out[-1][0].append(arg.strip())
        else:
            out[-1] = (out[-1][0], True)
    return out


def _join_d(subs: list[tuple[list[str], bool]]) -> str:
    return " ".join(" ".join([f"M{pts[0]}", *(f"L{q}" for q in pts[1:]), *(["Z"] if closed else [])])
                    for pts, closed in subs)


def _xy(pt: str) -> tuple[float, float]:
    x, y = pt.split(",")
    return float(x), float(y)


def _split_leads(d: str, terminals: tuple[tuple[float, float, str], ...]) -> tuple[str, list[tuple[str, str]]]:
    """Cut the leads off a body path: an end segment of an open sub-path that starts at a pin anchor and runs
    horizontally or vertically is a wire of that pin's net. Returns (body path data or "", [(net, lead data)])."""
    body: list[tuple[list[str], bool]] = []
    leads: list[tuple[str, str]] = []

    def pin_net(pt: str) -> str | None:
        x, y = _xy(pt)
        return next((net for tx, ty, net in terminals if abs(tx - x) < 0.02 and abs(ty - y) < 0.02), None)

    def straight(a: str, b: str) -> bool:
        (x0, y0), (x1, y1) = _xy(a), _xy(b)
        return abs(x0 - x1) < 0.01 or abs(y0 - y1) < 0.01

    for pts, closed in _subpaths(d):
        pts = list(pts)
        if not closed and len(pts) >= 2 and (net := pin_net(pts[0])) and straight(pts[0], pts[1]):
            leads.append((net, f"M{pts[0]} L{pts[1]}"))
            pts = pts[1:]
        if not closed and len(pts) >= 2 and (net := pin_net(pts[-1])) and straight(pts[-2], pts[-1]):
            leads.append((net, f"M{pts[-2]} L{pts[-1]}"))
            pts = pts[:-1]
        if len(pts) >= 2:
            body.append((pts, closed))
    return _join_d(body), leads


def _on_axis(a: str, b: str, c: str) -> bool:
    """b lies on the horizontal or vertical segment a-c (a collinear midpoint schemdraw adds to lines)."""
    (x0, y0), (x1, y1), (x2, y2) = _xy(a), _xy(b), _xy(c)
    if abs(x0 - x1) < 0.01 and abs(x1 - x2) < 0.01:
        return min(y0, y2) - 0.01 <= y1 <= max(y0, y2) + 0.01
    if abs(y0 - y1) < 0.01 and abs(y1 - y2) < 0.01:
        return min(x0, x2) - 0.01 <= x1 <= max(x0, x2) + 0.01
    return False


def _compact_d(ds: list[str]) -> str:
    """One path from the pieces of one role: open pieces that meet end to start are chained, collinear midpoints
    of straight runs dropped. The ink stays the same."""
    chains: list[list[str]] = []
    closed: list[tuple[list[str], bool]] = []
    for d in ds:
        for pts, is_closed in _subpaths(d):
            if is_closed:
                closed.append((pts, True))
                continue
            pts = list(pts)
            for ch in chains:
                if ch[-1] == pts[0]:
                    ch.extend(pts[1:])
                    break
                if ch[0] == pts[-1]:
                    ch[:0] = pts[:-1]
                    break
            else:
                chains.append(pts)
    out = []
    for ch in chains:
        pts = [ch[0]]
        for i in range(1, len(ch) - 1):
            if not _on_axis(pts[-1], ch[i], ch[i + 1]):
                pts.append(ch[i])
        pts.append(ch[-1])
        out.append((pts, False))
    return _join_d(out + closed)


# drawing order: lines below symbols, junction dots on top; hit areas and labels follow
_KIND_ORDER = {"wire": 0, "port": 1, "body": 2, "junction": 3}


def _role_attrs(kind: str, net: str | None, ref: str | None) -> dict[str, str]:
    out = {"data-kind": kind}
    if net:
        out["data-net"] = net
    if ref:
        out["data-ref"] = ref
    return out


def _tagged_shapes(src: ET.Element, tags: list[_Tag]) -> list[ET.Element]:
    """schemdraw's shapes with their roles. Plain stroked paths of one role (kind, net, part) merge into one path;
    filled or otherwise styled shapes, circles and polygons stay separate."""
    merged: dict[tuple, list[str]] = {}
    single: list[tuple[tuple, ET.Element]] = []
    order: dict[tuple, int] = {}

    def slot(key: tuple) -> tuple:
        order.setdefault(key, len(order))
        return key

    for el in src.iter():
        tag = el.tag.split("}")[-1]
        if el is src or tag not in _GEOMETRY:
            continue
        st = _style(el)
        ink = st.get("stroke") if _paint(st.get("stroke")) == "currentColor" else st.get("fill")
        m = re.fullmatch(r"#([0-9a-fA-F]{6})", (ink or "").strip())
        idx = int(m.group(1), 16) - 1 if m else -1
        if not 0 <= idx < len(tags):
            raise RuntimeError(f"schemdraw shape without a role: {tag} {ink!r}")
        t = tags[idx]
        shape = _copy_shape(el, tag, ink)
        plain = tag == "path" and set(shape.attrib) == {"d"}
        if t.kind == "body" and t.terminals and tag == "path":
            body_d, leads = _split_leads(shape.get("d", ""), t.terminals)
            for net, lead in leads:
                merged.setdefault(slot(("wire", net, None)), []).append(lead)
            if not body_d:
                continue
            shape.set("d", body_d)
        if plain:
            merged.setdefault(slot((t.kind, t.net, t.ref)), []).append(shape.get("d", ""))
        else:
            key = slot((t.kind, t.net, t.ref, "single", len(single)))
            single.append((key, shape))
    out: list[tuple[int, int, ET.Element]] = []
    for key, ds in merged.items():
        el = ET.Element("path", {"d": _compact_d(ds), **_role_attrs(*key[:3])})
        out.append((_KIND_ORDER[key[0]], order[key], el))
    for key, shape in single:
        for k, v in _role_attrs(*key[:3]).items():
            shape.set(k, v)
        out.append((_KIND_ORDER[key[0]], order[key], shape))
    return [el for _k, _o, el in sorted(out, key=lambda x: (x[0], x[1]))]


def text_width(text: str, size: float) -> float:
    """Estimated monospace width: 0.6 em per character, wide (East Asian) characters count twice."""
    cells = sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in text)
    return CHAR_EM * size * cells


def _label_box(lb: _Label) -> tuple[float, float, float, float]:
    """Estimated box in SVG units (y down): ``text_width`` by one line box (``LINE_EM`` x font size)."""
    x, y = lb.x * UNIT, -lb.y * UNIT
    w, h = text_width(lb.text, lb.size), LINE_EM * lb.size
    x0 = {"left": x, "center": x - w / 2, "right": x - w}[lb.halign]
    y0 = {"bottom": y - h, "center": y - h / 2, "top": y}[lb.valign]
    return x0, y0, x0 + w, y0 + h


def text_boxes(svg: str) -> list[tuple[str, float, float, float, float]]:
    """(text, x0, y0, x1, y1) for every <text> of a rendered SVG, estimated like ``_label_box``."""
    out = []
    for t in ET.fromstring(svg).iter(f"{{{SVG_NS}}}text"):  # noqa: S314 - our own SVG
        s = "".join(t.itertext())
        size = float(t.get("font-size") or FONT_SIZE)
        x, y = float(t.get("x") or 0), float(t.get("y") or 0)
        w, h = text_width(s, size), LINE_EM * size
        x0 = {"start": x, "middle": x - w / 2, "end": x - w}[t.get("text-anchor") or "start"]
        out.append((s, x0, y - h / 2, x0 + w, y + h / 2))
    return out


def _shapes(root: ET.Element) -> tuple[list[tuple[float, float, float, float]], list[tuple[float, float, float]]]:
    """Ink of the drawing: line segments of paths and polygons, and circles (cx, cy, r); hit areas excluded."""
    segs: list[tuple[float, float, float, float]] = []
    circles: list[tuple[float, float, float]] = []
    for el in root.iter():
        tag = el.tag.split("}")[-1]
        if tag == "path":
            pts: list[tuple[float, float]] = []
            start = None
            for cmd, nums in re.findall(r"([MLZ])([^MLZ]*)", el.get("d", "")):
                vals = [float(v) for v in _NUM.findall(nums)]
                if cmd == "Z":
                    if pts and start:
                        segs.append((*pts[-1], *start))
                    continue
                for i in range(0, len(vals) - 1, 2):
                    pt = (vals[i], vals[i + 1])
                    if cmd == "M" and i == 0:
                        start = pt
                    elif pts:
                        segs.append((*pts[-1], *pt))
                    pts.append(pt)
        elif tag in ("polygon", "polyline"):
            vals = [float(v) for v in _NUM.findall(el.get("points", ""))]
            pts = list(zip(vals[0::2], vals[1::2], strict=False))
            if tag == "polygon" and pts:
                pts.append(pts[0])
            segs += [(*a, *b) for a, b in zip(pts, pts[1:], strict=False)]
        elif tag == "circle":
            circles.append((float(el.get("cx", 0)), float(el.get("cy", 0)), float(el.get("r", 0))))
    return segs, circles


def _boxes_overlap(a, b) -> bool:
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


def _segment_hits_box(seg, box) -> bool:
    """Liang-Barsky clip of a segment against an axis-aligned box (open interior)."""
    x0, y0, x1, y1 = seg
    bx0, by0, bx1, by1 = box
    dx, dy = x1 - x0, y1 - y0
    t0, t1 = 0.0, 1.0
    for pp, q in ((-dx, x0 - bx0), (dx, bx1 - x0), (-dy, y0 - by0), (dy, by1 - y0)):
        if pp == 0:
            if q <= 0:
                return False
            continue
        r = q / pp
        if pp < 0:
            t0 = max(t0, r)
        else:
            t1 = min(t1, r)
        if t0 >= t1:
            return False
    return True


def _point_box(px: float, py: float, box) -> float:
    return math.hypot(max(box[0] - px, 0.0, px - box[2]), max(box[1] - py, 0.0, py - box[3]))


def _point_segment(px: float, py: float, seg) -> float:
    x0, y0, x1, y1 = seg
    dx, dy = x1 - x0, y1 - y0
    ll = dx * dx + dy * dy
    t = 0.0 if ll == 0 else max(0.0, min(1.0, ((px - x0) * dx + (py - y0) * dy) / ll))
    return math.hypot(px - (x0 + t * dx), py - (y0 + t * dy))


def _segment_box(seg, box) -> float:
    """Distance between a segment and a box (0 when the segment enters the box). For disjoint convex shapes the
    minimum lies at an end point of the segment or a corner of the box."""
    if _segment_hits_box(seg, box):
        return 0.0
    corners = ((box[0], box[1]), (box[2], box[1]), (box[2], box[3]), (box[0], box[3]))
    return min(_point_box(seg[0], seg[1], box), _point_box(seg[2], seg[3], box),
               *(_point_segment(cx, cy, seg) for cx, cy in corners))


def label_clearances(svg: str) -> list[tuple[str, float]]:
    """(text, px) for every label: the gap between its estimated box and the stroke edge of the nearest line or
    circle (circles count as discs). Negative or 0 means the label touches the drawing."""
    root = ET.fromstring(svg)  # noqa: S314 - our own SVG
    segs, circles = _shapes(root)
    out = []
    for text, *box in text_boxes(svg):
        near = [_segment_box(s, box) for s in segs] + [_point_box(cx, cy, box) - r for cx, cy, r in circles]
        out.append((text, round(min(near, default=math.inf) - LINE_WIDTH / 2, 2)))
    return out


def label_problems(svg: str) -> tuple[list[str], list[str]]:
    """(label pairs that overlap, labels closer than ``MIN_CLEAR`` px to a line), from the estimated text boxes."""
    boxes = text_boxes(svg)
    overlaps = [f"{a[0]!r} / {b[0]!r}" for i, a in enumerate(boxes) for b in boxes[i + 1:] if _boxes_overlap(a[1:], b[1:])]
    close = [f"{text!r} {max(gap, 0.0):.1f} px" for text, gap in label_clearances(svg) if gap < MIN_CLEAR]
    return overlaps, close


def _ink_bounds(root: ET.Element) -> tuple[float, float, float, float]:
    """Bounding box of the strokes: the geometry plus half the line width (circles: radius plus half the width)."""
    segs, circles = _shapes(root)
    half = LINE_WIDTH / 2
    xs = [v for s in segs for v in (s[0], s[2])]
    ys = [v for s in segs for v in (s[1], s[3])]
    return (min([*(v - half for v in xs), *(cx - r - half for cx, _cy, r in circles)]),
            min([*(v - half for v in ys), *(cy - r - half for _cx, cy, r in circles)]),
            max([*(v + half for v in xs), *(cx + r + half for cx, _cy, r in circles)]),
            max([*(v + half for v in ys), *(cy + r + half for _cx, cy, r in circles)]))


def _finish(raw: bytes, sheet: _Sheet, aria: str) -> str:
    src = ET.fromstring(raw)  # noqa: S314 - schemdraw output, not user input
    root = ET.Element("svg", {
        "xmlns": SVG_NS, "viewBox": "", "preserveAspectRatio": "xMidYMid meet", "role": "img", "aria-label": aria,
        "fill": "none", "stroke": "currentColor", "stroke-width": _n(LINE_WIDTH), "stroke-linecap": "round",
        "stroke-linejoin": "round", "font-family": FONT,
    })
    for el in src.iter():
        tag = el.tag.split("}")[-1]
        if el is src or tag in ("defs", "clipPath", "style", "title", "g") or tag in _GEOMETRY:
            continue
        if tag in ("text", "tspan"):
            raise RuntimeError("unexpected schemdraw text")
        if el.tag.startswith(f"{{{SVG_NS}}}") or "}" not in el.tag:
            raise RuntimeError(f"unexpected SVG element {tag!r} from schemdraw")
    root.extend(_tagged_shapes(src, sheet.tags))
    x0, y0, x1, y1 = _ink_bounds(root)  # geometry only: the hit areas below do not count for the viewBox
    # hit areas first, below the ink: the pointer finds a wire or port of a net on top, the part around it
    for i, (ref, elements) in enumerate(sheet.hits):
        bx = [el.get_bbox(transform=True, includetext=False) for el in elements]
        hx0, hx1 = min(b.xmin for b in bx) - 0.1, max(b.xmax for b in bx) + 0.1
        hy0, hy1 = min(b.ymin for b in bx) - 0.1, max(b.ymax for b in bx) + 0.1
        root.insert(i, ET.Element("rect", {"data-kind": "body", "data-ref": ref, "x": _n(hx0 * UNIT),
                                           "y": _n(-hy1 * UNIT), "width": _n((hx1 - hx0) * UNIT),
                                           "height": _n((hy1 - hy0) * UNIT), "fill": "none", "stroke": "none",
                                           "pointer-events": "all"}))
    for lb in sheet.labels:
        bx0, by0, bx1, by1 = _label_box(lb)
        x0, y0, x1, y1 = min(x0, bx0), min(y0, by0), max(x1, bx1), max(y1, by1)
        anchor = {"left": "start", "center": "middle", "right": "end"}[lb.halign]
        t = ET.SubElement(root, "text", {
            "x": _n((bx0 + bx1) / 2 if anchor == "middle" else (bx0 if anchor == "start" else bx1)),
            "y": _n((by0 + by1) / 2), "dominant-baseline": "central",
            **({} if anchor == "start" else {"text-anchor": anchor}),  # start is the SVG default (bytes)
            "font-family": FONT, "font-size": _n(lb.size), "fill": "currentColor", "stroke": "none", **lb.attrs})
        t.text = lb.text
    x0, y0, x1, y1 = math.floor(x0 - PAD), math.floor(y0 - PAD), math.ceil(x1 + PAD), math.ceil(y1 + PAD)
    root.set("viewBox", f"{x0} {y0} {x1 - x0} {y1 - y0}")
    return _serialize(root)


def _xml_escape(text: str, quote: bool) -> str:
    out = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return out.replace("'", "&apos;") if quote else out


def _serialize(root: ET.Element) -> str:
    """The flat SVG (root + shapes + texts) as XML with single-quoted attributes and ``/>`` without a space: the SVG
    travels JSON-encoded in the tool result, where every double quote costs a backslash (size budget)."""
    def one(el: ET.Element) -> str:
        attrs = "".join(f" {k}='{_xml_escape(v, True)}'" for k, v in el.attrib.items())
        inner = (_xml_escape(el.text, False) if el.text else "") + "".join(one(c) for c in el)
        return f"<{el.tag}{attrs}>{inner}</{el.tag}>" if inner else f"<{el.tag}{attrs}/>"
    return one(root)


def _draw(block: str, nl: wiring.Netlist, p: Mapping[str, Any], ends: Mapping[str, wiring.Endpoint],
          aria: str) -> tuple[str, list[str]]:
    import schemdraw  # lazy: plugin dependency, may be missing
    import schemdraw.elements as elm

    d = schemdraw.Drawing(canvas="svg", show=False)
    d.config(unit=3, inches_per_unit=INCHES_PER_UNIT, color="currentColor", lw=LINE_WIDTH, bgcolor="none",
             margin=PAD / UNIT)
    sheet = _Sheet(d, elm, nl)
    DRAW[block](sheet, nl, p, ends)
    raw = d.get_imagedata("svg")
    svg = _finish(raw if isinstance(raw, bytes) else str(raw).encode(), sheet, aria)
    labels = [lb.text for lb in sheet.labels if "data-pin" not in lb.attrs]
    return svg, labels


def _divider_overvoltage(p: Mapping[str, Any], gpio: int, devkit: str | None) -> tuple[dict, dict, list[str]] | None:
    """(check, warning, source ids) when the divider output at full input exceeds the chip's input limit
    (electrical.get v_in_max = VIH max); None at or below the limit or without data."""
    from . import boards, electrical
    chip = "esp32s3"
    if devkit:
        with contextlib.suppress(Exception):  # the drawing must not fail on this note
            chip = boards.load(devkit).get("chip") or chip
    try:
        esp = electrical.get(chip)
    except Exception:  # noqa: BLE001
        esp = None
    limit = None if esp is None else esp.get("v_in_max")
    if not isinstance(limit, int | float):
        return None
    vout = p["v_in"] * p["r2"] / (p["r1"] + p["r2"])
    if vout <= limit + 1e-9:
        return None
    chk = check("schematic.divider_vout", "failed", f"V_out {format_si(vout, 'V')} at GPIO{gpio} > {format_si(limit, 'V')}")
    warn = warning("divider_overvoltage", "danger",
                   f"V_out {format_si(vout, 'V')} at GPIO{gpio} exceeds the ESP input limit {format_si(limit, 'V')} "
                   f"(VIH max) with R1 {format_si(p['r1'], 'Ω')}, R2 {format_si(p['r2'], 'Ω')} and V_in "
                   f"{format_si(p['v_in'], 'V')}. Size the divider with bench_calc divider.", list(esp.get("source_ids") or []))
    return chk, warn, list(esp.get("source_ids") or [])


# --------------------------------------------------------------------------- action

def _safety(block: str, p: Mapping[str, Any]) -> list[dict[str, Any]]:
    out = []
    texts = " ".join(str(v) for v in p.values() if isinstance(v, str))
    if re.search(r"laser", texts, re.IGNORECASE):
        out.append(warning("laser_safety", "danger", "Laser modules can damage eyes. Never look into the beam."))
    if block == "npn_low_side":
        out.append(warning("transistor_pinout", "info",
                           "Q1 B/C/E follow the symbol only. Take the pinout from the transistor datasheet, do not guess."))
    if block == "led":
        out.append(warning("led_polarity", "info", "D1 is polarized: A = anode, K = cathode."))
    if block == "divider":
        out.append(warning("low_voltage_only", "caution",
                           "Low-voltage sources only. Never connect mains voltage to the divider."))
    return out


def _signal_text(board: wiring.Board, ep: wiring.Endpoint) -> str:
    if board.gpio is None:
        return "an unassigned GPIO"
    if board.devkit:
        return f"IO{board.gpio} ({ep.node})"
    return f"GPIO{board.gpio}"


_ROLE = re.compile(r"[A-Z0-9_]{1,24}")  # role names


def _assignment(project: Any, role: Any) -> Mapping[str, Any] | None:
    """The project's assignment for ``role`` (``assignments[]``); None without a role."""
    if project is not None and not isinstance(project, Mapping):
        raise _bad("project must be a bench project object (the project of project.get)")
    if role is None:
        return None
    if not isinstance(role, str) or not _ROLE.fullmatch(role):
        raise _bad(f"role must be a role name such as LASER ([A-Z0-9_]{{1,24}}), got {role!r}")
    if project is None:
        raise _bad("role needs a project (or give gpio and params.net)")
    hit = next((a for a in project.get("assignments") or [] if isinstance(a, Mapping) and a.get("role") == role),
               None)
    if hit is None:
        raise _bad(f"no assignment with role {role} in project {project.get('id')}", "assign it with bench_project first")
    return hit


def _net_from(block: str, params: Any, hit: Mapping[str, Any] | None) -> tuple[Any, str | None]:
    """Without an explicit ``net`` the signal net comes from the assignment: its ``net`` field, else the role
    name. A candidate that is no valid schematic net (or equals the divider's input net) is skipped; then the block
    default stays. Returns (params, reason for the assumption or None)."""
    if hit is None or block not in PARAMS or not isinstance(params, Mapping | None):
        return params, None
    params = dict(params or {})
    if params.get("net") is not None:
        return params, None  # an explicit parameter wins
    table = {q.name: q for q in PARAMS[block]}
    taken = set()
    if "input_net" in table:
        try:
            taken.add(_check_param(block, table["input_net"], params.get("input_net") or table["input_net"].default))
        except BenchError:
            pass  # validate() reports it
    for value, origin in ((hit.get("net"), "net"), (hit.get("role"), "role")):
        if not isinstance(value, str):
            continue
        try:
            net = _check_param(block, table["net"], value)
        except BenchError:
            continue
        if net not in taken:
            where = "net of the assignment" if origin == "net" else "no net in the assignment; the role name"
            return {**params, "net": net}, f"{where} {hit.get('role')} (GPIO{hit.get('pin')})"
    return params, None


def _divider_from_project(project: Any, params: Any) -> tuple[Any, tuple[str, str] | None, list[tuple[str, str, str]]]:
    """A divider whose ADC net has exactly one project resistor to another net (top) and one to GND
    (bottom) takes the project's nets, values and refs where the params leave them open (R1 at VBAT, not "VIN").
    Returns (params, (top ref, bottom ref) or None, assumptions)."""
    if not isinstance(project, Mapping) or not isinstance(params, Mapping) or not isinstance(params.get("net"), str):
        return params, None, []
    net = params["net"].strip()
    top, bottom = [], []
    for part in project.get("parts") or []:
        if not isinstance(part, Mapping) or part.get("kind") != "resistor" or part.get("module"):
            continue
        conn = part.get("conn") if isinstance(part.get("conn"), Mapping) else {}
        ends = [n for n in (_conn_net(project, v) for v in conn.values()) if n]
        if len(ends) != 2 or net not in ends or ends[0] == ends[1]:
            continue
        other = ends[1] if ends[0] == net else ends[0]
        (bottom if other == wiring.GROUND else top).append((part, other))
    if len(top) != 1 or len(bottom) != 1:
        return params, None, []
    (tp, t_net), (bp, _g) = top[0], bottom[0]
    out = dict(params)
    notes: list[tuple[str, str, str]] = []
    for key, value, why in (("input_net", t_net, f"the net of project part {tp.get('ref')} (top of {net})"),
                            ("r1", tp.get("value"), f"value of project part {tp.get('ref')}"),
                            ("r2", bp.get("value"), f"value of project part {bp.get('ref')}")):
        if out.get(key) is None and value is not None:
            out[key] = value
            notes.append((key, str(value), why))
    refs = (str(tp.get("ref")).upper(), str(bp.get("ref")).upper())
    if out.get("r1") != tp.get("value") or out.get("r2") != bp.get("value") or out.get("input_net") != t_net:
        return out, None, notes  # the params differ from the project parts: keep R1/R2 as new parts
    return out, refs, notes


def render(block: str, params: Mapping[str, Any] | None = None, *, devkit: str | None = None,
           gpio: int | str | None = None, project: Mapping[str, Any] | None = None,
           role: str | None = None, part: str | None = None) -> dict[str, Any]:
    """Draw a block and its wiring. Never raises; problems come back as an error envelope.

    With ``project`` (the project object of project.get) and ``role``, the assignment of that role supplies the
    defaults: ``gpio`` (its pin), ``params.net`` (its net, else the role name) and ``devkit`` (the project board).
    Explicit arguments and parameters win.

    Multi-GPIO blocks (``module``, ``level_shifter``) take ``params.gpios``
    {signal or pin name: GPIO}; a single ``gpio`` goes to the first signal pin (channel 1). ``part`` (= params.part,
    a project part such as U1) draws that part's module with its conn, address and facts; the project adds its
    ``options.rails`` and the nets of its assignments."""
    if block in MULTI_BLOCKS or part is not None:
        return _render_multi(block, params, devkit=devkit, gpio=gpio, project=project, role=role, part=part)
    try:
        hit = _assignment(project, role)
        params, net_reason = _net_from(block, params, hit)
        div_refs, div_notes = None, []
        if block == "divider":
            params, div_refs, div_notes = _divider_from_project(project, params)
        p, defaulted = validate(block, params)
        if div_refs:
            p["_refs"] = div_refs
        if gpio is None and hit is not None:
            gpio = hit.get("pin")
        if devkit is None and project is not None:
            devkit = (project.get("board") or {}).get("devkit")
        num = _check_gpio(gpio)
        if devkit is not None and not isinstance(devkit, str):
            raise _bad("devkit must be a board id such as 'esp32-s3-devkitc-1'")
        board = wiring.Board(devkit or None, num)
        types = {q.name: q.type for q in PARAMS[block]}
        values = {k: format_ohms(v) for k, v in p.items() if types.get(k) == "ohm" and v is not None}
        nl = wiring.build(block, p, board, values)
        problems = wiring.check_netlist(nl)
        if problems:
            raise _bad("; ".join(problems), "use distinct net names")
        ends = {"sig": board.signal()}
        for rail in (*wiring.RAILS, wiring.GROUND):
            if any(n == rail for n, _ in nl.nets):
                ends[rail] = board.rail(rail)
        src = sources.resolve(nl.source_ids)
    except BenchError as err:
        return fail(ACTION, err.code, err.message, err.hint)
    except Exception as exc:  # noqa: BLE001 - handlers never raise
        return fail(ACTION, "invalid_args", f"cannot render {block!r}: {exc}")

    table = nl.as_result()
    sig = ends["sig"]
    summary = f"{TITLES[block]} ({p['net']}) on {_signal_text(board, sig)}: {len(nl.parts)} parts, {len(nl.wires)} wires."
    assumptions = [assumption("pin_check", "not checked", "the schematic does not judge the GPIO; run pins.check")]
    if not devkit:
        assumptions.append(assumption("devkit", "none", "no DevKit given; endpoints use chip pin names"))
    if net_reason:
        assumptions.append(assumption("net", p["net"], net_reason))
    for key, value, why in div_notes:
        assumptions.append(assumption(key, value, why))
    used_rule_of_thumb = False
    for name in defaulted:
        q = next(q for q in PARAMS[block] if q.name == name)
        if q.type == "ohm":
            assumptions.append(assumption(name, format_ohms(p[name]),
                                          "default value (rule of thumb), not calculated; size it with bench_calc"))
            used_rule_of_thumb = True
    if used_rule_of_thumb:
        src = [*src, *sources.resolve(["rule-of-thumb"])]
    if block == "divider":
        assumptions.append(assumption("adc_range", "not checked",
                                      f"the drawing does not check {p['net']} against the ADC range; use bench_calc divider"))
    warns = _safety(block, p)
    if hit is not None and num is not None and hit.get("pin") != num:
        warns.append(warning("assignment_pin_differs", "caution",
                             f"GPIO{num} is not the pin of the assignment {hit.get('role')} (GPIO{hit.get('pin')})."))
    if num is None:
        warns.append(warning("gpio_unassigned", "info", "No GPIO given; the drawing shows a placeholder pin."))
    checks = [check("schematic.netlist", "passed", "every part pin is on one net; wires connect each net")]
    if devkit and num is not None:
        checks.append(check("schematic.header_pin", "passed", f"GPIO{num} is {sig.node} on {devkit}"))
    if block == "divider" and num is not None and p.get("v_in") is not None:
        over = _divider_overvoltage(p, num, devkit)
        if over is not None:
            checks.append(over[0])
            warns.append(over[1])
            src = [*src, *[s for s in sources.resolve(over[2]) if s not in src]]
    try:
        svg, labels = _draw(block, nl, p, ends, summary)
    except ImportError:
        return fail(ACTION, "dependency_missing", "schemdraw is not installed; cannot draw the schematic",
                    "install the plugin dependencies: schemdraw>=0.21,<0.24",
                    result={"block": block, "svg": None, **table, "labels": []}, sources=src)
    except Exception as exc:  # noqa: BLE001
        return fail(ACTION, "tool_failed", f"schemdraw failed to draw {block}: {exc}", sources=src)
    overlaps, close = label_problems(svg)
    checks.append(check("schematic.labels_overlap", "failed" if overlaps else "passed",
                        "; ".join(overlaps) if overlaps else "no overlapping labels"))
    checks.append(check("schematic.labels_clear", "failed" if close else "passed",
                        f"closer than {_n(MIN_CLEAR)} px to a line: {', '.join(close)}" if close
                        else f"every label keeps at least {_n(MIN_CLEAR)} px from the lines"))
    result = {"block": block, "svg": svg, **table, "labels": labels}
    return envelope(ACTION, summary, result, checks=checks, warnings=warns, assumptions=assumptions, sources=src)

# --------------------------------------------------------------------------- multi-GPIO action

LEVEL_SOURCE = "mod-level-an10441"  # NXP/Nexperia AN10441 (data/sources/mod-level.json)
MODULE_DEFAULT = "bme280"  # params.module default (the pilot module of the catalog)
_SIGNAL_ALIAS = {"SDA": "i2c_sda", "SCL": "i2c_scl", "SCLK": "spi_sck", "MOSI": "spi_sdi", "SDI": "spi_sdi",
                 "MISO": "spi_sdo", "SDO": "spi_sdo", "CS": "spi_cs", "SS": "spi_cs", "TX": "uart_tx",
                 "RX": "uart_rx", "TXD": "uart_tx", "RXD": "uart_rx"}
_CHANNEL = re.compile(r"(?:LV|CH)?([1-9])", re.IGNORECASE)


def _project_rails(project: Mapping[str, Any] | None) -> dict[str, float]:
    """options.rails of a project (written by bench_project set_rails, already checked there)."""
    out: dict[str, float] = {}
    rails = ((project or {}).get("options") or {}).get("rails")
    if isinstance(rails, Mapping):
        for net, v in rails.items():
            if (isinstance(net, str) and net not in modspec.FIXED_RAILS and isinstance(v, int | float)
                    and not isinstance(v, bool) and 0 < v <= MAX_VOLTS):
                out[net] = float(v)
    return out


def _pin_nets(project: Mapping[str, Any] | None) -> dict[int, str]:
    """GPIO -> net of the project's assignments that name a net (the first wins, as in modcheck)."""
    out: dict[int, str] = {}
    for a in (project or {}).get("assignments") or []:
        if isinstance(a, Mapping) and isinstance(a.get("pin"), int) and isinstance(a.get("net"), str) \
                and a["net"].strip():
            out.setdefault(a["pin"], a["net"].strip())
    return out


def _role_nets(project: Mapping[str, Any] | None) -> dict[str, str]:
    """Role -> net of its assignment (``net``, else ``GPIO<pin>``): a module conn value that names a role sits on
    that net, the same convention as modcheck (drawing and check agree)."""
    items = [a for a in (project or {}).get("assignments") or [] if isinstance(a, Mapping)
             and isinstance(a.get("pin"), int)]
    nets = {a["net"].strip() for a in items if isinstance(a.get("net"), str) and a["net"].strip()}
    out: dict[str, str] = {}
    for a in items:
        role = a.get("role")
        if isinstance(role, str) and role.strip() and role.strip() not in nets:
            net = a["net"].strip() if isinstance(a.get("net"), str) and a["net"].strip() else f"GPIO{a['pin']}"
            out.setdefault(role.strip(), net)
    return out


def _pin_modes(project: Mapping[str, Any] | None) -> dict[int, str]:
    """GPIO -> assignment mode (out, spi_sck, …) of the project; the first assignment of a GPIO wins."""
    out: dict[int, str] = {}
    for a in (project or {}).get("assignments") or []:
        if isinstance(a, Mapping) and isinstance(a.get("pin"), int) and isinstance(a.get("mode"), str):
            out.setdefault(a["pin"], a["mode"])
    return out


def _driven(project: Mapping[str, Any] | None, ref: str) -> dict[str, tuple[str, bool]]:
    """Net -> (driver "U1.1Y", push-pull) of the module outputs of the project's other module parts (their conn):
    an input of the drawn module on such a net is fed by that output, not by a GPIO."""
    from . import modules
    out: dict[str, tuple[str, bool]] = {}
    pin_net = _pin_nets(project)
    for part in (project or {}).get("parts") or []:
        if not isinstance(part, Mapping) or not isinstance(part.get("module"), str):
            continue
        pref = str(part.get("ref") or "").upper()
        conn = part.get("conn") if isinstance(part.get("conn"), Mapping) else {}
        if pref == ref.upper() or not conn:
            continue
        try:
            entry = modules.catalog().get(part["module"], part.get("variant") if isinstance(part.get("variant"), str)
                                          else None)
        except Exception:  # noqa: BLE001 - an unknown module drives nothing here; pins.check reports it
            entry = {}
        for q in entry.get("pins") or []:
            if not isinstance(q, Mapping) or q.get("signal") not in wiring.OUT_SIGNALS:
                continue
            raw = conn.get(q.get("name"))
            if not isinstance(raw, str) or not raw.strip():
                continue
            net = raw.strip()
            if m := re.fullmatch(r"GPIO(\d{1,3})", net):
                net = pin_net.get(int(m.group(1)), net)
            if net in (*wiring.RAILS, wiring.GROUND):
                continue
            push = wiring.push_pull(q, entry.get("io"))
            if net not in out or (push and not out[net][1]):
                out[net] = (f"{pref}.{q['name']}", push)
    return out


def _pullup_values(project: Mapping[str, Any] | None, rails: Mapping[str, float]) -> dict[str, tuple[str, str]]:
    """Values for pull-ups the module data leaves open: {net: (value, why)} from the project's resistors between that
    net and a supply, and {wiring.I2C_CALC_KEY: (value, why)} from the latest stored i2c_pullup calculation."""
    out: dict[str, tuple[str, str]] = {}
    supplies = {*wiring.RAILS, *rails}
    for part in (project or {}).get("parts") or []:
        if not isinstance(part, Mapping) or part.get("kind") != "resistor" or part.get("module"):
            continue
        conn = part.get("conn") if isinstance(part.get("conn"), Mapping) else {}
        ends = [v.strip() for v in conn.values() if isinstance(v, str) and v.strip()]
        val = wiring.ohms_text(part.get("value"))
        if len(ends) != 2 or val is None:
            continue
        for net, other in ((ends[0], ends[1]), (ends[1], ends[0])):
            if other in supplies and net not in supplies and net != wiring.GROUND:
                why = f"value of the project part {part.get('ref')} ({part.get('value')}) on {net}"
                out.setdefault(net, (val, why))
    calcs = [c for c in (project or {}).get("calcs") or [] if isinstance(c, Mapping) and c.get("type") == "i2c_pullup"]
    if calcs:
        c = calcs[-1]
        res = c.get("result") if isinstance(c.get("result"), Mapping) else {}
        given = ((res.get("inputs") or {}).get("r_pullup") or {}) if isinstance(res.get("inputs"), Mapping) else {}
        pick = given if isinstance(given, Mapping) and given.get("value") else res.get("suggested")
        if isinstance(pick, Mapping) and isinstance(pick.get("value"), int | float) and pick["value"] > 0:
            how = "r_pullup" if pick is given else "suggested value"
            out[wiring.I2C_CALC_KEY] = (wiring.fmt_si(float(pick["value"]), "Ω"),
                                        f"{how} of the stored calculation {c.get('id')} (bench_calc i2c_pullup)")
    return out


def _conn_net(project: Mapping[str, Any] | None, raw: Any) -> str | None:
    """The net a conn value names: ``GPIO<n>`` = the project net of that GPIO, a role = its assignment's net."""
    if not isinstance(raw, str) or not raw.strip():
        return None
    net = raw.strip()
    if m := re.fullmatch(r"GPIO(\d{1,3})", net):
        return _pin_nets(project).get(int(m.group(1)), net)
    return _role_nets(project).get(net, net)


def _module_parts(project: Mapping[str, Any] | None) -> list[Mapping[str, Any]]:
    return [q for q in (project or {}).get("parts") or [] if isinstance(q, Mapping)
            and isinstance(q.get("module"), str) and q["module"].strip() and isinstance(q.get("ref"), str)]


def _entry_of(part: Mapping[str, Any]) -> Mapping[str, Any]:
    from . import modules
    try:
        return modules.catalog().get(part["module"], part.get("variant") if isinstance(part.get("variant"), str)
                                     else None)
    except Exception:  # noqa: BLE001 - an unknown module adds nothing here; pins.check reports it
        return {}


def _has_board_pullups(facts: Any) -> bool:
    facts = facts if isinstance(facts, Mapping) else {}
    return facts.get("pullups") not in (None, "none", "unknown") or "pullups" in (facts.get("onboard") or [])


def _bus_pullups(project: Mapping[str, Any] | None, ref: str, rails: Mapping[str, float]) -> dict[str, str]:
    """Nets whose pull-ups already exist elsewhere in the project (one set per bus): {net: why}.
    - a project resistor between the net and a supply (rails, options.rails);
    - another module part on the net with pull-ups on its board (facts.pullups value or facts.onboard, user);
    - another module part on the net that needs pull-ups and whose schematic is stored before this part's one
      (circuits[] order): that schematic draws them."""
    out: dict[str, str] = {}
    if project is None:
        return out
    supplies = {*wiring.RAILS, *rails}
    for part in project.get("parts") or []:
        if not isinstance(part, Mapping) or part.get("kind") != "resistor" or part.get("module"):
            continue
        conn = part.get("conn") if isinstance(part.get("conn"), Mapping) else {}
        ends = [n for n in (_conn_net(project, v) for v in conn.values()) if n]
        if len(ends) != 2:
            continue
        for net, other in ((ends[0], ends[1]), (ends[1], ends[0])):
            if other in supplies and net not in supplies and net != wiring.GROUND:
                out.setdefault(net, f"project part {part.get('ref')} ({part.get('value')}) pulls {net} up to {other}")
    stored = [str((c.get("params") or {}).get("part") or "").upper() for c in project.get("circuits") or []
              if isinstance(c, Mapping) and c.get("block") == "module" and isinstance(c.get("params"), Mapping)]
    mine = stored.index(ref.upper()) if ref.upper() in stored else len(stored)
    for part in _module_parts(project):
        pref = part["ref"].strip().upper()
        if pref == ref.upper():
            continue
        conn = part.get("conn") if isinstance(part.get("conn"), Mapping) else {}
        entry = _entry_of(part)
        need = [pin for req in entry.get("requires") or [] if isinstance(req, Mapping) and req.get("code") == "pullup"
                for pin in req.get("pins") or []]
        nets = [n for n in (_conn_net(project, conn.get(pin)) for pin in need) if n and n not in supplies
                and n != wiring.GROUND]
        if _has_board_pullups(part.get("facts")):
            for net in nets:
                out.setdefault(net, f"on the board of {pref} (facts, user-confirmed)")
        elif pref in stored and stored.index(pref) < mine:
            for net in nets:
                out.setdefault(net, f"drawn in the schematic of {pref}")
    return out


def _ref_maker(project: Mapping[str, Any] | None, ref: str) -> tuple[Any, list[str], int | None]:
    """new_ref for the drawn parts of module part ``ref``: never a project part's ref; with two or more module parts
    numbered per sheet (U2 = the 2nd module part -> R201, C201, …), so the schematics of a project do not collide.
    Returns (new_ref, the list it fills, sheet number or None)."""
    taken = {str(q.get("ref") or "").strip().upper() for q in (project or {}).get("parts") or []
             if isinstance(q, Mapping)}
    mods = [q["ref"].strip().upper() for q in _module_parts(project)]
    sheet = mods.index(ref.upper()) + 1 if len(mods) > 1 and ref.upper() in mods else None
    counters: dict[str, int] = {}
    made: list[str] = []

    def new_ref(prefix: str) -> str:
        while True:
            counters[prefix] = counters.get(prefix, 0) + 1
            n = counters[prefix] + (sheet * 100 if sheet else 0)
            cand = f"{prefix}{n}"
            if cand not in taken:
                made.append(cand)
                return cand

    return new_ref, made, sheet


_CELL = re.compile(r"CR\d{4}|coin[ -]?cell|backup cell|battery holder|cell holder", re.IGNORECASE)


def _variant_board_pins(entry: Mapping[str, Any], mid: str, variant: str | None) -> dict[str, str]:
    """Pins a breakout variant wires on its own board: a variant that turns a bare chip (kind ic) into a
    board (kind module) but keeps the chip's pins carries the chip's ``tie`` on supply, ground and battery pins on
    that board (ZS-042: VBAT at the CR2032 holder, not at GND). Variants with their own ``pins`` decide themselves."""
    from . import modules
    if not variant or entry.get("kind") != "module":
        return {}
    try:
        base = modules.catalog().get(mid)
    except Exception:  # noqa: BLE001
        return {}
    if base.get("kind") == "module" or base.get("pins") != entry.get("pins"):
        return {}
    title = str(next((v.get("title") for v in base.get("variants") or [] if isinstance(v, Mapping)
                      and v.get("id") == variant), "") or "")
    cell = bool(_CELL.search(title))
    out: dict[str, str] = {}
    for q in entry.get("pins") or []:
        if not isinstance(q, Mapping) or not isinstance(q.get("tie"), str):
            continue
        if q.get("signal") in ("supply", "gnd", "power_out"):
            what = " (its coin-cell holder)" if cell and re.search(r"BAT", q["name"], re.IGNORECASE) else ""
            out[q["name"]] = (f"variant {variant} is a board{what}: the bare-chip tie {q['name']} to {q['tie']} is "
                              "made on the board, not drawn")
    return out


def _module_gpios(entry: Mapping[str, Any], gpios: Mapping[str, int]) -> dict[str, int]:
    """params.gpios keys -> module pin names: a pin name, a signal (i2c_sda) or its short name (SDA, MOSI, TX)."""
    pins = [q for q in entry.get("pins") or [] if isinstance(q, Mapping) and q.get("signal") != "nc"]
    names = {q["name"].upper(): q["name"] for q in pins}
    hint = f"pins of {entry['id']}: {', '.join(q['name'] for q in pins)}"
    out: dict[str, int] = {}
    for key, num in gpios.items():
        pin = names.get(key.upper())
        if pin is None:
            sig = key.lower() if key.lower() in modspec.SIGNALS else _SIGNAL_ALIAS.get(key.upper())
            hits = [q["name"] for q in pins if sig and q.get("signal") == sig]
            if len(hits) != 1:
                why = "is on several pins" if hits else "is no pin or signal"
                raise _bad(f"gpios.{key} {why} of {entry['id']}", hint)
            pin = hits[0]
        sig = next(q.get("signal") for q in pins if q["name"] == pin)
        if sig in ("supply", "gnd", "power_out"):
            raise _bad(f"gpios.{key}: {pin} is a supply pin, not a signal", hint)
        if pin in out and out[pin] != num:
            raise _bad(f"gpios: {pin} is given twice", hint)
        out[pin] = num
    return out


def _part_of(project: Mapping[str, Any] | None, ref: str) -> Mapping[str, Any]:
    if project is None:
        raise _bad("part needs a project", "give project (the project id in the tool) or params.module")
    ref = ref.upper()
    parts = [q for q in project.get("parts") or [] if isinstance(q, Mapping)]
    hit = next((q for q in parts if str(q.get("ref", "")).upper() == ref), None)
    if hit is None:
        raise _bad(f"no part {ref} in project {project.get('id')}",
                   f"parts: {', '.join(str(q.get('ref')) for q in parts) or 'none'}")
    if not isinstance(hit.get("module"), str) or not hit["module"].strip():
        raise _bad(f"{ref} is no module part", "add modules with bench_project action=add_module")
    return hit


def _module_plan(p: Mapping[str, Any], defaulted: list[str], devkit: str | None, num: int | None,
                 project: Mapping[str, Any] | None, rails: Mapping[str, float]
                 ) -> tuple[wiring.ModulePlan, dict[str, Any], list[dict[str, Any]]]:
    from . import modules
    ref, conn, address, facts, value = "U1", {}, p["address"], {}, None
    mid, variant = p["module"], p["variant"]
    extra: list[dict[str, Any]] = []
    if p["part"] is not None:
        part = _part_of(project, p["part"])
        ref, value = str(part["ref"]).upper(), part.get("value")
        if "module" not in defaulted and modules.catalog().resolve_id(mid) != modules.catalog().resolve_id(
                part["module"]):
            raise _bad(f"params.module {mid} is not the module of {ref} ({part['module']})",
                       "leave params.module out with part")
        mid = part["module"]
        variant = variant or (part.get("variant") if isinstance(part.get("variant"), str) else None)
        conn = {k: v for k, v in (part.get("conn") or {}).items() if isinstance(k, str) and isinstance(v, str)}
        address = address or (part.get("address") if isinstance(part.get("address"), str) else None)
        facts = dict(part.get("facts") or {})
    elif "module" in defaulted:
        extra.append(assumption("module", mid, "no module and no part given; the pilot module of the catalog"))
    entry = modules.catalog().get(mid, variant)
    conn.update(p["conn"] or {})
    roles = _role_nets(project)
    conn = {k: roles.get(v.strip(), v) if isinstance(v, str) else v for k, v in conn.items()}
    gpios = _module_gpios(entry, p["gpios"] or {})
    if num is not None:
        if gpios and num not in gpios.values():
            raise _bad(f"gpio {num} is not in params.gpios", "give the GPIOs in params.gpios only")
        on_pin = _pin_nets(project).get(num)
        wired = {v.strip() for v in conn.values() if isinstance(v, str)}
        if not gpios and (f"GPIO{num}" in wired or (on_pin is not None and on_pin in wired)):
            extra.append(assumption("gpio", f"GPIO{num}", f"the part's conn already puts {on_pin or f'GPIO{num}'} "
                                    "on its pin; no other pin is added"))
        elif not gpios:  # never a module output, never a pin the part's conn or a tie already wires
            first = next((q["name"] for q in entry.get("pins") or [] if isinstance(q, Mapping)
                          and q.get("signal") in wiring.ESP_SIGNALS and q.get("signal") not in wiring.OUT_SIGNALS
                          and q["name"] not in conn and not isinstance(q.get("tie"), str)), None)
            if first is None:
                raise _bad(f"{entry['id']} has no free input pin for gpio {num}",
                           f"name the pin in params.gpios, e.g. {{\"<pin>\": {num}}}, or connect it in the part's conn")
            gpios = {first: num}
    r_pullup = p["r_pullup"]
    new_ref, made, sheet = _ref_maker(project, ref)
    plan = wiring.module_plan(entry, devkit=devkit, ref=ref, value=value, conn=conn, gpios=gpios, address=address,
                              facts=facts, rails=rails, pin_net=_pin_nets(project), r_pullup=r_pullup,
                              driven=_driven(project, ref), pin_mode=_pin_modes(project),
                              pullup_values=_pullup_values(project, rails),
                              pullups_present=_bus_pullups(project, ref, rails),
                              board_pins=_variant_board_pins(entry, mid, variant), new_ref=new_ref)
    if project is not None and made:
        how = f"numbered for sheet {sheet} ({ref} = module part {sheet})" if sheet else "numbered"
        extra.append(assumption("refs", ", ".join(made), f"proposed refs of the drawn parts, {how} so they do not "
                                "collide with the project parts or the other module schematics; not yet project "
                                "parts (add them with bench_project to keep them)"))
    return plan, entry, extra


def _channel_names(gpios: Mapping[str, int], channels: int, fixed: bool) -> tuple[int, dict[int, int],
                                                                                   dict[int, str]]:
    """level_shifter params.gpios -> (channels, {channel: GPIO}, {channel: signal name})."""
    by_ch: dict[int, int] = {}
    names: dict[int, str] = {}
    named: list[tuple[str, int]] = []
    seen: set[int] = set()
    for key, num in gpios.items():
        if num in seen:
            raise _bad(f"GPIO{num} is given for two channels", "one GPIO per channel")
        seen.add(num)
        m = _CHANNEL.fullmatch(key)
        if m:
            by_ch[int(m.group(1))] = num
        else:
            net = key.upper()
            if not _NET.fullmatch(net) or net in RESERVED_NETS:
                raise _bad(f"gpios.{key}: a channel name like SDA, SCL or LV1 (A-Z, 0-9, _; max. 24)")
            named.append((net, num))
    free = [n for n in range(1, 5) if n not in by_ch]
    for net, num in named:
        if not free:
            break
        n = free.pop(0)
        by_ch[n], names[n] = num, net
    need = max([*by_ch, 0])
    if len(by_ch) < len(gpios) or need > 4:
        raise _bad("a level_shifter block has at most 4 channels", "split larger buses into two blocks")
    if need > channels:
        if fixed:
            raise _bad(f"params.gpios names channel {need}, but channels is {channels}")
        channels = need
    return channels, by_ch, names


def _multi_checks(svg: str, checks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    overlaps, close = label_problems(svg)
    checks.append(check("schematic.labels_overlap", "failed" if overlaps else "passed",
                        "; ".join(overlaps) if overlaps else "no overlapping labels"))
    checks.append(check("schematic.labels_clear", "failed" if close else "passed",
                        f"closer than {_n(MIN_CLEAR)} px to a line: {', '.join(close)}" if close
                        else f"every label keeps at least {_n(MIN_CLEAR)} px from the lines"))
    return checks


def _capped(severity: str, cls: str | None) -> str:
    cap = modspec.CLASS_MAX_SEVERITY.get(cls or "A", "danger")
    rank = modspec.SEVERITY_RANK
    return severity if rank[severity] <= rank[cap] else cap


def _gpio_text(board: wiring.Board, nums: list[int]) -> str:
    if not nums:
        return "unassigned GPIOs"
    return ", ".join(f"IO{n}" if board.devkit else f"GPIO{n}" for n in nums)


def _render_multi(block: str, params: Any, *, devkit: Any, gpio: Any, project: Any, role: Any,
                  part: Any) -> dict[str, Any]:
    try:
        if part is not None:
            if block != "module":
                raise _bad("part is only for block module")
            if not isinstance(params, Mapping | None):
                raise _bad("params must be an object")
            params = {**(params or {}), "part": part}
        hit = _assignment(project, role)
        p, defaulted = validate(block, params)
        if gpio is None and hit is not None:
            gpio = hit.get("pin")
        if devkit is None and project is not None:
            devkit = (project.get("board") or {}).get("devkit")
        num = _check_gpio(gpio)
        if devkit is not None and not isinstance(devkit, str):
            raise _bad("devkit must be a board id such as 'esp32-s3-devkitc-1'")
        devkit = devkit or None
        rails = {**_project_rails(project), **(p["rails"] or {})}
        entry: Mapping[str, Any] | None = None
        assumptions = [assumption("pin_check", "not checked", "the schematic does not judge the GPIOs; run pins.check")]
        if not devkit:
            assumptions.append(assumption("devkit", "none", "no DevKit given; endpoints use chip pin names"))
        warns: list[dict[str, Any]] = []
        shorts: list[str] = []
        if block == "module":
            plan, entry, extra = _module_plan(p, defaulted, devkit, num, project, rails)
            nl, board = plan.netlist, plan.board
            assumptions += extra
            cls = entry.get("_class")
            assumptions += [assumption(k, v, r) for k, v, r in plan.assumptions]
            for code, sev, text, sids in plan.notes:
                warns.append(warning(code, _capped(sev, cls), text[:300], sids))
            nums = [r.gpio for r in plan.rows if r.gpio is not None]
            open_rows = [r.pin for r in plan.rows if r.port == "gpio" and r.gpio is None]
            for net, what, sev in plan.shorts:
                shorts.append(f"{', '.join(what)} on one net ({net})")
                warns.append(warning("net_short", sev, f"{', '.join(what)} on one net ({net}): the drawing connects "
                                     "them, which shorts the signals. Give each signal its own net (bench_project "
                                     "assign net=… per signal, or GPIO<n> in the part's conn).", []))
            if open_rows:
                warns.append(warning("gpio_unassigned", "info", f"No GPIO for {', '.join(open_rows)}; the drawing "
                                     "shows placeholder pins (params.gpios or the part's conn)."))
            ids = [*plan.source_ids]
            for req in entry.get("requires") or []:
                if isinstance(req, Mapping) and isinstance(req.get("source_id"), str):
                    ids.append(req["source_id"])
            iface = "/".join(dict.fromkeys(str(it.get("type")) for it in entry.get("interfaces") or []
                                           if isinstance(it, Mapping))) or entry["id"]
            what = f"{plan.module.ref} {plan.module.value} ({iface})"
        else:
            low_v, high_v = p["low_v"], p["high_v"]
            if low_v > high_v:
                raise _bad(f"low_v {format_volts(low_v)} is above high_v {format_volts(high_v)}",
                           "AN10441: VDD2 (high side) must be equal to or higher than VDD1 (low side)")
            channels, by_ch, names = _channel_names(p["gpios"] or {}, p["channels"], "channels" not in defaulted)
            if num is not None and not by_ch:
                by_ch = {1: num}
            elif num is not None and num not in by_ch.values():
                raise _bad(f"gpio {num} is not in params.gpios", "give the GPIOs in params.gpios only")
            r_value = format_ohms(p["r_pullup"]) if p["r_pullup"] is not None else "R"
            plan = wiring.level_plan(devkit=devkit, channels=channels, low_v=low_v, high_v=high_v, r_value=r_value,
                                     mosfet=p["mosfet"], gpios=by_ch, names=names, rails=rails,
                                     pin_net=_pin_nets(project))
            nl, board = plan.netlist, plan.board
            if p["r_pullup"] is None:
                assumptions.append(assumption("r_pullup", "R", "no value given; size the pull-ups of each side with "
                                              "bench_calc i2c_pullup"))
            assumptions.append(assumption("mosfet", p["mosfet"], "check in the MOSFET datasheet that its gate "
                                          f"threshold lies well below low_v ({format_volts(low_v)})"))
            warns.append(warning("mosfet_pinout", "info", "Q G/D/S follow the symbol only. Take the pinout from the "
                                 "MOSFET datasheet, do not guess."))
            if low_v == high_v:
                warns.append(warning("level_shift_none", "info", "low_v equals high_v: no level shift is needed."))
            nums = [c.gpio for c in plan.channels if c.gpio is not None]
            if len(nums) < len(plan.channels):
                warns.append(warning("gpio_unassigned", "info", "No GPIO for some channels; the drawing shows "
                                     "placeholder pins (params.gpios)."))
            ids = [*nl.source_ids]
            if LEVEL_SOURCE in sources.all_sources():
                ids.insert(0, LEVEL_SOURCE)
            else:  # only while data/sources/mod-level.json is missing: say so, never cite a missing id
                warns.append(warning("source_pending", "caution", f"Unverified: the AN10441 source ({LEVEL_SOURCE}) "
                                     "is not in this build's data; check the channel against NXP AN10441."))
            what = f"{len(plan.channels)} channel{'s' if len(plan.channels) > 1 else ''} {plan.low} to {plan.high}"
        problems = wiring.check_netlist(nl)
        if problems:
            raise _bad("; ".join(problems), "use distinct net names")
        src = sources.resolve(ids)
    except BenchError as err:
        return fail(ACTION, err.code, err.message, err.hint)
    except Exception as exc:  # noqa: BLE001 - handlers never raise
        return fail(ACTION, "invalid_args", f"cannot render {block!r}: {exc}")

    table = nl.as_result()
    summary = (f"{TITLES[block]}: {what} on {_gpio_text(board, nums)}: {len(nl.parts)} parts, "
               f"{len(nl.wires)} wires.")
    checks = [check("schematic.netlist", "failed", "; ".join(shorts)) if shorts else
              check("schematic.netlist", "passed", "every part pin is on one net; wires connect each net")]
    if devkit and nums:
        checks.append(check("schematic.header_pin", "passed", "; ".join(
            f"GPIO{n} is {board.gpio_endpoint(n).node} on {devkit}" for n in dict.fromkeys(nums))))
    try:
        svg, labels = _draw(block, nl, {**p, "_plan": plan}, {}, summary)
    except ImportError:
        return fail(ACTION, "dependency_missing", "schemdraw is not installed; cannot draw the schematic",
                    "install the plugin dependencies: schemdraw>=0.21,<0.24",
                    result={"block": block, "svg": None, **table, "labels": []}, sources=src)
    except Exception as exc:  # noqa: BLE001
        return fail(ACTION, "tool_failed", f"schemdraw failed to draw {block}: {exc}", sources=src)
    result = {"block": block, "svg": svg, **table, "labels": labels}
    return envelope(ACTION, summary, result, checks=_multi_checks(svg, checks), warnings=warns,
                    assumptions=assumptions, sources=src)
