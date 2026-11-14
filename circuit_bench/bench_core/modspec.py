"""Shared vocabulary of the module catalog.

Every closed list a data file, the loader, the check engine, the project model, the tools or the desktop relies on
lives here, so the module families agree without touching each other's files.
"""
from __future__ import annotations

import re

SCHEMA = 1

# --- ids and prefixes ----------------------------------------------------------------------------------------------
MODULE_ID_RE = re.compile(r"^[a-z0-9_]{2,32}$")
WP_RE = re.compile(r"^n?[a-z]{2,12}$")  # data/modules/<family>.json, sources mod-<family>-…, rules mod.<family>.<name>
SOURCE_PREFIX = "mod-"  # data/sources/mod-<family>.json ids start with f"mod-{family}-"
RULE_PREFIX = "mod."  # generic rules mod.<name>, family rules mod.<family>.<name>
WARNING_PREFIX = "mod_"  # warning codes mod_<name> / mod_<family>_<name>
CHECK_PREFIX = "modules."  # check ids modules.<name> (one per rule that ran)

# --- cited number F ------------------------------------------------------------------------------------------------
UNITS: tuple[str, ...] = ("V", "A", "Ω", "F", "Hz", "s", "W", "°C", "K", "%", "bit")
F_KEYS = frozenset({"value", "unit", "page", "evidence", "source_id", "conditions", "rel", "rel_offset", "of"})
# exactly one of value / rel / rel_offset; rel and rel_offset need "of" (a supply pin name of the same module)

# --- entry fields --------------------------------------------------------------------------------------------------
MODULE_KEYS = frozenset({
    "id", "aliases", "title", "category", "manufacturer", "kind", "source_ids", "supplies", "io", "pins",
    "interfaces", "current", "requires", "hazards", "variants", "notes",
    # kind "module" whose own maker documents the whole module (HopeRF RFM95W): the values describe the module
    # itself, so the breakout cap (facts.regulator) does not apply
    "module_datasheet",
})
MODULE_REQUIRED = frozenset({"id", "title", "category", "manufacturer", "kind", "source_ids", "pins"})
FILE_KEYS = frozenset({"schema", "wp", "note", "modules"})
KINDS: tuple[str, ...] = ("ic", "module")  # ic = bare chip; module = breakout board (facts by the user)

CATEGORIES: tuple[str, ...] = (
    "display.oled", "display.lcd", "display.tft", "display.led",
    "led.addressable",
    "logic.level_shifter", "logic.shift_register", "logic.mux",
    "isolation.opto", "switch.relay", "discrete.diode",
    "sensor.environment", "sensor.light", "sensor.gas", "sensor.temperature", "sensor.motion", "sensor.distance",
    "sensor.bio", "sensor.ir", "sensor.hall", "sensor.touch", "sensor.current",
    "adc", "dac", "power.monitor", "power.ldo", "power.buck", "power.charger",
    "rtc", "memory", "io.expander", "io.pwm", "io.i2c_mux",
    "driver.motor", "driver.stepper", "driver.array",
    "audio.amp", "audio.dac", "audio.mic",
    "comm.rs485", "comm.can", "comm.usb_uart", "comm.radio", "comm.rfid", "comm.ethernet", "comm.gnss",
    "comm.cellular", "storage.sd",
)

SUPPLY_KEYS = frozenset({"min", "max", "abs_max", "typ"})  # supplies[<pin name>] -> F per key
IO_KEYS = frozenset({"domain", "domain_v", "vih", "vil", "voh", "vol", "v_in_max", "outputs", "five_v_tolerant"})
# io.domain_v (optional): F with an absolute ``value`` in V (unit "V", page, evidence): the logic pins run on this fixed
# internal voltage (e.g. SIM800L 2.8 V), not on the supply; the level rules use it instead of the supply voltage
IO_ABSOLUTE_V_KEYS = frozenset({"domain_v"})


def domain_v_problems(io: object) -> list[str]:
    """Problems of ``io.domain_v`` (empty when absent or valid): an F with a finite ``value`` in V, 0 < value <=
    MAX_RAIL_V, cited (page + evidence), without rel / rel_offset / of."""
    if not isinstance(io, dict) or "domain_v" not in io:
        return []
    f, where = io["domain_v"], "io.domain_v"
    if not isinstance(f, dict):
        return [f"{where}: expected an F object {{value, unit: 'V', page, evidence}}"]
    out = []
    extra = sorted(set(f) - F_KEYS)
    if extra:
        out.append(f"{where}: unknown keys {extra}")
    if any(k in f for k in ("rel", "rel_offset", "of")):
        out.append(f"{where}: absolute value expected (no rel / rel_offset / of)")
    v = f.get("value")
    if isinstance(v, bool) or not isinstance(v, int | float) or v != v or not 0 < v <= MAX_RAIL_V:
        out.append(f"{where}: value must be a number above 0 V and up to {MAX_RAIL_V:g} V")
    if f.get("unit") != "V":
        out.append(f"{where}: unit must be 'V'")
    if not isinstance(f.get("page"), int) or isinstance(f.get("page"), bool) or not f.get("evidence"):
        out.append(f"{where}: page and evidence are required (a datasheet value)")
    return out


OUTPUT_TYPES: tuple[str, ...] = ("push_pull", "open_drain", "tristate")

# --- pins and signals ----------------------------------------------------------------------------------------------
SIGNALS: tuple[str, ...] = (
    "i2c_sda", "i2c_scl",
    "spi_sck", "spi_cs", "spi_sdi", "spi_sdo",
    "uart_rx", "uart_tx",
    "onewire",
    "i2s_bclk", "i2s_ws", "i2s_din", "i2s_dout",
    "digital_in", "pwm_in", "led_data_in", "reset_in", "enable_in",
    "digital_out", "open_drain_out", "led_data_out",
    "analog_out", "analog_in",
    "addr_select", "mode_select",
    "supply", "gnd", "power_out",
    "nc",
)
PIN_KEYS = frozenset({"name", "signal", "tie", "must_connect", "active_low", "internal_pull", "output", "note"})

# module signal -> ESP assignment modes that may sit on the same net (empty tuple: no ESP pin expected)
SIGNAL_MODES: dict[str, tuple[str, ...]] = {
    "i2c_sda": ("i2c_sda",), "i2c_scl": ("i2c_scl",),
    "spi_sck": ("spi_sck",), "spi_cs": ("spi_cs", "out"),
    "spi_sdi": ("spi_mosi",), "spi_sdo": ("spi_miso",),
    "uart_rx": ("uart_tx",), "uart_tx": ("uart_rx",),
    "onewire": ("out", "in_pullup", "in"),
    "i2s_bclk": ("out",), "i2s_ws": ("out",), "i2s_din": ("out",), "i2s_dout": ("in",),
    # digital inputs may hang on an SPI peripheral (74HC595 latch/clock/data)
    "digital_in": ("out", "pwm", "spi_mosi", "spi_sck", "spi_cs"), "pwm_in": ("pwm", "out"),
    "led_data_in": ("out", "pwm", "spi_mosi"),
    "reset_in": ("out",), "enable_in": ("out",),
    "digital_out": ("in", "in_pullup", "in_pulldown", "spi_miso"), "open_drain_out": ("in", "in_pullup", "in_pulldown"),
    "led_data_out": (), "analog_out": ("adc",), "analog_in": (),
    "addr_select": (), "mode_select": (), "supply": (), "gnd": (), "power_out": (), "nc": (),
}
# which way the logic level goes on a signal net: "in" = the ESP drives the module input, "out" = the module drives
SIGNAL_DIRECTION: dict[str, str] = {
    "i2c_sda": "bidir_od", "i2c_scl": "bidir_od", "onewire": "bidir_od",
    "spi_sck": "in", "spi_cs": "in", "spi_sdi": "in", "spi_sdo": "out",
    "uart_rx": "in", "uart_tx": "out",
    "i2s_bclk": "in", "i2s_ws": "in", "i2s_din": "in", "i2s_dout": "out",
    "digital_in": "in", "pwm_in": "in", "led_data_in": "in", "reset_in": "in", "enable_in": "in",
    "digital_out": "out", "open_drain_out": "out_od", "analog_out": "analog",
}

# --- breakout labels -------------------------------------------------------------------------------------------------
# A breakout board prints common names (SDA, VCC, MOSI ...) where the datasheet names the chip pin (SDI, VDD, DIN ...).
# A label is naming, not a rule: it follows from the pin's cited ``signal`` and counts only when exactly one pin of the
# active variant carries that signal. Left out on purpose: VIN/3V3/5V (on a breakout often the input of a regulator,
# not the chip pin) and RX/TX (named from the other side on module and ESP). power_out pins never match.
# Supply and ground labels only stand in for each other: VCC/VDD or GND/VSS counts only when that one pin is itself
# named VCC/VDD or GND/VSS (any case); on a pin named VIN, VM, VBAT, COIL1, IN- ... it is refused as unknown.
# An I²C or SPI label is ambiguous when any other pin's name starts with it (any case), e.g. CLK next to CLKOUT.
PIN_LABELS: dict[str, tuple[str, ...]] = {
    "i2c_sda": ("SDA",), "i2c_scl": ("SCL",),
    "spi_sck": ("SCK", "SCLK", "CLK"), "spi_sdi": ("MOSI", "SDI", "DIN", "SI"),
    "spi_sdo": ("MISO", "SDO", "DOUT", "SO"), "spi_cs": ("CS", "SS", "NSS", "CSN"),
    "gnd": ("GND", "VSS"), "supply": ("VCC", "VDD"),
}
LABEL_SIGNAL: dict[str, str] = {label: sig for sig, labels in PIN_LABELS.items() for label in labels}
POWER_SIGNALS = frozenset({"gnd", "supply"})  # their labels map only onto a pin named like one of them
LABEL_TEXT: dict[str, str] = {  # what the pin is, for the assumption text
    "i2c_sda": "I²C data pin", "i2c_scl": "I²C clock pin", "spi_sck": "SPI clock pin", "spi_sdi": "SPI data input",
    "spi_sdo": "SPI data output", "spi_cs": "SPI chip select", "gnd": "ground pin", "supply": "supply pin",
}


def _pin_list(pins: object) -> list[dict]:
    return [p for p in pins if isinstance(p, dict) and isinstance(p.get("name"), str)] \
        if isinstance(pins, list | tuple) else []


def resolve_pin(pins: object, name: object) -> dict:
    """The pin a ``conn`` key means, among ``pins`` (the ``pins`` list of a catalog entry with its variant applied).

    ``{"pin", "via", "candidates"}``: via ``name`` (exact pin name), ``case`` (the one pin of that name ignoring case),
    ``label`` (a breakout label of ``PIN_LABELS`` that exactly one pin's signal carries; for a supply or ground label
    that pin must itself be named like one of the row's labels; for a bus label no other pin's name may start with
    it, else that pin and those are the candidates). No match: pin None with the sorted candidates (two or more:
    ambiguous, never guessed; none: unknown)."""
    items = _pin_list(pins)
    none = {"pin": None, "via": None, "candidates": []}
    if not isinstance(name, str) or not name:
        return none
    names = [p["name"] for p in items]
    if name in names:
        return {"pin": name, "via": "name", "candidates": []}
    same = [n for n in names if n.casefold() == name.casefold()]
    if len(same) == 1:
        return {"pin": same[0], "via": "case", "candidates": []}
    if len(same) > 1:
        return {**none, "candidates": sorted(same)}
    sig = LABEL_SIGNAL.get(name.upper())
    if sig is None:
        return none
    fits = [p["name"] for p in items if p.get("signal") == sig]
    if len(fits) == 1:
        if sig in POWER_SIGNALS:
            if fits[0].upper() not in PIN_LABELS[sig]:
                return none  # VCC on VIN, VM, COIL1 ...: not sure which terminal the label means
        else:
            key = name.casefold()
            alike = [n for n in names if n != fits[0] and n.casefold().startswith(key)]
            if alike:  # CLK next to a clock output CLKOUT: the board may print CLK on either pin
                return {**none, "candidates": sorted([fits[0], *alike])}
        return {"pin": fits[0], "via": "label", "candidates": []}
    return {**none, "candidates": sorted(fits)}


def label_table(pins: object) -> dict[str, dict]:
    """Every label of ``PIN_LABELS`` that names a pin (or several) of ``pins``: label -> ``resolve_pin`` answer."""
    out = {}
    for label in LABEL_SIGNAL:
        res = resolve_pin(pins, label)
        if res["pin"] is not None or res["candidates"]:
            out[label] = res
    return out


def pins_hint(pins: object) -> str:
    """'GND, CSB, SDI (SDA), SCK (SCL), SDO, VDDIO, VDD': the pin names, each with the labels that map to it. A pin
    whose own name already is a label of its signal (GND, VDD, CLK ...) gets none."""
    items = _pin_list(pins)
    table = label_table(items)
    out = []
    for p in items:
        own = PIN_LABELS.get(str(p.get("signal")), ())
        labels = [] if p["name"].upper() in own else \
            [lb for lb, res in table.items() if res["via"] == "label" and res["pin"] == p["name"]]
        out.append(f"{p['name']} ({', '.join(labels)})" if labels else p["name"])
    return ", ".join(out)


def alias_text(module_id: str, pin: dict, label: str, via: str) -> str:
    """Reason of the assumption ``pin_alias``: what the pin is and how the catalog names it, plus its note."""
    name = pin.get("name")
    if via == "case":
        text = f"{module_id}: the catalog spells the pin {name}"
    else:
        text = f"{module_id}: {LABEL_TEXT.get(LABEL_SIGNAL.get(label.upper(), ''), 'pin')}, catalog pin {name}"
    note = pin.get("note")
    if isinstance(note, str) and note.strip():
        text += f" ({note.strip()[:120]})"
    return text


INTERFACE_TYPES: tuple[str, ...] = ("i2c", "spi", "uart", "onewire", "i2s", "analog", "digital", "pwm",
                                    "led_serial", "parallel")
INTERFACE_KEYS = frozenset({"type", "addresses", "default", "select", "reserved", "f_max_hz", "mux_channels",
                            "mode", "lsb_first", "baud_default", "note"})
I2C_ADDR_RE = re.compile(r"^0x[0-7][0-9a-f]$")  # 7-bit, lower case

CURRENT_KEYS = frozenset({"supply", "typ", "max", "peak", "sleep", "note"})

REQUIRE_CODES: tuple[str, ...] = ("pullup", "pulldown", "decoupling", "bulk_cap", "termination", "flyback",
                                  "series_resistor", "level_shifter", "regulator", "xshut_per_device")
REQUIRE_KEYS = frozenset({"code", "kind", "value", "pins", "to", "page", "evidence", "source_id", "note"})

HAZARD_CODES: tuple[str, ...] = ("li_ion", "mains", "motor_supply", "heat", "laser", "high_current")
HAZARD_KEYS = frozenset({"code", "text", "page", "evidence", "source_id"})

VARIANT_KEYS = frozenset({"id", "title", "overrides"})
NOTE_KEYS = frozenset({"text", "verified", "page", "evidence", "source_id"})

# --- source classes and severity caps ---------------------------------------------------------------------------------
SOURCE_CLASSES: tuple[str, ...] = ("A", "A1", "A2", "B")
CLASS_MAX_SEVERITY: dict[str, str] = {"A": "danger", "A1": "danger", "A2": "danger", "B": "info"}  # A2 = hard
SEVERITY_RANK: dict[str, int] = {"info": 0, "caution": 1, "danger": 2}

# --- project fields (schema stays 1, everything optional) -------------------------------------------------------------
PART_MODULE_FIELDS: tuple[str, ...] = ("module", "variant", "conn", "address", "facts")
FACT_KEYS: dict[str, tuple[str, ...] | None] = {
    "regulator": ("none", "3V3", "unknown"),
    "pullups": None,  # "none", "unknown" or a resistance text such as "10k"
    "pullups_to": None,  # module pin, net or volts text (e.g. VDD, 3V3, 5V)
    "level_shifter": None,  # bool
    "mains": None,  # bool: the board switches mains voltage (relay contacts) -> always danger, out of scope
    # list: parts the breakout carries (user-confirmed). elec.required_parts and bus.unconnected read it
    "onboard": ("decoupling", "pullups", "reset_rc", "protection"),
    # current in A (number) or text ("2.2A", "350 mA"): the maximum the WHOLE part draws (qty included), measured or
    # confirmed by the user or taken from bench_calc led_strip; mod.power_budget uses it before the catalog values.
    # Stored as a number in A.
    "i_max": None,
}
FIXED_RAILS: dict[str, float] = {"GND": 0.0, "3V3": 3.3, "5V": 5.0}
MAX_RAIL_V = 60.0  # low voltage only (product rule); same limit as calc.LOW_VOLTAGE_MAX_V
MAX_CONN = 48
MODULE_OPS: tuple[str, ...] = ("add_module", "connect", "set_rails")

# --- engine result -------------------------------------------------------------------------------------------------
MAX_FINDINGS_SHOWN = 12

# --- calculators ---------------------------------------------------------------------------------------------------
BASIC_CALCS: tuple[str, ...] = ("led", "npn", "divider", "i2c_pullup", "mosfet", "ldo")  # order fixed (UI, demo)
NEW_CALCS: tuple[str, ...] = ("ina_shunt", "current_sense", "rtd", "ntc", "adc_ext", "current_limit", "led_strip",
                              "opto", "buck", "charger")
CALC_GROUPS: tuple[str, ...] = ("basics", "power", "sensing", "drive", "light")
# calc kind -> module family of bench_core/calcs/<kind>.py
CALC_OWNER: dict[str, str] = {
    "ina_shunt": "powermon", "current_sense": "powermon", "rtd": "thermo", "ntc": "thermo", "adc_ext": "adc",
    "current_limit": "motor", "led_strip": "pixel", "opto": "switch", "buck": "power", "charger": "power",
}

# --- schematic -----------------------------------------------------------------------------------------------------
NEW_BLOCKS: tuple[str, ...] = ("module", "level_shifter")

# --- module families -------------------------------------------------------------------------------------------------
FAMILIES: tuple[str, ...] = ("display", "pixel", "level", "logic", "switch", "env", "ambient", "motion", "prox", "adc",
                             "powermon", "thermo", "rtc", "iox", "motor", "power", "wired", "radio", "net")
