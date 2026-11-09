"""Circuit Bench: Hermes plugin for ESP32 electronics work.

Agent half (registered in register()): the tools bench_project, bench_pins, bench_calc, bench_schematic,
bench_solder, bench_board, bench_crash (toolset circuit-bench), the pre_tool_call approval hook, the /bench
command and the bundled skill circuit-bench:esp32-bench.
Backend: dashboard/plugin_api.py (routes under /api/plugins/circuit-bench/).
Desktop half: desktop/plugin.js (generated from desktop-src/ by scripts/build-desktop.mjs).

Keep this module light: no third-party imports at module level (schemdraw/pyserial are imported lazily).
"""
from __future__ import annotations

import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)
PLUGIN_ID = "circuit-bench"
SKILLS_DIR = Path(__file__).resolve().parent / "skills"


def skill_frontmatter(text: str) -> dict[str, str]:
    """Top-level scalar keys of a SKILL.md frontmatter (no YAML dependency); {} without a closed frontmatter."""
    lines = text.removeprefix("\ufeff").splitlines()
    if not lines or lines[0].strip() != "---":
        return {}
    out: dict[str, str] = {}
    for line in lines[1:]:
        if line.strip() == "---":
            return out
        if not line[:1].strip() or line.lstrip().startswith("#") or ":" not in line:
            continue
        key, _, value = line.partition(":")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if value:
            out[key.strip()] = value
    return {}


def _cron_probe(ctx):
    """True inside a cron run. ``ctx.current_cron_execution`` is a method of the context: bind it here."""
    probe = getattr(ctx, "current_cron_execution", None)
    if not callable(probe):
        logger.info("circuit-bench: this Hermes has no ctx.current_cron_execution; cron is read from HERMES_CRON_SESSION")
        return None

    def cron() -> bool:
        return probe() is not None

    return cron


def _register_skills(ctx) -> None:
    register_skill = getattr(ctx, "register_skill", None)
    if not callable(register_skill):
        logger.info("circuit-bench: bundled skill not registered (this Hermes has no ctx.register_skill)")
        return
    for skill_md in sorted(SKILLS_DIR.glob("*/SKILL.md")):
        name = skill_md.parent.name
        try:
            meta = skill_frontmatter(skill_md.read_text(encoding="utf-8"))
            register_skill(name, skill_md, description=meta.get("description", ""),
                           frontmatter={k: meta[k] for k in ("name", "description") if k in meta})
        except Exception as e:  # noqa: BLE001 - a skill must never stop the tools from loading
            logger.warning("circuit-bench: skill %s not registered (%s)", name, type(e).__name__)


def register(ctx) -> None:
    """Hermes entry point. Tools and the approval hook are required; command and skill are optional surfaces
    (they only log when they fail). Without the hook the tools refuse real boards (Host.hook_active)."""
    from . import hooks, schemas, tools

    host = tools.Host(cron=_cron_probe(ctx))
    handlers = tools.make_handlers(host)
    for schema in schemas.ALL:
        ctx.register_tool(name=schema["name"], toolset=schemas.TOOLSET, schema=schema,
                          handler=handlers[schema["name"]], emoji=schemas.EMOJI.get(schema["name"], ""))
    try:
        ctx.register_hook("pre_tool_call", hooks.make_pre_tool_call(host))
    except Exception as e:  # noqa: BLE001 - tools stay usable for sim:// and offline work
        logger.error("circuit-bench: approval hook not registered (%s); the tools refuse real boards",
                     type(e).__name__)
    else:
        host.hook_active = True
        hooks.HOOK_ACTIVE = True
    try:
        from . import commands
        ctx.register_command("bench", handler=commands.make_command(host),
                             description="Circuit Bench overview, doctor, ports and projects",
                             args_hint="[doctor|ports|projects]")
    except Exception as e:  # noqa: BLE001
        logger.warning("circuit-bench: /bench not registered (%s)", type(e).__name__)
    try:
        _register_skills(ctx)
    except Exception as e:  # noqa: BLE001
        logger.warning("circuit-bench: bundled skill not registered (%s)", type(e).__name__)
    logger.info("circuit-bench: registered %d tools (pid %s, hook %s)", len(schemas.ALL), os.getpid(),
                "on" if host.hook_active else "off")
