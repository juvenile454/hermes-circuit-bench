"""/bench slash command: plain text for CLI, Telegram and Desktop.

``/bench`` overview, ``/bench doctor``, ``/bench ports``, ``/bench projects``. Reads only the plugin's own data
folder (projects) and the port list; arguments are never used as paths.
"""
from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)
USAGE = "Usage: /bench [doctor | ports | projects]"
TOOLS = "bench_project, bench_pins, bench_calc, bench_schematic, bench_solder, bench_board, bench_crash"
_MARK = {"passed": "ok  ", "failed": "FAIL", "skipped": "skip", "not_checked": "n/c "}
MAX_LINES = 40


def _projects_lines(limit: int = 20) -> list[str]:
    from .bench_core import project as P
    env = P.list()
    if not env["ok"]:
        return [f"Projects: unavailable ({(env.get('error') or {}).get('message', 'error')})"]
    items = env["result"]["projects"]
    if not items:
        return [("Projects: none yet. Ask Hermes to create one (bench_project create) or open the demo "
                 "(bench_project demo).")]
    lines = [f"Projects ({len(items)}):"]
    for p in items[:limit]:
        board = " ".join(x for x in (p.get("chip"), (p.get("variant") or "").upper() or None) if x)
        sim = ", simulated" if p.get("simulated") else ""
        lines.append(f"  {p['id']}: {p.get('title')} ({board}{sim}), rev {p.get('rev')}")
    if len(items) > limit:
        lines.append(f"  … and {len(items) - limit} more")
    lines += [f"  ! {w['message']}" for w in env.get("warnings", [])[:3]]
    return lines


def _ports_lines() -> list[str]:
    from .bench_core import board
    env = board.ports()
    if not env["ok"]:
        return [f"Ports: unavailable ({(env.get('error') or {}).get('message', 'error')})"]
    lines = [f"Ports: {env['summary']}"]
    for p in env["result"]["ports"][:10]:
        lines.append(f"  {p['device']}  {p.get('kind')}  {p.get('description')}" + ("  [simulated]" if p.get("simulated")
                                                                                      else ""))
    lines += [f"  ! {w['message']}" for w in env.get("warnings", [])[:3]]
    return lines


def _switch_lines() -> list[str]:
    from .bench_core import guard
    from .bench_core import settings as S
    cfg = S.load()
    hw = S.hardware_enabled(cfg)
    lines = [f"Hardware access: {'on' if hw else 'off (only simulated sim:// boards)'}",
             "Agent flashing: " + ("allowed, every flash asks for approval" if cfg.get("allow_flash") is True
                                   else "off (setting allow_flash)"),
             "Serial ports: " + ("ask before the agent opens a port" if cfg.get("approve_serial") is not False
                                 else "opened without asking (setting approve_serial)")]
    if guard.approvals_bypassed():
        lines.append("Approvals are off or YOLO is on: the agent cannot use real boards; use the Bench UI.")
    return lines


def overview() -> str:
    lines = ["Circuit Bench: ESP32 pins, parts, schematics, soldering, build/flash/monitor, crash decoding."]
    lines += _projects_lines(limit=5)
    lines += _switch_lines()
    lines += [f"Tools for Hermes: {TOOLS}.", USAGE]
    return "\n".join(lines)


def doctor_text() -> str:
    from .bench_core import doctor
    env = doctor.run()
    lines = [env["summary"]]
    for c in env.get("checks", []):
        name = c["id"].split(".", 1)[-1]
        mark = "miss" if c["status"] == "failed" and name in doctor.TOOL_IDS else _MARK.get(c["status"], c["status"])
        lines.append(f"  [{mark}] {name}: {c.get('detail', '')}")
    lines += [f"  ! {w['message']}" for w in env.get("warnings", [])[:8]]
    return "\n".join(lines[:MAX_LINES])


def make_command(host: Any = None) -> Callable[[str], str]:
    def bench(raw_args: str = "") -> str:
        try:
            words = str(raw_args or "").split()
            sub = words[0].lower() if words else ""
            if sub in ("", "help", "status"):
                return overview()
            if sub == "doctor":
                return doctor_text()
            if sub == "ports":
                return "\n".join(_ports_lines())
            if sub == "projects":
                return "\n".join(_projects_lines())
            return f"Unknown /bench option {sub[:20]!r}. {USAGE}"
        except Exception as e:  # noqa: BLE001 - a command answers with text, never an exception
            logger.warning("circuit-bench: /bench failed (%s)", type(e).__name__)
            return f"Circuit Bench: /bench failed ({type(e).__name__}). {USAGE}"

    return bench
