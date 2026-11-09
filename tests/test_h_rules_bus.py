"""Pins: shared I²C/SPI bus instead of duplicate_pin and the DevKit module hint in variant_unknown (the verdict
stays unchanged)."""
import json

import pytest

from circuit_bench import tools
from circuit_bench.bench_core import pins
from circuit_bench.bench_core.contracts import validate_envelope

I2C_SRC, SPI_SRC = "nxp-um10204", "idf-v6.1-spi-master"
TWO_I2C = [
    {"role": "BME_SDA", "mode": "i2c_sda", "pin": 4, "net": "I2C_SDA"},
    {"role": "BME_SCL", "mode": "i2c_scl", "pin": 5, "net": "I2C_SCL"},
    {"role": "OLED_SDA", "mode": "i2c_sda", "pin": 4, "net": "I2C_SDA"},
    {"role": "OLED_SCL", "mode": "i2c_scl", "pin": 5, "net": "I2C_SCL"},
]


def _ok(res):
    assert validate_envelope(res) == [], res
    assert res["ok"] is True, res
    return res


def _check(items, **kw):
    return _ok(pins.check("esp32s3", items, variant=kw.pop("variant", "n16r8"), **kw))


def _status(res, cid):
    return next(c for c in res["checks"] if c["id"] == cid)


def _ids(entry):
    return [r["rule_id"] for r in entry["reasons"]]


# --- shared bus ----------------------------------------------------------------------------------------------------
def test_two_i2c_devices_share_gpio4_and_5():
    res = _check(TWO_I2C)
    for p in res["result"]["pins"]:
        assert p["verdict"] == "ok", p
        assert _ids(p) == ["shared_bus"]
        [r] = p["reasons"]
        assert r["severity"] == "info" and r["source_id"] == I2C_SRC
    assert I2C_SRC in [s["id"] for s in res["sources"]]
    dup = _status(res, "pins.duplicates")
    assert dup["status"] == "passed" and "GPIO4" in dup["detail"] and "GPIO5" in dup["detail"]
    assert res["result"]["counts"] == {"ok": 4, "caution": 0, "blocked": 0}


def test_shared_spi_bus_lines_cite_the_idf_docs():
    items = [{"role": f"{dev}_{line.upper()}", "mode": f"spi_{line}", "pin": pin, "net": f"SPI_{line.upper()}"}
             for dev in ("SD", "TFT") for line, pin in (("sck", 12), ("mosi", 11), ("miso", 13))]
    items += [{"role": "SD_CS", "mode": "spi_cs", "pin": 10, "net": "SD_CS"},
              {"role": "TFT_CS", "mode": "spi_cs", "pin": 9, "net": "TFT_CS"}]
    res = _check(items)
    for p in res["result"]["pins"]:
        assert p["verdict"] == "ok", p
        if p["mode"] != "spi_cs":
            assert [(r["rule_id"], r["source_id"]) for r in p["reasons"]] == [("shared_bus", SPI_SRC)]
    assert _status(res, "pins.duplicates")["status"] == "passed"
    assert SPI_SRC in [s["id"] for s in res["sources"]]


@pytest.mark.parametrize("nets", [(None, None), ("I2C_SDA", None), ("I2C_SDA", "SDA2"), ("", "")])
def test_same_bus_mode_without_matching_net_stays_blocked_with_hint(nets):
    items = [{"role": "A", "mode": "i2c_sda", "pin": 4}, {"role": "B", "mode": "i2c_sda", "pin": 4}]
    for it, net in zip(items, nets, strict=True):
        if net is not None:
            it["net"] = net
    res = _check(items)
    assert _status(res, "pins.duplicates")["status"] == "failed"
    for p in res["result"]["pins"]:
        assert p["verdict"] == "blocked" and "duplicate_pin" in _ids(p) and "shared_bus" not in _ids(p)
        dup = next(r for r in p["reasons"] if r["rule_id"] == "duplicate_pin")
        assert "give every device on a shared bus the same net" in dup["message"]


def test_spi_cs_twice_is_blocked():
    res = _check([{"role": "A", "mode": "spi_cs", "pin": 10, "net": "CS"}, {"role": "B", "mode": "spi_cs", "pin": 10,
                                                                           "net": "CS"}])
    assert all(p["verdict"] == "blocked" and "duplicate_pin" in _ids(p) for p in res["result"]["pins"])
    assert _status(res, "pins.duplicates")["status"] == "failed"


def test_sda_and_scl_on_one_pin_is_blocked():
    res = _check([{"role": "A", "mode": "i2c_sda", "pin": 4, "net": "BUS"}, {"role": "B", "mode": "i2c_scl", "pin": 4,
                                                                            "net": "BUS"}])
    for p in res["result"]["pins"]:
        assert p["verdict"] == "blocked" and "duplicate_pin" in _ids(p)
        dup = next(r for r in p["reasons"] if r["rule_id"] == "duplicate_pin")
        assert "same net" not in dup["message"]  # the hint fits only one bus line shared by several devices


def test_mixed_shared_and_plain_duplicate():
    res = _check([*TWO_I2C, {"role": "LED", "mode": "out", "pin": 6}, {"role": "BTN", "mode": "in", "pin": 6}])
    verdicts = {p["role"]: p["verdict"] for p in res["result"]["pins"]}
    assert verdicts == {"BME_SDA": "ok", "BME_SCL": "ok", "OLED_SDA": "ok", "OLED_SCL": "ok", "LED": "blocked",
                        "BTN": "blocked"}
    dup = _status(res, "pins.duplicates")
    assert dup["status"] == "failed" and "GPIO6" in dup["detail"]


def test_shared_bus_keeps_the_pin_rules():
    # GPIO35 on an N16R8 is octal PSRAM: sharing the bus there does not hide the blocked rule
    res = _check([{"role": "A", "mode": "i2c_sda", "pin": 35, "net": "SDA"}, {"role": "B", "mode": "i2c_sda", "pin": 35,
                                                                             "net": "SDA"}])
    for p in res["result"]["pins"]:
        assert p["verdict"] == "blocked" and "shared_bus" in _ids(p) and "duplicate_pin" not in _ids(p)


def test_bad_net_type_is_invalid_args():
    res = pins.check("esp32s3", [{"role": "A", "mode": "i2c_sda", "pin": 4, "net": 5}], variant="n16r8")
    assert res["ok"] is False and res["error"]["code"] == "invalid_args"


def test_plain_duplicate_is_unchanged():
    # same as tests/test_pins_rules.py::test_duplicate_pin_failed (modes out/in, no bus); a net changes nothing
    res = _check([{"role": "A", "mode": "out", "pin": 4, "net": "N"}, {"role": "B", "mode": "in", "pin": 4, "net": "N"}],
                 variant="n8")
    assert _status(res, "pins.duplicates")["status"] == "failed"
    assert all(p["verdict"] == "blocked" and "duplicate_pin" in _ids(p) for p in res["result"]["pins"])


def test_tool_check_with_bus_assignments():
    handlers = tools.make_handlers(tools.Host(hook_active=True))
    env = json.loads(handlers["bench_pins"]({"action": "check", "chip": "esp32s3", "variant": "n16r8",
                                             "assignments": TWO_I2C}))
    assert env["ok"] is True, env
    assert [p["verdict"] for p in env["result"]["pins"]] == ["ok"] * 4


def test_project_assign_stores_shared_bus_verdicts():
    handlers = tools.make_handlers(tools.Host(hook_active=True))
    created = json.loads(handlers["bench_project"]({"action": "create", "id": "bus-test", "title": "Bus",
                                                    "chip": "esp32s3", "variant": "n16r8"}))
    assert created["ok"], created
    env = json.loads(handlers["bench_project"]({"action": "assign", "id": "bus-test", "assignments": TWO_I2C}))
    assert env["ok"], env
    got = json.loads(handlers["bench_project"]({"action": "get", "id": "bus-test"}))["result"]["project"]
    assert [(a["role"], a["verdict"], a["rule_ids"]) for a in got["assignments"]] == [
        (a["role"], "ok", ["shared_bus"]) for a in TWO_I2C]


# --- DevKit module hint in variant_unknown ---------------------------------------------------------------------------
def _variant_warning(res):
    return next(w for w in res["warnings"] if w["code"] == "variant_unknown")


def test_c6_devkitc_without_variant_names_wroom_1():
    plain = _ok(pins.check("esp32c6", [{"role": "X", "mode": "in", "pin": 14}]))
    res = _ok(pins.check("esp32c6", [{"role": "X", "mode": "in", "pin": 14}], devkit="esp32-c6-devkitc-1"))
    w = _variant_warning(res)
    assert ("The DevKit is sold with module ESP32-C6-WROOM-1 (variant wroom-1, ordering information): pass "
            "variant=wroom-1 if your board carries it.") in w["message"]
    assert "devkitc1-c6-ordering" in w["source_ids"]
    assert "devkitc1-c6-ordering" in [s["id"] for s in res["sources"]]
    # verdicts unchanged (a hint, no default): GPIO14 is not broken out on the DevKitC-1 (blocked), and the variant
    # rule stays "depends on the variant" (caution, not_checked) as without the devkit
    p, q = res["result"]["pins"][0], plain["result"]["pins"][0]
    assert p["verdict"] == "blocked" and _ids(p) == ["not_broken_out", "c6.no_sip_flash"]
    assert q["verdict"] == "caution" and _ids(q) == ["c6.no_sip_flash"]
    assert p["reasons"][1] == q["reasons"][0] and p["reasons"][1]["severity"] == "caution"
    assert _status(res, "pins.no_sip_flash")["status"] == _status(plain, "pins.no_sip_flash")["status"] == "not_checked"
    assert res["result"]["variant"] is None
    assert "sold with module" not in _variant_warning(plain)["message"]


def test_module_hint_also_in_suggest_and_info():
    sug = _ok(pins.suggest("esp32c6", [{"role": "X", "mode": "out"}], devkit="esp32-c6-devkitm-1"))
    assert "pass variant=mini-1" in _variant_warning(sug)["message"]
    assert "devkitm1-c6-ordering" in [s["id"] for s in sug["sources"]]
    info = _ok(pins.info("esp32", 16, devkit="esp32-devkitc-v4"))
    assert "pass variant=wroom-32e" in _variant_warning(info)["message"]
    assert "devkitc-esp32-v4-ordering" in [s["id"] for s in info["sources"]]
    assert info["result"]["variant"] is None  # a hint, never a default


def test_no_module_hint_without_a_known_module_variant():
    # ESP32-S3-DevKitC-1 names no module variant; with a variant given there is no variant_unknown at all
    res = _ok(pins.check("esp32s3", [{"role": "X", "mode": "out", "pin": 4}], devkit="esp32-s3-devkitc-1"))
    assert "sold with module" not in _variant_warning(res)["message"]
    res = _ok(pins.check("esp32c6", [{"role": "X", "mode": "in", "pin": 14}], variant="wroom-1",
                         devkit="esp32-c6-devkitc-1"))
    assert not any(w["code"] == "variant_unknown" for w in res["warnings"])
