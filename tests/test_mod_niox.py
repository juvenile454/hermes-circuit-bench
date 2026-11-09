"""Module family niox: RV-3028-C7, MCP7940N, 24LC256, 24AA32A, TCA9555, PCA9555, PCA9548A.

Address, supply and level expectations run against the real generic bus and electrical rules; the family rule is
mod.niox.rtc_backup. Projects are synthetic.
"""
from __future__ import annotations

import json
from pathlib import Path

import modkit as mk
import pytest

from circuit_bench.bench_core import electrical, modcheck, modules, pins

ROOT = Path(__file__).resolve().parent.parent
NIOX = json.loads((ROOT / "circuit_bench/data/modules/niox.json").read_text(encoding="utf-8"))
PARTS = ("rv3028c7", "mcp7940n", "24lc256", "24aa32a", "tca9555", "pca9555", "pca9548a")
SOURCE = {"rv3028c7": ("mod-niox-rv3028-am", "A1"), "mcp7940n": ("mod-niox-mcp7940n-ds", "A"),
          "24lc256": ("mod-niox-24lc256-ds", "A"), "24aa32a": ("mod-niox-24aa32a-ds", "A"),
          "tca9555": ("mod-niox-tca9555-ds", "A"), "pca9555": ("mod-niox-pca9555-ds", "A"),
          "pca9548a": ("mod-niox-pca9548a-ds", "A")}
BACKUP = "mod.niox.rtc_backup"
RAILS = {"rails": {"1V0": 1.0, "1V8": 1.8, "6V": 6.0, "CELL": 3.0}}


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
    n = len(pins_)
    return {p: (hi if (value >> (n - 1 - k)) & 1 else "GND") for k, p in enumerate(pins_)}


def _status(rep, rid):
    return {f.status for f in mk.findings(rep, rid)}


# --- connections -----------------------------------------------------------------------------------------------
def rv(vdd="3V3", vb="VBK", sda="SDA0"):
    return {"SDA": sda, "SCL": sda.replace("SDA", "SCL"), "VDD": vdd, "VSS": "GND", "VBACKUP": vb, "EVI": "GND"}


def mcp(vcc="3V3", vbat="GND"):
    return {"SDA": "SDA0", "SCL": "SCL0", "VCC": vcc, "VSS": "GND", "VBAT": vbat}


def ee(a=0, vcc="3V3"):
    return {"SDA": "SDA0", "SCL": "SCL0", "VCC": vcc, "VSS": "GND", "WP": "GND", **_bits(["A2", "A1", "A0"], a, vcc)}


def tca55(a=0, vcc="3V3"):
    return {"SDA": "SDA0", "SCL": "SCL0", "VCC": vcc, "GND": "GND", **_bits(["A2", "A1", "A0"], a, vcc)}


def pca55(a=0, vdd="3V3"):
    return {"SDA": "SDA0", "SCL": "SCL0", "VDD": vdd, "VSS": "GND", **_bits(["A2", "A1", "A0"], a, vdd)}


def mux(a=0, vdd="3V3", channels=(0, 1)):
    ch = {}
    for c in channels:
        ch[f"SD{c}"], ch[f"SC{c}"] = f"SDA0_C{c}", f"SCL0_C{c}"
    return {"SDA": "SDA0", "SCL": "SCL0", "VDD": vdd, "VSS": "GND", "RESET": "RST",
            **_bits(["A2", "A1", "A0"], a, vdd), **ch}


def pullups(to="3V3"):
    return [{"ref": "R1", "kind": "resistor", "value": "4k7", "conn": {"1": "SDA0", "2": to}},
            {"ref": "R2", "kind": "resistor", "value": "4k7", "conn": {"1": "SCL0", "2": to}}]


# --- data ------------------------------------------------------------------------------------------------------
def test_catalog_has_all_niox_parts_without_problems(cat):
    assert [p for p in cat.problems if p.startswith("niox.json")] == []
    assert [m["id"] for m in NIOX["modules"]] == list(PARTS)
    for mid in PARTS:
        e = cat.get(mid)
        sid, cls = SOURCE[mid]
        assert e["source_ids"] == [sid] and cat.source_class(sid) == cls
        assert e["kind"] == "ic"


def test_ids_and_aliases_resolve_to_niox(cat):
    # duplicates across files are a loader problem (checked above); here: every name lands on this file's entry
    for m in NIOX["modules"]:
        for name in (m["id"], *m.get("aliases", [])):
            e = cat.get(name)
            assert (e["id"], e["_wp"]) == (m["id"], "niox")


@pytest.mark.parametrize(("mid", "lo", "hi"), [
    ("24lc256", 0x50, "VCC"), ("24aa32a", 0x50, "VCC"), ("tca9555", 0x20, "VCC"), ("pca9555", 0x20, "VDD"),
    ("pca9548a", 0x70, "VDD")])
def test_address_select_maps_cover_every_address(cat, mid, lo, hi):
    it = modcheck.i2c_iface(cat.get(mid))
    assert it is not None and it["select"]["pins"] == ["A2", "A1", "A0"]
    assert modcheck.addresses(it) == [f"0x{lo + i:02x}" for i in range(8)]
    m = it["select"]["map"]
    assert m["GND,GND,GND"] == f"0x{lo:02x}" and m[f"{hi},GND,{hi}"] == f"0x{lo + 5:02x}"
    assert sorted(m.values()) == modcheck.addresses(it)


@pytest.mark.parametrize(("mid", "addr"), [("rv3028c7", "0x52"), ("mcp7940n", "0x6f")])
def test_rtc_addresses_are_fixed(cat, mid, addr):
    it = modcheck.i2c_iface(cat.get(mid))
    assert it is not None and modcheck.addresses(it) == [addr] and "select" not in it


def test_pca9548a_mux_channels_and_evidence(cat):
    e = cat.get("pca9548a")
    it = modcheck.i2c_iface(e)
    assert it is not None
    assert modcheck.mux_channels(it) == [(str(c), f"SD{c}", f"SC{c}") for c in range(8)]
    assert any("Multiple channels can be enabled at the same time." in str(n.get("evidence")) for n in e["notes"])


def test_variants_change_supply_and_speed(cat):
    assert cat.get("24lc256", "24aa256")["supplies"]["VCC"]["min"]["value"] == 1.7
    it = modcheck.i2c_iface(cat.get("24lc256", "24fc256"))
    assert it is not None and it["f_max_hz"]["value"] == 1e6
    assert cat.get("24aa32a", "24lc32a")["supplies"]["VCC"]["min"]["value"] == 2.5


def test_ports_and_pins(cat):
    by = {p["name"]: p for p in cat.get("tca9555")["pins"]}
    assert all(f"P{a}{b}" in by for a in (0, 1) for b in range(8))
    by = {p["name"]: p for p in cat.get("pca9555")["pins"]}
    assert all(f"IO{a}_{b}" in by for a in (0, 1) for b in range(8))
    for mid in ("24lc256", "24aa32a"):
        by = {p["name"]: p for p in cat.get(mid)["pins"]}
        assert all(by[p]["must_connect"] for p in ("A0", "A1", "A2", "WP"))
    assert cat.get("rv3028c7")["io"]["five_v_tolerant"] is False


# --- addresses ---------------------------------------------------------------------------------------------------
@pytest.mark.parametrize(("a", "b", "addr"), [
    (mk.mod("U1", "rv3028c7", rv()), mk.mod("U2", "24lc256", ee(0b010)), "0x52"),
    (mk.mod("U1", "rv3028c7", rv()), mk.mod("U2", "24aa32a", ee(0b010)), "0x52"),
    (mk.mod("U1", "rv3028c7", rv()), mk.mod("U2", "at24c32", None), None),
    (mk.mod("U1", "mcp7940n", mcp()), mk.mod("U2", "mcp7940n", mcp()), "0x6f"),
    (mk.mod("U1", "24lc256", ee(7)), mk.mod("U2", "24aa32a", ee(7)), "0x57"),
    (mk.mod("U1", "tca9555", tca55(0)), mk.mod("U2", "mcp23017", {
        "SDA": "SDA0", "SCL": "SCL0", "VDD": "3V3", "VSS": "GND", "RESET": "3V3", "A2": "GND", "A1": "GND",
        "A0": "GND"}), "0x20"),
    (mk.mod("U1", "pca9555", pca55(7)), mk.mod("U2", "pcf8574", {
        "SDA": "SDA0", "SCL": "SCL0", "VCC": "3V3", "GND": "GND", "A2": "3V3", "A1": "3V3", "A0": "3V3"}), "0x27"),
    (mk.mod("U1", "tca9555", tca55(3)), mk.mod("U2", "pca9555", pca55(3)), "0x23"),
    (mk.mod("U1", "pca9548a", mux(0, channels=())), mk.mod("U2", "tca9548a", {
        "SDA": "SDA0", "SCL": "SCL0", "VCC": "3V3", "GND": "GND", "RESET": "3V3", "A2": "GND", "A1": "GND",
        "A0": "GND"}), "0x70"),
])
def test_address_conflicts(cat, esp, a, b, addr):
    if addr is None:  # AT24C32 default (A0–A2 open = internal pull-downs) is 0x50: no clash with the fixed 0x52
        rep = _run(cat, esp, [a, b], only=("mod.address_conflict",))
        assert "mod_address_conflict" not in mk.codes(rep)
        return
    rep = _run(cat, esp, [a, b], only=("mod.address_conflict",))
    assert _devs(rep)["U1"][1] == _devs(rep)["U2"][1] == addr
    assert "mod_address_conflict" in mk.codes(rep)


def test_ens160_shares_the_rv3028_address(cat, esp):
    if not cat.has("ens160"):
        pytest.skip("ENS160 is not in the catalog (yet)")
    it = modcheck.i2c_iface(cat.get("ens160"))
    assert it is not None and "0x52" in modcheck.addresses(it)


def test_distinct_addresses_pass(cat, esp):
    rep = _run(cat, esp, [mk.mod("U1", "rv3028c7", rv()), mk.mod("U2", "mcp7940n", mcp()),
                          mk.mod("U3", "24lc256", ee(0)), mk.mod("U4", "24aa32a", ee(1)),
                          mk.mod("U5", "tca9555", tca55(0)), mk.mod("U6", "pca9555", pca55(1)),
                          mk.mod("U7", "pca9548a", mux(2, channels=()))], only=("mod.address_conflict",))
    assert {r: a for r, (_, a) in _devs(rep).items()} == {
        "U1": "0x52", "U2": "0x6f", "U3": "0x50", "U4": "0x51", "U5": "0x20", "U6": "0x21", "U7": "0x72"}
    assert "mod_address_conflict" not in mk.codes(rep)


def test_mux_separates_two_rv3028(cat, esp):
    rep = _run(cat, esp, [mk.mod("U1", "pca9548a", mux(0)), mk.mod("U2", "rv3028c7", rv(sda="SDA0_C0")),
                          mk.mod("U3", "rv3028c7", rv(sda="SDA0_C1"))], only=("mod.address_conflict",))
    assert _devs(rep) == {"U1": ("main", "0x70"), "U2": ("U1.0", "0x52"), "U3": ("U1.1", "0x52")}
    assert "mod_address_conflict" not in mk.codes(rep)


def test_mux_same_channel_still_conflicts(cat, esp):
    rep = _run(cat, esp, [mk.mod("U1", "pca9548a", mux(0)), mk.mod("U2", "rv3028c7", rv(sda="SDA0_C0")),
                          mk.mod("U3", "24lc256", {**ee(0b010), "SDA": "SDA0_C0", "SCL": "SCL0_C0"})],
               only=("mod.address_conflict",))
    assert "mod_address_conflict" in mk.codes(rep)


def test_pca9685_all_call_sees_the_pca9548a(cat, esp):
    pca = {"SDA": "SDA0", "SCL": "SCL0", "VDD": "3V3", "VSS": "GND", "OE": "GND", "EXTCLK": "GND",
           **_bits(["A5", "A4", "A3", "A2", "A1", "A0"], 0, "3V3")}
    rule = "mod.iox.pca9685_allcall"
    rep = _run(cat, esp, [mk.mod("U1", "pca9685", pca), mk.mod("U2", "pca9548a", mux(0, channels=()))], only=(rule,))
    assert [(f.status, f.severity) for f in mk.findings(rep, rule)] == [("failed", "caution")]
    rep = _run(cat, esp, [mk.mod("U1", "pca9685", pca), mk.mod("U2", "pca9548a", mux(1, channels=()))], only=(rule,))
    assert _status(rep, rule) == {"passed"}


# --- supply ------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize(("part", "status"), [
    (mk.mod("U1", "rv3028c7", rv("1V0")), "failed"),                              # I²C from 1.2 V
    (mk.mod("U1", "rv3028c7", rv("1V8")), "passed"),
    (mk.mod("U1", "rv3028c7", rv("6V")), "failed"),                               # max 5.5 V
    (mk.mod("U1", "mcp7940n", mcp("1V8")), "passed"),                             # min 1.8 V
    (mk.mod("U1", "mcp7940n", mcp("6V")), "failed"),
    (mk.mod("U1", "24lc256", ee(0, "1V8")), "failed"),                            # 24LC256 min 2.5 V
    (mk.mod("U1", "24lc256", ee(0, "1V8"), variant="24aa256"), "passed"),         # 24AA256 min 1.7 V
    (mk.mod("U1", "24aa32a", ee(0, "1V8")), "passed"),                            # min 1.7 V
    (mk.mod("U1", "24aa32a", ee(0, "1V8"), variant="24lc32a"), "failed"),         # 24LC32A min 2.5 V
    (mk.mod("U1", "tca9555", tca55(0, "1V8")), "passed"),                         # min 1.65 V
    (mk.mod("U1", "tca9555", tca55(0, "6V")), "failed"),
    (mk.mod("U1", "pca9555", pca55(0, "1V8")), "failed"),                         # min 2.3 V
    (mk.mod("U1", "pca9555", pca55(0, "5V")), "passed"),
    (mk.mod("U1", "pca9548a", mux(0, "1V8")), "failed"),                          # min 2.3 V
    (mk.mod("U1", "pca9548a", mux(0, "5V")), "passed"),
])
def test_supply_range(cat, esp, part, status):
    rep = _run(cat, esp, [part], options=RAILS, only=("mod.supply_range",))
    main = [f for f in mk.findings(rep, "mod.supply_range") if "VBACKUP" not in f.message and "VBAT" not in f.message]
    assert {f.status for f in main} == {status}


def test_backup_inputs_are_range_checked(cat, esp):
    rep = _run(cat, esp, [mk.mod("U1", "rv3028c7", rv(vb="6V")), mk.mod("U2", "mcp7940n", mcp(vbat="6V"))],
               options=RAILS, only=("mod.supply_range",))
    bad = [f for f in mk.findings(rep, "mod.supply_range") if f.status == "failed"]
    assert sorted(f.refs[0] for f in bad) == ["U1", "U2"]
    assert all("VBACKUP" in f.message or "VBAT" in f.message for f in bad)
    # unused backup on GND is allowed by the data (no minimum)
    rep = _run(cat, esp, [mk.mod("U1", "mcp7940n", mcp())], options=RAILS, only=("mod.supply_range",))
    assert _status(rep, "mod.supply_range") == {"passed"}


# --- levels ------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("part", [mk.mod("U1", "mcp7940n", mcp("5V")), mk.mod("U1", "rv3028c7", rv("5V")),
                                  mk.mod("U1", "tca9555", tca55(0, "5V")), mk.mod("U1", "24lc256", ee(0, "5V"))])
def test_5v_parts_on_a_3v3_bus_miss_vih(cat, esp, part):
    rep = _run(cat, esp, [part, *pullups("3V3")], only=("mod.level_in",))
    fs = [f for f in mk.findings(rep, "mod.level_in") if f.status == "failed"]
    assert fs and all(f.severity == "caution" for f in fs)


def test_rv3028_vih_is_0_8_vdd(cat, esp):
    rep = _run(cat, esp, [mk.mod("U1", "rv3028c7", rv("5V")), *pullups("3V3")], only=("mod.level_in",))
    assert any("4.00 V" in f.message for f in mk.findings(rep, "mod.level_in"))


@pytest.mark.parametrize("part", [mk.mod("U1", "mcp7940n", mcp()), mk.mod("U1", "pca9548a", mux(0)),
                                  mk.mod("U1", "pca9555", pca55(0)), mk.mod("U1", "24aa32a", ee(0))])
def test_3v3_parts_on_a_3v3_bus_pass(cat, esp, part):
    rep = _run(cat, esp, [part, *pullups("3V3")], only=("mod.level_in",))
    assert _status(rep, "mod.level_in") == {"passed"}


def test_5v_pullups_hit_the_esp(cat, esp):
    rep = _run(cat, esp, [mk.mod("U1", "24lc256", ee(0, "5V")), *pullups("5V")], only=("mod.level_out",))
    assert {(f.status, f.severity) for f in mk.findings(rep, "mod.level_out")} == {("failed", "danger")}


# --- mod.niox.rtc_backup -------------------------------------------------------------------------------------------
def test_rv3028_vbackup_directly_on_gnd_is_info(cat, esp):
    rep = _run(cat, esp, [mk.mod("U1", "rv3028c7", rv(vb="GND"))], only=(BACKUP,))
    (f,) = mk.findings(rep, BACKUP)
    assert (f.status, f.severity, f.refs) == ("failed", "info", ["U1"])
    assert "10 kΩ" in f.message and f.source_ids == ["mod-niox-rv3028-am"]


def test_rv3028_vbackup_on_a_resistor_or_cell_passes(cat, esp):
    r = {"ref": "R9", "kind": "resistor", "value": "10k", "conn": {"1": "VBK", "2": "GND"}}
    rep = _run(cat, esp, [mk.mod("U1", "rv3028c7", rv(vb="VBK")), r], only=(BACKUP,))
    assert [(f.status, f.refs) for f in mk.findings(rep, BACKUP)] == [("passed", ["U1"])]


def test_rv3028_vbackup_open_is_left_to_unconnected(cat, esp):
    conn = rv()
    del conn["VBACKUP"]
    rep = _run(cat, esp, [mk.mod("U1", "rv3028c7", conn)], only=(BACKUP, "mod.unconnected"))
    assert mk.findings(rep, BACKUP) == []
    assert any("VBACKUP" in f.message for f in mk.findings(rep, "mod.unconnected") if f.status == "failed")


def test_mcp7940n_vbat(cat, esp):
    rep = _run(cat, esp, [mk.mod("U1", "mcp7940n", mcp(vbat="GND"))], only=(BACKUP,))
    assert _status(rep, BACKUP) == {"passed"}
    rep = _run(cat, esp, [mk.mod("U1", "mcp7940n", mcp(vbat="CELL"))], options=RAILS, only=(BACKUP,))
    (f,) = mk.findings(rep, BACKUP)
    assert (f.status, f.severity) == ("failed", "info") and "VBATEN" in f.message


def test_rule_ignores_other_parts(cat, esp):
    rep = _run(cat, esp, [mk.mod("U1", "24lc256", ee(0)), mk.mod("U2", "pca9555", pca55(0))], only=(BACKUP,))
    assert mk.findings(rep, BACKUP) == []


# --- end to end ----------------------------------------------------------------------------------------------------
def test_pins_check_reports_the_0x52_conflict_end_to_end():
    modules.clear_cache()
    parts = [{"ref": "U1", "kind": "ic", "value": "RV-3028-C7", "module": "rv3028c7", "conn": rv()},
             {"ref": "U2", "kind": "ic", "value": "24LC256", "module": "24lc256", "conn": ee(0b010)}]
    env = pins.check("esp32s3", [{"mode": "i2c_sda", "pin": 8, "net": "SDA0"}, {"mode": "i2c_scl", "pin": 9, "net": "SCL0"}],
                     parts=parts, options={})
    w = [x for x in env["warnings"] if x["code"] == "mod_address_conflict"]
    assert w and w[0]["severity"] == "caution" and "0x52" in w[0]["message"]
