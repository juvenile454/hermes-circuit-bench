import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
CI = ROOT / ".github" / "workflows" / "ci.yml"
# actions the workflow may use, each pinned to a full commit SHA with the release in a comment. Dependabot keeps the
# pins current (.github/dependabot.yml), so the test checks the form and that all jobs share one pin per action.
ACTIONS = {"actions/checkout", "astral-sh/setup-uv", "actions/setup-node", "actions/cache"}
HERMES_TAGS = ["v0.22.5", "v0.23.0", "v0.23.1"]
MACOS_IF = ("github.event.repository.private == false", "github.ref == 'refs/heads/main'", "startsWith(github.ref, 'refs/tags/')",
            "github.event_name == 'workflow_dispatch'", "contains(github.event.head_commit.message, '[macos]')")
# commit SHA of each Hermes release tag (git rev-parse <tag>^{commit}); the workflow refuses a moved tag
HERMES_SHAS = {"v0.22.5": "bf0203a794a07aac3ff764972ab9087baa4e4f4e",
               "v0.23.0": "2bd378ed1b8d6bf2192cb26e0a55ff3091e6bd19",
               "v0.23.1": "3b421578588243f920886e6fe79a6faa87ea026e"}
HERMES_CLONE = "https://github.com/NousResearch/hermes-agent"
HERMES_BIN = '"$RUNNER_TEMP/hermes-agent/.venv/bin/hermes"'


@pytest.fixture(scope="module")
def wf() -> dict:
    return yaml.safe_load(CI.read_text(encoding="utf-8"))


def _runs(job: dict) -> str:
    return "\n".join(str(s.get("run", "")) for s in job["steps"])


def test_ci_dev_deps_match_dev_deps_sh():
    sh = re.search(r"DEV_DEPS='([^']+)'", (ROOT / "scripts" / "dev_deps.sh").read_text()).group(1)
    ci = re.search(r'DEV_DEPS: "([^"]+)"', CI.read_text()).group(1)
    assert sh == ci


def test_ci_triggers_permissions_and_timeouts(wf):
    on = wf.get("on", wf.get(True))  # YAML 1.1 reads the bare key `on` as True
    assert set(on) == {"push", "pull_request", "workflow_dispatch", "schedule"}
    assert wf["permissions"] == {"contents": "read"}
    assert wf["env"]["CIRCUIT_BENCH_HW"] == "off"
    assert set(wf["jobs"]) == {"python", "node", "macos", "hermes"}
    for name, job in wf["jobs"].items():
        assert isinstance(job.get("timeout-minutes"), int) and job["timeout-minutes"] <= 30, name


def test_ci_actions_are_pinned_to_commit_shas():
    pins: dict[str, set[str]] = {}
    for line in CI.read_text(encoding="utf-8").splitlines():
        if "uses:" not in line:
            continue
        m = re.fullmatch(r"\s*(?:- )?uses: ([\w.-]+/[\w.-]+)@([0-9a-f]{40})  # (v\d+\.\d+\.\d+)", line)
        assert m, f"not pinned to a commit SHA with its release: {line.strip()}"
        pins.setdefault(m.group(1), set()).add(f"{m.group(2)} {m.group(3)}")
    assert set(pins) == ACTIONS
    assert all(len(p) == 1 for p in pins.values()), pins


def test_ci_macos_job(wf):
    job = wf["jobs"]["macos"]
    assert job["runs-on"] == "macos-latest"
    cond = " ".join(job["if"].split())
    assert all(part in cond for part in MACOS_IF) and cond.count("||") == 4
    assert cond.startswith("github.event.repository.private == false ||")  # public: every push and pull request
    runs = _runs(job)
    assert "uv venv -p 3.11 .venv" in runs and "$DEV_DEPS" in runs
    assert "lowest" not in runs and "ruff" not in runs
    assert "scripts/fetch_corpus.py" in runs and ".venv/bin/python -m pytest -rs tests" in runs
    assert "node --test tests-js/*.mjs" in runs and "node scripts/build-desktop.mjs --check" in runs
    node = next(s for s in job["steps"] if s.get("uses", "").startswith("actions/setup-node@"))
    assert node["with"]["node-version"] == "22"


def test_ci_linux_jobs_run_on_every_push(wf):
    for name in ("python", "node", "hermes"):
        assert wf["jobs"][name]["runs-on"] == "ubuntu-latest" and "if" not in wf["jobs"][name]


def _hermes_steps(job: dict, tag: str) -> None:
    """Locked source checkout of `tag`, validate with temporary HOME and HERMES_HOME, sim_probe --fast."""
    steps = [s for s in job["steps"] if "run" in s]
    clone = next(s["run"] for s in steps if HERMES_CLONE in s["run"])
    assert f"git clone --depth 1 --branch {tag} " in clone and '"$RUNNER_TEMP/hermes-agent"' in clone
    check = 'test "$(git -C "$RUNNER_TEMP/hermes-agent" rev-parse HEAD)" = '
    assert check in clone and clone.index(check) < clone.index("uv sync"), "the checkout must be compared with the tag SHA"
    assert 'cd "$RUNNER_TEMP/hermes-agent" && uv sync --locked --python 3.14' in clone
    assert "uv pip install" not in _runs(job).replace("uv pip install --python .venv/bin/python", "")
    val = next(s["run"] for s in steps if "plugins validate" in s["run"])
    assert "set -o pipefail" in val
    assert 'export HOME="$RUNNER_TEMP/home" HERMES_HOME="$RUNNER_TEMP/hhome"' in val
    assert f"{HERMES_BIN} plugins validate circuit_bench --install-deps" in val
    assert val.index("export HOME=") < val.index("plugins validate")
    assert "grep -q 'Validation passed'" in val
    assert ".hermes" not in val and "~" not in val
    probe = [s["run"] for s in steps if "scripts/sim_probe.py" in s["run"]]
    assert len(probe) == 1 and probe[0].rstrip().endswith("scripts/sim_probe.py --fast")
    names = [s.get("name", "") for s in job["steps"]]
    assert names.index(next(n for n in names if "validate" in n)) < names.index("sim_probe --fast")


def test_ci_hermes_job(wf):
    job = wf["jobs"]["hermes"]
    matrix = job["strategy"]["matrix"]
    assert job["runs-on"] == "ubuntu-latest" and matrix["hermes"] == HERMES_TAGS
    assert {i["hermes"]: i["sha"] for i in matrix["include"]} == HERMES_SHAS
    clone = next(s["run"] for s in job["steps"] if HERMES_CLONE in s.get("run", ""))
    assert 'rev-parse HEAD)" = "${{ matrix.sha }}"' in clone
    assert job["strategy"]["fail-fast"] is False
    _hermes_steps(job, '"${{ matrix.hermes }}"')
    probe = next(s["run"] for s in job["steps"] if "scripts/sim_probe.py" in s.get("run", ""))
    assert probe.startswith('"$RUNNER_TEMP/hermes-agent/.venv/bin/python" ')
    uv = next(s for s in job["steps"] if s.get("uses", "").startswith("astral-sh/setup-uv@"))
    assert uv["with"]["cache-suffix"] == "hermes-${{ matrix.hermes }}"


def test_ci_macos_runs_hermes_newest_tag(wf):
    job = wf["jobs"]["macos"]
    _hermes_steps(job, HERMES_TAGS[-1])
    assert "Hermes " + HERMES_TAGS[-1] in job["name"]
    clone = next(s["run"] for s in job["steps"] if HERMES_CLONE in s.get("run", ""))
    assert f'rev-parse HEAD)" = {HERMES_SHAS[HERMES_TAGS[-1]]}' in clone
    probe = next(s["run"] for s in job["steps"] if "scripts/sim_probe.py" in s.get("run", ""))
    assert probe == ".venv/bin/python scripts/sim_probe.py --fast"


def test_ci_comments_name_only_public_files():
    text = CI.read_text(encoding="utf-8")
    comments = "\n".join(line.split("#", 1)[1] for line in text.splitlines() if line.lstrip().startswith("#"))
    for private in ("check.sh", "live_guard", "dev_env", "wt.sh", "docs/"):
        assert private not in comments, private
    assert not re.search(r"\b(E|R)[0-9]{1,2}\b", comments)
    for path in re.findall(r"\b(?:scripts|tests)/[\w./*-]+", comments):
        assert list(ROOT.glob(path.rstrip("."))), path


@pytest.mark.parametrize("dev", ["/dev/tty.usbmodem1101", "/dev/tty.usbserial-1", "/dev/cu.usbserial-1",
                                 "/dev/cu.usbmodem1101", b"/dev/tty.usbmodem1101"])
def test_macos_serial_devices_refused(dev):
    import conftest

    with pytest.raises(conftest.HardwareAccessRefused):
        open(dev, "rb")
    with pytest.raises(conftest.HardwareAccessRefused):
        conftest._audit("open", (dev, "rb", 0))


@pytest.mark.parametrize("dev", ["/dev/ttys003", "/dev/ttys000", "/dev/pts/3", "/dev/ptmx", "/dev/tty", "/dev/null"])
def test_pseudo_terminals_stay_allowed(dev):
    import conftest

    assert conftest._SERIAL_DEV.match(dev) is None
    conftest._audit("open", (dev, "rb", 0))  # no HardwareAccessRefused


def test_pty_tests_skip_outside_linux(monkeypatch):
    import conftest

    class Item:
        def __init__(self, *fixtures):
            self.fixturenames, self.marks = fixtures, []

        def add_marker(self, mark):
            self.marks.append(mark)

    pty, plain = Item("tmp_path", "pty_port"), Item("tmp_path")
    monkeypatch.setattr(conftest.sys, "platform", "linux")
    conftest.pytest_collection_modifyitems(None, [pty, plain])
    assert pty.marks == [] and plain.marks == []
    monkeypatch.setattr(conftest.sys, "platform", "darwin")
    conftest.pytest_collection_modifyitems(None, [pty, plain])
    assert [m.name for m in pty.marks] == ["skip"] and plain.marks == []
    assert pty.marks[0].kwargs["reason"] == conftest.PTY_LINUX_ONLY
