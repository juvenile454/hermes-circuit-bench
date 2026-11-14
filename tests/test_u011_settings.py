"""Reading Hermes' configuration: the shared reader hermes_value and unreadable plugin settings.

Every test uses a fake ``hermes_cli.config`` (no Hermes in the test environment). ``load_config`` of the fake returns
``state.value`` or raises it when it is an exception, so any exception type can be checked, not only the ones a
particular Hermes release raises.
"""
from __future__ import annotations

import copy
import sys
import types

import pytest

from circuit_bench.bench_core import settings

# Exceptions a config reader may raise: YAML errors are plain Exception subclasses, a broken file gives OSError or
# UnicodeDecodeError, a malformed structure KeyError/TypeError/AttributeError. ImportError is not in the list: it means
# "no Hermes" and has its own tests.
class FakeYAMLError(Exception):
    pass


ERRORS = [RuntimeError("boom"), ValueError("bad"), OSError(13, "denied"), PermissionError(13, "denied"),
          KeyError("plugins"), TypeError("x"), AttributeError("x"), FakeYAMLError("mapping values are not allowed"),
          UnicodeDecodeError("utf-8", b"\xff", 0, 1, "invalid start byte"), RecursionError("deep"), Exception("plain")]


@pytest.fixture
def hermes(monkeypatch):
    """Fake public hermes_cli.config; set .value to what load_config returns (an exception instance is raised)."""
    state = types.SimpleNamespace(value={}, calls=0)
    mod = types.ModuleType("hermes_cli.config")

    def load_config():
        state.calls += 1
        if isinstance(state.value, BaseException):
            raise state.value
        return state.value

    mod.load_config = load_config  # type: ignore[attr-defined]
    pkg = types.ModuleType("hermes_cli")
    pkg.config = mod  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "hermes_cli", pkg)
    monkeypatch.setitem(sys.modules, "hermes_cli.config", mod)
    return state


@pytest.fixture
def no_hermes(monkeypatch):
    """No Hermes in the process: the package hermes_cli is blocked in sys.modules (Python's "not importable")."""
    monkeypatch.setitem(sys.modules, "hermes_cli", None)
    monkeypatch.setitem(sys.modules, "hermes_cli.config", None)


# --------------------------------------------------------------------------------------------- hermes_value

CONFIG = {"approvals": {"timeout": 300, "mode": "manual"},
          "timeouts": {"tools": {"sequential_call": 420, "concurrent_batch": 0}},
          "plugins": {"entries": {"circuit-bench": {"settings": {"hardware_access": False}}}},
          "empty": None, "flag": False, "zero": 0, "list": [1, 2]}


def test_value_found(hermes):
    hermes.value = copy.deepcopy(CONFIG)
    assert settings.hermes_value("approvals", "timeout") == 300
    assert settings.hermes_value("timeouts", "tools", "sequential_call", default=1) == 420
    assert settings.hermes_value("approvals", "mode", default="x") == "manual"


def test_falsy_values_are_values(hermes):
    """0 and False are real values (the serial monitor: 0 = no deadline), only a missing key gives the default."""
    hermes.value = copy.deepcopy(CONFIG)
    assert settings.hermes_value("timeouts", "tools", "concurrent_batch", default=99) == 0
    assert settings.hermes_value("flag", default=True) is False
    assert settings.hermes_value("zero", default=5) == 0


def test_null_counts_as_missing(hermes):
    """A key present but empty in config.yaml (YAML null) is not set: the default, like plugin settings."""
    hermes.value = copy.deepcopy(CONFIG)
    assert settings.hermes_value("empty", default=7) == 7


@pytest.mark.parametrize("path", [("approvals", "missing"), ("missing",), ("missing", "deeper", "still"),
                                  ("approvals", "timeout", "deeper"),  # 300 is not a mapping
                                  ("list", "0"), ("empty", "x")])
def test_missing_key_gives_default(hermes, path):
    hermes.value = copy.deepcopy(CONFIG)
    sentinel = object()
    assert settings.hermes_value(*path, default=sentinel) is sentinel
    assert settings.hermes_value(*path) is None


def test_default_is_none_without_argument(hermes):
    hermes.value = {}
    assert settings.hermes_value("approvals", "timeout") is None


@pytest.mark.parametrize("error", ERRORS, ids=lambda e: type(e).__name__)
def test_any_exception_gives_default(hermes, error):
    hermes.value = error
    assert settings.hermes_value("approvals", "timeout", default=300) == 300
    assert hermes.calls == 1


def test_system_exit_from_the_reader_gives_default(hermes):
    """A config reader that exits must not end the tool call: the reader never raises."""
    hermes.value = SystemExit(1)
    assert settings.hermes_value("approvals", "timeout", default=300) == 300


@pytest.mark.parametrize("value", [None, [], "text", 3, ("approvals",)])
def test_config_that_is_not_a_mapping_gives_default(hermes, value):
    hermes.value = value
    assert settings.hermes_value("approvals", "timeout", default=300) == 300


def test_no_hermes_gives_default(no_hermes):
    assert settings.hermes_value("approvals", "timeout", default=300) == 300


def test_hermes_without_load_config_gives_default(monkeypatch):
    mod = types.ModuleType("hermes_cli.config")  # no load_config attribute
    pkg = types.ModuleType("hermes_cli")
    pkg.config = mod  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "hermes_cli", pkg)
    monkeypatch.setitem(sys.modules, "hermes_cli.config", mod)
    assert settings.hermes_value("approvals", "timeout", default=300) == 300


def test_bad_paths_give_default(hermes):
    hermes.value = copy.deepcopy(CONFIG)
    assert settings.hermes_value(default=1) == 1  # no path: not a value
    assert settings.hermes_value("approvals", 3, default=1) == 1  # type: ignore[arg-type]
    assert settings.hermes_value(None, default=1) == 1  # type: ignore[arg-type]


def test_reader_writes_nothing(hermes, tmp_path):
    """The reader neither changes the loaded config nor hands out a reference into it, and creates no file."""
    original = copy.deepcopy(CONFIG)
    hermes.value = copy.deepcopy(CONFIG)
    got = settings.hermes_value("approvals", default={})
    assert got == original["approvals"]
    got["timeout"] = 1
    got["new"] = True
    assert hermes.value == original
    assert settings.hermes_value("approvals", "timeout") == 300
    assert list((tmp_path / "hhome").iterdir()) == []  # HERMES_HOME of conftest stays empty


# --------------------------------------------------------------------------------------------- unreadable settings

SAFE = {"allow_flash": False, "approve_serial": True, "hardware_access": False}
NUMBERS_AND_PATHS = {k: v for k, v in settings.DEFAULTS.items() if k not in SAFE}
USER = {"hardware_access": True, "allow_flash": True, "approve_serial": False, "default_baud": 9600,
        "monitor_max_seconds": 30, "build_timeout_seconds": 60, "pio_path": "/opt/pio", "esptool_path": "/opt/esptool"}


@pytest.fixture
def from_hermes(monkeypatch, hermes):
    """Settings come from the (fake) Hermes config: no test JSON, real boards allowed by the environment."""
    monkeypatch.delenv(settings.ENV_SETTINGS, raising=False)
    monkeypatch.setenv(settings.ENV_HW, "on")
    monkeypatch.setattr(settings, "_unreadable_logged", False, raising=False)
    return hermes


def _entry(values):
    return {"plugins": {"entries": {"circuit-bench": {"enabled": True, "settings": values}}}}


def _assert_safe(s):
    assert {k: s[k] for k in SAFE} == SAFE
    assert {k: s[k] for k in NUMBERS_AND_PATHS} == NUMBERS_AND_PATHS
    assert settings.hardware_enabled(s) is False


@pytest.mark.parametrize("error", ERRORS, ids=lambda e: type(e).__name__)
def test_load_config_raises_gives_safe_values(from_hermes, error):
    from_hermes.value = error
    s = settings.load()
    _assert_safe(s)
    assert s == {**settings.DEFAULTS, **SAFE}
    assert settings.read_error() == type(error).__name__


def test_safe_values_win_over_nothing_but_the_error(from_hermes):
    """Even a config that allowed everything a moment ago gives the safe values while it cannot be read."""
    from_hermes.value = _entry(USER)
    assert settings.load()["hardware_access"] is True and settings.read_error() is None
    from_hermes.value = RuntimeError("broken")
    _assert_safe(settings.load())
    from_hermes.value = _entry(USER)
    assert settings.load() == {**USER} and settings.read_error() is None  # readable again: the user's values


def test_system_exit_from_load_config_gives_safe_values(from_hermes):
    from_hermes.value = SystemExit(2)
    _assert_safe(settings.load())


def test_broken_hermes_import_gives_safe_values(from_hermes, monkeypatch):
    """hermes_cli is there but its config module fails to import with something other than ImportError."""
    class Broken(types.ModuleType):
        def __getattr__(self, name):
            raise RuntimeError("half-installed")

    monkeypatch.setitem(sys.modules, "hermes_cli.config", Broken("hermes_cli.config"))
    _assert_safe(settings.load())
    assert settings.read_error() == "RuntimeError"


@pytest.mark.parametrize("cfg", [None, [], "plugins: {}", 3,
                                 {"plugins": []}, {"plugins": "x"}, {"plugins": {"entries": ["circuit-bench"]}},
                                 {"plugins": {"entries": {"circuit-bench": "on"}}},
                                 _entry(["hardware_access"]), _entry("hardware_access: false"), _entry(True)],
                         ids=lambda c: repr(c)[:40])
def test_config_of_the_wrong_shape_gives_safe_values(from_hermes, cfg):
    """A config (or plugin entry) that is not a mapping cannot be read either: safe values, not the defaults."""
    from_hermes.value = cfg
    _assert_safe(settings.load())
    assert settings.read_error()


@pytest.mark.parametrize("cfg", [{}, {"plugins": None}, {"plugins": {}}, {"plugins": {"entries": None}},
                                 {"plugins": {"entries": {}}}, {"plugins": {"entries": {"other": {"settings": {}}}}},
                                 {"plugins": {"entries": {"circuit-bench": None}}},
                                 {"plugins": {"entries": {"circuit-bench": {"enabled": True}}}},
                                 _entry(None), _entry({})],
                         ids=lambda c: repr(c)[:60])
def test_readable_config_without_plugin_entry_gives_defaults(from_hermes, cfg):
    """Unchanged: a readable config without plugin settings means the defaults (hardware_access true)."""
    from_hermes.value = cfg
    s = settings.load()
    assert s == settings.DEFAULTS and s["hardware_access"] is True
    assert settings.read_error() is None and settings.invalid_keys() == []
    assert settings.hardware_enabled(s) is True


def test_readable_user_settings_unchanged(from_hermes):
    from_hermes.value = _entry(USER)
    assert settings.load() == USER and settings.read_error() is None


def test_no_hermes_gives_defaults(monkeypatch, no_hermes):
    """Unchanged: without Hermes (ImportError) the defaults apply."""
    monkeypatch.delenv(settings.ENV_SETTINGS, raising=False)
    monkeypatch.setenv(settings.ENV_HW, "on")
    assert settings.load() == settings.DEFAULTS and settings.read_error() is None


@pytest.mark.parametrize("raw", ["{not json", "{\"hardware_access\": true,}", "[]", "[{\"hardware_access\": true}]",
                                 "\"hardware_access\"", "3", "null", "true"])
def test_broken_settings_json_gives_safe_values(monkeypatch, raw):
    monkeypatch.setenv(settings.ENV_SETTINGS, raw)
    monkeypatch.setenv(settings.ENV_HW, "on")
    monkeypatch.setattr(settings, "_unreadable_logged", False, raising=False)
    _assert_safe(settings.load())
    assert settings.read_error() and settings.ENV_SETTINGS in settings.read_error()
    assert settings.invalid_keys() == []


@pytest.mark.parametrize("raw", ["", "  ", "{}"])
def test_empty_settings_json_gives_defaults(monkeypatch, raw):
    monkeypatch.setenv(settings.ENV_SETTINGS, raw)
    monkeypatch.setenv(settings.ENV_HW, "on")
    assert settings.load() == settings.DEFAULTS and settings.read_error() is None


def test_warning_logged_once_per_process(from_hermes, caplog):
    from_hermes.value = RuntimeError("broken")
    with caplog.at_level("WARNING", logger=settings.logger.name):
        for _ in range(5):
            settings.load()
            settings.invalid_keys()
            settings.sim_only_hint()
            settings.hardware_enabled()
    records = [r for r in caplog.records if "could not be read" in r.getMessage()]
    assert len(records) == 1, [r.getMessage() for r in caplog.records]
    assert "RuntimeError" in records[0].getMessage() and "broken" not in records[0].getMessage()


def test_warning_logged_once_also_for_broken_json(monkeypatch, caplog):
    monkeypatch.setenv(settings.ENV_SETTINGS, "{not json")
    monkeypatch.setattr(settings, "_unreadable_logged", False, raising=False)
    with caplog.at_level("WARNING", logger=settings.logger.name):
        for _ in range(3):
            settings.load()
    assert len([r for r in caplog.records if "could not be read" in r.getMessage()]) == 1


SENTENCE = "the plugin settings could not be read from Hermes' configuration, so real boards stay off"


def test_sim_only_hint_names_the_unreadable_settings(from_hermes):
    from_hermes.value = OSError(13, "denied")
    assert SENTENCE in settings.sim_only_hint()
    from_hermes.value = {}
    assert SENTENCE not in settings.sim_only_hint()
    assert "Access real hardware" in settings.sim_only_hint()


def test_sim_only_hint_names_unreadable_settings_also_with_the_hw_switch_off(from_hermes, monkeypatch):
    """Both reasons hold: unsetting CIRCUIT_BENCH_HW alone would not bring the boards back."""
    from_hermes.value = RuntimeError("x")
    monkeypatch.setenv(settings.ENV_HW, "off")
    hint = settings.sim_only_hint()
    assert SENTENCE in hint and settings.ENV_HW in hint


def test_hw_switch_off_still_wins_over_readable_settings(from_hermes, monkeypatch):
    from_hermes.value = _entry(USER)
    monkeypatch.setenv(settings.ENV_HW, "off")
    assert settings.load()["hardware_access"] is False and settings.read_error() is None


# --------------------------------------------------------------------------------------------- doctor

def _settings_check(env):
    return next(c for c in env["checks"] if c["id"] == "doctor.settings")


@pytest.fixture
def no_real_tools(monkeypatch):
    """The doctor must not run a real toolchain from the developer's PlatformIO folder."""
    monkeypatch.delenv("PLATFORMIO_CORE_DIR", raising=False)


@pytest.mark.parametrize("error", [RuntimeError("boom"), OSError(13, "denied"), FakeYAMLError("bad yaml")],
                         ids=lambda e: type(e).__name__)
def test_doctor_names_unreadable_settings(from_hermes, no_real_tools, error):
    from_hermes.value = error
    from circuit_bench.bench_core import doctor
    env = doctor.run()
    assert env["ok"] is True
    chk = _settings_check(env)
    assert chk["status"] == "failed"
    assert "could not be read" in chk["detail"] and type(error).__name__ in chk["detail"]
    warn = next(w for w in env["warnings"] if w["code"] == "settings_unreadable")
    assert warn["severity"] == "caution" and SENTENCE in warn["message"]
    assert env["result"]["hardware"]["hardware_access"] is False and env["result"]["hardware"]["enabled"] is False
    assert env["result"]["settings"]["allow_flash"] is False and env["result"]["settings"]["approve_serial"] is True
    hw_off = next(w for w in env["warnings"] if w["code"] == "hardware_off")
    assert "unreadable" in hw_off["message"]


def test_doctor_names_broken_settings_json(monkeypatch, no_real_tools):
    monkeypatch.setenv(settings.ENV_SETTINGS, "{not json")
    from circuit_bench.bench_core import doctor
    env = doctor.run()
    chk = _settings_check(env)
    assert chk["status"] == "failed" and settings.ENV_SETTINGS in chk["detail"]
    assert "settings_unreadable" in {w["code"] for w in env["warnings"]}


def test_doctor_readable_settings_unchanged(from_hermes, no_real_tools, monkeypatch):
    monkeypatch.setenv(settings.ENV_HW, "off")  # the doctor would list the real ports otherwise
    from_hermes.value = {}
    from circuit_bench.bench_core import doctor
    env = doctor.run()
    assert _settings_check(env) == {"id": "doctor.settings", "status": "passed", "detail": "all settings readable"}
    assert "settings_unreadable" not in {w["code"] for w in env["warnings"]}
    assert env["result"]["settings"]["allow_flash"] is False and env["result"]["settings"]["approve_serial"] is True


# --------------------------------------------------------------------------------------------- failed config read
# Hermes' load_config does not raise on a broken config.yaml: it returns a dict subclass with ``read_error`` set
# (the last known good config or Hermes' defaults). The plugin checks the attribute, it does not import the class.

class FailedRead(dict):
    def __init__(self, data=None, error=None):
        super().__init__(data or {})
        self.read_error = error


@pytest.mark.parametrize("error", [OSError(13, "denied"), FakeYAMLError("bad yaml"), ValueError("not a mapping"),
                                   "a text reason", True], ids=repr)
def test_failed_read_without_plugin_entry_gives_safe_values(from_hermes, error):
    from_hermes.value = FailedRead({"approvals": {"mode": "manual"}}, error)
    s = settings.load()
    _assert_safe(s)
    assert s == {**settings.DEFAULTS, **SAFE}
    assert settings.read_error()


def test_failed_read_with_last_known_good_entry_still_gives_safe_values(from_hermes):
    """The last known good config allowed real boards and flashing: while the file is broken it is not used."""
    from_hermes.value = FailedRead(_entry({**USER, "hardware_access": True, "allow_flash": True}), OSError(5, "io"))
    s = settings.load()
    assert s == {**settings.DEFAULTS, **SAFE}  # numbers and paths: defaults, not the last known good values
    assert settings.read_error() == "config.yaml could not be read (OSError)"
    assert SENTENCE in settings.sim_only_hint()


def test_read_error_none_counts_as_readable(from_hermes):
    from_hermes.value = FailedRead(_entry(USER), None)
    assert settings.load() == USER and settings.read_error() is None


def test_failed_read_logged_once(from_hermes, caplog):
    from_hermes.value = FailedRead({}, OSError(13, "secret path /srv/x"))
    with caplog.at_level("WARNING", logger=settings.logger.name):
        for _ in range(4):
            settings.load()
    records = [r.getMessage() for r in caplog.records if "could not be read" in r.getMessage()]
    assert len(records) == 1 and "secret path" not in records[0]


def test_wrong_shape_logged_once(from_hermes, caplog):
    from_hermes.value = _entry("hardware_access: false")
    with caplog.at_level("WARNING", logger=settings.logger.name):
        for _ in range(4):
            settings.load()
    assert len([r for r in caplog.records if "could not be read" in r.getMessage()]) == 1


@pytest.mark.parametrize("level", ["cfg", "plugins", "entries", "entry", "settings"])
def test_each_level_that_is_not_a_mapping_gives_safe_values(from_hermes, level):
    cfg = {"plugins": {"entries": {"circuit-bench": {"settings": {"hardware_access": True}}}}}
    if level == "cfg":
        cfg = ["plugins"]
    elif level == "plugins":
        cfg["plugins"] = ["entries"]
    elif level == "entries":
        cfg["plugins"]["entries"] = "circuit-bench"
    elif level == "entry":
        cfg["plugins"]["entries"]["circuit-bench"] = 1
    else:
        cfg["plugins"]["entries"]["circuit-bench"]["settings"] = ["hardware_access"]
    from_hermes.value = cfg
    _assert_safe(settings.load())
    assert settings.read_error()


def test_failed_read_doctor(from_hermes, no_real_tools):
    from_hermes.value = FailedRead(_entry({"hardware_access": True}), FakeYAMLError("x"))
    from circuit_bench.bench_core import doctor
    env = doctor.run()
    assert _settings_check(env)["status"] == "failed"
    assert "settings_unreadable" in {w["code"] for w in env["warnings"]}
    assert env["result"]["hardware"]["enabled"] is False


def test_hermes_value_on_failed_read_gives_default(hermes):
    """The last known good values are not handed out either."""
    hermes.value = FailedRead({"approvals": {"timeout": 60}}, OSError(13, "denied"))
    assert settings.hermes_value("approvals", "timeout", default=300) == 300


def test_hermes_value_not_a_mapping_in_between(hermes):
    hermes.value = {"timeouts": {"tools": ["sequential_call"]}, "approvals": "manual"}
    assert settings.hermes_value("timeouts", "tools", "sequential_call", default=420) == 420
    assert settings.hermes_value("approvals", "timeout", default=300) == 300


def test_hermes_value_returns_the_raw_value(hermes):
    """No type check or conversion: the callers check the type."""
    hermes.value = {"approvals": {"timeout": "300"}, "timeouts": {"tools": {"sequential_call": -1.5}}}
    assert settings.hermes_value("approvals", "timeout", default=1) == "300"
    assert settings.hermes_value("timeouts", "tools", "sequential_call", default=1) == -1.5


def test_hermes_value_uses_load_config_not_the_readonly_variant(from_hermes):
    hermes = from_hermes
    mod = sys.modules["hermes_cli.config"]

    def readonly():
        raise AssertionError("load_config_readonly must not be used")

    mod.load_config_readonly = readonly  # type: ignore[attr-defined]
    hermes.value = {"approvals": {"timeout": 9}}
    assert settings.hermes_value("approvals", "timeout") == 9
    assert settings.load() == settings.DEFAULTS
    assert hermes.calls == 2


# --------------------------------------------------------------------------------------------- which import failure
# Only a missing package hermes_cli means "no Hermes" (tests, any run outside Hermes). Every other failure while
# importing hermes_cli.config or load_config means Hermes is there but its settings cannot be read: the safe values.

PERMISSIVE = {"plugins": {"entries": {"circuit-bench": {"settings": {"hardware_access": True, "allow_flash": True,
                                                                      "approve_serial": False}}}}}
_PERMISSIVE_SRC = f"\n\ndef load_config():\n    return {PERMISSIVE!r}\n"

# fake Hermes packages on disk: file name -> source; the real import machinery raises the error
BROKEN_PACKAGES = {
    # a Hermes whose config module has no load_config (renamed in a future release): ImportError "cannot import name"
    "no_load_config": {"__init__.py": "", "config.py": f"def read_config():\n    return {PERMISSIVE!r}\n"},
    # the config module fails on a missing dependency (ModuleNotFoundError, name of the dependency)
    "missing_dependency": {"__init__.py": "",
                           "config.py": "import cb_missing_dependency_for_tests  # noqa: F401" + _PERMISSIVE_SRC},
    "missing_yaml": {"__init__.py": "",
                     "config.py": "raise ModuleNotFoundError(\"No module named 'yaml'\", name='yaml')" + _PERMISSIVE_SRC},
    # the package itself is there but fails to import on a missing dependency
    "package_init_fails": {"__init__.py": "import cb_missing_dependency_for_tests  # noqa: F401\n",
                           "config.py": _PERMISSIVE_SRC},
    # a plain ImportError (e.g. a C extension that does not load)
    "plain_import_error": {"__init__.py": "", "config.py": "raise ImportError('extension failed to load')" +
                           _PERMISSIVE_SRC},
    # the package is there, its config module is missing (ModuleNotFoundError, name "hermes_cli.config")
    "no_config_module": {"__init__.py": ""},
}
BROKEN_KINDS = [*BROKEN_PACKAGES, "module_without_config", "module_without_load_config"]


@pytest.fixture
def clean_hermes_modules():
    """No hermes_cli module in sys.modules during the test; whatever the test imports is removed afterwards."""
    saved = {n: m for n, m in sys.modules.items() if n == "hermes_cli" or n.startswith("hermes_cli.")}
    for name in saved:
        del sys.modules[name]
    yield
    for name in [n for n in sys.modules if n == "hermes_cli" or n.startswith("hermes_cli.")]:
        del sys.modules[name]
    sys.modules.update(saved)


@pytest.fixture(params=BROKEN_KINDS)
def broken_hermes(request, monkeypatch, tmp_path, clean_hermes_modules):
    """A Hermes that is there but whose config reader cannot be imported; settings come from Hermes, HW switch on."""
    kind = request.param
    if kind in BROKEN_PACKAGES:
        pkg = tmp_path / "fake_hermes" / "hermes_cli"
        pkg.mkdir(parents=True)
        for name, source in BROKEN_PACKAGES[kind].items():
            (pkg / name).write_text(source, encoding="utf-8")
        monkeypatch.syspath_prepend(str(pkg.parent))
    elif kind == "module_without_config":  # a module, not a package: "'hermes_cli' is not a package"
        monkeypatch.setitem(sys.modules, "hermes_cli", types.ModuleType("hermes_cli"))
    else:  # module_without_load_config
        mod = types.ModuleType("hermes_cli.config")
        mod.read_config = lambda: copy.deepcopy(PERMISSIVE)  # type: ignore[attr-defined]
        pkg_mod = types.ModuleType("hermes_cli")
        pkg_mod.config = mod  # type: ignore[attr-defined]
        monkeypatch.setitem(sys.modules, "hermes_cli", pkg_mod)
        monkeypatch.setitem(sys.modules, "hermes_cli.config", mod)
    monkeypatch.delenv(settings.ENV_SETTINGS, raising=False)
    monkeypatch.delenv(settings.ENV_DEV_GUARD, raising=False)
    monkeypatch.setenv(settings.ENV_HW, "on")
    monkeypatch.setattr(settings, "_unreadable_logged", False, raising=False)
    return kind


def test_broken_hermes_import_is_hermes_with_unreadable_settings(broken_hermes):
    s = settings.load()
    _assert_safe(s)
    assert s == {**settings.DEFAULTS, **SAFE}
    assert s["hardware_access"] is False and s["allow_flash"] is False and s["approve_serial"] is True
    assert settings.read_error()
    assert SENTENCE in settings.sim_only_hint()


def test_broken_hermes_import_hermes_value_gives_default(broken_hermes):
    assert settings.hermes_value("approvals", "timeout", default=300) == 300
    assert settings.hermes_value("plugins", "entries", "circuit-bench", "settings", "hardware_access") is None


def test_broken_hermes_import_settings_json_needs_dev_guard(broken_hermes, monkeypatch):
    """Hermes is there: a leftover test switch must not turn on real boards or flashing."""
    monkeypatch.setenv(settings.ENV_SETTINGS, '{"allow_flash": true, "hardware_access": true}')
    assert settings.env_settings_allowed() is False and settings.env_settings_ignored() is True
    s = settings.load()
    assert s["allow_flash"] is False and s["hardware_access"] is False and s["approve_serial"] is True
    assert settings.read_error()
    monkeypatch.setenv(settings.ENV_DEV_GUARD, "1")  # development: the test switch counts
    assert settings.env_settings_allowed() is True
    assert settings.load()["allow_flash"] is True and settings.read_error() is None


def test_broken_hermes_import_doctor(broken_hermes, no_real_tools):
    from circuit_bench.bench_core import doctor
    env = doctor.run()
    assert env["ok"] is True
    chk = _settings_check(env)
    assert chk["status"] == "failed" and "could not be read" in chk["detail"]
    assert "settings_unreadable" in {w["code"] for w in env["warnings"]}
    assert env["result"]["hardware"]["enabled"] is False
    assert env["result"]["settings"]["allow_flash"] is False and env["result"]["settings"]["approve_serial"] is True


def test_broken_hermes_import_logged_once(broken_hermes, caplog):
    with caplog.at_level("WARNING", logger=settings.logger.name):
        for _ in range(3):
            settings.load()
    assert len([r for r in caplog.records if "could not be read" in r.getMessage()]) == 1


def _assert_outside_hermes(monkeypatch):
    monkeypatch.delenv(settings.ENV_SETTINGS, raising=False)
    monkeypatch.delenv(settings.ENV_DEV_GUARD, raising=False)
    monkeypatch.setenv(settings.ENV_HW, "on")
    assert settings.load() == settings.DEFAULTS and settings.read_error() is None
    assert settings.env_settings_allowed() is True
    assert settings.hermes_value("approvals", "timeout", default=300) == 300
    monkeypatch.setenv(settings.ENV_SETTINGS, '{"allow_flash": true}')  # outside Hermes the test switch counts
    assert settings.load()["allow_flash"] is True and settings.env_settings_ignored() is False


def test_package_blocked_in_sys_modules_is_no_hermes(monkeypatch, no_hermes):
    """Unchanged: sys.modules["hermes_cli"] = None is a missing package, the defaults apply."""
    _assert_outside_hermes(monkeypatch)


def test_only_the_package_blocked_is_no_hermes(monkeypatch, clean_hermes_modules):
    """sys.modules["hermes_cli"] = None alone (no entry for the submodule): the defaults apply."""
    monkeypatch.setitem(sys.modules, "hermes_cli", None)
    _assert_outside_hermes(monkeypatch)


def test_package_really_missing_is_no_hermes(monkeypatch, clean_hermes_modules):
    """Unchanged: no hermes_cli anywhere on the path (the test environment), the defaults apply."""
    import importlib.util
    importlib.invalidate_caches()
    if importlib.util.find_spec("hermes_cli") is not None:
        pytest.skip("hermes_cli is installed in this environment")
    _assert_outside_hermes(monkeypatch)


# ------------------------------------------------------------------- hermes_value with the last known good values
# Hermes keeps working with its fallback while config.yaml cannot be read (the last known good config, its defaults
# or nothing). A caller that must agree with Hermes (the serial monitor's deadline) asks for it explicitly; the
# default and the plugin settings stay at "unreadable".

LKG_CONFIG = {"approvals": {"timeout": 60}, "timeouts": {"tools": {"sequential_call": 60, "concurrent_batch": 0}},
              "plugins": {"entries": {"circuit-bench": {"settings": {**USER, "hardware_access": True,
                                                                       "allow_flash": True}}}},
              "empty": None, "flag": False}


@pytest.mark.parametrize("error", [OSError(13, "denied"), FakeYAMLError("bad yaml"), ValueError("x")],
                         ids=lambda e: type(e).__name__)
def test_last_known_good_reads_the_fallback(hermes, error):
    hermes.value = FailedRead(copy.deepcopy(LKG_CONFIG), error)
    assert settings.hermes_value("timeouts", "tools", "sequential_call", default=420, last_known_good=True) == 60
    assert settings.hermes_value("timeouts", "tools", "concurrent_batch", default=420, last_known_good=True) == 0
    assert settings.hermes_value("approvals", "timeout", default=300, last_known_good=True) == 60
    assert settings.hermes_value("flag", default=True, last_known_good=True) is False


def test_last_known_good_keeps_the_rules_of_a_readable_config(hermes):
    """Missing key, null, a level that is not a mapping: the default, as for a readable config."""
    hermes.value = FailedRead({"timeouts": "broken", "approvals": {"timeout": None}, "list": [1]}, ValueError("x"))
    assert settings.hermes_value("timeouts", "tools", "sequential_call", default=7, last_known_good=True) == 7
    assert settings.hermes_value("approvals", "timeout", default=7, last_known_good=True) == 7
    assert settings.hermes_value("missing", default=7, last_known_good=True) == 7
    assert settings.hermes_value("list", "x", default=7, last_known_good=True) == 7


def test_last_known_good_returns_a_copy(hermes):
    fallback = FailedRead(copy.deepcopy(LKG_CONFIG), ValueError("x"))
    hermes.value = fallback
    tools = settings.hermes_value("timeouts", "tools", last_known_good=True)
    tools["sequential_call"] = 1
    assert fallback["timeouts"]["tools"]["sequential_call"] == 60


def test_empty_fallback_gives_default_with_the_switch(hermes):
    hermes.value = FailedRead({}, ValueError("x"))
    assert settings.hermes_value("timeouts", "tools", "sequential_call", default=420, last_known_good=True) == 420


def test_without_the_switch_the_fallback_still_gives_default(hermes):
    hermes.value = FailedRead(copy.deepcopy(LKG_CONFIG), OSError(5, "io"))
    assert settings.hermes_value("timeouts", "tools", "sequential_call", default=420) == 420
    assert settings.hermes_value("timeouts", "tools", "sequential_call", default=420, last_known_good=False) == 420
    assert settings.hermes_value("approvals", "timeout", default=300) == 300


def test_readable_config_same_with_and_without_the_switch(hermes):
    hermes.value = copy.deepcopy(CONFIG)
    for path, default in [(("approvals", "timeout"), 1), (("timeouts", "tools", "concurrent_batch"), 9),
                          (("empty",), 3), (("missing",), 4), (("list",), None)]:
        assert settings.hermes_value(*path, default=default, last_known_good=True) == \
            settings.hermes_value(*path, default=default)


def test_plugin_settings_ignore_the_fallback(from_hermes):
    """The fallback allows real boards and flashing: settings.load() keeps the safe values all the same."""
    from_hermes.value = FailedRead(copy.deepcopy(LKG_CONFIG), FakeYAMLError("bad yaml"))
    assert settings.hermes_value("timeouts", "tools", "sequential_call", last_known_good=True) == 60  # read first
    s = settings.load()
    _assert_safe(s)
    assert s["hardware_access"] is False and s["allow_flash"] is False and s["approve_serial"] is True
    assert s == {**settings.DEFAULTS, **SAFE}
    assert settings.read_error() == "config.yaml could not be read (FakeYAMLError)"
    assert settings.hermes_value("timeouts", "tools", "sequential_call", last_known_good=True) == 60  # and after


@pytest.mark.parametrize("error", ERRORS, ids=lambda e: type(e).__name__)
def test_load_config_raises_gives_default_with_the_switch(hermes, error):
    hermes.value = error
    assert settings.hermes_value("approvals", "timeout", default=300, last_known_good=True) == 300
    assert settings.hermes_value("approvals", "timeout", default=300) == 300


def test_system_exit_gives_default_with_the_switch(hermes):
    hermes.value = SystemExit(1)
    assert settings.hermes_value("approvals", "timeout", default=300, last_known_good=True) == 300


@pytest.mark.parametrize("value", [["approvals"], "approvals: 1", 3, None])
def test_root_not_a_mapping_gives_default_with_the_switch(hermes, value):
    hermes.value = value
    assert settings.hermes_value("approvals", default=300, last_known_good=True) == 300
    assert settings.hermes_value("approvals", default=300) == 300


@pytest.mark.parametrize("value", [["approvals"], "approvals: 1"])
def test_failed_read_root_not_a_mapping_gives_default_with_the_switch(hermes, value):
    class FailedList(list):
        read_error = ValueError("x")

    class FailedStr(str):
        read_error = ValueError("x")

    hermes.value = FailedList(value) if isinstance(value, list) else FailedStr(value)
    assert settings.hermes_value("approvals", default=300, last_known_good=True) == 300


def test_no_hermes_gives_default_with_the_switch(no_hermes):
    assert settings.hermes_value("approvals", "timeout", default=300, last_known_good=True) == 300


def test_broken_hermes_import_gives_default_with_the_switch(broken_hermes):
    assert settings.hermes_value("approvals", "timeout", default=300, last_known_good=True) == 300


def test_the_switch_never_raises(hermes):
    class Odd(dict):
        read_error = ValueError("x")

        def __contains__(self, key):
            raise RuntimeError("odd")

    class Uncopyable:
        def __deepcopy__(self, memo):
            raise RuntimeError("no copy")

    class BadAttr(dict):
        @property
        def read_error(self):
            raise RuntimeError("attribute")

    hermes.value = Odd({"a": 1})
    assert settings.hermes_value("a", default=5, last_known_good=True) == 5
    hermes.value = FailedRead({"a": Uncopyable()}, ValueError("x"))
    assert settings.hermes_value("a", default=5, last_known_good=True) == 5
    hermes.value = BadAttr({"a": 1})
    assert settings.hermes_value("a", default=5, last_known_good=True) == 5
    assert settings.hermes_value(default=5, last_known_good=True) == 5
    assert settings.hermes_value(1, default=5, last_known_good=True) == 5  # type: ignore[arg-type]
