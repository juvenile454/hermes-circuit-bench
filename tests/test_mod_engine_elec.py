"""Generic electrical module rules.

mod.supply_range (extension), mod.level_in, mod.level_out, mod.power_budget, mod.required_parts, mod.hazard with the
full severity cap. Every rule: positive, negative, edge case, data missing. Honesty tests (breakout without facts,
class B, missing ESP values, unmet conditions) and a false-alarm list of ten correct projects. Synthetic modules
(``ee_*``) live here; values are invented, sources are the ``tst-`` sources of tests/mod_fixtures.py.
"""
from __future__ import annotations

import copy

import pytest

import mod_fixtures as fx
import modkit as k
from circuit_bench.bench_core import contracts, electrical, modcheck, modules, pins

F, R = fx.F, fx.R
GND = fx.GND
BUS = k.i2c()  # GPIO8 SDA0, GPIO9 SCL0
I2C = {"SDA": "SDA0", "SCL": "SCL0"}
MY_CODES = {"mod_supply_range", "mod_level_in", "mod_level_out", "mod_power_budget", "mod_required_parts",
            "mod_hazard"}
MY_RULES = tuple(f"mod.{c[4:]}" for c in sorted(MY_CODES))
PU = [{"ref": "R1", "kind": "resistor", "value": "4k7", "conn": {"1": "SDA0", "2": "3V3"}},
      {"ref": "R2", "kind": "resistor", "value": "4k7", "conn": {"1": "SCL0", "2": "3V3"}}]


def pullups(to: str = "3V3", sda: str = "SDA0", scl: str = "SCL0") -> list[dict]:
    return [{"ref": "R1", "kind": "resistor", "value": "4k7", "conn": {"1": sda, "2": to}},
            {"ref": "R2", "kind": "resistor", "value": "4k7", "conn": {"1": scl, "2": to}}]


def part(ref: str, kind: str, a: str, b: str, value: str = "x") -> dict:
    return {"ref": ref, "kind": kind, "value": value, "conn": {"1": a, "2": b}}


def gpio_mod(mid: str = "ee_gpio", *, kind: str = "ic", src: str = "tst-5v-ds", vih=None, vil=None, voh=None,
             v_in_max=None, outputs: str | None = "push_pull", domain: str | None = "VCC", supply=None,
             pins_extra=(), current=None, requires=None, hazards=None, extra_io=None) -> dict:
    """A synthetic digital part: VCC/GND, DIN (digital_in), DOUT (digital_out), AOUT (analog_out), INT (open drain)."""
    io = {}
    if domain:
        io["domain"] = domain
    for key, val in (("vih", vih), ("vil", vil), ("voh", voh), ("v_in_max", v_in_max)):
        if val is not None:
            io[key] = val
    if outputs:
        io["outputs"] = outputs
    io.update(extra_io or {})
    m = {"id": mid, "title": f"EE {mid}", "category": "sensor.light", "manufacturer": "Test", "kind": kind,
         "source_ids": [src],
         "supplies": {"VCC": supply or {"min": F(1.8), "max": F(5.5), "abs_max": F(6.0)}},
         "io": io,
         "pins": [{"name": "VCC", "signal": "supply"}, GND, {"name": "DIN", "signal": "digital_in"},
                  {"name": "DOUT", "signal": "digital_out"}, {"name": "AOUT", "signal": "analog_out"},
                  {"name": "INT", "signal": "open_drain_out"}, *pins_extra],
         "interfaces": [{"type": "digital"}]}
    if current is not None:
        m["current"] = current
    if requires is not None:
        m["requires"] = requires
    if hazards is not None:
        m["hazards"] = hazards
    return m


def run(parts, *, extra=(), assignments=None, options=None, only=None, esp=None, devkit=None):
    return k.run(catalog=fx.catalog(*extra), electrical=fx.ESP if esp is None else esp,
                 assignments=BUS if assignments is None else assignments, parts=parts, options=options,
                 devkit=devkit, only=only)


def fs(rep, rule_id, status=None):
    return k.findings(rep, rule_id, status)


def sev_of(rep, rule_id):
    return [(f.status, f.severity) for f in fs(rep, rule_id)]


DIG = [k.assign("out", 4, "DIN"), k.assign("in", 5, "DOUT"), k.assign("adc", 1, "AOUT")]


def dig(mid="ee_gpio", vcc="3V3", facts=None, conn=None, ref="U1", **_):
    return k.mod(ref, mid, {"VCC": vcc, "DIN": "GPIO4", "DOUT": "GPIO5", "AOUT": "GPIO1", **(conn or {})},
                 facts=facts)


# =====================================================================================================================
# mod.supply_range (extension)
# =====================================================================================================================
def test_supply_edge_values_are_not_interpolated():
    m = gpio_mod(supply={"min": F(3.3), "max": F(3.6), "abs_max": F(5.0)})
    rep = run([dig(vcc="3V3")], extra=[m], assignments=DIG, only=("mod.supply_range",))
    assert sev_of(rep, "mod.supply_range") == [("passed", None)]  # v == min
    rep = run([dig(vcc="V36")], extra=[m], assignments=DIG, options={"rails": {"V36": 3.6}}, only=("mod.supply_range",))
    assert sev_of(rep, "mod.supply_range") == [("passed", None)]  # v == max
    rep = run([dig(vcc="5V")], extra=[m], assignments=DIG, only=("mod.supply_range",))
    assert sev_of(rep, "mod.supply_range") == [("failed", "caution")]  # v == abs_max: above max, not danger


def test_supply_on_gnd_is_not_powered():
    rep = run([dig(vcc="GND")], extra=[gpio_mod()], assignments=DIG, only=("mod.supply_range",))
    f = fs(rep, "mod.supply_range")[0]
    assert (f.status, f.severity) == ("failed", "caution") and "not powered" in f.message


def test_supply_from_a_gpio_is_not_a_rail():
    rep = run([dig(vcc="GPIO6")], extra=[gpio_mod()], assignments=[*DIG, k.assign("out", 6, "PWR")],
              only=("mod.supply_range",))
    f = fs(rep, "mod.supply_range")[0]
    assert (f.status, f.severity) == ("not_checked", "info") and "GPIO6" in f.message


def test_supply_from_a_gpio_above_abs_max_is_danger():
    m = gpio_mod(supply={"min": F(1.7), "max": F(2.0), "abs_max": F(2.5)})
    rep = run([dig(vcc="GPIO6")], extra=[m], assignments=[*DIG, k.assign("out", 6, "PWR")],
              only=("mod.supply_range",))
    f = fs(rep, "mod.supply_range")[0]
    assert (f.status, f.severity) == ("failed", "danger") and "2.50 V" in f.message
    assert "tst-esp-ds" in f.source_ids


def test_supply_unknown_rail_and_open_pin_are_not_checked():
    rep = run([dig(vcc="VX")], extra=[gpio_mod()], assignments=DIG, only=("mod.supply_range",))
    assert sev_of(rep, "mod.supply_range") == [("not_checked", "info")]
    rep = run([k.mod("U1", "ee_gpio", {"DIN": "GPIO4"})], extra=[gpio_mod()], assignments=DIG,
              only=("mod.supply_range",))
    assert sev_of(rep, "mod.supply_range") == [("not_checked", None)]


@pytest.mark.parametrize(("src", "kind", "facts", "want"), [
    ("tst-5v-ds", "ic", None, "danger"),          # A, bare chip: full rule
    ("tst-mux-ds", "ic", None, "danger"),         # A1
    ("tst-oled-ds", "ic", None, "danger"),        # A2: may be hard
    ("tst-bsensor-shop", "ic", None, "info"),     # B: never hard
    ("tst-5v-ds", "module", None, "caution"),     # breakout without facts
    ("tst-5v-ds", "module", {"regulator": "unknown"}, "caution"),
    ("tst-5v-ds", "module", {"regulator": "none"}, "danger"),
    ("tst-5v-ds", "module", {"regulator": "3V3"}, "info"),
    ("tst-bsensor-shop", "module", {"regulator": "none"}, "info"),
])
def test_supply_cap_matrix(src, kind, facts, want):
    m = gpio_mod(kind=kind, src=src, supply={"min": F(1.7), "max": F(3.6), "abs_max": F(4.0)})
    rep = run([dig(vcc="5V", facts=facts)], extra=[m], assignments=DIG, only=("mod.supply_range",))
    assert sev_of(rep, "mod.supply_range") == [("failed", want)]


# =====================================================================================================================
# mod.level_in
# =====================================================================================================================
def _lin(vih=None, vcc="3V3", facts=None, kind="ic", src="tst-5v-ds", esp=None, options=None, **kw):
    m = gpio_mod(kind=kind, src=src, vih=vih, **kw)
    rep = run([dig(vcc=vcc, facts=facts)], extra=[m], assignments=DIG, options=options, only=("mod.level_in",),
              esp=esp)
    return rep, fs(rep, "mod.level_in")


def test_level_in_vih_above_esp_vdd_is_not_recognised():
    rep, f = _lin(vih=R(0.7, "VCC"), vcc="5V")  # 3.50 V > 3.30 V
    assert [(x.status, x.severity) for x in f] == [("failed", "caution")]
    assert "not recognised" in f[0].message and "3.50 V" in f[0].message and "level shifter" in f[0].message
    assert k.codes(rep) == {"mod_level_in"} and "tst-esp-ds" in f[0].source_ids


def test_level_in_vih_equal_to_voh_passes():
    _, f = _lin(vih=F(2.64))
    assert [(x.status, x.severity) for x in f] == [("passed", None)]


def test_level_in_vih_between_voh_and_vdd_is_outside_the_guaranteed_levels():
    for v in (2.65, 3.3):  # just above VOH, and exactly VDD
        _, f = _lin(vih=F(v))
        assert [(x.status, x.severity) for x in f] == [("failed", "caution")], v
        assert "outside the guaranteed levels" in f[0].message and "2.64 V" in f[0].message


def test_level_in_low_level_against_esp_vol():
    _, f = _lin(vih=F(2.0), vil=F(0.3))  # VIL 0.30 V < ESP VOL 0.33 V
    assert [(x.status, x.severity) for x in f] == [("failed", "caution")] and "VIL" in f[0].message
    _, f = _lin(vih=F(2.0), vil=F(0.33))
    assert f[0].status == "passed"


def test_level_in_esp_high_above_module_input_maximum_is_danger():
    opts = {"rails": {"V18": 1.8}}
    _, f = _lin(vih=R(0.7, "VCC"), vcc="V18", options=opts,
                v_in_max={"rel_offset": 0.3, "of": "VCC", "unit": "V", "page": 1, "evidence": "x"})
    assert [(x.status, x.severity) for x in f] == [("failed", "danger")] and "2.10 V" in f[0].message
    _, f = _lin(vih=R(0.7, "VCC"), vcc="V30", options={"rails": {"V30": 3.0}},
                v_in_max={"rel_offset": 0.3, "of": "VCC", "unit": "V", "page": 1, "evidence": "x"})
    assert f[0].status == "passed"  # 3.30 V == 3.0 V + 0.3 V: edge, allowed


def test_level_in_level_shifter_fact_passes_with_a_hint():
    _, f = _lin(vih=R(0.7, "VCC"), vcc="5V", kind="module", facts={"level_shifter": True, "regulator": "none"})
    assert [(x.status, x.severity) for x in f] == [("passed", None)] and "level shifter" in f[0].message


def test_level_in_without_vih_is_not_checked():
    rep, f = _lin(vih=None)
    assert [(x.status, x.severity) for x in f] == [("not_checked", None)] and k.codes(rep) == set()
    rep, f = _lin(vih=None, vcc="5V")  # module above the ESP's VDD: say so (info)
    assert [(x.status, x.severity) for x in f] == [("not_checked", "info")]


def test_level_in_without_esp_values_is_not_checked():
    for esp in ({}, {**fx.ESP, "voh": None}):
        _, f = _lin(vih=R(0.7, "VCC"), vcc="5V", esp=esp)
        assert [(x.status, x.severity) for x in f] == [("not_checked", "info")]
        assert "No DC characteristics" in f[0].message


def test_level_in_unmet_condition_is_never_interpolated():
    vih = F(3.15, conditions="VCC = 4.5 V")
    _, f = _lin(vih=vih, vcc="5V")
    assert [(x.status, x.severity) for x in f] == [("not_checked", "info")]
    assert "never interpolated" in f[0].message and "4.5 V" in f[0].message
    _, f = _lin(vih=vih, vcc="V45", options={"rails": {"V45": 4.5}})
    assert [(x.status, x.severity) for x in f] == [("failed", "caution")]  # 3.15 V: outside the guaranteed levels
    rng = R(0.7, "VCC") | {"conditions": "VCC 2.0–3.6 V"}
    _, f = _lin(vih=rng, vcc="5V")
    assert f[0].status == "not_checked"
    _, f = _lin(vih=rng, vcc="3V3")
    assert f[0].status == "passed"  # 2.31 V


def test_level_in_caps():
    _, f = _lin(vih=R(0.7, "VCC"), vcc="5V", src="tst-bsensor-shop")
    assert (f[0].status, f[0].severity) == ("failed", "info") and "Unverified" in f[0].message
    _, f = _lin(vih=R(0.7, "VCC"), vcc="V18", options={"rails": {"V18": 1.8}}, kind="module",
                v_in_max={"rel_offset": 0.3, "of": "VCC", "unit": "V", "page": 1, "evidence": "x"})
    assert (f[0].status, f[0].severity) == ("failed", "caution") and "Breakout board" in f[0].message


def test_level_in_on_i2c_uses_the_known_pullup_voltage():
    sensor = k.mod("U1", "tst_sensor", {**I2C, "VDD": "3V3", "SDO": "GND"})
    rep = run([sensor, *pullups("3V3")], only=("mod.level_in",))
    assert {(f.status, f.severity) for f in fs(rep, "mod.level_in")} == {("passed", None)}
    rep = run([sensor, *pullups("5V")], only=("mod.level_in",))  # 5 V > VDDIO + 0.3 V = 3.6 V
    f = fs(rep, "mod.level_in")
    assert [(x.status, x.severity) for x in f] == [("failed", "danger")] * 2 and "5.00 V" in f[0].message
    rep = run([sensor], only=("mod.level_in",))  # no pull-ups: nothing to compare (see required_parts)
    assert fs(rep, "mod.level_in") == []


# =====================================================================================================================
# mod.level_out
# =====================================================================================================================
def _lout(vcc="3V3", facts=None, kind="ic", src="tst-5v-ds", options=None, esp=None, extra_parts=(), **kw):
    m = gpio_mod(kind=kind, src=src, **kw)
    rep = run([dig(vcc=vcc, facts=facts), *extra_parts], extra=[m], assignments=DIG, options=options,
              only=("mod.level_out",), esp=esp)
    return rep, [f for f in fs(rep, "mod.level_out") if "DOUT" in f.message]


def test_level_out_push_pull_5v_is_danger():
    _, f = _lout(vcc="5V")
    assert [(x.status, x.severity) for x in f] == [("failed", "danger")]
    assert "5.00 V" in f[0].message and "3.60 V" in f[0].message and "GPIO5" in f[0].message
    assert set(f[0].source_ids) == {"tst-5v-ds", "tst-esp-ds"}


def test_level_out_push_pull_at_3v3_and_edge_pass():
    _, f = _lout(vcc="3V3", voh=R(0.9, "VCC"))
    assert [(x.status, x.severity) for x in f] == [("passed", None)]
    _, f = _lout(vcc="V36", options={"rails": {"V36": 3.6}})  # == v_in_max: allowed
    assert f[0].status == "passed"
    _, f = _lout(vcc="V361", options={"rails": {"V361": 3.61}})
    assert (f[0].status, f[0].severity) == ("failed", "danger")


def test_level_out_low_high_level():
    _, f = _lout(vcc="V18", options={"rails": {"V18": 1.8}})
    assert (f[0].status, f[0].severity) == ("failed", "caution") and "VIH" in f[0].message
    _, f = _lout(vcc="3V3", voh=F(2.4))  # VOH 2.40 V < ESP VIH 2.475 V
    assert (f[0].status, f[0].severity) == ("failed", "caution") and "guaranteed" in f[0].message


def test_level_out_unknown_output_type_is_caution():
    _, f = _lout(vcc="5V", outputs=None)
    assert (f[0].status, f[0].severity) == ("failed", "caution") and "output type" in f[0].message


def test_level_out_unknown_domain_voltage_is_not_checked():
    _, f = _lout(vcc="VX")
    assert [(x.status, x.severity) for x in f] == [("not_checked", None)]


@pytest.mark.parametrize(("kind", "facts", "want"), [
    ("ic", None, "danger"), ("module", None, "caution"), ("module", {"regulator": "none"}, "danger"),
    ("module", {"regulator": "3V3"}, None), ("module", {"level_shifter": True}, None),  # user-confirmed, as in level_in
])
def test_level_out_breakout_cap(kind, facts, want):
    _, f = _lout(vcc="5V", kind=kind, facts=facts)
    assert f[0].severity == want, f[0].message
    if kind == "module" and want == "caution":
        assert "Breakout board" in f[0].message


def test_level_out_without_esp_values_is_not_checked():
    rep, _ = _lout(vcc="5V", esp={})
    f = fs(rep, "mod.level_out")
    assert [(x.status, x.severity) for x in f] == [("not_checked", "info")] and "No DC" in f[0].message


def test_level_out_analog_output():
    rep, _ = _lout(vcc="3V3")
    a = [f for f in fs(rep, "mod.level_out") if "AOUT" in f.message]
    assert [(x.status, x.severity) for x in a] == [("not_checked", None)] and "ADC range" in a[0].message
    rep, _ = _lout(vcc="5V")
    a = [f for f in fs(rep, "mod.level_out") if "AOUT" in f.message]
    assert [(x.status, x.severity) for x in a] == [("failed", "caution")]


def test_level_out_open_drain_pin_follows_its_pullup():
    asg = [*DIG, k.assign("in", 7, "INT", )]
    m = gpio_mod()
    conn = {"VCC": "3V3", "INT": "GPIO7"}
    rep = run([k.mod("U1", "ee_gpio", conn), part("R5", "resistor", "GPIO7", "5V")], extra=[m], assignments=asg,
              only=("mod.level_out",))
    f = [x for x in fs(rep, "mod.level_out") if "GPIO7" in x.message]
    assert [(x.status, x.severity) for x in f] == [("failed", "danger")] and "R5 to 5V" in f[0].message
    rep = run([k.mod("U1", "ee_gpio", conn), part("R5", "resistor", "GPIO7", "3V3")], extra=[m], assignments=asg,
              only=("mod.level_out",))
    assert [x.status for x in fs(rep, "mod.level_out") if "GPIO7" in x.message] == ["passed"]


def test_i2c_pullup_resistor_to_5v_is_danger_even_for_class_b():
    for mid, conn in (("tst_sensor", {**I2C, "VDD": "3V3", "SDO": "GND"}), ("tst_bsensor", {**I2C, "VCC": "3V3"})):
        rep = run([k.mod("U1", mid, conn), *pullups("5V")], only=("mod.level_out",))
        f = fs(rep, "mod.level_out")
        assert [(x.status, x.severity) for x in f] == [("failed", "danger")] * 2, mid  # SDA0, SCL0
        assert "R1 to 5V" in f[0].message and f[0].source_ids == ["tst-esp-ds"]


def test_i2c_pullup_edges():
    sensor = k.mod("U1", "tst_sensor", {**I2C, "VDD": "3V3", "SDO": "GND"})
    rep = run([sensor, *pullups("V36")], options={"rails": {"V36": 3.6}}, only=("mod.level_out",))
    assert {x.status for x in fs(rep, "mod.level_out")} == {"passed"}  # == v_in_max
    rep = run([sensor, *pullups("V18")], options={"rails": {"V18": 1.8}}, only=("mod.level_out",))
    assert {(x.status, x.severity) for x in fs(rep, "mod.level_out")} == {("failed", "caution")}  # < VIH
    rep = run([sensor, *pullups("VPU")], only=("mod.level_out",))  # voltage of VPU unknown
    f = fs(rep, "mod.level_out")
    assert {(x.status, x.severity) for x in f} == {("failed", "caution")} and "confirm the pull-up" in f[0].message
    rep = run([sensor], only=("mod.level_out",))  # no pull-up at all: nothing above 3.6 V
    assert {x.status for x in fs(rep, "mod.level_out")} == {"passed"}


@pytest.mark.parametrize(("vin", "facts", "want"), [
    ("5V", None, ("failed", "caution")),                         # breakout pull-ups may sit on 5 V
    ("5V", {"pullups_to": "3V3"}, ("passed", None)),
    ("5V", {"pullups_to": "5V"}, ("failed", "danger")),          # user fact + ESP datasheet: hard
    ("5V", {"pullups": "none"}, ("passed", None)),
    ("5V", {"regulator": "3V3"}, ("failed", "info")),            # 3.3 V board: hint to confirm
    ("5V", {"pullups_to": "VPU"}, ("failed", "caution")),
    ("3V3", None, ("passed", None)),
])
def test_i2c_breakout_pullups(vin, facts, want):
    rep = run([k.mod("U1", "tst_breakout", {**I2C, "VIN": vin, "ADR": "GND"}, facts=facts)], only=("mod.level_out",))
    f = fs(rep, "mod.level_out")
    assert {(x.status, x.severity) for x in f} == {want}, [x.message for x in f]


# =====================================================================================================================
# mod.power_budget
# =====================================================================================================================
def oled(ref="U1", vdd="3V3", qty=None):
    return k.mod(ref, "tst_oled", {**I2C, "VDD": vdd}, qty=qty)


def test_power_budget_within_limit_passes_and_names_the_sums():
    rep = run([oled()], options={"rail_limits": {"3V3": 0.5}}, only=("mod.power_budget",))
    f = fs(rep, "mod.power_budget")
    assert [(x.status, x.severity) for x in f] == [("passed", None)]
    assert "typ 8.00 mA" in f[0].message and "max 20.0 mA" in f[0].message and "peak 30.0 mA" in f[0].message


def test_power_budget_max_above_limit_is_caution():
    rep = run([oled(qty=3)], options={"rail_limits": {"3V3": 0.05}}, only=("mod.power_budget",))
    f = fs(rep, "mod.power_budget")[0]
    assert (f.status, f.severity) == ("failed", "caution") and "maximum current 60.0 mA" in f.message
    assert "50.0 mA" in f.message and "(user)" in f.message and k.codes(rep) == {"mod_power_budget"}


def test_power_budget_peak_above_limit_is_named_separately():
    rep = run([oled()], options={"rail_limits": {"3V3": 0.025}}, only=("mod.power_budget",))
    f = fs(rep, "mod.power_budget")[0]
    assert (f.status, f.severity) == ("failed", "caution") and "peak current 30.0 mA" in f.message


def test_power_budget_limit_equal_to_the_sum_passes():
    rep = run([oled()], options={"rail_limits": {"3V3": 0.03}}, only=("mod.power_budget",))
    assert sev_of(rep, "mod.power_budget") == [("passed", None)]


def test_power_budget_without_limit_lists_sums_without_a_warning():
    rep = run([oled()], only=("mod.power_budget",))
    f = fs(rep, "mod.power_budget")
    assert [(x.status, x.severity) for x in f] == [("not_checked", None)] and "max 20.0 mA" in f[0].message
    assert rep.warnings == [] and k.check_of(rep, "mod.power_budget")["status"] == "not_checked"


def test_power_budget_names_missing_current_values():
    rep = run([oled(), k.mod("U2", "tst_bsensor", {**I2C, "VCC": "3V3"})], options={"rail_limits": {"3V3": 0.5}},
              only=("mod.power_budget",))
    f = fs(rep, "mod.power_budget")[0]
    assert (f.status, f.severity) == ("not_checked", "info") and "U2 has no current data" in f.message
    assert "max 20.0 mA" in f.message and "known" in f.message and "below" not in f.message  # no claim about unknown parts


def test_power_budget_board_limit_from_the_devkit():
    class El:
        def get(self, chip):
            return dict(fx.ESP)

        def boards(self):
            return {"tst_kit": {"rail_3v3_limit": F(0.025, "A", "tst-esp-ds")}}

    rep = k.run(catalog=fx.catalog(), electrical=El(), assignments=BUS, parts=[oled()], devkit="tst_kit",
                only=("mod.power_budget",))
    f = fs(rep, "mod.power_budget")[0]
    assert (f.status, f.severity) == ("failed", "caution") and "tst-esp-ds" in f.message
    assert "tst-esp-ds" in f.source_ids


def test_power_budget_class_b_and_breakout_caps():
    big = gpio_mod("ee_big", src="tst-bsensor-shop", current={"supply": "VCC", "max": F(0.4, "A")})
    rep = run([dig("ee_big")], extra=[big], assignments=DIG, options={"rail_limits": {"3V3": 0.1}},
              only=("mod.power_budget",))
    assert sev_of(rep, "mod.power_budget") == [("failed", "info")]
    big_a = gpio_mod("ee_big", kind="module", current={"supply": "VCC", "max": F(0.4, "A")})
    rep = run([dig("ee_big")], extra=[big_a], assignments=DIG, options={"rail_limits": {"3V3": 0.1}},
              only=("mod.power_budget",))
    assert sev_of(rep, "mod.power_budget") == [("failed", "caution")]  # current is no breakout fact: no extra text
    assert "Breakout board" not in fs(rep, "mod.power_budget")[0].message


def test_power_budget_ignores_signal_inputs_and_checks_gpio_powered_modules():
    m = gpio_mod(current={"supply": "VCC", "max": F(0.05, "A")})
    rep = run([dig()], extra=[m], assignments=DIG, only=("mod.power_budget",))
    assert all("GPIO4" not in f.message for f in fs(rep, "mod.power_budget"))  # DIN draws nothing from GPIO4
    asg = [*DIG, k.assign("out", 6, "PWR")]
    rep = run([dig(vcc="GPIO6")], extra=[m], assignments=asg, only=("mod.power_budget",))
    f = fs(rep, "mod.power_budget")[0]
    assert (f.status, f.severity) == ("failed", "caution") and "typical source current 40.0 mA" in f.message
    rep = run([dig(vcc="GPIO6")], extra=[m], assignments=asg, only=("mod.power_budget",),
              esp={**fx.ESP, "i_out_total_max": 0.045})
    assert sev_of(rep, "mod.power_budget") == [("failed", "danger")]
    small = gpio_mod(current={"supply": "VCC", "max": F(0.002, "A")})
    rep = run([dig(vcc="GPIO6")], extra=[small], assignments=asg, only=("mod.power_budget",))
    assert sev_of(rep, "mod.power_budget") == [("not_checked", "info")]


# =====================================================================================================================
# mod.required_parts
# =====================================================================================================================
REQ = [
    {"code": "pullup", "kind": "resistor", "value": "10k", "pins": ["INT"], "to": "VCC", "page": 7, "evidence": "x"},
    {"code": "decoupling", "kind": "ceramic", "value": "100nF", "pins": ["VCC"], "to": "GND", "page": 9,
     "evidence": "Place a 100 nF capacitor close to VCC"},
]


def req_mod(requires=REQ, **kw):
    return gpio_mod("ee_req", requires=requires, **kw)


def rq(parts, requires=REQ, conn=None, facts=None, options=None, kind="ic", src="tst-5v-ds", extra_mods=()):
    u = k.mod("U1", "ee_req", {"VCC": "3V3", "INT": "GPIO7", "DIN": "GPIO4", **(conn or {})}, facts=facts)
    rep = run([u, *parts], extra=[req_mod(requires, kind=kind, src=src), *extra_mods],
              assignments=[*DIG, k.assign("in", 7, "INT")], options=options, only=("mod.required_parts",))
    return rep, fs(rep, "mod.required_parts")


def test_required_parts_met_by_parts():
    rep, f = rq([part("R5", "resistor", "GPIO7", "3V3"), part("C1", "ceramic", "3V3", "GND")])
    assert [(x.status, x.severity) for x in f] == [("passed", None)] * 2 and rep.warnings == []
    _, f = rq([part("R5", "resistor", "GPIO7", "VB"), part("C1", "capacitor", "GND", "3V3")],
              options={"rails": {"VB": 3.3}})  # same voltage rail, generic capacitor kind, reversed pins
    assert [x.status for x in f] == ["passed", "passed"]


def test_required_parts_missing_is_caution_with_value_and_page():
    rep, f = rq([])
    assert [(x.status, x.severity) for x in f] == [("failed", "caution")] * 2
    assert "add 10k resistor" in f[0].message and "p. 7" in f[0].message
    assert "add 100nF ceramic" in f[1].message and "p. 9" in f[1].message
    assert k.codes(rep) == {"mod_required_parts"}


def test_required_parts_wrong_nets_or_kinds_do_not_count():
    _, f = rq([part("R5", "resistor", "GPIO7", "GND"), part("C1", "ceramic", "3V3", "VX"),
               part("D1", "diode", "GPIO7", "3V3")])
    assert [x.status for x in f] == ["failed", "failed"]


def test_required_parts_pullup_on_an_esp_pin_may_go_to_3v3():
    _, f = rq([part("C1", "ceramic", "5V", "GND")], conn={"VCC": "5V"})
    assert (f[0].status, f[0].severity) == ("failed", "caution") and "to 5V (on an ESP pin: to 3V3" in f[0].message
    _, f = rq([part("R5", "resistor", "GPIO7", "3V3"), part("C1", "ceramic", "5V", "GND")], conn={"VCC": "5V"})
    assert [x.status for x in f] == ["passed", "passed"]
    _, f = rq([part("R5", "resistor", "INTN", "3V3"), part("C1", "ceramic", "5V", "GND")],
              conn={"VCC": "5V", "INT": "INTN"})  # not an ESP net: the data's rail applies
    assert f[0].status == "failed"


def test_required_parts_met_by_facts():
    _, f = rq([part("C1", "ceramic", "3V3", "GND")], kind="module", facts={"pullups": "10k"})
    assert [x.status for x in f] == ["passed", "passed"] and "facts.pullups" in f[0].message
    _, f = rq([part("C1", "ceramic", "3V3", "GND")], kind="module", facts={"pullups": "unknown"})
    assert (f[0].status, f[0].severity) == ("failed", "info") and "measure the board" in f[0].message
    assert "R_min" in f[0].message
    _, f = rq([part("C1", "ceramic", "3V3", "GND")], kind="module", facts={"pullups": "none"})
    assert (f[0].status, f[0].severity) == ("failed", "caution")


def test_required_parts_recommendation_is_info():
    reqs = [{"code": "bulk_cap", "kind": "electrolytic", "value": "10uF", "pins": ["VCC"], "to": "GND",
             "evidence": "An optional 10 uF capacitor reduces ripple"},
            {"code": "decoupling", "kind": "ceramic", "value": "100nF", "pins": ["VCC"],
             "evidence": "The recommended value for C1 is 100 nF"}]
    _, f = rq([], requires=reqs)
    assert [(x.status, x.severity) for x in f] == [("failed", "info"), ("failed", "caution")]
    assert "recommended" in f[0].message


def test_required_parts_open_pin_or_unknown_is_not_checked():
    _, f = rq([], requires=[REQ[0] | {"pins": ["DOUT"]}])  # DOUT is not connected
    assert [(x.status, x.severity) for x in f] == [("not_checked", None)]
    _, f = rq([], requires=[{"code": "flyback", "kind": "diode", "pins": ["VCC"], "evidence": "x"}])
    assert [(x.status, x.severity) for x in f] == [("not_checked", "info")]


def test_required_parts_flyback_termination_series():
    coil = [{"name": "C1P", "signal": "power_out"}, {"name": "C1N", "signal": "power_out"}]
    reqs = [{"code": "flyback", "kind": "diode", "pins": ["C1P", "C1N"], "page": 3, "evidence": "x"}]
    m = gpio_mod("ee_req", requires=reqs, pins_extra=coil)

    def go(parts):
        u = k.mod("U1", "ee_req", {"VCC": "5V", "C1P": "COILP", "C1N": "COILN"})
        return fs(run([u, *parts], extra=[m], assignments=DIG, only=("mod.required_parts",)), "mod.required_parts")

    assert [x.status for x in go([part("D1", "diode", "COILN", "COILP")])] == ["passed"]
    f = go([part("D1", "diode", "COILN", "5V")])
    assert (f[0].status, f[0].severity) == ("failed", "caution") and "across COILP and COILN" in f[0].message
    reqs = [{"code": "series_resistor", "kind": "resistor", "value": "330R", "pins": ["DIN"], "evidence": "x"}]
    _, f = rq([part("R9", "resistor", "DATA", "GPIO4")], requires=reqs, conn={"DIN": "DATA"})
    assert [x.status for x in f] == ["passed"]
    _, f = rq([], requires=reqs)
    assert f[0].severity == "caution" and "330R" in f[0].message


def test_required_parts_level_shifter_regulator_xshut():
    reqs = [{"code": "level_shifter", "kind": "module", "pins": ["DIN"], "evidence": "x"},
            {"code": "regulator", "kind": "module", "pins": ["VCC"], "evidence": "x"}]
    _, f = rq([], requires=reqs)
    assert [x.severity for x in f] == ["caution", "caution"]
    _, f = rq([], requires=reqs, kind="module", facts={"level_shifter": True, "regulator": "3V3"})
    assert [x.status for x in f] == ["passed", "passed"]
    shifter = gpio_mod("ee_shift") | {"category": "logic.level_shifter"}
    _, f = rq([k.mod("U9", "ee_shift", {"VCC": "3V3", "DIN": "GPIO4"})], requires=reqs[:1], extra_mods=[shifter])
    assert [x.status for x in f] == ["passed"] and "U9" in f[0].message
    x = [{"code": "xshut_per_device", "kind": "wire", "pins": ["DIN"], "evidence": "x"}]
    m = gpio_mod("ee_req", requires=x)
    two = [k.mod("U1", "ee_req", {"VCC": "3V3", "DIN": "GPIO4"}), k.mod("U2", "ee_req", {"VCC": "3V3", "DIN": "GPIO4"})]
    rep = run(two, extra=[m], assignments=DIG, only=("mod.required_parts",))
    assert {f.severity for f in fs(rep, "mod.required_parts")} == {"caution"}
    two[1]["conn"]["DIN"] = "GPIO5"
    rep = run(two, extra=[m], assignments=DIG, only=("mod.required_parts",))
    assert {f.status for f in fs(rep, "mod.required_parts")} == {"passed"}


def test_required_parts_bus_pullups_from_another_board():
    reqs = [{"code": "pullup", "kind": "resistor", "pins": ["SDA", "SCL"], "to": "VDDIO", "evidence": "x"}]
    s = copy.deepcopy(next(m for m in fx.MODULES if m["id"] == "tst_sensor")) | {"requires": reqs}
    parts = [k.mod("U1", "tst_sensor", {**I2C, "VDD": "3V3", "SDO": "GND"}),
             k.mod("U2", "tst_breakout", {**I2C, "VIN": "3V3"}, facts={"pullups": "4k7"})]
    rep = run(parts, extra=[s], only=("mod.required_parts",))
    assert [f.status for f in fs(rep, "mod.required_parts")] == ["passed"]
    rep = run(parts[:1], extra=[s], only=("mod.required_parts",))
    f = fs(rep, "mod.required_parts")[0]
    assert f.severity == "caution" and "bench_calc i2c_pullup" in f.message


def test_required_parts_caps():
    _, f = rq([], src="tst-bsensor-shop")
    assert {x.severity for x in f} == {"info"}
    _, f = rq([], kind="module")
    assert {x.severity for x in f} == {"caution"} and all("Breakout board" in x.message for x in f)


# =====================================================================================================================
# mod.hazard
# =====================================================================================================================
def hz(codes, src="tst-5v-ds", kind="ic", n=1):
    m = gpio_mod("ee_hz", src=src, kind=kind, hazards=[{"code": c, "text": f"{c} text."} for c in codes])
    rep = run([dig("ee_hz", ref=f"U{i + 1}") for i in range(n)], extra=[m], assignments=DIG, only=("mod.hazard",))
    return rep, fs(rep, "mod.hazard")


def test_hazard_severities():
    rep, f = hz(["mains", "li_ion", "laser", "heat", "motor_supply", "high_current"])
    assert [(x.status, x.severity) for x in f] == [("failed", s) for s in
                                                  ("danger", "danger", "danger", "caution", "caution", "caution")]
    assert "low voltage only" in f[0].message and "protected cell" in f[1].message
    assert k.codes(rep) == {"mod_hazard"}


def test_hazard_danger_is_never_capped_and_the_rest_is():
    _, f = hz(["mains", "li_ion", "heat"], src="tst-bsensor-shop")
    assert [x.severity for x in f] == ["danger", "danger", "info"]
    _, f = hz(["mains", "heat"], kind="module")
    assert [x.severity for x in f] == ["danger", "caution"] and "Breakout board" not in f[1].message


def test_hazard_groups_instances_and_no_hazard_no_check():
    _, f = hz(["heat"], n=3)
    assert len(f) == 1 and f[0].refs == ["U1", "U2", "U3"]
    rep, f = hz([])
    assert f == [] and k.check_of(rep, "mod.hazard") is None


# =====================================================================================================================
# honesty
# =====================================================================================================================
def test_breakout_at_5v_without_facts_is_caution_not_danger():
    m = gpio_mod(kind="module", vih=R(0.7, "VCC"),
                 supply={"min": F(1.7), "max": F(3.6), "abs_max": F(4.0)})
    rep = run([dig(vcc="5V")], extra=[m], assignments=DIG, only=MY_RULES)
    hard = [f for f in rep.findings if f.severity == "danger"]
    assert hard == [] and {w["severity"] for w in rep.warnings} <= {"caution", "info"}
    assert any(w["code"] == "mod_supply_range" and w["severity"] == "caution" for w in rep.warnings)
    rep = run([dig(vcc="5V", facts={"regulator": "none"})], extra=[m], assignments=DIG, only=MY_RULES)
    assert {(f.rule_id, f.severity) for f in rep.findings if f.severity == "danger"} == {
        ("mod.supply_range", "danger"), ("mod.level_out", "danger")}


def test_class_b_module_is_never_hard_without_user_parts():
    m = gpio_mod("ee_b", src="tst-bsensor-shop", vih=R(0.7, "VCC"), supply={"min": F(1.7), "max": F(3.6),
                 "abs_max": F(4.0)}, current={"supply": "VCC", "max": F(1.0, "A")},
                 requires=REQ, hazards=[{"code": "heat", "text": "Gets hot."}])
    rep = run([dig("ee_b", vcc="5V", conn={"INT": "GPIO7"})], extra=[m], assignments=[*DIG, k.assign("in", 7)],
              options={"rail_limits": {"5V": 0.1}}, only=MY_RULES)
    failed = [f for f in rep.findings if f.status == "failed"]
    assert failed and {f.severity for f in failed} == {"info"}
    assert all("Unverified" in f.message for f in failed)


def test_missing_esp_values_never_guess():
    m = gpio_mod(vih=R(0.7, "VCC"))
    rep = run([dig(vcc="5V")], extra=[m], assignments=DIG, only=("mod.level_in", "mod.level_out"), esp={})
    assert {(f.status, f.severity) for f in rep.findings} == {("not_checked", "info")}
    assert k.check_of(rep, "mod.level_in")["status"] == "not_checked"


def test_runtime_electrical_data_is_used():
    esp = electrical.get("esp32s3")
    assert (esp["voh"], esp["vih"], esp["v_in_max"]) == (2.64, 2.475, 3.6)
    m = gpio_mod(vih=F(2.64))
    rep = k.run(catalog=fx.catalog(m), electrical=None, assignments=DIG, parts=[dig()], only=("mod.level_in",))
    f = fs(rep, "mod.level_in")[0]
    assert f.status == "passed" and "elec-ds-esp32s3" in f.source_ids


def test_messages_fit_the_warning_limit():
    m = gpio_mod(kind="module", vih=R(0.7, "VCC"), v_in_max=F(3.0), current={"supply": "VCC", "max": F(1.0, "A")},
                 requires=REQ, hazards=[{"code": "li_ion", "text": "Contains a Li-ion cell."}],
                 supply={"min": F(1.7), "max": F(3.6), "abs_max": F(4.0)})
    rep = run([dig(vcc="5V", conn={"INT": "GPIO7"}), *pullups("5V")], extra=[m],
              assignments=[*BUS, *DIG, k.assign("in", 7)], options={"rail_limits": {"5V": 0.1}}, only=MY_RULES)
    assert rep.findings
    for f in rep.findings:
        assert len(f.message) <= modcheck.MAX_MESSAGE_CHARS, (f.rule_id, len(f.message), f.message)
    env = contracts.envelope("pins.check", "x", {}, checks=rep.checks, warnings=rep.warnings)
    assert contracts.validate_envelope(env) == []


# =====================================================================================================================
# pins.check with the real BME280 and the real ESP data
# =====================================================================================================================
BME = {"ref": "U1", "kind": "ic", "value": "BME280", "module": "bme280",
       "conn": {"SDI": "SDA0", "SCK": "SCL0", "SDO": "GND", "VDD": "3V3", "GND": "GND"}}
CAP = part("C1", "ceramic", "3V3", "GND", "100nF")


def _mod_warnings(env):
    return [w for w in env["warnings"] if w["code"] in MY_CODES]


def test_pins_check_real_bme280_correct_project():
    env = pins.check("esp32s3", BUS, parts=[BME, *pullups("3V3"), CAP], options={})
    assert env["ok"] and contracts.validate_envelope(env) == []
    assert _mod_warnings(env) == []
    checks = {c["id"]: c["status"] for c in env["checks"] if c["id"].startswith("modules.")}
    assert checks["modules.supply_range"] == checks["modules.level_in"] == checks["modules.level_out"] == "passed"
    assert checks["modules.required_parts"] == "passed" and checks["modules.power_budget"] == "not_checked"


def test_pins_check_real_bme280_problems():
    env = pins.check("esp32s3", BUS, parts=[BME, *pullups("5V"), CAP], options={})
    ws = {(w["code"], w["severity"]) for w in _mod_warnings(env)}
    assert ("mod_level_out", "danger") in ws and ("mod_level_in", "danger") in ws
    assert "elec-ds-esp32s3" in {s["id"] for s in env["sources"]}
    env = pins.check("esp32s3", BUS, parts=[BME], options={})
    ws = [(w["code"], w["severity"]) for w in _mod_warnings(env)]
    assert ws == [("mod_required_parts", "caution"), ("mod_required_parts", "caution")]  # pull-ups, decoupling
    env = pins.check("esp32s3", BUS, parts=[{**BME, "conn": {**BME["conn"], "VDD": "5V"}}, *pullups("3V3")],
                     options={})
    assert ("mod_supply_range", "danger") in {(w["code"], w["severity"]) for w in _mod_warnings(env)}


def test_pins_check_gy_breakout_alias_at_5v_is_caution():
    gy = {**BME, "kind": "module", "module": "gy-bme280", "conn": {**BME["conn"], "VDD": "5V"}}
    entry = modules.catalog().get("bme280")
    fake = fx.FakeCatalog([{**entry, "kind": "module", "aliases": ["gy-bme280"]}],
                          sources={"mod-env-bme280-ds": {"id": "mod-env-bme280-ds", "class": "A"}})
    rep = modcheck.run(chip="esp32s3", assignments=BUS, parts=[gy, CAP], catalog=fake, electrical=None, options={})
    hard = {(f.rule_id, f.severity) for f in rep.findings if f.status == "failed"}
    assert ("mod.supply_range", "caution") in hard and all(s != "danger" for _, s in hard)


# =====================================================================================================================
# false-alarm list: ten correct projects, no caution/danger and no failed check from these rules
# =====================================================================================================================
def _uart_mod():
    return {"id": "ee_uart", "title": "EE UART module", "category": "comm.radio", "manufacturer": "Test", "kind": "ic",
            "source_ids": ["tst-5v-ds"], "supplies": {"VCC": {"min": F(3.0), "max": F(3.6), "abs_max": F(4.0)}},
            "io": {"domain": "VCC", "vih": R(0.7, "VCC"), "vil": R(0.3, "VCC"), "voh": R(0.9, "VCC"),
                   "v_in_max": {"rel_offset": 0.3, "of": "VCC", "unit": "V", "page": 1, "evidence": "x"},
                   "outputs": "push_pull"},
            "pins": [{"name": "VCC", "signal": "supply"}, GND, {"name": "RXD", "signal": "uart_rx"},
                     {"name": "TXD", "signal": "uart_tx"}],
            "interfaces": [{"type": "uart"}],
            "current": {"supply": "VCC", "typ": F(0.02, "A"), "max": F(0.12, "A"), "peak": F(0.25, "A")},
            "requires": [{"code": "bulk_cap", "kind": "electrolytic", "value": "10uF", "pins": ["VCC"], "to": "GND",
                          "page": 2, "evidence": "x"}]}


def _ttl_mod():  # 5 V part with TTL inputs (VIH 2.0 V fixed): driven from 3.3 V without a shifter
    return gpio_mod("ee_ttl", vih=F(2.0), vil=F(0.8), v_in_max=F(5.5), domain="VCC",
                    supply={"min": F(4.5), "max": F(5.5), "abs_max": F(7.0)},
                    current={"supply": "VCC", "max": F(0.01, "A")})


def _req_ok():
    return [part("R5", "resistor", "GPIO7", "3V3"), part("C1", "ceramic", "3V3", "GND")]


FX_SENSOR = {**I2C, "VDD": "3V3", "SDO": "GND"}
GOOD = {
    "real_bme280_pullups_cap": dict(real=True, parts=[BME, *pullups("3V3"), CAP]),
    "real_bme280_0x77_with_limit": dict(real=True, parts=[{**BME, "conn": {**BME["conn"], "SDO": "3V3"}},
                                                          *pullups("3V3"), CAP],
                                        options={"rail_limits": {"3V3": 0.5}}),
    "real_bme280_devkit_limit": dict(real=True, parts=[BME, *pullups("3V3"), CAP], devkit="esp32-s3-devkitc-1"),
    "sensor_and_oled_on_one_bus": dict(parts=[k.mod("U1", "tst_sensor", FX_SENSOR), k.mod("U2", "tst_oled",
                                              {**I2C, "VDD": "3V3"}), *pullups("3V3")],
                                       options={"rail_limits": {"3V3": 0.3}}),
    "breakout_at_3v3_no_facts": dict(parts=[k.mod("U1", "tst_breakout", {**I2C, "VIN": "3V3", "ADR": "GND"})]),
    "mux_at_3v3_with_pullups": dict(parts=[k.mod("U1", "tst_mux", {**I2C, "VCC": "3V3"}), *pullups("3V3")]),
    "ttl_part_at_5v_driven_by_esp": dict(parts=[k.mod("U1", "ee_ttl", {"VCC": "5V", "DIN": "GPIO4"})],
                                         extra=[_ttl_mod()], assignments=DIG, options={"rail_limits": {"5V": 0.5}}),
    "requirements_met_by_parts": dict(parts=[k.mod("U1", "ee_req", {"VCC": "3V3", "INT": "GPIO7", "DIN": "GPIO4",
                                                                     "DOUT": "GPIO5"}), *_req_ok()],
                                      extra=[req_mod(vih=R(0.7, "VCC"), voh=R(0.9, "VCC"))],
                                      assignments=[*DIG, k.assign("in", 7, "INT")]),
    "uart_module_with_bulk_cap_and_limit": dict(
        parts=[k.mod("U1", "ee_uart", {"VCC": "3V3", "RXD": "GPIO17", "TXD": "GPIO18"}),
               part("C2", "electrolytic", "3V3", "GND", "10uF")], extra=[_uart_mod()],
        assignments=[k.assign("uart_tx", 17, "TX"), k.assign("uart_rx", 18, "RX")],
        options={"rail_limits": {"3V3": 0.5}}),
    "imu_and_sensor_0x77_with_pullups": dict(parts=[k.mod("U1", "tst_imu", {**I2C, "VDD": "3V3"}),
                                                    k.mod("U2", "tst_sensor", {**FX_SENSOR, "SDO": "3V3"}),
                                                    *pullups("3V3")]),
}


@pytest.mark.parametrize("name", sorted(GOOD))
def test_false_alarm_list(name):
    p = dict(GOOD[name])
    if p.pop("real", False):
        rep = modcheck.run(chip="esp32s3", assignments=BUS, parts=p["parts"], options=p.get("options"),
                           devkit=p.get("devkit"))
    else:
        rep = run(p["parts"], extra=p.get("extra", ()), assignments=p.get("assignments"), options=p.get("options"))
    mine = [f for f in rep.findings if f.rule_id in MY_RULES]
    assert mine, name
    bad = [f for f in mine if f.status == "failed" or (f.severity in ("caution", "danger"))]
    assert bad == [], [(f.rule_id, f.severity, f.message) for f in bad]
    assert [w for w in rep.warnings if w["code"] in MY_CODES] == [], name
    assert all(c["status"] != "failed" for c in rep.checks if c["id"] in {modcheck.check_id(r) for r in MY_RULES})


def test_false_alarm_list_has_ten_projects():
    assert len(GOOD) == 10
