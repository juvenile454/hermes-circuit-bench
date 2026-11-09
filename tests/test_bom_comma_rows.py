"""Comma-separated BOM rows without a header row (``R1,10k,0805,1``) next to the other text forms."""
import json

import pytest

from circuit_bench import tools
from circuit_bench.bench_core import bom, contracts, solder
from circuit_bench.bench_core.contracts import BenchError


def _rows(text):
    return [(p["ref"], p["value"], p["package"], p["qty"]) for p in bom.parse(text)]


def _code(text):
    with pytest.raises(BenchError) as e:
        bom.parse(text)
    return e.value.code, str(e.value)


@pytest.mark.parametrize(("text", "rows"), [
    ("R1,10k,0805,1", [("R1", "10k", "0805", 1)]),
    ('"R1","10k","0805","1"', [("R1", "10k", "0805", 1)]),
    ("R1, R2, 10k", [("R1", "10k", None, 1), ("R2", "10k", None, 1)]),
    ("R1, 10k, 0805, 2", [("R1", "10k", "0805", 2)]),
    ("C1,100nF", [("C1", "100nF", None, 1)]),
    ("R1-R3,4k7,0207", [("R1", "4k7", "0207", 1), ("R2", "4k7", "0207", 1), ("R3", "4k7", "0207", 1)]),
    ('R1,"4,7k",0207,1', [("R1", "4,7k", "0207", 1)]),  # a quoted cell keeps its comma
    ("R1,10k,0805,1,", [("R1", "10k", "0805", 1)]),  # trailing comma of a spreadsheet export
    ("Q1,BC547,TO-92,1", [("Q1", "BC547", "TO-92", 1)]),  # BC547 looks like a reference, other prefix: value
    ("U1,ESP32-S3-DevKitC-1", [("U1", "ESP32-S3-DevKitC-1", None, 1)]),
    ("- R1,10k", [("R1", "10k", None, 1)]),  # list bullet
])
def test_comma_rows_are_read(text, rows):
    assert _rows(text) == rows


def test_comma_rows_package_and_kind_like_the_semicolon_form():
    comma = bom.parse("R1,10k,Resistor_SMD:R_0805_2012Metric,1\nC2,100uF,CP_Radial_D6.3mm,1")
    semi = bom.parse("R1;10k;Resistor_SMD:R_0805_2012Metric;1\nC2;100uF;CP_Radial_D6.3mm;1")
    assert comma == semi
    assert comma[0]["package"] == "R_0805_2012Metric" and comma[1]["kind"] == "electrolytic"


def test_mixed_comma_list_and_semicolon_lines():
    text = "R1,10k,0805,1\nR2 4k7 (0207)\nC1; 100nF; 0603; 1\nC2, C3: 22pF\n# comment\nLED1,red,3mm\nQ1 BC547"
    assert _rows(text) == [
        ("R1", "10k", "0805", 1), ("R2", "4k7", "0207", 1), ("C1", "100nF", "0603", 1),
        ("C2", "22pF", None, 1), ("C3", "22pF", None, 1), ("LED1", "red", "3mm", 1), ("Q1", "BC547", None, 1),
    ]


@pytest.mark.parametrize(("text", "rows"), [
    ("R2, R3: 10k", [("R2", "10k", None, 1), ("R3", "10k", None, 1)]),
    ("R1 10k, 1%", [("R1", "10k, 1%", None, 1)]),
    ("R1, R2 10k", [("R1", "10k", None, 1), ("R2", "10k", None, 1)]),
    ("R1,R2 10k, 1%", [("R1", "10k, 1%", None, 1), ("R2", "10k, 1%", None, 1)]),
    ("R1-R4, R6 10k", [(f"R{i}", "10k", None, 1) for i in (1, 2, 3, 4, 6)]),
    ("R1;10k;0805;1", [("R1", "10k", "0805", 1)]),
    ("R1\t10k\t0805\t1", [("R1", "10k", "0805", 1)]),
    ("R1 | 10k | 0805 | 1", [("R1", "10k", "0805", 1)]),
])
def test_list_and_field_forms_keep_their_meaning(text, rows):
    assert _rows(text) == rows


def test_header_csv_with_preamble_is_unchanged():
    kicad = ('"Source:","synthetic.kicad_sch"\n"Date:","2026-11-09"\n\n'
             '"Reference","Value","Footprint","Qty","DNP"\n'
             '"R1-R4","10k","Resistor_SMD:R_0805_2012Metric","4",""\n'
             '"C1","100nF","Capacitor_SMD:C_0603_1608Metric","1",""\n'
             '"R5","1k","Resistor_SMD:R_0805_2012Metric","1","DNP"\n')
    parts = {p["ref"]: p for p in bom.parse(kicad)}
    assert sorted(parts) == ["C1", "R1", "R2", "R3", "R4"]  # R5 is DNP, the range is expanded
    assert parts["R3"]["package"] == "R_0805_2012Metric" and parts["C1"]["kind"] == "ceramic"
    altium = ('Bill of Materials,synthetic.PrjPcb\n\n'
              'Comment,Description,Designator,Footprint,Quantity\n'
              '100nF,Capacitor,"C1, C2",0603,2\n'
              '10k,Resistor,R1,0805,1\n')
    parts = {p["ref"]: p for p in bom.parse(altium)}
    assert sorted(parts) == ["C1", "C2", "R1"]
    assert parts["C2"]["value"] == "100nF" and parts["R1"]["package"] == "0805"


@pytest.mark.parametrize(("text", "needle"), [
    ("R1,R2,R3", "no value (line 1)"),
    ("R1, R2", "no value (line 1)"),
    ("R1,,0805,1", "no value (line 1)"),
    ("C1,100nF,0603,2\nR1,10k,0805,1,5%", "too many cells (line 2)"),
    ("R1,R2,10k,0805,1,x", "too many cells (line 1)"),
])
def test_comma_rows_that_cannot_be_read(text, needle):
    code, msg = _code(text)
    assert code == "invalid_args" and needle in msg


def test_solder_plan_reads_comma_rows():
    env = solder.plan("R1,10k,0805,1\nC1,100nF,0603,2")
    assert env["ok"] and env["result"]["parts_total"] == 2
    refs = sorted(r for s in env["result"]["steps"] for r in s["refs"])
    assert refs == ["C1", "R1"]


def _tool(args):
    out = tools.make_handlers(tools.Host(hook_active=True))["bench_solder"](args)
    env = json.loads(out)
    assert contracts.validate_envelope(env) == [], env
    return env


def test_bench_solder_tool_with_comma_rows():
    env = _tool({"action": "plan", "bom": "R1,10k,0805,1\nC1,100nF,0603,2"})
    assert env["ok"] and env["result"]["parts_total"] == 2
    for bad in ("R1,R2,R3", "R1,10k,0805,1,x"):
        env = _tool({"action": "plan", "bom": bad})
        assert env["ok"] is False and env["error"]["code"] == "invalid_args"
