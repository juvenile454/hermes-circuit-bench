"""Crash decoder sources: per-chip Fatal Errors pages, reset names per target, SOC-only sections, toolchain packages.

Corpus tests read the pinned files from tests/.corpus (manifests tests/corpus/crash.json, pins.json, chips.json) and
skip when they are missing.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from circuit_bench.bench_core import chips, crash, sources
from test_crash_sources import norm, only_blocks

CORPUS = Path(__file__).resolve().parent / ".corpus"
FE_RST = CORPUS / "esp-idf" / "v6.1" / "docs" / "en" / "api-guides" / "fatal-errors.rst"
ARCH_BLOCKS = {"CONFIG_IDF_TARGET_ARCH_XTENSA", "CONFIG_IDF_TARGET_ARCH_RISCV"}


def corpus(path: Path) -> str:
    if not path.is_file():
        pytest.skip(f"corpus file missing: {path} (run scripts/fetch_corpus.py)")
    return path.read_text(encoding="utf-8")


def soc_caps(chip: str) -> str:
    return corpus(CORPUS / "esp-idf" / "v6.1" / "components" / "soc" / chip / "include" / "soc" / "soc_caps.h")


def test_fatal_errors_pages_are_known_sources():
    pages = crash.fe_pages()
    assert set(pages) == set(chips.ids())
    for chip, sid in pages.items():
        src = sources.get(sid)
        assert f"/{chip}/api-guides/fatal-errors.html" in src["url"], sid
    assert set(crash.FE_PAGE_LACKS) == set(pages.values())
    for spec in crash.FE_PAGE_LACKS.values():
        assert spec <= set(crash.RULE_FE_CONDITION.values())
    for chip in chips.ids():
        sources.get(chips.get(chip)["source_ids"]["toolchain_prefix"])
        sources.get(f"idf-v6.1-soccaps-{chip}")
    sources.get("pio-esp32-8.0.0-platform-json")


def test_reset_names_cover_every_registered_chip():
    table = crash.RTC_WDT_RESET_BY_TARGET
    assert set(chips.ids()) <= set(table)
    assert table["esp32c6"] == "LP_WDT_SYS"
    assert table["esp32s2"] == "RTCWDT_RTC_RST"
    assert {table["esp32c6"], table["esp32s2"]} <= crash._RTC_WDT_RESET_NAMES
    assert crash._RTC_WDT_RESET_NAMES == set(table.values())


@pytest.mark.corpus
def test_reset_name_table_is_quoted_from_the_pinned_rst():
    rst = corpus(FE_RST)
    assert crash.RTC_WDT_RESET_SUBSTITUTION in rst.splitlines()
    assert "rst:0x10 ({IDF_TARGET_RTCWDT_RTC_RESET})" in rst


@pytest.mark.corpus
def test_soc_only_sections_match_the_rst():
    """RULE_FE_CONDITION lists exactly the rules whose evidence sits in a '.. only:: SOC_...' block."""
    rst = corpus(FE_RST)
    found: dict[str, str] = {}
    for name, rule in crash.RULES.items():
        if rule["src"] != "fe":
            continue
        ev = rule["evidence"]
        quotes = [q for qs in ev.values() for q in qs] if isinstance(ev, dict) else ev
        conds = {c for q in quotes for c in only_blocks(rst, q)} - ARCH_BLOCKS - {None}
        assert len(conds) <= 1, (name, conds)
        if conds:
            found[name] = conds.pop()
    assert found == crash.RULE_FE_CONDITION
    for code, spec in crash.WARNING_EVIDENCE.items():
        for q in spec.get("fe", []):
            assert set(only_blocks(rst, q)) - ARCH_BLOCKS - {None} == set(), code


@pytest.mark.corpus
def test_page_lacks_follow_soc_caps():
    pages = crash.fe_pages()
    for chip, sid in pages.items():
        caps = soc_caps(chip)
        lacks = {c for c in set(crash.RULE_FE_CONDITION.values())
                 if not re.search(rf"^#define {c}\s+1\b", caps, re.M)}
        assert crash.FE_PAGE_LACKS[sid] == lacks, chip
    assert "SOC_MEMPROT_SUPPORTED" in crash.FE_PAGE_LACKS[pages["esp32c6"]]
    assert "SOC_BOD_SUPPORTED" not in crash.FE_PAGE_LACKS[pages["esp32s2"]]


@pytest.mark.corpus
def test_arch_sections_of_the_new_chips():
    """S2 renders the Xtensa blocks (LoadProhibited, EXCVADDR), C6 the RISC-V blocks (Store Access Fault, MTVAL)."""
    rst = corpus(FE_RST)
    assert chips.arch("esp32s2") == "xtensa" and chips.arch("esp32c6") == "riscv"
    assert set(only_blocks(rst, "LoadProhibited, StoreProhibited")) == {"CONFIG_IDF_TARGET_ARCH_XTENSA"}
    assert set(only_blocks(rst, "Instruction Access Fault, Load Access Fault, Store Access Fault")) == {
        "CONFIG_IDF_TARGET_ARCH_RISCV"}
    assert "MEPC    : 0x420048b4  RA      : 0x420048b4" in rst
    assert "Backtrace: 0x400e14ed:0x3ffb5030 0x400d0802:0x3ffb5050" in rst
    assert norm(crash.RULES["access_fault"]["evidence"][0]) in norm(rst)


@pytest.mark.corpus
def test_toolchain_packages_of_the_pinned_platforms():
    """6.9.0 ships per-chip Xtensa toolchains, 8.0.0 the unified toolchain-xtensa-esp-elf; RISC-V is one package."""
    base = CORPUS / "platformio" / "platform-espressif32"
    old = json.loads(corpus(base / "v6.9.0" / "platform.json"))["packages"]
    new = json.loads(corpus(base / "v8.0.0" / "platform.json"))["packages"]
    assert {"toolchain-xtensa-esp32", "toolchain-xtensa-esp32s2", "toolchain-xtensa-esp32s3",
            "toolchain-riscv32-esp"} <= set(old)
    assert {"toolchain-xtensa-esp-elf", "toolchain-riscv32-esp"} <= set(new)
    assert not [p for p in new if re.fullmatch(r"toolchain-xtensa-esp32\w*", p)]
    assert f"toolchain-{crash.UNIFIED_XTENSA_PREFIX}" in new
    for chip in chips.ids():
        prefix = chips.toolchain_prefix(chip)
        if chips.arch(chip) == "xtensa":
            assert f"toolchain-{prefix.removesuffix('-elf')}" in old, chip
        else:
            assert prefix == "riscv32-esp-elf"
