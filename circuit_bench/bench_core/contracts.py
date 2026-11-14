"""Result envelope and shared vocabulary."""
from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from typing import Any, Literal

Status = Literal["passed", "failed", "skipped", "not_checked"]
Severity = Literal["info", "caution", "danger"]

CHECK_STATUSES: tuple[str, ...] = ("passed", "failed", "skipped", "not_checked")
WARNING_SEVERITIES: tuple[str, ...] = ("info", "caution", "danger")
RULE_SEVERITIES: tuple[str, ...] = ("blocked", "caution", "info")

ERROR_CODES: frozenset[str] = frozenset({
    # input
    "invalid_args", "unknown_chip", "unknown_pin", "unknown_board", "rule_data_missing",
    # tools
    "dependency_missing", "tool_missing", "tool_failed",
    # port
    "port_not_found", "port_busy", "timeout",
    # approvals
    "not_confirmed", "flash_disabled", "unattended_blocked",
    # project
    "project_not_found", "project_conflict", "project_damaged", "job_not_found",
    # firmware
    "elf_missing", "elf_mismatch", "decode_failed",
    # chip and platform
    "chip_mismatch", "platform_too_old",
    # sim / hardware switch
    "sim_only",
})

ACTIONS: frozenset[str] = frozenset({
    "pins.check", "pins.suggest", "pins.info",
    "calc.led", "calc.npn", "calc.divider", "calc.i2c_pullup", "calc.mosfet", "calc.ldo",
    # module catalog
    "calc.list", "calc.ina_shunt", "calc.current_sense", "calc.rtd", "calc.ntc", "calc.adc_ext", "calc.current_limit",
    "calc.led_strip", "calc.opto", "calc.buck", "calc.charger",
    "modules.list", "modules.info",
    "schematic.render", "solder.plan", "solder.step",
    "board.ports", "board.detect", "board.build", "board.flash", "board.flash_check", "board.layout", "serial.monitor",
    "serial.open", "serial.close", "serial.tail", "job.get",
    "crash.decode",
    "project.create", "project.get", "project.list", "project.update", "project.delete",
    "doctor.run", "sim.demo", "health",
})

MODES: tuple[str, ...] = (
    "out", "in", "in_pullup", "in_pulldown", "adc", "pwm", "i2c_sda", "i2c_scl",
    "spi_sck", "spi_mosi", "spi_miso", "spi_cs", "uart_tx", "uart_rx", "touch",
)

MAX_RESULT_BYTES = 8 * 1024  # answers to the model stay small


class BenchError(Exception):
    """Raised by helpers; action functions turn it into an error envelope."""

    def __init__(self, code: str, message: str, hint: str | None = None):
        if code not in ERROR_CODES:
            raise ValueError(f"unknown error code: {code!r}")
        super().__init__(message)
        self.code = code
        self.message = message
        self.hint = hint

    def as_dict(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message, "hint": self.hint}


def check(check_id: str, status: str, detail: str = "") -> dict[str, Any]:
    if status not in CHECK_STATUSES:
        raise ValueError(f"unknown check status: {status!r}")
    return {"id": check_id, "status": status, "detail": detail}


def warning(code: str, severity: str, message: str, source_ids: Iterable[str] = ()) -> dict[str, Any]:
    if severity not in WARNING_SEVERITIES:
        raise ValueError(f"unknown warning severity: {severity!r}")
    return {"code": code, "severity": severity, "message": message, "source_ids": list(source_ids)}


def assumption(key: str, value: str, reason: str) -> dict[str, Any]:
    return {"key": key, "value": value, "reason": reason}


def envelope(action: str, summary: str, result: Any = None, *, checks: Iterable[Mapping] = (),
             warnings: Iterable[Mapping] = (), assumptions: Iterable[Mapping] = (),
             sources: Iterable[Mapping] = (), simulated: bool = False) -> dict[str, Any]:
    """Success envelope."""
    if action not in ACTIONS:
        raise ValueError(f"unknown action: {action!r}")
    return {
        "ok": True,
        "action": action,
        "summary": summary,
        "result": {} if result is None else result,
        "checks": [dict(c) for c in checks],
        "warnings": [dict(w) for w in warnings],
        "assumptions": [dict(a) for a in assumptions],
        "sources": [dict(s) for s in sources],
        "simulated": bool(simulated),
        "error": None,
    }


def fail(action: str, code: str, message: str, hint: str | None = None, *, result: Any = None,
         checks: Iterable[Mapping] = (), warnings: Iterable[Mapping] = (), sources: Iterable[Mapping] = (),
         simulated: bool = False) -> dict[str, Any]:
    """Error envelope. ``summary`` repeats the message so CLI/Telegram users see it. Message, hint and summary show
    format, direction and separator characters, lone surrogates, C1 controls and default-ignorable code points as
    ``\\uXXXX`` (``shown.for_model``): a path or chip text in an error cannot hide text from the reader or start a
    line that looks like another answer. The input itself is not refused for them."""
    from .shown import for_model
    message, hint = for_model(message), for_model(hint)
    err = BenchError(code, message, hint)  # validates the code
    env = envelope(action, message, result, checks=checks, warnings=warnings, sources=sources, simulated=simulated)
    env["ok"] = False
    env["error"] = err.as_dict()
    return env


def from_error(action: str, err: BenchError, **kw: Any) -> dict[str, Any]:
    return fail(action, err.code, err.message, err.hint, **kw)


_PREFIXES = ((1e9, "G"), (1e6, "M"), (1e3, "k"), (1.0, ""), (1e-3, "m"), (1e-6, "µ"), (1e-9, "n"), (1e-12, "p"))
_NO_PREFIX_UNITS = {"%", "°C", "dB", "", "x"}


def _round_sig(x: float, digits: int) -> float:
    return round(x, digits - 1 - math.floor(math.log10(abs(x))))


def format_si(value: float, unit: str, digits: int = 3) -> str:
    """'2.60 mA', '6.76 mW', '1.00 kΩ', '0 A'. ``digits`` significant digits, decimal point."""
    if not isinstance(value, int | float) or isinstance(value, bool) or not math.isfinite(value):
        raise ValueError(f"not a finite number: {value!r}")
    if digits < 1:
        raise ValueError("digits must be >= 1")
    if value == 0:
        return f"0 {unit}".rstrip()
    rounded = _round_sig(float(value), digits)  # round first, so 0.99996 A becomes 1.00 A, not 1000 mA
    if unit in _NO_PREFIX_UNITS:
        scale, prefix = 1.0, ""
    else:
        mag = abs(rounded)
        scale, prefix = next(((f, p) for f, p in _PREFIXES if mag >= f), _PREFIXES[-1])
    scaled = rounded / scale
    decimals = max(0, digits - 1 - math.floor(math.log10(abs(scaled))))
    return f"{scaled:.{decimals}f} {prefix}{unit}".rstrip()


def qty(value: float, unit: str, digits: int = 3) -> dict[str, Any]:
    """SI value plus display text."""
    return {"value": value, "unit": unit, "display": format_si(value, unit, digits)}


def validate_envelope(obj: Any) -> list[str]:
    """Problems with an envelope (empty list = valid). Used by tests and the fixture check."""
    problems: list[str] = []
    if not isinstance(obj, dict):
        return ["envelope is not an object"]
    required = ("ok", "action", "summary", "result", "checks", "warnings", "assumptions", "sources", "simulated", "error")
    problems += [f"missing key: {k}" for k in required if k not in obj]
    if problems:
        return problems
    if obj["action"] not in ACTIONS:
        problems.append(f"unknown action: {obj['action']!r}")
    if not isinstance(obj["summary"], str) or not obj["summary"]:
        problems.append("summary must be a non-empty string")
    for c in obj["checks"]:
        if not isinstance(c, dict) or c.get("status") not in CHECK_STATUSES or not c.get("id"):
            problems.append(f"bad check: {c!r}")
    for w in obj["warnings"]:
        if not isinstance(w, dict) or w.get("severity") not in WARNING_SEVERITIES or not w.get("code"):
            problems.append(f"bad warning: {w!r}")
    for s in obj["sources"]:
        if not isinstance(s, dict) or not s.get("id") or "url" not in s or "retrieved" not in s:
            problems.append(f"bad source: {s!r}")
    if obj["ok"] is True and obj["error"] is not None:
        problems.append("ok envelope must have error null")
    if obj["ok"] is False:
        err = obj["error"]
        if not isinstance(err, dict) or err.get("code") not in ERROR_CODES or not err.get("message"):
            problems.append(f"bad error: {err!r}")
    if not isinstance(obj["simulated"], bool):
        problems.append("simulated must be a bool")
    return problems
