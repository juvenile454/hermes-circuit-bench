"""Family rules ``niox``: RV-3028-C7, MCP7940N, 24LC256, 24AA32A, TCA9555, PCA9555,
PCA9548A.

Address conflicts (fixed 0x52/0x6F, 0x20–0x27 against MCP23017/PCF857x, 0x70 against TCA9548A/PCA9685 All Call), mux
channels, supply ranges, pull-ups and tied address pins are generic. Only the backup inputs of
the two RTCs need a family rule:

- ``mod.niox.rtc_backup``:
  - RV-3028-C7: an unused VBACKUP must be tied to VSS through 10 kΩ (application manual p. 9). VBACKUP directly on
    GND -> failed/info.
  - MCP7940N: the VBAT input only takes over after firmware sets VBATEN (RTCWKDAY bit 3, data sheet p. 18). VBAT on a
    net other than GND -> failed/info (a reminder, the wiring is fine).
  - otherwise passed; VBACKUP/VBAT not connected -> no finding (``mod.unconnected`` reports must_connect pins).
The cited facts are notes with evidence in data/modules/niox.json; this file holds no limits.
"""
from __future__ import annotations

from . import modcheck

Finding, rule = modcheck.Finding, modcheck.rule

RID = "mod.niox.rtc_backup"
BACKUP_PIN: dict[str, str] = {"rv3028c7": "VBACKUP", "mcp7940n": "VBAT"}


@rule(RID)
def rtc_backup(ctx: modcheck.Ctx) -> list[modcheck.Finding]:
    out: list[modcheck.Finding] = []
    for inst in ctx.instances:
        pin = BACKUP_PIN.get(inst.module_id)
        if pin is None:
            continue
        net = ctx.net_of(inst, pin)
        if net is None:
            continue
        who = f"{ctx.label(inst)} {pin}"
        if inst.module_id == "rv3028c7":
            if net == "GND":
                out.append(ctx.finding(
                    RID, "failed", "info",
                    f"{who} is tied directly to GND: without a backup source the application manual asks for "
                    f"VBACKUP to VSS through a 10 kΩ resistor.", inst, source_id=ctx.src(inst)))
            else:
                out.append(Finding(RID, "passed", None, f"{who} on {net}.", [inst.ref]))
        elif net == "GND":
            out.append(Finding(RID, "passed", None, f"{who} on GND: battery backup not used.", [inst.ref]))
        else:
            out.append(ctx.finding(
                RID, "failed", "info",
                f"{who} on {net}: the MCP7940N switches to the backup supply only after firmware sets VBATEN "
                f"(RTCWKDAY bit 3).", inst, source_id=ctx.src(inst)))
    return out
