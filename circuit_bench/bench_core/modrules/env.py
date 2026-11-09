"""Family rules ``env``: Bosch BMx280/BME68x and Sensirion SHT3x.

Every fact comes from the entry's own datasheet (data/modules/env.json, data/sources/mod-env.json); the page is named
in the message. The generic rules (supply, levels, addresses, power budget with the heater peaks in ``current.peak``)
live in bus.py / elec.py.

- ``mod.env.bmp_vs_bme`` (info): a BME280 or BMP280 instance -> the chip_id hint (BME280 0x60, BMP280 0x58,
  register 0xD0), because boards are sold under the wrong name. Datasheets: BME280 p. 27, BMP280 p. 24.
- ``mod.env.bme680_sdo_float`` (caution): SDO of a Bosch part (BME280, BMP280, BME680, BME688) without a net. All four
  datasheets: "The SDO pin cannot be left floating; if left floating, the I²C address will be undefined."
  (BME680 p. 38, BME688 p. 45, BME280 p. 33, BMP280 p. 28). Connected (to GND, VDDIO or a GPIO) -> passed. The
  failed finding supersedes ``mod.address_select`` (SDO open) on the same part: one cause, one warning.
- ``mod.env.sht_addr_float`` (caution): ADDR of an SHT3x without a net. SHT3x-DIS datasheet p. 9: "The ADDR pin must
  not be left floating."
"""
from __future__ import annotations

from . import modcheck

Ctx, Finding, rule = modcheck.Ctx, modcheck.Finding, modcheck.rule

CHIP_ID = {"bme280": ("0x60", 27), "bmp280": ("0x58", 24)}
SDO_PAGE = {"bme280": 33, "bmp280": 28, "bme680": 38, "bme688": 45}
SHT_ADDR_PAGE = {"sht31": 9}


def _open(inst: modcheck.Instance, pin: str) -> bool:
    net = inst.conn.get(pin)
    return not isinstance(net, str) or not net.strip()


@rule("mod.env.bmp_vs_bme")
def bmp_vs_bme(ctx: Ctx) -> list[Finding]:
    out = []
    for inst in ctx.instances:
        if inst.module_id not in CHIP_ID:
            continue
        cid, page = CHIP_ID[inst.module_id]
        if inst.module_id == "bme280":
            msg = (f"{ctx.label(inst)}: boards sold as BME280 sometimes carry a BMP280 (no humidity). Read register "
                   f"0xD0 (chip_id): {cid} = BME280, 0x58 = BMP280 (datasheet p. {page}).")
        else:
            msg = (f"{ctx.label(inst)}: the BMP280 measures pressure and temperature only, no humidity. Register "
                   f"0xD0 (chip_id) reads {cid} on a BMP280 and 0x60 on a BME280 (datasheet p. {page}).")
        out.append(ctx.finding("mod.env.bmp_vs_bme", "failed", "info", msg, inst, source_id=ctx.src(inst)))
    return out


@rule("mod.env.bme680_sdo_float")
def bme680_sdo_float(ctx: Ctx) -> list[Finding]:
    out = []
    for inst in ctx.instances:
        page = SDO_PAGE.get(inst.module_id)
        if page is None:
            continue
        if _open(inst, "SDO"):
            out.append(ctx.finding(
                "mod.env.bme680_sdo_float", "failed", "caution",
                f"{ctx.label(inst)}: SDO is not connected. The SDO pin cannot be left floating, otherwise the I²C "
                f"address is undefined (datasheet p. {page}). Connect SDO to GND (0x76) or VDDIO (0x77); on a "
                f"breakout, check whether the board already pulls SDO.", inst, source_id=ctx.src(inst),
                chip_fact=False))
            out[-1].supersedes = ("mod.address_select",)
        else:
            out.append(ctx.finding("mod.env.bme680_sdo_float", "passed", None,
                                   f"{ctx.label(inst)}: SDO on {inst.conn['SDO']}.", inst, source_id=ctx.src(inst)))
    return out


@rule("mod.env.sht_addr_float")
def sht_addr_float(ctx: Ctx) -> list[Finding]:
    out = []
    for inst in ctx.instances:
        page = SHT_ADDR_PAGE.get(inst.module_id)
        if page is None:
            continue
        if _open(inst, "ADDR"):
            out.append(ctx.finding(
                "mod.env.sht_addr_float", "failed", "caution",
                f"{ctx.label(inst)}: ADDR is not connected. The ADDR pin must not be left floating (datasheet "
                f"p. {page}). Connect ADDR to GND (0x44) or VDD (0x45); on a breakout, check whether the board "
                f"already pulls ADDR.", inst, source_id=ctx.src(inst), chip_fact=False))
        else:
            out.append(ctx.finding("mod.env.sht_addr_float", "passed", None,
                                   f"{ctx.label(inst)}: ADDR on {inst.conn['ADDR']}.", inst, source_id=ctx.src(inst)))
    return out
