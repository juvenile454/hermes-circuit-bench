"""Module family npower: TLV75533P, TPS563201, BQ24074 (Texas Instruments).

Catalog entries (data/modules/npower.json; generic checks in tests/test_m0_modules_data.py), the regulator record for
calc.ldo (data/parts/power_npower.json; every quoted number checked here against the committed excerpt
tests/corpus/excerpts/mod-npower-*.txt), the family rules of modrules/npower.py and the generic rules on these parts.
Projects are synthetic. Hand calculations in the comments.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

import excerpts as ex
import modkit as mk
from circuit_bench.bench_core import calc_power, electrical, modules, parts, sources
from circuit_bench.bench_core.modrules import npower as rules

ROOT = Path(__file__).resolve().parent.parent
PARTS_FILE = ROOT / "circuit_bench" / "data" / "parts" / "power_npower.json"
ESP = electrical.get("esp32s3")
EXC = {e.source_id: e for e in ex.excerpts("mod-npower-*.txt")}
PARTS = ("tlv75533p", "tps563201", "bq24074")
REL = 1e-9


def _cited(source_id: str, page: int, evidence) -> bool:
    want = [evidence] if isinstance(evidence, str) else list(evidence)
    return ex.find_parts_in_order(want, [ln for seg in EXC[source_id].page_segments(page) for ln in seg])


def _run(*project_parts, options=None, only=None, assignments=()):
    return mk.run(electrical=ESP, parts=list(project_parts), options=options, only=only, assignments=list(assignments))


def _f(rep, rule_id, status=None):
    return mk.findings(rep, rule_id, status)


def cap(ref, net, value="1uF", to="GND"):
    return {"ref": ref, "kind": "capacitor", "value": value, "conn": {"1": net, "2": to}}


def res(ref, a, b, value="10k"):
    return {"ref": ref, "kind": "resistor", "value": value, "conn": {"1": a, "2": b}}


def tlv(vin="VBAT", vout="3V3", en: str | None = "VBAT"):
    conn = {"IN": vin, "OUT": vout, "GND": "GND"}
    if en:
        conn["EN"] = en
    return mk.mod("U1", "tlv75533p", conn)


def bq(out="VSYS", bat="VBAT", vin="5V", **extra):
    conn = {"IN": vin, "OUT": out, "BAT": bat, "VSS": "GND", "CE": "GND", "EN1": "GND", "EN2": "VSYS",
            "ISET": "ISET", "ILIM": "ILIM", "TS": "TS", **extra}
    return mk.mod("U3", "bq24074", conn)


# --- catalog, sources, data ----------------------------------------------------------------------------------------
def test_the_three_parts_are_in_the_catalog_with_class_a():
    cat = modules.catalog()
    assert [p for p in cat.problems if "npower" in p] == []
    # tlv75533p and tps563201: the ti.com file through web.archive.org (A1; ti.com re-stamps its PDFs daily)
    want = {"tlv75533p": "A1", "tps563201": "A1", "bq24074": "A"}
    for mid in PARTS:
        m = cat.get(mid)
        assert m["_wp"] == "npower" and m["_class"] == want[mid] and m["manufacturer"] == "Texas Instruments"
    assert {cat.get(m)["category"] for m in PARTS} == {"power.ldo", "power.buck", "power.charger"}


def test_sources_resolve_and_match_the_manifest():
    manifest = {f["source_id"]: f for f in json.loads((ROOT / "tests/corpus/mod-npower.json").read_text())["files"]}
    assert set(manifest) == {f"mod-npower-{k}-ds" for k in ("tlv755p", "tps563201", "bq24074")}
    for sid, f in manifest.items():
        src = sources.get(sid)
        assert src["url"] == f["url"]
        # the ti.com file, or a web.archive.org snapshot of it (ti.com re-stamps its PDFs daily)
        assert re.fullmatch(r"(https://web\.archive\.org/web/\d+id_/)?https://www\.ti\.com/lit/ds/symlink/\w+\.pdf",
                            f["url"]), f["url"]
        assert f["sha256"] in src["note"] and src["class"] == ("A1" if src["url"].startswith("https://web.archive.org/") else "A")
        assert EXC[sid].meta["corpus"] == f"{f['path']} sha256 {f['sha256']}"


def test_charger_carries_the_li_ion_hazard_and_the_regulators_none():
    cat = modules.catalog()
    hz = cat.get("bq24074")["hazards"]
    assert [h["code"] for h in hz] == ["li_ion", "heat"] and "fire" in hz[0]["text"] and "NTC" in hz[0]["text"]
    assert "1.5 A" in hz[1]["text"] and hz[1]["page"] == 42
    assert cat.get("tlv75533p")["hazards"] == [] and cat.get("tps563201")["hazards"] == []


def test_key_values_of_the_entries():
    cat = modules.catalog()
    t, b, q = cat.get("tlv75533p"), cat.get("tps563201"), cat.get("bq24074")
    assert (t["supplies"]["IN"]["min"]["value"], t["supplies"]["IN"]["max"]["value"],
            t["supplies"]["IN"]["abs_max"]["value"]) == (1.45, 5.5, 6.0)
    assert (b["supplies"]["VIN"]["min"]["value"], b["supplies"]["VIN"]["max"]["value"],
            b["supplies"]["VIN"]["abs_max"]["value"]) == (4.5, 17.0, 19.0)
    assert (q["supplies"]["IN"]["min"]["value"], q["supplies"]["IN"]["max"]["value"],
            q["supplies"]["IN"]["abs_max"]["value"]) == (4.35, 10.2, 28.0)
    assert (b["io"]["vih"]["value"], b["io"]["vil"]["value"]) == (1.6, 0.8)
    assert (q["io"]["vih"]["value"], q["io"]["vil"]["value"], q["io"]["outputs"]) == (1.4, 0.4, "open_drain")
    en = next(p for p in b["pins"] if p["name"] == "EN")
    assert en["must_connect"] and en["internal_pull"] == "down"  # "must be pulled up to enable the device"
    assert [p["name"] for p in q["pins"] if p["signal"] == "power_out"] == ["BAT", "OUT"]  # BAT first (li_ion rule)


def test_tps563201_vfb_and_the_datasheet_divider():
    # V_FB 0.768 V typ. (continuous mode, 0.749–0.787 V); table 7-2: 3.3 V with R1 33.2 kΩ, R2 10.0 kΩ:
    # 0.768 · (1 + 33.2 / 10.0) = 0.768 · 4.32 = 3.31776 V; 5 V: 0.768 · (1 + 54.9 / 10) = 4.98432 V
    notes = modules.catalog().get("tps563201")["notes"]
    vfb = next(n for n in notes if n["text"].startswith("Feedback voltage"))
    assert "749 768 787 mV" in vfb["evidence"][1] and vfb["page"] == 6
    assert 0.768 * (1 + 33.2 / 10.0) == pytest.approx(3.31776, rel=REL)
    assert 0.768 * (1 + 54.9 / 10.0) == pytest.approx(4.98432, rel=REL)
    table = next(n for n in notes if n["text"].startswith("Recommended values for 3.3 V"))
    assert _cited("mod-npower-tps563201-ds", table["page"], table["evidence"])


def test_bq24074_charge_current_formula_from_the_datasheet():
    # I_CHG = K_ISET / R_ISET, K_ISET 890 AΩ typ. (797–975): 1.78 kΩ -> 0.5 A (0.4478–0.5478 A)
    req = next(r for r in modules.catalog().get("bq24074")["requires"] if r["pins"] == ["ISET"])
    assert req["value"] == "1.78k" and "890 AΩ" in req["note"]
    assert 890 / 1780 == pytest.approx(0.5, rel=REL)
    assert 797 / 1780 == pytest.approx(0.447753, rel=1e-5) and 975 / 1780 == pytest.approx(0.547753, rel=1e-5)
    kiset = next(n for n in modules.catalog().get("bq24074")["notes"] if n["text"].startswith("Fast-charge current"))
    assert kiset["page"] == 13 and "797 890 975" in kiset["evidence"][1]
    assert _cited("mod-npower-bq24074-ds", kiset["page"], kiset["evidence"])


def _cited_fields(rec):
    for key in ("v_out", "dropout", "i_q"):
        yield key, rec[key]
    yield from rec["ratings"].items()


def test_parts_file_is_complete_for_calc_ldo_and_cited():
    data = json.loads(PARTS_FILE.read_text(encoding="utf-8"))
    (rec,) = data["parts"]
    assert rec["kind"] == "ldo" and rec["module"] == "tlv75533p" and "missing" not in rec
    assert set(rec["ratings"]) == {"v_in_max", "i_limit_min", "t_j_max", "r_th_ja", "t_shutdown"}
    for key, f in _cited_fields(rec):
        assert _cited(rec["source_id"], f["page"], f["evidence"]), key
    assert (rec["dropout"]["value"], rec["dropout"]["i_out"], rec["i_q"]["value"]) == (0.238, 0.5, 40e-6)
    assert rec["ratings"]["r_th_ja"]["value"] == 231.1 and rec["ratings"]["t_j_max"]["value"] == 125.0
    assert parts.find("TLV75533P", "ldo")["id"] == "TLV75533PDBVR"


def test_calc_ldo_with_the_tlv75533p():
    # 5 V -> 3.3 V at 300 mA: P = 1.7 · 0.3 + 5 · 40 µA = 0.51 + 0.0002 = 0.5102 W
    # T_J = 25 + 0.5102 · 231.1 = 142.907 °C > 125 °C (SOT-23-5 DBV) -> t_j failed; 0.3 A ≤ 0.56 A limit
    env = calc_power.ldo(5, 3.3, 0.3, part="TLV75533P")
    assert env["ok"]
    assert env["result"]["p_total"]["value"] == pytest.approx(0.5102, rel=REL)
    assert env["result"]["t_j"]["value"] == pytest.approx(142.907, rel=REL)
    st = {c["id"].rsplit(".", 1)[1]: c["status"] for c in env["checks"]}
    assert st == {"headroom": "passed", "dropout": "passed", "current_limit": "passed", "v_in_max": "passed",
                  "t_j": "failed"}
    # from a Li-Ion cell at 3.5 V: 0.2 V < 0.238 V max dropout at 500 mA -> dropout failed
    env = calc_power.ldo(3.5, 3.3, 0.1, part="TLV75533P")
    assert {c["id"].rsplit(".", 1)[1]: c["status"] for c in env["checks"]}["dropout"] == "failed"


# --- mod.npower.dropout --------------------------------------------------------------------------------------------
@pytest.mark.parametrize(("vbat", "status", "severity"), [
    (3.7, "passed", None),       # 3.7 − 3.3 = 0.400 V ≥ 0.238 V
    (3.538, "passed", None),     # exactly at the dropout: 0.238 V
    (3.5, "failed", "caution"),  # 0.200 V < 0.238 V
])
def test_dropout_against_the_battery_rail(vbat, status, severity):
    rep = _run(tlv(), options={"rails": {"VBAT": vbat}}, only=(rules.DROPOUT_RULE, "mod.power.dropout"))
    (f,) = _f(rep, rules.DROPOUT_RULE)
    assert (f.status, f.severity) == (status, severity), f.message
    assert f.source_ids == ["mod-npower-tlv755p-ds"]
    assert _f(rep, "mod.power.dropout") == []  # the power family rule (VIN/VOUT pins) does not double it


def test_dropout_needs_a_user_rail_and_a_known_output():
    assert _f(_run(tlv(vin="5V"), only=(rules.DROPOUT_RULE,)), rules.DROPOUT_RULE) == []
    rep = _run(tlv(vout="V3"), options={"rails": {"VBAT": 3.7}}, only=(rules.DROPOUT_RULE,))
    (f,) = _f(rep, rules.DROPOUT_RULE)
    assert f.status == "not_checked" and "OUT is not on a known rail" in f.message


def test_dropout_without_regulator_record_is_not_checked(monkeypatch):
    monkeypatch.setattr(rules, "_ldo_record", lambda inst: None)
    rep = _run(tlv(), options={"rails": {"VBAT": 3.7}}, only=(rules.DROPOUT_RULE,))
    assert [(f.status, f.message) for f in _f(rep, rules.DROPOUT_RULE)] == [("not_checked",
                                                                             "U1 (tlv75533p): no dropout data.")]


def test_dropout_leaves_vin_vout_ldos_to_the_power_rule():
    rep = _run(mk.mod("U1", "mcp1700", {"VIN": "VBAT", "VOUT": "3V3", "GND": "GND"}),
               options={"rails": {"VBAT": 3.7}}, only=(rules.DROPOUT_RULE, "mod.power.dropout"))
    assert _f(rep, rules.DROPOUT_RULE) == [] and len(_f(rep, "mod.power.dropout")) == 1


# --- mod.npower.power_path_out -------------------------------------------------------------------------------------
@pytest.mark.parametrize(("out", "status", "severity", "text"), [
    ("3V3", "failed", "danger", "ESP absolute maximum 3.60 V"),  # 3.3 V < 4.3 V: OUT lifts the ESP rail
    ("5V", "failed", "caution", "power path is bypassed"),      # 5.0 V > 4.5 V: OUT tied to the input
    ("VSYS", "passed", None, "own net VSYS"),
])
def test_power_path_out(out, status, severity, text):
    rep = _run(bq(out=out), only=(rules.PATH_RULE,))
    (f,) = _f(rep, rules.PATH_RULE)
    assert (f.status, f.severity) == (status, severity) and text in f.message, f.message


def test_power_path_out_within_the_window_and_open():
    rep = _run(bq(out="VSYS"), options={"rails": {"VSYS": 4.4}}, only=(rules.PATH_RULE,))
    assert _f(rep, rules.PATH_RULE)[0].status == "passed"
    conn = {"IN": "5V", "BAT": "VBAT", "VSS": "GND"}
    assert _f(_run(mk.mod("U3", "bq24074", conn), only=(rules.PATH_RULE,)), rules.PATH_RULE) == []


# --- generic and power family rules on the npower parts ------------------------------------------------------------
def test_li_ion_rules_fire_for_the_bq24074():
    rep = _run(bq(), only=("mod.hazard", "mod.power.li_ion"))
    assert sorted((f.status, f.severity) for f in _f(rep, "mod.hazard")) == [("failed", "caution"),
                                                                             ("failed", "danger")]
    assert [f.status for f in _f(rep, "mod.power.li_ion")] == ["passed"]  # mod.hazard carries the danger
    rep = _run(bq(bat="3V3"), only=("mod.power.li_ion",))
    assert any("BAT is on the 3V3 rail" in f.message for f in _f(rep, "mod.power.li_ion"))


@pytest.mark.parametrize(("part", "status", "severity"), [
    (tlv(vin="12V"), "failed", "danger"),     # 12 V > 6.0 V absolute maximum
    (tlv(vin="5V"), "passed", None),          # 5 V within 1.45–5.5 V
    (mk.mod("U2", "tps563201", {"VIN": "3V3", "GND": "GND"}), "failed", None),  # 3.3 V < 4.5 V min
    (mk.mod("U2", "tps563201", {"VIN": "12V", "GND": "GND"}), "passed", None),
    (bq(vin="12V"), "failed", None),          # 12 V > 10.2 V (OVP suspends charging)
    (bq(vin="5V"), "passed", None),
])
def test_supply_range(part, status, severity):
    rep = _run(part, options={"rails": {"12V": 12.0}}, only=("mod.supply_range",))
    (f,) = _f(rep, "mod.supply_range")
    assert f.status == status, f.message
    if severity:
        assert f.severity == severity


def test_supply_range_severity_below_minimum_and_above_operating():
    rep = _run(mk.mod("U2", "tps563201", {"VIN": "3V3", "GND": "GND"}), only=("mod.supply_range",))
    assert _f(rep, "mod.supply_range")[0].severity in ("caution", "danger")
    rep = _run(bq(vin="12V"), options={"rails": {"12V": 12.0}}, only=("mod.supply_range",))
    assert _f(rep, "mod.supply_range")[0].severity in ("caution", "danger")


def test_enable_pins_driven_by_the_esp():
    # ESP32-S3 V_OH 2.64 V is above EN V_IH 1.6 V (TPS) / 1.4 V (BQ CE) -> passed. TLV755P: V_LO 0.3 V lies below the
    # ESP's V_OL max 0.33 V (0.1 · VDD) -> caution: a GPIO low is not guaranteed to switch the LDO off.
    rep = _run(tlv(en="GPIO4"), mk.mod("U2", "tps563201", {"VIN": "12V", "GND": "GND", "EN": "GPIO5"}),
               bq(CE="GPIO6"), assignments=[mk.assign("out", 4), mk.assign("out", 5), mk.assign("out", 6)],
               options={"rails": {"12V": 12.0}}, only=("mod.level_in",))
    st = {f.refs[0]: (f.status, f.severity) for f in _f(rep, "mod.level_in")}
    assert st == {"U1": ("failed", "caution"), "U2": ("passed", None), "U3": ("passed", None)}
    assert "VIL 300 mV" in _f(rep, "mod.level_in", "failed")[0].message


def test_open_drain_status_pulled_to_5v_into_an_esp_input_is_flagged():
    rep = _run(bq(CHG="GPIO7"), res("R1", "GPIO7", "5V"), assignments=[mk.assign("in", 7)],
               only=("mod.level_out",))
    fs = _f(rep, "mod.level_out", "failed")
    assert fs and fs[0].severity == "danger", [f.message for f in _f(rep, "mod.level_out")]
    rep = _run(bq(CHG="GPIO7"), res("R1", "GPIO7", "3V3"), assignments=[mk.assign("in", 7)],
               only=("mod.level_out",))
    assert _f(rep, "mod.level_out", "failed") == []


def test_open_enable_pins_are_flagged():
    rep = _run(mk.mod("U2", "tps563201", {"VIN": "12V", "GND": "GND", "SW": "SWN", "VFB": "FB", "VBST": "BST"}),
               options={"rails": {"12V": 12.0}}, only=("mod.unconnected",))
    assert any("EN (enable_in) must be connected" in f.message for f in _f(rep, "mod.unconnected", "failed"))
    rep = _run(tlv(en=None), options={"rails": {"VBAT": 3.7}}, only=("mod.unconnected",))
    assert any("EN" in f.message for f in _f(rep, "mod.unconnected", "failed"))
    assert _f(_run(tlv(), options={"rails": {"VBAT": 3.7}}, only=("mod.unconnected",)), "mod.unconnected",
              "failed") == []


def test_required_parts():
    # TLV: 1 µF on IN and OUT (both "required" -> caution); with both caps: passed
    rep = _run(tlv(), options={"rails": {"VBAT": 3.7}}, only=("mod.required_parts",))
    assert sorted(str(f.severity) for f in _f(rep, "mod.required_parts", "failed")) == ["caution", "caution"]
    rep = _run(tlv(), cap("C1", "VBAT"), cap("C2", "3V3"), options={"rails": {"VBAT": 3.7}},
               only=("mod.required_parts",))
    assert _f(rep, "mod.required_parts", "failed") == []
    # TPS: the bootstrap capacitor goes from VBST to SW, not to GND
    tps = mk.mod("U2", "tps563201", {"VIN": "12V", "GND": "GND", "SW": "SWN", "VFB": "FB", "VBST": "BST",
                                    "EN": "12V"})
    rep = _run(tps, cap("C1", "12V", "22uF"), cap("C2", "BST", "100nF", to="GND"), options={"rails": {"12V": 12.0}},
               only=("mod.required_parts",))
    assert [f.message for f in _f(rep, "mod.required_parts", "failed") if "VBST" in f.message]
    rep = _run(tps, cap("C1", "12V", "22uF"), cap("C2", "BST", "100nF", to="SWN"), options={"rails": {"12V": 12.0}},
               only=("mod.required_parts",))
    assert _f(rep, "mod.required_parts", "failed") == []
    # BQ: R_ISET missing -> caution with the value
    rep = _run(bq(), only=("mod.required_parts",))
    iset = [f for f in _f(rep, "mod.required_parts", "failed") if "(ISET)" in f.message]
    assert iset and iset[0].severity == "caution" and "1.78k" in iset[0].message


def test_battery_project_end_to_end():
    from circuit_bench.bench_core import pins
    proj = [
        {"ref": "U3", "kind": "ic", "value": "BQ24074", "module": "bq24074",
         "conn": {"IN": "5V", "OUT": "VSYS", "BAT": "VBAT", "VSS": "GND", "CE": "GND", "EN1": "GND", "EN2": "VSYS",
                  "ISET": "ISET", "ILIM": "ILIM", "TS": "TS", "CHG": "GPIO7"}},
        {"ref": "U1", "kind": "ic", "value": "TLV75533P", "module": "tlv75533p",
         "conn": {"IN": "VSYS", "OUT": "3V3", "GND": "GND", "EN": "VSYS"}},
    ]
    env = pins.check("esp32s3", [{"role": "CHG", "mode": "in", "pin": 7, "net": "GPIO7"}], parts=proj,
                     options={"rails": {"VSYS": 4.4, "VBAT": 3.7}})
    codes = {w["code"]: w["severity"] for w in env["warnings"]}
    hz = sorted(w["severity"] for w in env["warnings"] if w["code"] == "mod_hazard")
    assert hz == ["caution", "danger"] and "mod_power_li_ion" not in codes  # li_ion danger once, heat caution
    assert "mod_npower_power_path_out" not in codes and "mod_npower_dropout" not in codes  # OUT on VSYS, 1.1 V head
    env = pins.check("esp32s3", [{"role": "CHG", "mode": "in", "pin": 7, "net": "GPIO7"}],
                     parts=[dict(proj[0], conn=dict(proj[0]["conn"], OUT="3V3"))],
                     options={})
    assert {w["code"]: w["severity"] for w in env["warnings"]}.get("mod_npower_power_path_out") == "danger"


# --- data corrections ------------------------------------------------------------------------------------------------
def test_npower_v_in_max_is_the_absolute_rating():
    cat = modules.catalog()
    got = {m: (cat.get(m)["io"]["v_in_max"]["value"], cat.get(m)["io"]["v_in_max"]["page"]) for m in PARTS}
    assert got == {"tlv75533p": (6.0, 4), "tps563201": (19.0, 4), "bq24074": (7.0, 10)}
