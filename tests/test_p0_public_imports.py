"""Catalog rule 9 (public surfaces only): circuit_bench imports from Hermes only what Hermes documents for plugins.

The allowlist is the subset of `_PUBLIC` in hermes_cli/plugin_validate_private_imports.py (Hermes main, 06.11.2026)
that this plugin may use. `hermes plugins validate` warns about anything else ("private core imports").
"""
import ast
from pathlib import Path

PKG = Path(__file__).resolve().parent.parent / "circuit_bench"
HERMES_TOP = {"agent", "cli", "cron", "gateway", "hermes_cli", "hermes_constants", "hermes_platform", "hermes_state",
              "plugins", "pm", "providers", "tools", "utils", "acp_adapter", "run_agent", "model_tools", "toolsets"}
ALLOWED_MODULES = {"hermes_cli.config", "hermes_cli.plugin_events", "plugins.plugin_storage", "plugins.plugin_utils",
                   "cron.execution_identity", "hermes_constants", "tools.registry"}


def _hermes_imports(path: Path):
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield node.lineno, alias.name
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            if node.module in ("plugins", "hermes_cli", "cron", "tools"):  # `from plugins import plugin_storage`
                for alias in node.names:
                    yield node.lineno, f"{node.module}.{alias.name}"
            else:
                yield node.lineno, node.module


def test_only_public_hermes_imports():
    bad = []
    for path in PKG.rglob("*.py"):
        for line, module in _hermes_imports(path):
            if module.split(".")[0] in HERMES_TOP and module not in ALLOWED_MODULES:
                bad.append(f"{path.relative_to(PKG)}:{line} {module}")
    assert bad == [], "private Hermes imports (catalog rule 9): " + ", ".join(bad)
