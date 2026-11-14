"""Development board data: data/boards/<id>.json."""
from __future__ import annotations

import builtins
import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from .contracts import BenchError

BOARDS_DIR = Path(__file__).resolve().parent.parent / "data" / "boards"
PIN_KINDS = ("gpio", "power", "ground", "reset", "nc", "signal")  # nc/signal: not connected / board-only signal pins

# Board drawing: which physical parts the desktop model draws and roughly where.
# Every part carries a verbatim quote; a position read from a manufacturer photo also names the figure.
DRAWING_KINDS = ("usb_port", "button", "led", "power_led", "ldo", "bridge_ic", "rj45", "phy_ic", "antenna_connector")
DRAWING_CONNECTORS = ("micro_usb", "usb_c", None)
DRAWING_EDGES = ("top", "bottom", "left", "right")
DRAWING_ZONES = ("below_module", "middle", "lower")
DRAWING_SIDES = ("left", "center", "right")
_PART_KEYS = {"kind", "label", "ref", "gpio", "connector", "edge", "order", "zone", "side", "source_id", "quote",
              "figure", "note"}


LEAVE_DEVKIT_OUT = "; or leave devkit out: the chip checks still run, pins.broken_out and pins.board are skipped"


@lru_cache(maxsize=16)
def _read(board_id: str) -> dict[str, Any]:
    if not board_id or "/" in board_id or board_id.startswith("."):
        raise BenchError("unknown_board", f"unknown board {board_id!r}")
    path = BOARDS_DIR / f"{board_id}.json"
    if not path.is_file():
        raise BenchError("unknown_board", f"unknown board {board_id!r}",
                         f"known boards: {', '.join(ids())}{LEAVE_DEVKIT_OUT}")
    return json.loads(path.read_text(encoding="utf-8"))


def load(board_id: str) -> dict[str, Any]:
    """Board data as stored (deep copy)."""
    return json.loads(json.dumps(_read(board_id)))


def ids() -> list[str]:
    return sorted(p.stem for p in BOARDS_DIR.glob("*.json"))


def list_boards() -> list[dict[str, Any]]:
    out = []
    for board_id in ids():
        b = _read(board_id)
        out.append({"id": b["id"], "title": b["title"], "revision": b.get("revision"), "chip": b["chip"]})
    return out


def header_of(board_id: str, gpio: int) -> str | None:
    """'J3-13' for a GPIO broken out on the board, else None."""
    for header in _read(board_id)["headers"]:
        for pin in header["pins"]:
            if pin.get("kind") == "gpio" and pin.get("gpio") == gpio:
                return f"{header['id']}-{pin['n']}"
    return None


def broken_out(board_id: str) -> set[int]:
    return {p["gpio"] for h in _read(board_id)["headers"] for p in h["pins"] if p.get("kind") == "gpio"}


def layout(board_id: str) -> dict[str, Any]:
    """UI layout: pins per side in header order, plus onboard parts and USB ports.

    Boards that describe their module and buttons (ESP32-DevKitC V4, ESP32-C3-DevKitM-1) also return
    ``module`` ({name, part_numbers, variant, flash_mb, psram_mb, antenna, source_id}) and ``buttons`` (labels left to
    right as in the guide's pin layout figure); the S3-DevKitC-1 v1.1 answer keeps its original shape. Optional board keys
    are passed through when present: ``warnings`` (board-level hazards
    {id, severity, message, source_id}), ``connectors`` (e.g. RJ45), ``ethernet`` (PHY facts, information only) and
    ``flash_hint``. ``buttons: []`` means the board has no buttons. ``drawing`` is passed
    through unchanged; without it the desktop draws a generic, marked model.
    """
    try:
        b = _read(board_id)
    except BenchError as e:  # asked for by id: devkit cannot be left out here, so the hint only lists the boards
        raise BenchError(e.code, e.message, e.hint.removesuffix(LEAVE_DEVKIT_OUT) if e.hint else e.hint) from None
    sides: dict[str, list[dict[str, Any]]] = {"left": [], "right": []}
    for header in b["headers"]:
        for pin in header["pins"]:
            sides[header["side"]].append({"header": header["id"], **pin})
    out = {"id": b["id"], "title": b["title"], "revision": b.get("revision"), "chip": b["chip"],
           "source_id": b["source_id"], "left": sides["left"], "right": sides["right"],
           "onboard": [*b.get("onboard", [])], "usb": [*b.get("usb", [])]}
    for key in ("module", "buttons", "warnings", "connectors", "ethernet", "flash_hint", "drawing"):
        if key in b:
            out[key] = json.loads(json.dumps(b[key]))
    return out


def drawing_problems(board: dict[str, Any]) -> list[str]:
    """Contract check of a board's ``drawing`` block; [] when valid or absent."""
    d = board.get("drawing")
    if d is None:
        return []
    bad: list[str] = []
    if not isinstance(d, dict) or set(d) - {"schema", "orientation", "parts", "module_size_mm"}:
        return [f"drawing: unknown keys {sorted(set(d) - {'schema', 'orientation', 'parts', 'module_size_mm'})}"]
    if d.get("schema") != 1 or d.get("orientation") != "module_top" or not isinstance(d.get("parts"), builtins.list):
        bad.append("drawing: schema 1, orientation module_top and a parts list are required")
        return bad
    usb_labels = {u.get("label") for u in board.get("usb", [])}
    onboard_gpios = {o.get("gpio") for o in board.get("onboard", [])}
    seen_edges: set[tuple[str, int]] = set()
    for i, p in enumerate(d["parts"]):
        where = f"drawing.parts[{i}]"
        if not isinstance(p, dict):
            bad.append(f"{where}: not an object")
            continue
        if set(p) - _PART_KEYS:
            bad.append(f"{where}: unknown keys {sorted(set(p) - _PART_KEYS)}")
        if p.get("kind") not in DRAWING_KINDS:
            bad.append(f"{where}: kind {p.get('kind')!r}")
        if not (isinstance(p.get("source_id"), str) and isinstance(p.get("quote"), str) and p["quote"].strip()):
            bad.append(f"{where}: source_id and a verbatim quote are required")
        if p.get("connector", None) not in DRAWING_CONNECTORS:
            bad.append(f"{where}: connector {p.get('connector')!r}")
        if "connector" in p and p.get("kind") != "usb_port":
            bad.append(f"{where}: connector only on usb_port")
        has_edge, has_zone = "edge" in p, "zone" in p
        if has_edge == has_zone:
            bad.append(f"{where}: exactly one of edge (+order) or zone")
        if has_edge:
            if p["edge"] not in DRAWING_EDGES or not isinstance(p.get("order"), int) or p["order"] < 1:
                bad.append(f"{where}: edge {p.get('edge')!r} needs an order >= 1")
            elif (p["edge"], p["order"]) in seen_edges:
                bad.append(f"{where}: duplicate {p['edge']} order {p['order']}")
            else:
                seen_edges.add((p["edge"], p["order"]))
            if "side" in p:
                bad.append(f"{where}: side only with zone")
        if has_zone and (p["zone"] not in DRAWING_ZONES or p.get("side", "center") not in DRAWING_SIDES):
            bad.append(f"{where}: zone {p.get('zone')!r} / side {p.get('side')!r}")
        if bool(p.get("figure")) != bool(p.get("note")):
            bad.append(f"{where}: figure and note go together")
        if p.get("kind") == "usb_port" and p.get("ref") not in usb_labels:
            bad.append(f"{where}: ref {p.get('ref')!r} is not a usb[].label")
        if p.get("kind") == "led" and p.get("gpio") not in onboard_gpios:
            bad.append(f"{where}: gpio {p.get('gpio')!r} is not an onboard[].gpio")
        if "gpio" in p and p.get("kind") != "led":
            bad.append(f"{where}: gpio only on led")
        if p.get("kind") in ("button", "led", "power_led", "ldo", "bridge_ic", "phy_ic") and not p.get("label"):
            bad.append(f"{where}: label required")
    if p_buttons := [p.get("label") for p in d["parts"] if isinstance(p, dict) and p.get("kind") == "button"]:
        if "buttons" in board and sorted(p_buttons) != sorted(board["buttons"]):
            bad.append(f"drawing: buttons {p_buttons} differ from buttons {board['buttons']}")
    m = d.get("module_size_mm")
    if m is not None and not (isinstance(m, dict) and set(m) == {"w", "h", "source_id", "quote"}
                              and all(isinstance(m[k], (int, float)) and m[k] > 0 for k in ("w", "h"))):
        bad.append("drawing.module_size_mm: {w, h, source_id, quote} with positive sizes")
    return bad


def warnings_of(board_id: str) -> list[dict[str, Any]]:
    """Board-level hazards, [] for boards without any."""
    return json.loads(json.dumps(_read(board_id).get("warnings", [])))


def clear_cache() -> None:
    _read.cache_clear()


list = list_boards  # contract name; shadows the builtin here, so this module never calls it
