"""Family rules ``iox``: I/O expanders, PWM controller, I²C switch.

- ``mod.iox.mcp23017_gpx7_output``: GPA7/GPB7 of the MCP23017 (and GP7 of the MCP23008) are output only in the
  current datasheets (DS20001952E p. 11, DS20001919I p. 4). A net on such a pin that something else drives (an ESP
  output, another module's output pin, a switch/button part) or that is tied to a rail means the pin is used as an
  input -> info. Pins without a connection give no finding.
- ``mod.iox.pcf8574_quasi_bidir``: PCF8574/PCF8574A/PCF8575 ports are quasi-bidirectional: high = a 30-310 µA
  current source (SCPS068K/SCPS069H p. 5, SCPS121I p. 5). Loads (LED, transistor, relay, buzzer part) on port pins
  -> one info per expander listing them: wire the load active-low (sink) or add a driver. Port pins that only drive
  module logic inputs (e.g. an LCD backpack) are fine with the weak high -> passed.
- ``mod.iox.pca9685_allcall``: the PCA9685 answers the LED All Call address 0x70 after power-up (NXP PCA9685 Rev. 4
  p. 8, MODE1.ALLCALL = 1 p. 14). Any other device at 0x70 that can see the PCA9685 (same segment, or mux
  ancestor/descendant: ``Ctx.visible``), or a PCA9685 set to 0x70 itself -> caution (two devices answer one
  address: wrong data, no damage). Other PCA9685 are not counted (answering All Call together is the feature). The
  finding supersedes ``mod.address_reserved`` (bus.py reports the same pair generically).
"""
from __future__ import annotations

from typing import Any

from . import modcheck

Finding, rule, norm_address = modcheck.Finding, modcheck.rule, modcheck.norm_address

OUTPUT_ONLY: dict[str, tuple[str, ...]] = {"mcp23017": ("GPA7", "GPB7"), "mcp23008": ("GP7",)}
QUASI: dict[str, str] = {"pcf8574": "P", "pcf8574a": "P", "pcf8575": "P"}
ALLCALL = "0x70"
SUPERSEDES = ("mod.address_reserved",)  # bus.py reports the same pair generically: one cause, one warning

DRIVING_MODES = frozenset({"out", "pwm"})                     # an ESP output on the net drives the pin
DRIVING_SIGNALS = frozenset({"digital_out", "open_drain_out", "analog_out", "led_data_out", "uart_tx", "power_out",
                             "i2s_dout", "spi_sdo"})
INPUT_SIGNALS = frozenset({"digital_in", "pwm_in", "led_data_in", "reset_in", "enable_in", "i2s_din", "spi_sdi",
                           "spi_cs", "spi_sck", "uart_rx"})
SWITCH_KINDS = frozenset({"switch", "button"})
LOAD_KINDS = frozenset({"led", "transistor", "relay", "buzzer"})
MAX_LISTED = 4  # port pins named in one quasi_bidir finding (the rest are counted)
LOAD_PREFIXES = (("LED", "led"), ("Q", "transistor"), ("K", "relay"), ("BZ", "buzzer"))


def _port_order(pin: str, prefix: str) -> tuple[int, str]:
    tail = pin[len(prefix):]
    return (int(tail), pin) if pin.startswith(prefix) and tail.isdigit() else (10**6, pin)


def _pin_signal(inst: modcheck.Instance, pin: str) -> str | None:
    for p in inst.module.get("pins") or []:
        if isinstance(p, dict) and p.get("name") == pin:
            return p.get("signal")
    return None


def _part_kind(part: dict[str, Any]) -> str | None:
    k = part.get("kind")
    if isinstance(k, str) and k and k != "unknown":
        return k
    ref = str(part.get("ref") or "").upper()
    for prefix, kind in LOAD_PREFIXES:
        if ref.startswith(prefix) and ref[len(prefix):len(prefix) + 1].isdigit():
            return kind
    return None


def _others_on(ctx: modcheck.Ctx, inst: modcheck.Instance, net: str) -> list[tuple[str, str, str | None, str | None]]:
    """(ref, pin, module signal or None, part kind or None) of the other pins on ``net``."""
    by_ref = {p.get("ref"): p for p in ctx.parts if isinstance(p, dict)}
    insts = {i.ref: i for i in ctx.instances}
    out = []
    for ref, pin in (ctx.nets.get(net) or {}).get("pins", []):
        if ref == inst.ref:
            continue
        other = insts.get(ref)
        if other is not None:
            out.append((ref, pin, _pin_signal(other, pin), None))
        else:
            out.append((ref, pin, None, _part_kind(by_ref.get(ref) or {})))
    return out


def _gpios(ctx: modcheck.Ctx, net: str, modes: frozenset[str]) -> list[int]:
    info = ctx.nets.get(net) or {}
    return [g for g, m in zip(info.get("gpios", []), info.get("modes", []), strict=False) if m in modes]


@rule("mod.iox.mcp23017_gpx7_output")
def mcp23017_gpx7_output(ctx: modcheck.Ctx) -> list[modcheck.Finding]:
    rid = "mod.iox.mcp23017_gpx7_output"
    out: list[modcheck.Finding] = []
    for inst in ctx.instances:
        pins = OUTPUT_ONLY.get(inst.module_id)
        if not pins:
            continue
        used, ok = [], []
        for pin in pins:
            net = inst.conn.get(pin)
            if not net:
                continue
            why = []
            if net in ctx.rails:
                why.append(f"tied to rail {net}")
            why += [f"driven by GPIO{g}" for g in _gpios(ctx, net, DRIVING_MODES)]
            for ref, opin, sig, kind in _others_on(ctx, inst, net):
                if sig in DRIVING_SIGNALS:
                    why.append(f"driven by {ref}.{opin} ({sig})")
                elif kind in SWITCH_KINDS:
                    why.append(f"read from {ref} ({kind})")
            (used if why else ok).append((pin, net, why))
        for pin, net, why in used:
            out.append(ctx.finding(
                rid, "failed", "info",
                f"{ctx.label(inst)}: {pin} (net {net}) is used as an input ({'; '.join(why)}), but {pin} is output "
                f"only in the current {inst.module_id.upper()} datasheet. Move the input to another pin.",
                inst, source_id=ctx.src(inst)))
        if ok and not used:
            out.append(Finding(rid, "passed", None,
                               f"{ctx.label(inst)}: {', '.join(p for p, _, _ in ok)} used as output only.", [inst.ref]))
    return out


@rule("mod.iox.pcf8574_quasi_bidir")
def pcf8574_quasi_bidir(ctx: modcheck.Ctx) -> list[modcheck.Finding]:
    """One finding per expander: port pins with a current load (LED, transistor, relay, buzzer) -> one info listing
    them; port pins that only drive module logic inputs (high-impedance CMOS) are fine with the weak high -> passed."""
    rid = "mod.iox.pcf8574_quasi_bidir"
    out: list[modcheck.Finding] = []
    for inst in ctx.instances:
        prefix = QUASI.get(inst.module_id)
        if not prefix:
            continue
        loads, inputs, plain = [], [], []
        for pin, net in sorted(inst.conn.items(), key=lambda kv: _port_order(kv[0], prefix)):
            if not (pin.startswith(prefix) and pin[len(prefix):].isdigit()) or net in ctx.rails:
                continue
            cur, logic = [], []
            for ref, opin, sig, kind in _others_on(ctx, inst, net):
                if kind in LOAD_KINDS:
                    cur.append(f"{ref} ({kind})")
                elif sig in INPUT_SIGNALS:
                    logic.append(f"{ref}.{opin} ({sig})")
            if cur:
                loads.append((pin, net, cur))
            elif logic:
                inputs.append((pin, net, logic))
            else:
                plain.append(pin)
        if loads:
            shown = [f"{pin} (net {net}) → {', '.join(hits)}" for pin, net, hits in loads[:MAX_LISTED]]
            more = f" and {len(loads) - MAX_LISTED} more" if len(loads) > MAX_LISTED else ""
            pins = "/".join(p for p, _, _ in loads[:MAX_LISTED])
            out.append(ctx.finding(
                rid, "failed", "info",
                f"{ctx.label(inst)}: {len(loads)} port pin(s) drive a current load: {'; '.join(shown)}{more}. The port is "
                f"quasi-bidirectional: high is only a weak current source (about 30–300 µA), low sinks up to 25 mA. "
                f"Wire loads active-low (supply → load → {pins}) or add a driver transistor.",
                inst, source_id=ctx.src(inst)))
        elif inputs:
            pins = ", ".join(p for p, _, _ in inputs)
            out.append(Finding(rid, "passed", None,
                               f"{ctx.label(inst)}: {pins} drive logic inputs only (e.g. {inputs[0][2][0]}); the weak "
                               "quasi-bidirectional high is enough for high-impedance CMOS inputs.", [inst.ref]))
        elif plain:
            out.append(Finding(rid, "passed", None,
                               f"{ctx.label(inst)}: no load on a port pin needs high-side current.", [inst.ref]))
    return out


@rule("mod.iox.pca9685_allcall")
def pca9685_allcall(ctx: modcheck.Ctx) -> list[modcheck.Finding]:
    rid = "mod.iox.pca9685_allcall"
    out: list[modcheck.Finding] = []
    for pca in ctx.instances:
        if pca.module_id != "pca9685" or pca.ref not in ctx.placement:
            continue
        bus, seg = ctx.placement[pca.ref]
        if norm_address(pca.address) == ALLCALL:
            f = ctx.finding(
                rid, "failed", "caution",
                f"{ctx.label(pca)} is set to {ALLCALL}, its own LED All Call address (enabled at power-up). "
                f"Choose another A5–A0 setting.", pca, source_id=ctx.src(pca), chip_fact=False)
            f.supersedes = SUPERSEDES
            out.append(f)
            continue
        clash = [o for o in ctx.instances
                 if o.ref != pca.ref and o.module_id != "pca9685" and norm_address(o.address) == ALLCALL
                 and o.ref in ctx.placement and ctx.placement[o.ref][0] == bus
                 and ctx.visible(seg, ctx.placement[o.ref][1])]
        if clash:
            names = ", ".join(ctx.label(o) for o in clash)
            f = ctx.finding(
                rid, "failed", "caution",
                f"{ctx.label(pca)} answers the LED All Call address {ALLCALL} after power-up; {names} also sits at "
                f"{ALLCALL} and can see it: both answer, reads and writes there go wrong (no damage, open-drain bus). "
                f"Move the other device off {ALLCALL} (e.g. TCA9548A A0 high = 0x71) or clear MODE1.ALLCALL in "
                f"firmware before talking to it.",
                [pca, *clash], source_id=[ctx.src(pca)] + [None] * len(clash), chip_fact=False)
            f.supersedes = SUPERSEDES
            out.append(f)
        else:
            out.append(Finding(rid, "passed", None,
                               f"{ctx.label(pca)}: no other device at {ALLCALL} (LED All Call) on {bus}.", [pca.ref]))
    return out
