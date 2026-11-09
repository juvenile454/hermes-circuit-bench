"""Public texts state the documented limits: one-shot runs, --enable, the serial approval switch, offline-only chips,
the Hermes tool-call deadline, the manifest description and the skill's refusal hints."""
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
README = ROOT / "README.md"
SECURITY = ROOT / "SECURITY.md"
CHANGELOG = ROOT / "CHANGELOG.md"
MANIFEST = ROOT / "circuit_bench" / "plugin.yaml"
SKILL = ROOT / "circuit_bench" / "skills" / "esp32-bench" / "SKILL.md"
GAP = ("A session-scoped `/yolo` and one-shot runs (`hermes -z`, which bypass approvals by design) are not visible to "
       "plugins: there Hermes passes agent builds, flashes and port openings without asking. Keep **Allow flashing real "
       "boards** off while you use them.")
SERIAL_SWITCH = "while **Ask before opening serial ports** is on"


def _flat(path: Path) -> str:
    return " ".join(path.read_text(encoding="utf-8").split())


def _section(text: str, heading: str) -> str:
    """The flattened text from ``heading`` up to the next level-2 or level-3 heading."""
    start = text.index(heading + " ")
    nxt = re.compile(r" #{2,3} ").search(text, start + len(heading))
    return text[start:nxt.start() if nxt else None]


GAP_REF = "Session-scoped `/yolo` and one-shot runs (`hermes -z`) pass agent builds, flashes and port openings without asking"


def test_one_shot_gap_is_disclosed_in_every_place():
    """Full text where safety and disclosure are read (catalog rule 13); the limit lists point back to it."""
    readme = _flat(README)
    for heading in ("## Safety", "## Disclosure"):
        assert GAP in _section(readme, heading), heading
    limits = _section(readme, "## Limits")
    assert GAP_REF in limits and "(see [Safety](#safety))" in limits
    security = _flat(SECURITY)
    assert "outside the documented `/yolo`, `hermes -z` and `approvals.mode: off` cases" in security
    assert GAP in security
    changelog = _flat(CHANGELOG)
    assert GAP in _section(changelog, "### Safety")
    known = _section(changelog, "### Known limits")
    assert GAP_REF in known and "see Safety above" in known


def test_install_commands_enable_the_plugin():
    readme = _flat(README)
    quick, install = _section(readme, "## Try it in 60 seconds"), _section(readme, "## Install")
    repo = re.compile(r'`hermes plugins install "https://github\.com/[\w.-]+/hermes-circuit-bench#circuit_bench" --enable`')
    assert "`hermes plugins install circuit-bench --enable`" in quick and repo.search(quick)
    assert "Not in your catalog yet? Install from the repository:" in quick and "Until the catalog" not in readme
    assert "hermes plugins install circuit-bench --enable" in install and repo.search(install)
    assert not re.search(r'#circuit_bench"(?! --enable)', readme)
    assert 'Without `--enable`, answer "Enable now?" with y; otherwise the tools and the Bench backend stay off.' in install
    assert not re.search(r"hermes plugins install circuit-bench(?! --enable)", readme)


def test_serial_approval_is_conditional():
    assert SERIAL_SWITCH in _flat(SECURITY)
    assert SERIAL_SWITCH in _section(_flat(CHANGELOG), "### Agent half")
    disclosure = _section(_flat(README), "## Disclosure")
    assert "after approval while **Ask before opening serial ports** is on, the default" in disclosure
    assert SERIAL_SWITCH in disclosure[disclosure.index("**Approvals:**"):]


def test_c3_is_named_as_offline_only():
    phrase = "ESP32-C3, ESP32-S2 and ESP32-C6 are checked offline only"
    assert phrase in _flat(README) and phrase in _flat(CHANGELOG)
    for path in (README, CHANGELOG):
        assert "ESP32-S2 and ESP32-C6 are checked offline only" not in _flat(path).replace(phrase, ""), path


def test_tool_call_deadline_is_a_documented_limit():
    assert ("Hermes ends a tool call after 420 s by default (`timeouts.tools.sequential_call`); a first build of a new "
            "platform can take longer: start it from the Bench (05 FLASH) or raise that timeout.") in _flat(README)


def test_fix_with_hermes_label_matches_the_button():
    assert "**Fix with Hermes ›**" not in _flat(README) and "**Fix with Hermes**" in _flat(README)


def test_manifest_description_is_two_sentences():
    desc = yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))["description"]
    assert len(desc) <= 300 and desc.endswith(".")
    assert len(re.findall(r"[.!?](?:\s|$)", desc)) == 2, desc
    assert "180 cited modules" in desc


def test_skill_explains_refusals_and_replanning():
    text = _flat(SKILL)
    for needle in ("`allow_flash` must be on for real boards (`sim://` is not affected)",
                   "C3, S2 and C6 are checked offline only (data, build, decode), not on a real board",
                   ("Run `bench_solder plan` with `project` once the parts are complete, and again after `add_parts`, "
                    "`remove_parts` or `add_module`; the Bench SOLDER station stays empty until then"),
                   ("`not_confirmed`: a precondition is missing (project, detected board, successful build, approval) or "
                    "the board changed: follow the hint."),
                   "`elf_missing`: the build output is incomplete: build again.",
                   "Pass `project` to `bench_crash` so it finds the ELF (functions, files, lines)."):
        assert needle in text, needle
    assert "other board: USB serial or MAC differ" not in text


def test_headless_install_needs_yes_deps():
    readme = _flat(README)
    assert "Without a terminal (script, SSH, an agent) add `--yes-deps`." in _section(readme, "## Try it in 60 seconds")
    assert ("Without a terminal (scripts, SSH, an agent) it cannot ask and skips them, and the plugin stays off: add "
            "`--yes-deps`.") in _section(readme, "## Install")


def test_tool_path_settings_name_the_searched_folders():
    settings = yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))["config_schema"]
    assert settings["esptool_path"]["description"].endswith("Empty: search PATH and ~/.local/bin.")
    assert settings["pio_path"]["description"].endswith("Empty: search PATH, ~/.platformio/penv/bin and ~/.local/bin.")


def test_erase_is_described_precisely():
    for path in (README, CHANGELOG):
        assert not re.search(r"no erase(?! beyond the written sectors)", _flat(path)), path


def test_readme_anchor_links_point_to_headings():
    text = README.read_text(encoding="utf-8")
    slugs = {re.sub(r"[^\w\- ]", "", h.strip().lower()).replace(" ", "-") for h in re.findall(r"^#{2,3} (.+)$", text, re.M)}
    anchors = set(re.findall(r"\]\(#([\w-]+)\)", text))
    assert anchors and anchors <= slugs, anchors - slugs


SIM_BUILD = ("A build for a `sim://` board asks in the same way when it really runs PlatformIO (`pio` and every package "
             "installed); otherwise it is simulated, runs nothing and never asks.")


def test_build_approval_follows_what_runs():
    for path in (README, CHANGELOG):
        text = _flat(path)
        assert "agent build that starts PlatformIO asks through" in text and SIM_BUILD in text, path
        assert "not `sim://`" not in text and "imulated builds never ask" not in text, path
    assert "From the chat, Hermes asks before every build that starts PlatformIO" in _flat(README)
    assert "on `sim://` too when `pio` really runs" in _flat(SKILL)


def test_crash_decoding_is_not_listed_as_running_project_code():
    readme = _flat(README)
    assert "`pio project metadata` (also for flash) and uploads run" in readme
    assert "Crash decoding from the chat runs only `addr2line` on the ELF of the last build." in readme


def test_limits_name_what_is_not_analysed():
    limits = _section(_flat(README), "## Limits")
    assert "Discrete parts in a project (resistors, LEDs, transistors) get no electrical check of their own" in limits
    assert "A divider output above the pin's 3.6 V maximum is a danger warning" in limits
    assert "above the 40 mA a pin typically drives is a caution" in limits
    assert "GPIO current limits" not in limits
    assert "Discrete parts get no check of their own (assumption `discrete_parts`)" in _flat(SKILL)


def test_doctor_line_says_the_simulation_needs_no_tools():
    assert "hardware switch (the simulation needs none of the tools)." in _flat(README)
