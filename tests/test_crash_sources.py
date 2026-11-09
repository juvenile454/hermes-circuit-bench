"""Crash decoder sources: every interpretation and warning cites data/sources/, and the quoted evidence is in the pinned text.

Corpus tests read the pinned ESP-IDF v6.1 files from tests/.corpus (manifest tests/corpus/crash.json, fetched with
scripts/fetch_corpus.py crash) and skip when they are missing.
"""
from __future__ import annotations

import html
import json
import re
from pathlib import Path

import pytest

from circuit_bench.bench_core import crash, sources

ROOT = Path(__file__).resolve().parent.parent
CORPUS = ROOT / "tests" / ".corpus"
FE_IDS = ("idf-v6.1-fatal-errors", "idf-v6.1-fatal-errors-esp32", "idf-v6.1-fatal-errors-esp32c3")
# source id -> pinned file holding its text (paths below tests/.corpus/esp-idf/v6.1 unless they start with riscv/)
CORPUS_FILES = {
    "riscv-isa-unpriv-rv32": "riscv/isa-v20260120/unpriv/rv32.html",
    "fe": "docs/en/api-guides/fatal-errors.rst",
    "idf-v6.1-wdts": "docs/en/api-reference/system/wdts.rst",
    "idf-v6.1-error-handling": "docs/en/api-guides/error-handling.rst",
    "idf-v6.1-idf-monitor": "docs/en/api-guides/tools/idf-monitor.rst",
    "idf-v6.1-app-image-format": "docs/en/api-reference/system/app_image_format.rst",
    "idf-v6.1-src-panic": "components/esp_system/panic.c",
    "idf-v6.1-src-app-desc": "components/esp_app_format/esp_app_desc.c",
    "idf-v6.1-src-backtrace-xtensa": "components/esp_system/port/arch/xtensa/debug_helpers.c",
    "idf-v6.1-src-panic-arch-xtensa": "components/esp_system/port/arch/xtensa/panic_arch.c",
    "idf-v6.1-src-panic-arch-riscv": "components/esp_system/port/arch/riscv/panic_arch.c",
    "idf-v6.1-src-assert": "components/esp_libc/src/assert.c",
    "idf-v6.1-src-freertos-stack-overflow": "components/freertos/FreeRTOS-Kernel/portable/xtensa/port.c",
    "idf-v6.1-src-task-wdt": "components/esp_system/task_wdt/task_wdt.c",
}
ONLINE_ONLY = {"binutils-addr2line", "elf-gabi-e-machine", "rule-of-thumb"}


def norm(text: str) -> str:
    return re.sub(r"\s+", " ", text)


def corpus(sid: str) -> str:
    rel = CORPUS_FILES[sid]
    path = CORPUS / (rel if rel.startswith("riscv/") else f"esp-idf/v6.1/{rel}")
    if not path.is_file():
        pytest.skip(f"corpus file missing: {path} (run scripts/fetch_corpus.py crash)")
    text = path.read_text(encoding="utf-8")
    return html.unescape(re.sub(r"<[^>]+>", "", text)) if path.suffix == ".html" else text


def only_blocks(rst: str, quote: str) -> list[str | None]:
    """Condition of the innermost '.. only::' block around each line that contains ``quote`` (None = no block)."""
    lines = rst.splitlines()
    out: list[str | None] = []
    for i, line in enumerate(lines):
        if norm(quote) not in norm(line):
            continue
        indent, cond = len(line) - len(line.lstrip()), None
        for prev in reversed(lines[:i]):
            pind = len(prev) - len(prev.lstrip())
            if prev.strip() and pind < indent:
                if prev.strip().startswith(".. only::"):
                    cond = prev.strip().removeprefix(".. only::").strip()
                    break
                indent = pind
                if pind == 0:
                    break
        out.append(cond)
    assert out, f"quote not on one line: {quote!r}"
    return out


def test_crash_sources_file_is_well_formed():
    entries = json.loads((ROOT / "circuit_bench" / "data" / "sources" / "crash.json").read_text(encoding="utf-8"))
    ids = [e["id"] for e in entries]
    assert len(ids) == len(set(ids))
    for e in entries:
        assert e["url"].startswith("https://"), e
        assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", e["retrieved"]), e
        assert sources.get(e["id"])["url"] == e["url"]
    for e in entries:
        if "/blob/" in e["url"]:  # GitHub source links are pinned to the v6.1 tag commit
            assert "/blob/fff9895c82d744c7237be8847347bdd1b07c6643/" in e["url"], e["id"]
    for sid in ("idf-v6.1-src-panic", "idf-v6.1-src-app-desc"):
        assert "unverified" in sources.get(sid)["note"]


def test_every_rule_and_warning_cites_a_known_source():
    for name, rule in crash.RULES.items():
        ids = FE_IDS if rule["src"] == "fe" else (rule["src"],)
        for sid in ids:
            sources.get(sid)
        assert rule["evidence"], name
    for code, spec in crash.WARNING_EVIDENCE.items():
        for sid in spec:
            for real in (FE_IDS if sid == "fe" else (sid,)):
                sources.get(real)
        assert spec, code
    assert set(CORPUS_FILES) | ONLINE_ONLY >= {r["src"] for r in crash.RULES.values()}
    assert crash._fe_source("riscv", None) == "idf-v6.1-fatal-errors-esp32c3"
    assert crash._fe_source("xtensa", "esp32") == "idf-v6.1-fatal-errors-esp32"
    assert crash._fe_source("xtensa", "esp32s3") == "idf-v6.1-fatal-errors"
    assert crash._fe_source(None, None) == "idf-v6.1-fatal-errors"


@pytest.mark.corpus
def test_rule_evidence_is_quoted_from_the_pinned_text():
    for name, rule in crash.RULES.items():
        text = norm(corpus(rule["src"]))
        evidence = rule["evidence"]
        quotes = [q for qs in evidence.values() for q in qs] if isinstance(evidence, dict) else evidence
        for q in quotes:
            assert norm(q) in text, f"{name}: {q!r}"
    for code, spec in crash.WARNING_EVIDENCE.items():
        for sid, quotes in spec.items():
            text = norm(corpus(sid))
            for q in quotes:
                assert norm(q) in text, f"{code}: {q!r}"


@pytest.mark.corpus
def test_architecture_specific_evidence_sits_in_the_right_only_block():
    rst = corpus("fe")
    for name, rule in crash.RULES.items():
        if not isinstance(rule["evidence"], dict):
            continue
        for arch, quotes in rule["evidence"].items():
            want = {"xtensa": "CONFIG_IDF_TARGET_ARCH_XTENSA", "riscv": "CONFIG_IDF_TARGET_ARCH_RISCV"}[arch]
            for q in quotes:
                assert set(only_blocks(rst, q)) == {want}, f"{name}/{arch}: {q!r}"
    # Xtensa-only and RISC-V-only rules
    for rule, want in (("instr_fetch_prohibited", "CONFIG_IDF_TARGET_ARCH_XTENSA"),
                       ("load_store_error", "CONFIG_IDF_TARGET_ARCH_XTENSA"),
                       ("access_fault", "CONFIG_IDF_TARGET_ARCH_RISCV"),
                       ("instruction_address_misaligned", "CONFIG_IDF_TARGET_ARCH_RISCV")):
        assert set(only_blocks(rst, crash.RULES[rule]["evidence"][0])) == {want}, rule


@pytest.mark.corpus
def test_cause_tables_equal_the_panic_handler_source():
    def table(sid: str) -> list[str | None]:
        src = corpus(sid)
        body = re.search(r"static const char \*reason\[\] = \{(.*?)\};", src, re.S)
        assert body
        return [None if t == "NULL" else t.strip('"') for t in re.findall(r'"[^"]*"|NULL', body[1])]

    assert table("idf-v6.1-src-panic-arch-xtensa") == list(crash.XTENSA_EXCCAUSE)
    assert table("idf-v6.1-src-panic-arch-riscv") == list(crash.RISCV_MCAUSE)


@pytest.mark.corpus
def test_ubsan_table_and_reset_names_follow_the_docs():
    rst = norm(corpus("fe"))
    for name, meaning in crash.UBSAN_TYPES.items():
        assert f"``{name}``" in rst
        assert norm(meaning) in rst
    subst = re.search(r"\{IDF_TARGET_RTCWDT_RTC_RESET:([^}]*)\}", corpus("fe"))
    assert subst
    names = set(re.findall(r'=\s*"([A-Z_]+)"', subst[1]))
    assert names == crash._RTC_WDT_RESET_NAMES
    assert "rst:0x10 ({IDF_TARGET_RTCWDT_RTC_RESET})" in corpus("fe")


@pytest.mark.corpus
def test_log_formats_the_parser_relies_on():
    fe = corpus("fe")
    assert "Guru Meditation Error: Core  0 panic'ed (Breakpoint). Exception was unhandled." in fe
    assert "Brownout detector was triggered" in fe
    assert "Stack smashing protect failure!" in fe
    assert "Undefined behavior of type out_of_bounds" in fe
    assert "Debug exception reason: Stack canary watchpoint triggered (task_name)" in fe
    assert 'panic_print_str("Guru Meditation Error: Core ");' in corpus("idf-v6.1-src-panic")
    assert 'panic_print_str(" panic\'ed (");' in corpus("idf-v6.1-src-panic")
    assert 'panic_print_str("Rebooting...\\r\\n");' in corpus("idf-v6.1-src-panic")
    assert 'print_str("\\r\\n\\r\\nBacktrace:", panic);' in corpus("idf-v6.1-src-backtrace-xtensa")
    assert '#define ERR_STR2 " has been detected."' in corpus("idf-v6.1-src-freertos-stack-overflow")
    assert 'ESP_EARLY_LOGI(TAG, "ELF file SHA256:  %s...", buf);' in corpus("idf-v6.1-src-app-desc")
    wdt = corpus("idf-v6.1-src-task-wdt")
    assert '"The following tasks/users did not reset the watchdog in time:"' in wdt
    assert 'ESP_EARLY_LOGE(TAG, " - %s%s", name, cpu);' in wdt
    assert 'ESP_EARLY_LOGE(TAG, "CPU %d: %s"' in wdt
    eh = corpus("idf-v6.1-error-handling")
    assert 'ESP_ERROR_CHECK failed: esp_err_t 0x107 (ESP_ERR_TIMEOUT) at 0x400d1fdf' in eh
    assert 'file: "/Users/user/esp/example/main/main.c" line 20' in eh
    mon = corpus("idf-v6.1-idf-monitor")
    assert "{IDF_TARGET_TOOLCHAIN_PREFIX}-addr2line " + " ".join(crash.ADDR2LINE_ARGS) + " build/PROJECT.elf ADDRESS" in mon
    assert "(inlined by) inner_dont_crash at" in mon
    assert "abort() was called at PC 0x42067cd5 on core 0" in mon


@pytest.mark.corpus
def test_github_line_ranges_cover_the_cited_code():
    checks = {
        "idf-v6.1-src-panic": 'panic_print_str("\\r\\nELF file SHA256: ");',
        "idf-v6.1-src-app-desc": '"ELF file SHA256:  %s..."',
        "idf-v6.1-src-backtrace-xtensa": '" |<-CORRUPTED"',
        "idf-v6.1-src-panic-arch-xtensa": '"LoadProhibited", "StoreProhibited"',
        "idf-v6.1-src-panic-arch-riscv": '"Store access fault"',
        "idf-v6.1-src-assert": '"assert failed: "',
        "idf-v6.1-src-freertos-stack-overflow": '"***ERROR*** A stack overflow in task "',
        "idf-v6.1-src-task-wdt": '"Task watchdog got triggered. "',
    }
    for sid, needle in checks.items():
        url = sources.get(sid)["url"]
        m = re.search(r"#L(\d+)-L(\d+)$", url)
        assert m, url
        lines = corpus(sid).splitlines()[int(m[1]) - 1: int(m[2])]
        assert needle in "\n".join(lines), sid
