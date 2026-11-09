"""Module family net: real catalog entries W5500, NEO-6M, NEO-M8N, SD card (SPI mode), SIM800L and
the family rules in bench_core/modrules/net.py. Every project is synthetic; values come from data/modules/net.json."""
from __future__ import annotations

import json
from pathlib import Path

import excerpts as ex
import modkit as mk
import pytest

from circuit_bench.bench_core import electrical, modules, pins
from circuit_bench.bench_core.modrules import net as netrules

ROOT = Path(__file__).resolve().parent.parent
NET = {m["id"]: m for m in json.loads((ROOT / "circuit_bench" / "data" / "modules" / "net.json")
                                      .read_text(encoding="utf-8"))["modules"]}
NET_SOURCES = {s["id"]: s for s in json.loads((ROOT / "circuit_bench" / "data" / "sources" / "mod-net.json")
                                               .read_text(encoding="utf-8"))}
ESP = electrical.get("esp32s3")
UART = [mk.assign("uart_tx", 17, "GSM_RX"), mk.assign("uart_rx", 18, "GSM_TX")]
SPI = [mk.assign("spi_sck", 12, "SCK0"), mk.assign("spi_mosi", 11, "MOSI0"), mk.assign("spi_miso", 13, "MISO0"),
       mk.assign("spi_cs", 10, "CS0"), mk.assign("spi_cs", 9, "CS1")]
GNSS = [mk.assign("uart_tx", 17, "GPS_RX"), mk.assign("uart_rx", 18, "GPS_TX")]


def run(*parts, assignments=(), options=None, only=None):
    kw = {"only": only} if only else {}
    return mk.run(electrical=ESP, assignments=list(assignments), parts=list(parts), options=options, **kw)


def one(rep, rule_id, ref=None, status=None):
    fs = [f for f in mk.findings(rep, rule_id, status) if ref is None or ref in f.refs]
    assert len(fs) == 1, fs
    return fs[0]


def sim(vbat="VBAT", ref="U1", variant=None, facts=None, **extra):
    pin = "VCC" if variant == "breakout" else "VBAT"
    conn = {pin: vbat, "GND": "GND", "RXD": "GSM_RX", "TXD": "GSM_TX", **extra}
    return mk.mod(ref, "sim800l", conn, variant=variant, facts=facts)


VBAT40 = {"rails": {"VBAT": 4.0}}


# --- catalog and sources ------------------------------------------------------------------------------------------
def test_catalog_has_the_five_parts_without_problems():
    cat = modules.Catalog.from_dir()
    assert cat.problems == []
    rows = {r["id"]: r for r in cat.search(limit=400)["items"]}
    assert {k: (rows[k]["category"], rows[k]["class"]) for k in ("w5500", "neo6m", "neom8n", "sdcard", "sim800l")} == {
        "w5500": ("comm.ethernet", "A"), "neo6m": ("comm.gnss", "A"), "neom8n": ("comm.gnss", "A"),
        "sdcard": ("storage.sd", "A2"), "sim800l": ("comm.cellular", "A2")}
    assert rows["sim800l"]["supply"] == "3.4–4.4 V" and rows["w5500"]["supply"] == "2.97–3.63 V"
    assert rows["neo6m"]["supply"] == "2.7–3.6 V" and rows["sdcard"]["supply"] == "2.7–3.6 V"
    for mid, var in (("w5500", "breakout"), ("neo6m", "gy_neo6mv2"), ("neom8n", "gy_neom8n"), ("sdcard", "breakout"),
                     ("sim800l", "breakout")):
        board = cat.get(mid, var)
        assert board["kind"] == "module"
        assert any(n["verified"] is False for n in board["notes"]), mid


def test_sources_are_manufacturer_or_marked_copies():
    assert {k: s["class"] for k, s in NET_SOURCES.items()} == {
        "mod-net-w5500-ds": "A", "mod-net-neo6m-ds": "A", "mod-net-neom8n-ds": "A", "mod-net-sdcard-spec": "A2",
        "mod-net-sim800l-hd": "A2"}
    assert NET_SOURCES["mod-net-w5500-ds"]["url"].startswith("https://docs.wiznet.io/")
    assert all(NET_SOURCES[k]["url"].startswith("https://content.u-blox.com/") for k in ("mod-net-neo6m-ds",
                                                                                           "mod-net-neom8n-ds"))
    assert "blank" in NET_SOURCES["mod-net-sdcard-spec"]["note"]


def test_rule_constants_are_the_excerpt_lines():
    """The VIH maxima and the init clock in modrules/net.py are not in data/: pin them to the pinned excerpt."""
    by = ex.by_source("mod-net-*.txt", ex.EXCERPTS)
    (sim,) = by["mod-net-sim800l-hd"]
    assert netrules.SIM800_VIH_MAX["uart_rx"][:2] == (3.1, 28) and any(ln.strip() == "VIH 2.1 - 3.1  V" for ln in sim.page_segments(28)[0])
    assert netrules.SIM800_VIH_MAX["reset_in"][:2] == (2.0, 25) and any(ln.strip() == "VIH 1.5 1.8 2.0 V" for ln in sim.page_segments(25)[0])
    (sd,) = by["mod-net-sdcard-spec"]
    assert netrules.SD_INIT_HZ == (100_000.0, 400_000.0)
    assert any("frequency range of 100 KHz-400 KHz." in ln for ln in sd.page_segments(94)[0])


# --- SIM800L: VBAT ------------------------------------------------------------------------------------------------
def test_sim800_on_5v_is_danger_with_the_abs_max():
    rep = run(sim("5V"), assignments=UART, only=("mod.net.sim800_vbat", "mod.supply_range"))
    f = one(rep, "mod.net.sim800_vbat")
    assert (f.status, f.severity) == ("failed", "danger")
    assert "4.50 V" in f.message and "2.00 A" in f.message and f.source_ids == ["mod-net-sim800l-hd"]
    assert one(rep, "mod.supply_range").severity == "danger"
    assert "mod_net_sim800_vbat" in mk.codes(rep)


def test_sim800_on_3v3_is_caution_below_the_range():
    f = one(run(sim("3V3"), assignments=UART, only=("mod.net.sim800_vbat",)), "mod.net.sim800_vbat")
    assert (f.status, f.severity) == ("failed", "caution")
    assert "below the VBAT range 3.40 V–4.40 V" in f.message and "powers itself down" in f.message


def test_sim800_at_4v0_passes_and_names_the_burst():
    f = one(run(sim(), assignments=UART, options=VBAT40, only=("mod.net.sim800_vbat",)), "mod.net.sim800_vbat")
    assert f.status == "passed" and "2.00 A" in f.message


def test_sim800_rail_limit_below_the_burst_is_caution():
    opts = {**VBAT40, "rail_limits": {"VBAT": 1.0}}
    f = one(run(sim(), assignments=UART, options=opts, only=("mod.net.sim800_vbat",)), "mod.net.sim800_vbat")
    assert (f.status, f.severity) == ("failed", "caution") and "1.00 A" in f.message
    opts = {**VBAT40, "rail_limits": {"VBAT": 2.5}}
    assert one(run(sim(), assignments=UART, options=opts, only=("mod.net.sim800_vbat",)),
               "mod.net.sim800_vbat").status == "passed"


def test_sim800_unknown_vbat_is_not_checked():
    f = one(run(sim("VBAT"), assignments=UART, only=("mod.net.sim800_vbat",)), "mod.net.sim800_vbat")
    assert f.status == "not_checked" and f.severity is None


def test_sim800_breakout_caps_the_5v_danger_until_the_regulator_is_confirmed():
    rep = run(sim("5V", variant="breakout"), assignments=UART, only=("mod.net.sim800_vbat",))
    assert one(rep, "mod.net.sim800_vbat").severity == "caution"
    rep = run(sim("5V", variant="breakout", facts={"regulator": "none"}), assignments=UART,
              only=("mod.net.sim800_vbat",))
    assert one(rep, "mod.net.sim800_vbat").severity == "danger"


def test_sim800_bulk_cap_is_a_recommended_requirement():
    req = NET["sim800l"]["requires"][0]
    assert (req["code"], req["pins"], req["page"]) == ("bulk_cap", ["VBAT"], 20) and "100 µF" in req["value"]
    assert NET["sim800l"]["current"]["peak"]["value"] == 2.0


# --- SIM800L: logic levels ----------------------------------------------------------------------------------------
def test_sim800_rxd_from_a_3v3_gpio_is_caution():
    f = one(run(sim(), assignments=UART, options=VBAT40, only=("mod.net.sim800_vih",)), "mod.net.sim800_vih")
    assert (f.status, f.severity) == ("failed", "caution")
    assert "RXD" in f.message and "3.30 V" in f.message and "3.10 V" in f.message and "RESET" not in f.message
    assert f.source_ids == ["mod-net-sim800l-hd"]


def test_sim800_reset_driven_by_a_gpio_is_named():
    asg = [*UART, mk.assign("out", 5, "GSM_RST")]
    f = one(run(sim(RESET="GSM_RST"), assignments=asg, options=VBAT40, only=("mod.net.sim800_vih",)),
            "mod.net.sim800_vih")
    assert "RESET" in f.message and "2.00 V" in f.message and "open-drain" in f.message


def test_sim800_level_shifter_passes_and_unwired_rxd_is_silent():
    rep = run(sim(facts={"level_shifter": True}), assignments=UART, options=VBAT40, only=("mod.net.sim800_vih",))
    assert one(rep, "mod.net.sim800_vih").status == "passed"
    rep = run(mk.mod("U1", "sim800l", {"VBAT": "VBAT", "GND": "GND", "TXD": "GSM_TX"}), assignments=UART[1:],
              options=VBAT40, only=("mod.net.sim800_vih",))
    assert mk.findings(rep, "mod.net.sim800_vih") == []


# --- SD card ------------------------------------------------------------------------------------------------------
def sd(vdd="3V3", variant=None, facts=None, ref="U2"):
    conn = ({"SCK": "SCK0", "MOSI": "MOSI0", "MISO": "MISO0", "CS": "CS0", "VCC": vdd, "GND": "GND"}
            if variant == "breakout" else
            {"SCLK": "SCK0", "DI": "MOSI0", "DO": "MISO0", "CS": "CS0", "VDD": vdd, "VSS": "GND"})
    return mk.mod(ref, "sdcard", conn, variant=variant, facts=facts)


def test_sd_init_hint_is_info_with_the_spec_values():
    rep = run(sd(), assignments=SPI)
    f = one(rep, "mod.net.sd_spi_init_400k")
    assert (f.status, f.severity) == ("failed", "info")
    assert "100 kHz–400 kHz" in f.message and "74 clocks" in f.message and "25.0 MHz" in f.message
    assert f.source_ids == ["mod-net-sdcard-spec"]
    assert one(rep, "mod.supply_range").status == "passed"


def test_sd_init_hint_needs_sclk_on_an_esp_pin():
    rep = run(mk.mod("U2", "sdcard", {"VDD": "3V3", "VSS": "GND"}), assignments=SPI)
    assert mk.findings(rep, "mod.net.sd_spi_init_400k") == []


def test_bare_card_on_5v_is_caution_and_the_breakout_with_regulator_info():
    f = one(run(sd("5V"), assignments=SPI, only=("mod.supply_range",)), "mod.supply_range")
    assert (f.status, f.severity) == ("failed", "caution") and "3.60 V" in f.message
    f = one(run(sd("5V", "breakout", {"regulator": "3V3"}), assignments=SPI, only=("mod.supply_range",)),
            "mod.supply_range")
    assert (f.status, f.severity) == ("failed", "info")


def test_sd_entry_has_no_logic_levels_from_the_blank_tables():
    m = NET["sdcard"]
    assert "io" not in m
    assert m["current"]["max"]["value"] == 0.1 and m["interfaces"][0]["f_max_hz"]["value"] == 25e6


# --- W5500 --------------------------------------------------------------------------------------------------------
def w5500(vdd="3V3", ref="U3"):
    return mk.mod(ref, "w5500", {"SCLK": "SCK0", "MOSI": "MOSI0", "MISO": "MISO0", "SCSn": "CS1", "VDD": vdd,
                                 "GND": "GND", "INTn": "ETH_INT"})


def test_w5500_current_lands_in_the_3v3_budget():
    rep = run(w5500(), assignments=[*SPI, mk.assign("in", 14, "ETH_INT")])
    rails = {r["net"]: r for r in rep.result["rails"]}
    assert rails["3V3"]["i_typ"] == pytest.approx(0.132) and rails["3V3"]["i_max"] == pytest.approx(0.132)
    rep = run(w5500(), sd(), assignments=SPI)
    rails = {r["net"]: r for r in rep.result["rails"]}
    assert rails["3V3"]["i_max"] == pytest.approx(0.232)  # W5500 132 mA + SD card 100 mA


def test_w5500_on_5v_exceeds_abs_max_and_3v3_is_clean():
    f = one(run(w5500("5V"), assignments=SPI, only=("mod.supply_range",)), "mod.supply_range")
    assert (f.status, f.severity) == ("failed", "danger") and "4.60 V" in f.message
    rep = run(w5500(), assignments=SPI, only=("mod.supply_range", "mod.net.sim800_vih", "mod.net.sd_spi_init_400k"))
    assert [f.status for f in mk.findings(rep)] == ["passed"]


def test_w5500_entry_spi_and_levels():
    m = NET["w5500"]
    spi = m["interfaces"][0]
    assert spi["mode"] == 0 and spi["f_max_hz"]["value"] == 33.3e6
    assert m["io"]["five_v_tolerant"] is True and m["io"]["vih"]["value"] == 2.0
    assert {p["name"]: p.get("internal_pull") is not None for p in m["pins"]}["RSTn"] is True


# --- GNSS ---------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("mid,tx,rx", [("neo6m", "TxD1", "RxD1"), ("neom8n", "TXD", "RXD")])
def test_gnss_module_on_5v_is_danger(mid, tx, rx):
    part = mk.mod("U4", mid, {"VCC": "5V", "GND": "GND", tx: "GPS_TX", rx: "GPS_RX", "V_BCKP": "3V3"})
    f = one(run(part, assignments=GNSS, only=("mod.supply_range",)), "mod.supply_range", status="failed")
    assert f.severity == "danger" and "3.60 V" in f.message
    assert NET[mid]["interfaces"][0]["baud_default"] == 9600
    vmax = NET[mid]["io"]["v_in_max"]
    assert (vmax.get("value"), vmax.get("rel_offset")) == ((3.6, None) if mid == "neo6m" else (None, 0.5))
    assert NET[mid]["io"]["five_v_tolerant"] is False


def test_gnss_breakouts_at_5v_are_capped_by_the_regulator_fact():
    conn = {"VCC": "5V", "GND": "GND", "TX": "GPS_TX", "RX": "GPS_RX"}
    for mid, var in (("neo6m", "gy_neo6mv2"), ("neom8n", "gy_neom8n")):
        rep = run(mk.mod("U4", mid, conn, variant=var), assignments=GNSS, only=("mod.supply_range",))
        assert one(rep, "mod.supply_range").severity == "caution", mid
        rep = run(mk.mod("U4", mid, conn, variant=var, facts={"regulator": "3V3"}), assignments=GNSS,
                  only=("mod.supply_range",))
        assert one(rep, "mod.supply_range").severity == "info", mid


def test_gnss_at_3v3_is_clean():
    part = mk.mod("U4", "neo6m", {"VCC": "3V3", "GND": "GND", "TxD1": "GPS_TX", "RxD1": "GPS_RX", "V_BCKP": "3V3"})
    rep = run(part, assignments=GNSS, only=("mod.supply_range",))
    assert {f.status for f in mk.findings(rep)} == {"passed"}
    m8 = NET["neom8n"]
    assert m8["io"]["v_in_max"]["of"] == "VCC" and "capped at 3.6 V" in m8["io"]["v_in_max"]["conditions"]
    assert next(p for p in m8["pins"] if p["name"] == "RESET_N")["internal_pull"]["up"]["value"] == 11000.0


# --- end to end ---------------------------------------------------------------------------------------------------
def test_pins_check_reports_net_warnings():
    parts = [{"ref": "U1", "kind": "module", "value": "SIM800L", "module": "sim800l",
              "conn": {"VBAT": "3V3", "GND": "GND", "RXD": "GSM_RX", "TXD": "GSM_TX"}},
             {"ref": "U2", "kind": "ic", "value": "microSD", "module": "sdcard",
              "conn": {"SCLK": "SCK0", "DI": "MOSI0", "DO": "MISO0", "CS": "CS0", "VDD": "3V3", "VSS": "GND"}}]
    res = pins.check("esp32s3", [*UART, *SPI[:4]], parts=parts, options={})
    codes = {w["code"] for w in res["warnings"]}
    assert "mod_net_sim800_vbat" in codes  # the shown warnings are capped and sorted by severity
    # compact answers fold the module checks into one summary check "modules"
    ids = {c["id"] for c in res["checks"]}
    summary = " ".join(c["detail"] for c in res["checks"] if c["id"] == "modules")
    for rule in ("net.sim800_vbat", "net.sim800_vih", "net.sd_spi_init_400k"):
        assert f"modules.{rule}" in ids or rule in summary
    assert "mod-net-sim800l-hd" in {src["id"] for src in res["sources"]}


# --- data corrections ------------------------------------------------------------------------------------------------
def test_sim800_vbat_folds_the_generic_supply_range_finding():
    """p35: SIM800L on 3V3 gives one supply warning (sim800_vbat), the generic supply_range one is covered."""
    rep = run(sim(vbat="3V3"), assignments=UART, only=("mod.net.sim800_vbat", "mod.supply_range"))
    f = one(rep, "mod.net.sim800_vbat", status="failed")
    assert f.supersedes == ("mod.supply_range",)
    codes = [w["code"] for w in rep.warnings if w["severity"] in ("caution", "danger")]
    assert codes.count("mod_net_sim800_vbat") == 1 and "mod_supply_range" not in codes
    check = [c for c in rep.checks if c["id"].endswith("supply_range")][0]
    assert check["detail"].startswith("covered by mod_net_sim800_vbat")


def test_w5500_and_neom8n_v_in_max_are_the_absolute_ratings():
    w = NET["w5500"]["io"]["v_in_max"]
    assert (w["value"], w["page"], w["evidence"]) == (6.0, 58, "VIN DC input voltage -0.5 to 6 V")
    m8 = NET["neom8n"]["io"]["v_in_max"]
    assert (m8["rel_offset"], m8["of"], m8["page"]) == (0.5, "VCC", 18)
