"""Bench project store: one ``project.json`` (schema 1) per project.

Actions (result envelope): ``create``, ``get``, ``list``, ``update``, ``delete``. Helpers (raise ``BenchError``):
``path``, ``artifacts_dir``, ``validate``.

``delete`` never removes files: it moves the whole project folder (``project.json``, ``artifacts/``, a copied
``firmware/``) to ``data_dir()/trash/<id>-<UTC stamp>/``, so a mistaken click can be undone by moving it back.
Firmware folders outside the project (``firmware.dir`` set by the agent) are never touched.

Storage: ``storage.data_dir()/projects/<id>/project.json`` plus ``artifacts/``. Folders 0700, files 0600.

Writing only through ``update(id, expected_rev, ops, *, by)`` with the typed operations (``OPS``):
- every op is checked before anything is written; one bad op rejects the whole update (nothing changes);
- ``fcntl.flock`` on ``projects/<id>/.lock`` (0600, never deleted) serialises writers across processes;
- a wrong ``expected_rev`` is ``project_conflict`` (result carries the current ``rev``);
- written atomically (temporary file in the same folder, fsync, ``os.replace``);
- ``rev`` grows by one per write; an update that changes nothing writes nothing and keeps ``rev``;
- after a write the event ``project.updated`` ``{id, rev, changed, by}`` goes out (``events.emit``).

``assign``/``unassign``/``set_board`` (and the module ops, ``_VERDICT_OPS``) recompute every verdict with
``pins.check`` (the server decides, never the caller). Op shape: ``{"op": "<name>", <fields>}``; field tables in ``OPS``. ``set_detected``, ``set_build``,
``set_flash`` and ``set_debug`` accept the full result objects of board.detect/build/flash and crash.decode and keep
only the project fields; all other ops refuse unknown fields. Those four (``SERVER_OPS``) are written only by
server-side producers (``update(..., trusted=True)``), never by a client.

Module instances (schema stays 1, every field optional): a part may carry ``module``
(catalog id; an alias is stored as its id), ``variant``, ``conn`` ({pin: net}; plain parts may carry it too),
``address`` (I²C, lower case) and ``facts`` (user facts of the breakout, keys ``modspec.FACT_KEYS``). ``options``
may carry ``rails`` ({net: V}) and ``rail_limits`` ({net: A}). Ops ``add_module``, ``connect`` (changes conn,
address, facts, variant, qty in place), ``set_rails``.
Writes check these against the catalog (``_catalog()``); reading checks only their form, so a project whose module
left the catalog still loads (the engine reports ``mod.unknown``). Module findings are never stored.
"""
from __future__ import annotations

import builtins
import contextlib
import copy
import datetime as _dt
import fcntl
import json
import logging
import math
import os
import re
import tempfile
import time
from collections.abc import Iterator, Mapping
from functools import lru_cache
from pathlib import Path
from typing import Any

from . import boards, bom, events, modspec, pins, solder, sources, storage, units
from . import settings as _settings
from .contracts import MODES, WARNING_SEVERITIES, BenchError, assumption, envelope, fail, from_error, warning

logger = logging.getLogger(__name__)
_list = builtins.list  # this module exports list() (contract name): at run time the plain name is list_projects
_SEQ = (builtins.list, tuple)

SCHEMA = 1
BY = ("agent", "ui")
LOCK_TIMEOUT_S = 10.0
MAX_OPS = 50
MAX_PROJECT_BYTES = 1 << 20
MAX_ASSIGNMENTS = 64
MAX_PARTS = 200
MAX_CALCS = 50
MAX_CIRCUITS = 30
MAX_STEPS = 100
MAX_NOTES = 200
NOTE_MAX_CHARS = 2000
TITLE_MAX_CHARS = 120
DEFAULT_OPTIONS = {"wifi": True, "framework": "arduino", "logic_v": 3.3}
PACKAGE_DIR = Path(__file__).resolve().parent.parent  # circuit_bench/: never a firmware folder

_ID_RE = re.compile(r"^[a-z0-9-]{1,48}$")
_ISO_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
_ROLE_RE = re.compile(r"^[A-Z0-9_]{1,24}$")
_NET_RE = re.compile(r"^[A-Za-z0-9_+.-]{1,32}$")
_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,31}$")
_TYPE_RE = re.compile(r"^[a-z0-9_]{1,32}$")
_CODE_RE = re.compile(r"^[a-z0-9_]{1,40}$")
_SOURCE_ID_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,80}$")
_REF_RE = re.compile(r"^[A-Z][A-Z_]*\d+[A-Z0-9_.]*$")  # same rule as bom.py
_STEP_ID_RE = re.compile(r"^[0-9a-f]{10}$")
_SHA_RE = re.compile(r"^[0-9a-f]{64}$")
_IMAGE_RE = re.compile(r"^[A-Za-z0-9_.-]{1,60}\.bin$")
_LOG_SHA_RE = re.compile(r"^[0-9a-f]{8,64}$")  # the prefix of the "ELF file SHA256: ..." panic/boot line
_MAC_RE = re.compile(r"^[0-9a-f]{2}(?::[0-9a-f]{2}){5,7}$")
_ENV_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.:-]{0,63}$")  # same rule as board.py
_LOG_REF_RE = re.compile(r"^[a-z]+-\d{8}-\d{6}(?:-\d+)?\.log$")  # same rule as serialport.py
_SVG_RE = re.compile(r"^artifacts/[A-Za-z0-9_.-]{1,64}\.svg$")

TOP_KEYS = ("schema", "id", "rev", "title", "simulated", "created", "updated", "board", "options", "assignments",
            "parts", "calcs", "circuits", "solder", "firmware", "debug", "notes")
CONTENT_KEYS = ("board", "options", "assignments", "parts", "calcs", "circuits", "solder", "firmware", "debug", "notes")
BOARD_KEYS = ("chip", "module", "variant", "devkit", "detected")
ASSIGNMENT_KEYS = ("role", "mode", "pin", "net", "verdict", "rule_ids", "updated_by")
DETECTED_FIELDS = ("port", "mac", "chip", "description", "features", "flash_size", "variant_suggestion", "at", "simulated")
DETECTED_OPTIONAL = ("usb_id",)  # stored only when set (older projects and sim boards have none)
_HEX4_RE = re.compile(r"^[0-9a-f]{4}$")
BUILD_FIELDS = ("ok", "at", "ram_pct", "flash_pct", "elf", "elf_sha256", "images", "chip")  # images: optional;
# chip: the chip the env was checked to build for (board.build pre-check), optional
FLASH_FIELDS = ("ok", "at", "port", "mac", "elf_sha256")
PANIC_FIELDS = ("kind", "reason", "core", "arch", "top_frame", "at", "log_ref", "elf_match", "elf_sha256")
PART_FIELDS = ("ref", "kind", "value", "package", "qty", "from_calc")
PART_MODULE_FIELDS = modspec.PART_MODULE_FIELDS  # optional: module, variant, conn, address, facts
PART_ALL_FIELDS = PART_FIELDS + PART_MODULE_FIELDS  # stored order of a part's keys
OPTION_OPTIONAL = ("rails", "rail_limits")  # optional options keys; left out when empty
MAX_RAILS = 16  # entries of options.rails and of options.rail_limits
MAX_RAIL_A = 10.0  # options.rail_limits: a user-given load limit in A
MAX_PULLUP_OHM = 10e6
MAX_PART_A = 50.0  # facts.i_max: the measured / confirmed current of one part (all of its qty), in A
MODULE_HINT = "list modules with bench_pins action=modules"
_PIN_NAME_RE = re.compile(r"^[A-Za-z0-9_+.-]{1,16}$")  # conn pin names of plain parts (R3: "1", "2")
# Pin names of plain parts (add_parts conn / connect): free text; the module checks (modrules required_parts,
# flyback, pull-ups …) read only the nets a part touches, never the pin names, so polarity is not checked. The
# names below are the convention the docs (schema, skill) use.
PLAIN_PIN_HINT = ("pin names: [A-Za-z0-9_+.-]{1,16}; resistor/capacitor 1, 2; electrolytic/battery +, -; "
                  "diode/LED A, K")
_U_REF_RE = re.compile(r"^U(\d+)$")
CALC_FIELDS = ("id", "type", "inputs", "result", "assumptions", "sources")
CIRCUIT_FIELDS = ("id", "block", "params", "svg")
STEP_FIELDS = ("id", "n", "refs", "kind", "action", "hints")
HINT_FIELDS = ("code", "severity", "text", "source_ids")

# op -> fields. Ops in _RESULT_OPS take a result object and drop fields that are not project fields.
OPS: dict[str, tuple[str, ...]] = {
    "set_board": ("chip", "variant", "devkit", "wifi"),
    "set_detected": DETECTED_FIELDS + DETECTED_OPTIONAL,
    "assign": ("role", "mode", "pin", "net"),
    "unassign": ("role",),
    "add_parts": ("parts",),
    "remove_parts": ("refs",),
    "add_calc": ("calc",),
    "add_circuit": ("circuit",),
    "set_solder_plan": ("steps",),
    "solder_done": ("step_id", "done"),
    "set_firmware": ("dir", "env"),
    "set_build": BUILD_FIELDS,
    "set_flash": FLASH_FIELDS,
    "set_debug": ("last_panic",),
    "note": ("text",),
    "add_module": ("module", "variant", "ref", "conn", "address", "facts", "qty"),
    "connect": ("ref", "conn", "address", "facts", "variant", "qty"),
    "set_rails": ("rails", "rail_limits"),
}
_RESULT_OPS = frozenset({"set_detected", "set_build", "set_flash"})
# Results of actions the server ran itself (board.detect/build/flash, crash.decode). Only server-side producers
# (jobs.record, the tool handlers, the crash route) write them with ``update(..., trusted=True)``; a client
# (PATCH /projects/{id}) cannot fake a detected board or an approved build.
SERVER_OPS = frozenset({"set_detected", "set_build", "set_flash", "set_debug"})
_VERDICT_OPS = frozenset({"set_board", "assign", "unassign", *modspec.MODULE_OPS})  # update() sets recompute


# --------------------------------------------------------------------------------------------- primitives

def _now() -> str:
    return _dt.datetime.now(_dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _bad(where: str, msg: str, hint: str | None = None) -> BenchError:
    return BenchError("invalid_args", f"{where}: {msg}", hint)


def _text(value: Any, where: str, max_len: int, *, none: bool = False, pattern: re.Pattern[str] | None = None,
          hint: str | None = None, multiline: bool = False) -> str | None:
    if value is None and none:
        return None
    if not isinstance(value, str):
        raise _bad(where, f"expected text, not {type(value).__name__}", hint)
    allowed = "\t\n" if multiline else ""
    if not value or len(value) > max_len or any((ord(c) < 32 or ord(c) == 127) and c not in allowed for c in value):
        raise _bad(where, f"expected 1 to {max_len} characters without control characters", hint)
    if pattern is not None and not pattern.fullmatch(value):
        raise _bad(where, f"bad value {value[:60]!r}", hint)
    return value


def _bool(value: Any, where: str, *, none: bool = False) -> bool | None:
    if value is None and none:
        return None
    if not isinstance(value, bool):
        raise _bad(where, "expected true or false")
    return value


def _int(value: Any, where: str, lo: int, hi: int, *, none: bool = False) -> int | None:
    if value is None and none:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or not lo <= value <= hi:
        raise _bad(where, f"expected a whole number from {lo} to {hi}")
    return value


def _num(value: Any, where: str, lo: float, hi: float, *, none: bool = False) -> float | int | None:
    if value is None and none:
        return None
    if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(value) or not lo <= value <= hi:
        raise _bad(where, f"expected a number from {lo:g} to {hi:g}")
    return value


def _iso(value: Any, where: str, *, default_now: bool = False, none: bool = False) -> str | None:
    if value is None and default_now:
        return _now()
    if value is None and none:
        return None
    if not isinstance(value, str) or not _ISO_RE.fullmatch(value):
        raise _bad(where, "expected an ISO 8601 UTC time like 2026-11-06T21:41:07Z")
    return value


def _json(value: Any, where: str, kind: type, max_bytes: int) -> Any:
    if not isinstance(value, kind):
        raise _bad(where, f"expected {'an object' if kind is dict else 'a list'}")
    try:
        text = json.dumps(value, ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError):
        raise _bad(where, "must contain only JSON values") from None
    if len(text.encode("utf-8")) > max_bytes:
        raise _bad(where, f"larger than {max_bytes} bytes")
    return json.loads(text)


def _fields(obj: Any, where: str, allowed: tuple[str, ...], *, required: tuple[str, ...] = (),
            lenient: bool = False) -> dict[str, Any]:
    if not isinstance(obj, Mapping):
        raise _bad(where, "expected an object")
    extra = [k for k in obj if k not in allowed]
    if extra and not lenient:
        raise _bad(where, f"unknown field {sorted(map(str, extra))[0]!r}", f"fields: {', '.join(allowed)}")
    missing = [k for k in required if k not in obj]
    if missing:
        raise _bad(where, f"missing field {missing[0]!r}")
    return {k: obj[k] for k in allowed if k in obj}


def _home_dirs() -> set[Path]:
    """The home folders a firmware folder must not be: HOME and the account's home (both resolved)."""
    out = set()
    for home in (os.environ.get("HOME"), storage.real_home()):
        if home:
            with contextlib.suppress(OSError, RuntimeError):
                out.add(Path(home).expanduser().resolve())
    return out


def _check_id(pid: Any) -> str:
    if not isinstance(pid, str) or not _ID_RE.fullmatch(pid):
        raise BenchError("invalid_args", f"bad project id {str(pid)[:60]!r}",
                         "project ids are 1 to 48 characters a-z, 0-9 and '-', e.g. laser-trigger")
    return pid


def _not_found(pid: str) -> BenchError:
    return BenchError("project_not_found", f"no bench project {pid!r}", _settings.PROJECT_LIST_HINT)


# --------------------------------------------------------------------------------------------- board data

@lru_cache(maxsize=8)
def _chip_info(chip: str) -> tuple[str, dict[str, tuple[str, str | None]]]:
    """(chip title, {variant id: (label, module family like 'wroom-1')})."""
    data = pins.load(chip)
    title = data["title"]
    variants: dict[str, tuple[str, str | None]] = {}
    for v in data.get("variants", []):
        label, module = v.get("label") or v["id"].upper(), v.get("module") or ""
        family = None
        if module == f"{title}-{label}":  # ESP32: the variant is the module (ESP32-WROOM-32E, label WROOM-32E)
            family = label.lower()
        elif module.startswith(f"{title}-") and module.endswith(f"-{label}"):  # ESP32-S3-WROOM-1-N16R8
            family = module[len(title) + 1:len(module) - len(label) - 1].lower() or None
        variants[v["id"]] = (label, family)
    return title, variants


def _variant(chip: str, variant: Any) -> tuple[str | None, str | None]:
    """(variant id, module family)."""
    if variant is None:
        return None, None
    title, variants = _chip_info(chip)
    if not isinstance(variant, str):
        raise _bad("variant", "expected text or null")
    vid = variant.strip().lower()
    if not variants:
        raise BenchError("invalid_args", f"no module variants known for {title}", "pass variant=null for this chip")
    if vid not in variants:
        raise BenchError("invalid_args", f"unknown module variant {variant[:20]!r} for {title}",
                         f"known variants: {', '.join(variants)}")
    return vid, variants[vid][1]


def _devkit(chip: str, devkit: Any) -> str | None:
    if devkit is None:
        return None
    if not isinstance(devkit, str):
        raise _bad("devkit", "expected a board id or null")
    board = boards.load(devkit)  # unknown_board
    if board["chip"] != chip:
        raise BenchError("invalid_args", f"{board['title']} carries an {board['chip']}, not an {chip}",
                         "pick the chip of the board or another devkit")
    return devkit


def _board_label(board: Mapping[str, Any]) -> str:
    try:
        title, variants = _chip_info(board["chip"])
    except BenchError:
        return str(board.get("chip"))
    if board.get("variant") in variants:
        return f"{title} {variants[board['variant']][0]}"
    return title


# --------------------------------------------------------------------------------------------- normalisers

def _detected(obj: Any, where: str = "set_detected") -> dict[str, Any]:
    f = _fields(obj, where, DETECTED_FIELDS + DETECTED_OPTIONAL, required=("port",), lenient=True)
    port = _text(f["port"], f"{where}.port", 256)
    mac = _text(f.get("mac"), f"{where}.mac", 23, none=True)
    if mac is not None:
        mac = mac.strip().lower()
        if not _MAC_RE.fullmatch(mac):
            raise _bad(f"{where}.mac", f"bad MAC address {mac!r}")
    features = f.get("features") or []
    if not isinstance(features, _SEQ) or len(features) > 32:
        raise _bad(f"{where}.features", "expected a list of at most 32 texts")
    simulated = f.get("simulated")
    out = {
        "port": port, "mac": mac,
        "chip": _text(f.get("chip"), f"{where}.chip", 80, none=True),
        "description": _text(f.get("description"), f"{where}.description", 200, none=True),
        "features": [_text(x, f"{where}.features[]", 120) for x in features],
        "flash_size": _text(f.get("flash_size"), f"{where}.flash_size", 16, none=True),
        "variant_suggestion": _text(f.get("variant_suggestion"), f"{where}.variant_suggestion", 16, none=True),
        "at": _iso(f.get("at"), f"{where}.at", default_now=True),
        "simulated": port.startswith("sim://") if simulated is None else _bool(simulated, f"{where}.simulated"),
    }
    usb_id = _usb_id(f.get("usb_id"), f"{where}.usb_id")
    if usb_id is not None:  # optional: sim boards, ports without a USB serial number and older projects have none
        out["usb_id"] = usb_id
    return out


def _usb_id(value: Any, where: str) -> dict[str, str] | None:
    """USB identity of a detected board: {"vid", "pid"} 4 hex digits each, "serial" 1-64 printable
    characters; None stays None."""
    if value is None:
        return None
    f = _fields(value, where, ("vid", "pid", "serial"), required=("vid", "pid", "serial"))
    out = {}
    for key in ("vid", "pid"):
        v = f[key].strip().lower() if isinstance(f[key], str) else f[key]
        _text(v, f"{where}.{key}", 4, pattern=_HEX4_RE, hint="4 hex digits, e.g. 303a")
        out[key] = v
    serial = _text(f["serial"], f"{where}.serial", 64)
    if not serial.isprintable():
        raise _bad(f"{where}.serial", "expected printable characters")
    out["serial"] = serial
    return out


def _sha(value: Any, where: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not _SHA_RE.match(value.strip().lower()):
        raise _bad(where, "expected the 64-digit SHA-256 of the ELF or null")
    return value.strip().lower()


def _images(value: Any, where: str) -> dict[str, str] | None:
    """``{image file name: sha256}`` of the flash images of a build (firmware.bin, bootloader.bin, partitions.bin)."""
    if value is None:
        return None
    if not isinstance(value, Mapping) or len(value) > 8:
        raise _bad(where, "expected an object {image file name: sha256} with at most 8 entries")
    out = {}
    for name, sha in sorted(value.items()):
        _text(name, f"{where} name", 64, pattern=_IMAGE_RE)
        out[name] = _sha(sha, f"{where}.{name}")
        if out[name] is None:
            raise _bad(f"{where}.{name}", "expected the 64-digit SHA-256 of the image")
    return out


def _build(obj: Any, where: str = "set_build") -> dict[str, Any]:
    f = _fields(obj, where, BUILD_FIELDS, required=("ok",), lenient=True)
    out = {
        "ok": _bool(f["ok"], f"{where}.ok"),
        "at": _iso(f.get("at"), f"{where}.at", default_now=True),
        "ram_pct": _num(f.get("ram_pct"), f"{where}.ram_pct", 0, 100, none=True),
        "flash_pct": _num(f.get("flash_pct"), f"{where}.flash_pct", 0, 100, none=True),
        "elf": _text(f.get("elf"), f"{where}.elf", 1024, none=True),
        "elf_sha256": _sha(f.get("elf_sha256"), f"{where}.elf_sha256"),
    }
    images = _images(f.get("images"), f"{where}.images")
    if images:  # optional: simulated builds and projects of older versions have none
        out["images"] = images
    if f.get("chip") is not None:  # optional: builds without the pre-check (sim, older versions, unreadable env)
        out["chip"] = pins.normalize_chip(f["chip"])
    return out


def _flash(obj: Any, where: str = "set_flash") -> dict[str, Any]:
    f = _fields(obj, where, FLASH_FIELDS, required=("ok",), lenient=True)
    mac = _text(f.get("mac"), f"{where}.mac", 23, none=True)
    if mac is not None:
        mac = mac.strip().lower()
        if not _MAC_RE.fullmatch(mac):
            raise _bad(f"{where}.mac", f"bad MAC address {mac!r}")
    return {
        "ok": _bool(f["ok"], f"{where}.ok"),
        "at": _iso(f.get("at"), f"{where}.at", default_now=True),
        "port": _text(f.get("port"), f"{where}.port", 256, none=True),
        "mac": mac,
        "elf_sha256": _sha(f.get("elf_sha256"), f"{where}.elf_sha256"),
    }


def _top_frame(frames: Any) -> str | None:
    if not isinstance(frames, _SEQ):
        return None
    for fr in frames:
        if isinstance(fr, Mapping) and isinstance(fr.get("function"), str) and fr["function"] not in ("", "??"):
            file, line = fr.get("file"), fr.get("line")
            where = f" ({file}:{line})" if isinstance(file, str) and file and file != "??" and line else ""
            return f"{fr['function']}{where}"[:200]
    return None


_REF_STAMP_RE = re.compile(r"^[a-z]+-(\d{8})-(\d{6})(?:-\d+)?\.log$")


def _ref_time(log_ref: Any) -> str | None:
    """UTC time of a serial artifact name (serialport.open_artifact: "panic-YYYYMMDD-HHMMSS[-n].log")."""
    m = _REF_STAMP_RE.match(log_ref) if isinstance(log_ref, str) else None
    if not m:
        return None
    try:
        t = _dt.datetime.strptime(m.group(1) + m.group(2), "%Y%m%d%H%M%S")
    except ValueError:
        return None
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


def _panic(obj: Any, where: str = "set_debug.last_panic") -> dict[str, Any] | None:
    """Short form of a crash.decode result (or of an already short panic). Fields that are null are left out."""
    if obj is None:
        return None
    if isinstance(obj, Mapping) and obj.get("action") == "crash.decode" and isinstance(obj.get("result"), Mapping):
        obj = obj["result"]  # a whole envelope
    if not isinstance(obj, Mapping):
        raise _bad(where, "expected the crash.decode result or null")
    top = obj.get("top_frame")
    if top is None:
        top = _top_frame(obj.get("frames"))
    log_ref = _text(obj.get("log_ref"), f"{where}.log_ref", 64, none=True, pattern=_LOG_REF_RE)
    # which firmware crashed: the hash prefix of the "ELF file SHA256:" line (crash.decode: elf_sha256_log)
    log_sha = obj.get("elf_sha256") if "elf_sha256" in obj else obj.get("elf_sha256_log")
    if isinstance(log_sha, str):
        log_sha = log_sha.strip().lower()
    out = {
        "kind": _text(obj.get("kind"), f"{where}.kind", 32, none=True, pattern=_TYPE_RE),
        "reason": _text(obj.get("reason"), f"{where}.reason", 120, none=True),
        "core": _int(obj.get("core"), f"{where}.core", 0, 7, none=True),
        "arch": _text(obj.get("arch"), f"{where}.arch", 16, none=True, pattern=_TYPE_RE),
        "top_frame": _text(top, f"{where}.top_frame", 200, none=True),
        # when the board crashed, not when it was decoded: a decode after a flash must not make an old panic current
        "at": _iso(obj.get("at") if obj.get("at") is not None else _ref_time(log_ref), f"{where}.at", default_now=True),
        "log_ref": log_ref,
        "elf_match": _bool(obj.get("elf_match"), f"{where}.elf_match", none=True),
        "elf_sha256": _text(log_sha, f"{where}.elf_sha256", 64, none=True, pattern=_LOG_SHA_RE),
    }
    if out["kind"] is None and out["reason"] is None:
        raise _bad(where, "needs kind or reason")
    return {k: v for k, v in out.items() if v is not None}


def _assignment(obj: Any, where: str, by: str) -> dict[str, Any]:
    f = _fields(obj, where, OPS["assign"], required=("role", "mode", "pin"))
    mode = f["mode"]
    if mode not in MODES:
        raise _bad(f"{where}.mode", f"unknown mode {str(mode)[:20]!r}", f"modes: {', '.join(MODES)}")
    try:
        pin = pins.normalize_pin(f["pin"])
    except BenchError as e:
        raise _bad(f"{where}.pin", e.message, e.hint) from None
    return {"role": _text(f["role"], f"{where}.role", 24, pattern=_ROLE_RE,
                          hint="role: [A-Z0-9_]{1,24}, e.g. LASER or BUTTON"),
            "mode": mode, "pin": pin,
            "net": _text(f.get("net"), f"{where}.net", 32, none=True, pattern=_NET_RE, hint="net: [A-Za-z0-9_+.-]{1,32}"),
            "verdict": "ok", "rule_ids": [], "updated_by": by}


def _part(obj: Any, where: str, *, stored: bool = False, aliases: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Normalised part. ``stored``: the check of a stored project (only the form of the module fields, no catalog).
    ``aliases``: collects the pin_alias assumptions of a module part's conn (see ``_conn``)."""
    f = _fields(obj, where, PART_ALL_FIELDS, required=("ref", "kind", "value"))
    ref = _text(f["ref"], f"{where}.ref", 16, hint="references look like R1, C2, LED3, SW1")
    ref = ref.strip().upper()
    if not _REF_RE.fullmatch(ref):
        raise _bad(f"{where}.ref", f"bad reference {ref!r}", "references look like R1, C2, LED3, SW1")
    kind = f["kind"]
    if kind not in bom.kinds():
        raise _bad(f"{where}.kind", f"unknown part kind {str(kind)[:20]!r}", f"kinds: {', '.join(bom.kinds())}")
    out: dict[str, Any] = {"ref": ref, "kind": kind, "value": _text(f["value"], f"{where}.value", 60)}
    if "package" in f:
        out["package"] = _text(f["package"], f"{where}.package", 40)
    if "qty" in f:
        out["qty"] = _int(f["qty"], f"{where}.qty", 1, 999)
    if "from_calc" in f:
        out["from_calc"] = _text(f["from_calc"], f"{where}.from_calc", 32, pattern=_SLUG_RE)
    if any(k in f for k in PART_MODULE_FIELDS):
        out.update(_module_fields(f, where, stored=stored, aliases=aliases))
    return out


def _module_fields(f: Mapping[str, Any], where: str, *, stored: bool,
                   aliases: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """module, variant, conn, address, facts of a part, in stored order. Writing (``stored`` False) resolves
    the module in the catalog and checks variant, conn pins and address against it; null there means "not given".
    A stored project is checked for form only, so a module that left the catalog never damages it."""
    if not stored:
        f = {k: v for k, v in f.items() if v is not None}
    if "module" not in f:
        lone = next((k for k in ("variant", "address", "facts") if k in f), None)
        if lone is not None:
            raise _bad(f"{where}.{lone}", "only for a module part: give module too", MODULE_HINT)
    out: dict[str, Any] = {}
    entry: Mapping[str, Any] | None = None
    if "module" in f:
        if stored:
            out["module"] = _text(f["module"], f"{where}.module", 32, pattern=modspec.MODULE_ID_RE, hint=MODULE_HINT)
            if "variant" in f:
                out["variant"] = _text(f["variant"], f"{where}.variant", 32)
        else:
            mid, vid, entry = _module_entry(f["module"], f.get("variant"), where)
            out["module"] = mid
            if vid is not None:
                out["variant"] = vid
    if "conn" in f:
        conn = _conn(f["conn"], f"{where}.conn", _pins(entry) if entry is not None else None, module="module" in f,
                     module_id=out.get("module"), aliases=aliases)
        if conn:  # never stored empty (a stored {} is then not in the stored form)
            out["conn"] = conn
    if "address" in f:
        out["address"] = _address(f["address"], f"{where}.address", entry, out.get("module"))
    if "facts" in f:
        facts = _facts(f["facts"], f"{where}.facts")
        if facts:
            out["facts"] = facts
    return out


def _short_title(title: Any, module_id: str) -> str:
    """Part value of a module instance: the first word of the catalog title (the part number, e.g. BME280)."""
    words = title.split() if isinstance(title, str) else []
    short = words[0].strip(",;:") if words else ""
    return (short or module_id.upper())[:60]


def _source_ids(value: Any, where: str) -> list[str]:
    if not isinstance(value, _SEQ) or len(value) > 50:
        raise _bad(where, "expected a list of source ids")
    out: list[str] = []
    for s in value:
        sid = s.get("id") if isinstance(s, Mapping) else s  # a resolved source object or its id
        sid = _text(sid, f"{where}[]", 80, pattern=_SOURCE_ID_RE)
        if sid not in out:
            out.append(sid)
    return out


def _calc(obj: Any, where: str = "add_calc.calc") -> dict[str, Any]:
    f = _fields(obj, where, CALC_FIELDS, required=("id", "type", "inputs", "result"))
    return {"id": _text(f["id"], f"{where}.id", 32, pattern=_SLUG_RE, hint="calc ids look like npn-1"),
            "type": _text(f["type"], f"{where}.type", 32, pattern=_TYPE_RE),
            "inputs": _json(f["inputs"], f"{where}.inputs", dict, 8192),
            "result": _json(f["result"], f"{where}.result", dict, 16384),
            "assumptions": _json(f.get("assumptions", []), f"{where}.assumptions", _list, 8192),
            "sources": _source_ids(f.get("sources", []), f"{where}.sources")}


def _circuit(obj: Any, where: str = "add_circuit.circuit") -> dict[str, Any]:
    f = _fields(obj, where, CIRCUIT_FIELDS, required=("id", "block"))
    return {"id": _text(f["id"], f"{where}.id", 32, pattern=_SLUG_RE),
            "block": _text(f["block"], f"{where}.block", 32, pattern=_TYPE_RE),
            "params": _json(f.get("params", {}), f"{where}.params", dict, 8192),
            "svg": _text(f.get("svg"), f"{where}.svg", 80, none=True, pattern=_SVG_RE,
                         hint="svg: a file under the project's artifacts/ folder, e.g. artifacts/laser.svg")}


def _hint(obj: Any, where: str) -> dict[str, Any]:
    f = _fields(obj, where, HINT_FIELDS, required=HINT_FIELDS)
    if f["severity"] not in WARNING_SEVERITIES:
        raise _bad(f"{where}.severity", f"expected one of {', '.join(WARNING_SEVERITIES)}")
    return {"code": _text(f["code"], f"{where}.code", 40, pattern=_CODE_RE), "severity": f["severity"],
            "text": _text(f["text"], f"{where}.text", 600, multiline=True), "source_ids": _source_ids(f["source_ids"], f"{where}.source_ids")}


def _step(obj: Any, where: str) -> dict[str, Any]:
    f = _fields(obj, where, STEP_FIELDS, required=STEP_FIELDS)
    kind = f["kind"]
    if kind not in bom.kinds():
        raise _bad(f"{where}.kind", f"unknown part kind {str(kind)[:20]!r}")
    refs = f["refs"]
    if not isinstance(refs, _SEQ) or not refs or len(refs) > MAX_PARTS:
        raise _bad(f"{where}.refs", "expected a non-empty list of references")
    refs = [_text(r, f"{where}.refs[]", 16, pattern=_REF_RE) for r in refs]
    sid = _text(f["id"], f"{where}.id", 10, pattern=_STEP_ID_RE)
    if sid != solder.step_id(kind, refs):
        raise _bad(f"{where}.id", f"step id {sid} does not belong to {kind} {','.join(refs)}",
                   "pass the steps exactly as solder.plan returned them")
    hints = f["hints"]
    if not isinstance(hints, _SEQ) or len(hints) > 20:
        raise _bad(f"{where}.hints", "expected a list of at most 20 hints")
    return {"id": sid, "n": _int(f["n"], f"{where}.n", 1, MAX_STEPS), "refs": refs, "kind": kind,
            "action": _text(f["action"], f"{where}.action", 600, multiline=True),
            "hints": [_hint(h, f"{where}.hints[{i}]") for i, h in enumerate(hints)]}


def _note(obj: Any, where: str) -> dict[str, Any]:
    f = _fields(obj, where, ("text", "at", "by"), required=("text", "at", "by"))
    if f["by"] not in BY:
        raise _bad(f"{where}.by", "expected agent or ui")
    return {"text": _text(f["text"], f"{where}.text", NOTE_MAX_CHARS, multiline=True), "at": _iso(f["at"], f"{where}.at"), "by": f["by"]}


# --------------------------------------------------------------------------------------------- modules

def _catalog() -> Any:
    """The module catalog (``modules.catalog()``). The one seam to it: imported lazily, so the project store works
    without a catalog; tests swap it for a fake with ``has``/``resolve_id``/``get``."""
    from . import modules
    return modules.catalog()


def _module_entry(name: Any, variant: Any, where: str) -> tuple[str, str | None, dict[str, Any]]:
    """(module id, variant id or None, catalog entry with the variant applied) for an id or alias."""
    if not isinstance(name, str) or not name.strip() or len(name) > 64:
        raise _bad(f"{where}.module", "expected a module id or alias, e.g. bme280", MODULE_HINT)
    if variant is not None:
        _text(variant, f"{where}.variant", 32)
    try:
        cat = _catalog()
        key = name.strip()
        if not cat.has(key) and cat.has(key.lower()):
            key = key.lower()
        if not cat.has(key):
            raise BenchError("invalid_args", f"{where}.module: unknown module {name.strip()[:40]!r}", MODULE_HINT)
        mid = cat.resolve_id(key)
        entry = cat.get(mid)
        vid = None
        if variant is not None:
            known = [v["id"] for v in entry.get("variants") or [] if isinstance(v, Mapping) and isinstance(v.get("id"), str)]
            want = variant.strip().lower()
            vid = variant if variant in known else next((k for k in known if k.lower() == want), None)
            if vid is None:
                raise _bad(f"{where}.variant", f"unknown variant {variant[:32]!r} of module {mid}",
                           f"variants: {', '.join(known)}" if known else f"{mid} has no variants: leave variant out")
            entry = cat.get(mid, vid)
    except BenchError:
        raise
    except Exception as e:  # a broken catalog is a server fault, never a bad request
        logger.error("circuit-bench: module catalog failed", exc_info=e)
        raise BenchError("tool_failed", f"module catalog unavailable ({type(e).__name__})", "see the Hermes log") from None
    return mid, vid, entry


def _pin_names(entry: Mapping[str, Any]) -> list[str]:
    return [p["name"] for p in entry.get("pins") or [] if isinstance(p, Mapping) and isinstance(p.get("name"), str)]


def _pins(entry: Mapping[str, Any]) -> list[dict[str, Any]]:
    return [p for p in entry.get("pins") or [] if isinstance(p, Mapping) and isinstance(p.get("name"), str)]


def _pins_hint(pins: list[dict[str, Any]]) -> str:
    """``pins: …`` with the breakout labels (modspec.pins_hint), cut at a pin boundary near 300 characters."""
    text = modspec.pins_hint(pins)
    if len(text) > 300:
        text = text[:text.rfind(", ", 0, 298)] + ", …"
    return f"pins: {text}"


def _conn(value: Any, where: str, pins: list[dict[str, Any]] | None, *, module: bool, module_id: str | None = None,
          deletes: bool = False, aliases: list[dict[str, Any]] | None = None,
          stored: frozenset[str] | set[str] = frozenset()) -> dict[str, str | None]:
    """{pin: net}. ``pins``: the module's pins (writing a module part, variant applied); None for plain parts (pins
    ``[A-Za-z0-9_+.-]{1,16}``) and for stored module parts (form only). ``deletes``: null values allowed (connect).

    With ``pins`` a key is a pin name (exact, else the one pin of that name in any case) or a breakout label
    (``modspec.resolve_pin``: SDA, VCC, MOSI ... when exactly one pin carries that signal). A label that fits several
    pins is refused, never guessed. The chip pin name is kept; each mapping goes to ``aliases`` as an assumption
    ``pin_alias``. ``stored``: the pins of the part's saved conn; a null for one of them unlinks it as written."""
    if not isinstance(value, Mapping) or len(value) > modspec.MAX_CONN:
        raise _bad(where, f"expected an object {{pin: net}} with at most {modspec.MAX_CONN} entries")
    out: dict[str, str | None] = {}
    given: dict[str, Any] = {}  # pin -> the key that named it
    found: list[dict[str, Any]] = []
    for key, net in value.items():
        pin = key
        if pins is not None and not (deletes and net is None and key in stored):
            res = modspec.resolve_pin(pins, key)
            if res["pin"] is None and res["candidates"]:
                raise _bad(where, f"{str(key)[:32]!r} fits more than one pin of {module_id} "
                                  f"({', '.join(res['candidates'])}): name the pin", _pins_hint(pins))
            if res["pin"] is None:
                raise _bad(where, f"module {module_id} has no pin {str(key)[:32]!r}", _pins_hint(pins))
            pin = res["pin"]
            if res["via"] != "name":
                info = next(p for p in pins if p["name"] == pin)
                found.append(assumption("pin_alias", f"{key} → {pin}",
                                        modspec.alias_text(str(module_id), info, key, res["via"])))
        elif module:
            _text(pin, f"{where} pin", 32)
        else:
            _text(pin, f"{where} pin", 16, pattern=_PIN_NAME_RE, hint=PLAIN_PIN_HINT)
        if pin in given:
            raise _bad(where, f"{str(given[pin])[:32]!r} and {str(key)[:32]!r} both name pin {pin} of {module_id}",
                       "give each pin once")
        given[pin] = key
        if net is None and deletes:
            out[pin] = None
            continue
        out[pin] = _text(net, f"{where}.{key}", 32, pattern=_NET_RE,
                         hint="net: [A-Za-z0-9_+.-]{1,32}; GND, 3V3, 5V, GPIO<n> or a net name like SDA0")
    if aliases is not None:
        aliases.extend(a for a in found if a not in aliases)
    return out


def _hex_addr(value: Any) -> str | None:
    if isinstance(value, int) and not isinstance(value, bool) and 0 <= value <= 0x7F:
        return f"0x{value:02x}"
    if isinstance(value, str):
        return value.strip().lower()
    return None


def _i2c_addresses(entry: Mapping[str, Any]) -> list[str]:
    """The I²C addresses of a catalog entry (``interfaces[type=i2c].addresses``: list or cited number with a list)."""
    out: list[str] = []
    for iface in entry.get("interfaces") or []:
        if not isinstance(iface, Mapping) or iface.get("type") != "i2c":
            continue
        addrs = iface.get("addresses")
        if isinstance(addrs, Mapping):
            addrs = addrs.get("value")
        for a in [*(addrs if isinstance(addrs, _SEQ) else []), iface.get("default")]:
            h = _hex_addr(a)
            if h and modspec.I2C_ADDR_RE.fullmatch(h) and h not in out:
                out.append(h)
    return out


def _address(value: Any, where: str, entry: Mapping[str, Any] | None, module_id: str | None) -> str:
    addr = _hex_addr(value)
    if addr is None or not modspec.I2C_ADDR_RE.fullmatch(addr):
        raise _bad(where, f"expected a 7-bit I²C address like 0x76, not {str(value)[:20]!r}")
    if entry is not None:
        known = _i2c_addresses(entry)
        if not known:
            raise _bad(where, f"module {module_id} has no I²C address", "leave address out")
        if addr not in known:
            raise _bad(where, f"{addr} is not an I²C address of module {module_id}", f"addresses: {', '.join(known)}")
    return addr


def _facts(value: Any, where: str) -> dict[str, Any]:
    """User facts of a breakout board (closed keys ``modspec.FACT_KEYS``), in that order."""
    if not isinstance(value, Mapping):
        raise _bad(where, "expected an object")
    extra = [k for k in value if k not in modspec.FACT_KEYS]
    if extra:
        raise _bad(where, f"unknown fact {str(extra[0])[:32]!r}", f"facts: {', '.join(modspec.FACT_KEYS)}")
    out: dict[str, Any] = {}
    for key in modspec.FACT_KEYS:
        if key not in value:
            continue
        v, w = value[key], f"{where}.{key}"
        if key == "regulator":
            choices = modspec.FACT_KEYS["regulator"] or ()
            hit = next((c for c in choices if isinstance(v, str) and v.strip().lower() == c.lower()), None)
            if hit is None:
                raise _bad(w, f"expected one of {', '.join(choices)}")
            out[key] = hit
        elif key == "pullups":
            out[key] = _pullups(v, w)
        elif key == "pullups_to":
            out[key] = _text(v, w, 32, pattern=_NET_RE, hint="module pin, net or volts: [A-Za-z0-9_+.-]{1,32}, "
                             "e.g. VDD, 3V3, 5V")
        elif key == "onboard":
            out[key] = _onboard(v, w)
        elif key == "i_max":  # the whole part (qty included), stored in A
            out[key] = _rail_value(v, w, "A", MAX_PART_A)
        else:  # level_shifter, mains
            out[key] = _bool(v, w)
    return out


def _onboard(value: Any, where: str) -> list[str]:
    """facts.onboard: the parts a breakout carries, a list of ``modspec.FACT_KEYS["onboard"]`` (stored in that
    order, no repeats; [] is allowed: the user confirmed a bare board)."""
    choices = modspec.FACT_KEYS["onboard"] or ()
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, _SEQ) or len(value) > len(choices) * 2:
        raise _bad(where, "expected a list", f"onboard: any of {', '.join(choices)}")
    got = set()
    for v in value:
        hit = next((c for c in choices if isinstance(v, str) and v.strip().lower() == c), None)
        if hit is None:
            raise _bad(where, f"unknown onboard part {str(v)[:32]!r}", f"onboard: any of {', '.join(choices)}")
        got.add(hit)
    return [c for c in choices if c in got]


def _pullups(value: Any, where: str) -> str:
    hint = "none, unknown or a resistance such as 10k or 4.7 kΩ"
    text = _text(value, where, 16, hint=hint).strip()
    if text.lower() in ("none", "unknown"):
        return text.lower()
    try:
        ohm, unit = units.parse(text)
    except BenchError:
        raise _bad(where, f"cannot read {text!r}", hint) from None
    if unit not in (None, "Ω") or not 0 < ohm <= MAX_PULLUP_OHM:
        raise _bad(where, f"expected a resistance above 0 Ω and up to 10 MΩ, not {text!r}", hint)
    return text


def _rail_value(value: Any, where: str, unit: str, hi: float) -> float | int:
    if isinstance(value, str):
        try:
            value = units.parse_quantity(value, unit)
        except BenchError as e:
            raise _bad(where, e.message, e.hint) from None
    v = _num(value, where, 0, hi)
    if v <= 0:
        raise _bad(where, f"expected a value above 0 {unit} and up to {hi:g} {unit}")
    return v


def _rails(value: Any, where: str) -> dict[str, float | int]:
    """options.rails {net: V}: extra supply rails (0 < V <= modspec.MAX_RAIL_V); GND, 3V3 and 5V are fixed.
    Null entries are left out."""
    if not isinstance(value, Mapping) or len(value) > MAX_RAILS:
        raise _bad(where, f"expected an object {{net: volts}} with at most {MAX_RAILS} entries")
    fixed = {k.lower() for k in modspec.FIXED_RAILS}
    out: dict[str, float | int] = {}
    for name, v in value.items():
        _text(name, f"{where} name", 32, pattern=_NET_RE, hint="net: [A-Za-z0-9_+.-]{1,32}, e.g. VMOT")
        if name.lower() in fixed:
            raise _bad(f"{where}.{name}", f"{name} is a fixed rail ({', '.join(modspec.FIXED_RAILS)})",
                       "name only extra rails, e.g. VMOT, VBAT or 1V8")
        if v is not None:
            out[name] = _rail_value(v, f"{where}.{name}", "V", modspec.MAX_RAIL_V)
    return out


def _rail_limits(value: Any, where: str, rails: Mapping[str, Any]) -> dict[str, float | int]:
    """options.rail_limits {net: A} (0 < A <= MAX_RAIL_A) for 3V3, 5V or a net of options.rails."""
    if not isinstance(value, Mapping) or len(value) > MAX_RAILS:
        raise _bad(where, f"expected an object {{net: amps}} with at most {MAX_RAILS} entries")
    out: dict[str, float | int] = {}
    for name, v in value.items():
        _text(name, f"{where} name", 32, pattern=_NET_RE)
        if name not in ("3V3", "5V") and name not in rails:
            raise _bad(f"{where}.{name}", f"{name} is not a rail", "use 3V3, 5V or a net of rails (set_rails rails)")
        if v is not None:
            out[name] = _rail_value(v, f"{where}.{name}", "A", MAX_RAIL_A)
    return out


# --------------------------------------------------------------------------------------------- schema check

def _same(normalised: Any, stored: Any, where: str) -> None:
    if normalised != stored:
        raise _bad(where, "not in the stored form")


def _unique(items: list[dict[str, Any]], key: str, where: str) -> None:
    seen = [i[key] for i in items]
    dup = next((k for k in seen if seen.count(k) > 1), None)
    if dup is not None:
        raise _bad(where, f"{key} {dup!r} appears twice")


def _check_list(value: Any, where: str, max_items: int) -> list[Any]:
    if not isinstance(value, _list) or len(value) > max_items:
        raise _bad(where, f"expected a list of at most {max_items} entries")
    return value


def _check_stored(p: Any) -> None:
    """Raise BenchError(invalid_args) at the first deviation from the stored form of schema 1."""
    if not isinstance(p, dict):
        raise _bad("project", "expected an object")
    missing = [k for k in TOP_KEYS if k not in p]
    extra = [k for k in p if k not in TOP_KEYS]
    if missing or extra:
        raise _bad("project", f"missing field {missing[0]!r}" if missing else f"unknown field {str(extra[0])!r}")
    if p["schema"] != SCHEMA or isinstance(p["schema"], bool):
        raise _bad("schema", f"expected {SCHEMA}")
    _check_id(p["id"])
    _int(p["rev"], "rev", 1, 2**53)
    _text(p["title"], "title", TITLE_MAX_CHARS)
    _bool(p["simulated"], "simulated")
    _iso(p["created"], "created")
    _iso(p["updated"], "updated")

    b = p["board"]
    if not isinstance(b, dict) or sorted(b) != sorted(BOARD_KEYS):
        raise _bad("board", f"expected the fields {', '.join(BOARD_KEYS)}")
    chip = pins.normalize_chip(b["chip"])
    if chip != b["chip"]:
        raise _bad("board.chip", "not in the stored form")
    vid, _ = _variant(chip, b["variant"])
    _same(vid, b["variant"], "board.variant")
    _text(b["module"], "board.module", 32, none=True)
    _same(_devkit(chip, b["devkit"]), b["devkit"], "board.devkit")
    if b["detected"] is not None:
        _same(_detected(b["detected"], "board.detected"), b["detected"], "board.detected")

    o = p["options"]
    if not isinstance(o, dict) or sorted(k for k in o if k not in OPTION_OPTIONAL) != sorted(DEFAULT_OPTIONS):
        raise _bad("options", f"expected the fields {', '.join(DEFAULT_OPTIONS)} (optional: {', '.join(OPTION_OPTIONAL)})")
    _bool(o["wifi"], "options.wifi")
    _text(o["framework"], "options.framework", 32, pattern=_TYPE_RE)
    _num(o["logic_v"], "options.logic_v", 0.5, 5.5)
    for key in OPTION_OPTIONAL:  # stored only when not empty
        if key in o and (not isinstance(o[key], dict) or not o[key]):
            raise _bad(f"options.{key}", "expected a non-empty object")
    if "rails" in o:
        _same(_rails(o["rails"], "options.rails"), o["rails"], "options.rails")
    if "rail_limits" in o:
        _same(_rail_limits(o["rail_limits"], "options.rail_limits", o.get("rails") or {}), o["rail_limits"],
              "options.rail_limits")

    for i, a in enumerate(_check_list(p["assignments"], "assignments", MAX_ASSIGNMENTS)):
        w = f"assignments[{i}]"
        if not isinstance(a, dict) or sorted(a) != sorted(ASSIGNMENT_KEYS):
            raise _bad(w, f"expected the fields {', '.join(ASSIGNMENT_KEYS)}")
        if a["updated_by"] not in BY:
            raise _bad(f"{w}.updated_by", "expected agent or ui")
        _same(_assignment({k: a[k] for k in OPS["assign"]}, w, a["updated_by"]) | {k: a[k] for k in ("verdict", "rule_ids")},
              a, w)
        if a["verdict"] not in pins.VERDICTS:
            raise _bad(f"{w}.verdict", f"expected one of {', '.join(pins.VERDICTS)}")
        rule_ids = _check_list(a["rule_ids"], f"{w}.rule_ids", 32)
        for r in rule_ids:
            _text(r, f"{w}.rule_ids[]", 64)
    _unique(p["assignments"], "role", "assignments")

    for i, x in enumerate(_check_list(p["parts"], "parts", MAX_PARTS)):
        _same(_part(x, f"parts[{i}]", stored=True), x, f"parts[{i}]")
    _unique(p["parts"], "ref", "parts")
    for i, x in enumerate(_check_list(p["calcs"], "calcs", MAX_CALCS)):
        _same(_calc(x, f"calcs[{i}]"), x, f"calcs[{i}]")
    _unique(p["calcs"], "id", "calcs")
    for i, x in enumerate(_check_list(p["circuits"], "circuits", MAX_CIRCUITS)):
        _same(_circuit(x, f"circuits[{i}]"), x, f"circuits[{i}]")
    _unique(p["circuits"], "id", "circuits")

    s = p["solder"]
    if not isinstance(s, dict) or sorted(s) != ["done", "steps"]:
        raise _bad("solder", "expected the fields steps, done")
    for i, x in enumerate(_check_list(s["steps"], "solder.steps", MAX_STEPS)):
        _same(_step(x, f"solder.steps[{i}]"), x, f"solder.steps[{i}]")
    _unique(s["steps"], "id", "solder.steps")
    ids = [x["id"] for x in s["steps"]]
    done = _check_list(s["done"], "solder.done", MAX_STEPS)
    if any(d not in ids for d in done) or len(set(done)) != len(done):
        raise _bad("solder.done", "expected unique ids of steps in solder.steps")

    fw = p["firmware"]
    if not isinstance(fw, dict) or sorted(fw) != ["dir", "env", "last_build", "last_flash"]:
        raise _bad("firmware", "expected the fields dir, env, last_build, last_flash")
    _text(fw["dir"], "firmware.dir", 1024, none=True)
    _text(fw["env"], "firmware.env", 64, none=True, pattern=_ENV_RE)
    if fw["last_build"] is not None:
        _same(_build(fw["last_build"], "firmware.last_build"), fw["last_build"], "firmware.last_build")
    if fw["last_flash"] is not None:
        _same(_flash(fw["last_flash"], "firmware.last_flash"), fw["last_flash"], "firmware.last_flash")

    d = p["debug"]
    if not isinstance(d, dict) or sorted(d) != ["last_panic"]:
        raise _bad("debug", "expected the field last_panic")
    _same(_panic(d["last_panic"], "debug.last_panic"), d["last_panic"], "debug.last_panic")

    for i, x in enumerate(_check_list(p["notes"], "notes", MAX_NOTES)):
        _same(_note(x, f"notes[{i}]"), x, f"notes[{i}]")


def validate(project: Any) -> list[str]:
    """Problems with a project object against schema 1 (empty list = valid). Stops at the first problem."""
    try:
        _check_stored(project)
    except BenchError as e:
        return [e.message]
    except Exception as e:  # noqa: BLE001 - a malformed object must never crash the check
        return [f"project: unexpected structure ({type(e).__name__})"]
    return []


# --------------------------------------------------------------------------------------------- files

def _projects_root() -> Path:
    root = storage.data_dir() / "projects"
    root.mkdir(mode=0o700, exist_ok=True)
    return root


def path(id: str) -> Path:  # contract name
    """Folder of project ``id`` (``data_dir()/projects/<id>``); not created, the project need not exist."""
    return _projects_root() / _check_id(id)


def artifacts_dir(id: str) -> Path:  # contract name
    """``projects/<id>/artifacts/`` (0700), created on demand; ``project_not_found`` if the project does not exist."""
    pdir = path(id)
    if not (pdir / "project.json").is_file():
        raise _not_found(id)
    adir = pdir / "artifacts"
    adir.mkdir(mode=0o700, exist_ok=True)
    return adir


@contextlib.contextmanager
def _locked(pdir: Path) -> Iterator[None]:
    """Exclusive flock on ``<pdir>/.lock`` (0600, kept forever); waits up to LOCK_TIMEOUT_S, then ``timeout``."""
    fd = os.open(pdir / ".lock", os.O_RDWR | os.O_CREAT | os.O_CLOEXEC, 0o600)
    try:
        deadline = time.monotonic() + LOCK_TIMEOUT_S
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise BenchError("timeout", f"project {pdir.name!r} is locked by another writer",
                                     "retry in a moment") from None
                time.sleep(0.005)
        yield
    finally:
        os.close(fd)  # releases the lock


def _read(pdir: Path) -> dict[str, Any]:
    pid = pdir.name
    try:
        text = (pdir / "project.json").read_text(encoding="utf-8")
    except FileNotFoundError:
        raise _not_found(pid) from None
    except OSError as e:
        raise BenchError("project_not_found", f"project {pid!r} is unreadable ({e.strerror})",
                         "check the permissions of the project folder") from None
    try:
        obj = json.loads(text)
    except ValueError:
        obj = None
    problems = ["project.json is not valid JSON"] if obj is None else validate(obj)
    if not problems and obj["id"] != pid:
        problems = [f"id {obj['id']!r} does not match its folder"]
    if problems:
        raise BenchError("project_damaged", f"project {pid!r} is damaged ({problems[0]})",
                         "restore project.json from a backup or remove the project folder")
    return obj


def _fsync_dir(folder: Path) -> None:
    try:
        fd = os.open(folder, os.O_RDONLY | os.O_DIRECTORY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


def _write(pdir: Path, obj: dict[str, Any]) -> None:
    problems = validate(obj)
    if problems:  # defensive: never store what get() would refuse
        raise BenchError("invalid_args", f"project would be invalid ({problems[0]})")
    data = json.dumps(obj, ensure_ascii=False, indent=1) + "\n"
    if len(data.encode("utf-8")) > MAX_PROJECT_BYTES:
        raise BenchError("invalid_args", f"project would exceed {MAX_PROJECT_BYTES} bytes",
                         "remove notes, calculations or circuits")
    fd, tmp = tempfile.mkstemp(prefix=".project.", suffix=".tmp", dir=pdir)  # 0600
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, pdir / "project.json")
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise
    _fsync_dir(pdir)


def _emit_updated(pid: str, rev: int, changed: list[str], by: str) -> None:
    try:
        events.emit("project.updated", {"id": pid, "rev": rev, "changed": changed, "by": by})
    except Exception as e:  # noqa: BLE001 - the write already happened; an event never undoes it
        logger.warning("circuit-bench: project.updated for %s not sent (%s)", pid, type(e).__name__)


def _internal(action: str, e: Exception) -> dict[str, Any]:
    logger.error("circuit-bench: %s failed", action, exc_info=e)
    return fail(action, "tool_failed", f"project store failed ({type(e).__name__})", "see the Hermes log")


# --------------------------------------------------------------------------------------------- summaries

def _pin_text(assignments: list[dict[str, Any]]) -> str:
    if not assignments:
        return "no pins assigned"
    n = {v: sum(a["verdict"] == v for a in assignments) for v in pins.VERDICTS}
    out = f"{n['ok']} pins ok" if n["ok"] != 1 else "1 pin ok"
    for v in ("caution", "blocked"):
        if n[v]:
            out += f", {n[v]} {v}"
    return out


def _summary(p: dict[str, Any]) -> str:
    bits = [_pin_text(p["assignments"])]
    steps, done = p["solder"]["steps"], p["solder"]["done"]
    if steps:
        bits.append(f"solder {len(done)}/{len(steps)}")
    build = p["firmware"]["last_build"]
    if build is not None:
        bits.append("last build ok" if build["ok"] else "last build failed")
    panic = p["debug"]["last_panic"]
    if panic is not None:
        bits.append(f"last panic {panic.get('reason') or panic.get('kind')}")
    label = _board_label(p["board"]) + (", simulated" if p["simulated"] else "")
    return f"{p['title']} ({label}): {', '.join(bits)}."


def _list_entry(p: dict[str, Any]) -> dict[str, Any]:
    b = p["board"]
    return {"id": p["id"], "title": p["title"], "chip": b["chip"], "variant": b["variant"], "devkit": b["devkit"],
            "rev": p["rev"], "updated": p["updated"], "simulated": p["simulated"]}


def _variant_notes(board: Mapping[str, Any]) -> list[dict[str, Any]]:
    _, variants = _chip_info(board["chip"])
    if variants and board["variant"] is None:
        return [warning("variant_unknown", "caution", "Module variant not set: pins that depend on the PSRAM type are "
                        f"not checked. Set it with set_board (known: {', '.join(variants)}).")]
    return []


# --------------------------------------------------------------------------------------------- actions

def create(id: str, title: str, chip: str, variant: str | None = None, devkit: str | None = None, *,
           simulated: bool = False, by: str = "agent") -> dict[str, Any]:
    """Action project.create: a new project at rev 1 (``project_conflict`` if the id exists).

    Options start as Wi-Fi on (the stricter pin rules apply), Arduino, 3.3 V logic; change Wi-Fi with set_board."""
    action = "project.create"
    try:
        pid = _check_id(id)
        if not isinstance(title, str):
            raise _bad("title", "expected text")
        title_ = _text(title.strip(), "title", TITLE_MAX_CHARS)
        chip_ = pins.normalize_chip(chip)
        variant_, module = _variant(chip_, variant)
        devkit_ = _devkit(chip_, devkit)
        sim = _bool(simulated, "simulated")
        if by not in ("agent", "ui"):
            raise _bad("by", "expected 'agent' or 'ui'")
        now = _now()
        project = {
            "schema": SCHEMA, "id": pid, "rev": 1, "title": title_, "simulated": sim, "created": now, "updated": now,
            "board": {"chip": chip_, "module": module, "variant": variant_, "devkit": devkit_, "detected": None},
            "options": dict(DEFAULT_OPTIONS), "assignments": [], "parts": [], "calcs": [], "circuits": [],
            "solder": {"steps": [], "done": []},
            "firmware": {"dir": None, "env": None, "last_build": None, "last_flash": None},
            "debug": {"last_panic": None}, "notes": [],
        }
        pdir = path(pid)
        pdir.mkdir(mode=0o700, exist_ok=True)
        with _locked(pdir):
            if (pdir / "project.json").exists():
                raise BenchError("project_conflict", f"bench project {pid!r} already exists",
                                 "open it with project.get or choose another id")
            _write(pdir, project)
        (pdir / "artifacts").mkdir(mode=0o700, exist_ok=True)
    except BenchError as e:
        return from_error(action, e)
    except Exception as e:  # noqa: BLE001 - an action returns an envelope, never an exception
        return _internal(action, e)
    _emit_updated(pid, 1, ["created"], by)
    summary = f"Created bench project {pid!r}: {_summary(project)}"
    return envelope(action, summary, {"project": project, "rev": 1}, warnings=_variant_notes(project["board"]),
                    assumptions=[assumption("wifi", "on", "not given; Wi-Fi on applies the stricter pin rules "
                                            "(change with set_board)")], simulated=sim)


def get(id: str) -> dict[str, Any]:  # contract name
    """Action project.get: ``result = {"project", "rev"}``."""
    action = "project.get"
    try:
        project = _read(path(id))
    except BenchError as e:
        return from_error(action, e)
    except Exception as e:  # noqa: BLE001
        return _internal(action, e)
    return envelope(action, _summary(project), {"project": project, "rev": project["rev"]},
                    warnings=_variant_notes(project["board"]), simulated=project["simulated"])


def list_projects() -> dict[str, Any]:
    """Action project.list: ``result = {"projects": [{id, title, chip, variant, devkit, rev, updated, simulated}]}``
    sorted by id. Damaged projects are skipped with a warning ``project_damaged``."""
    action = "project.list"
    entries: list[dict[str, Any]] = []
    warns: list[dict[str, Any]] = []
    try:
        root = _projects_root()
        for pdir in sorted(root.iterdir()):
            if not pdir.is_dir() or not _ID_RE.fullmatch(pdir.name) or not (pdir / "project.json").exists():
                continue
            try:
                entries.append(_list_entry(_read(pdir)))
            except BenchError as e:
                warns.append(warning("project_damaged", "caution", f"{e.message}; skipped"))
    except BenchError as e:
        return from_error(action, e)
    except Exception as e:  # noqa: BLE001
        return _internal(action, e)
    n = len(entries)
    return envelope(action, f"{n} bench project{'' if n == 1 else 's'}.", {"projects": entries}, warnings=warns)


class _Update:
    """Applies the ops of one update to a deep copy of the project."""

    def __init__(self, project: dict[str, Any], by: str):
        self.before = project
        self.p = copy.deepcopy(project)
        self.by = by
        self.now = _now()
        self.recompute = False
        self.touched: set[str] = set()  # roles (re)assigned in this update
        self.aliases: list[dict[str, Any]] = []  # pin_alias assumptions: breakout labels mapped to chip pins

    # ---- board
    def set_board(self, op: dict[str, Any]) -> None:
        if not op:
            raise _bad("set_board", "give at least one of chip, variant, devkit, wifi")
        cur = self.p["board"]
        chip = pins.normalize_chip(op["chip"]) if "chip" in op else cur["chip"]
        changed_chip = chip != cur["chip"]
        variant = op["variant"] if "variant" in op else (None if changed_chip else cur["variant"])
        devkit = op["devkit"] if "devkit" in op else cur["devkit"]
        if "devkit" not in op and changed_chip and devkit is not None and boards.load(devkit)["chip"] != chip:
            devkit = None  # the old devkit carries the old chip
        vid, module = _variant(chip, variant)
        self.p["board"] = {"chip": chip, "module": module, "variant": vid, "devkit": _devkit(chip, devkit),
                           "detected": None if changed_chip else cur["detected"]}  # another chip: detect again
        if changed_chip and self.p["firmware"]["last_build"] is not None:
            self.p["firmware"]["last_build"] = None  # a build for the old chip must never reach the new one
        if "wifi" in op:
            self.p["options"]["wifi"] = _bool(op["wifi"], "set_board.wifi")
        self.recompute = True

    def set_detected(self, op: dict[str, Any]) -> None:
        self.p["board"]["detected"] = _detected(op)

    # ---- pins
    def assign(self, op: dict[str, Any]) -> None:
        entry = _assignment(op, "assign", self.by)
        items = self.p["assignments"]
        idx = next((i for i, a in enumerate(items) if a["role"] == entry["role"]), None)
        if idx is None:
            if len(items) >= MAX_ASSIGNMENTS:
                raise _bad("assign", f"at most {MAX_ASSIGNMENTS} assignments")
            items.append(entry)
        else:
            items[idx] = entry
        self.touched.add(entry["role"])
        self.recompute = True

    def unassign(self, op: dict[str, Any]) -> None:
        role = _text(op.get("role"), "unassign.role", 24, pattern=_ROLE_RE)
        items = self.p["assignments"]
        if not any(a["role"] == role for a in items):
            raise _bad("unassign", f"no assignment with role {role}")
        self.p["assignments"] = [a for a in items if a["role"] != role]
        self.touched.discard(role)
        self.recompute = True

    # ---- parts, calculations, circuits
    def add_parts(self, op: dict[str, Any]) -> None:
        parts = op.get("parts")
        if not isinstance(parts, _SEQ) or not parts or len(parts) > MAX_PARTS:
            raise _bad("add_parts.parts", f"expected a list of 1 to {MAX_PARTS} parts")
        new = [_part(x, f"add_parts.parts[{i}]", aliases=self.aliases) for i, x in enumerate(parts)]
        _unique(new, "ref", "add_parts.parts")
        items = self.p["parts"]
        for part in new:
            idx = next((i for i, x in enumerate(items) if x["ref"] == part["ref"]), None)
            if idx is None:
                items.append(part)
            else:
                items[idx] = part
        if len(items) > MAX_PARTS:
            raise _bad("add_parts", f"at most {MAX_PARTS} parts per project")

    # ---- module instances
    def add_module(self, op: dict[str, Any]) -> None:
        """A module instance as a new part: ref U<n> (one above the highest U number) unless given (must be free),
        kind and value (short title: the part number) from the catalog, package none."""
        if op.get("module") is None:
            raise _bad("add_module", "missing field 'module'", MODULE_HINT)
        items = self.p["parts"]
        if len(items) >= MAX_PARTS:
            raise _bad("add_module", f"at most {MAX_PARTS} parts per project")
        have = {x["ref"] for x in items}
        if op.get("ref") is not None:
            ref = _text(op["ref"], "add_module.ref", 16, hint="references look like U1, U2").strip().upper()
            if not _REF_RE.fullmatch(ref):
                raise _bad("add_module.ref", f"bad reference {ref!r}", "references look like U1, U2")
            if ref in have:
                raise _bad("add_module.ref", f"{ref} is already used in this project",
                           "pick a free reference or leave ref out (the next U<n> is chosen)")
        else:
            ref = f"U{max((int(m.group(1)) for r in have if (m := _U_REF_RE.match(r))), default=0) + 1}"
        mid, vid, entry = _module_entry(op["module"], op.get("variant"), "add_module")
        kind = entry.get("kind") if entry.get("kind") in modspec.KINDS else "module"
        part: dict[str, Any] = {"ref": ref, "kind": kind, "value": _short_title(entry.get("title"), mid), "module": mid}
        if vid is not None:
            part["variant"] = vid
        part.update({k: op[k] for k in ("qty", "conn", "address", "facts") if op.get(k) is not None})
        items.append(_part(part, "add_module", aliases=self.aliases))

    def connect(self, op: dict[str, Any]) -> None:
        """Change a part in place: merge {pin: net} into its conn (null removes a pin; a pin that is not connected:
        no change); for a module part also ``variant`` (catalog variant; every connected pin must exist in it),
        ``address`` (checked like add_module; null removes it), ``facts`` (merged per key; null removes a key) and
        ``qty`` (any part). At least one of them."""
        ref = _text(op.get("ref"), "connect.ref", 16, hint="references look like U1, R3").strip().upper()
        items = self.p["parts"]
        idx = next((i for i, x in enumerate(items) if x["ref"] == ref), None)
        if idx is None:
            raise _bad("connect", f"no part {ref} in this project",
                       f"parts: {', '.join(sorted(x['ref'] for x in items)) or 'none'}")
        part = items[idx]
        if not any(k in op for k in ("conn", "address", "facts", "variant", "qty")):
            raise _bad("connect", "give conn, address, facts, variant or qty",
                       "conn: {pin: net} (null removes a pin), e.g. {\"SDA\": \"GPIO8\"}")
        is_mod = "module" in part
        if not is_mod:
            lone = next((k for k in ("variant", "address", "facts") if op.get(k) is not None), None)
            if lone is not None:
                raise _bad(f"connect.{lone}", f"{ref} is not a module part", "only module parts take variant, "
                           "address and facts; plain parts take conn and qty")
        new = dict(part)
        entry: Mapping[str, Any] | None = None
        if is_mod and (op.get("variant") is not None or op.get("address") is not None or (
                isinstance(op.get("conn"), Mapping) and any(v is not None for v in op["conn"].values()))):
            vid = op.get("variant") if op.get("variant") is not None else part.get("variant")
            _, vid, entry = _module_entry(part["module"], vid, "connect")
            if vid is not None:
                new["variant"] = vid
        elif is_mod and isinstance(op.get("conn"), Mapping) and op["conn"]:
            # only unlinks: the catalog maps labels (SDA -> SDI); a module that left it still unlinks saved pins
            with contextlib.suppress(BenchError):
                _, _, entry = _module_entry(part["module"], part.get("variant"), "connect")
        if "conn" in op:
            conn = op.get("conn")
            if not isinstance(conn, Mapping) or not conn:
                raise _bad("connect.conn", "expected an object {pin: net} with at least one entry (null removes a pin)")
            changes = _conn(conn, "connect.conn", _pins(entry) if entry is not None else None, module=is_mod,
                            module_id=part.get("module"), deletes=True, aliases=self.aliases,
                            stored=set(part.get("conn") or {}))
            merged = dict(part.get("conn") or {})
            for pin, net in changes.items():
                if net is None:
                    merged.pop(pin, None)
                else:
                    merged[pin] = net
            if len(merged) > modspec.MAX_CONN:
                raise _bad("connect.conn", f"{ref} would have more than {modspec.MAX_CONN} connections")
            new["conn"] = merged
        if op.get("variant") is not None and entry is not None:
            names = set(_pin_names(entry))
            gone = [pin for pin in new.get("conn") or {} if pin not in names]
            if gone:
                raise _bad("connect.variant", f"variant {new['variant']} of {part['module']} has no pin {gone[0]!r}",
                           "unlink the pin first (conn {pin: null})")
        if "address" in op:
            if op["address"] is None:
                new.pop("address", None)
            else:
                new["address"] = _address(op["address"], "connect.address", entry, part.get("module"))
        elif "address" in new and entry is not None and op.get("variant") is not None:
            new["address"] = _address(new["address"], "connect.address", entry, part.get("module"))
        if op.get("facts") is not None:
            if not isinstance(op["facts"], Mapping):
                raise _bad("connect.facts", "expected an object")
            facts = dict(part.get("facts") or {})
            _facts({k: v for k, v in op["facts"].items() if v is not None or k not in modspec.FACT_KEYS},
                   "connect.facts")  # checks the values and refuses unknown keys (even with null)
            for key, v in op["facts"].items():
                if v is None:
                    facts.pop(key, None)
            facts.update(_facts({k: v for k, v in op["facts"].items() if v is not None}, "connect.facts"))
            new["facts"] = {k: facts[k] for k in modspec.FACT_KEYS if k in facts}
        if "qty" in op:
            if op["qty"] is None:
                new.pop("qty", None)
            else:
                new["qty"] = _int(op["qty"], "connect.qty", 1, 999)
        items[idx] = {k: new[k] for k in PART_ALL_FIELDS if k in new and not (k in ("conn", "facts") and not new[k])}

    def set_rails(self, op: dict[str, Any]) -> None:
        """Replace options.rails and/or options.rail_limits; null or {} removes them. Limits of rails that are gone
        are dropped when only rails is given."""
        if not op:
            raise _bad("set_rails", "give rails and/or rail_limits (null removes them)")
        o = self.p["options"]
        rails = o.get("rails") or {}
        if "rails" in op:
            rails = {} if op["rails"] is None else _rails(op["rails"], "set_rails.rails")
        limits = o.get("rail_limits") or {}
        if "rail_limits" in op:
            limits = {} if op["rail_limits"] is None else _rail_limits(op["rail_limits"], "set_rails.rail_limits", rails)
        else:
            limits = {k: v for k, v in limits.items() if k in ("3V3", "5V") or k in rails}
        new = {k: v for k, v in o.items() if k not in OPTION_OPTIONAL}
        if rails:
            new["rails"] = rails
        if limits:
            new["rail_limits"] = limits
        self.p["options"] = new

    def _replace_by_id(self, key: str, obj: dict[str, Any], limit: int) -> None:
        items = self.p[key]
        idx = next((i for i, x in enumerate(items) if x["id"] == obj["id"]), None)
        if idx is None:
            if len(items) >= limit:
                raise _bad(key, f"at most {limit} entries per project")
            items.append(obj)
        else:
            items[idx] = obj

    def remove_parts(self, op: dict[str, Any]) -> None:
        """Drop parts by reference (R1, LED3 ...). Calculations, circuits and solder steps stay; the Bench shows the
        solder plan as out of date (step refs no longer in the parts) until it is re-planned."""
        refs = op.get("refs")
        if not isinstance(refs, _SEQ) or not refs or len(refs) > MAX_PARTS:
            raise _bad("remove_parts.refs", f"expected a list of 1 to {MAX_PARTS} references")
        wanted = []
        for i, r in enumerate(refs):
            ref = _text(r, f"remove_parts.refs[{i}]", 16, hint="references look like R1, C2, LED3, SW1").strip().upper()
            if ref not in wanted:
                wanted.append(ref)
        have = {x["ref"] for x in self.p["parts"]}
        missing = [r for r in wanted if r not in have]
        if missing:
            known = ", ".join(sorted(have)) or "none"
            raise _bad("remove_parts", f"no part {', '.join(missing)} in this project", f"parts: {known}")
        self.p["parts"] = [x for x in self.p["parts"] if x["ref"] not in wanted]

    def add_calc(self, op: dict[str, Any]) -> None:
        self._replace_by_id("calcs", _calc(op.get("calc")), MAX_CALCS)

    def add_circuit(self, op: dict[str, Any]) -> None:
        self._replace_by_id("circuits", _circuit(op.get("circuit")), MAX_CIRCUITS)

    # ---- solder
    def set_solder_plan(self, op: dict[str, Any]) -> None:
        steps = op.get("steps")
        if not isinstance(steps, _SEQ) or len(steps) > MAX_STEPS:
            raise _bad("set_solder_plan.steps", f"expected a list of at most {MAX_STEPS} steps")
        new = [_step(x, f"set_solder_plan.steps[{i}]") for i, x in enumerate(steps)]
        _unique(new, "id", "set_solder_plan.steps")
        old_done = set(self.p["solder"]["done"])
        self.p["solder"] = {"steps": new, "done": [s["id"] for s in new if s["id"] in old_done]}

    def solder_done(self, op: dict[str, Any]) -> None:
        sid = _text(op.get("step_id"), "solder_done.step_id", 10, pattern=_STEP_ID_RE,
                    hint="use an id from solder.steps[].id")
        done = _bool(op.get("done"), "solder_done.done")
        ids = [s["id"] for s in self.p["solder"]["steps"]]
        if sid not in ids:
            raise _bad("solder_done", f"no solder step {sid}", "set the solder plan first")
        marked = set(self.p["solder"]["done"])
        marked = marked | {sid} if done else marked - {sid}
        self.p["solder"]["done"] = [i for i in ids if i in marked]

    # ---- firmware, debug
    def set_firmware(self, op: dict[str, Any]) -> None:
        raw = _text(op.get("dir"), "set_firmware.dir", 1024)
        folder = Path(raw).expanduser()
        if not folder.is_absolute():
            raise _bad("set_firmware.dir", "expected an absolute path")
        folder = folder.resolve()
        if folder == PACKAGE_DIR or folder.is_relative_to(PACKAGE_DIR):
            raise _bad("set_firmware.dir", "points into the plugin package",
                       "copy the example into the project folder first (projects/<id>/firmware/)")
        if folder.parent == folder or folder in _home_dirs():
            raise _bad("set_firmware.dir", f"{folder} is the file system root or a home folder, not a firmware folder",
                       "name the PlatformIO project folder (the one with platformio.ini)")
        if not folder.is_dir():
            raise _bad("set_firmware.dir", f"{folder} is not a folder")
        if not (folder / "platformio.ini").is_file():
            raise _bad("set_firmware.dir", f"{folder} has no platformio.ini",
                       "name the PlatformIO project folder (the one with platformio.ini)")
        env = _text(op.get("env"), "set_firmware.env", 64, pattern=_ENV_RE, hint="use the [env:<name>] from platformio.ini")
        fw = self.p["firmware"]
        if (fw["dir"], fw["env"]) != (str(folder), env):
            fw["last_build"] = None  # a build of another folder or env is not this firmware
        fw["dir"], fw["env"] = str(folder), env

    def set_build(self, op: dict[str, Any]) -> None:
        self.p["firmware"]["last_build"] = _build(op)

    def set_flash(self, op: dict[str, Any]) -> None:
        self.p["firmware"]["last_flash"] = _flash(op)

    def set_debug(self, op: dict[str, Any]) -> None:
        if "last_panic" not in op:
            raise _bad("set_debug", "missing field 'last_panic'")
        self.p["debug"]["last_panic"] = _panic(op["last_panic"])

    def note(self, op: dict[str, Any]) -> None:
        text = op.get("text")
        text = _text(text.strip() if isinstance(text, str) else text, "note.text", NOTE_MAX_CHARS, multiline=True)
        if len(self.p["notes"]) >= MAX_NOTES:
            raise _bad("note", f"at most {MAX_NOTES} notes per project")
        self.p["notes"].append({"text": text, "at": self.now, "by": self.by})

    # ---- verdicts
    def verdicts(self) -> tuple[list[dict[str, Any]], list[str]]:
        """Recompute every verdict with pins.check; warnings (+ source ids) for new or changed non-ok verdicts."""
        items = self.p["assignments"]
        if not self.recompute or not items:
            return [], []
        b = self.p["board"]
        res = pins.check(b["chip"], [{k: a.get(k) for k in ("role", "mode", "pin", "net")} for a in items],
                         variant=b["variant"], wifi=self.p["options"]["wifi"], devkit=b["devkit"])
        if not res["ok"]:
            err = res["error"]
            raise BenchError(err["code"], f"pin check: {err['message']}", err.get("hint"))
        before = {a["role"]: (a["verdict"], a["rule_ids"]) for a in self.before["assignments"]}
        warns: list[dict[str, Any]] = []
        ids: list[str] = []
        for a, r in zip(items, res["result"]["pins"], strict=True):
            a["verdict"], a["rule_ids"] = r["verdict"], _list(r["rule_ids"])
            fresh = a["role"] in self.touched or before.get(a["role"]) != (a["verdict"], a["rule_ids"])
            if a["verdict"] == "ok" or not fresh:
                continue
            reasons = sorted(r["reasons"], key=lambda x: {"blocked": 0, "caution": 1}.get(x["severity"], 2))
            src = [x["source_id"] for x in reasons if x.get("source_id")]
            main = reasons[0]["message"] if reasons else ""
            warns.append(warning(f"pin_{a['verdict']}", "danger" if a["verdict"] == "blocked" else "caution",
                                 f"{a['role']} on GPIO{a['pin']} is {a['verdict']}: {main}".rstrip(": "), src))
            ids += src
        return warns, ids


def update(id: str, expected_rev: int, ops: Any, *, by: str, trusted: bool = False) -> dict[str, Any]:  # contract name
    """Action project.update: apply ``ops`` (all or nothing) if the project is at ``expected_rev``.

    ``result = {"rev", "project", "changed": [top-level fields that changed]}``; ``by`` is ``agent`` or ``ui``.
    ``trusted``: internal, only for server-side producers of results (``SERVER_OPS``: set_detected, set_build,
    set_flash, set_debug); without it those ops are refused with ``invalid_args``."""
    action = "project.update"
    conflict_rev: int | None = None
    try:
        pid = _check_id(id)
        if by not in BY:
            raise BenchError("invalid_args", f"by must be agent or ui, not {str(by)[:20]!r}")
        if isinstance(expected_rev, bool) or not isinstance(expected_rev, int) or expected_rev < 1:
            raise BenchError("invalid_args", "expected_rev must be the project's rev (a whole number >= 1)",
                             "read it with project.get")
        if not isinstance(ops, _SEQ) or not ops or len(ops) > MAX_OPS:
            raise BenchError("invalid_args", f"ops must be a list of 1 to {MAX_OPS} operations",
                             f"operations: {', '.join(OPS)}")
        checked: list[tuple[str, dict[str, Any]]] = []
        for i, op in enumerate(ops):
            name = op.get("op") if isinstance(op, Mapping) else None
            if not isinstance(name, str) or name not in OPS:
                raise BenchError("invalid_args", f"ops[{i}]: unknown operation {str(name)[:30]!r}",
                                 f"operations: {', '.join(OPS)}")
            if name in SERVER_OPS and trusted is not True:
                raise BenchError("invalid_args", f"ops[{i}]: {name} is written by Circuit Bench itself, not by a client",
                                 "run the action instead (board detect, build, flash or crash decode)")
            fields = {k: v for k, v in op.items() if k != "op"}
            checked.append((name, fields if name in _RESULT_OPS else _fields(fields, name, OPS[name])))
        pdir = path(pid)
        if not (pdir / "project.json").exists():
            raise _not_found(pid)
        with _locked(pdir):
            current = _read(pdir)
            if current["rev"] != expected_rev:
                conflict_rev = current["rev"]
                raise BenchError("project_conflict",
                                 f"project {pid!r} is at rev {current['rev']}, not {expected_rev}: it changed meanwhile",
                                 "reload the project (project.get) and apply the change again")
            job = _Update(current, by)
            for i, (name, fields) in enumerate(checked):
                try:
                    getattr(job, name)(fields)
                    if name in _VERDICT_OPS:
                        job.recompute = True
                except BenchError as e:
                    raise BenchError(e.code, f"ops[{i}] ({name}): {e.message}", e.hint) from None
            warns, src_ids = job.verdicts()
            new = job.p
            changed = [k for k in CONTENT_KEYS if new[k] != current[k]]
            if changed:
                new["rev"] = current["rev"] + 1
                new["updated"] = job.now
                _write(pdir, new)
    except BenchError as e:
        return from_error(action, e, result={"rev": conflict_rev} if conflict_rev is not None else None)
    except Exception as e:  # noqa: BLE001
        return _internal(action, e)
    if changed:
        _emit_updated(pid, new["rev"], changed, by)
        summary = f"{new['title']}: rev {new['rev']}, changed {', '.join(changed)}."
    else:
        summary = f"{new['title']}: no changes (rev {new['rev']})."
    if warns:
        summary += " " + "; ".join(w["message"].split(":")[0] for w in warns) + "."
    try:
        srcs = sources.resolve(src_ids)
    except BenchError:
        srcs = []
    return envelope(action, summary, {"rev": new["rev"], "project": new, "changed": changed}, warnings=warns,
                    assumptions=job.aliases, sources=srcs, simulated=new["simulated"])


def _trash_target(pid: str) -> Path:
    trash = storage.data_dir() / "trash"
    trash.mkdir(mode=0o700, exist_ok=True)
    stamp = _dt.datetime.now(_dt.UTC).strftime("%Y%m%d-%H%M%S")
    for n in range(100):
        target = trash / (f"{pid}-{stamp}" if n == 0 else f"{pid}-{stamp}-{n}")
        if not target.exists():
            return target
    raise BenchError("project_conflict", f"too many trashed copies of {pid!r} in one second", "retry in a moment")


def last_build_elf(project: Mapping[str, Any]) -> str | None:
    """The ELF of the project's last successful build as stored by ``set_build`` (a relative path is taken from the
    firmware folder), or None: no build stored, a failed build, or no ELF recorded. Does not look at the disk."""
    fw = project.get("firmware") or {}
    build = fw.get("last_build") or {}
    elf = build.get("elf") if build.get("ok") is True else None
    if not isinstance(elf, str) or not elf:
        return None
    path = Path(elf)
    if not path.is_absolute() and fw.get("dir"):
        path = Path(fw["dir"]) / path
    return str(path)


def delete(id: str, *, by: str = "ui") -> dict[str, Any]:
    """Action project.delete: move ``projects/<id>/`` to ``trash/<id>-<stamp>/`` (``project_not_found`` if absent).

    ``result = {"id", "title", "trash"}``; the event ``project.updated`` goes out with ``changed: ["deleted"]``.
    A damaged project can be deleted too (that is the way out the damaged-project hint names)."""
    action = "project.delete"
    try:
        pid = _check_id(id)
        if by not in BY:
            raise _bad("by", "expected 'agent' or 'ui'")
        pdir = path(pid)
        if not (pdir / "project.json").is_file():
            raise _not_found(pid)
        with _locked(pdir):
            try:
                project = _read(pdir)
                title, rev = project["title"], project["rev"]
            except BenchError as e:
                if e.code != "project_damaged":
                    raise
                title, rev = pid, 0
            target = _trash_target(pid)
            os.replace(pdir, target)  # same file system (both under data_dir): atomic, nothing is copied
        _fsync_dir(pdir.parent)
    except BenchError as e:
        return from_error(action, e)
    except Exception as e:  # noqa: BLE001
        return _internal(action, e)
    _emit_updated(pid, rev, ["deleted"], by)
    return envelope(action, f"Moved bench project {pid!r} ({title}) to the trash: {target}.",
                    {"id": pid, "title": title, "trash": str(target)})


list = list_projects  # contract name; shadows the builtin in this module, see _list
