"""Roles in the schematic SVG (data-kind, data-net, data-ref), merged ink per role, split leads, label
clearance with the desktop's stroke widths per role, size budget, and the SVG stays self-contained."""
from __future__ import annotations

import json
import math
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from circuit_bench.bench_core import schematic
from circuit_bench.bench_core.contracts import MAX_RESULT_BYTES

pytest.importorskip("schemdraw")

TESTS = Path(__file__).resolve().parent
if str(TESTS) not in sys.path:
    sys.path.insert(0, str(TESTS))

import test_schem_render as base  # noqa: E402  (the independent ink geometry and the typical cases of the schematic tests)

NS = "{http://www.w3.org/2000/svg}"
KINDS = {"wire", "body", "pin", "label", "port", "junction"}
# desktop stroke widths per role (lines 1.5 px, bodies, ports and rings 2 px; 15-styles-wire.js)
ROLE_STROKE = {"wire": 1.5, "junction": 1.5, "body": 2.0, "port": 2.0}
SUPPLY = {"3V3", "5V"}


def _env(case: str, table=base.TYPICAL) -> dict:
    block, params, devkit, gpio = table[case]
    env = schematic.render(block, params, devkit=devkit, gpio=gpio)
    assert env["ok"], env["error"]
    return env


def _root(env: dict) -> ET.Element:
    return ET.fromstring(env["result"]["svg"])  # noqa: S314 - SVG produced by the code under test


def _children(root: ET.Element) -> list[ET.Element]:
    return list(root)


@pytest.mark.parametrize("case", sorted(base.TYPICAL))
def test_every_element_has_a_role(case):
    env = _env(case)
    root = _root(env)
    nets = {n["name"] for n in env["result"]["nets"]}
    refs = {p["ref"] for p in env["result"]["parts"]}
    for el in _children(root):
        tag = el.tag.removeprefix(NS)
        kind = el.get("data-kind")
        assert kind in KINDS, (tag, el.attrib)
        if tag == "text":
            assert kind in ("label", "pin"), el.text
            assert (kind == "pin") == (el.get("data-pin") is not None), el.text
        else:
            assert kind not in ("label", "pin"), tag
        if kind in ("wire", "junction", "port"):
            assert el.get("data-net") in nets, (kind, el.attrib)
        if kind == "body":
            assert el.get("data-ref") in refs, el.attrib
        if el.get("data-net") is not None:
            assert el.get("data-net") in nets, el.attrib
    # every net of the table is drawn (as wire or port), so hovering a row can light it in the plan
    drawn = {el.get("data-net") for el in _children(root) if el.get("data-kind") in ("wire", "port")}
    assert drawn == nets, (drawn, nets)


def test_npn_roles_match_the_netlist():
    env = _env("npn", base.CASES)
    root = _root(env)
    by = {}
    for el in _children(root):
        by.setdefault((el.get("data-kind"), el.get("data-net") or el.get("data-ref")), []).append(el)
    # one merged wire path per net
    for net in ("LASER_EN", "LASER_BASE", "LASER_LOW", "5V", "GND"):
        wires = [e for e in by.get(("wire", net), []) if e.tag == f"{NS}path"]
        assert len(wires) == 1, net
    assert {e.tag.removeprefix(NS) for e in by[("port", "LASER_EN")]} == {"circle"}  # the board pin (open dot)
    assert by[("port", "GND")][0].tag == f"{NS}path" and by[("port", "5V")][0].tag == f"{NS}path"
    junction = by[("junction", "LASER_BASE")]
    assert len(junction) == 1 and junction[0].get("fill") == "currentColor"
    # the resistor body is the zigzag only: its leads are wires of the pin nets
    r1 = [e for e in by[("body", "R1")] if e.tag == f"{NS}path"][0]
    assert r1.get("d").startswith("M36,0 L39,-9") and r1.get("d").endswith("L72,0")
    assert by[("wire", "LASER_EN")][0].get("d") == "M0,0 L36,0"
    assert "M72,0" in by[("wire", "LASER_BASE")][0].get("d")
    # node labels name their net (supply and board pin), part labels their part
    texts = {t.text: t for t in root.iter(f"{NS}text")}
    assert texts["+5 V"].get("data-net") == "5V" and texts["J1-20 · IO14"].get("data-net") == "LASER_EN"
    assert texts["R1 1 kΩ"].get("data-ref") == "R1" and texts["B"].get("data-kind") == "pin"


@pytest.mark.parametrize("case", sorted(base.TYPICAL))
def test_labels_clear_with_role_stroke_widths(case):
    """labels_clear (>= 6 px) also holds when the desktop draws bodies and ports 2 px wide."""
    env = _env(case)
    root = _root(env)
    texts = list(root.iter(f"{NS}text"))
    close = []
    for t in texts:
        box = base._box(t)
        best = math.inf
        for el in _children(root):
            kind = el.get("data-kind")
            if kind not in ROLE_STROKE or el.tag == f"{NS}rect":
                continue
            holder = ET.Element("svg")
            holder.append(el)
            segs, circles = base._ink(holder)
            half = ROLE_STROKE[kind] / 2
            if segs:
                best = min(best, min(base._to_box(x, y, box) for x, y in base._samples(segs)) - base.STEP / 2 - half)
            for cx, cy, r in circles:
                best = min(best, base._to_box(cx, cy, box) - r - half)
        if best < schematic.MIN_CLEAR:
            close.append((t.get("data-pin") or t.text, round(best, 2)))
    assert close == []


@pytest.mark.parametrize("case", sorted(base.TYPICAL))
def test_size_budget_for_every_typical_case(case):
    env = _env(case)
    if env["result"]["block"] in schematic.MULTI_BLOCKS:
        # module/level_shifter SVGs are 7-16 KB: bench_schematic writes them to a file and answers the model with the
        # path (tools.py), the route gives the desktop the SVG itself; the rest of the answer stays small
        env = {**env, "result": {k: v for k, v in env["result"].items() if k != "svg"}}
    assert len(json.dumps(env).encode()) <= MAX_RESULT_BYTES


@pytest.mark.parametrize("case", sorted(base.CASES))
def test_svg_stays_self_contained_and_sanitizer_safe(case):
    svg = _env(case, base.CASES)["result"]["svg"]
    # the same list as sanitizeSvg in desktop-src/lib/wire.js
    for bad in (r"<script", r"<foreignObject", r"\son[a-z]+\s*=", r"javascript:", r"<iframe", r"<image",
                r"\b(?:xlink:)?href\s*=", r"<!ENTITY", r"<style"):
        assert not re.search(bad, svg, re.IGNORECASE), bad
    root = ET.fromstring(svg)  # noqa: S314
    assert root.get("stroke") == "currentColor" and root.get("stroke-width") == "1.5"
    assert not re.search(r"#[0-9a-fA-F]{6}", svg)  # no stand-in colour leaks out


def test_roles_need_a_tag():
    sheet = schematic._Sheet(None, None)
    with pytest.raises(ValueError):
        sheet.add(object(), "decor")
    with pytest.raises(RuntimeError, match="without a role"):
        src = '<svg xmlns="http://www.w3.org/2000/svg"><path d="M0,0 L1,1" style="stroke:#000009;fill:none" /></svg>'
        schematic._tagged_shapes(ET.fromstring(src), [])  # noqa: S314


def test_lead_split_and_compaction():
    terms = ((0.0, 0.0, "A"), (108.0, 0.0, "B"))
    body, leads = schematic._split_leads("M0,0 L36,0 L39,-9 L45,9 L72,0 L108,0", terms)
    assert body == "M36,0 L39,-9 L45,9 L72,0" and leads == [("A", "M0,0 L36,0"), ("B", "M72,0 L108,0")]
    # a closed outline is never cut; a diagonal end is no lead
    assert schematic._split_leads("M0,0 L10,10 L0,20 Z", terms) == ("M0,0 L10,10 L0,20 Z", [])
    assert schematic._split_leads("M0,0 L10,10", terms) == ("M0,0 L10,10", [])
    assert schematic._compact_d(["M0,0 L10,0", "M10,0 L20,0 L30,0", "M5,5 L5,9"]) == "M0,0 L30,0 M5,5 L5,9"
    assert schematic._compact_d(["M10,0 L20,0", "M0,0 L10,0"]) == "M0,0 L20,0"


def test_net_labels_at_ports_and_rails():
    """The signal net above its board pin, the header pin of every supply and ground port."""
    texts = {t.text: t for t in _root(_env("npn", base.CASES)).iter(f"{NS}text")}
    assert texts["LASER_EN"].get("data-net") == "LASER_EN" and texts["LASER_EN"].get("data-kind") == "label"
    assert texts["J1-21 · 5V"].get("data-net") == "5V" and texts["J1-21 · 5V"].get("data-node") == "J1-21"
    assert texts["J1-22 · G"].get("data-net") == "GND"  # the board's own header label for ground
    assert "+5 V" in texts  # the supply value stays
    for case, want in (("led", {"LED", "J1-22 · G"}), ("led_low", {"LED", "J1-1 · 3V3"}),
                       ("button", {"BUTTON", "J1-2 · 3V3", "J1-22 · G"}), ("divider", {"VSENSE", "J1-22 · G"}),
                       ("npn_3v3", {"LOAD_EN", "J1-1 · 3V3", "J3-1 · G"})):
        assert want <= {t.text for t in _root(_env(case, base.CASES)).iter(f"{NS}text")}, case
    # without a DevKit there is no header pin to name: the symbol and "+5 V" say it all
    nodev = {t.text for t in _root(_env("npn_nodevkit", base.CASES)).iter(f"{NS}text")}
    assert "LOAD_EN" in nodev and not any("·" in x for x in nodev)


def test_hit_areas_lie_below_the_ink_and_attributes_are_single_quoted():
    svg = _env("npn", base.CASES)["result"]["svg"]
    root = ET.fromstring(svg)  # noqa: S314
    tags = [el.tag.removeprefix(NS) for el in root]
    rects = [i for i, t in enumerate(tags) if t == "rect"]
    assert rects == list(range(len(rects))) and len(rects) == 4
    assert '"' not in svg.split(">", 1)[0] and "/>" in svg and " />" not in svg
    assert schematic._serialize(ET.fromstring("<a b=\"it's &amp; &lt;\">x &gt; y</a>")) == \
        "<a b='it&apos;s &amp; &lt;'>x &gt; y</a>"  # noqa: S314
