"""Found by the 07-modules screenshot: POST /pins/check accepts the body the desktop sends for a project with modules
(desktop-src/25-store.js runChecks + lib/modules.js modCheckExtras: board fields, assignments with nets, parts,
options). The route refused it with ``unknown field(s): options, parts``, so the real app never showed // buses."""
from __future__ import annotations

import test_api_support as sup  # noqa: F401
from test_api_support import *  # noqa: F403

DEMO_ASSIGN = [{"role": "SDA", "mode": "i2c_sda", "pin": 8, "net": "SDA0"},
               {"role": "SCL", "mode": "i2c_scl", "pin": 9, "net": "SCL0"}]
DEMO_MODULES = [  # the I²C part of tests/test_api_fixtures.py MODULES_DEMO: DS3231 and MPU-6050 (AD0 low) share 0x68
    {"module": "ds3231", "conn": {"SDA": "SDA0", "SCL": "SCL0", "VCC": "3V3", "GND": "GND"}},
    {"module": "mpu6050", "conn": {"SDA": "SDA0", "SCL": "SCL0", "AD0": "GND", "VDD": "3V3", "GND": "GND"}},
]


def _desktop_body(p: dict) -> dict:
    b = p["board"]
    return {"chip": b["chip"], "variant": b["variant"], "wifi": p["options"]["wifi"], "devkit": b["devkit"],
            "assignments": [{k: a[k] for k in ("role", "mode", "pin", "net")} for a in p["assignments"]],
            "parts": p["parts"], "options": p["options"]}


def test_pins_check_takes_the_desktop_body_with_parts_and_options(api):
    api.ok(api.post("/projects", {"id": "e35-mod", "title": "E35", "chip": "esp32s3", "variant": "n16r8",
                                  "devkit": "esp32-s3-devkitc-1"}))
    api.apply("e35-mod", *[{"op": "assign", **a} for a in DEMO_ASSIGN], *[{"op": "add_module", **m} for m in DEMO_MODULES])
    p = api.ok(api.get("/projects/e35-mod"))["result"]["project"]
    env = api.ok(api.post("/pins/check", _desktop_body(p)))
    assert env["result"]["modules"]["counts"]["modules"] == 2
    assert any(w["code"] == "mod_address_conflict" for w in env["warnings"])
    # the explicit (unsaved) view wins over the stored project, as in pins_check
    env2 = api.ok(api.post("/pins/check", {**_desktop_body(p), "parts": [], "project": "e35-mod"}))
    assert not any(w["code"] == "mod_address_conflict" for w in env2["warnings"])


def test_pins_check_still_refuses_unknown_fields(api):
    r = api.post("/pins/check", {"chip": "esp32s3", "assignments": [{"role": "LED", "mode": "out", "pin": 4}], "bom": []})
    assert r.status_code == 400 and r.json()["error"]["code"] == "invalid_args"
