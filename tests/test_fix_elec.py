"""False alarms and gaps in the generic electrical rules (modrules/elec.py) found by rule reviews and model probes.

1. supply conditions: only supply names count (VCE / VO / VOL, load test points and parentheses do not)
2. a VOH given under load (>= 1 mA) below the ESP's VIH is only an info (SN65HVD230, W5500)
3. mod.hazard under Finding.supersedes (a passed family finding lowers it; li_ion stays danger)
4. mod.power_budget text without current data; a known sum above the limit stays caution
5. facts.regulator on a chip entry (GY-BME280 at 5 V)
6. io.domain_v (fixed internal I/O voltage) in modspec and the level rules
7. mod.required_parts: bulk_cap is only a hint when optional; "strongly recommended" is never a hint
p5: facts.pullups_to as a module pin / net / number; an open-drain net pulled above any module input's
maximum is danger; facts.pullups "unknown" asks to measure.
Synthetic modules (``fe_*``) with invented values and the ``tst-`` sources of tests/mod_fixtures.py; a few checks use
the real catalog (the reviewed projects).
"""
from __future__ import annotations

import pytest

import mod_fixtures as fx
import modkit as k
from circuit_bench.bench_core import modcheck, modspec

F, R, GND = fx.F, fx.R, fx.GND
DIG = [k.assign("out", 4, "DIN"), k.assign("in", 5, "DOUT")]
BUS = k.i2c()  # GPIO8 SDA0, GPIO9 SCL0


def dmod(mid: str = "fe_dig", *, vih=None, voh=None, v_in_max=None, supply_pin: str = "VCC", supply=None,
         extra_io=None, kind: str = "ic", current=None, requires=None, hazards=None, i2c: bool = False) -> dict:
    io = {"domain": supply_pin, "outputs": "push_pull"}
    for key, val in (("vih", vih), ("voh", voh), ("v_in_max", v_in_max)):
        if val is not None:
            io[key] = val
    io.update(extra_io or {})
    pins = [{"name": supply_pin, "signal": "supply"}, GND, {"name": "DIN", "signal": "digital_in"},
            {"name": "DOUT", "signal": "digital_out"}]
    if i2c:
        pins += [{"name": "SDA", "signal": "i2c_sda"}, {"name": "SCL", "signal": "i2c_scl"}]
    m = {"id": mid, "title": f"FE {mid}", "category": "sensor.light", "manufacturer": "Test", "kind": kind,
         "source_ids": ["tst-5v-ds"], "pins": pins,
         "supplies": {supply_pin: supply or {"min": F(1.8), "max": F(5.5), "abs_max": F(6.0)}},
         "io": io, "interfaces": [{"type": "i2c" if i2c else "digital"}]}
    for key, val in (("current", current), ("requires", requires), ("hazards", hazards)):
        if val is not None:
            m[key] = val
    return m


def run(parts, *, extra=(), assignments=None, options=None, only=None):
    return k.run(catalog=fx.catalog(*extra), electrical=fx.ESP, assignments=DIG if assignments is None else
                 assignments, parts=parts, options=options, only=only)


def fs(rep, rule_id, status=None):
    return k.findings(rep, rule_id, status)


def dig(mid="fe_dig", vcc="3V3", pin="VCC", ref="U1", facts=None):
    return k.mod(ref, mid, {pin: vcc, "GND": "GND", "DIN": "GPIO4", "DOUT": "GPIO5"}, facts=facts)


# =====================================================================================================================
# 1. supply conditions
# =====================================================================================================================
COND = [  # (conditions, supply volts, the value is used)
    ("VCE = 2 V", 3.3, True),
    ("VI(on) max for VCE = 2 V at IC = 200 mA, TA = 25 °C (2.7 V at 250 mA, 3 V at 300 mA)", 5.0, True),
    ("SDA sinks ≥ 3 mA at VO = 0.4 V, VCC 2.5–6 V", 3.3, True),
    ("VOL = 0.4 V", 3.3, True),
    ("GPIO/INT, IOH = −3.0 mA at VDD 4.5 V (−400 µA at VDD 1.8 V)", 3.3, True),
    ("VCC 3.0–3.6 V (VCC 1.8–2.7 V: 0.7 VCC)", 3.3, True),
    ("TA = 25 °C", 3.3, True),
    ("VCC = 4.5 V", 3.3, False),
    ("VCC 4.5–5.5 V", 3.3, False),
    ("VDD 4.5–5.5 V", 3.3, False),        # a supply word for a module whose pin is VCC: the I/O domain counts
    ("VCC ≥ 4.5 V", 3.3, False),
    ("VCC ≥ 4.5 V", 5.0, True),
    ("V+ = 5 V ±10 %", 3.3, False),
    ("V+ = 5 V ±10 %", 5.0, True),
    ("1.9 V < VDD < 3.6 V", 3.3, True),
    ("1.9 V < VDD < 3.6 V", 5.0, False),
]


@pytest.mark.parametrize("cond,volts,used", COND)
def test_conditions_read_only_supply_names(cond, volts, used):
    m = dmod(vih=F(2.0, conditions=cond), v_in_max=F(6.0))
    rail = {3.3: "3V3", 5.0: "5V"}[volts]
    rep = run([dig(vcc=rail)], extra=[m], only=("mod.level_in",))
    f = fs(rep, "mod.level_in")[0]
    if used:
        assert f.status == "passed", f.message
    else:
        assert f.status == "not_checked" and "never interpolated" in f.message, f.message


def test_condition_on_a_named_supply_pin_uses_that_pin():
    m = dmod(supply_pin="VBAT", vih=F(2.0, conditions="VBAT 3.4–4.4 V"), v_in_max=F(6.0),
             supply={"min": F(3.4), "max": F(4.4), "abs_max": F(5.0)})
    rep = run([dig(pin="VBAT", vcc="V40")], extra=[m], options={"rails": {"V40": 4.0}}, only=("mod.level_in",))
    assert fs(rep, "mod.level_in")[0].status == "passed"
    rep = run([dig(pin="VBAT", vcc="3V3")], extra=[m], only=("mod.level_in",))
    assert fs(rep, "mod.level_in")[0].status == "not_checked"


def test_uln2003_vce_condition_is_no_supply_condition():
    """p37: ULN2003A VIH 'for VCE = 2 V' is used at 5 V (no 'project runs at 5.00 V' text)."""
    rep = modcheck.run(chip="esp32s3", assignments=[k.assign("out", 4, "IN1")],
                       parts=[k.mod("U1", "uln2003a", {"1B": "IN1", "E": "GND", "COM": "5V", "1C": "M1"})],
                       options={}, only=("mod.level_in",))
    texts = [f.message for f in fs(rep, "mod.level_in")]
    assert texts and not any("VCE" in t for t in texts), texts


# =====================================================================================================================
# 2. VOH under load
# =====================================================================================================================
@pytest.mark.parametrize("cond,want", [
    ("IO = -8 mA", "info"), ("IOH = 8 mA", "info"), ("at −2 mA (−20 µA: 3.2 V)", "info"),
    ("IOH = -1 mA", "info"), (None, "caution"), ("IOH = −0.5 mA", "caution"), ("IOH = -100 µA", "caution"),
])
def test_loaded_voh_below_esp_vih_is_only_a_hint(cond, want):
    voh = F(2.4, conditions=cond) if cond else F(2.4)
    rep = run([dig()], extra=[dmod(voh=voh)], only=("mod.level_out",))
    f = fs(rep, "mod.level_out")[0]
    assert (f.status, f.severity) == ("failed", want), f.message
    if want == "info":
        assert "load" in f.message and "almost no current" in f.message


@pytest.mark.parametrize("mid,conn,assign", [
    ("sn65hvd230", {"VCC": "3V3", "GND": "GND", "D": "CTX", "R": "CRX", "RS": "GND", "CANH": "CH", "CANL": "CL"},
     [k.assign("out", 4, "CTX"), k.assign("in", 5, "CRX")]),
])
def test_real_can_transceiver_has_no_level_out_caution(mid, conn, assign):
    """p12: SN65HVD230 R (VOH 2.4 V at IO = -8 mA) on an ESP input: no caution."""
    rep = modcheck.run(chip="esp32s3", assignments=assign, parts=[k.mod("U1", mid, conn)], options={},
                       only=("mod.level_out",))
    hard = [f for f in fs(rep, "mod.level_out") if f.severity in ("caution", "danger")]
    assert not hard, [f.message for f in hard]


# =====================================================================================================================
# 3. mod.hazard and supersedes
# =====================================================================================================================
def test_hazard_mains_lowered_by_a_passed_family_finding_li_ion_stays():
    relay = dmod("fe_relay", hazards=[{"code": "mains", "text": "Contacts rated for mains", "page": 1,
                                       "evidence": "250 VAC"}])
    cell = dmod("fe_cell", hazards=[{"code": "li_ion", "text": "Charges Li-ion cells", "page": 1,
                                     "evidence": "Li-ion"}])
    parts = [dig("fe_relay"), k.mod("U2", "fe_cell", {"VCC": "5V", "GND": "GND"})]

    def fam(ctx):
        return [modcheck.Finding("mod.tstfam.relay", "passed", None, "contacts on low voltage", ["U1"], [],
                                 ("mod.hazard",))]

    with k.temp_rule("mod.tstfam.relay", fam):
        rep = run(parts, extra=[relay, cell], only=("mod.hazard", "mod.tstfam.relay"))
    sev = {tuple(w["refs"]): w["severity"] for w in rep.warnings if w["code"] == "mod_hazard"}
    assert sev == {("U1",): "info", ("U2",): "danger"}
    rep = run(parts, extra=[relay, cell], only=("mod.hazard",))  # without the family rule: both danger
    assert {w["severity"] for w in rep.warnings if w["code"] == "mod_hazard"} == {"danger"}


# =====================================================================================================================
# 4. mod.power_budget
# =====================================================================================================================
LED = dmod("fe_led", current={"supply": "VCC", "max": F(0.06, "A")})
NODATA = dmod("fe_nodata")


def test_budget_without_data_names_known_sum_and_missing_parts():
    rep = run([dig("fe_led", vcc="5V"), dig("fe_nodata", vcc="5V", ref="U3")], extra=[LED, NODATA],
              options={"rail_limits": {"5V": 4.0}}, only=("mod.power_budget",))
    f = fs(rep, "mod.power_budget")[0]
    assert (f.status, f.severity) == ("not_checked", "info")
    assert "max 60.0 mA" in f.message and "known; U3 has no current data" in f.message
    assert "below" not in f.message


def test_budget_known_sum_above_limit_is_caution_despite_missing_data():
    led = k.mod("LED", "fe_led", {"VCC": "5V", "GND": "GND", "DIN": "GPIO4"}, qty=150)  # 150 x 60 mA = 9 A
    rep = run([led, dig("fe_nodata", vcc="5V", ref="U3")], extra=[LED, NODATA],
              options={"rail_limits": {"5V": 4.0}}, only=("mod.power_budget",))
    f = fs(rep, "mod.power_budget")[0]
    assert (f.status, f.severity) == ("failed", "caution") and "9.00 A" in f.message and "U3" in f.message


def test_budget_150_ws2812b_without_led_current_in_the_catalog_names_the_chain():
    """probe ws2812_150_budget: the catalog has no LED maximum current; the text points to bench_calc led_strip."""
    rep = modcheck.run(chip="esp32s3", assignments=[k.assign("out", 16, "LED_DIN")],
                       parts=[k.mod("LED", "ws2812b", {"VDD": "5V", "VSS": "GND", "DIN": "LED_DIN"}, qty=150)],
                       options={"rail_limits": {"5V": 4.0}}, only=("mod.power_budget",))
    f = fs(rep, "mod.power_budget")[0]
    cur = modcheck._default_catalog().get("ws2812b").get("current") or {}
    if "max" in cur:  # once the LED current is in the catalog, 150 LEDs exceed 4 A
        assert (f.status, f.severity) == ("failed", "caution")
    else:
        assert f.status == "not_checked" and "150 × ws2812b" in f.message and "led_strip" in f.message
        assert "below" not in f.message


# =====================================================================================================================
# 5. facts.regulator on a chip entry
# =====================================================================================================================
def test_chip_entry_behind_a_user_confirmed_regulator_is_info():
    m = dmod("fe_33", supply={"min": F(1.7), "max": F(3.6), "abs_max": F(4.0)})
    rep = run([dig("fe_33", vcc="5V")], extra=[m], only=("mod.supply_range",))
    assert [(f.status, f.severity) for f in fs(rep, "mod.supply_range")] == [("failed", "danger")]
    rep = run([dig("fe_33", vcc="5V", facts={"regulator": "3V3"})], extra=[m], only=("mod.supply_range",))
    f = fs(rep, "mod.supply_range")[0]
    assert (f.status, f.severity) == ("failed", "info")
    assert "behind the board regulator (user-confirmed" in f.message


def test_regulator_fact_does_not_hide_a_chip_that_fails_even_at_3v3():
    m = dmod("fe_5only", supply={"min": F(4.5), "max": F(5.5), "abs_max": F(6.0)})
    rep = run([dig("fe_5only", vcc="5V", facts={"regulator": "3V3"})], extra=[m], only=("mod.supply_range",))
    assert fs(rep, "mod.supply_range")[0].status == "passed"  # 5 V within 4.5–5.5 V: no regulator logic needed
    m = dmod("fe_lo", supply={"min": F(1.7), "max": F(2.0), "abs_max": F(2.5)})
    rep = run([dig("fe_lo", vcc="5V", facts={"regulator": "3V3"})], extra=[m], only=("mod.supply_range",))
    assert fs(rep, "mod.supply_range")[0].severity == "danger"  # even 3.3 V is above abs_max


def test_real_gy_bme280_at_5v_with_regulator_fact():
    """probe gy_bme280_5v_facts: no danger on the chip."""
    parts = [k.mod("U1", "bme280", {"VDD": "5V", "VDDIO": "5V", "GND": "GND", "SDI": "SDA0", "SCK": "SCL0",
                                    "SDO": "GND"}, facts={"regulator": "3V3", "pullups": "10k", "pullups_to": "3V3"})]
    rep = modcheck.run(chip="esp32s3", assignments=BUS, parts=parts, options={})
    hard = [f for f in rep.findings if f.rule_id.startswith("mod.") and f.status == "failed"
            and f.severity == "danger"]
    assert not hard, [f.message for f in hard]
    sr = fs(rep, "mod.supply_range")
    assert sr and all(f.severity == "info" and "user-confirmed" in f.message for f in sr)


# =====================================================================================================================
# 6. io.domain_v
# =====================================================================================================================
DV = F(2.8, conditions="internal I/O domain")


def test_domain_v_validation():
    assert "domain_v" in modspec.IO_KEYS
    assert modspec.domain_v_problems({}) == [] and modspec.domain_v_problems({"domain_v": DV}) == []
    bad = {
        "number": 2.8, "unit": F(2.8, "A"), "zero": F(0), "too high": F(61), "bool": F(True),
        "rel": {**R(0.8, "VCC")}, "no page": {"value": 2.8, "unit": "V", "evidence": "x"},
        "no evidence": {"value": 2.8, "unit": "V", "page": 1}, "unknown key": {**DV, "typ": 1},
    }
    for name, f in bad.items():
        assert modspec.domain_v_problems({"domain_v": f}), name


def _sim(dv=None, voh=None):
    extra = {"domain_v": dv} if dv is not None else {}
    return dmod("fe_sim", supply_pin="VBAT", voh=voh, vih=F(2.1), v_in_max={"rel_offset": 0.3, "of": "VBAT",
                "unit": "V", "page": 1, "evidence": "VBAT + 0.3 V"},
                supply={"min": F(3.4), "max": F(4.4), "abs_max": F(5.0)}, extra_io=extra)


def test_domain_v_replaces_the_supply_in_level_out():
    parts, opts = [dig("fe_sim", pin="VBAT", vcc="VB")], {"rails": {"VB": 4.0}}
    rep = run(parts, extra=[_sim()], options=opts, only=("mod.level_out",))
    assert fs(rep, "mod.level_out")[0].severity == "danger"  # push-pull high = VBAT 4.0 V > 3.6 V
    rep = run(parts, extra=[_sim(DV)], options=opts, only=("mod.level_out",))
    f = fs(rep, "mod.level_out")[0]
    assert f.status == "passed" and "2.80 V" in f.message, f.message
    bad = {"value": 2.8, "unit": "V"}  # invalid (no page / evidence): ignored, never trusted
    rep = run(parts, extra=[_sim(bad)], options=opts, only=("mod.level_out",))
    assert fs(rep, "mod.level_out")[0].severity == "danger"


def test_domain_v_replaces_the_supply_in_level_in():
    parts, opts = [dig("fe_sim", pin="VBAT", vcc="VB")], {"rails": {"VB": 4.0}}
    rep = run(parts, extra=[_sim()], options=opts, only=("mod.level_in",))
    assert fs(rep, "mod.level_in")[0].status == "passed"  # v_in_max = 4.3 V
    rep = run(parts, extra=[_sim(DV)], options=opts, only=("mod.level_in",))
    f = fs(rep, "mod.level_in")[0]
    assert (f.status, f.severity) == ("failed", "danger") and "3.10 V" in f.message, f.message


def test_domain_v_keeps_supply_conditions_on_the_supply():
    m = _sim(DV)
    m["io"]["vih"] = F(2.1, conditions="VBAT 3.4–4.4 V")
    rep = run([dig("fe_sim", pin="VBAT", vcc="VB")], extra=[m], options={"rails": {"VB": 4.0}},
              only=("mod.level_in",))
    assert "never interpolated" not in fs(rep, "mod.level_in")[0].message


# =====================================================================================================================
# 7. mod.required_parts: recommendation vs. requirement
# =====================================================================================================================
@pytest.mark.parametrize("code,evidence,want", [
    ("bulk_cap", "a bypass capacitor (low ESR) such as a 100 uF is strongly recommended.", "caution"),
    ("bulk_cap", "a 100 µF capacitor is recommended", "caution"),
    ("bulk_cap", "an optional 100 µF capacitor", "info"),
    ("decoupling", "The recommended value for C1 is 100 nF", "caution"),
    ("decoupling", "a 100 nF capacitor is recommended", "info"),
    ("decoupling", "100 nF is highly recommended", "caution"),
])
def test_required_parts_hint_or_requirement(code, evidence, want):
    req = [{"code": code, "kind": "capacitor", "value": "100 µF", "pins": ["VCC"], "to": "GND", "page": 3,
            "evidence": evidence}]
    rep = run([dig("fe_req")], extra=[dmod("fe_req", requires=req)], only=("mod.required_parts",))
    f = fs(rep, "mod.required_parts")[0]
    assert (f.status, f.severity) == ("failed", want), f.message


def test_real_sim800l_bulk_cap_is_caution():
    """p35: SIM800L without a 100 µF buffer capacitor (2 A bursts) is caution."""
    parts = [k.mod("U1", "sim800l", {"VBAT": "VB", "GND": "GND", "TXD": "RX1", "RXD": "TX1"})]
    rep = modcheck.run(chip="esp32s3", assignments=[k.assign("in", 5, "RX1"), k.assign("out", 4, "TX1")],
                       parts=parts, options={"rails": {"VB": 4.0}}, only=("mod.required_parts",))
    f = [x for x in fs(rep, "mod.required_parts") if "bulk_cap" in x.message]
    assert f and f[0].severity == "caution", [x.message for x in f]


# =====================================================================================================================
# p5: pull-up voltage of open-drain nets
# =====================================================================================================================
OD = dmod("fe_od", i2c=True, v_in_max=F(6.0))
LOW = dmod("fe_low", i2c=True, supply_pin="VS", v_in_max={"rel_offset": 0.3, "of": "VS", "unit": "V", "page": 1,
                                                          "evidence": "VS + 0.3 V"})


def od(ref="U1", mid="fe_od", vcc="5V", pin="VCC", sda="SDA0", scl="SCL0", facts=None):
    return k.mod(ref, mid, {pin: vcc, "GND": "GND", "SDA": sda, "SCL": scl}, facts=facts)


@pytest.mark.parametrize("to,want", [("VCC", "danger"), ("5V", "danger"), ("5", "danger"), ("5 V", "danger"),
                                     ("3V3", None), ("NOPE", "caution")])
def test_pullups_to_pin_net_or_number(to, want):
    rep = run([od(facts={"pullups": "4k7", "pullups_to": to})], extra=[OD], assignments=BUS, only=("mod.level_out",))
    got = {f.severity for f in fs(rep, "mod.level_out")}
    assert got == {want}, [f.message for f in fs(rep, "mod.level_out")]


def test_real_pcf8574_lcd_backpack_pullups_to_vcc_is_danger():
    """p5: PCF8574 with facts pullups_to "VCC", VCC on 5 V: never 'no pull-up to a rail above 3.60 V'."""
    parts = [k.mod("U1", "pcf8574", {"VCC": "5V", "GND": "GND", "SDA": "SDA0", "SCL": "SCL0", "A0": "5V",
                                     "A1": "5V", "A2": "5V"}, facts={"pullups": "4k7", "pullups_to": "VCC"})]
    rep = modcheck.run(chip="esp32s3", assignments=BUS, parts=parts, options={}, only=("mod.level_out",))
    assert {f.severity for f in fs(rep, "mod.level_out")} == {"danger"}


def test_other_module_on_a_5v_pulled_bus_is_danger():
    parts = [od(facts={"pullups": "4k7", "pullups_to": "VCC"}), od("U2", "fe_low", vcc="3V3", pin="VS")]
    rep = run(parts, extra=[OD, LOW], assignments=BUS, only=("mod.level_in",))
    bad = [f for f in fs(rep, "mod.level_in") if "U2" in f.refs]
    assert bad and all(f.severity == "danger" for f in bad), [f.message for f in fs(rep, "mod.level_in")]


def test_open_drain_net_without_esp_pin_checks_every_module_input():
    pu = [{"ref": "R1", "kind": "resistor", "value": "4k7", "conn": {"1": "SDA5", "2": "5V"}},
          {"ref": "R2", "kind": "resistor", "value": "4k7", "conn": {"1": "SCL5", "2": "5V"}}]
    parts = [od(sda="SDA5", scl="SCL5"), od("U2", "fe_low", vcc="3V3", pin="VS", sda="SDA5", scl="SCL5"), *pu]
    rep = run(parts, extra=[OD, LOW], assignments=BUS, only=("mod.level_in",))
    got = [(f.refs, f.severity) for f in fs(rep, "mod.level_in")]
    assert len(got) == 2 and all(g == (["U2"], "danger") for g in got), got  # SDA5 and SCL5
    parts[1] = od("U2", "fe_low", vcc="5V", pin="VS", sda="SDA5", scl="SCL5")  # VS 5 V: 5.3 V max, fine
    assert fs(run(parts, extra=[OD, LOW], assignments=BUS, only=("mod.level_in",)), "mod.level_in") == []


def test_pullups_unknown_on_a_chip_entry_asks_to_measure():
    req = [{"code": "pullup", "kind": "resistor", "pins": ["SDA", "SCL"], "to": "VCC", "page": 2, "evidence": "x"}]
    m = dmod("fe_odr", i2c=True, v_in_max=F(6.0), requires=req)
    rep = run([od(mid="fe_odr", facts={"pullups": "unknown"})], extra=[m], assignments=BUS,
              only=("mod.level_out", "mod.required_parts"))
    assert {f.severity for f in fs(rep, "mod.level_out")} == {"caution"}  # board pull-ups may sit on 5 V
    f = fs(rep, "mod.required_parts")[0]
    assert f.severity == "info" and "measure" in f.message and "R_min" in f.message
    pu = [{"ref": "R1", "kind": "resistor", "value": "4k7", "conn": {"1": "SDA0", "2": "3V3"}},
          {"ref": "R2", "kind": "resistor", "value": "4k7", "conn": {"1": "SCL0", "2": "3V3"}}]
    rep = run([od(mid="fe_odr", facts={"pullups": "unknown"}), *pu], extra=[m], assignments=BUS,
              only=("mod.required_parts",))
    f = fs(rep, "mod.required_parts")[0]
    assert (f.status, f.severity) == ("failed", "info") and "parallel value" in f.message
