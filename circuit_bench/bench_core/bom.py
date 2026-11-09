"""Bill of materials parser for the solder helper.

``parse(text_or_rows)`` turns a BOM into ``[{"ref", "value", "kind", "package", "qty"}]``:

- CSV with or without a header row.
  - With a header row (``,``, ``;`` or tab; quotes allowed): the header may follow preamble lines (old KiCad
    exports). Columns: ``Reference|Designator|Ref|Refs``, ``Value``, ``Footprint|Package``, ``Qty|Quantity``,
    optional ``DNP`` (marked rows are skipped) and ``Kind``.
  - Without a header row: one part or group per line, fields ``ref, value, package, qty`` split by ``,``, ``;``,
    tab or ``|`` (``R1,10k,0805,1``, ``"R1","10k"``, ``R1; 10k; 0207; 1``). A comma row starts with one or more
    reference cells of the same prefix (``R1, R2, 10k``); package and qty are optional. Quote a cell that holds a
    comma (``R1,"4,7k"``).
- List text, one part or group per line: ``R1 1k``, ``R2, R3: 10k``, ``R4-R6 4k7 (0207)``, ``C2 100uF [radial]``.
  ``#`` and ``//`` start comments. Lines of all forms may be mixed.
- Rows: a list of dicts (``ref``/``reference``/``designator``, ``value``, ``package``/``footprint``, ``qty``,
  optional ``kind``), a list of lists ``[ref, value, package?, qty?]`` or a list of list-form strings.

Grouped references (``R1, R2`` or KiCad ranges ``R1-R4``) are expanded to one part each (``qty`` 1).
``classify`` derives the kind from the reference prefix and refines it with value and package; capacitors
without a type or package are classified by value (rule of thumb, limits in ``data/solder/rules.json``).
Helpers raise ``BenchError``; ``solder.plan`` turns that into the result envelope.
"""
from __future__ import annotations

import csv
import json
import math
import re
from collections.abc import Iterable, Mapping
from functools import lru_cache
from pathlib import Path
from typing import Any

from .contracts import BenchError

RULES_PATH = Path(__file__).resolve().parent.parent / "data" / "solder" / "rules.json"
MAX_PARTS = 2000
MAX_TEXT = 200_000
_HEADER_SCAN_LINES = 30

_REF_HEADERS = {"reference", "references", "ref", "refs", "designator", "designators", "ref des", "refdes",
                "reference designator", "reference designators", "part reference"}
_VALUE_HEADERS = {"value", "values", "val"}
_VALUE_FALLBACK_HEADERS = {"comment"}  # Altium puts the value into "Comment"
_PACKAGE_HEADERS = {"footprint", "footprints", "package", "case", "case/package"}
_QTY_HEADERS = {"qty", "quantity", "qnty", "count", "amount"}
_KIND_HEADERS = {"kind"}
_DNP_HEADERS = {"dnp", "do not populate", "do not place"}
_DNP_TRUE = {"dnp", "yes", "y", "x", "1", "true", "do not populate", "do not place", "excluded"}

_KIND_ALIASES = {
    "res": "resistor", "resistors": "resistor",
    "cap": "capacitor", "capacitors": "capacitor",
    "electrolytic_capacitor": "electrolytic", "elko": "electrolytic", "elcap": "electrolytic",
    "polarized_capacitor": "electrolytic", "polarised_capacitor": "electrolytic",
    "ceramic_capacitor": "ceramic", "mlcc": "ceramic", "film_capacitor": "film",
    "npn": "transistor", "pnp": "transistor", "bjt": "transistor", "mosfet": "transistor", "fet": "transistor",
    "jumper": "wire_jumper", "wire": "wire_jumper", "wire_bridge": "wire_jumper",
    "pin_header": "header", "pin_socket": "header", "female_header": "header", "socket_header": "header",
    "screw_terminal": "terminal", "terminal_block": "terminal",
    "dev_board": "module", "devkit": "module", "board": "module",
    "button": "switch", "pushbutton": "switch", "push_button": "switch",
    "pot": "potentiometer", "trimmer": "potentiometer",
    "xtal": "crystal", "oscillator": "crystal", "resonator": "crystal",
    "zener": "diode", "rectifier": "diode", "schottky": "diode",
    "cell": "battery", "akku": "battery", "accumulator": "battery", "batteries": "battery", "battery_pack": "battery",
    "li_ion": "battery", "lipo": "battery", "li_po": "battery", "coin_cell": "battery",
}

_REF = re.compile(r"^[A-Z][A-Z_]*\d+[A-Z0-9_.]*$")
_RANGE = re.compile(r"^([A-Z][A-Z_]*)(\d+)-(?:([A-Z][A-Z_]*))?(\d+)$")
_REF_PATTERN = r"[A-Za-z][A-Za-z_]*\d+[A-Za-z0-9_.]*(?:[-\u2013](?:[A-Za-z][A-Za-z_]*)?\d+)?"
_LIST_LINE = re.compile(rf"^(?P<refs>{_REF_PATTERN}(?:\s*,\s*{_REF_PATTERN})*)(?:\s*[:=]\s*|\s+[-\u2013]\s+|\s+|$)(?P<rest>.*)$")
_FIELD_SPLIT = re.compile(r"\s*(?:\t|\||;)\s*")
_BULLET = re.compile(r"^(?:[-*\u2022]\s+|\d+[.)]\s+)")
_PACKAGE_HINT = re.compile(
    r"^(to-?\d+\w*|p?dip-?\d+|soic-?\d+|sot-?\d+\w*|do-?\d+\w*|\d{4}|radial|axial|tht|smd|\d+(?:[.,]\d+)?\s?mm|"
    r"t-1(?:\s3/4)?|[12]x\d{1,2}|hc-?49\w*)$", re.I)

_BATTERY = re.compile(r"\b18650\b|\b21700\b|li[ -]?ion|li[ -]?po\b|lipo|\bcr\d{4}\b|\bakku\b|\bbatter(?:y|ie)\b|"
                      r"\bcell\b", re.I)
_LED = re.compile(r"\bled\b|\bled_|_led\b|light[ -]emitting", re.I)
_MODULE = re.compile(r"devkit|dev[ -]?kit|dev[ -]?board|module|\bmodul\b|breakout|nodemcu|wemos|d1[ _-]?mini|arduino|"
                     r"\bpico\b|xiao|\besp32|\besp8266|wroom|wrover|\bboard\b", re.I)
_TERMINAL = re.compile(r"terminal|screw|klemme|phoenix|wago|kf301|kf128|dg301", re.I)
_HEADER = re.compile(r"header|pin_?socket|pin socket|socket|buchsenleiste|stiftleiste|\b[12]x\d{1,2}\b|_[12]x\d{1,2}|"
                     r"conn_0[12]x\d{2}|dupont", re.I)
_ELKO = re.compile(r"\belko\b|electrolytic|elektrolyt|\belec\b|polari[sz]ed|\bcp_|cp_elec|\bcpol\b", re.I)
_CERAMIC = re.compile(r"ceramic|keramik|\bmlcc\b|\bx[5-8][rst]\b|\bc0g\b|\bnp0\b|\by5v\b|\bz5u\b|c_disc|\bdisc\b|^c_\d{4}", re.I)
_FILM = re.compile(r"\bfilm\b|\bfolie\b|mk[tsp]\d|\bmk[tsp]\b|wima|polyester|polypropylene|c_rect", re.I)
_CAP_RKM = re.compile(r"(?<![\d.,])(\d+)([pnu])(\d+)(?![\d])", re.I)
_CAP_VALUE = re.compile(r"(?<![\d.,])(\d+(?:[.,]\d+)?)\s*([pnu])(f)?(?![a-z])", re.I)
_CAP_EXP = {"p": -12, "n": -9, "u": -6}  # exact decimal parsing: float("10e-6") == 1e-05, 10 * 1e-6 is not


@lru_cache(maxsize=1)
def _rules_cached() -> dict[str, Any]:
    try:
        data = json.loads(RULES_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise BenchError("rule_data_missing", f"solder rules not readable: {exc}", "reinstall the plugin") from None
    if data.get("schema") != 1 or not isinstance(data.get("kinds"), list):
        raise BenchError("rule_data_missing", "solder rules have an unknown schema", "reinstall the plugin")
    return data


def rules() -> dict[str, Any]:
    """Parsed ``data/solder/rules.json`` (cached; callers must not mutate it)."""
    return _rules_cached()


def kinds() -> list[str]:
    """Known kinds in rules order."""
    return [k["kind"] for k in rules()["kinds"]]


def capacitance(value: str) -> float | None:
    """Capacitance in farads from a value text ('100nF', '0.1 uF', '4u7', '100µF/10V'); None if not found."""
    text = (value or "").replace("\u00b5", "u").replace("\u03bc", "u")
    m = _CAP_RKM.search(text)
    if m:
        return float(f"{m.group(1)}.{m.group(3)}e{_CAP_EXP[m.group(2).lower()]}")
    m = _CAP_VALUE.search(text)
    if m:
        return float(f"{m.group(1).replace(',', '.')}e{_CAP_EXP[m.group(2).lower()]}")
    return None


def _capacitor(value: str, package: str) -> tuple[str, str]:
    text = f"{value} {package}"
    if _ELKO.search(text) or _ELKO.search(package or ""):
        return "electrolytic", "type"
    if _FILM.search(text):
        return "film", "type"
    if _CERAMIC.search(text) or _CERAMIC.search(package or ""):
        return "ceramic", "type"
    farads = capacitance(value)
    if farads is None:
        return "capacitor", "unclear"
    limits = rules()["classify"]["capacitor_by_value"]
    if farads < limits["ceramic_below_f"]:
        return "ceramic", "value"
    if farads >= limits["electrolytic_from_f"]:
        return "electrolytic", "value"
    return "capacitor", "unclear"


def _norm_kind(kind: Any) -> str | None:
    if not isinstance(kind, str) or not kind.strip():
        return None
    k = re.sub(r"[\s\-]+", "_", kind.strip().lower())
    return _KIND_ALIASES.get(k, k)


def prefix_of(ref: str) -> str:
    m = re.match(r"[A-Z_]*[A-Z]", ref)
    return m.group(0).rstrip("_") if m else ""


def classify(ref: str, value: str = "", package: str | None = "", kind: str | None = None) -> tuple[str, str]:
    """``(kind, basis)``. basis: ``given`` | ``prefix`` | ``type`` | ``value`` | ``unclear`` | ``unknown``."""
    value = value or ""
    package = package or ""
    known = set(kinds())
    given = _norm_kind(kind)
    if given and given in known and given not in ("capacitor", "unknown"):
        return given, "given"
    base = "capacitor" if given == "capacitor" else rules()["classify"]["prefixes"].get(prefix_of(ref))
    text = f"{value} {package}"
    if base is None:
        if _BATTERY.search(text):  # a cell without a BT ref still gets the battery step (polarity)
            return "battery", "type"
        return "unknown", "unknown"
    if base == "capacitor":
        return _capacitor(value, package)
    if base == "diode" and _LED.search(text):
        return "led", "type"
    if base == "ic":
        return ("module", "type") if _MODULE.search(text) and not re.search(r"socket", text, re.I) else ("ic", "prefix")
    if base == "connector":
        if _TERMINAL.search(text):
            return "terminal", "type"
        if _HEADER.search(text):
            return "header", "type"
    return base, "prefix"


def _clean(cell: Any) -> str:
    if cell is None:
        return ""
    if isinstance(cell, bool) or not isinstance(cell, str | int | float):
        raise BenchError("invalid_args", f"unexpected BOM cell {cell!r}", "BOM cells must be text or numbers")
    return str(cell).strip().strip('"').strip()


def _strip_library(package: str) -> str:
    # KiCad footprints are "Library:Footprint"; keep the footprint name only.
    if ":" in package and not re.match(r"^[A-Za-z]:[\\/]", package):
        return package.split(":", 1)[1].strip()
    return package


def split_refs(cell: str, *, where: str = "") -> list[str]:
    """'R1, R2' / 'R1 R2' / 'R1-R4' -> ['R1', 'R2', ...]. Virtual parts ('#PWR01') are dropped."""
    text = re.sub(r"\s*[-\u2013]\s*", "-", cell.strip())
    out: list[str] = []
    for token in (t for t in re.split(r"[,;\s]+", text) if t):
        token = token.upper()
        if token.startswith("#"):
            continue
        if "?" in token:
            raise BenchError("invalid_args", f"reference {token} is not annotated{where}",
                             "annotate the schematic so every part has a number (R1, C2, ...)")
        m = _RANGE.match(token)
        if m and (m.group(3) in (None, m.group(1))):
            start, end = int(m.group(2)), int(m.group(4))
            if end < start or end - start >= MAX_PARTS:
                raise BenchError("invalid_args", f"bad reference range {token}{where}", "write ranges like R1-R4")
            out += [f"{m.group(1)}{n}" for n in range(start, end + 1)]
        elif _REF.match(token):
            out.append(token)
        else:
            raise BenchError("invalid_args", f"bad reference {token!r}{where}",
                             "references look like R1, C2, LED3, SW1; separate several with commas")
    return out


def _qty(cell: str, where: str) -> int | None:
    if not cell:
        return None
    try:
        q = float(cell.replace(",", "."))
    except ValueError:
        raise BenchError("invalid_args", f"bad quantity {cell!r}{where}", "quantities are whole numbers") from None
    if not math.isfinite(q) or not 1 <= q <= 999 or q != int(q):  # same range as a project part's qty
        raise BenchError("invalid_args", f"bad quantity {cell!r}{where}", "quantities are whole numbers from 1 to 999")
    return int(q)


class _Collector:
    def __init__(self) -> None:
        self.parts: list[dict[str, Any]] = []
        self.seen: set[str] = set()
        self.basis: dict[str, str] = {}  # ref -> classify basis (given, prefix, type, value, unclear, unknown)
        self.modules: dict[str, str] = {}  # ref -> catalog module id (project parts from add_module)

    def add(self, refs_cell: str, value: str, package: str, qty: int | None, kind: str | None, where: str,
            module: str | None = None) -> None:
        refs = split_refs(refs_cell, where=where)
        if not refs:
            if refs_cell.strip().startswith("#"):
                return
            raise BenchError("invalid_args", f"missing reference{where}", "every BOM row needs a reference such as R1")
        package = _strip_library(package)
        for ref in refs:
            if ref in self.seen:
                raise BenchError("invalid_args", f"duplicate reference {ref}{where}", "each reference may appear once in the BOM")
            self.seen.add(ref)
            k, basis = classify(ref, value, package, kind)
            self.basis[ref] = basis
            if module:
                self.modules[ref] = module
            self.parts.append({"ref": ref, "value": value, "kind": k, "package": package or None,
                               "qty": qty if (qty and len(refs) == 1) else 1})
            if len(self.parts) > MAX_PARTS:
                raise BenchError("invalid_args", f"more than {MAX_PARTS} parts", "split the BOM")


def _header_columns(cells: list[str]) -> dict[str, int] | None:
    names = [re.sub(r"\s+", " ", c.strip().strip('"').strip().lower()) for c in cells]
    cols: dict[str, int] = {}
    for i, n in enumerate(names):
        for key, aliases in (("ref", _REF_HEADERS), ("value", _VALUE_HEADERS), ("package", _PACKAGE_HEADERS),
                             ("qty", _QTY_HEADERS), ("kind", _KIND_HEADERS), ("dnp", _DNP_HEADERS),
                             ("value_fallback", _VALUE_FALLBACK_HEADERS)):
            if n in aliases and key not in cols:
                cols[key] = i
    if "ref" not in cols or len(cols) < 2:
        return None
    if "value" not in cols and "value_fallback" in cols:
        cols["value"] = cols["value_fallback"]
    return cols


def _find_csv_header(lines: list[str]) -> tuple[int, str, dict[str, int]] | None:
    for idx, line in enumerate(lines[:_HEADER_SCAN_LINES]):
        if not line.strip():
            continue
        best = None
        for delim in (";", ",", "\t"):
            if delim not in line:
                continue
            cells = next(csv.reader([line], delimiter=delim))
            cols = _header_columns(cells)
            if cols and (best is None or len(cols) > len(best[2])):
                best = (idx, delim, cols)
        if best:
            return best
    return None


def _parse_csv(lines: list[str], idx: int, delim: str, cols: dict[str, int], out: _Collector) -> None:
    reader = csv.reader(lines[idx + 1:], delimiter=delim)
    for n, row in enumerate(reader, start=idx + 2):
        cells = [_clean(c) for c in row]
        if not any(cells):
            continue
        where = f" (line {n})"

        def cell(key: str, cells: list[str] = cells) -> str:
            i = cols.get(key)
            return cells[i] if i is not None and i < len(cells) else ""

        if "dnp" in cols and cell("dnp").lower() in _DNP_TRUE:
            continue
        out.add(cell("ref"), cell("value"), cell("package"), _qty(cell("qty"), where), cell("kind") or None, where)


def _split_rest(rest: str) -> tuple[str, str]:
    rest = rest.strip()
    m = re.match(r"^(.*?)\s*\[([^\]]*)\]\s*$", rest)
    if m:
        return m.group(1).strip(), m.group(2).strip()
    m = re.match(r"^(.*?)\s*\(([^)]*)\)\s*$", rest)
    if m and _PACKAGE_HINT.match(m.group(2).strip()):
        return m.group(1).strip(), m.group(2).strip()
    return rest, ""


def _comma_cells(text: str, m: re.Match[str] | None) -> list[str] | None:
    """The cells of a comma row (``R1,10k,0805,1``, ``"R1","10k"``, ``R1, R2, 10k``), or None for any other line.

    A comma row has a comma, its first cell is a reference or a range, and it is not list text: ``R2, R3: 10k``
    and ``R1, R2 10k`` (references, then the value after a space) keep their list meaning, ``R1 10k, 1%`` does
    not start with a reference cell. References only (``R1,R2,R3``) count as a comma row without a value."""
    if "," not in text:
        return None
    rest = m.group("rest") if m else ""
    if m and ((rest and not rest.startswith(",")) or text[m.end("refs"):].lstrip().startswith((":", "="))):
        return None
    cells = [_clean(c) for c in next(csv.reader([text], delimiter=",", skipinitialspace=True), [])]
    if not cells or not re.fullmatch(_REF_PATTERN, cells[0]):
        return None
    while cells and not cells[-1]:
        cells.pop()  # trailing commas of a spreadsheet export
    return cells


def _parse_comma_row(cells: list[str], where: str, out: _Collector) -> None:
    prefix = prefix_of(cells[0].upper())
    refs = 1  # further leading reference cells with the same prefix ("Q1,BC547" keeps BC547 as value)
    while (refs < len(cells) and re.fullmatch(_REF_PATTERN, cells[refs])
           and prefix_of(cells[refs].upper()) == prefix):
        refs += 1
    fields = cells[refs:]
    if len(fields) > 3:
        raise BenchError("invalid_args", f"too many cells{where}: {len(cells)}",
                         "comma rows are ref, value, package, qty; quote a cell that holds a comma, e.g. \"4,7k\"")
    fields += [""] * (3 - len(fields))
    if not fields[0]:
        raise BenchError("invalid_args", f"no value{where}",
                         "give the value after the references, e.g. 'R1,10k,0805,1' or 'R1, R2, 10k'")
    out.add(", ".join(cells[:refs]), fields[0], fields[1], _qty(fields[2], where), None, where)


def _parse_line(line: str, n: int, out: _Collector) -> None:
    text = _BULLET.sub("", line.strip())
    if not text or text.startswith(("#", "//")):
        return
    where = f" (line {n})"
    if _FIELD_SPLIT.search(text):
        fields = [_clean(f) for f in _FIELD_SPLIT.split(text)]
        fields += [""] * (4 - len(fields))
        out.add(fields[0], fields[1], fields[2], _qty(fields[3], where), None, where)
        return
    m = _LIST_LINE.match(text)
    cells = _comma_cells(text, m)
    if cells is not None:
        _parse_comma_row(cells, where, out)
        return
    if not m:
        if re.match(r"^[A-Za-z][A-Za-z_]*\?", text):
            split_refs(text.split()[0], where=where)  # raises "not annotated"
        raise BenchError("invalid_args", f"cannot read BOM line {n}: {text[:60]!r}",
                         "start each line with the reference, e.g. 'R1 1k' or 'C1, C2: 100nF'")
    value, package = _split_rest(m.group("rest"))
    refs = m.group("refs")
    # "R1 R2 10k": further references with the same prefix, separated by spaces only. "Q1 BC547" keeps BC547 as value.
    prefix = prefix_of(refs.split(",")[0].strip().upper())
    words = value.split()
    while words and prefix and re.fullmatch(rf"{re.escape(prefix)}\d+", words[0], re.I):
        refs += f", {words.pop(0)}"
    value = " ".join(words) if words != value.split() else value
    out.add(refs, value, package, None, None, where)


def _parse_text(text: str, out: _Collector) -> None:
    if len(text) > MAX_TEXT:
        raise BenchError("invalid_args", f"BOM text longer than {MAX_TEXT} characters", "split the BOM")
    lines = text.lstrip("\ufeff").splitlines()
    header = _find_csv_header(lines)
    if header:
        _parse_csv(lines, *header, out)
        return
    for n, line in enumerate(lines, start=1):
        _parse_line(line, n, out)


def _row_get(row: Mapping[str, Any], aliases: Iterable[str]) -> Any:
    lowered = {str(k).strip().lower(): v for k, v in row.items()}
    for a in aliases:
        if a in lowered and lowered[a] not in (None, ""):
            return lowered[a]
    return None


def parse(text_or_rows: str | Iterable[Any]) -> list[dict[str, Any]]:
    """Parse a BOM (CSV with or without a header row, list text or rows) into parts. Raises ``BenchError('invalid_args')``."""
    return parse_detail(text_or_rows)[0]


def parse_detail(text_or_rows: str | Iterable[Any]) -> tuple[list[dict[str, Any]], dict[str, str], dict[str, str]]:
    """Like ``parse``, plus ``{ref: basis}`` of each kind (``given`` when the row named it, ``value`` when guessed from
    the value only, see ``classify``) and ``{ref: module id}`` of rows with a ``module`` key (project parts)."""
    out = _Collector()
    if isinstance(text_or_rows, str):
        _parse_text(text_or_rows, out)
    elif isinstance(text_or_rows, Iterable) and not isinstance(text_or_rows, bytes | Mapping):
        for n, row in enumerate(text_or_rows, start=1):
            where = f" (row {n})"
            if isinstance(row, str):
                _parse_line(row, n, out)
            elif isinstance(row, Mapping):
                ref = _row_get(row, ("ref", "refs", "reference", "references", "designator", "designators"))
                if isinstance(ref, list | tuple):
                    ref = ", ".join(_clean(r) for r in ref)
                value = _row_get(row, ("value", "val", "comment"))
                package = _row_get(row, ("package", "footprint", "case"))
                qty = _row_get(row, ("qty", "quantity", "count"))
                if str(_row_get(row, ("dnp",)) or "").strip().lower() in _DNP_TRUE:
                    continue
                kind = _row_get(row, ("kind",))
                module = _row_get(row, ("module",))
                out.add(_clean(ref), _clean(value), _clean(package), _qty(_clean(qty), where),
                        kind if isinstance(kind, str) else None, where,
                        _clean(module) if isinstance(module, str) else None)
            elif isinstance(row, list | tuple):
                cells = [_clean(c) for c in row] + [""] * 4
                out.add(cells[0], cells[1], cells[2], _qty(cells[3], where), None, where)
            else:
                raise BenchError("invalid_args", f"unexpected BOM row {row!r}{where}",
                                 "rows are dicts, lists or lines of text")
    else:
        raise BenchError("invalid_args", "the BOM must be text or a list of rows",
                         "pass CSV with or without a header row, one part per line, or a list of {ref, value, package, qty}")
    if not out.parts:
        raise BenchError("invalid_args", "the BOM is empty", "list at least one part, e.g. 'R1 1k'")
    return out.parts, out.basis, out.modules
