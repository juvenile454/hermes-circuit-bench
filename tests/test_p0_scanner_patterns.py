"""The plugin package stays clear of patterns that Hermes' install scanner (tools/skills_guard.py) rates high,
so `hermes plugins validate` reports no security caution for text that cannot act (hints, UI strings)."""
import re
from pathlib import Path

PKG = Path(__file__).resolve().parents[1] / "circuit_bench"
HIGH = {
    "sudo_usage": re.compile(r"\bsudo\b(?!\.\w)"),
    "inline_shell_exec": re.compile(r"!`[^`\s][^`\n]*`"),
}


def test_no_high_scanner_patterns_in_the_package():
    hits = []
    for path in sorted(PKG.rglob("*")):
        if path.suffix not in (".py", ".js", ".md", ".json", ".yaml", ".txt") or "__pycache__" in path.parts:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for name, rx in HIGH.items():
            for m in rx.finditer(text):
                line = text.count("\n", 0, m.start()) + 1
                hits.append(f"{name}: {path.relative_to(PKG)}:{line}: {m.group(0)[:40]}")
    assert hits == []
