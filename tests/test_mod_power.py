"""Module family power: catalog entries, regulator data (data/parts/power2.json), calculators
calc.buck / calc.charger and the family rules of modrules/power.py.

Every quoted number of power2.json and of the calculators' DATA tables is checked against the committed excerpts
tests/corpus/excerpts/mod-power-*.txt (page + verbatim line parts); the catalog entries are checked by
tests/test_m0_modules_data.py. Projects are synthetic. Hand calculations in the comments.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import excerpts as ex
import modkit as mk
from circuit_bench.bench_core import calc_power, calckit, electrical, modules, parts, sources
from circuit_bench.bench_core.calcs import buck as buck_calc
from circuit_bench.bench_core.calcs import charger as charger_calc
from circuit_bench.bench_core.modrules import power as rules

ROOT = Path(__file__).resolve().parent.parent
POWER2 = ROOT / "circuit_bench" / "data" / "parts" / "power2.json"
ESP = electrical.get("esp32s3")
EXC = {e.source_id: e for e in ex.excerpts("mod-power-*.txt")}
PARTS = {"ap2112k_33": "A", "ht7333": "A", "mcp1700": "A", "xc6206": "A1", "me6211": "A2", "lm2596": "A",
         "mp1584": "A1", "mcp73831": "A", "tp4056": "A"}
REL = 1e-9


def _cited(source_id: str, page: int, evidence) -> bool:
    want = [evidence] if isinstance(evidence, str) else list(evidence)
    return any(ex.find_parts_in_order(want, seg) for seg in EXC[source_id].page_segments(page)) or \
        ex.find_parts_in_order(want, [ln for seg in EXC[source_id].page_segments(page) for ln in seg])


def _run(*project_parts, options=None, only=None):
    return mk.run(electrical=ESP, parts=list(project_parts), options=options, only=only)


def _f(rep, rule_id, status=None):
    return mk.findings(rep, rule_id, status)


def _checks(env):
    return {c["id"].rsplit(".", 1)[1]: c["status"] for c in env["checks"]}


def _codes(env):
    return {w["code"] for w in env["warnings"]}


def cap(ref, net, value="1uF", **kw):
    return {"ref": ref, "kind": "capacitor", "value": value, "conn": {"1": net, "2": "GND"}, **kw}


# --- catalog, sources, data ----------------------------------------------------------------------------------------
def test_all_nine_parts_are_in_the_catalog_with_their_class():
    cat = modules.catalog()
    assert [p for p in cat.problems if "power.json" in p] == []
    for mid, cls in PARTS.items():
        entry = cat.get(mid)
        assert entry["_wp"] == "power" and entry["_class"] == cls, mid
        assert entry["category"].startswith("power.")
    assert cat.get("AP2112K-3.3")["id"] == "ap2112k_33" and cat.get("MCP1700T-3302E")["id"] == "mcp1700"


def test_chargers_carry_the_li_ion_hazard():
    for mid in ("mcp73831", "tp4056"):
        hz = modules.catalog().get(mid)["hazards"]
        assert [h["code"] for h in hz] == ["li_ion"] and "fire" in hz[0]["text"]


def test_sources_resolve_and_match_the_manifest():
    manifest = {f["source_id"]: f for f in json.loads((ROOT / "tests/corpus/mod-power.json").read_text())["files"]}
    assert set(manifest) == {f"mod-power-{k}-ds" for k in ("ap2112", "ht7333", "mcp1700", "xc6206", "me6211",
                                                           "lm2596", "mp1584", "mcp73831", "tp4056")}
    for sid, f in manifest.items():
        src = sources.get(sid)
        assert src["url"] == f["url"] and f["sha256"] in src["note"]
        assert EXC[sid].meta["corpus"] == f"{f['path']} sha256 {f['sha256']}"
    assert sources.get("mod-power-me6211-ds")["class"] == "A2" and "copy hosted by LCSC" in sources.get(
        "mod-power-me6211-ds")["title"]
    assert "NanJing Top Power" in sources.get("mod-power-tp4056-ds")["title"]
    assert manifest["mod-power-xc6206-ds"]["url"].startswith("https://web.archive.org/web/")


def _power2():
    return json.loads(POWER2.read_text(encoding="utf-8"))["parts"]


def _quoted(obj, path=""):
    if isinstance(obj, dict):
        if "evidence" in obj:
            yield path, obj
        for k, v in obj.items():
            if k != "evidence":
                yield from _quoted(v, f"{path}.{k}")
    elif isinstance(obj, list | tuple):
        for i, v in enumerate(obj):
            yield from _quoted(v, f"{path}[{i}]")


def test_power2_values_quote_the_excerpts():
    seen = 0
    for part in _power2():
        for path, item in _quoted(part):
            assert _cited(part["source_id"], item["page"], item["evidence"]), (part["id"], path)
            seen += 1
    assert seen >= 30


def test_power2_numbers_match_their_lines():
    p = {x["id"]: x for x in _power2()}
    ap = p["AP2112K-3.3"]
    assert "250 400" in ap["dropout"]["evidence"] and ap["dropout"]["value"] == 0.4 and ap["dropout"]["i_out"] == 0.6
    assert ap["ratings"]["r_th_ja"] == {**ap["ratings"]["r_th_ja"], "value": 184.0, "evidence": "SOT25 184"}
    assert "55 80 µA" in ap["i_q"]["evidence"] and ap["i_q"]["value"] == pytest.approx(80e-6, rel=REL)
    mc = p["MCP1700-3302E/TT"]
    assert "350 mV I L = 250 mA" in mc["dropout"]["evidence"] and mc["dropout"]["value"] == 0.35
    assert mc["ratings"]["r_th_ja"]["value"] == 212.0 and mc["ratings"]["t_j_max"]["value"] == 125.0
    assert p["XC6206P332MR"]["dropout"]["evidence"] == "75 350 250 680 200" and p["XC6206P332MR"]["dropout"]["value"] == 0.68
    assert p["HT7333-A"]["dropout"]["typical_only"] and p["ME6211C33M5G-N"]["dropout"]["typical_only"]


def test_power2_kinds_and_modules():
    p = {x["id"]: x for x in _power2()}
    assert {k for k, v in p.items() if v["kind"] == "ldo"} == {"AP2112K-3.3", "MCP1700-3302E/TT"}
    for v in p.values():
        assert v["module"] in PARTS
        if v["kind"] == "ldo_partial":
            assert v["missing"]  # calc.ldo would need these values; the datasheet does not give them
    assert set(parts.ids_of("ldo_partial")) == {"XC6206P332MR", "HT7333-A", "ME6211C33M5G-N"}


def test_calculator_data_quote_the_excerpts():
    for mod in (buck_calc, charger_calc):
        for cid, d in mod.DATA.items():
            for path, item in _quoted(d):
                assert _cited(d["source_id"], item["page"], item["evidence"]), (cid, path)


def test_calculators_are_registered_without_problems():
    assert {"buck", "charger"} <= set(calckit.kinds()) and calckit.problems() == []
    meta = {m["kind"]: m for m in calckit.meta()}
    assert meta["buck"]["group"] == "power" and meta["charger"]["group"] == "power"


# --- supply range: one project per part (wrong rail) ----------------------------------------------------------------
@pytest.mark.parametrize(("mid", "conn", "rail", "volts", "status", "severity"), [
    ("ap2112k_33", {"VIN": "5V", "VOUT": "3V3", "GND": "GND", "EN": "5V"}, None, None, "passed", None),
    ("ap2112k_33", {"VIN": "V12", "VOUT": "3V3", "GND": "GND"}, "V12", 12.0, "failed", "danger"),  # > 6.5 V abs max
    ("ap2112k_33", {"VIN": "VB", "VOUT": "3V3", "GND": "GND"}, "VB", 6.2, "failed", "caution"),  # 6.0 < 6.2 ≤ 6.5
    ("ht7333", {"VIN": "V12", "VOUT": "3V3", "GND": "GND"}, "V12", 12.0, "passed", None),
    ("ht7333", {"VIN": "V15", "VOUT": "3V3", "GND": "GND"}, "V15", 15.0, "failed", "danger"),  # > 14 V
    ("mcp1700", {"VIN": "5V", "VOUT": "3V3", "GND": "GND"}, None, None, "passed", None),
    ("mcp1700", {"VIN": "V9", "VOUT": "3V3", "GND": "GND"}, "V9", 9.0, "failed", "danger"),  # > 6.5 V
    ("xc6206", {"VIN": "V9", "VOUT": "3V3", "VSS": "GND"}, "V9", 9.0, "failed", "danger"),  # > 7.0 V (A1)
    ("me6211", {"VIN": "V7", "VOUT": "3V3", "VSS": "GND", "CE": "V7"}, "V7", 7.0, "failed", "danger"),  # A2 may be hard
    ("lm2596", {"VIN": "V48", "OUTPUT": "SW", "GND": "GND", "FEEDBACK": "FB", "ON_OFF": "GND"}, "V48", 48.0,
     "failed", "danger"),  # > 45 V
    ("lm2596", {"VIN": "V24", "OUTPUT": "SW", "GND": "GND", "FEEDBACK": "FB", "ON_OFF": "GND"}, "V24", 24.0,
     "passed", None),
    ("mp1584", {"VIN": "V32", "SW": "SW", "GND": "GND", "FB": "FB"}, "V32", 32.0, "failed", "danger"),  # > 30 V
    ("mcp73831", {"VDD": "5V", "VBAT": "VBAT", "VSS": "GND", "PROG": "P"}, None, None, "passed", None),
    ("mcp73831", {"VDD": "V9", "VBAT": "VBAT", "VSS": "GND", "PROG": "P"}, "V9", 9.0, "failed", "danger"),  # > 7 V
    ("tp4056", {"VCC": "V9", "BAT": "VBAT", "GND": "GND"}, "V9", 9.0, "failed", "danger"),  # > 8 V
    ("tp4056", {"VCC": "3V3", "BAT": "VBAT", "GND": "GND"}, None, None, "failed", "caution"),  # < 4.0 V
])
def test_supply_range_per_part(mid, conn, rail, volts, status, severity):
    rails = {"VBAT": 3.7}
    if rail:
        rails[rail] = volts
    rep = _run(mk.mod("U1", mid, conn), options={"rails": rails}, only=("mod.supply_range",))
    found = _f(rep, "mod.supply_range")
    assert found, mid
    worst = next((f for f in found if f.status == "failed"), found[0])
    assert (worst.status, worst.severity) == (status, severity), worst


# --- mod.power.ldo_esr ---------------------------------------------------------------------------------------------
def test_ldo_without_output_capacitor_is_caution():
    rep = _run(mk.mod("U1", "mcp1700", {"VIN": "5V", "VOUT": "3V3", "GND": "GND"}), only=(rules.ESR_RULE,))
    (f,) = _f(rep, rules.ESR_RULE)
    assert (f.status, f.severity) == ("failed", "caution") and "1.00 µF" in f.message and "p. 13" in f.message
    assert f.source_ids == ["mod-power-mcp1700-ds"]


def test_ldo_with_output_capacitor_passes():
    for mid, gnd in (("ap2112k_33", "GND"), ("mcp1700", "GND"), ("xc6206", "VSS")):
        conn = {"VIN": "5V", "VOUT": "3V3", gnd: "GND"}
        rep = _run(mk.mod("U1", mid, conn), cap("C1", "3V3", "10uF"), only=(rules.ESR_RULE,))
        (f,) = _f(rep, rules.ESR_RULE)
        assert f.status == "passed" and f.refs == ["U1", "C1"], mid


def test_ldo_capacitor_too_small_or_esr_out_of_range():
    rep = _run(mk.mod("U1", "mcp1700", {"VIN": "5V", "VOUT": "3V3", "GND": "GND"}),
               cap("C1", "3V3", "470nF", esr="3"), only=(rules.ESR_RULE,))
    (f,) = _f(rep, rules.ESR_RULE)
    assert f.status == "failed" and "470 nF" in f.message and "ESR 3.00 Ω" in f.message
    # two capacitors add up: 470 nF + 1 µF ≥ 1 µF; ESR 1 Ω within 0–2 Ω
    rep = _run(mk.mod("U1", "mcp1700", {"VIN": "5V", "VOUT": "3V3", "GND": "GND"}),
               cap("C1", "3V3", "470nF"), cap("C2", "3V3", "1µF", esr="1"), only=(rules.ESR_RULE,))
    assert _f(rep, rules.ESR_RULE)[0].status == "passed"


def test_ldo_esr_not_checked_without_datasheet_value_and_a2_is_hard():
    rep = _run(mk.mod("U1", "ht7333", {"VIN": "5V", "VOUT": "3V3", "GND": "GND"}), only=(rules.ESR_RULE,))
    assert _f(rep, rules.ESR_RULE)[0].status == "not_checked"
    rep = _run(mk.mod("U1", "me6211", {"VIN": "5V", "VOUT": "3V3", "VSS": "GND", "CE": "5V"}), only=(rules.ESR_RULE,))
    (f,) = _f(rep, rules.ESR_RULE)
    assert f.status == "failed" and f.severity == "caution"  # A2 source: hard findings allowed


def test_ldo_esr_ignores_unconnected_vout_and_other_categories():
    rep = _run(mk.mod("U1", "mcp1700", {"VIN": "5V", "GND": "GND"}),
               mk.mod("U2", "lm2596", {"VIN": "5V", "GND": "GND"}), only=(rules.ESR_RULE,))
    assert _f(rep, rules.ESR_RULE) == []


@pytest.mark.parametrize(("text", "value"), [("1uF", 1e-6), ("4.7 µF", 4.7e-6), ("470uF 16V", 470e-6),
                                             ("100n", 100e-9), (1e-6, 1e-6), ("x", None), (True, None)])
def test_farads(text, value):
    got = rules.farads(text)
    assert got == pytest.approx(value, rel=REL) if value else got is None


# --- mod.power.li_ion ----------------------------------------------------------------------------------------------
@pytest.mark.parametrize("mid", ["mcp73831", "tp4056"])
def test_charger_is_always_danger_once(mid):
    """hazards[li_ion] gives the danger through mod.hazard; mod.power.li_ion then passes (one notice, not two)."""
    rep = _run(mk.mod("U1", mid, {"VDD" if mid == "mcp73831" else "VCC": "5V"}),
               only=(rules.LI_ION_RULE, "mod.hazard"))
    (f,) = _f(rep, rules.LI_ION_RULE)
    assert f.status == "passed" and "mod.hazard" in f.message
    (h,) = _f(rep, "mod.hazard")
    assert (h.status, h.severity) == ("failed", "danger") and "fire" in h.message
    assert [w["severity"] for w in rep.warnings] == ["danger"]


def test_charger_without_hazard_entry_still_gets_the_danger(monkeypatch):
    from circuit_bench.bench_core import modules as _m
    cat = _m.catalog()
    entry = cat.get("tp4056")
    entry["hazards"] = []
    monkeypatch.setattr(cat, "get", lambda mid, variant=None, _g=cat.get: entry if mid == "tp4056" else _g(mid, variant))
    rep = _run(mk.mod("U1", "tp4056", {"VCC": "5V"}), only=(rules.LI_ION_RULE,))
    (f,) = _f(rep, rules.LI_ION_RULE)
    assert (f.status, f.severity) == ("failed", "danger") and "fire" in f.message


def test_tp4056_module_dw01_variant():
    cat = modules.catalog()
    v = cat.get("tp4056", "module-dw01")
    assert v["kind"] == "module" and [p["name"] for p in v["pins"]] == ["IN+", "IN-", "B+", "B-", "OUT+", "OUT-"]
    assert [h["code"] for h in v["hazards"]] == ["li_ion"] and v["requires"] == []
    board = [n for n in v["notes"] if n["text"].startswith(("Module boards", "The DW01A", "Set R_PROG"))]
    assert len(board) == 3 and all(n["verified"] is False for n in board)
    rep = _run(mk.mod("U1", "tp4056", {"IN+": "5V", "IN-": "GND", "B+": "VBAT", "B-": "BATN", "OUT+": "VBAT",
                                       "OUT-": "GND"}, variant="module-dw01"),
               only=("mod.unconnected", "mod.supply_range", "mod.hazard", rules.LI_ION_RULE))
    assert not [f for f in _f(rep, "mod.unconnected") if f.status == "failed"]
    assert [(w["code"], w["severity"]) for w in rep.warnings] == [("mod_hazard", "danger")]
    rep = _run(mk.mod("U1", "tp4056", {"IN+": "5V", "IN-": "GND", "B+": "3V3"}, variant="module-dw01"),
               only=(rules.LI_ION_RULE,))
    assert any("B+ is on the 3V3 rail" in f.message for f in _f(rep, rules.LI_ION_RULE))


def test_mp1584_has_no_unguaranteed_vil_and_tp4056_vol_quotes_the_row():
    cat = modules.catalog()
    assert "vil" not in cat.get("mp1584")["io"]
    assert "0.3 0.6 V" in cat.get("tp4056")["io"]["vol"]["evidence"]


def test_charger_battery_on_3v3_is_a_second_danger():
    rep = _run(mk.mod("U1", "tp4056", {"VCC": "5V", "BAT": "3V3", "GND": "GND"}), only=(rules.LI_ION_RULE,))
    found = _f(rep, rules.LI_ION_RULE)
    assert len(found) == 2 and "4.2 V" in found[1].message and "3.60 V" in found[1].message


def test_no_charger_no_li_ion_finding():
    rep = _run(mk.mod("U1", "mcp1700", {"VIN": "5V", "VOUT": "3V3", "GND": "GND"}), only=(rules.LI_ION_RULE,))
    assert _f(rep, rules.LI_ION_RULE) == []


# --- mod.power.dropout ---------------------------------------------------------------------------------------------
def _ldo(mid, vin="VBAT"):
    gnd = "VSS" if mid in ("xc6206", "me6211") else "GND"
    return mk.mod("U1", mid, {"VIN": vin, "VOUT": "3V3", gnd: "GND"})


@pytest.mark.parametrize(("mid", "vbat", "status", "severity"), [
    ("ap2112k_33", 3.7, "passed", None),     # 3.7 − 3.3 = 0.40 V = max dropout 400 mV at 600 mA
    ("ap2112k_33", 3.6, "failed", "caution"),  # 0.30 V < 0.40 V
    ("mcp1700", 3.7, "passed", None),        # 0.40 V ≥ 0.35 V
    ("xc6206", 3.7, "failed", "caution"),    # 0.40 V < 0.68 V (A1: hard)
    ("ht7333", 3.35, "failed", "info"),      # 0.05 V < 0.09 V typical only -> info
    ("me6211", 3.5, "failed", "info"),       # 0.20 V < 0.26 V typical only
])
def test_dropout_against_the_battery_rail(mid, vbat, status, severity):
    rep = _run(_ldo(mid), options={"rails": {"VBAT": vbat}}, only=(rules.DROPOUT_RULE,))
    (f,) = _f(rep, rules.DROPOUT_RULE)
    assert (f.status, f.severity) == (status, severity), f.message


def test_dropout_only_with_a_user_rail():
    rep = _run(_ldo("xc6206", vin="5V"), only=(rules.DROPOUT_RULE,))
    assert _f(rep, rules.DROPOUT_RULE) == []
    rep = _run(mk.mod("U1", "mcp1700", {"VIN": "VBAT", "VOUT": "V3", "GND": "GND"}),
               options={"rails": {"VBAT": 3.7}}, only=(rules.DROPOUT_RULE,))
    assert _f(rep, rules.DROPOUT_RULE)[0].status == "not_checked"  # VOUT not on a known rail


# --- end to end through pins.check ---------------------------------------------------------------------------------
def test_battery_project_end_to_end():
    from circuit_bench.bench_core import pins
    env = pins.check("esp32s3", [{"role": "CHRG", "mode": "in_pullup", "pin": 4, "net": "CHRG"}], parts=[
        {"ref": "U1", "kind": "ic", "value": "TP4056", "module": "tp4056",
         "conn": {"VCC": "5V", "BAT": "VBAT", "GND": "GND", "CHRG": "CHRG"}},
        {"ref": "U2", "kind": "ic", "value": "XC6206", "module": "xc6206",
         "conn": {"VIN": "VBAT", "VOUT": "3V3", "VSS": "GND"}}], options={"rails": {"VBAT": 3.7}})
    codes = {w["code"]: w["severity"] for w in env["warnings"]}
    assert codes.get("mod_hazard") == "danger" and "mod_power_li_ion" not in codes  # one Li-Ion notice
    assert codes.get("mod_power_dropout") == "caution"
    assert codes.get("mod_power_ldo_esr") == "caution"


# --- calc.buck -----------------------------------------------------------------------------------------------------
def test_buck_lm2596_datasheet_example():
    # p. 28: VOUT = 1.23 · (1 + R2/R1); R1 = 1 kΩ, R2 = 15.4 kΩ -> 1.23 · 16.4 = 20.172 V
    env = calckit.run("buck", {"r_top": "15.4k", "r_bottom": "1k", "v_in": 28, "i_out": 3})
    assert env["ok"] and env["result"]["v_out"]["value"] == pytest.approx(20.172, abs=1e-3)
    assert _checks(env) == {"v_out_range": "passed", "r_bottom": "passed", "v_in": "passed", "headroom": "passed",
                            "i_out": "passed"}
    # VFB 1.18–1.28 V over T_J -> 19.35–20.99 V
    rng = env["result"]["v_out_range"]
    assert rng["min"]["value"] == pytest.approx(19.352, abs=1e-3) and rng["max"]["value"] == pytest.approx(20.992, abs=1e-3)
    # target 20 V with R1 = 1 kΩ: R2 ideal = 1 kΩ · (20 / 1.23 − 1) = 15.26 kΩ (datasheet), E24 -> 15 kΩ
    env = calckit.run("buck", {"v_out": 20, "r_bottom": "1k"})
    steps = {s["name"]: s["value"]["value"] for s in env["result"]["steps"]}
    assert steps["r_top ideal"] == pytest.approx(15260.16, rel=1e-4) and env["result"]["r_top"]["value"] == 15000
    assert env["result"]["deviation"]["value"] == pytest.approx((1.23 * 16 - 20) / 20 * 100, rel=1e-3)


def test_buck_mp1584_datasheet_example():
    # p. 10: R2 = 40.2 kΩ, R1 = 127 kΩ for 3.3 V: 0.8 · (127 + 40.2) / 40.2 = 3.3274 V
    env = calckit.run("buck", {"chip": "mp1584", "r_top": "127k", "r_bottom": "40.2k"})
    assert env["result"]["v_out"]["value"] == pytest.approx(0.8 * 167.2 / 40.2, rel=1e-3)
    assert _checks(env)["r_bottom"] == "passed"
    assert buck_calc.v_out_of("mp1584", 127e3, 40.2e3) == pytest.approx(0.8 * 167.2 / 40.2, rel=REL)


def test_buck_pair_search_beats_the_fixed_r_bottom():
    env = calckit.run("buck", {"v_out": 3.3})
    r = env["result"]
    assert abs(r["deviation"]["value"]) < 1.0  # 1.3 kΩ / 2.2 kΩ: 1.23 · (1 + 2.2/1.3) = 3.3115 V
    assert 240 <= r["r_bottom"]["value"] <= 1500 and "buck_set_before_connect" in _codes(env)
    env = calckit.run("buck", {"chip": "mp1584", "v_out": 3.3})
    assert abs(env["result"]["deviation"]["value"]) < 0.5 and env["result"]["r_bottom"]["value"] <= 40e3


def test_buck_limits():
    env = calckit.run("buck", {"r_top": "127k", "r_bottom": "40.2k", "chip": "mp1584", "v_in": 32})
    assert _checks(env)["v_in"] == "failed" and "buck_v_in_abs_max" in _codes(env)
    env = calckit.run("buck", {"v_out": 3.3, "v_in": 4})  # LM2596 below 4.5 V and V_IN < V_OUT + 1.4 V
    assert _checks(env)["v_in"] == "failed" and _checks(env)["headroom"] == "failed"
    env = calckit.run("buck", {"v_out": 5, "i_out": 3.5})
    assert _checks(env)["i_out"] == "failed" and "buck_i_out" in _codes(env)
    env = calckit.run("buck", {"r_top": "10k", "r_bottom": "10k"})  # 2.46 V; r_bottom above 1.5 kΩ
    assert _checks(env)["r_bottom"] == "failed" and "buck_r_bottom" in _codes(env)


@pytest.mark.parametrize(("params", "needle"), [
    ({}, "give v_out"), ({"v_out": 50}, "1.200 V to 37.00 V"), ({"v_out": 1.2}, "needs no divider"),
    ({"v_out": 3.3, "chip": "lm317"}, "chip"), ({"v_out": 70}, "60 V"), ({"r_top": "1k"}, "give v_out")])
def test_buck_errors(params, needle):
    env = calckit.run("buck", params)
    assert env["ok"] is False and needle in env["error"]["message"], env["error"]


# --- calc.charger --------------------------------------------------------------------------------------------------
def test_charger_mcp73831_datasheet_points():
    # IREG = 1000 V / RPROG (p. 15): 10 kΩ -> 100 mA (table 90–110 mA), 2 kΩ -> 500 mA (450–550 mA)
    env = calckit.run("charger", {"chip": "mcp73831", "r_prog": "10k"})
    assert env["result"]["i_charge"]["value"] == pytest.approx(0.1, rel=REL)
    assert env["result"]["i_charge_range"]["min"]["value"] == pytest.approx(0.09, rel=REL)
    env = calckit.run("charger", {"chip": "mcp73831", "i_charge": "0.5A"})
    assert env["result"]["r_prog"]["value"] == 2000 and _checks(env)["r_prog"] == "passed"
    # p. 18: P = (5.5 V − 2.7 V) · 550 mA = 1.54 W; here V_PTH min = 0.64 · 4.2 = 2.688 V and R_PROG = 1000/0.55
    env = calckit.run("charger", {"chip": "mcp73831", "r_prog": 1000 / 0.55, "v_in": 5.5})
    assert env["result"]["p_charger"]["value"] == pytest.approx(1.54, rel=0.01)
    assert env["result"]["t_j"]["value"] == pytest.approx(25 + (5.5 - 2.688) * 0.55 * 230, rel=1e-3)
    assert "charger_heat" in _codes(env)


def test_charger_tp4056_formula():
    # IBAT = (VPROG / RPROG) · 1200, VPROG = 1 V: 1.2 kΩ -> 1.0 A (850–1150 mA, p. 5)
    env = calckit.run("charger", {"r_prog": "1.2k", "v_in": 5})
    r = env["result"]
    assert r["i_charge"]["value"] == pytest.approx(1.0, rel=REL) and r["i_charge_range"]["max"]["value"] == 1.15
    assert r["p_charger"]["value"] == pytest.approx((5 - 2.8) * 1.0, rel=REL) and r["t_j"] is None
    assert "charger_table" in _codes(env)
    # target 0.5 A: R ideal 2.4 kΩ (E24) -> exactly 0.5 A; 0.45 A -> 2.667 kΩ -> E24 up 2.7 kΩ -> 444 mA ≤ target
    assert calckit.run("charger", {"i_charge": 0.5})["result"]["r_prog"]["value"] == 2400
    env = calckit.run("charger", {"i_charge": 0.45})
    assert env["result"]["r_prog"]["value"] == 2700 and env["result"]["i_charge"]["value"] <= 0.45


def test_charger_always_warns_li_ion():
    for params in ({"r_prog": "2k"}, {"chip": "mcp73831", "r_prog": "10k"}, {"i_charge": 0.1}):
        env = calckit.run("charger", params)
        li = [w for w in env["warnings"] if w["code"] == "li_ion"]
        assert len(li) == 1 and li[0]["severity"] == "danger" and "fire" in li[0]["message"]


def test_charger_limits():
    env = calckit.run("charger", {"chip": "mcp73831", "r_prog": "1k"})  # 1 A > 500 mA, below 2 kΩ
    assert _checks(env)["r_prog"] == "failed" and _checks(env)["i_charge"] == "failed"
    env = calckit.run("charger", {"chip": "mcp73831", "r_prog": "100k"})  # ≥ 70 kΩ: shutdown
    assert "charger_r_prog_shutdown" in _codes(env)
    env = calckit.run("charger", {"r_prog": "1k"})  # TP4056 1.2 A > 1 A
    assert "charger_i_max" in _codes(env)
    env = calckit.run("charger", {"r_prog": "2k", "v_in": 9})
    assert "charger_v_in_abs_max" in _codes(env)


@pytest.mark.parametrize(("params", "needle"), [
    ({}, "either r_prog"), ({"r_prog": "2k", "i_charge": 0.5}, "either r_prog"), ({"r_prog": "2k", "chip": "x"}, "chip"),
    ({"r_prog": "-2k"}, "r_prog"), ({"r_prog": "2k", "t_ambient": "hot"}, "t_ambient")])
def test_charger_errors(params, needle):
    env = calckit.run("charger", params)
    assert env["ok"] is False and needle in env["error"]["message"], env["error"]


# --- calc.ldo with the new regulators ------------------------------------------------------------------------------
def test_ldo_calc_knows_the_complete_regulators():
    # AP2112K-3.3: P = (5 − 3.3) · 0.2 + 5 · 80 µA = 0.3404 W; T_J = 25 + 0.3404 · 184 = 87.63 °C
    env = calc_power.ldo(5, 3.3, 0.2, part="AP2112K-3.3")
    assert env["result"]["t_j"]["value"] == pytest.approx(25 + 0.3404 * 184, rel=1e-3)
    assert {c["id"].rsplit(".", 1)[1]: c["status"] for c in env["checks"]}["t_j"] == "passed"
    # 0.6 A at 5 V: P = 1.02 W, T_J = 25 + 1.0204 · 184 = 212.8 °C > 150 °C
    env = calc_power.ldo(5, 3.3, 0.6, part="AP2112K-3.3")
    assert {c["id"].rsplit(".", 1)[1]: c["status"] for c in env["checks"]}["t_j"] == "failed"
    # MCP1700: 0.3 A > 250 mA guaranteed output current
    env = calc_power.ldo(5, 3.3, 0.3, part="MCP1700-3302E/TT")
    assert {c["id"].rsplit(".", 1)[1]: c["status"] for c in env["checks"]}["current_limit"] == "failed"


def test_ldo_calc_reports_partial_regulators_as_not_checked():
    for pid in ("XC6206P332MR", "HT7333-A", "ME6211C33M5G-N"):
        env = calc_power.ldo(5, 3.3, 0.1, part=pid)
        assert env["ok"] and {c["id"].rsplit(".", 1)[1]: c["status"] for c in env["checks"]}["t_j"] == "not_checked"
