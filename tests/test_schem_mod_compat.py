"""The four old blocks stay byte-identical with the multi-GPIO
contract. Every case renders the whole envelope (SVG, nets, parts, wiring, labels, summary, checks, warnings,
assumptions, sources); its SHA-256 over ``json.dumps(env, sort_keys=True)`` was recorded before the
multi-GPIO blocks changed schematic.py and wiring.py.

Regenerate (only if an old block is changed on purpose, never to make this test pass):
    python tests/test_schem_mod_compat.py   # prints the table for SNAPSHOTS
"""
from __future__ import annotations

import hashlib
import itertools
import json

import pytest

from circuit_bench.bench_core import schematic

pytest.importorskip("schemdraw")

S3 = "esp32-s3-devkitc-1"
C3 = "esp32-c3-devkitm-1"
LONG = "W" * 24
OLD = ("led", "npn_low_side", "button_pullup", "divider")
REQUIRED = {"led": {"r_series": "4k7"}, "npn_low_side": {"r_base": "4k7"}, "button_pullup": {},
            "divider": {"r1": "4k7", "r2": "4k7"}}
CHOICES = {"led": {"active": ("high", "low")}, "npn_low_side": {"supply": ("5V", "3V3")}}
LONGS = {
    "led": {"r_series": "1.234M", "led": LONG, "net": "N" * 24},
    "npn_low_side": {"r_base": "1.234M", "r_pulldown": "1.234M", "transistor": LONG, "load": LONG, "net": "N" * 24},
    "button_pullup": {"r_pullup": "1.234M", "button": LONG, "net": "N" * 24},
    "divider": {"r1": "1.234M", "r2": "1.234M", "v_in": 12.5, "source": LONG, "input_net": "O" * 24,
                "net": "N" * 24},
}
WHERE = {"j1": (S3, 14), "j3": (S3, 48), "c3": (C3, 4), "bare": (None, None), "gpio_only": (None, 5)}


def _project() -> dict:
    def a(role, mode, pin, net):
        return {"role": role, "mode": mode, "pin": pin, "net": net, "verdict": "ok", "rule_ids": [],
                "updated_by": "agent"}
    return {"id": "bench-x", "board": {"chip": "esp32s3", "module": "wroom-1", "variant": "n16r8", "devkit": S3,
                                       "detected": None},
            "assignments": [a("LASER", "out", 14, "LASER_EN"), a("KEY", "in_pullup", 2, None),
                            a("VBAT", "adc", 1, "VBAT_DIV")], "parts": [], "options": {}}


def cases() -> dict[str, tuple[str, dict, dict]]:
    """name -> (block, params, keyword arguments of schematic.render)."""
    out: dict[str, tuple[str, dict, dict]] = {}
    for block in OLD:
        names = list(CHOICES.get(block, {}))
        combos = itertools.product(*(CHOICES[block][n] for n in names)) if names else [()]
        for combo in combos:
            choice = dict(zip(names, combo, strict=True))
            for size, extra in (("short", {}), ("long", LONGS[block])):
                for where, (devkit, gpio) in WHERE.items():
                    tag = "-".join(f"{k}={v}" for k, v in choice.items()) or "plain"
                    out[f"{block}:{tag}:{size}:{where}"] = (block, {**REQUIRED[block], **choice, **extra},
                                                             {"devkit": devkit, "gpio": gpio})
    proj = _project()
    out["npn:role"] = ("npn_low_side", {"r_base": "1k", "load": "laser module"}, {"project": proj, "role": "LASER"})
    out["button:role_no_net"] = ("button_pullup", {}, {"project": proj, "role": "KEY"})
    out["divider:role"] = ("divider", {"r1": "100k", "r2": "47k"}, {"project": proj, "role": "VBAT"})
    out["led:role_gpio_differs"] = ("led", {"r_series": 220}, {"project": proj, "role": "LASER", "gpio": 4})
    out["led:gpio_text"] = ("led", {"r_series": "220R"}, {"devkit": S3, "gpio": "GPIO4"})
    # error envelopes stay the same too
    out["err:unknown_block"] = ("relay", {}, {})
    out["err:missing"] = ("led", {}, {})
    out["err:unknown_param"] = ("led", {"r_series": 150, "colour": "red"}, {})
    out["err:pin"] = ("npn_low_side", {"r_base": 1000}, {"devkit": S3, "gpio": 26})
    out["err:board"] = ("npn_low_side", {"r_base": 1000}, {"devkit": "no-such-board", "gpio": 14})
    out["err:gpio"] = ("npn_low_side", {"r_base": 1000}, {"gpio": 99})
    out["err:role"] = ("led", {"r_series": 150}, {"project": proj, "role": "NOPE"})
    return out


def digest(env: dict) -> str:
    return hashlib.sha256(json.dumps(env, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:20]


def _hint_free(env: dict) -> dict:
    """The unknown-block error lists the blocks in its hint; that list grows with module/level_shifter."""
    if not env.get("ok") and str((env.get("error") or {}).get("hint") or "").startswith("blocks: "):
        env = json.loads(json.dumps(env))
        env["error"]["hint"] = "blocks: …"
    return env


SNAPSHOTS: dict[str, str] = {  # generated on the base tag modules-m0 with the old schematic.py/wiring.py
    # the four divider:plain:long:* hashes (6.25 V on a GPIO) were regenerated when the pin-limit check was added
    'button:role_no_net': 'fd9a353402197fed48b9',
    'button_pullup:plain:long:bare': '370925c3202882bc80af',
    'button_pullup:plain:long:c3': '64b73cd1b440f14bed5f',
    'button_pullup:plain:long:gpio_only': '7fa3feda554202d2ad1a',
    'button_pullup:plain:long:j1': '54dd3beffce48573c761',
    'button_pullup:plain:long:j3': 'b4e8857b1202413f68a3',
    'button_pullup:plain:short:bare': 'cc9e9aade8196ec51fd0',
    'button_pullup:plain:short:c3': '3f0bace3d3fc66809ac8',
    'button_pullup:plain:short:gpio_only': 'dce88a2fb8e98a98d77e',
    'button_pullup:plain:short:j1': 'b847e560bf62617b5761',
    'button_pullup:plain:short:j3': '53c57a0a1bdd99209810',
    'divider:plain:long:bare': '1c22b18673dc78338be1',
    'divider:plain:long:c3': 'b0b7270a30fe707d8f32',
    'divider:plain:long:gpio_only': '27ae88b5121033da5a48',
    'divider:plain:long:j1': 'e7ff634a473a42386c61',
    'divider:plain:long:j3': '5c096285e6d29f5e0271',
    'divider:plain:short:bare': '3865cbb2dff0399b00f2',
    'divider:plain:short:c3': '17b96013f172664979f4',
    'divider:plain:short:gpio_only': '00a1952c81797e3bd93d',
    'divider:plain:short:j1': 'e1e34a732a80be337d5c',
    'divider:plain:short:j3': '3afe0e9e94f15e74a09c',
    'divider:role': '1057a39d1969624fac5a',
    'err:board': 'd59a197aeba3f78b2606',
    'err:gpio': '09cbe9a613054bb04d75',
    'err:missing': '722ff725d9580ad050dc',
    'err:pin': '2f3310525f106fab2b38',
    'err:role': 'fad5446993b80ff19895',
    'err:unknown_block': '0fe0ce6b6c3a7f96d557',
    'err:unknown_param': '2757516a71526f5d11aa',
    'led:active=high:long:bare': '948a97d0370bbdc1d8fd',
    'led:active=high:long:c3': 'b1e1d30f964eb362ed56',
    'led:active=high:long:gpio_only': '6901591585feaa65fd63',
    'led:active=high:long:j1': 'fa48c80d806002f35944',
    'led:active=high:long:j3': 'd5ec88d2ee8f098a4998',
    'led:active=high:short:bare': '01967d9742a7b856e9ac',
    'led:active=high:short:c3': 'b0a575ecd1a23b0d88bf',
    'led:active=high:short:gpio_only': 'f1de74710887e5e3de04',
    'led:active=high:short:j1': '3b8386c93f2b5a2cf16e',
    'led:active=high:short:j3': '40047c91ce6a5575f7a9',
    'led:active=low:long:bare': '299c4843b0ec29608542',
    'led:active=low:long:c3': 'be543511677cfcb32d43',
    'led:active=low:long:gpio_only': '254b4fcf1a0b887ec65f',
    'led:active=low:long:j1': '142d4bcb77329c00fca8',
    'led:active=low:long:j3': '29ffcc2ff26535e20044',
    'led:active=low:short:bare': '587cb803c55d2ccf7c97',
    'led:active=low:short:c3': '207a3d85ee8c92114c5e',
    'led:active=low:short:gpio_only': 'e44fa129e150a4faffe4',
    'led:active=low:short:j1': '8a1958a6c5567c7037eb',
    'led:active=low:short:j3': 'ae4f49eff4c7369c17a4',
    'led:gpio_text': '56ed7d75d1503f667096',
    'led:role_gpio_differs': '82f628d41a4a4b335ce3',
    'npn:role': '278f61dd307f5cef28b2',
    'npn_low_side:supply=3V3:long:bare': 'afe6e654d05a1d69fb57',
    'npn_low_side:supply=3V3:long:c3': 'd3f3d9dfab323fcfc124',
    'npn_low_side:supply=3V3:long:gpio_only': '7f0e3058ac429a56da67',
    'npn_low_side:supply=3V3:long:j1': '3a65f245ac29552a5041',
    'npn_low_side:supply=3V3:long:j3': '6feea1e66579387f6128',
    'npn_low_side:supply=3V3:short:bare': '011596deac2f04667718',
    'npn_low_side:supply=3V3:short:c3': '5a75c32f291a004470be',
    'npn_low_side:supply=3V3:short:gpio_only': 'b00dba9a682c50a8259c',
    'npn_low_side:supply=3V3:short:j1': '9b56befe4effbb290b9c',
    'npn_low_side:supply=3V3:short:j3': '1b56bdbfe9e54a3219b8',
    'npn_low_side:supply=5V:long:bare': '57a1a78428a14cefe179',
    'npn_low_side:supply=5V:long:c3': '9452f2efca12446195ac',
    'npn_low_side:supply=5V:long:gpio_only': '87e4732598a934a0b6c9',
    'npn_low_side:supply=5V:long:j1': '2a618602b0a9a5a4f2c7',
    'npn_low_side:supply=5V:long:j3': '90822bc34ecf850ec8b7',
    'npn_low_side:supply=5V:short:bare': '1cfadfb42614fd83b540',
    'npn_low_side:supply=5V:short:c3': 'cbda320c8c2bc4281015',
    'npn_low_side:supply=5V:short:gpio_only': '9ecb8ca1b4908c30c17c',
    'npn_low_side:supply=5V:short:j1': '2112cb148dd60bdd630b',
    'npn_low_side:supply=5V:short:j3': '3aac2803117cb50d0f00',
}


def test_cases_cover_every_old_block_choice_and_size():
    names = cases()
    assert len(names) >= 70
    assert {c[0] for c in names.values()} >= set(OLD)
    assert set(SNAPSHOTS) == set(names)


@pytest.mark.parametrize("name", sorted(cases()))
def test_old_blocks_are_byte_identical(name):
    block, params, kw = cases()[name]
    env = _hint_free(schematic.render(block, params, **kw))
    assert digest(env) == SNAPSHOTS[name], (name, env.get("summary") or env.get("error"))


def test_unknown_block_hint_names_the_new_blocks():
    env = schematic.render("relay", {})
    assert env["error"]["hint"] == "blocks: " + ", ".join(schematic.BLOCKS)
    assert schematic.BLOCKS[:4] == OLD and schematic.BLOCKS[4:] == ("module", "level_shifter")


if __name__ == "__main__":
    for key, (blk, prm, kws) in sorted(cases().items()):
        print(f"    {key!r}: {digest(_hint_free(schematic.render(blk, prm, **kws)))!r},")
