"""Family rules ``nenv``: Sensirion SEN55 and ScioSense ENS160.

Every fact comes from the entry's own datasheet (data/modules/nenv.json, data/sources/mod-nenv.json); the page is
named in the message. Addresses (BMP388/BMP390 vs BME280 at 0x76/0x77, SHTC3 at 0x70 vs TCA9548A/PCA9685 All-Call,
TMP117 vs ADS1115 at 0x48–0x4B, SEN55 vs MPU-6050 at 0x69), supply ranges (ENS160 VDD 1.8 V, SEN55 5 V), levels,
bus speed (SEN55 100 kHz) and the required parts are the generic rules in bus.py / elec.py.

- ``mod.nenv.sen55_sel_gnd`` (caution): SEN5x datasheet p. 17: "the interface select (SEL) pin must be pulled to GND
  before or at the same time the sensor is powered up" (pin table p. 13: "Connect to GND"). SEL on the net of the GND
  pin (the default tie) -> passed; SEL open or on any other net (a rail or a GPIO, which is only driven after the ESP
  boots) -> failed/caution; GND pin open -> not_checked.
- ``mod.nenv.ens160_warmup`` (info): an ENS160 -> the start-up hint: 3 minutes warm-up after every power-on, 1 hour
  at the very first start-up before the readings are reasonable (datasheet p. 15, Table 9).
"""
from __future__ import annotations

from . import modcheck

Ctx, Finding, rule = modcheck.Ctx, modcheck.Finding, modcheck.rule

SEL_PAGE = 17
WARMUP_PAGE = 15
# the datasheet lines the messages rest on (tests/test_mod_nenv.py checks them against the excerpts)
QUOTES = {
    "mod-nenv-sen55-ds": {13: ["5 SEL Interface select Connect to GND"],
                          17: ["interface select (SEL) pin must be pulled to",
                               "GND before or at the same time the sensor is powered up."]},
    "mod-nenv-ens160-ds": {15: ["Initial Start-up 1 hour", "Warm-up 3 minutes"],
                           16: ["See “Validity Flag” in section “DEVICE_STATUS (Address 0x20)”"]},
}


def _net(inst: modcheck.Instance, pin: str) -> str | None:
    net = inst.conn.get(pin)
    return net.strip() if isinstance(net, str) and net.strip() else None


@rule("mod.nenv.sen55_sel_gnd")
def sen55_sel_gnd(ctx: Ctx) -> list[Finding]:
    rid = "mod.nenv.sen55_sel_gnd"
    out: list[Finding] = []
    for inst in ctx.instances:
        if inst.module_id != "sen55":
            continue
        sid = ctx.src(inst)
        gnd, sel = _net(inst, "GND"), _net(inst, "SEL")
        if gnd is None:
            out.append(Finding(rid, "not_checked", None, f"{ctx.label(inst)}: GND not connected, SEL not checked.",
                               [inst.ref], [sid] if sid else []))
            continue
        if sel == gnd:
            out.append(Finding(rid, "passed", None, f"{ctx.label(inst)}: SEL on {gnd}, I²C selected.", [inst.ref],
                               [sid] if sid else []))
            continue
        where = "not connected" if sel is None else f"on {sel}"
        out.append(ctx.finding(
            rid, "failed", "caution",
            f"{ctx.label(inst)}: SEL is {where}. The interface select (SEL) pin must be pulled to GND before or at "
            f"the same time the sensor is powered up to select I²C (datasheet p. {SEL_PAGE}); tie SEL to {gnd}.",
            inst, source_id=sid))
    return out


@rule("mod.nenv.ens160_warmup")
def ens160_warmup(ctx: Ctx) -> list[Finding]:
    out: list[Finding] = []
    for inst in ctx.instances:
        if inst.module_id != "ens160":
            continue
        out.append(ctx.finding(
            "mod.nenv.ens160_warmup", "failed", "info",
            f"{ctx.label(inst)}: TVOC/eCO2/AQI readings need 3 minutes of warm-up after each power-on and 1 hour at "
            f"the very first start-up (datasheet p. {WARMUP_PAGE}); discard earlier values (DEVICE_STATUS validity "
            f"flag).", inst, source_id=ctx.src(inst), chip_fact=False))
    return out
