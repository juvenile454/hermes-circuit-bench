"""Tool schemas. Plain JSON Schema: no $ref/$defs, no type arrays, unions only as anyOf.

Every object node carries ``properties`` and ``required`` so Hermes' schema sanitizer leaves the schemas unchanged.
Budgets (ratchets in tests/test_m0_api_schemas.py): description per tool <= 500
characters (Hermes tool_search clips there), all descriptions together <= 2800, ``len(json.dumps(ALL)) <= 10000``.
Stdlib plus registers that are importable at module level: the chips (``bench_core.chips``, JSON only),
the part kinds of the solder rules (``bench_core.bom.kinds()``), the calculators
(``bench_core.calckit.kinds()``) and the module vocabulary (``bench_core.modspec``).
No chip, calculator or interface list is a literal here.
"""
from __future__ import annotations

from typing import Any

from .bench_core import bom, calckit, chips, modspec, schematic

TAIL = " Only report checks listed as passed; cite the returned sources."
TOOLSET = "circuit-bench"
# Same values as bench_core.contracts.MODES (a test keeps them equal); BLOCKS from schematic.BLOCKS (the old four,
# then modspec.NEW_BLOCKS), CALCS from the register.
MODES = ["out", "in", "in_pullup", "in_pulldown", "adc", "pwm", "i2c_sda", "i2c_scl", "spi_sck", "spi_mosi",
         "spi_miso", "spi_cs", "uart_tx", "uart_rx", "touch"]
BLOCKS = list(schematic.BLOCKS)
CALCS = list(calckit.kinds())


def _obj(props: dict[str, Any], required: tuple[str, ...] = (), **extra: Any) -> dict[str, Any]:
    return {"type": "object", "properties": props, "required": list(required), **extra}


def _s(desc: str = "", **extra: Any) -> dict[str, Any]:
    return {"type": "string", **({"description": desc} if desc else {}), **extra}


def _action(values: list[str]) -> dict[str, Any]:
    return {"type": "string", "enum": values}


def _tool(name: str, description: str, props: dict[str, Any]) -> dict[str, Any]:
    return {"name": name, "description": description + TAIL, "parameters": _obj(props, ("action",))}


PROJECT_ACTIONS = ("create", "get", "list", "set_board", "assign", "unassign", "set_firmware", "add_parts",
                   "remove_parts", "note", *modspec.MODULE_OPS, "demo")
PINS_ACTIONS = ("check", "suggest", "info", "modules", "module")
CALC_LIST = "list"

_PIN = {"type": "integer", "description": "GPIO number"}


def _assignments(net: str = "") -> dict[str, Any]:
    return {"type": "array", "items": _obj({"role": _s("e.g. LASER"), "mode": _action(MODES), "pin": _PIN,
                                            "net": _s(net)}, ("role", "mode", "pin"))}


_ASSIGNMENTS = _assignments()
_BOARD = {"chip": _s(chips.ids_text()), "variant": _s("module variant, e.g. n16r8"),
          "devkit": _s("e.g. esp32-s3-devkitc-1"), "wifi": {"type": "boolean"}}
_PROJECT = _s()  # the bench_project id (name says it; saves schema cost)


def _map(desc: str) -> dict[str, Any]:
    return _obj({}, additionalProperties=True, description=desc)

PROJECT = _tool(
    "bench_project",
    "ESP32 bench projects. assign adds/replaces roles; assign, set_board, parts and module actions return checks. "
    "connect edits a part (conn, address, facts, variant, qty); add_parts with conn, or connect ref later. "
    "demo: simulated project (id laser-trigger unless given; an existing one stays unchanged) whose "
    "firmware crashes on purpose; only it is emulated.",
    {"action": _action(list(PROJECT_ACTIONS)),
     "id": _s(), "title": _s(), **_BOARD,
     "variant": _s("ESP variant (create, set_board); add_module: catalog variant"),
     "module": _s("bench_pins modules id"), "ref": _s("e.g. U1"), "conn": _map("pin/label (SDA)->net/role/GPIO<n>; null unlinks"),
     "address": _s("e.g. 0x76"), "facts": _map("bool: level_shifter, mains; pullups none/unknown/4k7; pullups_to "
                                          "pin/net/V; regulator none/3V3/unknown; onboard [decoupling,pullups,"
                                          "reset_rc,protection]; i_max A, whole part incl. qty (measured or "
                                          "bench_calc led_strip); connect merges keys, null drops one"), "rails": _map("net -> V"),
     "rail_limits": _map("net -> A"), "qty": {"type": "integer"},
     "assignments": _assignments("signal net, e.g. I2C_SDA; default: role"), "role": _s(),
     "firmware_dir": _s("absolute PlatformIO folder"), "env": _s("PlatformIO env"),
     "parts": {"type": "array", "items": _obj({"ref": _s("e.g. R1"), "kind": _action(bom.kinds()), "value": _s(),
                                               "package": _s(), "qty": {"type": "integer"},
                                               "conn": _map("pin->net: R/C 1,2; elko/battery +,-; diode A,K")},
                                              ("ref", "kind", "value"))},
     "refs": {"type": "array", "items": _s()},
     "text": _s(), "rev": {"type": "integer"}},
)

PINS = _tool(
    "bench_pins",
    "ESP32 GPIO choices against Espressif rules: check (a project adds its modules), suggest free pins (distinct "
    "picks in allocation), info on one GPIO. modules: search the catalog (q, category, interface); module: one "
    "entry (id, catalog variant). Board and assignments can come "
    "from a project.",
    {"action": _action(list(PINS_ACTIONS)), **_BOARD, "project": _PROJECT, "assignments": _ASSIGNMENTS,
     "requests": {"type": "array", "items": _obj({"role": _s(), "mode": _action(MODES), "pin": _PIN},
                                                 ("role", "mode"))},
     "pin": _PIN, "id": _s(), "q": _s(), "category": _s(), "interface": _s(),
     "limit": {"type": "integer", "description": "suggest: 3 per role, max 10; modules: page"},
     "offset": {"type": "integer"}},
)



def calc_schema() -> dict[str, Any]:
    """bench_calc from the calculator register (calckit): every registered kind plus ``list``."""
    return _tool(
        "bench_calc",
        f"Calculators (units, assumptions, sources): {', '.join(modspec.BASIC_CALCS)} and more; list gives every "
        "calculator with its inputs. inputs: text with units or SI ('3V3', '20mA', '4k7'), e.g. led {v_supply, v_f, "
        "i_f}. project stores the result.",
        {"action": _action([*calckit.kinds(), CALC_LIST]), "inputs": _obj({}, additionalProperties=True),
         "project": _PROJECT},
    )


CALC = calc_schema()

SCHEMATIC = _tool(
    "bench_schematic",
    "Draw a block as SVG plus wiring table: led (r_series), npn_low_side (r_base), button_pullup, divider (r1, "
    "r2), module (part or params.module, params.gpios), level_shifter. Values: bench_calc. Returns svg_path, "
    "MEDIA line; project stores it, gives devkit, rails, role GPIO.",
    {"action": _action(["render"]), "block": _action(BLOCKS), "params": _obj({}, additionalProperties=True),
     "part": _s(), "gpio": _PIN, "role": _s("project role: its GPIO"), "devkit": _BOARD["devkit"],
     "project": _PROJECT, "out_dir": _s("absolute SVG folder")},
)

SOLDER = _tool(
    "bench_solder",
    "Soldering order for a BOM (plan) with polarity and safety hints, and ticking steps off (step, needs "
    "project). bom: CSV/one part per line, or rows; default: the project's parts.",
    {"action": _action(["plan", "step"]),
     "bom": {"anyOf": [{"type": "string"},
                       {"type": "array", "items": _obj({"ref": _s(), "value": _s(), "package": _s(),
                                                        "qty": {"type": "integer"}}, ("ref",))}]},
     "project": _PROJECT, "step_id": _s(), "done": {"type": "boolean"}},
)

BOARD = _tool(
    "bench_board",
    "Boards: ports, detect (esptool; resets the board), build (PlatformIO, no upload; runs the project's "
    "PlatformIO scripts, may download platforms), flash (detect + build first; that build's "
    "elf_sha256, allow_flash), monitor (serial lines, panics). Real builds, flashes and ports need approval. "
    "Refusals: chip_mismatch, platform_too_old. sim:// is simulated and emulates only the demo firmware "
    "(bench_project demo).",
    {"action": _action(["ports", "detect", "build", "flash", "monitor"]), "port": _s("e.g. /dev/ttyACM0 or sim://..."),
     "project": _PROJECT, "elf_sha256": _s("from the last build (12+ hex digits)"),
     "project_dir": _s("absolute folder with platformio.ini"), "env": _s("PlatformIO env"),
     "seconds": {"type": "number"}, "baud": {"type": "integer"}, "reset": {"type": "boolean"}},
)

CRASH = _tool(
    "bench_crash",
    "Decode an ESP32 panic (Guru Meditation, abort, watchdog, brownout): cause, registers, frames (function, "
    "file:line). log text or log_ref from bench_board monitor; project supplies "
    "chip and ELF. Read the code before proposing a fix.",
    {"action": _action(["decode"]), "log": _s(), "log_ref": _s(), "elf": _s("firmware.elf path"),
     "chip": _BOARD["chip"], "project": _PROJECT},
)

ALL = (PROJECT, PINS, CALC, SCHEMATIC, SOLDER, BOARD, CRASH)
NAMES = tuple(s["name"] for s in ALL)
EMOJI = {"bench_project": "🧰", "bench_pins": "📍", "bench_calc": "🧮", "bench_schematic": "📐",
         "bench_solder": "🔥", "bench_board": "🔌", "bench_crash": "💥"}
