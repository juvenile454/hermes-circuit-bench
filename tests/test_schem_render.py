"""Rendered SVG (themeable, labels as text, no overlaps, label clearance, tight viewBox, deterministic)
and the action envelope."""
from __future__ import annotations

import builtins
import itertools
import json
import math
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from circuit_bench.bench_core import schematic
from circuit_bench.bench_core.contracts import MAX_RESULT_BYTES, validate_envelope

schemdraw = pytest.importorskip("schemdraw")

ROOT = Path(__file__).resolve().parent.parent
NS = "{http://www.w3.org/2000/svg}"
S3 = "esp32-s3-devkitc-1"
LONG = "W" * schematic.TEXT_MAX
LONG_NET = "N" * 24
LINE_BOX = 1.2  # label box height in em: one line box (DOM text boxes of monospace fonts are about 1.16 em)
MIN_CLEAR = 6.0  # px between a label box and the stroke edge of any line
STROKE = 1.5

CASES = {
    "npn": ("npn_low_side", {"r_base": 1000, "load": "laser module", "net": "LASER_EN"}, S3, 14),
    "npn_3v3": ("npn_low_side", {"r_base": "2k2", "r_pulldown": "47k", "supply": "3V3", "load": "buzzer"}, S3, 1),
    "led": ("led", {"r_series": 150, "led": "red"}, S3, 4),
    "led_low": ("led", {"r_series": "4k7", "active": "low"}, S3, 1),
    "button": ("button_pullup", {}, S3, 5),
    "divider": ("divider", {"r1": "30k", "r2": "10k", "v_in": 12, "source": "battery"}, S3, 6),
    "divider_net": ("divider", {"r1": "100k", "r2": "47k"}, None, None),
    "npn_nodevkit": ("npn_low_side", {"r_base": 1000}, None, 14),
    # longest allowed texts: labels grow away from the drawing and must still be clear
    "npn_long": ("npn_low_side", {"r_base": "1.234M", "r_pulldown": "1.234M", "transistor": LONG, "load": LONG,
                                  "net": LONG_NET}, S3, 14),
    "led_long": ("led", {"r_series": "1.234M", "led": LONG, "net": LONG_NET}, S3, 48),
    "led_low_long": ("led", {"r_series": "1.234M", "led": LONG, "active": "low", "net": LONG_NET}, S3, 48),
    "button_long": ("button_pullup", {"r_pullup": "1.234M", "button": LONG, "net": LONG_NET}, S3, 0),
    "divider_long": ("divider", {"r1": "1.234M", "r2": "1.234M", "source": LONG, "input_net": "I" * 24,
                                 "net": LONG_NET}, S3, 10),
}


def _parse(svg: str) -> ET.Element:
    return ET.fromstring(svg)  # noqa: S314 - SVG produced by the code under test


def _render(case: str) -> dict:
    block, params, devkit, gpio = CASES[case]
    return schematic.render(block, params, devkit=devkit, gpio=gpio)


def _svg(case: str) -> ET.Element:
    env = _render(case)
    assert env["ok"], env["error"]
    return _parse(env["result"]["svg"])


def _texts(root: ET.Element) -> list[ET.Element]:
    return list(root.iter(f"{NS}text"))


def _box(t: ET.Element) -> tuple[float, float, float, float]:
    """Rough text box estimate: 0.6 x font size per character, one line box (1.2 em) high."""
    size = float(t.get("font-size", "nan"))
    x, y = float(t.get("x", "nan")), float(t.get("y", "nan"))
    w = 0.6 * size * len(t.text or "")
    x0 = {"start": x, "middle": x - w / 2, "end": x - w}[t.get("text-anchor", "start")]
    assert t.get("dominant-baseline") == "central"
    h = LINE_BOX * size
    return x0, y - h / 2, x0 + w, y + h / 2


def _overlap(a, b) -> bool:
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


def _overlapping_pairs(root: ET.Element) -> list[tuple[str, str]]:
    boxes = [(t.text or "", _box(t)) for t in _texts(root)]
    return [(a[0], b[0]) for i, a in enumerate(boxes) for b in boxes[i + 1:] if _overlap(a[1], b[1])]


# --------------------------------------------------------------------------- ink geometry (independent of the module)

STEP = 0.5  # px between sample points on a line; a sampled distance is at most STEP / 2 too large


def _ink(root: ET.Element) -> tuple[list[tuple[float, float, float, float]], list[tuple[float, float, float]]]:
    """Line segments (paths, polygons) and circles of the drawing; the transparent hit rects are no ink."""
    segs, circles = [], []
    num = r"-?(?:\d+\.?\d*|\.\d+)"
    for el in root.iter():
        tag = el.tag.removeprefix(NS)
        if tag == "path":
            pts: list[tuple[float, float]] = []
            for cmd, args in re.findall(r"([MLZ])([^MLZ]*)", el.get("d", "")):
                vals = [float(v) for v in re.findall(num, args)]
                if cmd == "Z":
                    segs.append((*pts[-1], *pts[0]))
                    continue
                for i in range(0, len(vals), 2):
                    pt = (vals[i], vals[i + 1])
                    if not (cmd == "M" and i == 0):
                        segs.append((*pts[-1], *pt))
                    else:
                        pts = []
                    pts.append(pt)
        elif tag == "polygon":
            vals = [float(v) for v in re.findall(num, el.get("points", ""))]
            pts = list(zip(vals[0::2], vals[1::2], strict=True))
            segs += [(*a, *b) for a, b in zip(pts, pts[1:] + pts[:1], strict=True)]
        elif tag == "circle":
            circles.append((float(el.get("cx", "0")), float(el.get("cy", "0")), float(el.get("r", "0"))))
    return segs, circles


def _samples(segs) -> list[tuple[float, float]]:
    out = []
    for x0, y0, x1, y1 in segs:
        n = max(1, math.ceil(math.hypot(x1 - x0, y1 - y0) / STEP))
        out += [(x0 + (x1 - x0) * k / n, y0 + (y1 - y0) * k / n) for k in range(n + 1)]
    return out


def _to_box(px: float, py: float, box) -> float:
    return math.hypot(max(box[0] - px, 0.0, px - box[2]), max(box[1] - py, 0.0, py - box[3]))


def _clearances(root: ET.Element) -> list[tuple[str, float]]:
    """(label, px) per text: gap between its box and the stroke edge of the nearest ink (sampled lines: the value
    is never too large; circles count as discs). Pin markers are named by their pin (J2.1, Q1.B)."""
    segs, circles = _ink(root)
    pts = _samples(segs)
    out = []
    for t in _texts(root):
        box = _box(t)
        line = min(_to_box(x, y, box) for x, y in pts) - STEP / 2
        disc = min((_to_box(cx, cy, box) - r for cx, cy, r in circles), default=math.inf)
        out.append((t.get("data-pin") or t.text or "", min(line, disc) - STROKE / 2))
    return out


def _ink_bounds(root: ET.Element) -> tuple[float, float, float, float]:
    segs, circles = _ink(root)
    half = STROKE / 2
    xs = [v for s in segs for v in (s[0] - half, s[2] - half, s[0] + half, s[2] + half)]
    ys = [v for s in segs for v in (s[1] - half, s[3] - half, s[1] + half, s[3] + half)]
    xs += [v for cx, _cy, r in circles for v in (cx - r - half, cx + r + half)]
    ys += [v for _cx, cy, r in circles for v in (cy - r - half, cy + r + half)]
    for t in _texts(root):
        x0, y0, x1, y1 = _box(t)
        xs += [x0, x1]
        ys += [y0, y1]
    return min(xs), min(ys), max(xs), max(ys)


def _typical_cases() -> dict[str, tuple]:
    """Every block of schematic.blocks(): each combination of its choices, with the shortest and the longest texts,
    on a DevKit (J1 and J3 side) and without one."""
    out = {}
    for b in schematic.blocks():
        params = b["params"]
        base = {p["name"]: "4k7" for p in params if p["required"]}
        choices = [[(p["name"], c) for c in p["choices"]] for p in params if p["type"] == "choice"]
        long = {}
        for i, p in enumerate(q for q in params if q["type"] == "net"):
            long[p["name"]] = "NOPQ"[i] * 24  # distinct nets
        for p in params:
            if p["type"] == "text":
                long[p["name"]] = "W" * schematic.TEXT_MAX
            elif p["type"] == "ohm":
                long[p["name"]] = "1.234M"
            elif p["type"] == "volt":
                long[p["name"]] = 12.5
        sizes = {"short": {}, "long": long}
        if any(p["type"] == "volt" for p in params):
            sizes["volt"] = {p["name"]: "3V3" for p in params if p["type"] == "volt"}
        for combo in itertools.product(*choices):
            for size, extra in sizes.items():
                for where, devkit, gpio in (("j1", S3, 14), ("j3", S3, 48), ("bare", None, None)):
                    tag = "-".join(f"{k}={v}" for k, v in combo)
                    out[f"{b['block']}:{tag}:{size}:{where}".replace("::", ":")] = (
                        b["block"], {**base, **dict(combo), **extra}, devkit, gpio)
    return out


TYPICAL = _typical_cases()


def test_schemdraw_version_is_supported():
    major, minor = (int(v) for v in schemdraw.__version__.split(".")[:2])
    assert (0, 21) <= (major, minor) < (0, 24), schemdraw.__version__


@pytest.mark.parametrize("case", sorted(CASES))
def test_paint_is_current_color_or_none(case):
    root = _svg(case)
    for el in root.iter():
        assert el.get("style") is None, el.tag
        for attr in ("fill", "stroke", "color", "stop-color"):
            if el.get(attr) is not None:
                assert el.get(attr) in ("currentColor", "none"), (el.tag, attr, el.get(attr))
    raw = ET.tostring(root, encoding="unicode")
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b|rgba?\(|\bwhite\b|\bblack\b|url\(", raw)


@pytest.mark.parametrize("case", sorted(CASES))
def test_svg_has_only_a_viewbox_and_no_background(case):
    root = _svg(case)
    assert root.tag == f"{NS}svg"
    assert root.get("width") is None and root.get("height") is None
    vb = [float(v) for v in root.get("viewBox", "").split()]
    assert len(vb) == 4 and vb[2] > 0 and vb[3] > 0
    assert root.get("preserveAspectRatio") == "xMidYMid meet"  # the UI scales the whole drawing, centred
    tags = {el.tag.removeprefix(NS) for el in root.iter()}
    assert tags <= {"svg", "path", "circle", "polygon", "rect", "text"}, tags
    for rect in root.iter(f"{NS}rect"):  # only transparent hit areas, never a background
        assert rect.get("fill") == "none" and rect.get("stroke") == "none" and rect.get("data-ref")


@pytest.mark.parametrize("case", sorted(CASES))
def test_labels_are_monospace_text_in_current_color(case):
    env = _render(case)
    root = _parse(env["result"]["svg"])
    texts = _texts(root)
    assert texts
    for t in texts:
        assert t.get("font-family") == "monospace" and t.get("fill") == "currentColor" and t.get("stroke") == "none"
        assert list(t) == [] and t.text  # one plain line, no tspans
    shown = [t.text for t in texts]
    assert all(lb in shown for lb in env["result"]["labels"])


def test_required_labels_are_present():
    texts = [t.text for t in _texts(_svg("npn"))]
    for lb in ("+5 V", "R1 1 kΩ", "R2 10 kΩ", "Q1 2N2222A", "J2 laser module", "J1-20 · IO14"):
        assert lb in texts, lb
    assert "5 V" not in texts and "V" not in texts  # the supply stays "+5 V" (an early prototype dropped the sign)
    assert "+3.3 V" in [t.text for t in _texts(_svg("npn_3v3"))]
    assert {"+3.3 V", "R1 10 kΩ", "SW1 push button", "J1-5 · IO5"} <= {t.text for t in _texts(_svg("button"))}
    assert {"R1 150 Ω", "D1 red", "A", "K", "J1-4 · IO4"} <= {t.text for t in _texts(_svg("led"))}
    assert {"+3.3 V", "R1 4.7 kΩ", "J3-4 · IO1"} <= {t.text for t in _texts(_svg("led_low"))}
    assert {"+12 V", "R1 30 kΩ", "R2 10 kΩ", "J2 battery", "J1-6 · IO6"} <= {t.text for t in _texts(_svg("divider"))}
    assert {"VIN", "GPIO"} <= {t.text for t in _texts(_svg("divider_net"))}
    assert "GPIO14" in [t.text for t in _texts(_svg("npn_nodevkit"))]


@pytest.mark.parametrize("case", sorted(CASES))
def test_no_label_boxes_overlap(case):
    assert _overlapping_pairs(_svg(case)) == []


@pytest.mark.parametrize("case", sorted(CASES))
def test_labels_stay_inside_the_viewbox(case):
    root = _svg(case)
    x, y, w, h = (float(v) for v in root.get("viewBox", "").split())
    for t in _texts(root):
        x0, y0, x1, y1 = _box(t)
        assert x <= x0 and x1 <= x + w and y <= y0 and y1 <= y + h, t.text


def test_typical_cases_cover_every_block():
    assert {c[0] for c in TYPICAL.values()} == {b["block"] for b in schematic.blocks()}
    assert len(TYPICAL) >= 30


@pytest.mark.parametrize("case", sorted(TYPICAL))
def test_labels_keep_clear_of_every_line(case):
    """Every label box (pin markers 1/2, B/C/E, A/K included) keeps >= 6 px from every line and symbol."""
    block, params, devkit, gpio = TYPICAL[case]
    env = schematic.render(block, params, devkit=devkit, gpio=gpio)
    assert env["ok"], env["error"]
    root = _parse(env["result"]["svg"])
    gaps = _clearances(root)
    close = [(label, round(gap, 2)) for label, gap in gaps if gap < MIN_CLEAR]
    assert close == [], close
    assert _overlapping_pairs(root) == []
    status = {c["id"]: c["status"] for c in env["checks"]}
    assert status["schematic.labels_clear"] == status["schematic.labels_overlap"] == "passed"
    # the module's exact measurement agrees with the sampled one here (both see the same drawing)
    exact = [gap for _text, gap in schematic.label_clearances(env["result"]["svg"])]
    assert len(exact) == len(gaps)
    for (label, sampled), gap in zip(gaps, exact, strict=True):
        assert sampled - 0.01 <= gap <= sampled + STEP / 2 + 0.01, (label, sampled, gap)


@pytest.mark.parametrize("case", sorted(CASES))
def test_pin_markers_sit_at_their_pins(case):
    """Pin markers stay next to their own pin: within 2 drawing units of the part's hit area."""
    root = _svg(case)
    hits = {r.get("data-ref"): [float(r.get(k)) for k in ("x", "y", "width", "height")] for r in root.iter(f"{NS}rect")}
    for t in _texts(root):
        pin = t.get("data-pin")
        if not pin:
            continue
        x, y, w, h = hits[pin.split(".")[0]]
        assert _to_box(*_box(t)[:2], (x - 72, y - 72, x + w + 72, y + h + 72)) == 0, pin


@pytest.mark.parametrize("case", sorted(TYPICAL))
def test_viewbox_is_tight_around_the_drawing(case):
    """The drawing ends without empty space: viewBox = ink and label boxes plus PAD (integer rounding)."""
    block, params, devkit, gpio = TYPICAL[case]
    env = schematic.render(block, params, devkit=devkit, gpio=gpio)
    root = _parse(env["result"]["svg"])
    vx, vy, vw, vh = (float(v) for v in root.get("viewBox").split())
    x0, y0, x1, y1 = _ink_bounds(root)
    slack = {"left": x0 - vx, "top": y0 - vy, "right": vx + vw - x1, "bottom": vy + vh - y1}
    assert all(schematic.PAD - 0.01 <= v <= schematic.PAD + 1.01 for v in slack.values()), slack
    assert schematic.PAD <= 4


def test_clearance_check_flags_a_label_next_to_a_line():
    """Before the clearance check the J2 pin numbers stood 2-4 px from the lead and the box: the check must fail such a layout."""
    svg = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100" stroke-width="1.5">'
           '<path d="M50,10 L50,40 M30,40 L70,40" />'
           '<text x="46" y="30" text-anchor="end" dominant-baseline="central" font-size="10" data-pin="J2.1">1</text>'
           '<text x="20" y="80" text-anchor="middle" dominant-baseline="central" font-size="12">far</text></svg>')
    root = _parse(svg)
    gaps = dict(_clearances(root))
    assert gaps["J2.1"] <= 3.25 and gaps["far"] > 20  # 4 px to the lead axis minus half the stroke
    overlaps, close = schematic.label_problems(svg)
    assert overlaps == [] and len(close) == 1 and close[0].startswith("'1' ")
    exact = dict(schematic.label_clearances(svg))
    assert exact["1"] < schematic.MIN_CLEAR <= exact["far"]


def test_overlap_check_catches_the_spike_collision():
    """Early prototype: '5 V' set right next to 'Laser-\\nmodul' collided. The same layout must be flagged."""
    svg = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 100">'
           '<text x="100" y="40" text-anchor="start" dominant-baseline="central" font-size="12">modul</text>'
           '<text x="130" y="42" text-anchor="start" dominant-baseline="central" font-size="12">5 V</text></svg>')
    assert _overlapping_pairs(_parse(svg)) == [("modul", "5 V")]
    overlaps, _ = schematic.label_problems(svg)
    assert overlaps == ["'modul' / '5 V'"]


@pytest.mark.parametrize("case", sorted(CASES))
def test_envelope_checks_pass_and_stay_small(case):
    env = _render(case)
    assert validate_envelope(env) == []
    assert env["action"] == "schematic.render" and env["ok"] is True
    status = {c["id"]: c["status"] for c in env["checks"]}
    assert status["schematic.labels_overlap"] == "passed"
    assert status["schematic.labels_clear"] == "passed"
    assert status["schematic.netlist"] == "passed"
    assert len(json.dumps(env).encode()) <= MAX_RESULT_BYTES


def test_every_part_has_a_hover_target():
    for case in CASES:
        env = _render(case)
        root = _parse(env["result"]["svg"])
        hit = {r.get("data-ref") for r in root.iter(f"{NS}rect")}
        labelled = {t.get("data-ref") for t in _texts(root) if t.get("data-ref")}
        refs = {p["ref"] for p in env["result"]["parts"]}
        assert hit == refs == labelled, case


def test_result_shape_matches_the_desktop_fixture():
    fixture = json.loads((ROOT / "desktop-src" / "fixtures" / "schematic.npn.json").read_text(encoding="utf-8"))
    env = _render("npn")
    assert set(env) == set(fixture)
    assert set(env["result"]) == set(fixture["result"])
    for key in ("nets", "parts", "wiring"):
        assert {frozenset(x) for x in env["result"][key]} == {frozenset(x) for x in fixture["result"][key]}
    assert env["result"]["wiring"][0] == fixture["result"]["wiring"][0] == {
        "from": "J1-20 · IO14", "to": "R1.1", "net": "LASER_EN"}
    assert env["result"]["parts"] == fixture["result"]["parts"]
    assert [w["code"] for w in env["warnings"]][:1] == ["laser_safety"]
    assert env["sources"][0]["id"] == "devkitc1-s3-v1.1"


def test_deterministic_bytes():
    first = {case: _render(case) for case in CASES}
    again = {case: _render(case) for case in reversed(list(CASES))}
    for case in CASES:
        assert json.dumps(first[case], sort_keys=True) == json.dumps(again[case], sort_keys=True), case
    assert "clip" not in first["npn"]["result"]["svg"] and "id=" not in first["npn"]["result"]["svg"]


def test_laser_warning_only_for_lasers():
    codes = [w["code"] for w in _render("npn")["warnings"]]
    assert "laser_safety" in codes
    codes = [w["code"] for w in _render("npn_3v3")["warnings"]]
    assert "laser_safety" not in codes and "transistor_pinout" in codes


def test_defaults_are_marked_as_rule_of_thumb():
    env = _render("button")
    a = {x["key"]: x for x in env["assumptions"]}
    assert a["r_pullup"]["value"] == "10 kΩ" and "rule of thumb" in a["r_pullup"]["reason"]
    assert "rule-of-thumb" in [s["id"] for s in env["sources"]]
    assert "rule-of-thumb" not in [s["id"] for s in _render("led")["sources"]]


def test_missing_schemdraw_gives_dependency_missing(monkeypatch):
    real_import = builtins.__import__

    def blocked(name, *a, **kw):
        if name.split(".")[0] == "schemdraw":
            raise ImportError(f"blocked for test: {name}")
        return real_import(name, *a, **kw)

    for name in list(sys.modules):
        if name == "schemdraw" or name.startswith("schemdraw."):
            monkeypatch.delitem(sys.modules, name)
    monkeypatch.setattr(builtins, "__import__", blocked)
    env = schematic.render("npn_low_side", {"r_base": 1000}, devkit=S3, gpio=14)
    assert env["ok"] is False and env["error"]["code"] == "dependency_missing"
    assert validate_envelope(env) == []
    assert env["result"]["svg"] is None
    assert env["result"]["wiring"][0]["from"] == "J1-20 · IO14"  # the table still works without schemdraw
