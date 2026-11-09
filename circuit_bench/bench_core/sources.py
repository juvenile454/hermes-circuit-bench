"""Cited sources: data/sources/*.json, ids globally unique.

Optional field ``class`` (modspec.SOURCE_CLASSES). In ``data/sources/mod-<family>.json``
(module catalog) it is required and every id starts with ``mod-<family>-``.
"""
from __future__ import annotations

import json
from collections.abc import Iterable
from functools import lru_cache
from pathlib import Path
from typing import Any

from . import modspec
from .contracts import BenchError

SOURCES_DIR = Path(__file__).resolve().parent.parent / "data" / "sources"
_KEYS = {"id", "title", "url", "retrieved", "note", "class"}


@lru_cache(maxsize=1)
def _load() -> dict[str, dict[str, Any]]:
    return load_dir(SOURCES_DIR)


def load_dir(directory: Path) -> dict[str, dict[str, Any]]:
    """Every source of ``directory/*.json`` by id; a malformed file or entry raises ValueError."""
    out: dict[str, dict[str, Any]] = {}
    for path in sorted(directory.glob("*.json")):
        entries = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(entries, list):
            raise ValueError(f"{path.name}: expected a list of sources")
        wp = path.stem.removeprefix(modspec.SOURCE_PREFIX) if path.stem.startswith(modspec.SOURCE_PREFIX) else None
        if wp is not None and not modspec.WP_RE.fullmatch(wp):
            raise ValueError(f"{path.name}: work package name {wp!r} does not match {modspec.WP_RE.pattern}")
        for e in entries:
            if not isinstance(e, dict) or not {"id", "title", "url", "retrieved"} <= e.keys() or not e.keys() <= _KEYS:
                raise ValueError(f"{path.name}: bad source entry {e!r}")
            if "class" in e and e["class"] not in modspec.SOURCE_CLASSES:
                raise ValueError(f"{path.name}: {e['id']!r}: class must be one of {modspec.SOURCE_CLASSES}")
            if wp is not None:
                if "class" not in e:
                    raise ValueError(f"{path.name}: {e['id']!r}: class is required in {modspec.SOURCE_PREFIX}*.json")
                if not str(e["id"]).startswith(f"{modspec.SOURCE_PREFIX}{wp}-"):
                    raise ValueError(f"{path.name}: {e['id']!r}: ids must start with {modspec.SOURCE_PREFIX}{wp}-")
            if e["id"] in out:
                raise ValueError(f"duplicate source id {e['id']!r} ({path.name})")
            out[e["id"]] = dict(e)
    return out


def all_sources() -> dict[str, dict[str, Any]]:
    return {k: dict(v) for k, v in _load().items()}


def get(source_id: str) -> dict[str, Any]:
    try:
        return dict(_load()[source_id])
    except KeyError:
        raise BenchError("rule_data_missing", f"unknown source id {source_id!r}",
                         "every rule needs a source in data/sources/") from None


def resolve(ids: Iterable[str]) -> list[dict[str, Any]]:
    """Source objects for ``ids`` (order kept, duplicates removed). Unknown id -> BenchError rule_data_missing."""
    seen: list[str] = []
    for i in ids:
        if i not in seen:
            seen.append(i)
    return [get(i) for i in seen]


def clear_cache() -> None:
    _load.cache_clear()
