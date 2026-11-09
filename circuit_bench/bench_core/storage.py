"""Data folder of the plugin (projects, artifacts, locks).

Inside Hermes: plugins.plugin_storage.plugin_data_dir("circuit-bench") (follows the active profile; resolved on
every call, never cached). Outside Hermes: CIRCUIT_BENCH_DATA_DIR. Never falls back to the home directory.
Development guard: with CIRCUIT_BENCH_DEV_GUARD=1 any folder below the real ~/.hermes that is not under
~/.hermes/cache/scratch is refused (protects the developer's live Hermes from tests and scripts).
"""
from __future__ import annotations

import os
import pwd
from pathlib import Path

from .contracts import BenchError

PLUGIN_NAME = "circuit-bench"
ENV_DATA_DIR = "CIRCUIT_BENCH_DATA_DIR"
ENV_DEV_GUARD = "CIRCUIT_BENCH_DEV_GUARD"


def real_home() -> Path:
    """The account's home from the password database (HOME may be replaced by tests)."""
    return Path(pwd.getpwuid(os.getuid()).pw_dir)


def check_dev_guard(path: Path) -> None:
    if os.environ.get(ENV_DEV_GUARD) != "1":
        return
    live = (real_home() / ".hermes").resolve()
    scratch = live / "cache" / "scratch"
    target = Path(path).resolve()
    if target.is_relative_to(live) and not target.is_relative_to(scratch):
        raise BenchError("invalid_args", f"refusing data folder inside the live Hermes home: {target}",
                         "development guard: use a temporary HERMES_HOME or CIRCUIT_BENCH_DATA_DIR")


def _hermes_data_dir() -> Path | None:
    try:
        from plugins import plugin_storage  # Hermes public plugin API
    except ImportError:
        return None
    return Path(plugin_storage.plugin_data_dir(PLUGIN_NAME))


def data_dir() -> Path:
    """Existing data folder (mode 0700)."""
    path = _hermes_data_dir()
    if path is None:
        env = os.environ.get(ENV_DATA_DIR)
        if not env:
            raise BenchError("dependency_missing", "no data folder: not running inside Hermes",
                             f"set {ENV_DATA_DIR} to a folder for Circuit Bench data")
        path = Path(env).expanduser()
    check_dev_guard(path)
    path.mkdir(parents=True, exist_ok=True)
    try:
        path.chmod(0o700)
    except OSError:
        pass
    return path


def sub_dir(*parts: str) -> Path:
    """data_dir()/parts..., created on demand."""
    p = data_dir().joinpath(*parts)
    p.mkdir(parents=True, exist_ok=True)
    return p
