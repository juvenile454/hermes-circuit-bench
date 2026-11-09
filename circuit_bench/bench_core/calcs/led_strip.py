"""calc.led_strip: current, power and data level of a chain of addressable LEDs.

Part data: data/parts/pixel.json (kind ``addressable_led``), each value cited from the datasheets of
data/sources/mod-pixel.json (excerpts tests/corpus/excerpts/mod-pixel-*.txt).

- Current: I = n · (channels · I_ch · brightness + I_q). I_ch is the per-colour current of a datasheet **test
  condition** (WS2812B: 12 mA working current of the LED table; SK6812: IOUT 13 mA of the rise/fall-time test), not a
  guaranteed maximum; I_q the quiescent current per LED. brightness is the PWM duty of every colour (1 = full white).
- Power: P = V_supply · I.
- Supply: V_supply against the datasheet range (hard check for class A/A2 data).
- Data level: VIH at V_supply against the ESP's guaranteed V_OH (data/electrical) and its VDD: level shifter
  needed / recommended / not needed.
- Frame time (single-wire parts): n · bits / bit rate + reset time.
- APA102C: image-only class B datasheet, so every value is unverified and no check is hard (not_checked, info).
"""
from __future__ import annotations

from typing import Any

from .. import calckit as ck
from .. import electrical
from ..calckit import BenchError, assumption, check, envelope, warning

ACTION = "calc.led_strip"
PARTS = ("ws2812b", "sk6812", "apa102c")
KIND = "addressable_led"
CHIP_DEFAULT = "esp32s3"
HIGH_CURRENT_A = 1.0  # rule of thumb: from here on wiring, connectors and the supply need attention
MAX_COUNT = 100000
FORMULA = "I = n · (channels · I_ch · brightness + I_q); P = V_supply · I; VIH = k · V_supply (or the datasheet value)"
_EPS = 1e-9


def _part(name: object) -> dict[str, Any]:
    pid = ck.choice(name, PARTS, "part")
    rec = ck.parts.find(pid, KIND)
    if rec is None:
        raise BenchError("rule_data_missing", f"no datasheet data for {pid}", "data/parts/pixel.json is missing")
    return rec


def _chip(chip: object) -> tuple[str, dict[str, Any]]:
    cid = str(chip or CHIP_DEFAULT).lower().replace("-", "").replace("_", "").replace(" ", "")
    esp = electrical.get(cid)
    if esp is None or esp.get("voh") is None or esp.get("vdd") is None:
        raise BenchError("invalid_args", f"no output levels for chip {chip!r}",
                         "use esp32, esp32s2, esp32s3, esp32c3 or esp32c6")
    return cid, esp


def _vih(rec: dict[str, Any], vs: float) -> tuple[float, str]:
    f = rec["vih"]
    if "rel" in f:
        return f["rel"] * vs, f"{f['rel']:g} · {ck.fmt(vs, 'V')}"
    note = f" (given at {ck.fmt(f['at_vdd'], 'V')} only)" if "at_vdd" in f and abs(f["at_vdd"] - vs) > _EPS else ""
    return float(f["value"]), f"datasheet value{note}"


@ck.action(ACTION)
def led_strip(count: object, *, part: object = "ws2812b", brightness: object = 1.0, v_supply: object = 5.0,
              chip: object = CHIP_DEFAULT) -> dict[str, Any]:
    """Current and power of n addressable LEDs and whether a 3.3 V GPIO needs a level shifter."""
    rec = _part(part)
    n_f = ck.count(count, "count")
    if n_f != int(n_f) or n_f > MAX_COUNT:
        raise BenchError("invalid_args", f"count must be a whole number of LEDs up to {MAX_COUNT}, got {n_f:g}",
                         "for example count=60")
    n = int(n_f)
    b = ck.count(brightness, "brightness")
    if b > 1:
        raise BenchError("invalid_args", f"brightness is a fraction 0–1, got {b:g}", "1 = full white, 0.5 = half")
    vs = ck.num(v_supply, "V", "v_supply")
    cid, esp = _chip(chip)
    sure = rec.get("verified") is True and rec.get("class") in ("A", "A1", "A2")
    sid = rec["source_id"]
    src_ids = [sid, *esp.get("source_ids", []), ck.RULE]
    ch = int(rec["channels"])
    i_ch = float(rec["i_channel"]["value"])
    i_q = float(rec["i_quiescent"]["value"]) if rec.get("i_quiescent") else 0.0
    i_led = ch * i_ch * b + i_q
    i_tot = n * i_led
    i_dark = n * i_q
    p_tot = vs * i_tot
    tag = "" if sure else " (unverified)"

    steps = [ck.step("I_LED", f"{ch} · {ck.fmt(i_ch, 'A')} · {b:g} + {ck.fmt(i_q, 'A')}", i_led, "A"),
             ck.step("I", f"{n} · {ck.fmt(i_led, 'A')}", i_tot, "A"),
             ck.step("I_dark", f"{n} · {ck.fmt(i_q, 'A')}", i_dark, "A"),
             ck.step("P", f"{ck.fmt(vs, 'V')} · {ck.fmt(i_tot, 'A')}", p_tot, "W")]
    assum = [
        assumption("i_channel", f"{ck.fmt(i_ch, 'A')} per colour{tag}",
                   f"{rec['id']} datasheet {rec['i_channel'].get('basis', '')} ({rec['i_channel']['conditions']}); "
                   "a test condition, not a guaranteed maximum: measure your strip"),
        assumption("brightness", f"{b:g} on every colour",
                   "the average LED current scales with the PWM duty (rule of thumb); 1 = full white"),
        assumption("i_quiescent", f"{ck.fmt(i_q, 'A')} per LED" if i_q else "not in the datasheet",
                   f"{rec['id']} datasheet ({rec['i_quiescent']['conditions']})" if i_q else
                   "the dark current is not included"),
    ]
    if not sure:
        assum.append(assumption("source", "class B, image-only datasheet",
                                f"{rec['id']}: values read from the page images; hints only, nothing checked"))
    checks: list[dict[str, Any]] = []
    warns: list[dict[str, Any]] = []

    # supply range
    vdd = rec.get("vdd") or {}
    lo = vdd.get("min", {}).get("value")
    hi = vdd.get("max", {}).get("value")
    if not sure:
        checks.append(check("calc.led_strip.supply", "not_checked",
                            f"{rec['id']} supply max {ck.fmt(hi, 'V')} only from an unverified image-only datasheet"))
        if hi is not None and vs > hi + _EPS:
            warns.append(warning("led_strip_supply", "info", f"V_supply {ck.fmt(vs, 'V')} is above the {rec['id']} "
                                 f"supply max {ck.fmt(hi, 'V')} read from the datasheet image (unverified).", [sid]))
    else:
        ok = (lo is None or vs >= lo - _EPS) and (hi is None or vs <= hi + _EPS)
        rng = (f"{ck.fmt(lo, 'V')}–{ck.fmt(hi, 'V')}" if lo is not None and hi is not None
               else f"max {ck.fmt(hi, 'V')}" if hi is not None else f"min {ck.fmt(lo or 0.0, 'V')}")
        checks.append(check("calc.led_strip.supply", "passed" if ok else "failed",
                            f"V_supply {ck.fmt(vs, 'V')} {'within' if ok else 'outside'} {rng} ({rec['id']} datasheet: "
                            f"{vdd['max'].get('conditions', '')})"))
        if not ok:
            sev = "danger" if hi is not None and vs > hi + _EPS else "caution"
            warns.append(warning("led_strip_supply", sev,
                                 f"V_supply {ck.fmt(vs, 'V')} is outside the {rec['id']} supply range {rng}"
                                 + (": the LEDs can be damaged." if sev == "danger" else ": the LEDs may not work."),
                                 [sid]))

    # data level against the ESP GPIO
    vih, vih_how = _vih(rec, vs)
    voh, vgpio = float(esp["voh"]), float(esp["vdd"])
    steps.append(ck.step("VIH", vih_how, vih, "V"))
    if vih <= voh + _EPS:
        shifter, status = "not_needed", "passed"
        text = f"VIH {ck.fmt(vih, 'V')} ≤ ESP V_OH min {ck.fmt(voh, 'V')}: a GPIO drives the data input directly"
    elif vih <= vgpio + _EPS:
        shifter, status = "recommended", "failed"
        text = (f"VIH {ck.fmt(vih, 'V')} is above the guaranteed ESP V_OH min {ck.fmt(voh, 'V')}, below its "
                f"{ck.fmt(vgpio, 'V')} supply: works only by margin")
    else:
        shifter, status = "needed", "failed"
        text = f"VIH {ck.fmt(vih, 'V')} is above the {ck.fmt(vgpio, 'V')} GPIO high level: no reliable data"
    checks.append(check("calc.led_strip.level", status if sure else "not_checked",
                        f"{text} ({rec['id']} datasheet{tag}; {cid} datasheet V_OH)"))
    if shifter != "not_needed":
        warns.append(warning("led_strip_level", "caution" if sure else "info",
                             f"{text}. Level shifter {shifter}: a 5 V-supplied buffer with TTL inputs (e.g. 74AHCT125) "
                             f"between GPIO and data input{tag}.", [sid, *esp.get("source_ids", [])]))
    assum.append(assumption("v_oh", f"{ck.fmt(voh, 'V')} min at VDD {ck.fmt(vgpio, 'V')}",
                            f"{cid} datasheet DC characteristics (data/electrical); the GPIO drives the first LED"))
    if rec["id"] == "WS2812B":
        assum.append(assumption("vih", "0.63 · VDD (datasheet V6.1)",
                                "older WS2812B revisions specify 0.7 · VDD; check the revision of your LEDs"))

    # frame time (single-wire)
    t_frame = None
    if rec.get("bit_rate") and rec.get("bits_per_led") and rec.get("t_reset"):
        bits, rate, t_res = rec["bits_per_led"]["value"], rec["bit_rate"]["value"], rec["t_reset"]["value"]
        t_frame = n * bits / rate + t_res
        steps.append(ck.step("t_frame", f"{n} · {bits} bit / {ck.fmt(rate, 'Hz')} + {ck.fmt(t_res, 's')}",
                             t_frame, "s"))

    # rated power cross-check (SK6812: 0.2 W per LED)
    if rec.get("p_rated"):
        p_led = vs * i_led
        steps.append(ck.step("P_LED", f"{ck.fmt(vs, 'V')} · {ck.fmt(i_led, 'A')}", p_led, "W"))
        assum.append(assumption("p_rated", ck.fmt(rec["p_rated"]["value"], "W") + " per LED",
                                f"{rec['id']} datasheet power rating, for comparison with P_LED"))

    if i_tot >= HIGH_CURRENT_A:
        warns.append(warning("high_current", "info",
                             f"{ck.fmt(i_tot, 'A')} at full setting: use a separate 5 V supply sized for it, thick "
                             "supply wires with power fed in at several points of long strips, a fuse, and a common "
                             "GND with the ESP; do not draw it through the DevKit's USB or 5 V pin (rule of thumb).",
                             [ck.RULE]))

    result = {
        "inputs": {"part": rec["id"], "count": n, "brightness": b, "v_supply": ck.q(vs, "V"), "chip": cid},
        "part": {"id": rec["id"], "source_id": sid, "class": rec.get("class"), "verified": sure,
                 "i_channel": {**ck.q(i_ch, "A"), "basis": rec["i_channel"].get("basis"),
                               "conditions": rec["i_channel"]["conditions"]},
                 "i_quiescent": ck.q(i_q, "A") if i_q else None},
        "i_led": ck.q(i_led, "A"), "i_total": ck.q(i_tot, "A"), "i_dark": ck.q(i_dark, "A"),
        "p_total": ck.q(p_tot, "W"), "vih": ck.q(vih, "V"), "v_oh_esp": ck.q(voh, "V"),
        "level_shifter": shifter, "t_frame": ck.q(t_frame, "s") if t_frame is not None else None,
        "formula": FORMULA, "steps": steps,
    }
    summary = (f"{n} × {rec['id']} at {ck.fmt(vs, 'V')}, brightness {b:g}: {ck.fmt(i_tot, 'A')}, {ck.fmt(p_tot, 'W')} "
               f"(datasheet test condition{tag}); level shifter {shifter.replace('_', ' ')}.")
    return envelope(ACTION, summary, result, checks=checks, warnings=warns, assumptions=assum,
                    sources=ck.sources.resolve(src_ids))


ck.register("led_strip", led_strip, (("count", "int", True, None), ("part", "str", False, "ws2812b"),
                                     ("brightness", "", False, 1.0), ("v_supply", "V", False, 5.0),
                                     ("chip", "str", False, CHIP_DEFAULT)),
            title="Addressable LED strip current and level", group="light",
            summary="Current and power of n WS2812B/SK6812/APA102C LEDs at a brightness, and whether a 3.3 V GPIO "
                    "needs a level shifter.")
