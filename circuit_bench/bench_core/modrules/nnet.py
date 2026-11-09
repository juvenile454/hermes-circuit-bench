"""Family rules ``nnet``: Ethernet, GNSS, USB-UART and NFC parts of data/modules/nnet.json.

Rules (warning code; severity before the severity cap):
- ``mod.nnet.rmii_pins`` (``mod_nnet_rmii_pins``): a LAN8720A (RMII PHY) needs the ESP's Ethernet MAC, and the EMAC
  routes the RMII data lines through the IO_MUX to fixed GPIOs. ESP-IDF v6.1 ``esp_eth.rst`` (source
  ``idf-v6.1-esp-eth``, lines 5-12) lists the pins for the ESP32 (TX_EN 21, TXD0 19, TXD1 22, CRS_DV 27, RXD0 25,
  RXD1 26; REF_CLK in GPIO0, out GPIO0/16/17) and the ESP32-P4 (several choices each); it names no RMII pins for
  any other target. Chip without EMAC pins in that list -> caution (use an SPI Ethernet controller such as the
  ENC28J60). An RMII pin on another GPIO -> caution (per pin, with the allowed GPIOs). REF_CLK (XTAL1/CLKIN or
  nINT/REFCLKO) on none of the allowed GPIOs -> caution; on GPIO0 of the ESP32 -> info (GPIO0 is a strapping pin:
  keep the clock off while the ESP32 boots, ``esp_eth.rst`` line 151). RMII pins without an ESP GPIO on their
  net are left to ``mod.unconnected``; none wired at all -> not_checked. Everything fits -> passed.

All findings rest on catalog data and the pinned ESP-IDF document and go through ``ctx.finding`` (source class cap).
"""
from __future__ import annotations

from collections.abc import Mapping

from . import modcheck

Ctx, Finding, Instance, rule = modcheck.Ctx, modcheck.Finding, modcheck.Instance, modcheck.rule

IDF_ETH = "idf-v6.1-esp-eth"
RMII_MODULES = frozenset({"lan8720a"})
# ESP-IDF v6.1 docs/en/api-reference/network/esp_eth.rst lines 5-12 (IDF_TARGET_SOC_* substitutions).
RMII_PINS: Mapping[str, Mapping[str, tuple[int, ...]]] = {
    "esp32": {"TXEN": (21,), "TXD0": (19,), "TXD1": (22,), "CRS_DV": (27,), "RXD0": (25,), "RXD1": (26,)},
    "esp32p4": {"TXEN": (33, 40, 49), "TXD0": (34, 41), "TXD1": (35, 42), "CRS_DV": (28, 45, 51),
                "RXD0": (29, 46, 52), "RXD1": (30, 47, 53)},
}
REF_CLK_IN: Mapping[str, tuple[int, ...]] = {"esp32": (0,), "esp32p4": (32, 44, 50)}
REF_CLK_OUT: Mapping[str, tuple[int, ...]] = {"esp32": (0, 16, 17), "esp32p4": (23, 39)}
REF_CLK_PINS = ("XTAL1", "nINT")  # XTAL1/CLKIN (REF_CLK In mode) or nINT/REFCLKO (REF_CLK Out mode)


def _gpios(ctx: Ctx, inst: Instance, pin: str) -> list[int]:
    net = ctx.net_of(inst, pin)
    if net is None:
        return []
    return sorted({g for g in (ctx.nets.get(net, {}).get("gpios") or []) if isinstance(g, int)})


def _gl(gpios: tuple[int, ...] | list[int]) -> str:
    return " or ".join(f"GPIO{g}" for g in gpios)


@rule("mod.nnet.rmii_pins")
def rmii_pins(ctx: Ctx) -> list[Finding]:
    rid = "mod.nnet.rmii_pins"
    out: list[Finding] = []
    sids = lambda inst: [s for s in (IDF_ETH, ctx.src(inst)) if s]  # noqa: E731
    for inst in ctx.instances:
        if inst.module_id not in RMII_MODULES:
            continue
        label = ctx.label(inst)
        table = RMII_PINS.get(ctx.chip)
        if table is None:
            out.append(ctx.finding(rid, "failed", "caution",
                                   f"{label} is an RMII Ethernet PHY and needs the ESP's Ethernet MAC; ESP-IDF lists "
                                   f"RMII pins only for the ESP32 and ESP32-P4, not for {ctx.chip}. Use an SPI "
                                   "Ethernet controller (e.g. ENC28J60) instead.",
                                   inst, source_ids=sids(inst), chip_fact=False))
            continue
        wrong: list[str] = []
        seen = 0
        for pin, allowed in table.items():
            got = _gpios(ctx, inst, pin)
            if not got:
                continue
            seen += 1
            if not any(g in allowed for g in got):
                wrong.append(f"{pin} on {_gl(got)} (the EMAC needs {_gl(allowed)})")
        ref = sorted({g for p in REF_CLK_PINS for g in _gpios(ctx, inst, p)})
        ref_ok = [g for g in ref if g in REF_CLK_IN[ctx.chip] or g in REF_CLK_OUT[ctx.chip]]
        if ref:
            seen += 1
            if not ref_ok:
                wrong.append(f"REF_CLK (XTAL1/CLKIN or nINT/REFCLKO) on {_gl(ref)} (input: "
                             f"{_gl(REF_CLK_IN[ctx.chip])}; output: {_gl(REF_CLK_OUT[ctx.chip])})")
        if not seen:
            out.append(Finding(rid, "not_checked", None, f"{label}: no RMII pin is on an ESP GPIO; RMII pins not "
                               "checked.", [inst.ref], sids(inst)))
            continue
        if wrong:
            out.append(ctx.finding(rid, "failed", "caution",
                                   f"{label}: the {ctx.chip} EMAC routes RMII to fixed GPIOs: {'; '.join(wrong)}.",
                                   inst, source_ids=sids(inst), chip_fact=False))
        if ctx.chip == "esp32" and 0 in ref_ok:
            out.append(ctx.finding(rid, "failed", "info",
                                   f"{label}: REF_CLK on GPIO0, a strapping pin of the ESP32. Keep the 50 MHz clock "
                                   "off while the ESP32 boots (oscillator enable or PHY reset) and enable it in the "
                                   "Ethernet driver.", inst, source_ids=sids(inst), chip_fact=False))
        if not wrong:
            out.append(Finding(rid, "passed", None, f"{label}: the RMII pins on ESP GPIOs match the {ctx.chip} "
                               "EMAC.", [inst.ref], sids(inst)))
    return out
