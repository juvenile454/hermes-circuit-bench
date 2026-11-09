"""Synthetic module catalog for the module engine tests.

Invented parts with the structure of real ones; every value is synthetic, every source id starts with
``tst-`` and is not in data/sources. ``FakeCatalog`` duck-types modules.Catalog (has / resolve_id / get / ids /
sources) so the engine tests do not depend on the loader. ``ESP`` holds synthetic chip values in the shape of
electrical.get.
"""
from __future__ import annotations

import copy
from collections.abc import Iterable, Mapping
from typing import Any


def F(value: Any, unit: str = "V", src: str | None = None, **kw: Any) -> dict[str, Any]:
    """A synthetic belegte Zahl."""
    out = {"value": value, "unit": unit, "page": 1, "evidence": f"synthetic {value} {unit}"}
    if src:
        out["source_id"] = src
    out.update(kw)
    return out


def R(rel: float, of: str, unit: str = "V") -> dict[str, Any]:
    return {"rel": rel, "of": of, "unit": unit, "page": 1, "evidence": f"synthetic {rel} {of}"}


def _src(sid: str, cls: str, title: str) -> dict[str, Any]:
    return {"id": sid, "title": f"{title} (synthetic test source)", "url": f"https://example.invalid/{sid}.pdf",
            "retrieved": "2026-11-08", "note": "synthetic, tests only", "class": cls}


SOURCES: dict[str, dict[str, Any]] = {s["id"]: s for s in (
    _src("tst-sensor-ds", "A", "TST sensor datasheet"),
    _src("tst-breakout-ds", "A", "TST breakout chip datasheet"),
    _src("tst-oled-ds", "A2", "TST OLED controller datasheet, copy hosted by a distributor"),
    _src("tst-5v-ds", "A", "TST 5 V display datasheet"),
    _src("tst-mux-ds", "A1", "TST I2C mux datasheet (archived)"),
    _src("tst-bsensor-shop", "B", "TST light sensor shop page"),
    _src("tst-rtc-ds", "A", "TST RTC datasheet"),
    _src("tst-imu-ds", "A2", "TST IMU datasheet, copy hosted by a distributor"),
    _src("tst-esp-ds", "A", "TST ESP chip datasheet"),
)}

GND = {"name": "GND", "signal": "gnd", "tie": "GND"}

MODULES: list[dict[str, Any]] = [
    {  # bare chip with VDD/VDDIO, address select pin (like an environment sensor)
        "id": "tst_sensor", "aliases": ["tst-sensor"], "title": "TST environment sensor", "category":
        "sensor.environment", "manufacturer": "Test", "kind": "ic", "source_ids": ["tst-sensor-ds"],
        "supplies": {"VDD": {"min": F(1.71), "max": F(3.6), "abs_max": F(4.25)},
                     "VDDIO": {"min": F(1.2), "max": F(3.6), "abs_max": F(4.25)}},
        "io": {"domain": "VDDIO", "vih": R(0.8, "VDDIO"), "vil": R(0.2, "VDDIO"),
               "v_in_max": {"rel_offset": 0.3, "of": "VDDIO", "unit": "V", "page": 1, "evidence": "x"},
               "outputs": "open_drain"},
        "pins": [{"name": "SDA", "signal": "i2c_sda"}, {"name": "SCL", "signal": "i2c_scl"},
                 {"name": "SDO", "signal": "addr_select", "must_connect": True},
                 {"name": "CSB", "signal": "mode_select", "tie": "VDDIO"},
                 {"name": "VDD", "signal": "supply"}, {"name": "VDDIO", "signal": "supply", "tie": "VDD"}, GND],
        "interfaces": [{"type": "i2c", "addresses": F(["0x76", "0x77"], "bit"), "default": "0x76",
                        "select": {"pin": "SDO", "map": {"GND": "0x76", "VDDIO": "0x77"}}, "f_max_hz": F(3.4e6, "Hz")}],
        "current": {"supply": "VDD", "typ": F(0.00035, "A"), "max": F(0.000714, "A"), "sleep": F(1e-7, "A")},
    },
    {  # breakout board of a sensor chip: kind=module (facts by the user)
        "id": "tst_breakout", "title": "TST sensor breakout", "category": "sensor.environment",
        "manufacturer": "Test", "kind": "module", "source_ids": ["tst-breakout-ds"],
        "supplies": {"VIN": {"min": F(1.71), "max": F(3.6), "abs_max": F(4.25)}},
        "pins": [{"name": "VIN", "signal": "supply"}, GND, {"name": "SDA", "signal": "i2c_sda"},
                 {"name": "SCL", "signal": "i2c_scl"}, {"name": "ADR", "signal": "addr_select"}],
        "interfaces": [{"type": "i2c", "addresses": F(["0x44", "0x45"], "bit"), "default": "0x44",
                        "select": {"pin": "ADR", "map": {"GND": "0x44", "VIN": "0x45"}}}],
        "current": {"supply": "VIN", "typ": F(0.0006, "A"), "max": F(0.0015, "A")},
    },
    {  # OLED controller, class A2 source (may still back a hard rule)
        "id": "tst_oled", "title": "TST OLED 128x64", "category": "display.oled", "manufacturer": "Test",
        "kind": "ic", "source_ids": ["tst-oled-ds"],
        "supplies": {"VDD": {"min": F(1.65), "max": F(3.3), "abs_max": F(4.0)}},
        "pins": [{"name": "VDD", "signal": "supply"}, GND, {"name": "SDA", "signal": "i2c_sda"},
                 {"name": "SCL", "signal": "i2c_scl"}, {"name": "SA0", "signal": "addr_select", "tie": "GND"}],
        "interfaces": [{"type": "i2c", "addresses": F(["0x3C", "0x3D"], "bit"), "default": "0x3C",
                        "select": {"pin": "SA0", "map": {"GND": "0x3c", "VDD": "0x3d"}}, "f_max_hz": F(4e5, "Hz")}],
        "current": {"supply": "VDD", "typ": F(0.008, "A"), "max": F(0.02, "A"), "peak": F(0.03, "A")},
    },
    {  # 5 V part with push-pull outputs (generic level rules)
        "id": "tst_5v_display", "title": "TST 5 V character display", "category": "display.lcd",
        "manufacturer": "Test", "kind": "ic", "source_ids": ["tst-5v-ds"],
        "supplies": {"VCC": {"min": F(4.5), "max": F(5.5), "abs_max": F(7.0)}},
        "io": {"domain": "VCC", "vih": R(0.7, "VCC"), "voh": R(0.9, "VCC"), "outputs": "push_pull"},
        "pins": [{"name": "VCC", "signal": "supply"}, GND, {"name": "DIN", "signal": "digital_in"},
                 {"name": "DOUT", "signal": "digital_out", "output": "push_pull"}],
        "interfaces": [{"type": "digital"}],
        "current": {"supply": "VCC", "typ": F(0.002, "A"), "max": F(0.004, "A")},
    },
    {  # I²C mux with 4 channels
        "id": "tst_mux", "title": "TST 4-channel I2C mux", "category": "io.i2c_mux", "manufacturer": "Test",
        "kind": "ic", "source_ids": ["tst-mux-ds"],
        "supplies": {"VCC": {"min": F(1.65), "max": F(5.5), "abs_max": F(6.0)}},
        "pins": [{"name": "VCC", "signal": "supply"}, GND, {"name": "SDA", "signal": "i2c_sda"},
                 {"name": "SCL", "signal": "i2c_scl"}, {"name": "A0", "signal": "addr_select", "tie": "GND"},
                 *({"name": f"SD{c}", "signal": "i2c_sda"} for c in range(4)),
                 *({"name": f"SC{c}", "signal": "i2c_scl"} for c in range(4))],
        "interfaces": [{"type": "i2c", "addresses": F(["0x70", "0x71"], "bit"), "default": "0x70",
                        "select": {"pin": "A0", "map": {"GND": "0x70", "VCC": "0x71"}},
                        "mux_channels": [{"channel": str(c), "sda": f"SD{c}", "scl": f"SC{c}"} for c in range(4)]}],
        "current": {"supply": "VCC", "max": F(0.00002, "A")},
    },
    {  # only a class B source: findings are info at most
        "id": "tst_bsensor", "title": "TST light sensor board", "category": "sensor.light", "manufacturer": "Test",
        "kind": "module", "source_ids": ["tst-bsensor-shop"],
        "supplies": {"VCC": {"min": F(3.0), "max": F(3.6), "abs_max": F(4.5)}},
        "pins": [{"name": "VCC", "signal": "supply"}, GND, {"name": "SDA", "signal": "i2c_sda"},
                 {"name": "SCL", "signal": "i2c_scl"}],
        "interfaces": [{"type": "i2c", "addresses": F(["0x23"], "bit"), "default": "0x23"}],
    },
    {  # 5 V-only RTC at a fixed address
        "id": "tst_rtc", "title": "TST real-time clock", "category": "rtc", "manufacturer": "Test", "kind": "ic",
        "source_ids": ["tst-rtc-ds"],
        "supplies": {"VCC": {"min": F(4.5), "max": F(5.5), "abs_max": F(7.0)}},
        "pins": [{"name": "VCC", "signal": "supply"}, GND, {"name": "SDA", "signal": "i2c_sda"},
                 {"name": "SCL", "signal": "i2c_scl"}],
        "interfaces": [{"type": "i2c", "addresses": F(["0x68"], "bit"), "default": "0x68"}],
        "current": {"supply": "VCC", "typ": F(0.0001, "A"), "max": F(0.0002, "A")},
    },
    {  # IMU on the same address range as the RTC, with a variant
        "id": "tst_imu", "title": "TST 6-axis IMU", "category": "sensor.motion", "manufacturer": "Test", "kind": "ic",
        "source_ids": ["tst-imu-ds"],
        "supplies": {"VDD": {"min": F(2.375), "max": F(3.46), "abs_max": F(6.0)}},
        "pins": [{"name": "VDD", "signal": "supply"}, GND, {"name": "SDA", "signal": "i2c_sda"},
                 {"name": "SCL", "signal": "i2c_scl"}, {"name": "AD0", "signal": "addr_select", "tie": "GND"}],
        "interfaces": [{"type": "i2c", "addresses": F(["0x68", "0x69"], "bit"), "default": "0x68",
                        "select": {"pin": "AD0", "map": {"GND": "0x68", "VDD": "0x69"}}}],
        "current": {"supply": "VDD", "typ": F(0.0039, "A"), "max": F(0.005, "A")},
        "variants": [{"id": "lv", "title": "low-voltage variant",
                      "overrides": {"supplies": {"VDD": {"min": F(1.71), "max": F(1.89), "abs_max": F(2.5)}}}}],
    },
]

ESP: dict[str, Any] = {"chip": "esp32s3", "vdd": 3.3, "vih": 2.475, "vil": 0.825, "voh": 2.64, "vol": 0.33,
                       "v_in_max": 3.6, "vdd_abs_max": 3.6, "ioh": 0.04, "iol": 0.028,
                       "source_ids": ["tst-esp-ds"], "conditions": "synthetic, VDD 3.3 V"}


class FakeCatalog:
    """Duck-typed modules.Catalog over dicts (tests only)."""

    def __init__(self, modules: Iterable[Mapping[str, Any]] = MODULES,
                 sources: Mapping[str, Mapping[str, Any]] | None = None, wp: str = "test"):
        self.modules = {m["id"]: copy.deepcopy(dict(m)) for m in modules}
        self.sources = dict(SOURCES if sources is None else sources)
        self.wp = wp
        self.problems: list[str] = []
        self._alias = {a: m["id"] for m in self.modules.values() for a in m.get("aliases", [])}

    def ids(self) -> list[str]:
        return sorted(self.modules)

    def has(self, id_or_alias: str) -> bool:
        return id_or_alias in self.modules or id_or_alias in self._alias

    def resolve_id(self, id_or_alias: str) -> str:
        if id_or_alias in self.modules:
            return id_or_alias
        return self._alias[id_or_alias]

    def get(self, id_or_alias: str, variant: str | None = None) -> dict[str, Any]:
        m = copy.deepcopy(self.modules[self.resolve_id(id_or_alias)])
        if variant is not None:
            v = next(x for x in m.get("variants", []) if x["id"] == variant)
            m.update(copy.deepcopy(v.get("overrides", {})))
        m["_wp"] = self.wp
        m["_class"] = (self.sources.get(m["source_ids"][0]) or {}).get("class")
        return m


def catalog(*extra: Mapping[str, Any]) -> FakeCatalog:
    """The synthetic catalog, optionally with extra entries (same id replaces)."""
    mods = {m["id"]: m for m in MODULES}
    mods.update({m["id"]: m for m in extra})
    return FakeCatalog(list(mods.values()))
