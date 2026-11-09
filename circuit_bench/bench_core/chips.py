"""Chip register: data/chips.json, the one list of supported chips.

Pure JSON reading, no other bench_core imports besides contracts, so every module may import it at module level.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from .contracts import BenchError

CHIPS_FILE = Path(__file__).resolve().parent.parent / "data" / "chips.json"
ARCHES = ("xtensa", "riscv")


@lru_cache(maxsize=1)
def _load() -> dict[str, dict[str, Any]]:
    spec = json.loads(CHIPS_FILE.read_text(encoding="utf-8"))
    out: dict[str, dict[str, Any]] = {}
    for c in spec["chips"]:
        if c["id"] in out:
            raise ValueError(f"data/chips.json: duplicate chip {c['id']!r}")
        if c["arch"] not in ARCHES:
            raise ValueError(f"data/chips.json: {c['id']}: unknown arch {c['arch']!r}")
        out[c["id"]] = c
    return out


def ids() -> list[str]:
    """Chip ids in register order."""
    return list(_load())


def get(chip: str) -> dict[str, Any]:
    try:
        return json.loads(json.dumps(_load()[chip]))
    except KeyError:
        raise BenchError("unknown_chip", f"unknown chip {chip!r}", f"known chips: {', '.join(ids())}") from None


def arch(chip: str) -> str:
    return get(chip)["arch"]


def title(chip: str) -> str:
    return get(chip)["title"]


def toolchain_prefix(chip: str) -> str:
    return get(chip)["toolchain_prefix"]


def arduino_platform_min(chip: str) -> str | None:
    return get(chip)["arduino_platform_min"]


def by_esptool_name(name: str | None) -> str | None:
    """Chip id for an esptool CHIP_NAME ('ESP32-C6', 'ESP32'), else None."""
    if not name:
        return None
    for cid, c in _load().items():
        if name in c["esptool_names"]:
            return cid
    return None


def by_pio_mcu(mcu: str | None) -> str | None:
    if not mcu:
        return None
    for cid, c in _load().items():
        if c["pio_mcu"] == mcu.lower():
            return cid
    return None


def _prefixes(a: str) -> tuple[str, ...]:
    out: list[str] = []
    for c in _load().values():
        if c["arch"] == a and c["toolchain_prefix"] not in out:
            out.append(c["toolchain_prefix"])
    return tuple(out)


def xtensa_prefixes() -> tuple[str, ...]:
    return _prefixes("xtensa")


def riscv_prefixes() -> tuple[str, ...]:
    return _prefixes("riscv")


def ids_text() -> str:
    """'esp32, esp32s2, ...' for messages and schema descriptions."""
    return ", ".join(ids())


def clear_cache() -> None:
    _load.cache_clear()
