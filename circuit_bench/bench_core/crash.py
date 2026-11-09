"""Crash decoder: ESP-IDF panic output -> cause, registers, frames with function and file:line, interpretation.

- ``parse(log) -> dict``: raw facts from the log (helper, no tools, never runs anything).
- ``decode(log, *, elf, chip, addr2line, cc_path, project_dir, run) -> result envelope`` (action ``crash.decode``):
  resolves the code addresses with ``<prefix>-addr2line -pfiaC -e ELF ADDR...`` (as IDF Monitor does) through ``run``
  (default ``clitools.run``; SIM and tests inject their own) and explains the crash. Every interpretation carries a
  ``source_id`` from data/sources/ (crash.json, base.json).

Chips come from the chip register (``bench_core.chips``, data/chips.json): Xtensa (ESP32, ESP32-S2, ESP32-S3) and
RISC-V (ESP32-C3, ESP32-C6); each chip has its toolchain prefix and its own Fatal Errors page. Formats follow ESP-IDF
v6.1 (Fatal Errors, Watchdogs, Error Handling, IDF Monitor) and the v6.1 sources that print them. This module does not
import ``board``: callers pass ``elf`` (for example the ELF of the project's last build), optionally ``cc_path``,
and the project's chip.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
from collections.abc import Callable, Iterable, Mapping
from pathlib import Path
from typing import Any

from . import chips, clitools, sources
from .contracts import MAX_RESULT_BYTES, BenchError, assumption, check, envelope, fail, from_error, warning

logger = logging.getLogger(__name__)

ACTION = "crash.decode"
KINDS: tuple[str, ...] = ("cpu_exception", "abort", "assert", "brownout", "task_wdt", "int_wdt", "stack_overflow",
                          "heap", "unknown")
FRAME_SOURCES: tuple[str, ...] = ("backtrace", "mepc", "ra", "stack_scan")
# Derived from the chip register (data/chips.json); kept as public names because
# tests, routes and doctor use them. chip id -> architecture, chip id -> toolchain prefix, arch -> prefixes.
CHIPS: dict[str, str] = {c: chips.arch(c) for c in chips.ids()}
TOOLCHAIN_PREFIX: dict[str, str] = {c: chips.toolchain_prefix(c) for c in chips.ids()}
_ARCH_PREFIXES: dict[str, tuple[str, ...]] = {"xtensa": chips.xtensa_prefixes(), "riscv": chips.riscv_prefixes()}
# Unified Xtensa toolchain of espressif32 8.0.0 (package toolchain-xtensa-esp-elf, source pio-esp32-8.0.0-platform-json).
# Its 14.2.0 build also ships the per-chip names (xtensa-esp32s2-elf-addr2line, ...); the unified name is only a
# fallback for Xtensa chips when no per-chip addr2line exists, stated as an assumption in the result.
UNIFIED_XTENSA_PREFIX = "xtensa-esp-elf"
ADDR2LINE_ARGS: tuple[str, ...] = ("-pfiaC", "-e")  # IDF Monitor: "<prefix>-addr2line -pfiaC -e build/PROJECT.elf ADDRESS"
ADDR2LINE_TIMEOUT_S = 30.0
MAX_LOG_CHARS = 2_000_000
MAX_BLOCK_LINES = 400
MAX_FRAMES = 24
STACK_SCAN_MAX_FRAMES = 12
STACK_SCAN_MAX_CANDIDATES = 96
# The docs say "close to zero" without a number; 4 KiB is our rule of thumb (stated as an assumption in the result).
NEAR_ZERO_LIMIT = 0x1000
# Valid data pointers per the docs: "not in 0x3fxxxxxx - 0x6xxxxxxx range" -> likely uninitialized or corrupted.
VALID_DATA_RANGE = (0x3F000000, 0x6FFFFFFF)

# EXCCAUSE -> name, as printed by the panic handler (idf-v6.1-src-panic-arch-xtensa, reason[]).
XTENSA_EXCCAUSE: tuple[str, ...] = (
    "IllegalInstruction", "Syscall", "InstructionFetchError", "LoadStoreError",
    "Level1Interrupt", "Alloca", "IntegerDivideByZero", "PCValue",
    "Privileged", "LoadStoreAlignment", "res", "res",
    "InstrPDAddrError", "LoadStorePIFDataError", "InstrPIFAddrError", "LoadStorePIFAddrError",
    "InstTLBMiss", "InstTLBMultiHit", "InstFetchPrivilege", "res",
    "InstrFetchProhibited", "res", "res", "res",
    "LoadStoreTLBMiss", "LoadStoreTLBMultihit", "LoadStorePrivilege", "res",
    "LoadProhibited", "StoreProhibited", "res", "res",
    "Cp0Dis", "Cp1Dis", "Cp2Dis", "Cp3Dis",
    "Cp4Dis", "Cp5Dis", "Cp6Dis", "Cp7Dis",
)
# MCAUSE -> name (idf-v6.1-src-panic-arch-riscv, reason[]); None = not printed by name.
RISCV_MCAUSE: tuple[str | None, ...] = (
    "Instruction address misaligned", "Instruction access fault", "Illegal instruction", "Breakpoint",
    "Load address misaligned", "Load access fault", "Store address misaligned", "Store access fault",
    "Environment call from U-mode", "Environment call from S-mode", None, "Environment call from M-mode",
    "Instruction page fault", "Load page fault", None, "Store page fault",
)

# --- interpretation rules --------------------------------------------------------------------------------------
# src "fe" = the Fatal Errors page of the chip (see _fe_source). "evidence" are verbatim quotes of the pinned source
# text (tests/corpus/crash.json); tests/test_crash_sources.py checks them. Texts are short paraphrases.
RULES: dict[str, dict[str, Any]] = {
    "illegal_instruction": {
        "src": "fe", "evidence": ["This CPU exception indicates that the instruction which was executed was not a valid instruction.",
                                  "FreeRTOS task function has returned.", "Failure to read next instruction from SPI flash.",
                                  "In C++ code, exiting from a non-void function without returning a value is considered to be an undefined behavior."],
        "text": "The CPU executed an invalid instruction. Common causes: a FreeRTOS task function returned instead of "
                "calling vTaskDelete(); the next instruction could not be read from SPI flash (flash pins reconfigured "
                "or disturbed); a non-void C++ function ended without returning a value."},
    "instr_fetch_prohibited": {
        "src": "fe", "evidence": ["Usually, this means an attempt to call a function pointer, which does not point to valid code."],
        "text": "The CPU could not fetch an instruction: the address is not in valid instruction RAM or ROM. Usually a "
                "call through a function pointer that does not point to valid code."},
    "load_prohibited": {
        "src": "fe", "evidence": ["The address which has been written/read is found in the ``EXCVADDR`` register in the register dump."],
        "text": "The program read from an invalid memory location; the address is in EXCVADDR."},
    "store_prohibited": {
        "src": "fe", "evidence": ["The address which has been written/read is found in the ``EXCVADDR`` register in the register dump."],
        "text": "The program wrote to an invalid memory location; the address is in EXCVADDR."},
    "integer_divide_by_zero": {
        "src": "fe", "evidence": ["Application has attempted to do an integer division by zero."],
        "text": "The program divided an integer by zero."},
    "load_store_alignment": {
        "src": "fe", "evidence": ["the address alignment does not match the load/store size"],
        "text": "A read or write used an address that does not match the access size (a 32-bit access needs a 4-byte "
                "aligned address, a 16-bit access a 2-byte aligned one)."},
    "load_store_error": {
        "src": "fe", "evidence": ["If the application has attempted to do an 8- or 16- bit read to, or write from, a memory region which only supports 32-bit reads/writes.",
                                  "If the application has attempted to write to a read-only memory region, such as IROM or DROM."],
        "text": "An 8- or 16-bit access to memory that supports only 32-bit access (for example a char* into IRAM or "
                "IROM), or a write to read-only memory (IROM, DROM)."},
    "debug_exception": {
        "src": "fe", "evidence": ["This CPU exception happens when the instruction ``BREAK`` is executed."],
        "text": "Unhandled debug exception (for example the BREAK instruction was executed).{detail}"},
    "instruction_address_misaligned": {
        "src": "fe", "evidence": ["This CPU exception indicates that the address of the instruction to execute is not 2-byte aligned."],
        "text": "The address of the instruction to execute is not 2-byte aligned."},
    "access_fault": {
        "src": "fe", "evidence": ["The address which was written/read is found in ``MTVAL`` register in the register dump."],
        "text": "The program tried to {verb} an invalid memory location; the address is in MTVAL."},
    "breakpoint": {
        "src": "fe", "evidence": ["This CPU exception happens when the instruction ``EBREAK`` is executed.",
                                  "Guru Meditation Error: Core  0 panic'ed (Breakpoint). Exception was unhandled."],
        "text": "The EBREAK instruction was executed. On RISC-V the FreeRTOS end-of-stack watchpoint also reports "
                "Breakpoint, so this can be a stack overflow."},
    "address_misaligned": {
        "src": "fe", "evidence": ["Application has attempted to read or write memory location, and address alignment did not match load/store size."],
        "text": "A read or write used an address that does not match the access size (a 32-bit access needs a 4-byte "
                "aligned address, a 16-bit access a 2-byte aligned one)."},
    "cache_error": {
        "src": "fe", "evidence": ["In some situations, ESP-IDF will temporarily disable access to external SPI flash and SPI RAM via caches.",
                                  "Make sure that any interrupt handlers registered with this flag have all the code and data in IRAM/DRAM."],
        "text": "Cache error. ESP-IDF disables the flash and PSRAM caches for a while, for example during SPI flash "
                "writes; interrupt handlers that run then (registered with ESP_INTR_FLAG_IRAM) must keep all code and "
                "data in IRAM/DRAM."},
    "memory_protection_fault": {
        "src": "fe", "evidence": ["writing to instruction RAM after the program is loaded",
                                  "executing code from data RAM (areas used for heap and static .data and .bss)"],
        "text": "Memory protection fault: a write to instruction RAM after loading, or code executed from data RAM."},
    "stack_protection_fault": {
        "src": "fe", "evidence": ["can watch the SP register to ensure that it is within the bounds of allocated stack memory"],
        "text": "Hardware stack guard: the stack pointer left the bounds of the task's stack (stack overflow)."},
    "int_wdt": {
        "src": "idf-v6.1-wdts", "evidence": ["has detected that interrupts have been blocked on CPU 0 for longer than the configured timeout period",
                                             "reducing the duration of long-running ISRs or critical sections, or by increasing the IWDT timeout period"],
        "text": "Interrupt watchdog timeout on CPU{cpu}: interrupts were blocked longer than the timeout, usually by a "
                "long ISR or critical section. Shorten them or raise the interrupt watchdog timeout."},
    "null_pointer_zero": {
        "code": "null_pointer", "src": "fe",
        "evidence": {"xtensa": ["If this address is zero, it usually means that the application has attempted to dereference a NULL pointer."],
                     "riscv": ["If this address is zero, it usually means that application attempted to dereference a NULL pointer."]},
        "text": "{reg} {addr}: {verb} through a NULL pointer."},
    "null_pointer_near": {
        "code": "null_pointer", "src": "fe",
        "evidence": {"xtensa": ["If this address is close to zero, it usually means that the application has attempted to access a member of a structure, but the pointer to the structure is NULL."],
                     "riscv": ["If this address is close to zero, it usually means that application attempted to access member of a structure, but the pointer to the structure was NULL."]},
        "text": "{reg} {addr}: {verb} through a NULL pointer at offset {offset} bytes."},
    "bad_pointer": {
        "src": "fe",
        "evidence": {"xtensa": ["(garbage value, not in ``0x3fxxxxxx`` - ``0x6xxxxxxx`` range), it likely means that the pointer used to access the data is either not initialized or has been corrupted."],
                     "riscv": ["(garbage value, not in ``0x3fxxxxxx`` - ``0x6xxxxxxx`` range), it likely means that the pointer used to access the data was either not initialized or was corrupted."]},
        "text": "{reg} {addr} is outside 0x3fxxxxxx-0x6xxxxxxx: the pointer is likely uninitialized or corrupted."},
    "bad_function_pointer": {
        "src": "fe", "evidence": ["it will be zero or will contain a garbage value (not ``0x4xxxxxxx``)"],
        "text": "PC {pc} is {what}: a call through a function pointer that does not point to valid code."},
    "abort": {
        "src": "fe", "evidence": ["abort() was called at PC 0x400dca43 on core 0"],
        "text": "abort() was called at PC {pc} on core {core}{where}; the backtrace shows the call chain."},
    "assert_failed": {
        "src": "idf-v6.1-src-assert", "evidence": ['#define ASSERT_STR "assert failed: "'],
        "text": "Assertion failed in {func} at {file}:{line}: {expr}."},
    "assert_failed_newlib": {
        "code": "assert_failed", "src": "fe", "evidence": ['assertion "head != NULL" failed: file'],
        "text": "Assertion failed in {func} at {file}:{line}: {expr}."},
    "esp_error_check": {
        "src": "idf-v6.1-error-handling",
        "evidence": ["If the value is not :c:macro:`ESP_OK`, :c:macro:`ESP_ERROR_CHECK` prints a detailed error message and calls ``abort()``"],
        "text": "ESP_ERROR_CHECK failed with {err} in {func} at {file}:{line} (expression: {expr}): the call returned "
                "an error and ESP_ERROR_CHECK aborted the program."},
    "heap_corrupt": {
        "src": "fe", "evidence": ["ESP-IDF's heap implementation contains a number of run-time checks of the heap structure.",
                                  'Additional checks ("Heap Poisoning") can be enabled in menuconfig.',
                                  "Consult :doc:`Heap Memory Debugging <../api-reference/system/heap_debug>` documentation"],
        "text": "A heap integrity check failed ({detail}). See ESP-IDF 'Heap Memory Debugging'; heap poisoning in "
                "menuconfig adds more checks."},
    "stack_smashing": {
        "src": "fe", "evidence": ["Check the function code for unbounded access to local arrays."],
        "text": "Stack smashing protection found a damaged stack frame. The backtrace points to the function: check it "
                "for unbounded access to local arrays."},
    "stack_canary": {
        "code": "stack_overflow", "src": "fe",
        "evidence": ["Debug exception reason: Stack canary watchpoint triggered (task_name)",
                     "one of the watchpoints is set to watch the last 32 bytes of stack",
                     "this may cause the watchpoint to be triggered up to 28 bytes earlier than expected"],
        "text": "Stack overflow in task {task}: the FreeRTOS end-of-stack watchpoint (last 32 bytes of the stack) "
                "triggered. It can fire up to 28 bytes before the real end."},
    "stack_overflow_check": {
        "code": "stack_overflow", "src": "idf-v6.1-src-freertos-stack-overflow",
        "evidence": ['#define ERR_STR1 "***ERROR*** A stack overflow in task "'],
        "text": "Stack overflow in task {task}: the FreeRTOS stack overflow hook detected it."},
    "brownout": {
        "src": "fe", "evidence": ["The brownout detector can trigger a system reset if the supply voltage goes below a safe level.",
                                  "only part of the message may be seen on the console"],
        "text": "Brownout: the supply voltage dropped below a safe level and the chip was reset. If the voltage drops "
                "fast, only part of the message reaches the console."},
    "task_wdt": {
        "src": "idf-v6.1-wdts",
        "evidence": ["Indicates that the Task Watchdog Timer (TWDT) has detected that one or more tasks have not yielded within the configured timeout period"],
        "text": "Task watchdog: {tasks} did not reset the watchdog in time{running}. Tasks did not yield, so the IDLE "
                "task could not feed the watchdog: let tasks yield, shorten long-running work or raise the timeout."},
    "task_wdt_nonfatal": {
        "src": "idf-v6.1-wdts",
        "evidence": ["On a TWDT timeout the default behaviour is to simply print a warning and a backtrace before continuing running the app.",
                     "If you want a timeout to cause a panic and a system reset then this can be configured through :ref:`CONFIG_ESP_TASK_WDT_PANIC`."],
        "text": "By default a task watchdog timeout only prints this warning and a backtrace and the app keeps running "
                "(it is fatal only with CONFIG_ESP_TASK_WDT_PANIC)."},
    "ubsan": {
        "src": "fe", "evidence": ["When UBSAN detects an error, a message and the backtrace are printed"],
        "text": "Undefined behavior sanitizer: {type} ({meaning})."},
    "rtc_wdt_reset": {
        "src": "fe", "evidence": ["If the execution time is exceeded, the RTC watchdog will restart the system.",
                                  "(9000 ms by default)",
                                  "The RTC watchdog is reconfigured in the panic handler to have a timeout of 10 seconds."],
        "text": "Reset by the RTC watchdog ({name}): start-up from the ROM bootloader to the app took too long "
                "(bootloader watchdog, 9000 ms by default), or the panic handler ran longer than 10 seconds."},
}
# UBSAN error types and their meaning, verbatim from the table in Fatal Errors (rst markup removed in the output).
UBSAN_TYPES: dict[str, str] = {
    "type_mismatch": "Incorrect pointer value: null, unaligned, not compatible with the given type.",
    "type_mismatch_v1": "Incorrect pointer value: null, unaligned, not compatible with the given type.",
    "add_overflow": "Integer overflow during addition, subtraction, multiplication, negation.",
    "sub_overflow": "Integer overflow during addition, subtraction, multiplication, negation.",
    "mul_overflow": "Integer overflow during addition, subtraction, multiplication, negation.",
    "negate_overflow": "Integer overflow during addition, subtraction, multiplication, negation.",
    "divrem_overflow": "Integer division by 0 or ``INT_MIN``.",
    "shift_out_of_bounds": "Overflow in left or right shift operators.",
    "out_of_bounds": "Access outside of bounds of an array.",
    "unreachable": "Unreachable code executed.",
    "missing_return": "Non-void function has reached its end without returning a value (C++ only).",
    "vla_bound_not_positive": "Size of variable length array is not positive.",
    "load_invalid_value": "Value of ``bool`` or ``enum`` (C++ only) variable is invalid (out of bounds).",
    "nonnull_arg": "Null argument passed to a function which is declared with a ``nonnull`` attribute.",
    "nonnull_return": "Null value returned from a function which is declared with ``returns_nonnull`` attribute.",
    "builtin_unreachable": "``__builtin_unreachable`` function called.",
    "pointer_overflow": "Overflow in pointer arithmetic.",
}
# Warnings with a documented basis: code -> (source ids, evidence quotes per source id).
WARNING_EVIDENCE: dict[str, dict[str, list[str]]] = {
    "backtrace_corrupted": {"idf-v6.1-src-backtrace-xtensa": ['print_str(" |<-CORRUPTED", panic);']},
    "backtrace_continues": {"idf-v6.1-src-backtrace-xtensa": ['print_str(" |<-CONTINUES", panic);']},
    "no_backtrace": {"fe": ["Do not print registers or backtrace, restart the chip immediately."]},
    "stack_scan_heuristic": {"idf-v6.1-src-panic-arch-riscv": ['panic_print_str("\\r\\nStack memory:\\r\\n");']},
    "ra_return_address": {"riscv-isa-unpriv-rv32": ["JAL stores the address of the instruction following the jump ('pc'+4) into register rd."]},
    "elf_mismatch": {"idf-v6.1-src-panic": ['panic_print_str("\\r\\nELF file SHA256: ");'],
                     "idf-v6.1-app-image-format": ["``app_elf_sha256``: contains SHA256 hash for the application ELF file"]},
}
_XTENSA_REASON_RULES = {
    "illegalinstruction": "illegal_instruction", "instrfetchprohibited": "instr_fetch_prohibited",
    "loadprohibited": "load_prohibited", "storeprohibited": "store_prohibited",
    "integerdividebyzero": "integer_divide_by_zero", "loadstorealignment": "load_store_alignment",
    "loadstoreerror": "load_store_error", "unhandled debug exception": "debug_exception",
    "cache error": "cache_error", "memory protection fault": "memory_protection_fault",
}
_RISCV_REASON_RULES = {
    "illegal instruction": "illegal_instruction", "instruction address misaligned": "instruction_address_misaligned",
    "instruction access fault": "access_fault", "load access fault": "access_fault", "store access fault": "access_fault",
    "breakpoint": "breakpoint", "load address misaligned": "address_misaligned",
    "store address misaligned": "address_misaligned", "cache error": "cache_error",
    "memory protection fault": "memory_protection_fault", "stack protection fault": "stack_protection_fault",
}
# RTC watchdog reset name per target: the substitution line of Fatal Errors, RTC Watchdog Timeout (verbatim from the
# pinned fatal-errors.rst; tests/test_cdebug_sources.py checks it). It prints as ``rst:0x10 (<name>)``.
RTC_WDT_RESET_SUBSTITUTION = ('{IDF_TARGET_RTCWDT_RTC_RESET:default="Not updated", esp32="RTCWDT_RTC_RESET", '
                              'esp32s2="RTCWDT_RTC_RST", esp32s3="RTCWDT_RTC_RST", esp32c3="RTCWDT_RTC_RST", '
                              'esp32c2="RTCWDT_RTC_RST", esp32c6="LP_WDT_SYS", esp32h2="LP_WDT_SYS", '
                              'esp32p4="LP_WDT_SYS"}')
RTC_WDT_RESET_BY_TARGET: dict[str, str] = dict(re.findall(r'(\w+)="([A-Z_]+)"', RTC_WDT_RESET_SUBSTITUTION))
_RTC_WDT_RESET_NAMES = set(RTC_WDT_RESET_BY_TARGET.values())
# Fatal Errors pages: source ids "idf-v6.1-fatal-errors[-<chip>]"; the chip of a page is the target in its URL.
FE_SOURCE_PREFIX = "idf-v6.1-fatal-errors"
_FE_URL_TARGET = re.compile(r"/en/[^/]+/([a-z0-9]+)/api-guides/fatal-errors\.html$")
# Rules whose evidence sits in a ``.. only:: SOC_...`` block of fatal-errors.rst: that section is only on the pages of
# targets with the capability (tests/test_cdebug_sources.py checks both tables against the pinned rst and soc_caps.h).
RULE_FE_CONDITION: dict[str, str] = {"memory_protection_fault": "SOC_MEMPROT_SUPPORTED",
                                     "stack_protection_fault": "SOC_ASSIST_DEBUG_SUPPORTED",
                                     "brownout": "SOC_BOD_SUPPORTED"}
# Fatal Errors page -> conditions of RULE_FE_CONDITION its target lacks (ESP-IDF v6.1 soc_caps.h of that target).
FE_PAGE_LACKS: dict[str, frozenset[str]] = {
    "idf-v6.1-fatal-errors": frozenset({"SOC_ASSIST_DEBUG_SUPPORTED"}),
    "idf-v6.1-fatal-errors-esp32": frozenset({"SOC_MEMPROT_SUPPORTED", "SOC_ASSIST_DEBUG_SUPPORTED"}),
    "idf-v6.1-fatal-errors-esp32s2": frozenset({"SOC_ASSIST_DEBUG_SUPPORTED"}),
    "idf-v6.1-fatal-errors-esp32c3": frozenset(),
    "idf-v6.1-fatal-errors-esp32c6": frozenset({"SOC_MEMPROT_SUPPORTED"}),
}
# Functions of the panic path itself (seen in the docs' abort/assert/UBSAN backtraces); the summary names the first
# frame outside this list. Only used for the summary text, never for an interpretation.
_PANIC_PATH = {"panic_abort", "esp_system_abort", "abort", "__assert_func", "__assert", "esp_panic_handler",
               "panic_handler", "vApplicationStackOverflowHook", "__stack_chk_fail", "_esp_error_check_failed",
               "esp_task_wdt_isr", "task_wdt_isr"}

# --- log patterns ----------------------------------------------------------------------------------------------
_ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
_TIME_PREFIX = re.compile(r"^\s*\[?\d{1,2}:\d{2}:\d{2}(?:[.,]\d+)?\]?\s*(?:->|>)?\s?")
_GURU = re.compile(r"Guru Meditation Error: Core\s+(\d+) panic'ed \(([^)]*)\)")
_ABORT = re.compile(r"abort\(\) was called at PC (0x[0-9a-fA-F]+) on core (\d+)")
_ASSERT = re.compile(r"assert failed: (\S+) (\S+):(\d+) \((.*)\)\s*$")
_ASSERT_NEWLIB = re.compile(r'assertion "(.*)" failed: file "([^"]*)", line (\d+)(?:, function: (\S+))?')
_ESP_ERR = re.compile(r"ESP_ERROR_CHECK failed: esp_err_t (0x[0-9a-fA-F]+)(?: \(([A-Za-z0-9_]+)\))?(?: at (0x[0-9a-fA-F]+))?")
_ESP_ERR_FILE = re.compile(r'^\s*file: "([^"]*)" line (\d+)')
_ESP_ERR_FUNC = re.compile(r"^\s*func: (\S+)")
_ESP_ERR_EXPR = re.compile(r"^\s*expression: (.*?)\s*$")
_BROWNOUT = re.compile(r"Brownout detector was(?: triggered)?")  # the docs warn that only part may reach the console
_TWDT = re.compile(r"Task watchdog got triggered\. The following tasks/users did not reset the watchdog in time:")
_TWDT_TASK = re.compile(r"-\s+(\S+) \((CPU [0-9/]+)\)")
_TWDT_RUNNING = re.compile(r"CPU (\d+): ([^\s,]+)")
_HEAP = re.compile(r"CORRUPT HEAP: (.*?)\s*$")
_SMASH = re.compile(r"Stack smashing protect failure!")
_SO_HOOK = re.compile(r"\*\*\*ERROR\*\*\* A stack overflow in task (.+?) has been detected\.")
_DEBUG_RSN = re.compile(r"Debug exception reason: (.*?)\s*$")
_CANARY = re.compile(r"Stack canary watchpoint triggered \(([^)]*)\)")
_UBSAN = re.compile(r"Undefined behavior of type (\w+)")
_BACKTRACE = re.compile(r"Backtrace:\s*(.*)$")
_PAIR = re.compile(r"\b(0x[0-9a-fA-F]{1,8}):(0x[0-9a-fA-F]{1,8})\b")
_REG_LINE = re.compile(r"^(?:\s*[A-Z][A-Z0-9/]*\s*:\s*0x[0-9a-fA-F]{1,8})+\s*$")
_REG = re.compile(r"([A-Z][A-Z0-9/]*)\s*:\s*(0x[0-9a-fA-F]{1,8})")
_DUMP_HEAD = re.compile(r"(?:Core\s+(\d+) )?[Rr]egister dump:")
_STACK_MEM_HEAD = re.compile(r"^\s*Stack memory:")
_STACK_MEM = re.compile(r"^\s*[0-9a-fA-F]{8}:((?:\s+0x[0-9a-fA-F]+)+)\s*$")
_WORD = re.compile(r"0x([0-9a-fA-F]+)")
_RESET = re.compile(r"rst:(0x[0-9a-fA-F]+) \(([A-Za-z0-9_]+)\)")
_ELF_SHA = re.compile(r"ELF file SHA256:\s+([0-9a-fA-F]{8,64})")
_REBOOT = re.compile(r"^\s*Rebooting\.\.\.")
_EVENTS = (_GURU, _ABORT, _ASSERT, _ASSERT_NEWLIB, _ESP_ERR, _BROWNOUT, _TWDT, _HEAP, _SMASH, _SO_HOOK, _UBSAN)
_A2L_ENTRY = re.compile(r"^(0x[0-9a-fA-F]+):\s*(.*?)\s*$")
_A2L_INLINED = re.compile(r"^\s*\(inlined by\)\s*(.*?)\s*$")
_DISCRIMINATOR = re.compile(r"\s*\(discriminator \d+\)\s*$")


# --- helpers ----------------------------------------------------------------------------------------------------
def normalize_chip(chip: str | None) -> str | None:
    """'ESP32-S3' -> esp32s3 (a chip id of the register). None stays None. Unknown chip -> BenchError unknown_chip."""
    if chip is None:
        return None
    if not isinstance(chip, str):
        raise BenchError("invalid_args", "chip must be a string")
    norm = re.sub(r"[-_\s]", "", chip.strip().lower())
    if not norm:
        return None
    if norm not in CHIPS:
        raise BenchError("unknown_chip", f"unknown chip {chip!r}", f"supported: {chips.ids_text()}")
    return norm


def _hex(n: int) -> str:
    return f"0x{n:08x}"


def _executable(p: Path) -> str | None:
    return str(p) if p.is_file() and os.access(p, os.X_OK) else None


def _pio_core_dir() -> Path:
    core = os.environ.get("PLATFORMIO_CORE_DIR")
    if core:
        return Path(core).expanduser()
    return Path(os.environ.get("HOME") or Path.home()) / ".platformio"


def _prefix_from_cc(cc_path: str) -> tuple[str, str] | None:
    """('xtensa-esp32s3-elf', '') for '.../xtensa-esp32s3-elf-gcc'; second item is an '.exe' suffix if any."""
    m = re.match(r"^(.+)-(?:gcc|g\+\+|cc|c\+\+)(\.exe)?$", Path(cc_path).name)
    return (m[1], m[2] or "") if m else None


def _package_dirs() -> list[Path]:
    """PlatformIO toolchain package folders, the active one before kept versions: ``toolchain-riscv32-esp`` before
    ``toolchain-riscv32-esp@8.4.0+2021r2-patch5`` (PlatformIO moves an older version into a ``<name>@<version>``
    folder when a newer one is installed)."""
    packages = _pio_core_dir() / "packages"
    try:
        dirs = [d for d in packages.glob("toolchain-*") if d.is_dir()]
    except OSError:
        return []
    return sorted(dirs, key=lambda d: (d.name.split("@", 1)[0], "@" in d.name, d.name))


def _find_prefix(prefix: str, suffix: str = "") -> str | None:
    name = f"{prefix}-addr2line{suffix}"
    hit = clitools.find(name)
    if hit:
        return hit
    for pkg in _package_dirs():
        hit = _executable(pkg / "bin" / name)
        if hit:
            return hit
    return None


def _is_unified(tool: str | None) -> bool:
    return bool(tool) and Path(str(tool)).name.startswith(f"{UNIFIED_XTENSA_PREFIX}-addr2line")


def _chip_for_prefix(prefix: str | None) -> str | None:
    """The chip whose toolchain prefix this is, if exactly one registered chip uses it (riscv32-esp-elf is shared)."""
    hits = [c for c, pre in TOOLCHAIN_PREFIX.items() if pre == prefix]
    return hits[0] if len(hits) == 1 else None


def find_addr2line(chip: str | None, cc_path: str | None = None) -> str | None:
    """Path of the chip's ``<prefix>-addr2line`` or None.

    Order: next to ``cc_path`` (``…-gcc`` -> ``…-addr2line``); then PATH (``clitools.find``); then PlatformIO's
    toolchain packages ``($PLATFORMIO_CORE_DIR or ~/.platformio)/packages/toolchain-*/bin/`` (espressif32 6.9.0:
    ``toolchain-xtensa-<chip>``, ``toolchain-riscv32-esp``; 8.0.0: ``toolchain-xtensa-esp-elf``,
    ``toolchain-riscv32-esp``; also kept versions ``toolchain-…@<version>``). The prefix comes from the chip register
    (``chips.toolchain_prefix``). For Xtensa chips without a per-chip addr2line the unified
    ``xtensa-esp-elf-addr2line`` is the last resort (``decode`` states it as an assumption).
    Raises BenchError unknown_chip for chips outside the register.
    """
    norm = normalize_chip(chip)
    if cc_path:
        parsed = _prefix_from_cc(str(cc_path))
        if parsed:
            prefix, suffix = parsed
            cc = Path(str(cc_path)).expanduser()
            if cc.parent != Path("."):
                hit = _executable(cc.with_name(f"{prefix}-addr2line{suffix}"))
                if hit:
                    return hit
            hit = _find_prefix(prefix, suffix)
            if hit:
                return hit
    if norm is None:
        return None
    hit = _find_prefix(TOOLCHAIN_PREFIX[norm])
    if hit is None and CHIPS[norm] == "xtensa":
        hit = _find_prefix(UNIFIED_XTENSA_PREFIX)
    return hit


def _elf_arch(path: Path) -> str | None:
    """Architecture from the ELF header (e_machine: EM_XTENSA 94, EM_RISCV 243; source elf-gabi-e-machine)."""
    try:
        with path.open("rb") as f:
            head = f.read(20)
    except OSError:
        return None
    if len(head) < 20 or head[:4] != b"\x7fELF":
        return None
    machine = int.from_bytes(head[18:20], "little" if head[5] == 1 else "big")
    return {94: "xtensa", 243: "riscv"}.get(machine)


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _clean(line: str) -> str:
    return _TIME_PREFIX.sub("", _ANSI.sub("", line), count=1).rstrip()


# --- parser -----------------------------------------------------------------------------------------------------
def _is_event(line: str) -> bool:
    return any(p.search(line) for p in _EVENTS)


# Public names of the same functions for the serial broker (serialport: block start and repeat signature).
clean_line = _clean
is_event_line = _is_event


def _is_trace(line: str) -> bool:
    if _DUMP_HEAD.search(line) or _STACK_MEM_HEAD.search(line):
        return True
    if _REG_LINE.match(line) and len(_REG.findall(line)) >= 2:  # register dump whose head line was cut off
        return True
    m = _BACKTRACE.search(line)
    return bool(m and _PAIR.search(m[1]))


def _blocks(lines: list[str]) -> list[tuple[int, int]]:
    """Crash blocks [start, end): from an event (or a stray dump/backtrace) to 'Rebooting...', the next 'rst:' line,
    the next event after a backtrace was seen, or MAX_BLOCK_LINES."""
    out: list[tuple[int, int]] = []
    i, n = 0, len(lines)
    while i < n:
        if not (_is_event(lines[i]) or _is_trace(lines[i])):
            i += 1
            continue
        start, j, traced = i, i, False
        while j < n:
            line = lines[j]
            if j > start and (_RESET.search(line) or (traced and _is_event(line))):
                break
            if _is_trace(line):
                traced = True
            j += 1
            if _REBOOT.search(line) or j - start >= MAX_BLOCK_LINES:
                break
        out.append((start, j))
        i = j
    return out


def _arch_of(p: Mapping[str, Any]) -> str | None:
    regs = p["registers"]
    if "MEPC" in regs or "MCAUSE" in regs or p["stack_words"]:
        return "riscv"
    if "EXCCAUSE" in regs or "EXCVADDR" in regs or "PS" in regs or p["debug_reason"]:
        return "xtensa"
    reason = (p["reason"] or "").lower()
    if reason in _RISCV_REASON_RULES and reason not in _XTENSA_REASON_RULES:
        return "riscv"
    if reason in _XTENSA_REASON_RULES and reason not in _RISCV_REASON_RULES:
        return "xtensa"
    return None


def parse(log: str | bytes) -> dict[str, Any]:
    """Raw facts of the first crash in ``log`` (helper; never runs tools).

    Keys: found, blocks, kind, reason, reason_inferred, core, arch, header, registers (first register dump, values as
    printed, lower case), backtrace [{pc, sp}], backtrace_end (None|'corrupted'|'continues'), stack_words (RISC-V
    'Stack memory:' words), abort {pc, core}, assert {func, file, line, expr, style}, esp_error_check {code, name, pc,
    file, line, func, expr}, debug_reason, stack_overflow_task, task_wdt {tasks: [{name, cpu}], running: [{cpu, task}]},
    heap, stack_smashing, ubsan, brownout, reset_reason {code, name, when: after_crash|before_crash|no_crash},
    elf_sha256, elf_sha256_line ('panic'|'boot'), rebooting. Raises BenchError invalid_args for non-text or oversized input.
    """
    if isinstance(log, bytes):
        log = log.decode("utf-8", errors="replace")
    if not isinstance(log, str):
        raise BenchError("invalid_args", "log must be text")
    if len(log) > MAX_LOG_CHARS:
        raise BenchError("invalid_args", f"log is too long ({len(log)} characters, limit {MAX_LOG_CHARS})",
                         "pass only the part from the crash header to 'Rebooting...'")
    lines = [_clean(x) for x in log.splitlines()]
    blocks = _blocks(lines)
    p: dict[str, Any] = {
        "found": bool(blocks), "blocks": len(blocks), "kind": "unknown", "reason": None, "reason_inferred": False,
        "core": None, "arch": None, "header": None, "registers": {}, "backtrace": [], "backtrace_end": None,
        "stack_words": [], "abort": None, "assert": None, "esp_error_check": None, "debug_reason": None,
        "stack_overflow_task": None, "task_wdt": None, "heap": None, "stack_smashing": False, "ubsan": None,
        "brownout": False, "reset_reason": None, "elf_sha256": None, "elf_sha256_line": None, "rebooting": False,
    }
    start, end = blocks[0] if blocks else (len(lines), len(lines))
    resets = [(i, m) for i, line in enumerate(lines) if (m := _RESET.search(line))]
    after = [(i, m) for i, m in resets if i >= end] if blocks else []
    before = [(i, m) for i, m in resets if i < start]
    if after:  # the reset this crash caused (ROM boot line after 'Rebooting...')
        p["reset_reason"] = {"code": after[0][1][1].lower(), "name": after[0][1][2], "when": "after_crash"}
    elif before:  # the reset that started the run that crashed (or the only boot in the log)
        p["reset_reason"] = {"code": before[-1][1][1].lower(), "name": before[-1][1][2],
                             "when": "before_crash" if blocks else "no_crash"}
    if not blocks:
        p["found"] = p["reset_reason"] is not None
        return p
    block = lines[start:end]
    _parse_block(block, p)
    if p["elf_sha256"] is None:  # boot line of the run that crashed ("app_init: ELF file SHA256:  <16 hex>...")
        for line in lines[:start]:
            if m := _ELF_SHA.search(line):
                p["elf_sha256"], p["elf_sha256_line"] = m[1].lower(), "boot"
    p["arch"] = _arch_of(p)
    _classify(p)
    return p


def _parse_block(block: list[str], p: dict[str, Any]) -> None:
    regs: dict[str, str] = {}
    dump_seen = regs_done = False
    in_stack = False
    twdt_text: list[str] | None = None
    for idx, line in enumerate(block):
        if in_stack:
            if m := _STACK_MEM.match(line):
                p["stack_words"] += ["0x" + w.lower() for w in _WORD.findall(m[1]) if len(w) <= 8]
                continue
            in_stack = False
        if twdt_text is not None and len(twdt_text) < 24 and not _is_trace(line):
            twdt_text.append(line)
        if m := _GURU.search(line):
            if p["header"] is None:
                p["header"], p["core"], p["reason"] = line.strip(), int(m[1]), m[2].strip()
            continue
        if m := _DUMP_HEAD.search(line):
            if dump_seen:
                regs_done = True
            dump_seen = True
            if m[1] is not None and p["core"] is None:
                p["core"] = int(m[1])
            continue
        if _REG_LINE.match(line) and not regs_done:
            dump_seen = True
            for name, value in _REG.findall(line):
                regs.setdefault(name, value.lower())
            continue
        if _STACK_MEM_HEAD.search(line):
            if not p["stack_words"]:
                in_stack = True
            continue
        if m := _BACKTRACE.search(line):
            pairs = _PAIR.findall(m[1])
            if pairs and not p["backtrace"]:
                p["backtrace"] = [{"pc": _hex(int(pc, 16)), "sp": _hex(int(sp, 16))} for pc, sp in pairs]
                if "|<-CORRUPTED" in m[1]:
                    p["backtrace_end"] = "corrupted"
                elif "|<-CONTINUES" in m[1]:
                    p["backtrace_end"] = "continues"
            if pairs and regs:
                regs_done = True
            continue
        if m := _ABORT.search(line):
            if p["abort"] is None:
                p["abort"] = {"pc": _hex(int(m[1], 16)), "core": int(m[2])}
        if m := _ASSERT.search(line):
            func = None if m[1] == "\b" else m[1]  # assert.c prints "\b" when the function name is unknown
            p["assert"] = p["assert"] or {"func": func, "file": m[2], "line": int(m[3]), "expr": m[4], "style": "idf"}
        elif m := _ASSERT_NEWLIB.search(line):
            p["assert"] = p["assert"] or {"func": m[4], "file": m[2], "line": int(m[3]), "expr": m[1], "style": "newlib"}
        if (m := _ESP_ERR.search(line)) and p["esp_error_check"] is None:
            info: dict[str, Any] = {"code": m[1].lower(), "name": m[2], "pc": _hex(int(m[3], 16)) if m[3] else None,
                                    "file": None, "line": None, "func": None, "expr": None}
            for follow in block[idx + 1: idx + 8]:
                if fm := _ESP_ERR_FILE.match(follow):
                    info["file"], info["line"] = fm[1], int(fm[2])
                elif fm := _ESP_ERR_FUNC.match(follow):
                    info["func"] = fm[1]
                elif fm := _ESP_ERR_EXPR.match(follow):
                    info["expr"] = fm[1]
            p["esp_error_check"] = info
        if m := _DEBUG_RSN.search(line):
            p["debug_reason"] = p["debug_reason"] or m[1].strip()
        if m := _CANARY.search(line):
            p["stack_overflow_task"] = p["stack_overflow_task"] or m[1]
        if m := _SO_HOOK.search(line):
            p["stack_overflow_task"] = p["stack_overflow_task"] or m[1]
        if (tm := _TWDT.search(line)) and twdt_text is None:
            twdt_text = [line[tm.end():]]
        if (m := _HEAP.search(line)) and p["heap"] is None:
            p["heap"] = m[1]
        if _SMASH.search(line):
            p["stack_smashing"] = True
        if (m := _UBSAN.search(line)) and p["ubsan"] is None:
            p["ubsan"] = m[1]
        if _BROWNOUT.search(line):
            p["brownout"] = True
        if (m := _ELF_SHA.search(line)) and p["elf_sha256"] is None:
            p["elf_sha256"], p["elf_sha256_line"] = m[1].lower(), "panic"
        if _REBOOT.search(line):
            p["rebooting"] = True
    p["registers"] = regs
    if twdt_text is not None:
        text = " ".join(twdt_text)
        head, _, tail = text.partition("Tasks currently running:")
        p["task_wdt"] = {"tasks": [{"name": n, "cpu": c} for n, c in _TWDT_TASK.findall(head)],
                         "running": [{"cpu": int(c), "task": t} for c, t in _TWDT_RUNNING.findall(tail)]}


def _classify(p: dict[str, Any]) -> None:
    reason = p["reason"]
    regs = p["registers"]
    if reason is None and p["header"] is None:  # header lost (log cut): fall back to the cause register
        cause = regs.get("EXCCAUSE") if p["arch"] == "xtensa" else regs.get("MCAUSE") if p["arch"] == "riscv" else None
        if cause is not None:
            n = int(cause, 16)
            table: tuple[str | None, ...] = XTENSA_EXCCAUSE if p["arch"] == "xtensa" else RISCV_MCAUSE
            if n < len(table) and table[n] not in (None, "res"):
                p["reason"], p["reason_inferred"] = table[n], True
    low = (p["reason"] or "").lower()
    if p["core"] is None and p["abort"]:
        p["core"] = p["abort"]["core"]
    if p["brownout"]:
        p["kind"], p["reason"] = "brownout", "Brownout detector was triggered"
    elif p["stack_overflow_task"] is not None or low == "stack protection fault":
        p["kind"] = "stack_overflow"
        if p["stack_overflow_task"] is not None and (p["reason"] is None or low == "unhandled debug exception"):
            p["reason"] = "Stack canary watchpoint triggered" if p["debug_reason"] else "Stack overflow"
    elif p["task_wdt"] is not None:
        p["kind"], p["reason"] = "task_wdt", "Task watchdog got triggered"
    elif low.startswith("interrupt wdt timeout"):
        p["kind"] = "int_wdt"
    elif p["heap"] is not None:
        p["kind"], p["reason"] = "heap", "CORRUPT HEAP"
    elif p["assert"] is not None:
        p["kind"], p["reason"] = "assert", "assert failed"
    elif p["esp_error_check"] is not None:
        err = p["esp_error_check"]
        p["kind"], p["reason"] = "assert", f"ESP_ERROR_CHECK failed: {err['name'] or err['code']}"
    elif p["stack_smashing"]:
        p["kind"], p["reason"] = "abort", "Stack smashing protect failure"
    elif p["ubsan"] is not None:
        p["kind"], p["reason"] = "abort", f"Undefined behavior: {p['ubsan']}"
    elif p["abort"] is not None:
        p["kind"], p["reason"] = "abort", "abort() was called"
    elif p["reason"] is not None:
        p["kind"] = "cpu_exception"


# --- addr2line --------------------------------------------------------------------------------------------------
def _loc(text: str) -> dict[str, Any]:
    text = _DISCRIMINATOR.sub("", text.strip())
    func, sep, where = text.rpartition(" at ")
    if not sep:
        func, _, where = text.partition(" ")
    file, _, line = where.rpartition(":")
    return {"function": None if func in ("", "??") else func,
            "file": None if file in ("", "??") else file,
            "line": int(line) if line.isdigit() and int(line) > 0 else None}


def parse_addr2line(lines: Iterable[str]) -> list[tuple[int, list[dict[str, Any]]]]:
    """Groups of ``addr2line -pfiaC`` output: [(address, [innermost location, inlined-by callers...])]."""
    groups: list[tuple[int, list[dict[str, Any]]]] = []
    for line in lines:
        if m := _A2L_ENTRY.match(line):
            groups.append((int(m[1], 16), [_loc(m[2])]))
        elif (m := _A2L_INLINED.match(line)) and groups:
            groups[-1][1].append(_loc(m[1]))
    return groups


def _match_groups(addrs: list[int], groups: list[tuple[int, list[dict[str, Any]]]]) -> list[list[dict] | None]:
    if len(groups) == len(addrs) and all(g[0] == a for g, a in zip(groups, addrs, strict=True)):
        return [g[1] for g in groups]
    pool: dict[int, list[list[dict]]] = {}
    for addr, chain in groups:
        pool.setdefault(addr, []).append(chain)
    return [pool[a].pop(0) if pool.get(a) else None for a in addrs]


def _resolved(chain: list[dict] | None) -> bool:
    return bool(chain) and chain[0]["function"] is not None


def _display_path(path: str | None, project_dir: str | Path | None) -> str | None:
    if not path:
        return path
    p = Path(path)
    if project_dir:
        base = Path(project_dir).expanduser()
        for root in (base, base.resolve()):
            try:
                return p.relative_to(root).as_posix()
            except ValueError:
                continue
    home = os.environ.get("HOME")
    if home and p.is_absolute():
        try:
            return "~/" + p.relative_to(home).as_posix()
        except ValueError:
            pass
    return path


# --- decoder ----------------------------------------------------------------------------------------------------
def fe_pages() -> dict[str, str]:
    """Registered chip -> source id of its ESP-IDF v6.1 Fatal Errors page (chip = target in the page URL; a page
    ``idf-v6.1-fatal-errors-<chip>`` wins over the unsuffixed one, which is the ESP32-S3 page)."""
    out: dict[str, str] = {}
    for sid, src in sources.all_sources().items():
        if sid != FE_SOURCE_PREFIX and not sid.startswith(FE_SOURCE_PREFIX + "-"):
            continue
        m = _FE_URL_TARGET.search(src["url"])
        if not m or m[1] not in CHIPS:
            continue
        if m[1] not in out or sid == f"{FE_SOURCE_PREFIX}-{m[1]}":
            out[m[1]] = sid
    return out


def _fe_source(arch: str | None, chip: str | None, need: str | None = None) -> str:
    """Fatal Errors page to cite: the chip's own page; else (no chip, or the crash output is from the other
    architecture, or the chip's page lacks the ``.. only:: <need>`` section) the unsuffixed page if it fits, else the
    first registered chip of that architecture whose page has the section."""
    pages = fe_pages()
    want = arch or (CHIPS.get(chip) if chip else None)

    def fits(c: str | None) -> bool:
        return (c in pages and (want is None or CHIPS[c] == want)
                and (need is None or need not in FE_PAGE_LACKS.get(pages[c], frozenset())))

    if chip and fits(chip):
        return pages[chip]
    default_chip = next((c for c, sid in pages.items() if sid == FE_SOURCE_PREFIX), None)
    if fits(default_chip):
        return FE_SOURCE_PREFIX
    return next((pages[c] for c in chips.ids() if fits(c)), FE_SOURCE_PREFIX)


def _short(func: str | None) -> str | None:
    return func.split("(", 1)[0] if func else func


def _in_panic_path(func: str | None) -> bool:
    name = _short(func) or ""
    return name in _PANIC_PATH or name.startswith("__ubsan_")


class _Ctx:
    """Collects interpretations, warnings, assumptions and the source ids they cite."""

    def __init__(self, arch: str | None, chip: str | None):
        self.arch, self.chip = arch, chip
        self.interpretation: list[dict[str, Any]] = []
        self.warnings: list[dict[str, Any]] = []
        self.assumptions: list[dict[str, Any]] = []
        self.source_ids: list[str] = []
        self._other_page: set[str] = set()

    def src(self, sid: str, need: str | None = None) -> str:
        if sid == "fe":
            sid = _fe_source(self.arch, self.chip, need)
            if need:
                self._note_other_page(sid, need)
        if sid not in self.source_ids:
            self.source_ids.append(sid)
        return sid

    def _note_other_page(self, sid: str, need: str) -> None:
        """The chip's own page lacks the section (and the crash output fits the chip): say which page is cited."""
        own = fe_pages().get(self.chip or "")
        if not own or own == sid or need in self._other_page or (self.arch and CHIPS[self.chip] != self.arch):
            return
        self._other_page.add(need)
        other = next((c for c, s in fe_pages().items() if s == sid), None)
        ids = [own, sid]
        caps = f"idf-v6.1-soccaps-{self.chip}"  # the target's soc_caps.h, where the capability is (not) defined
        if caps in sources.all_sources():
            ids.append(caps)
        for i in ids:
            if i not in self.source_ids:
                self.source_ids.append(i)
        self.warnings.append(warning(
            "doc_section_other_chip", "info",
            f"The ESP-IDF Fatal Errors page for {chips.title(self.chip)} has no section for this error ({need} "
            f"targets only); the explanation cites the page for {chips.title(other) if other else sid}. "
            "Check the chip setting.", ids))

    def interpret(self, rule: str, **fmt: Any) -> None:
        spec = RULES[rule]
        self.interpretation.append({"code": spec.get("code", rule), "text": spec["text"].format(**fmt),
                                    "source_id": self.src(spec["src"], RULE_FE_CONDITION.get(rule))})

    def warn(self, code: str, severity: str, message: str, source_ids: Iterable[str] = ()) -> None:
        ids = [self.src(s) for s in source_ids]
        self.warnings.append(warning(code, severity, message, ids))

    def assume(self, key: str, value: str, reason: str, source_ids: Iterable[str] = ()) -> None:
        for s in source_ids:
            self.src(s)
        self.assumptions.append(assumption(key, value, reason))


def _interpret_address(ctx: _Ctx, p: Mapping[str, Any], rule: str | None) -> str | None:
    """EXCVADDR (Xtensa Load/StoreProhibited) or MTVAL (RISC-V access faults), only as the docs explain it."""
    reason = (p["reason"] or "").lower()
    if ctx.arch == "xtensa" and rule in ("load_prohibited", "store_prohibited"):
        reg, verb = "EXCVADDR", "read" if rule == "load_prohibited" else "write"
    elif ctx.arch == "riscv" and rule == "access_fault":
        reg = "MTVAL"
        verb = {"load access fault": "read", "store access fault": "write"}.get(reason, "jump or call")
    else:
        return None
    raw = p["registers"].get(reg)
    if raw is None:
        return None
    addr = int(raw, 16)
    if addr == 0:
        ctx.interpret("null_pointer_zero", reg=reg, addr=_hex(addr), verb=verb)
        return f"{verb} through a NULL pointer"
    if addr < NEAR_ZERO_LIMIT:
        ctx.interpret("null_pointer_near", reg=reg, addr=_hex(addr), verb=verb, offset=addr)
        ctx.assume("near_zero_limit", _hex(NEAR_ZERO_LIMIT),
                   "rule of thumb: the ESP-IDF docs say 'close to zero' without a number", ["rule-of-thumb"])
        return f"{verb} through a NULL pointer at offset {addr} bytes"
    if not VALID_DATA_RANGE[0] <= addr <= VALID_DATA_RANGE[1]:
        ctx.interpret("bad_pointer", reg=reg, addr=_hex(addr))
        return "the pointer is likely uninitialized or corrupted"
    return None


def _interpret(ctx: _Ctx, p: Mapping[str, Any], loc_of: Callable[[str | None], str]) -> str | None:
    """Fill ctx.interpretation; returns a short detail for the summary (or None)."""
    detail: str | None = None
    reason = p["reason"] or ""
    low = reason.lower()
    kind = p["kind"]
    table = _RISCV_REASON_RULES if ctx.arch == "riscv" else _XTENSA_REASON_RULES
    rule = table.get(low)
    if kind == "int_wdt":
        ctx.interpret("int_wdt", cpu=low.rsplit("cpu", 1)[-1] if "cpu" in low else "?")
    elif rule == "debug_exception":
        ctx.interpret(rule, detail=f" Debug exception reason: {p['debug_reason']}." if p["debug_reason"] else "")
    elif rule == "access_fault":
        verb = {"load access fault": "read from", "store access fault": "write to"}.get(low, "execute code at")
        ctx.interpret(rule, verb=verb)
    elif rule is not None and kind in ("cpu_exception", "stack_overflow"):
        ctx.interpret(rule)
    if rule is not None:
        detail = _interpret_address(ctx, p, rule)
    if rule == "instr_fetch_prohibited" and "PC" in p["registers"]:
        pc = int(p["registers"]["PC"], 16)
        if pc == 0 or pc >> 28 != 0x4:
            ctx.interpret("bad_function_pointer", pc=_hex(pc), what="zero" if pc == 0 else "not 0x4xxxxxxx")
            detail = "call through an invalid function pointer"
    if p["stack_overflow_task"] is not None:
        if p["debug_reason"] and _CANARY.search(p["debug_reason"]):
            ctx.interpret("stack_canary", task=p["stack_overflow_task"])
        else:
            ctx.interpret("stack_overflow_check", task=p["stack_overflow_task"])
        detail = f"stack overflow in task {p['stack_overflow_task']}"
    if p["task_wdt"] is not None:
        tasks = ", ".join(f"{t['name']} ({t['cpu']})" for t in p["task_wdt"]["tasks"]) or "some tasks"
        running = p["task_wdt"]["running"]
        names = ", ".join("CPU {}: {}".format(r["cpu"], r["task"]) for r in running)
        run_txt = f" (running: {names})" if running else ""
        ctx.interpret("task_wdt", tasks=tasks, running=run_txt)
        ctx.interpret("task_wdt_nonfatal")
        detail = f"{tasks} did not reset the watchdog in time"
    if p["heap"] is not None:
        ctx.interpret("heap_corrupt", detail=f"CORRUPT HEAP: {p['heap']}")
        detail = f"CORRUPT HEAP: {p['heap']}"
    if p["assert"] is not None:
        a = p["assert"]
        ctx.interpret("assert_failed" if a["style"] == "idf" else "assert_failed_newlib", func=a["func"] or "?",
                      file=loc_of(a["file"]), line=a["line"], expr=a["expr"])
        detail = detail or f"assert failed in {a['func'] or '?'} ({loc_of(a['file'])}:{a['line']}): {a['expr']}"
    if p["esp_error_check"] is not None:
        e = p["esp_error_check"]
        err = f"{e['name']} ({e['code']})" if e["name"] else e["code"]
        ctx.interpret("esp_error_check", err=err, func=e["func"] or "?", file=loc_of(e["file"]) if e["file"] else "?",
                      line=e["line"] or "?", expr=e["expr"] or "?")
        detail = detail or f"ESP_ERROR_CHECK failed with {err}"
    if p["stack_smashing"]:
        ctx.interpret("stack_smashing")
    if p["ubsan"] is not None:
        meaning = UBSAN_TYPES.get(p["ubsan"])
        if meaning:
            ctx.interpret("ubsan", type=p["ubsan"], meaning=meaning.replace("``", "").rstrip("."))
    if p["brownout"]:
        ctx.interpret("brownout")
    return detail


def _where(frame: Mapping[str, Any] | None) -> str:
    if frame is None:
        return ""
    if not frame["function"]:
        return f" at {frame['pc']}"
    loc = f" ({frame['file']}:{frame['line']})" if frame["file"] and frame["line"] else ""
    return f" in {_short(frame['function'])}{loc}"


def _top_frame(p: Mapping[str, Any], frames: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Frame the summary names: the crash location for CPU exceptions, else the first frame outside the panic path."""
    if not frames:
        return None
    if p["kind"] in ("cpu_exception", "int_wdt") or (p["kind"] == "stack_overflow" and p["header"]):
        first = frames[0]
        return first if first["source"] != "stack_scan" else None
    for want_scan in (False, True):
        for f in frames:
            if f["function"] and (f["source"] == "stack_scan") == want_scan and not _in_panic_path(f["function"]):
                return f
    return None


def _summary(p: Mapping[str, Any], frames: list[dict[str, Any]], detail: str | None, reset_txt: str | None,
             loc_of: Callable[[str | None], str]) -> str:
    kind, reason = p["kind"], p["reason"]
    core = f" on core {p['core']}" if p["core"] is not None else ""
    where = _where(_top_frame(p, frames))
    if kind == "brownout":
        text = "Brownout: the supply voltage dropped below a safe level and the chip was reset"
    elif kind == "unknown" and frames:
        n = len(frames)
        text = (f"Backtrace without a crash header: {n} frame{'' if n == 1 else 's'} decoded; paste the log from the "
                "'Guru Meditation Error' (or 'abort()') line for the cause")
        if reset_txt:
            text += f"; reset reason {reset_txt}"
    elif kind == "unknown":
        text = "No crash report in the log"
        if reset_txt:
            text += f"; reset reason {reset_txt}"
    elif kind == "assert" and p["assert"] is not None:
        a = p["assert"]
        text = f"assert failed in {a['func'] or '?'} ({loc_of(a['file'])}:{a['line']}): {a['expr']}"
    elif kind == "assert" and p["esp_error_check"] is not None:
        e = p["esp_error_check"]
        err = f"{e['name']} ({e['code']})" if e["name"] else e["code"]
        loc = f" ({loc_of(e['file'])}:{e['line']})" if e["file"] else ""
        text = f"ESP_ERROR_CHECK failed with {err} in {e['func'] or '?'}{loc}"
        if e["expr"]:
            text += f": {e['expr']}"
    elif kind == "task_wdt":
        text = f"Task watchdog triggered: {detail}" if detail else "Task watchdog triggered"
        if where:
            text += f"; backtrace{where}"
    elif kind == "heap":
        text = f"Heap corruption detected{where}: {detail}"
    elif kind == "stack_overflow":
        task = f" in task {p['stack_overflow_task']}" if p["stack_overflow_task"] else ""
        text = f"{reason or 'Stack overflow'}{task}{core}{where}"
    else:  # cpu_exception, int_wdt, abort
        text = f"{reason}{'' if kind == 'int_wdt' else core}{where}"
        if detail:
            text += f": {detail}"
    return text.rstrip(".") + "."


def decode(log: str, *, elf: str | Path | None = None, chip: str | None = None, addr2line: str | None = None,
           cc_path: str | None = None, project_dir: str | Path | None = None,
           run: Callable[..., Mapping[str, Any]] = clitools.run) -> dict[str, Any]:
    """Action ``crash.decode``: parse the panic in ``log`` and resolve its code addresses (result envelope, never raises).

    ``elf``: firmware.elf of the build that crashed; without it only the parse result is returned (warning
    ``elf_missing``). ``chip``: a chip id of the register (``chips.ids()``), normally the project's
    ``board.chip``; else taken from ``cc_path`` (only a chip-specific prefix) or the RTC watchdog reset name in the log
    (only if it names exactly one chip; an assumption). The ELF header gives the architecture only. Evidence against
    the given chip (crash architecture, ELF architecture, compiler prefix, reset name) is a ``chip_mismatch`` warning.
    ``addr2line``: explicit tool path; else ``find_addr2line(chip, cc_path)``. ``project_dir``: file paths inside it
    are shown relative to it (paths under HOME as ``~/…``). ``run``: ``clitools.run``-compatible runner
    ``run(argv, *, timeout, tail)`` returning ``{"rc", "out_tail", "timed_out"}``. An injected runner (SIM, tests)
    gets ``elf`` and the tool name as they are: the ELF need not exist and a bare tool name is used if none is found.

    Frames: ``inlined: true`` means the frame was inlined into the next frame (same ``pc``, addr2line
    ``(inlined by)``). ``source``: backtrace (Backtrace: PC:SP pairs), mepc/ra (RISC-V register dump without a
    backtrace), stack_scan (heuristic: code addresses in the RISC-V 'Stack memory:' dump).
    """
    try:
        return _decode(log, elf=elf, chip=chip, addr2line=addr2line, cc_path=cc_path, project_dir=project_dir, run=run)
    except BenchError as e:
        return from_error(ACTION, e)
    except Exception as e:  # an action returns an envelope, never an exception
        logger.exception("circuit-bench: crash.decode failed")
        return fail(ACTION, "decode_failed", f"crash decoder failed ({type(e).__name__})",
                    "report this log to the circuit-bench maintainers")


def _candidates(p: Mapping[str, Any], arch: str | None) -> tuple[list[tuple[int, str]], int, list[int]]:
    """Code addresses to resolve: [(pc, source)], number of primary frames (backtrace or MEPC/RA), extra addresses
    (abort() and ESP_ERROR_CHECK PCs, resolved for the interpretation only)."""
    cands: list[tuple[int, str]] = []
    if p["backtrace"]:
        cands = [(int(b["pc"], 16), "backtrace") for b in p["backtrace"]]
    elif arch == "riscv":
        for reg, src in (("MEPC", "mepc"), ("RA", "ra")):
            if reg in p["registers"]:
                n = int(p["registers"][reg], 16)
                if all(n != pc for pc, _ in cands):
                    cands.append((n, src))
    primary = len(cands)
    if not p["backtrace"] and arch == "riscv" and p["stack_words"]:
        seen = {pc for pc, _ in cands}
        for word in p["stack_words"]:
            n = int(word, 16)
            if n >> 28 == 0x4 and n not in seen and len(cands) - primary < STACK_SCAN_MAX_CANDIDATES:
                seen.add(n)
                cands.append((n, "stack_scan"))
    extra = [int(h, 16) for h in (p["abort"]["pc"] if p["abort"] else None,
                                  p["esp_error_check"]["pc"] if p["esp_error_check"] else None) if h]
    return cands, primary, extra


def _check_chip(ctx: _Ctx, p: Mapping[str, Any], chip: str | None, elf_arch: str | None,
                cc_prefix: tuple[str, str] | None, reset_chips: list[str]) -> None:
    """One ``chip_mismatch`` warning if the log, the ELF or the compiler contradicts the given chip."""
    if chip is None:
        return
    chip_arch = CHIPS[chip]
    reasons: list[str] = []
    ids: list[str] = []
    if p["arch"] and chip_arch != p["arch"]:
        reasons.append(f"the crash output is from a {p['arch']} chip, but {chip} is {chip_arch}")
    elif elf_arch and chip_arch != elf_arch:
        reasons.append(f"the ELF is built for {elf_arch}, but {chip} is {chip_arch}")
        ids.append("elf-gabi-e-machine")
    if cc_prefix and cc_prefix[0] in TOOLCHAIN_PREFIX.values() and cc_prefix[0] != TOOLCHAIN_PREFIX[chip]:
        users = ", ".join(chips.title(c) for c, pre in TOOLCHAIN_PREFIX.items() if pre == cc_prefix[0])
        reasons.append(f"the firmware was built with {cc_prefix[0]}-gcc (toolchain of {users}), but {chip} uses "
                       f"{TOOLCHAIN_PREFIX[chip]}")
        ids += [chips.get(c)["source_ids"]["toolchain_prefix"] for c in chips.ids() if c == chip
                or TOOLCHAIN_PREFIX[c] == cc_prefix[0]]
    if reset_chips and chip in RTC_WDT_RESET_BY_TARGET and chip not in reset_chips:
        rr = p["reset_reason"]
        users = ", ".join(chips.title(c) for c in reset_chips)
        reasons.append(f"the reset reason {rr['name']} ({rr['code']}) is the RTC watchdog reset name of {users}; "
                       f"{chips.title(chip)} prints {RTC_WDT_RESET_BY_TARGET[chip]}")
        pages = fe_pages()
        ids += [pages[c] for c in (chip, *reset_chips) if c in pages]
    if reasons:
        text = "; ".join(reasons)
        ctx.warn("chip_mismatch", "caution", f"{text[0].upper()}{text[1:]}: check the chip setting.", ids)


def _choose_tool(ctx: _Ctx, *, addr2line: str | None, chip: str | None, cc_path: str | None, arch: str | None,
                 real_run: bool) -> str | None:
    if addr2line:
        return addr2line
    tool = find_addr2line(chip, cc_path)
    if tool is None and chip is None and arch in _ARCH_PREFIXES:
        for prefix in _ARCH_PREFIXES[arch] + ((UNIFIED_XTENSA_PREFIX,) if arch == "xtensa" else ()):
            tool = _find_prefix(prefix)
            if tool:
                ctx.assume("toolchain", Path(tool).name, f"chip not given; toolchain chosen by the {arch} crash output or ELF")
                break
    elif tool and chip and _is_unified(tool) and \
            (_prefix_from_cc(str(cc_path)) or ("",))[0] != UNIFIED_XTENSA_PREFIX:
        ctx.assume("toolchain", Path(tool).name,
                   f"no {TOOLCHAIN_PREFIX[chip]}-addr2line found; using the unified Xtensa addr2line of PlatformIO's "
                   "toolchain-xtensa-esp-elf for this Xtensa chip", ["pio-esp32-8.0.0-platform-json"])
    if tool is None and not real_run:
        prefix = TOOLCHAIN_PREFIX[chip] if chip else _ARCH_PREFIXES.get(arch or "xtensa", _ARCH_PREFIXES["xtensa"])[0]
        tool = f"{prefix}-addr2line"
    return tool


def _decode(log: Any, *, elf: str | Path | None, chip: str | None, addr2line: str | None, cc_path: str | None,
            project_dir: str | Path | None, run: Callable[..., Mapping[str, Any]]) -> dict[str, Any]:
    if log is None or (isinstance(log, str | bytes) and not log.strip()):
        raise BenchError("invalid_args", "log is empty", "paste the serial output of the crash")
    if not isinstance(log, str | bytes):
        raise BenchError("invalid_args", "log must be text")
    chip = normalize_chip(chip)
    real_run = run is clitools.run
    p = parse(log)
    if not p["found"]:
        return fail(ACTION, "decode_failed", "No ESP-IDF crash report found in the log.",
                    "paste the serial output from 'Guru Meditation Error' (or 'abort() was called') to 'Rebooting...'",
                    checks=[check("crash.parse", "failed", "no panic header, abort, assert, watchdog, brownout, "
                                                          "register dump, backtrace or reset reason found")])
    elf_path = Path(elf).expanduser() if elf else None
    elf_file = elf_path if elf_path is not None and elf_path.is_file() else None
    elf_arch = _elf_arch(elf_file) if elf_file else None
    cc_prefix = _prefix_from_cc(str(cc_path)) if cc_path else None
    given = chip
    if chip is None and cc_prefix:
        chip = _chip_for_prefix(cc_prefix[0])
    reset_name = p["reset_reason"]["name"] if p["reset_reason"] else None
    reset_chips = [c for c in chips.ids() if RTC_WDT_RESET_BY_TARGET.get(c) == reset_name] if reset_name else []
    inferred = None
    if chip is None and reset_chips:
        known_arch = p["arch"] or elf_arch
        fit = [c for c in reset_chips if known_arch is None or CHIPS[c] == known_arch]
        if len(fit) == 1:
            chip = inferred = fit[0]
    chip_arch = CHIPS.get(chip) if chip else None
    arch = p["arch"] or chip_arch or elf_arch
    ctx = _Ctx(arch, chip)
    _check_chip(ctx, p, chip if inferred is None else given, elf_arch, cc_prefix, reset_chips)
    if elf_arch and arch and elf_arch != arch:
        ctx.warn("elf_arch_mismatch", "caution", f"The ELF is built for {elf_arch}, the crash is from {arch}: this ELF "
                                                 "does not belong to the crashed firmware.", ["elf-gabi-e-machine"])
    if p["reason_inferred"]:
        cause_reg = "EXCCAUSE" if arch == "xtensa" else "MCAUSE"
        ctx.assume("reason", p["reason"], f"inferred from {cause_reg} {p['registers'][cause_reg]}: the panic header "
                                          "line is missing from the log",
                   ["idf-v6.1-src-panic-arch-xtensa" if arch == "xtensa" else "idf-v6.1-src-panic-arch-riscv"])
    if inferred:
        ctx.assume("chip", inferred, f"chip not given; the reset reason {reset_name} is the RTC watchdog reset name of "
                                     f"{chips.title(inferred)} only (among {chips.ids_text()})", ["fe"])

    cands, primary, extra = _candidates(p, arch)
    checks = [check("crash.parse", "passed", _parse_detail(p))]
    chains: list[list[dict] | None] = [None] * len(cands)
    extra_chains: list[list[dict] | None] = [None] * len(extra)
    addrs = [pc for pc, _ in cands] + extra
    if not addrs:
        a2l_check = check("crash.addr2line", "skipped", "no code addresses in the log")
    elif elf_path is None or (real_run and elf_file is None):
        msg = "No ELF file given" if elf_path is None else f"ELF file not found: {elf_path.name}"
        ctx.warn("elf_missing", "caution", f"{msg}: frames show addresses only. Pass project (its last build gives the "
                                           "ELF), or elf with the firmware.elf of the build that crashed.")
        a2l_check = check("crash.addr2line", "skipped", "no ELF file")
    else:
        tool = _choose_tool(ctx, addr2line=addr2line, chip=chip, cc_path=cc_path, arch=arch, real_run=real_run)
        if tool is None:
            ctx.warn("tool_missing", "caution", "addr2line of the ESP toolchain not found: frames show addresses only. "
                                                "Install the PlatformIO platform for the chip or pass cc_path.")
            a2l_check = check("crash.addr2line", "skipped", "addr2line not found")
        else:
            a2l_check, chains, extra_chains = _run_addr2line(ctx, run, tool, elf_path, addrs, len(cands), primary)

    frames = _build_frames(cands, chains, project_dir)
    if p["backtrace_end"] == "corrupted":
        ctx.warn("backtrace_corrupted", "caution", "The backtrace ends with |<-CORRUPTED: the stack was damaged, "
                                                   "deeper frames are missing or wrong.", ["idf-v6.1-src-backtrace-xtensa"])
    elif p["backtrace_end"] == "continues":
        ctx.warn("backtrace_continues", "info", "The backtrace ends with |<-CONTINUES: deeper frames were not printed.",
                 ["idf-v6.1-src-backtrace-xtensa"])
    if any(f["source"] == "stack_scan" for f in frames):
        ctx.warn("stack_scan_heuristic", "info", "Frames marked stack_scan are a heuristic: code addresses found in the "
                                                 "stack memory dump, not a verified call chain (return addresses may "
                                                 "point one line after the call).",
                 ["idf-v6.1-src-panic-arch-riscv", "rule-of-thumb"])
        ctx.assume("stack_scan_filter", "words 0x40000000-0x4fffffff that addr2line resolves to a source file",
                   "rule of thumb: ESP code addresses start with 0x4; the ELF decides which ones are code")
    if any(f["source"] == "ra" and f["function"] for f in frames):
        ctx.warn("ra_return_address", "info", "The ra frame is the return address: the call itself is on the line "
                                              "before it or the same line.", ["riscv-isa-unpriv-rv32"])
    if not cands and not p["stack_words"] and p["kind"] not in ("brownout", "unknown"):
        ctx.warn("no_backtrace", "info", "The log has no backtrace (silent reboot setting, or the log is cut). "
                                         "Capture the serial output up to 'Rebooting...'.", ["fe"])
    if p["blocks"] > 1:
        ctx.warn("multiple_crashes", "info", f"{p['blocks']} crash reports in the log; decoded the first one.")

    def loc_of(path: str | None) -> str:
        return _display_path(path, project_dir) or "?"

    detail = _interpret(ctx, p, loc_of)
    if p["kind"] == "abort" and p["abort"] is not None:
        chain = extra_chains[0] if extra_chains else None
        where = ""
        if chain and _resolved(chain):
            first = chain[0]  # source location of the abort() call (innermost of an inline chain)
            file, line = _display_path(first["file"], project_dir), first["line"]
            where = f" (in {_short(first['function'])}" + (f", {file}:{line})" if file and line else ")")
        ctx.interpret("abort", pc=p["abort"]["pc"], core=p["abort"]["core"], where=where)
    reset_txt = None
    if p["reset_reason"] is not None:
        rr = p["reset_reason"]
        reset_txt = f"{rr['name']} ({rr['code']})"
        if rr["name"] in _RTC_WDT_RESET_NAMES:
            ctx.interpret("rtc_wdt_reset", name=rr["name"])
            reset_txt += ": RTC watchdog reset"

    elf_match, elf_check = _elf_match(ctx, p, elf_file)
    checks += [a2l_check, elf_check]
    if len(frames) > MAX_FRAMES:
        ctx.warn("frames_truncated", "info", f"Showing the first {MAX_FRAMES} of {len(frames)} frames.")
    result = {
        "kind": p["kind"], "reason": p["reason"], "core": p["core"], "arch": arch,
        "registers": dict(p["registers"]), "frames": frames[:MAX_FRAMES], "interpretation": ctx.interpretation,
        "reset_reason": p["reset_reason"], "elf_sha256_log": p["elf_sha256"], "elf_match": elf_match,
    }
    summary = _summary(p, frames, detail, reset_txt, loc_of)
    simulated = bool(getattr(run, "simulated", False))  # sim.crash_runner(): addr2line answers from the sim data
    if simulated:
        ctx.assumptions.append(assumption("addr2line", "simulated", "simulated addr2line: answers from the Circuit "
                                          "Bench sim data, whose lines match the example firmware laser-trigger"))
    env = envelope(ACTION, summary, result, checks=checks, warnings=ctx.warnings, assumptions=ctx.assumptions,
                   sources=sources.resolve(ctx.source_ids), simulated=simulated)
    return _fit(env)


_KEY_REGISTERS = ("PC", "PS", "A0", "A1", "EXCCAUSE", "EXCVADDR", "MEPC", "RA", "SP", "MSTATUS", "MCAUSE", "MTVAL")


def _fit(env: dict[str, Any]) -> dict[str, Any]:
    """Keep the answer under MAX_RESULT_BYTES: drop frames from the end, then non-key registers."""
    def size() -> int:
        return len(json.dumps(env, ensure_ascii=False).encode())

    result = env["result"]
    cut = False
    while size() > MAX_RESULT_BYTES and len(result["frames"]) > 4:
        result["frames"] = result["frames"][:-2]
        cut = True
    if size() > MAX_RESULT_BYTES:
        result["registers"] = {k: v for k, v in result["registers"].items() if k in _KEY_REGISTERS}
        cut = True
    if cut:
        env["warnings"].append(warning("result_truncated", "info", "Frames or registers were cut to keep the answer "
                                                                   "small; decode again with a shorter log for more."))
    return env


def _parse_detail(p: Mapping[str, Any]) -> str:
    parts = []
    if p["header"]:
        parts.append("Guru Meditation header")
    elif p["kind"] != "unknown":
        parts.append(f"{p['kind']} message")
    if p["registers"]:
        parts.append("register dump")
    if p["backtrace"]:
        parts.append(f"backtrace ({len(p['backtrace'])} PC:SP pairs)")
    if p["stack_words"]:
        parts.append("stack memory dump")
    if p["reset_reason"]:
        parts.append(f"reset reason {p['reset_reason']['name']}")
    return (", ".join(parts) or "crash output") + " found"


def _run_addr2line(ctx: _Ctx, run: Callable[..., Mapping[str, Any]], tool: str, elf_path: Path, addrs: list[int],
                   n_cands: int, primary: int) -> tuple[dict[str, Any], list, list]:
    argv = [tool, *ADDR2LINE_ARGS, str(elf_path), *(_hex(a) for a in addrs)]
    empty: tuple[list, list] = ([None] * n_cands, [None] * (len(addrs) - n_cands))
    try:
        res = run(argv, timeout=ADDR2LINE_TIMEOUT_S, tail=max(200, 12 * len(addrs) + 50))
    except BenchError as e:
        ctx.warn(e.code if e.code in ("tool_missing", "sim_only") else "tool_failed", "caution",
                 f"addr2line could not run ({e.message}): frames show addresses only.")
        return check("crash.addr2line", "skipped", e.message), *empty
    if res.get("timed_out"):
        ctx.warn("tool_failed", "caution", f"addr2line timed out after {ADDR2LINE_TIMEOUT_S:.0f} s.")
        return check("crash.addr2line", "failed", "addr2line timed out"), *empty
    out = list(res.get("out_tail") or [])
    if res.get("rc") != 0:
        last = next((x for x in reversed(out) if x.strip()), "")
        ctx.warn("tool_failed", "caution", f"addr2line exited with code {res.get('rc')}: {last[:160]}")
        return check("crash.addr2line", "failed", f"addr2line exited with code {res.get('rc')}"), *empty
    chains = _match_groups(addrs, parse_addr2line(out))
    ok = sum(1 for c in chains[:primary] if _resolved(c))
    if primary == 0:
        status = "passed" if any(_resolved(c) for c in chains) else "failed"
        detail = "no backtrace; resolved stack scan and abort addresses only"
    else:
        status = "passed" if ok else "failed"
        detail = f"{ok} of {primary} frames resolved"
        if not ok:
            ctx.warn("unresolved", "caution", "addr2line resolved no frame: the ELF probably belongs to another build "
                                              "or has no debug information.")
    return check("crash.addr2line", status, detail), chains[:n_cands], chains[n_cands:]


def _build_frames(cands: list[tuple[int, str]], chains: list[list[dict] | None],
                  project_dir: str | Path | None) -> list[dict[str, Any]]:
    frames: list[dict[str, Any]] = []
    scanned = 0
    for idx, (pc, src) in enumerate(cands):
        chain = chains[idx] if idx < len(chains) else None
        if src == "stack_scan":
            if not chain or not _resolved(chain) or chain[0]["file"] is None or scanned >= STACK_SCAN_MAX_FRAMES:
                continue
            scanned += 1
        if not chain:
            frames.append({"i": 0, "pc": _hex(pc), "function": None, "file": None, "line": None, "inlined": False,
                           "source": src})
            continue
        for j, loc in enumerate(chain):
            frames.append({"i": 0, "pc": _hex(pc), "function": loc["function"],
                           "file": _display_path(loc["file"], project_dir), "line": loc["line"],
                           "inlined": j < len(chain) - 1, "source": src})
    for i, f in enumerate(frames):
        f["i"] = i
    return frames


def _elf_match(ctx: _Ctx, p: Mapping[str, Any], elf_file: Path | None) -> tuple[bool | None, dict[str, Any]]:
    log_sha = p["elf_sha256"]
    if log_sha is None:
        return None, check("crash.elf_match", "skipped", "no 'ELF file SHA256' line in the log")
    ctx.assume("elf_sha256_line", f"'ELF file SHA256: {log_sha}' ({p['elf_sha256_line']} output)",
               "unverified: line format taken from the ESP-IDF v6.1 sources, not yet checked against real logs",
               ["idf-v6.1-src-panic" if p["elf_sha256_line"] == "panic" else "idf-v6.1-src-app-desc",
                "idf-v6.1-app-image-format"])
    if set(log_sha) == {"0"}:
        ctx.warn("elf_sha256_zero", "info", "The log's ELF SHA256 is all zeros: the build did not embed it, so the "
                                            "ELF cannot be compared.")
        return None, check("crash.elf_match", "skipped", "ELF SHA256 in the log is all zeros")
    if elf_file is None:
        return None, check("crash.elf_match", "skipped", "no ELF file to compare")
    actual = _sha256_file(elf_file)
    if actual.startswith(log_sha):
        return True, check("crash.elf_match", "passed", "ELF SHA256 prefix in the log matches the build")
    ctx.warn("elf_mismatch", "caution", f"ELF SHA256 in the log ({log_sha}) does not match the ELF ({actual[:len(log_sha)]}): "
                                        "the frames may point to the wrong code. Decode with the ELF of the build "
                                        "that crashed.", ["idf-v6.1-src-panic", "idf-v6.1-app-image-format"])
    return False, check("crash.elf_match", "failed", "ELF SHA256 prefix in the log differs from the ELF")
