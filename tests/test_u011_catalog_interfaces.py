"""Every catalog entry (and every variant with its own pin list) that declares a bus interface lists the pins of that
bus. A part with an SPI interface but no clock pin accepts no SPI clock label and sends users to the wrong pin."""
from __future__ import annotations

from circuit_bench.bench_core import modules


def _entries():
    cat = modules.catalog()
    for mid in cat.ids():
        for vid in [None, *[v["id"] for v in cat.get(mid).get("variants") or []]]:
            yield mid, vid, cat.get(mid, vid)


def _interfaces(entry, kind):
    return [i for i in entry.get("interfaces") or [] if isinstance(i, dict) and i.get("type") == kind]


def _signals(entry):
    return {p.get("signal") for p in entry.get("pins") or []}


def test_whole_catalog_is_walked():
    entries = list(_entries())
    assert len({mid for mid, _, _ in entries}) >= 180
    assert len(entries) >= 180


def test_every_spi_entry_has_a_clock_pin_and_a_data_pin():
    bad = []
    for mid, vid, e in _entries():
        if _interfaces(e, "spi"):
            sig = _signals(e)
            if "spi_sck" not in sig or not sig & {"spi_sdi", "spi_sdo"}:
                bad.append((mid, vid, sorted(s for s in sig if str(s).startswith("spi_"))))
    assert bad == []


def test_every_i2c_entry_has_data_and_clock_pins():
    bad = []
    for mid, vid, e in _entries():
        if _interfaces(e, "i2c"):
            sig = _signals(e)
            if not {"i2c_sda", "i2c_scl"} <= sig:
                bad.append((mid, vid, sorted(s for s in sig if str(s).startswith("i2c_"))))
    assert bad == []
