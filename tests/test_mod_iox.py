"""Module family iox: MCP23017, MCP23008, PCF8574, PCF8574A, PCF8575, PCA9685, TCA9548A.

Expectations cover mod.address_conflict, mod.supply_range, the family rules mod.iox.* and the generic bus and
electrical rules. Projects are synthetic.
"""
from __future__ import annotations

import json
from pathlib import Path

import modkit as mk
import pytest

from circuit_bench.bench_core import electrical, modcheck, modules, pins

ROOT = Path(__file__).resolve().parent.parent
IOX = json.loads((ROOT / "circuit_bench/data/modules/iox.json").read_text(encoding="utf-8"))
PARTS = ("mcp23017", "mcp23008", "pcf8574", "pcf8574a", "pcf8575", "pca9685", "tca9548a")
GPX7 = "mod.iox.mcp23017_gpx7_output"
QUASI = "mod.iox.pcf8574_quasi_bidir"
ALLCALL = "mod.iox.pca9685_allcall"


@pytest.fixture(scope="module")
def cat():
    modules.clear_cache()
    return modules.catalog()


@pytest.fixture(scope="module")
def esp():
    return electrical.get("esp32s3")


def _run(cat, esp, parts, assignments=None, options=None, only=None):
    return mk.run(catalog=cat, electrical=esp, assignments=mk.i2c() if assignments is None else assignments,
                  parts=parts, options=options, only=only)


def _devs(rep):
    return {d["ref"]: (s["id"], d["address"]) for b in rep.result["buses"] for s in b["segments"] for d in s["devices"]}


def _bits(pins_, value, hi):
    """conn for address pins (MSB first) from an integer."""
    n = len(pins_)
    return {p: (hi if (value >> (n - 1 - k)) & 1 else "GND") for k, p in enumerate(pins_)}


# --- connections -----------------------------------------------------------------------------------------------
def mcp17(a=0, sda="SDA0", vdd="3V3", **extra):
    return {"SDA": sda, "SCL": sda.replace("SDA", "SCL"), "VDD": vdd, "VSS": "GND", "RESET": vdd,
            **_bits(["A2", "A1", "A0"], a, vdd), **extra}


def mcp08(a=0, vdd="3V3", **extra):
    return {"SDA": "SDA0", "SCL": "SCL0", "VDD": vdd, "VSS": "GND", "RESET": vdd, **_bits(["A2", "A1", "A0"], a, vdd),
            **extra}


def pcf(a=0, vcc="3V3", **extra):
    return {"SDA": "SDA0", "SCL": "SCL0", "VCC": vcc, "GND": "GND", **_bits(["A2", "A1", "A0"], a, vcc), **extra}


def pca(a=0, sda="SDA0", vdd="3V3"):
    return {"SDA": sda, "SCL": sda.replace("SDA", "SCL"), "VDD": vdd, "VSS": "GND", "OE": "GND", "EXTCLK": "GND",
            **_bits(["A5", "A4", "A3", "A2", "A1", "A0"], a, vdd)}


def tca(a=0, sda="SDA0", vcc="3V3", channels=(0, 1)):
    ch = {}
    for c in channels:
        ch[f"SD{c}"] = f"{sda}_C{c}"
        ch[f"SC{c}"] = f"{sda.replace('SDA', 'SCL')}_C{c}"
    return {"SDA": sda, "SCL": sda.replace("SDA", "SCL"), "VCC": vcc, "GND": "GND", "RESET": vcc,
            **_bits(["A2", "A1", "A0"], a, vcc), **ch}


def bme(ref, sda):
    return mk.mod(ref, "bme280", {"SDI": sda, "SCK": sda.replace("SDA", "SCL"), "SDO": "GND", "VDD": "3V3",
                                  "VDDIO": "3V3", "GND": "GND", "CSB": "3V3"})


# --- data ------------------------------------------------------------------------------------------------------
def test_catalog_has_all_iox_parts_without_problems(cat):
    assert [p for p in cat.problems if p.startswith("iox.json")] == []
    assert {m["id"] for m in IOX["modules"]} == set(PARTS)
    for mid in PARTS:
        e = cat.get(mid)
        assert e["source_ids"] == [f"mod-iox-{mid}-ds"]
        # pcf8574/pcf8574a: the ti.com file through web.archive.org (ti.com re-stamps its PDFs daily)
        assert cat.source_class(e["source_ids"][0]) == ("A1" if mid in ("pcf8574", "pcf8574a") else "A")


@pytest.mark.parametrize(("mid", "lo", "n", "pins_"), [
    ("mcp23017", 0x20, 8, ["A2", "A1", "A0"]), ("mcp23008", 0x20, 8, ["A2", "A1", "A0"]),
    ("pcf8574", 0x20, 8, ["A2", "A1", "A0"]), ("pcf8574a", 0x38, 8, ["A2", "A1", "A0"]),
    ("pcf8575", 0x20, 8, ["A2", "A1", "A0"]), ("tca9548a", 0x70, 8, ["A2", "A1", "A0"]),
    ("pca9685", 0x40, 64, ["A5", "A4", "A3", "A2", "A1", "A0"])])
def test_address_select_maps_cover_every_address(cat, mid, lo, n, pins_):
    it = modcheck.i2c_iface(cat.get(mid))
    assert it is not None
    assert modcheck.addresses(it) == [f"0x{lo + i:02x}" for i in range(n)]
    assert it["select"]["pins"] == pins_
    hi = "VCC" if mid.startswith(("pcf", "tca")) else "VDD"
    assert hi in {p["name"] for p in cat.get(mid)["pins"]}
    m = it["select"]["map"]
    assert len(m) == n and sorted(m.values()) == modcheck.addresses(it)
    key = ",".join(hi if (n - 1) >> (len(pins_) - 1 - k) & 1 else "GND" for k in range(len(pins_)))
    assert m[key] == f"0x{lo + n - 1:02x}"


def test_tca9548a_mux_channels_and_visibility_evidence(cat):
    e = cat.get("tca9548a")
    it = modcheck.i2c_iface(e)
    assert it is not None
    assert modcheck.mux_channels(it) == [(str(c), f"SD{c}", f"SC{c}") for c in range(8)]
    names = {p["name"] for p in e["pins"]}
    assert all(f"SD{c}" in names and f"SC{c}" in names for c in range(8))
    # the datasheet says channels can be enabled together: the evidence for the mux visibility of the bus rules
    assert any("any combination of the eight channels" in " ".join(n.get("evidence") or [])
               for n in e["notes"] if isinstance(n.get("evidence"), list))


def test_pca9685_reserved_addresses(cat):
    it = modcheck.i2c_iface(cat.get("pca9685"))
    assert it is not None
    assert it["reserved"] == ["0x70", "0x00"]
    assert it["default"] == "0x40"


def test_gpx7_is_output_only_in_the_data(cat):
    for mid, pins_ in (("mcp23017", ("GPA7", "GPB7")), ("mcp23008", ("GP7",))):
        by = {p["name"]: p for p in cat.get(mid)["pins"]}
        assert all("output only" in by[p]["note"] for p in pins_)


# --- addresses ---------------------------------------------------------------------------------------------------
@pytest.mark.parametrize(("a", "b", "addr"), [
    (mk.mod("U1", "mcp23017", mcp17(0)), mk.mod("U2", "pcf8574", pcf(0)), "0x20"),
    (mk.mod("U1", "mcp23008", mcp08(7)), mk.mod("U2", "pcf8575", pcf(7)), "0x27"),
    (mk.mod("U1", "pcf8574a", pcf(4)), mk.mod("U2", "pcf8574a", pcf(4)), "0x3c"),
    (mk.mod("U1", "pca9685", pca(0b101010)), mk.mod("U2", "pca9685", pca(0b101010)), "0x6a"),
    (mk.mod("U1", "tca9548a", tca(3)), mk.mod("U2", "tca9548a", tca(3, channels=())), "0x73"),
])
def test_address_conflicts(cat, esp, a, b, addr):
    rep = _run(cat, esp, [a, b], only=("mod.address_conflict",))
    assert _devs(rep)["U1"][1] == _devs(rep)["U2"][1] == addr
    assert "mod_address_conflict" in mk.codes(rep)


def test_address_select_resolves_distinct_addresses(cat, esp):
    rep = _run(cat, esp, [mk.mod("U1", "mcp23017", mcp17(0)), mk.mod("U2", "mcp23017", mcp17(5)),
                          mk.mod("U3", "pcf8574", pcf(7)), mk.mod("U4", "pcf8574a", pcf(7)),
                          mk.mod("U5", "pca9685", pca(0)), mk.mod("U6", "tca9548a", tca(1))],
               only=("mod.address_conflict",))
    assert {r: a for r, (_, a) in _devs(rep).items()} == {
        "U1": "0x20", "U2": "0x25", "U3": "0x27", "U4": "0x3f", "U5": "0x40", "U6": "0x71"}
    assert "mod_address_conflict" not in mk.codes(rep)


def test_mux_separates_identical_addresses(cat, esp):
    rep = _run(cat, esp, [mk.mod("U1", "tca9548a", tca(0)), bme("U2", "SDA0_C0"), bme("U3", "SDA0_C1")],
               only=("mod.address_conflict",))
    assert _devs(rep) == {"U1": ("main", "0x70"), "U2": ("U1.0", "0x76"), "U3": ("U1.1", "0x76")}
    assert "mod_address_conflict" not in mk.codes(rep)


def test_mux_same_channel_still_conflicts(cat, esp):
    rep = _run(cat, esp, [mk.mod("U1", "tca9548a", tca(0)), bme("U2", "SDA0_C0"), bme("U3", "SDA0_C0")],
               only=("mod.address_conflict",))
    assert "mod_address_conflict" in mk.codes(rep)


def test_device_on_channel_conflicts_with_main_device(cat, esp):
    rep = _run(cat, esp, [mk.mod("U1", "tca9548a", tca(0)), bme("U2", "SDA0_C0"), bme("U3", "SDA0")])
    assert "mod_address_conflict" in mk.codes(rep)


# --- supply ------------------------------------------------------------------------------------------------------
RAILS = {"rails": {"1V8": 1.8, "6V": 6.0}}


@pytest.mark.parametrize(("part", "status"), [
    (mk.mod("U1", "pcf8574", pcf(0, vcc="1V8")), "failed"),       # min 2.5 V
    (mk.mod("U1", "pcf8574a", pcf(0, vcc="1V8")), "failed"),
    (mk.mod("U1", "pcf8575", pcf(0, vcc="6V")), "failed"),        # max 5.5 V
    (mk.mod("U1", "pcf8574", pcf(0, vcc="6V")), "passed"),        # max 6 V
    (mk.mod("U1", "pca9685", pca(0, vdd="1V8")), "failed"),       # min 2.3 V
    (mk.mod("U1", "pca9685", pca(0, vdd="6V")), "failed"),        # max 5.5 V
    (mk.mod("U1", "tca9548a", tca(0, vcc="1V8")), "passed"),      # min 1.65 V
    (mk.mod("U1", "mcp23017", mcp17(0, vdd="1V8")), "passed"),    # min 1.8 V
    (mk.mod("U1", "mcp23008", mcp08(0, vdd="6V")), "failed"),     # max 5.5 V
    (mk.mod("U1", "mcp23017", mcp17(0, vdd="5V")), "passed"),
])
def test_supply_range(cat, esp, part, status):
    rep = _run(cat, esp, [part], options=RAILS, only=("mod.supply_range",))
    assert {f.status for f in mk.findings(rep, "mod.supply_range")} == {status}


def test_mcp23017_5v_int_into_esp_input(cat, esp):
    rep = _run(cat, esp, [mk.mod("U1", "mcp23017", mcp17(0, vdd="5V", INTA="GPIO4"))],
               assignments=[*mk.i2c(), mk.assign("in", 4)])
    assert rep is not None
    assert any(w["severity"] == "danger" and "U1" in w["refs"] for w in rep.warnings if w["code"] != "mod_supply_range")


# --- mod.iox.mcp23017_gpx7_output --------------------------------------------------------------------------------
def test_gpx7_read_from_a_switch_is_info(cat, esp):
    parts = [mk.mod("U1", "mcp23017", mcp17(0, GPA7="BTN")),
             {"ref": "SW1", "kind": "switch", "value": "button", "conn": {"1": "BTN", "2": "GND"}}]
    rep = _run(cat, esp, parts, only=(GPX7,))
    (f,) = mk.findings(rep, GPX7)
    assert (f.status, f.severity, f.refs) == ("failed", "info", ["U1"])
    assert "GPA7" in f.message and "SW1" in f.message
    assert f.source_ids == ["mod-iox-mcp23017-ds"]
    assert "mod_iox_mcp23017_gpx7_output" in mk.codes(rep)


def test_gpx7_driven_by_esp_or_module_output_or_rail(cat, esp):
    parts = [mk.mod("U1", "mcp23017", mcp17(0, GPB7="GPIO5", GPA7="3V3")),
             mk.mod("U2", "mcp23008", mcp08(1, GP7="INTX")),
             mk.mod("U3", "pcf8574", pcf(2, INT="INTX"))]
    rep = _run(cat, esp, parts, assignments=[*mk.i2c(), mk.assign("out", 5)], only=(GPX7,))
    fs = {(f.refs[0], f.status) for f in mk.findings(rep, GPX7)}
    assert fs == {("U1", "failed"), ("U2", "failed")}
    msgs = " ".join(f.message for f in mk.findings(rep, GPX7))
    assert "GPIO5" in msgs and "rail 3V3" in msgs and "U3.INT" in msgs and "GP7" in msgs


def test_gpx7_as_output_passes_and_unused_is_silent(cat, esp):
    parts = [mk.mod("U1", "mcp23017", mcp17(0, GPA7="LED_K")),
             {"ref": "D1", "kind": "led", "value": "red", "conn": {"A": "3V3_R", "K": "LED_K"}},
             mk.mod("U2", "mcp23017", mcp17(1))]
    rep = _run(cat, esp, parts, only=(GPX7,))
    assert [(f.refs, f.status) for f in mk.findings(rep, GPX7)] == [(["U1"], "passed")]


def test_gpx7_rule_ignores_other_parts(cat, esp):
    rep = _run(cat, esp, [mk.mod("U1", "pcf8574", pcf(0, P7="BTN")),
                          {"ref": "SW1", "kind": "switch", "value": "b", "conn": {"1": "BTN", "2": "GND"}}], only=(GPX7,))
    assert mk.findings(rep, GPX7) == []


# --- mod.iox.pcf8574_quasi_bidir ---------------------------------------------------------------------------------
@pytest.mark.parametrize("mid", ["pcf8574", "pcf8574a"])
def test_quasi_led_load_is_info(cat, esp, mid):
    parts = [mk.mod("U1", mid, pcf(0, P0="LEDA")), {"ref": "D1", "kind": "led", "value": "red",
                                                    "conn": {"A": "LEDA", "K": "GND"}}]
    rep = _run(cat, esp, parts, only=(QUASI,))
    (f,) = mk.findings(rep, QUASI)
    assert (f.status, f.severity) == ("failed", "info")
    assert "P0" in f.message and "D1 (led)" in f.message and "µA" in f.message


def test_quasi_pcf8575_drives_a_module_input_and_a_transistor_by_ref(cat, esp):
    parts = [mk.mod("U1", "pcf8575", pcf(0, P00="OE_N", P17="QB")), mk.mod("U2", "pca9685", pca(0)),
             {"ref": "Q1", "value": "2N2222", "conn": {"B": "QB", "E": "GND"}}]
    parts[1]["conn"]["OE"] = "OE_N"
    rep = _run(cat, esp, parts, only=(QUASI,))
    msgs = [f.message for f in mk.findings(rep, QUASI, "failed")]
    # one finding per expander, only the current load: a CMOS logic input is fine with the weak high
    assert len(msgs) == 1
    assert "Q1 (transistor)" in msgs[0] and "P17" in msgs[0] and "U2.OE" not in msgs[0]


def test_quasi_logic_inputs_only_pass_in_one_finding(cat, esp):
    # an LCD backpack: seven port pins drive module logic inputs -> no info flood, no wrong advice (p14)
    lcd = {f"P{i}": f"L{i}" for i in range(8)}
    parts = [mk.mod("U1", "pcf8574", pcf(0, **lcd))]
    parts += [mk.mod(f"U{i + 2}", "pca9685", {**pca(i + 1), "OE": f"L{i}"}) for i in range(7)]
    rep = _run(cat, esp, parts, only=(QUASI,))
    fs = mk.findings(rep, QUASI)
    assert [(f.status, f.refs) for f in fs] == [("passed", ["U1"])]
    assert "P0, P1" in fs[0].message and "logic inputs" in fs[0].message


def test_quasi_many_leds_give_one_finding(cat, esp):
    leds = [{"ref": f"D{i}", "kind": "led", "value": "red", "conn": {"A": f"LED{i}", "K": "GND"}} for i in range(6)]
    parts = [mk.mod("U1", "pcf8574", pcf(0, **{f"P{i}": f"LED{i}" for i in range(6)})), *leds]
    rep = _run(cat, esp, parts, only=(QUASI,))
    (f,) = mk.findings(rep, QUASI)
    assert (f.status, f.severity) == ("failed", "info")
    assert f.message.startswith("U1 (pcf8574): 6 port pin(s)") and "and 2 more" in f.message and "P0/P1/P2/P3" in f.message


def test_quasi_without_loads_passes_and_rails_are_ignored(cat, esp):
    parts = [mk.mod("U1", "pcf8574", pcf(0, P0="SENSE", P1="GND"))]
    rep = _run(cat, esp, parts, only=(QUASI,))
    assert [(f.status, f.refs) for f in mk.findings(rep, QUASI)] == [("passed", ["U1"])]
    rep = _run(cat, esp, [mk.mod("U1", "pcf8574", pcf(0))], only=(QUASI,))
    assert mk.findings(rep, QUASI) == []


# --- mod.iox.pca9685_allcall -------------------------------------------------------------------------------------
def test_allcall_tca_at_0x70_is_danger(cat, esp):
    rep = _run(cat, esp, [mk.mod("U1", "pca9685", pca(0)), mk.mod("U2", "tca9548a", tca(0, channels=()))],
               only=(ALLCALL, "mod.address_conflict"))
    (f,) = mk.findings(rep, ALLCALL)
    # two devices answer one address: wrong data, no damage (open-drain bus) -> caution
    assert (f.status, f.severity, f.refs) == ("failed", "caution", ["U1", "U2"])
    assert "0x70" in f.message and "0x71" in f.message and f.supersedes == ("mod.address_reserved",)
    assert "mod_address_conflict" not in mk.codes(rep)  # different addresses: only the family rule sees it


def test_allcall_folds_the_generic_reserved_finding(cat, esp):
    rep = _run(cat, esp, [mk.mod("U1", "pca9685", pca(0)), mk.mod("U2", "tca9548a", tca(0, channels=()))],
               only=(ALLCALL, "mod.address_reserved"))
    codes = [w["code"] for w in rep.warnings]
    assert codes.count("mod_iox_pca9685_allcall") == 1 and "mod_address_reserved" not in codes  # one warning (p24)
    assert mk.check_of(rep, "mod.address_reserved")["detail"].startswith("covered by mod_iox_pca9685_allcall")


def test_allcall_mux_moved_to_0x71_passes(cat, esp):
    rep = _run(cat, esp, [mk.mod("U1", "pca9685", pca(0)), mk.mod("U2", "tca9548a", tca(1, channels=()))],
               only=(ALLCALL,))
    assert [(f.status, f.refs) for f in mk.findings(rep, ALLCALL)] == [("passed", ["U1"])]


def test_allcall_pca_behind_the_mux_still_sees_it(cat, esp):
    rep = _run(cat, esp, [mk.mod("U1", "tca9548a", tca(0)), mk.mod("U2", "pca9685", pca(0, sda="SDA0_C0"))],
               only=(ALLCALL,))
    assert _devs(rep)["U2"] == ("U1.0", "0x40")
    assert [(f.status, f.severity) for f in mk.findings(rep, ALLCALL)] == [("failed", "caution")]


def test_allcall_other_channel_is_not_visible(cat, esp):
    rep = _run(cat, esp, [mk.mod("U1", "tca9548a", tca(1)), mk.mod("U2", "pca9685", pca(0, sda="SDA0_C0")),
                          mk.mod("U3", "tca9548a", tca(0, sda="SDA0_C1", channels=()))], only=(ALLCALL,))
    assert _devs(rep)["U3"] == ("U1.1", "0x70")
    assert [f.status for f in mk.findings(rep, ALLCALL)] == ["passed"]


def test_allcall_pca_set_to_0x70_itself(cat, esp):
    rep = _run(cat, esp, [mk.mod("U1", "pca9685", pca(0b110000))], only=(ALLCALL,))
    assert _devs(rep)["U1"][1] == "0x70"
    (f,) = mk.findings(rep, ALLCALL)
    assert (f.status, f.severity) == ("failed", "caution") and "own LED All Call" in f.message


def test_allcall_two_pca9685_are_fine(cat, esp):
    rep = _run(cat, esp, [mk.mod("U1", "pca9685", pca(0)), mk.mod("U2", "pca9685", pca(1))], only=(ALLCALL,))
    assert {f.status for f in mk.findings(rep, ALLCALL)} == {"passed"}


def test_allcall_pca_off_bus_gives_no_finding(cat, esp):
    rep = _run(cat, esp, [mk.mod("U1", "pca9685", {"VDD": "3V3", "VSS": "GND"})], only=(ALLCALL,))
    assert mk.findings(rep, ALLCALL) == []


def test_reserved_generic_rule_sees_allcall(cat, esp):
    rep = _run(cat, esp, [mk.mod("U1", "pca9685", pca(0)), mk.mod("U2", "tca9548a", tca(0, channels=()))])
    assert mk.findings(rep, "mod.address_reserved", "failed")
    # one cause, one warning: the generic finding is folded into the family warning
    assert "mod_iox_pca9685_allcall" in mk.codes(rep) and "mod_address_reserved" not in mk.codes(rep)


# --- end to end ----------------------------------------------------------------------------------------------------
def test_pins_check_reports_allcall_end_to_end():
    modules.clear_cache()
    parts = [{"ref": "U1", "kind": "ic", "value": "PCA9685", "module": "pca9685", "conn": pca(0)},
             {"ref": "U2", "kind": "ic", "value": "TCA9548A", "module": "tca9548a", "conn": tca(0, channels=())}]
    env = pins.check("esp32s3", [{"mode": "i2c_sda", "pin": 8, "net": "SDA0"}, {"mode": "i2c_scl", "pin": 9, "net": "SCL0"}],
                     parts=parts, options={})
    w = [x for x in env["warnings"] if x["code"] == "mod_iox_pca9685_allcall"]
    assert len(w) == 1 and w[0]["source_ids"][0] == "mod-iox-pca9685-ds"
    assert "mod_address_reserved" not in {x["code"] for x in env["warnings"]}  # folded into the family finding
