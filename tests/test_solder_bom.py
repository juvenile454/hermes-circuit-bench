"""BOM parser (bench_core/bom.py)."""
import pytest

from circuit_bench.bench_core import bom
from circuit_bench.bench_core.contracts import BenchError

SPIKE_LIST = """\
# synthetic 11-part BOM (same shape as the spike's laser driver board)
J1 Female header 1x20 (ESP32-S3)
J2 Female header 1x20 (ESP32-S3)
R1 1 kΩ
R2 10 kΩ
Q1 2N2222A
C1 100 nF
C2 100 µF/10 V
D1 LED red
W1 Wire jumper GND
X1 Screw terminal 2-pin (5 V)
U1 ESP32-S3-DevKitC-1
"""

KICAD_SEMICOLON = """\
"Reference";"Value";"Footprint";"Qty";"DNP"
"C1,C3";"100nF";"Capacitor_THT:C_Disc_D5.0mm_W2.5mm_P5.00mm";"2";""
"C2";"100uF";"Capacitor_THT:CP_Radial_D6.3mm_P2.50mm";"1";""
"D1";"LED";"LED_THT:LED_D5.0mm";"1";""
"J1-J2";"Conn_01x20_Socket";"Connector_PinSocket_2.54mm:PinSocket_1x20_P2.54mm_Vertical";"2";""
"R1, R2";"4,7k";"Resistor_THT:R_Axial_DIN0207_L6.3mm_D2.5mm_P10.16mm_Horizontal";"2";""
"R3";"10k";"Resistor_THT:R_Axial_DIN0207_L6.3mm_D2.5mm_P10.16mm_Horizontal";"1";"DNP"
"Q1";"2N2222A";"Package_TO_SOT_THT:TO-92_Inline";"1";""
"""


def _by_ref(parts):
    return {p["ref"]: p for p in parts}


def test_list_form_spike_bom_kinds():
    parts = bom.parse(SPIKE_LIST)
    assert len(parts) == 11
    kinds = {p["ref"]: p["kind"] for p in parts}
    assert kinds == {
        "J1": "header", "J2": "header", "R1": "resistor", "R2": "resistor", "Q1": "transistor",
        "C1": "ceramic", "C2": "electrolytic", "D1": "led", "W1": "wire_jumper", "X1": "terminal", "U1": "module",
    }
    p = _by_ref(parts)
    assert p["R1"] == {"ref": "R1", "value": "1 kΩ", "kind": "resistor", "package": None, "qty": 1}
    assert p["J1"]["value"] == "Female header 1x20 (ESP32-S3)"  # parentheses that are not a package stay in the value


def test_every_part_has_exactly_the_contract_keys():
    for p in bom.parse(SPIKE_LIST):
        assert set(p) == {"ref", "value", "kind", "package", "qty"}


def test_kicad_like_csv_with_semicolons_and_quotes():
    parts = bom.parse(KICAD_SEMICOLON)
    p = _by_ref(parts)
    assert sorted(p) == ["C1", "C2", "C3", "D1", "J1", "J2", "Q1", "R1", "R2"]  # R3 is DNP, ranges and lists expanded
    assert p["C1"]["kind"] == "ceramic" and p["C3"]["kind"] == "ceramic"
    assert p["C2"]["kind"] == "electrolytic"
    assert p["C2"]["package"] == "CP_Radial_D6.3mm_P2.50mm"  # library nickname stripped
    assert p["D1"]["kind"] == "led"
    assert p["J1"]["kind"] == "header" and p["J2"]["kind"] == "header"
    assert p["R1"]["value"] == "4,7k" and p["R1"]["qty"] == 1
    assert p["Q1"]["kind"] == "transistor"


def test_csv_header_after_preamble_and_comma_delimiter():
    text = (
        "Source: synthetic.kicad_sch\nDate: 2026-11-06\nTool: synthetic\n\n"
        "Ref,Qty,Value,Package\n"
        "\"R1,R2\",2,220,0207\n"
        "U1,1,NE555,DIP-8\n"
        "SW1,1,Tactile switch,6mm\n"
    )
    p = _by_ref(bom.parse(text))
    assert p["R1"]["value"] == "220" and p["R2"]["package"] == "0207"
    assert p["U1"]["kind"] == "ic"
    assert p["SW1"]["kind"] == "switch"


def test_designator_and_quantity_header_aliases_tab_separated():
    text = "Designator\tComment\tFootprint\tQuantity\nY1\t16MHz\tHC-49\t1\nL1\t10uH\tAxial\t1\n"
    p = _by_ref(bom.parse(text))
    assert p["Y1"]["kind"] == "crystal" and p["Y1"]["value"] == "16MHz"
    assert p["L1"]["kind"] == "inductor"


def test_list_form_variants():
    text = """
    - R1, R2: 10k
    R4-R6 4k7 (0207)
    C5 = 22pF [0805]
    LED1 green (5mm)
    RV1 10k trimmer
    BZ1 active buzzer
    TP1
    F1 500mA fuse
    K1 5V relay
    BT1 LiPo 3.7 V
    // comment
    SW2 | push button | 6x6 | 1
    """
    p = _by_ref(bom.parse(text))
    assert sorted(p) == sorted(["R1", "R2", "R4", "R5", "R6", "C5", "LED1", "RV1", "BZ1", "TP1", "F1", "K1", "BT1", "SW2"])
    assert p["R5"]["value"] == "4k7" and p["R5"]["package"] == "0207"
    assert p["C5"]["kind"] == "ceramic" and p["C5"]["package"] == "0805"
    assert p["LED1"]["kind"] == "led" and p["LED1"]["package"] == "5mm"
    assert p["RV1"]["kind"] == "potentiometer"
    assert p["BZ1"]["kind"] == "buzzer"
    assert p["TP1"]["kind"] == "test_point" and p["TP1"]["value"] == ""
    assert p["F1"]["kind"] == "fuse"
    assert p["K1"]["kind"] == "relay"
    assert p["BT1"]["kind"] == "battery"
    assert p["SW2"]["value"] == "push button" and p["SW2"]["package"] == "6x6"


def test_space_separated_refs_with_the_same_prefix():
    p = _by_ref(bom.parse("R1 R2 10k\nQ1 Q2 BC547\nQ3 BC557"))
    assert p["R1"]["value"] == p["R2"]["value"] == "10k"
    assert p["Q2"]["value"] == "BC547"
    assert p["Q3"]["value"] == "BC557"  # a part name is not taken for a reference


def test_rows_dicts_lists_and_given_kind():
    rows = [
        {"ref": "R1", "kind": "resistor", "value": "1 kΩ", "from_calc": "npn-1"},
        {"Reference": "C9", "Value": "1uF"},  # unclear by value, no package
        {"ref": "Q1", "kind": "NPN", "value": "2N2222A", "package": "TO-92"},
        {"ref": ["J3", "J4"], "value": "JST-XH 2-pin"},
        ["D2", "1N4148", "DO-35"],
        "U2 ESP32-S3-DevKitC-1",
        {"ref": "C7", "kind": "capacitor", "value": "470uF 16V"},
    ]
    p = _by_ref(bom.parse(rows))
    assert p["R1"]["kind"] == "resistor"
    assert p["C9"]["kind"] == "capacitor"  # cannot tell ceramic from electrolytic -> ask
    assert p["Q1"]["kind"] == "transistor"
    assert p["J3"]["kind"] == "connector" and p["J4"]["kind"] == "connector"
    assert p["D2"]["kind"] == "diode" and p["D2"]["package"] == "DO-35"
    assert p["U2"]["kind"] == "module"
    assert p["C7"]["kind"] == "electrolytic"


@pytest.mark.parametrize(("value", "package", "kind", "basis"), [
    ("100nF", "", "ceramic", "value"),
    ("0.1 uF", "", "ceramic", "value"),
    ("22p", "", "ceramic", "value"),
    ("100 µF/10 V", "", "electrolytic", "value"),
    ("4u7", "", "capacitor", "unclear"),
    ("1uF", "", "capacitor", "unclear"),
    ("10uF", "", "electrolytic", "value"),
    ("10uF", "C_0805_2012Metric", "ceramic", "type"),
    ("10uF X7R", "", "ceramic", "type"),
    ("1uF", "CP_Radial_D5.0mm_P2.00mm", "electrolytic", "type"),
    ("100n", "C_Rect_L7.2mm_W2.5mm_P5.00mm_FKS2_FKP2_MKS2_MKP2", "film", "type"),
    ("47uF elko", "", "electrolytic", "type"),
    ("", "", "capacitor", "unclear"),
    ("104", "", "capacitor", "unclear"),
])
def test_capacitor_classification(value, package, kind, basis):
    assert bom.classify("C1", value, package) == (kind, basis)


@pytest.mark.parametrize(("text", "farads"), [
    ("100nF", 100e-9), ("100 nF", 100e-9), ("0,1µF", 0.1e-6), ("4u7", 4.7e-6), ("2n2", 2.2e-9),
    ("100uF/10V", 100e-6), ("22 pF", 22e-12), ("10V", None), ("", None), ("100", None),
])
def test_capacitance_parser(text, farads):
    got = bom.capacitance(text)
    if farads is None:
        assert got is None
    else:
        assert got == pytest.approx(farads)


def test_unknown_prefix_is_unknown_kind():
    p = _by_ref(bom.parse("Z1 mystery part\nH1 MountingHole"))
    assert p["Z1"]["kind"] == "unknown" and p["H1"]["kind"] == "unknown"


def test_virtual_parts_are_dropped():
    text = "Reference;Value\n#PWR01;GND\nR1;1k\n"
    assert [p["ref"] for p in bom.parse(text)] == ["R1"]


@pytest.mark.parametrize(("bad", "fragment"), [
    ("", "empty"),
    ("   \n# only a comment\n", "empty"),
    ("R1 1k\nR1 2k", "duplicate reference R1"),
    ("R? 1k", "not annotated"),
    ("Resistor 10k", "cannot read BOM line 1"),
    ("Reference;Value;Qty\nR1;1k;two\n", "bad quantity"),
    ("Reference;Value\nR4-R2;1k\n", "bad reference range"),
    ("Reference;Value\n;1k\n", "missing reference"),
])
def test_bad_input_raises_invalid_args(bad, fragment):
    with pytest.raises(BenchError) as e:
        bom.parse(bad)
    assert e.value.code == "invalid_args"
    assert fragment in e.value.message


@pytest.mark.parametrize("bad", [None, 42, b"R1 1k", {"ref": "R1"}, [object()], [{"ref": "R1", "value": {"x": 1}}]])
def test_bad_types_raise_invalid_args(bad):
    with pytest.raises(BenchError) as e:
        bom.parse(bad)
    assert e.value.code == "invalid_args"


def test_parse_is_deterministic():
    assert bom.parse(KICAD_SEMICOLON) == bom.parse(KICAD_SEMICOLON)
