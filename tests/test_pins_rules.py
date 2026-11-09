"""pins.check / pins.suggest / pins.info (mandatory tests)."""
import json

import pytest

from circuit_bench.bench_core import pins
from circuit_bench.bench_core.contracts import MAX_RESULT_BYTES, MODES, validate_envelope

DEVKIT = "esp32-s3-devkitc-1"
DEMO = [
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


# --- mandatory cases --------------------------------------------------------------------------------------------------
def test_s3_n16r8_gpio35_in_pullup_blocked_by_octal_psram_with_source():
    res, p = one("esp32s3", 35, "in_pullup", variant="n16r8", wifi=True, devkit=DEVKIT)
    assert p["verdict"] == "blocked"
    reason = next(r for r in p["reasons"] if r["rule_id"] == "s3.octal_psram")
    assert reason["severity"] == "blocked" and reason["source_id"] == "idf-v6.1-gpio-esp32s3"
    src = {s["id"]: s for s in res["sources"]}["idf-v6.1-gpio-esp32s3"]
    assert src["url"].startswith("https://") and src["retrieved"]
    assert status(res, "pins.octal_psram") == "failed"
    assert p["header"] == "J3-13" and "SPIIO6" in p["functions"]


def test_s3_n8_gpio35_ok():
    res, p = one("esp32s3", 35, "in_pullup", variant="n8", devkit=DEVKIT)
    assert p["verdict"] == "ok" and p["reasons"] == []
    assert status(res, "pins.octal_psram") == "passed"


def test_s3_gpio14_out_ok_and_gpio0_caution():
    _, p14 = one("esp32s3", 14, "out", variant="n16r8", devkit=DEVKIT)
    assert p14["verdict"] == "ok" and p14["header"] == "J1-20"
    res, p0 = one("esp32s3", 0, "out", variant="n16r8", devkit=DEVKIT)
    assert p0["verdict"] == "caution" and ids(p0) == ["s3.strapping"]
    assert status(res, "pins.strapping") == "failed"


def test_esp32_gpio34_out_blocked():
    _, p = one("esp32", 34, "out")
    assert p["verdict"] == "blocked" and "esp32.input_only" in ids(p)


def test_esp32_gpio25_adc_with_wifi_blocked_and_suggests_32_33():
    res, p = one("esp32", 25, "adc", wifi=True)
    assert p["verdict"] == "blocked" and ids(p) == ["esp32.adc2_wifi"]
    assert p["alternatives"][:2] == [32, 33]
    assert status(res, "pins.adc2_wifi") == "failed"
    sug = ok_env(pins.suggest("esp32", [{"role": "SENSE", "mode": "adc", "pin": 25}], variant=None, wifi=True, devkit=None))
    assert [s["gpio"] for s in sug["result"]["requests"][0]["suggestions"]][:2] == [32, 33]
    _, p_off = one("esp32", 25, "adc", wifi=False)
    assert p_off["verdict"] == "ok"


def test_esp32_gpio14_caution_jtag():
    _, p = one("esp32", 14, "out")
    assert p["verdict"] == "caution" and ids(p) == ["esp32.jtag"]


def test_c3_gpio9_caution():
    _, p = one("esp32c3", 9, "in")
    assert p["verdict"] == "caution" and ids(p) == ["c3.strapping"]


def test_duplicate_pin_failed():
    res = ok_env(pins.check("esp32s3", [{"role": "A", "mode": "out", "pin": 4}, {"role": "B", "mode": "in", "pin": 4}],
                            variant="n8"))
    assert status(res, "pins.duplicates") == "failed"
    for p in res["result"]["pins"]:
        assert p["verdict"] == "blocked" and "duplicate_pin" in ids(p)


def test_s3_gpio26_not_broken_out_on_devkit():
    res, p = one("esp32s3", 26, "out", variant="n8", devkit=DEVKIT)
    assert p["verdict"] == "blocked" and "not_broken_out" in ids(p)
    assert p["header"] is None
    assert status(res, "pins.broken_out") == "failed"
    reason = next(r for r in p["reasons"] if r["rule_id"] == "not_broken_out")
    assert reason["source_id"] == "devkitc1-s3-v1.1"


def test_suggest_is_deterministic():
    args = ("esp32s3", [{"role": "BUTTON", "mode": "in_pullup", "pin": 35}, {"role": "LED", "mode": "pwm"}])
    kw = {"variant": "n16r8", "wifi": True, "devkit": DEVKIT, "taken": (1, 8, 9, 14)}
    a, b = pins.suggest(*args, **kw), pins.suggest(*args, **kw)
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)
    ok_env(a)


def test_demo_case_konzept_9():
    """S3 N16R8 on DevKitC-1, Wi-Fi on, taken {1, 8, 9, 14}: BUTTON in_pullup on GPIO35 -> blocked, suggestions [2, 4, 5]."""
    res = ok_env(pins.check("esp32s3", DEMO, variant="n16r8", wifi=True, devkit=DEVKIT))
    r = res["result"]
    assert r["counts"] == {"ok": 4, "caution": 0, "blocked": 1}
    btn = next(p for p in r["pins"] if p["role"] == "BUTTON")
    assert btn["verdict"] == "blocked" and ids(btn) == ["s3.octal_psram"]
    assert btn["alternatives"] == [2, 4, 5]
    assert res["summary"] == "ESP32-S3 N16R8, Wi-Fi on: 4 ok, 0 caution, 1 blocked (GPIO35: octal PSRAM)."
    assert [(p["role"], p["pin"], p["verdict"]) for p in r["pins"]] == [
        ("LASER", 14, "ok"), ("BUTTON", 35, "blocked"), ("SDA", 8, "ok"), ("SCL", 9, "ok"), ("VBAT", 1, "ok")]
    assert btn["rule_ids"] == ["s3.octal_psram"] and btn["header"] == "J3-13"
    assert status(res, "pins.octal_psram") == "failed" and status(res, "pins.duplicates") == "passed"
    assert status(res, "pins.adc2_wifi") == "passed"  # VBAT is on ADC1
    assert len(json.dumps(res)) <= MAX_RESULT_BYTES

    sug = ok_env(pins.suggest("esp32s3", [{"role": "BUTTON", "mode": "in_pullup", "pin": 35}], variant="n16r8",
                              wifi=True, devkit=DEVKIT, taken=[1, 8, 9, 14]))
    req = sug["result"]["requests"][0]
    assert [s["gpio"] for s in req["suggestions"]] == [2, 4, 5]
    assert [s["header"] for s in req["suggestions"]] == ["J3-5", "J1-4", "J1-5"]
    excluded = {e["gpio"]: e["why"] for e in req["excluded"]}
    assert excluded[1] == "taken" and "strapping" in excluded[3] and "caution" in excluded[3]
    assert sug["summary"] == "Free pins for BUTTON (in_pullup) instead of GPIO35: GPIO2, GPIO4, GPIO5."


def test_variant_unknown_gpio35_is_caution_not_checked():
    res, p = one("esp32s3", 35, "in_pullup", variant=None, devkit=DEVKIT)
    assert p["verdict"] == "caution"
    reason = next(r for r in p["reasons"] if r["rule_id"] == "s3.octal_psram")
    assert reason["severity"] == "caution" and "module variant unknown" in reason["message"].lower()
    assert status(res, "pins.octal_psram") == "not_checked"
    assert any(w["code"] == "variant_unknown" for w in res["warnings"])
    sug = ok_env(pins.suggest("esp32s3", [{"role": "B", "mode": "in", "pin": 0}], variant=None, wifi=False, devkit=None))
    assert not {33, 34, 35, 36, 37} & {s["gpio"] for s in sug["result"]["requests"][0]["suggestions"]}


# --- ESP32 module variants (GPIO16/17), C3 UART0 ----------------------------------------------------------------------
@pytest.mark.parametrize("gpio", [16, 17])
def test_esp32_gpio16_17_depend_on_the_module_variant(gpio):
    """WROOM-32E: free; WROVER-E (PSRAM): blocked by esp32.psram_16_17; variant unknown: caution, not_checked."""
    dk = "esp32-devkitc-v4"
    res, p = one("esp32", gpio, "out", variant="wroom-32e", devkit=dk)
    assert p["verdict"] == "ok" and p["reasons"] == [] and p["header"] == f"J3-{28 - gpio}"
    assert status(res, "pins.psram_16_17") == "passed" and status(res, "pins.spi_flash") == "passed"
    assert res["summary"].startswith("ESP32 WROOM-32E, Wi-Fi off: 1 ok")
    assert not any(w["code"] == "variant_unknown" for w in res["warnings"])

    res, p = one("esp32", gpio, "out", variant="wrover-e", devkit=dk)
    assert p["verdict"] == "blocked" and ids(p) == ["esp32.psram_16_17"]
    reason = p["reasons"][0]
    assert reason["severity"] == "blocked" and reason["source_id"] == "devkitc-esp32-v4"
    assert "ESP32-WROVER" in reason["message"] and "ESP32-WROOM" in reason["message"] and "usually" in reason["message"]
    assert status(res, "pins.psram_16_17") == "failed"
    assert "devkitc-esp32-v4" in {s["id"] for s in res["sources"]}
    assert p["alternatives"] == [4, 18, 19]

    res, p = one("esp32", gpio, "out", variant=None, devkit=dk)
    assert p["verdict"] == "caution" and ids(p) == ["esp32.psram_16_17"]
    assert "module variant unknown" in p["reasons"][0]["message"].lower()
    assert "If the condition holds (a module with PSRAM, e.g. ESP32-WROVER)" in p["reasons"][0]["message"]
    assert status(res, "pins.psram_16_17") == "not_checked"
    assert any(w["code"] == "variant_unknown" and "WROVER-E, WROOM-32E" in w["message"] for w in res["warnings"])
    assert res["summary"].startswith("ESP32 (module variant unknown), Wi-Fi off: 0 ok, 1 caution")


def test_esp32_gpio6_11_stay_blocked_on_every_module():
    for variant in (None, "wroom-32e", "wrover-e"):
        for gpio in range(6, 12):
            _, p = one("esp32", gpio, "in", variant=variant)
            assert p["verdict"] == "blocked" and ids(p) == ["esp32.spi_flash"], (variant, gpio)


def test_esp32_suggest_offers_gpio16_17_only_on_wroom():
    req = [{"role": "LED", "mode": "out"}]
    got = {v: [s["gpio"] for s in ok_env(pins.suggest("esp32", req, variant=v, wifi=True, devkit="esp32-devkitc-v4"))
                ["result"]["requests"][0]["suggestions"]] for v in (None, "wroom-32e", "wrover-e")}
    assert got == {None: [4, 18, 19], "wroom-32e": [4, 16, 17], "wrover-e": [4, 18, 19]}


def test_esp32_info_gpio16_applies_per_variant():
    for variant, applies, mode in (("wroom-32e", False, "ok"), ("wrover-e", True, "blocked"), (None, None, "caution")):
        res = ok_env(pins.info("esp32", 16, variant=variant, devkit="esp32-devkitc-v4"))
        rule = next(x for x in res["result"]["rules"] if x["rule_id"] == "esp32.psram_16_17")
        assert rule["applies"] is applies and rule["when"] == {"psram": "spi"}, variant
        assert res["result"]["modes"]["out"] == mode, variant
        assert not any(x["rule_id"] == "esp32.spi_flash" for x in res["result"]["rules"])
    assert "blocked: WROVER PSRAM (WROVER-E)" in ok_env(pins.info("esp32", 17, variant="wrover-e"))["summary"]


@pytest.mark.parametrize(("gpio", "name"), [(21, "U0TXD"), (20, "U0RXD")])
def test_c3_uart0_is_caution_with_the_devkit_source(gpio, name):
    res, p = one("esp32c3", gpio, "out", devkit="esp32-c3-devkitm-1")
    assert p["verdict"] == "caution" and ids(p) == ["c3.uart0"]
    reason = p["reasons"][0]
    assert reason["source_id"] == "devkitm1-c3-v1" and f"{name} (GPIO{gpio})" in reason["message"]
    assert "USB-to-UART bridge" in reason["message"]
    assert status(res, "pins.uart0") == "failed"
    assert p["header"] == {21: "J3-2", 20: "J3-3"}[gpio]


# --- further behaviour ------------------------------------------------------------------------------------------------
def test_esp32_input_only_pins_have_no_pulls():
    _, p = one("esp32", 34, "in_pullup")
    assert p["verdict"] == "blocked" and ids(p) == ["esp32.no_pulls"]
    _, p_in = one("esp32", 34, "in")
    assert p_in["verdict"] == "ok"


def test_esp32_gpio36_interrupt_hint_is_info_only():
    _, p = one("esp32", 36, "in")
    assert p["verdict"] == "ok" and ids(p) == ["esp32.gpio36_39_irq"]
    assert p["reasons"][0]["severity"] == "info"


def test_s3_rgb_led_on_devkit_is_caution():
    res, p = one("esp32s3", 38, "out", variant="n8", devkit=DEVKIT)
    assert p["verdict"] == "caution" and ids(p) == ["onboard"] and "RGB LED" in p["reasons"][0]["message"]
    assert status(res, "pins.board") == "failed"
    _, bare = one("esp32s3", 38, "out", variant="n8")
    assert bare["verdict"] == "ok" and bare["header"] is None


def test_s3_uart0_and_usb_jtag_caution_pad_jtag_info():
    for gpio, rule in ((43, "s3.uart0"), (44, "s3.uart0"), (19, "s3.usb_jtag"), (20, "s3.usb_jtag")):
        _, p = one("esp32s3", gpio, "out", variant="n8", devkit=DEVKIT)
        assert p["verdict"] == "caution" and ids(p) == [rule], gpio
    _, p = one("esp32s3", 40, "out", variant="n8", devkit=DEVKIT)
    assert p["verdict"] == "ok" and ids(p) == ["s3.pad_jtag"]
    assert "only if pad JTAG is used" in p["reasons"][0]["message"]


def test_s3_adc2_with_wifi_is_info_unverified_and_not_checked():
    res, p = one("esp32s3", 11, "adc", variant="n8", wifi=True)
    assert p["verdict"] == "ok" and ids(p) == ["s3.adc2_wifi"]
    assert p["reasons"][0]["severity"] == "info" and "unverified" in p["reasons"][0]["message"]
    assert status(res, "pins.adc2_wifi") == "not_checked"
    res_off, p_off = one("esp32s3", 11, "adc", variant="n8", wifi=False)
    assert p_off["reasons"] == [] and status(res_off, "pins.adc2_wifi") == "passed"


def test_mode_capabilities_adc_and_touch():
    _, p = one("esp32s3", 21, "adc", variant="n8")
    assert p["verdict"] == "blocked" and ids(p) == ["no_adc"]
    _, t = one("esp32s3", 4, "touch", variant="n8")
    assert t["verdict"] == "ok"
    res, c3 = one("esp32c3", 4, "touch")
    assert c3["verdict"] == "blocked" and ids(c3) == ["no_touch"] and status(res, "pins.modes") == "failed"
    _, c3adc = one("esp32c3", 5, "adc")
    assert c3adc["verdict"] == "caution" and ids(c3adc) == ["c3.adc2"]


def test_unknown_pin_is_blocked_finding():
    res, p = one("esp32c3", 22, "out")
    assert p["verdict"] == "blocked" and ids(p) == ["unknown_pin"]
    assert status(res, "pins.exists") == "failed"


def test_pin_spellings_and_chip_aliases():
    for pin in (35, "35", "GPIO35", "io35"):
        _, p = one("ESP32-S3", pin, "in", variant="N16R8")
        assert p["pin"] == 35 and p["verdict"] == "blocked"


def test_suggest_out_skips_strapping_and_ascends():
    res = ok_env(pins.suggest("esp32", [{"role": "LED", "mode": "out"}], variant=None, wifi=False, devkit=None))
    got = [s["gpio"] for s in res["result"]["requests"][0]["suggestions"]]
    assert got == sorted(got) and len(got) == 3
    assert not set(got) & {0, 2, 5, 12, 15}
    assert got == [4, 18, 19]


def test_suggest_adc_prefers_adc1():
    res = ok_env(pins.suggest("esp32s3", [{"role": "VBAT", "mode": "adc"}], variant="n8", wifi=False, devkit=DEVKIT,
                              taken=[1]))
    assert [s["gpio"] for s in res["result"]["requests"][0]["suggestions"]] == [2, 4, 5]
    c3 = ok_env(pins.suggest("esp32c3", [{"mode": "adc"}], variant=None, wifi=True, devkit=None))
    assert [s["gpio"] for s in c3["result"]["requests"][0]["suggestions"]] == [0, 1, 3]


def test_info_gpio35():
    res = ok_env(pins.info("esp32s3", 35, variant="n16r8", devkit=DEVKIT))
    r = res["result"]
    assert r["gpio"] == 35 and r["header"] == "J3-13" and r["broken_out"] is True
    assert {"SPIIO6", "FSPID", "SUBSPID"} <= set(r["functions"])
    assert r["adc"] is None and r["input_only"] is False and r["internal_pulls"] is True
    rule = next(x for x in r["rules"] if x["rule_id"] == "s3.octal_psram")
    assert rule["applies"] is True and rule["when"] == {"psram": "octal"} and rule["severity"] == "blocked"
    assert r["modes"]["in_pullup"] == "blocked"
    assert "GPIO35" in res["summary"] and "octal PSRAM" in res["summary"]
    assert any(s["id"] == "idf-v6.1-gpio-esp32s3" for s in res["sources"])
    n8 = ok_env(pins.info("esp32s3", 35, variant="n8", devkit=None))
    assert next(x for x in n8["result"]["rules"] if x["rule_id"] == "s3.octal_psram")["applies"] is False
    assert n8["result"]["modes"]["in_pullup"] == "ok"


def test_info_esp32_adc_and_touch():
    r = ok_env(pins.info("esp32", 4, variant=None, devkit=None))["result"]
    assert r["adc"] == {"unit": 2, "channel": 0} and r["touch"] == 0 and r["rtc"] is True
    assert next(x for x in r["rules"] if x["rule_id"] == "esp32.adc2_wifi")["applies"] is None  # depends on Wi-Fi
    assert r["modes"]["adc"] == "caution"


@pytest.mark.parametrize("call, code", [
    (lambda: pins.check("esp32h2", [{"mode": "out", "pin": 1}]), "unknown_chip"),
    (lambda: pins.check("esp32s3", [{"mode": "blink", "pin": 1}]), "invalid_args"),
    (lambda: pins.check("esp32s3", [{"mode": "out", "pin": 1}], variant="n4r9"), "invalid_args"),
    (lambda: pins.check("esp32", [{"mode": "out", "pin": 1}], variant="n8"), "invalid_args"),
    (lambda: pins.check("esp32", [{"mode": "out", "pin": 1}], devkit=DEVKIT), "invalid_args"),
    (lambda: pins.check("esp32s3", [{"mode": "out", "pin": 1}], devkit="nope"), "unknown_board"),
    (lambda: pins.check("esp32s3", [{"mode": "out", "pin": 1, "role": "bad role"}]), "invalid_args"),
    (lambda: pins.check("esp32s3", []), "invalid_args"),
    (lambda: pins.check("esp32s3", None), "invalid_args"),
    (lambda: pins.check("esp32s3", [{"mode": "out", "pin": True}]), "invalid_args"),
    (lambda: pins.check("esp32s3", [{"mode": "out", "pin": "GPIOx"}]), "invalid_args"),
    (lambda: pins.check("esp32s3", [{"mode": "out", "pin": 1}], wifi="yes"), "invalid_args"),
    (lambda: pins.check(None, [{"mode": "out", "pin": 1}]), "unknown_chip"),
    (lambda: pins.suggest("esp32s3", [{"mode": "out"}], variant=None, wifi=False, devkit=None, taken=["x"]), "invalid_args"),
    (lambda: pins.suggest("esp32s3", "out", variant=None, wifi=False, devkit=None), "invalid_args"),
    (lambda: pins.info("esp32s3", 22, variant=None, devkit=None), "unknown_pin"),
    (lambda: pins.info("esp32s3", "abc", variant=None, devkit=None), "invalid_args"),
])
def test_errors_are_envelopes_never_exceptions(call, code):
    res = call()
    assert validate_envelope(res) == [], res
    assert res["ok"] is False and res["error"]["code"] == code, res


def test_every_mode_checks_on_every_pin_without_crash():
    for chip in pins.chips():
        data = pins.load(chip)
        variant = data["variants"][0]["id"] if data["variants"] else None
        assignments = [{"role": f"P{g['num']}", "mode": MODES[i % len(MODES)], "pin": g["num"]}
                       for i, g in enumerate(data["gpios"])]
        res = ok_env(pins.check(chip, assignments, variant=variant, wifi=True))
        assert len(res["result"]["pins"]) == len(data["gpios"])
        assert sum(res["result"]["counts"].values()) == len(data["gpios"])
