"""Family rules ``radio``: nRF24L01+, SX1276/RFM95W, MFRC522, PN532.

Every fact comes from the entry's own manufacturer document (data/modules/radio.json, data/sources/mod-radio.json); the
page is named in the message and the same line is quoted in the entry (``requires``/``notes``), which
tests/test_mod_radio.py ties to the constants below. Supply, levels, addresses and the power budget (TX peaks in
``current.peak``) are the generic rules in bus.py / elec.py.

- ``mod.radio.nrf24_bulk_cap`` (info): an nRF24L01+ without a large capacitor between VCC and GND. Nordic nRF24L01+
  Product Specification v1.0 p. 65: "Mounting a large surface mount capacitor (for example, 4.7µF ceramic) in parallel
  with the smaller value capacitors is recommended." The value is an example, not a limit: a capacitor ≥ 4.7 µF on
  VCC–GND passes, a smaller one or none is an info. VCC open -> not_checked.
- ``mod.radio.sx1276_duty_20dbm`` (info; caution below 2.4 V): SX1276 datasheet Rev. 7 p. 84 and RFM95W datasheet
  (2019 edition) p. 80: "+20 dBm" on PA_BOOST is limited to a 1 % transmit duty cycle and needs a 2.4–3.7 V supply.
  The project has no TX power setting, so every SX1276/RFM95W gets the info; a known supply below 2.4 V -> caution
  ("+20 dBm is not available").
- ``mod.radio.pn532_lsb_first`` (info): a PN532 on SPI (no variant or variant ``spi``): mode 0, LSB first (UM0701-02
  p. 25). Most SPI drivers default to MSB first.
- ``mod.radio.mfrc522_sda_is_cs`` (caution): the MFRC522 board pin "SDA" is the SPI chip select (NSS) on RC522 boards
  (MFRC522 data sheet Rev. 3.9 p. 9, Table 5: pin SDA = NSS in SPI mode). On a net with an ESP ``i2c_sda`` pin or a
  module's I²C SDA -> caution; on an ESP ``spi_cs``/``out`` pin -> passed; open -> not_checked.
"""
from __future__ import annotations

import re
from typing import Any

from . import modcheck

Ctx, Finding, Instance, fmt, rule = modcheck.Ctx, modcheck.Finding, modcheck.Instance, modcheck.fmt, modcheck.rule

# nRF24L01+ Product Specification v1.0, p. 65 (mod-radio-nrf24l01p-ps)
NRF_BULK = {"farads": 4.7e-6, "page": 65, "source_id": "mod-radio-nrf24l01p-ps"}
# +20 dBm on PA_BOOST: (source id, page, duty cycle %, minimum supply V)
PA20 = {"sx1276": ("mod-radio-sx1276-ds", 84, 1.0, 2.4), "rfm95w": ("mod-radio-rfm95w-sf", 80, 1.0, 2.4)}
PA20_DOC = {"sx1276": "SX1276 datasheet Rev. 7", "rfm95w": "RFM95W datasheet, 2019 edition"}
PN532_SPI = {"source_id": "mod-radio-pn532-um", "page": 25}
MFRC522_CS = {"source_id": "mod-radio-mfrc522-ds", "page": 9}

_CAP_KINDS = {"capacitor", "ceramic", "electrolytic", "film", "cap"}
_CAP_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*([pnuµμm])\s*F?", re.I)
_CAP_RKM = re.compile(r"^(\d+)([pnuµμ])(\d+)", re.I)
_EXP = {"p": -12, "n": -9, "u": -6, "µ": -6, "μ": -6, "m": -3}


def capacitance(value: Any) -> float | None:
    """Farads from a value text ('4.7uF', '4u7', '10 µF', '100nF'); None if no capacitance is found."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    m = _CAP_RKM.match(text)
    if m:
        return float(f"{m.group(1)}.{m.group(3)}") * 10 ** _EXP[m.group(2).lower()]
    m = _CAP_RE.search(text)
    if m:
        return float(m.group(1).replace(",", ".")) * 10 ** _EXP[m.group(2).lower()]
    return None


def _is_cap(part: dict[str, Any]) -> bool:
    kind = str(part.get("kind") or "").strip().lower()
    ref = str(part.get("ref") or "")
    return kind in _CAP_KINDS or (not kind and re.match(r"^C\d", ref) is not None)


def _part_nets(ctx: Ctx, part: dict[str, Any]) -> set[str]:
    """Nets a plain part touches (ctx.nets lists (ref, pin) per net, GPIO names already resolved)."""
    ref = part.get("ref")
    return {n for n, info in ctx.nets.items() if any(r == ref for r, _ in info.get("pins", []))}


@rule("mod.radio.nrf24_bulk_cap")
def nrf24_bulk_cap(ctx: Ctx) -> list[Finding]:
    out = []
    rid, page, sid = "mod.radio.nrf24_bulk_cap", NRF_BULK["page"], NRF_BULK["source_id"]
    for inst in ctx.instances:
        if inst.module_id != "nrf24l01p":
            continue
        vcc, gnd = ctx.net_of(inst, "VCC"), ctx.net_of(inst, "GND") or "GND"
        if vcc is None:
            out.append(Finding(rid, "not_checked", None, f"{ctx.label(inst)}: VCC not connected, bulk capacitor "
                                                         "not checked.", [inst.ref]))
            continue
        caps = [(p.get("ref"), capacitance(p.get("value"))) for p in ctx.parts
                if not p.get("module") and _is_cap(p) and {vcc, gnd} <= _part_nets(ctx, p)]
        known = [c for _, c in caps if c is not None]
        big = [r for r, c in caps if c is not None and c >= NRF_BULK["farads"] * (1 - 1e-9)]
        if big:
            out.append(Finding(rid, "passed", None, f"{ctx.label(inst)}: {', '.join(map(str, big))} on {vcc}–{gnd} "
                                                    f"(≥ {NRF_BULK['farads'] * 1e6:g} µF).", [inst.ref], [sid]))
            continue
        if caps and not known:
            out.append(Finding(rid, "not_checked", "info", f"{ctx.label(inst)}: capacitor value of "
                                                           f"{', '.join(str(r) for r, _ in caps)} unknown, bulk "
                                                           "capacitor not checked.", [inst.ref], [sid]))
            continue
        have = (f"the largest capacitor on {vcc}–{gnd} is {fmt(max(known), 'F')}" if known
                else f"no capacitor between {vcc} and {gnd} in the parts list")
        out.append(ctx.finding(rid, "failed", "info",
                               f"{ctx.label(inst)}: {have}. Nordic recommends a large ceramic capacitor (for example "
                               f"{NRF_BULK['farads'] * 1e6:g} µF) in parallel with the small decoupling capacitors at "
                               f"VDD (product specification p. {page}).", inst, source_id=sid, chip_fact=False))
    return out


@rule("mod.radio.sx1276_duty_20dbm")
def sx1276_duty_20dbm(ctx: Ctx) -> list[Finding]:
    out = []
    rid = "mod.radio.sx1276_duty_20dbm"
    for inst in ctx.instances:
        if inst.module_id not in PA20:
            continue
        sid, page, duty, vmin = PA20[inst.module_id]
        sup = ctx.supply_volts(inst)
        v = min(sup.values()) if sup else None
        if v is not None and v < vmin - 1e-9:
            out.append(ctx.finding(rid, "failed", "caution",
                                   f"{ctx.label(inst)} at {fmt(v, 'V')}: +20 dBm on PA_BOOST needs a "
                                   f"{vmin:g}–3.7 V supply, so +20 dBm is not available here ({PA20_DOC[inst.module_id]} p. {page}).",
                                   inst, source_id=sid, supply=True))
            continue
        out.append(ctx.finding(rid, "failed", "info",
                               f"{ctx.label(inst)}: at +20 dBm on PA_BOOST the transmit duty cycle is limited to "
                               f"{duty:g} % and the supply must be {vmin:g}–3.7 V ({PA20_DOC[inst.module_id]} p. {page}); "
                               "regional rules (e.g. EU 868 MHz) may be stricter.", inst, source_id=sid,
                               chip_fact=False))
    return out


@rule("mod.radio.pn532_lsb_first")
def pn532_lsb_first(ctx: Ctx) -> list[Finding]:
    out = []
    for inst in ctx.instances:
        if inst.module_id != "pn532":
            continue
        spi = next((it for it in inst.module.get("interfaces") or [] if it.get("type") == "spi"), None)
        if spi is None or not spi.get("lsb_first"):
            continue
        out.append(ctx.finding("mod.radio.pn532_lsb_first", "failed", "info",
                               f"{ctx.label(inst)}: the PN532 SPI uses mode 0 and sends LSB first (user manual "
                               f"UM0701-02 p. {PN532_SPI['page']}); set the bit order of this SPI device to LSB first "
                               "(ESP-IDF: SPI_DEVICE_BIT_LSBFIRST, Arduino: SPISettings(..., LSBFIRST, SPI_MODE0)). "
                               "Select SPI with I0 = 0, I1 = 1.", inst, source_id=PN532_SPI["source_id"],
                               chip_fact=False))
    return out


@rule("mod.radio.mfrc522_sda_is_cs")
def mfrc522_sda_is_cs(ctx: Ctx) -> list[Finding]:
    out = []
    rid, page, sid = "mod.radio.mfrc522_sda_is_cs", MFRC522_CS["page"], MFRC522_CS["source_id"]
    for inst in ctx.instances:
        if inst.module_id != "mfrc522":
            continue
        net = ctx.net_of(inst, "SDA")
        if net is None:
            out.append(Finding(rid, "not_checked", None, f"{ctx.label(inst)}: SDA (SPI chip select) not "
                                                         "connected.", [inst.ref]))
            continue
        info = ctx.nets.get(net, {})
        i2c_esp = "i2c_sda" in (info.get("modes") or [])
        by_ref = {i.ref: i for i in ctx.instances}
        i2c_mod = sorted({r for r, p in info.get("pins", []) if r != inst.ref and r in by_ref and any(
            pp.get("name") == p and pp.get("signal") == "i2c_sda" for pp in by_ref[r].module.get("pins") or [])})
        if i2c_esp or i2c_mod:
            on = "an ESP I²C SDA pin" if i2c_esp else f"the I²C SDA of {', '.join(i2c_mod)}"
            out.append(ctx.finding(rid, "failed", "caution",
                                   f"{ctx.label(inst)}: the board pin 'SDA' is the SPI chip select (NSS) of the "
                                   f"MFRC522 in SPI mode (data sheet p. {page}, Table 5), but net {net} is {on}. "
                                   "Wire SDA to its own GPIO as chip select (mode spi_cs or out).", inst,
                                   source_id=sid, chip_fact=False))
        elif any(m in ("spi_cs", "out") for m in info.get("modes") or []):
            out.append(Finding(rid, "passed", None, f"{ctx.label(inst)}: SDA (SPI chip select) on {net}.",
                               [inst.ref], [sid]))
    return out

