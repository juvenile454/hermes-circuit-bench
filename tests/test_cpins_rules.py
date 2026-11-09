"""pins.check / pins.suggest / pins.info on the ESP32-S2 and ESP32-C6 data and the S3 module variants
(mandatory tests). No corpus needed."""
import pytest

from circuit_bench.bench_core import pins
from circuit_bench.bench_core.contracts import MODES, validate_envelope

S3_DEVKIT = "esp32-s3-devkitc-1"
S3_DEMO = [
    {"role": "LASER", "mode": "out", "pin": 14, "net": "LASER_EN"},
    {"role": "BUTTON", "mode": "in_pullup", "pin": 35, "net": "BTN"},
    {"role": "SDA", "mode": "i2c_sda", "pin": 8, "net": "I2C_SDA"},
    {"role": "SCL", "mode": "i2c_scl", "pin": 9, "net": "I2C_SCL"},
    {"role": "VBAT", "mode": "adc", "pin": 1, "net": "VBAT_DIV"},
]


def ok_env(res):
    assert validate_envelope(res) == [], res
    assert res["ok"] is True, res
    return res


def one(chip, pin, mode="out", **kw):
    res = ok_env(pins.check(chip, [{"role": "X", "mode": mode, "pin": pin}], **kw))
    return res, res["result"]["pins"][0]


def ids(entry):
    return [r["rule_id"] for r in entry["reasons"]]


def status(res, check_id):
    return next(c["status"] for c in res["checks"] if c["id"] == check_id)


def suggestions(chip, mode, **kw):
    res = ok_env(pins.suggest(chip, [{"role": "X", "mode": mode}], **kw))
    return [s["gpio"] for s in res["result"]["requests"][0]["suggestions"]], res


# --- ESP32-S2 ----------------------------------------------------------------------------------------------------------
def test_s2_gpio46_out_blocked_by_input_only_and_in_not_blocked():
    _, p = one("esp32s2", 46, "out")
    assert p["verdict"] == "blocked" and ids(p) == ["s2.strapping", "s2.input_only"]
    assert next(r for r in p["reasons"] if r["rule_id"] == "s2.input_only")["source_id"] == "idf-v6.1-gpio-esp32s2"
    # GPIO46 is also a strapping pin (s2.strapping, modes *): `in` is therefore caution, never blocked
    _, p = one("esp32s2", 46, "in")
    assert p["verdict"] == "caution" and ids(p) == ["s2.strapping"]


@pytest.mark.parametrize("mode", ["pwm", "uart_tx", "spi_mosi", "spi_sck", "spi_cs", "in_pullup"])
def test_s2_gpio46_rule_modes_blocked_by_the_rule(mode):
    _, p = one("esp32s2", 46, mode)
    # the data rule names the fixed pull-down; the engine adds no generic no_output/no_pulls on top of it
    assert p["verdict"] == "blocked" and ids(p) == ["s2.strapping", "s2.input_only"]


@pytest.mark.parametrize("mode, generic", [("i2c_sda", "no_output"), ("i2c_scl", "no_output"),
                                           ("in_pulldown", "no_pulls")])
def test_s2_gpio46_other_modes_blocked_by_the_engine_flags(mode, generic):
    _, p = one("esp32s2", 46, mode)  # s2.input_only names the fixed pull-down as the reason
    assert p["verdict"] == "blocked" and ids(p) == ["s2.strapping", "s2.input_only"]  # replaces the generic reason
    assert generic in ("no_output", "no_pulls")


@pytest.mark.parametrize("mode", ["uart_rx", "spi_miso", "adc", "touch"])
def test_s2_gpio46_input_modes_not_blocked_by_input_only(mode):
    _, p = one("esp32s2", 46, mode)
    assert "s2.input_only" not in ids(p)


@pytest.mark.parametrize("pin, verdict, rule", [
    (45, "caution", "s2.strapping"),
    (0, "caution", "s2.strapping"),
    (26, "blocked", "s2.spi_flash"),
    (32, "blocked", "s2.spi_flash"),
    (19, "caution", "s2.usb_otg"),
    (20, "caution", "s2.usb_otg"),
    (43, "caution", "s2.uart0"),
    (44, "caution", "s2.uart0"),
    (40, "caution", "s2.jtag"),
    (39, "caution", "s2.jtag"),
])
def test_s2_rule_verdicts(pin, verdict, rule):
    _, p = one("esp32s2", pin, "out")
    assert p["verdict"] == verdict and ids(p) == [rule]


def test_s2_pins_without_rules_are_ok():
    for pin in (1, 14, 21, 33, 38):
        _, p = one("esp32s2", pin, "out")
        assert p["verdict"] == "ok" and p["reasons"] == [], pin


def test_s2_gpio21_adc_blocked_no_adc():
    _, p = one("esp32s2", 21, "adc")
    assert p["verdict"] == "blocked" and ids(p) == ["no_adc"]


def test_s2_gpio11_adc_with_wifi_is_info_only():
    res, p = one("esp32s2", 11, "adc", wifi=True)
    assert p["verdict"] == "ok" and ids(p) == ["s2.adc2_wifi"]
    assert p["reasons"][0]["severity"] == "info" and p["reasons"][0]["source_id"] == "idf-v6.1-adc-oneshot"
    assert status(res, "pins.adc2_wifi") == "not_checked"  # unverified rule: never claimed as passed
    _, p = one("esp32s2", 11, "adc", wifi=False)
    assert p["verdict"] == "ok" and p["reasons"] == []


def test_s2_gpio1_touch_ok():
    _, p = one("esp32s2", 1, "touch")
    assert p["verdict"] == "ok" and p["reasons"] == [] and "TOUCH1" in p["functions"]
    _, p = one("esp32s2", 21, "touch")
    assert p["verdict"] == "blocked" and ids(p) == ["no_touch"]


def test_s2_has_no_variants():
    res, _ = one("esp32s2", 1)
    assert res["warnings"] == [] and res["result"]["variant"] is None
    bad = pins.check("esp32s2", [{"mode": "out", "pin": 1}], variant="n8r2")
    assert bad["ok"] is False and bad["error"]["code"] == "invalid_args"


def test_s2_unknown_pins():
    for pin in (22, 25, 47):
        _, p = one("esp32s2", pin)
        assert p["verdict"] == "blocked" and ids(p) == ["unknown_pin"], pin


def test_s2_suggest_deterministic_with_expected_values():
    # out, GPIO1-21 taken: GPIO0 is strapping (out prefers none), GPIO22-25 do not exist, GPIO26-32 are SPI0/1
    # (s2.spi_flash, blocked); GPIO33-35 have no rule -> exactly [33, 34, 35]
    taken = list(range(1, 22))
    a, res_a = suggestions("esp32s2", "out", taken=taken)
    b, res_b = suggestions("esp32s2", "out", taken=taken)
    assert a == b == [33, 34, 35] and res_a == res_b
    excluded = {e["gpio"]: e["why"] for e in res_a["result"]["requests"][0]["excluded"]}
    assert "strapping" in excluded[0] and "SPI flash/PSRAM (blocked)" == excluded[26]
    # adc prefers ADC1 (GPIO1-10): with Wi-Fi on the first three ADC1 pins
    assert suggestions("esp32s2", "adc", wifi=True)[0] == [1, 2, 3]
    # in_pullup with everything below 45 taken: GPIO45 strapping (caution), GPIO46 blocked -> nothing left
    got, res = suggestions("esp32s2", "in_pullup", taken=[n for n in range(45)])
    assert got == [] and [w["code"] for w in res["warnings"]] == ["no_suggestion"]


def test_s2_info_gpio46():
    res = ok_env(pins.info("esp32s2", 46))
    r = res["result"]
    assert r["input_only"] is True and r["internal_pulls"] is False
    assert [x["rule_id"] for x in r["rules"]] == ["s2.strapping", "s2.input_only"]
    assert r["modes"]["in"] == "caution" and r["modes"]["out"] == "blocked" and r["modes"]["in_pullup"] == "blocked"


# --- ESP32-C6 ----------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("pin, verdict, rule", [
    (9, "caution", "c6.strapping"),
    (4, "caution", "c6.strapping"),
    (15, "caution", "c6.strapping"),
    (24, "blocked", "c6.spi_flash"),
    (30, "blocked", "c6.spi_flash"),
    (12, "caution", "c6.usb_jtag"),
    (13, "caution", "c6.usb_jtag"),
    (16, "caution", "c6.uart0"),
    (17, "caution", "c6.uart0"),
])
@pytest.mark.parametrize("variant", ["wroom-1", "mini-1"])
def test_c6_rule_verdicts(pin, verdict, rule, variant):
    _, p = one("esp32c6", pin, "out", variant=variant)
    assert p["verdict"] == verdict and ids(p) == [rule]


def test_c6_adc_only_adc1_and_no_touch():
    _, p = one("esp32c6", 7, "adc", variant="wroom-1")
    assert p["verdict"] == "blocked" and ids(p) == ["no_adc"]
    _, p = one("esp32c6", 0, "adc", variant="wroom-1", wifi=True)
    assert p["verdict"] == "ok" and p["reasons"] == []
    for g in pins.load("esp32c6")["gpios"]:
        _, p = one("esp32c6", g["num"], "touch", variant="wroom-1")
        assert p["verdict"] == "blocked" and "no_touch" in ids(p), g["num"]
        assert next(r for r in p["reasons"] if r["rule_id"] == "no_touch")["message"] == "ESP32-C6 has no touch sensor."


def test_c6_variant_mini_1_gpio10_11_blocked():
    for pin in (10, 11):
        _, p = one("esp32c6", pin, "in", variant="mini-1")
        assert p["verdict"] == "blocked" and ids(p) == ["c6.sip_flash"]
        _, p = one("esp32c6", pin, "in", variant="wroom-1")
        assert p["verdict"] == "ok" and p["reasons"] == []
    _, p = one("esp32c6", 14, "in", variant="mini-1")
    assert p["verdict"] == "ok" and p["reasons"] == []


def test_c6_variant_wroom_1_gpio14_blocked():
    res, p = one("esp32c6", 14, "in", variant="wroom-1")
    assert p["verdict"] == "blocked" and ids(p) == ["c6.no_sip_flash"]
    assert status(res, "pins.no_sip_flash") == "failed" and status(res, "pins.sip_flash") == "passed"


def test_c6_variant_unknown_gpio14_caution_not_checked():
    res, p = one("esp32c6", 14, "in", variant=None)
    assert p["verdict"] == "caution" and ids(p) == ["c6.no_sip_flash"]
    assert "Module variant unknown" in p["reasons"][0]["message"]
    assert status(res, "pins.no_sip_flash") == "not_checked"
    assert [w["code"] for w in res["warnings"]] == ["variant_unknown"]
    _, p = one("esp32c6", 10, "in", variant=None)
    assert p["verdict"] == "caution" and ids(p) == ["c6.sip_flash"]


def test_c6_variant_ids():
    assert [v["id"] for v in pins.load("esp32c6")["variants"]] == ["mini-1", "wroom-1"]
    bad = pins.check("esp32c6", [{"mode": "out", "pin": 1}], variant="n8")
    assert bad["ok"] is False and bad["error"]["code"] == "invalid_args"


def test_c6_unknown_pin():
    _, p = one("esp32c6", 31, variant="wroom-1")
    assert p["verdict"] == "blocked" and ids(p) == ["unknown_pin"]


def test_c6_suggest_deterministic_with_expected_values():
    taken = list(range(10))
    # wroom-1: GPIO10/11 led out and without rule; 12/13 USB-JTAG (caution), 14 not led out (blocked),
    # 15 strapping, 16/17 UART0 (caution) -> [10, 11, 18]
    a, res_a = suggestions("esp32c6", "out", variant="wroom-1", taken=taken)
    b, res_b = suggestions("esp32c6", "out", variant="wroom-1", taken=taken)
    assert a == b == [10, 11, 18] and res_a == res_b
    # mini-1: GPIO10/11 not led out (blocked), 12/13 caution, 14 free -> [14, 18, 19]
    assert suggestions("esp32c6", "out", variant="mini-1", taken=taken)[0] == [14, 18, 19]
    # variant unknown: 10, 11 and 14 are caution (not checked) and left out -> [18, 19, 20]
    got, res = suggestions("esp32c6", "out", variant=None, taken=taken)
    assert got == [18, 19, 20] and status(res, "suggest.variant") == "not_checked"
    # adc: only ADC1 GPIO0-6; strapping only matters for out/pwm, but GPIO4/5 are caution -> [0, 1, 2]
    assert suggestions("esp32c6", "adc", variant="wroom-1", wifi=True)[0] == [0, 1, 2]
    assert suggestions("esp32c6", "adc", variant="wroom-1", taken=[0, 1, 2, 3])[0] == [6]


def test_c6_info_lp_gpio_and_variant_rules():
    r = ok_env(pins.info("esp32c6", 4, variant="wroom-1"))["result"]
    assert r["rtc"] is True and "LP_GPIO4" in r["functions"] and "MTMS" in r["functions"]
    r = ok_env(pins.info("esp32c6", 14, variant=None))["result"]
    assert [(x["rule_id"], x["applies"]) for x in r["rules"]] == [("c6.no_sip_flash", None)]
    r = ok_env(pins.info("esp32c6", 14, variant="mini-1"))["result"]
    assert [(x["rule_id"], x["applies"]) for x in r["rules"]] == [("c6.no_sip_flash", False)]
    assert r["modes"]["out"] == "ok"


# --- ESP32-S3 module variants ------------------------------------------------------------------------------------------
@pytest.mark.parametrize("variant", ["n4r8", "n8r8", "n16r8"])
def test_s3_octal_variants_block_gpio35(variant):
    _, p = one("esp32s3", 35, "in_pullup", variant=variant, devkit=S3_DEVKIT)
    assert p["verdict"] == "blocked" and ids(p) == ["s3.octal_psram"]


@pytest.mark.parametrize("variant", ["n4", "n8", "n16", "n4r2", "n8r2", "n16r2"])
def test_s3_quad_or_no_psram_variants_leave_gpio35_ok(variant):
    _, p = one("esp32s3", 35, "in_pullup", variant=variant, devkit=S3_DEVKIT)
    assert p["verdict"] == "ok" and p["reasons"] == []


def test_s3_demo_case_stays_2_4_5():
    res = ok_env(pins.check("esp32s3", S3_DEMO, variant="n16r8", wifi=True, devkit=S3_DEVKIT))
    btn = next(p for p in res["result"]["pins"] if p["role"] == "BUTTON")
    assert btn["verdict"] == "blocked" and btn["alternatives"] == [2, 4, 5]
    sug = ok_env(pins.suggest("esp32s3", [{"role": "BUTTON", "mode": "in_pullup", "pin": 35}], variant="n16r8",
                              wifi=True, devkit=S3_DEVKIT, taken=[1, 8, 9, 14]))
    assert [s["gpio"] for s in sug["result"]["requests"][0]["suggestions"]] == [2, 4, 5]


def test_s3_variant_unknown_lists_all_variants():
    res, p = one("esp32s3", 35, "in", variant=None)
    assert p["verdict"] == "caution"
    msg = res["warnings"][0]["message"]
    for label in ("N4", "N8", "N16", "N4R2", "N8R2", "N16R2", "N4R8", "N8R8", "N16R8"):
        assert label in msg


# --- all chips ---------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("chip", ["esp32s2", "esp32c6"])
def test_every_mode_on_every_pin_of_the_new_chips(chip):
    data = pins.load(chip)
    variants = [v["id"] for v in data["variants"]] or [None]
    for variant in variants + ([None] if data["variants"] else []):
        for mode in MODES:
            res = ok_env(pins.check(chip, [{"mode": mode, "pin": g["num"]} for g in data["gpios"][:16]],
                                    variant=variant, wifi=True))
            assert sum(res["result"]["counts"].values()) == min(16, len(data["gpios"]))
