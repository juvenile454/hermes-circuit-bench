"""Solder helper: BOM -> ordered solder steps with hints, progress by stable step ids.

Public action functions (result envelope):
- ``plan(parts)`` -> ``solder.plan``: ``result = {"steps", "parts_total", "unknown_parts", "unclear_parts"}``.
  ``parts`` is anything ``bom.parse`` accepts (CSV with or without a header row, list text, rows, or the project's parts).
- ``step(plan, step_id, done)`` -> ``solder.step``: marks one step done/undone and returns the progress.

Helpers for callers that hold a project: ``rows_from_parts(parts)`` (the BOM rows ``plan`` gets from the project's
parts) and ``plan_state(project)`` (whether the stored plan still covers the parts).

Step objects: ``{"id", "n", "refs", "kind", "action", "hints": [{"code", "severity", "text", "source_ids"}]}``.
One step per kind (parts of an unknown kind get one step each). Order and hints come from
``data/solder/rules.json``: mechanical parts last, before that low before tall, robust before heat-sensitive
(``rule-of-thumb``). Hints cite manufacturer documents in ``data/sources/solder.json``; there are no
temperature numbers, because no part datasheet is known for a BOM line.
"""
from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable, Mapping
from typing import Any

from . import bom, sources
from .contracts import BenchError, assumption, envelope, format_si, from_error, warning

ACTION_PLAN = "solder.plan"
ACTION_STEP = "solder.step"
_SEVERITY_RANK = {"danger": 0, "caution": 1, "info": 2}
_MAX_VALUES_SHOWN = 6
_MAX_VALUE_CHARS = 40
_ORIENTATION_CODES = ("polarity", "pinout", "orientation")
_PLAN_HINT = "pass the plan returned by solder.plan, or the project's solder object {steps, done}"


def step_id(kind: str, refs: Iterable[str]) -> str:
    """Stable step id: ``sha1(kind + sorted refs)[:10]``, canonical text ``"<kind>:<R1>,<R2>,..."``."""
    canon = f"{kind}:{','.join(sorted(str(r).upper() for r in refs))}"
    return hashlib.sha1(canon.encode("utf-8"), usedforsecurity=False).hexdigest()[:10]


def _natural(ref: str) -> tuple[str, int, str]:
    m = re.match(r"^([A-Z_]*?)(\d+)(.*)$", ref)
    return (m.group(1), int(m.group(2)), m.group(3)) if m else (ref, -1, "")


def sort_refs(refs: Iterable[str]) -> list[str]:
    """R1, R2, R10 (natural order)."""
    return sorted(refs, key=_natural)


def compress_refs(refs: Iterable[str]) -> str:
    """'R1-R4, R7' for display (natural order, runs of three or more become ranges)."""
    out: list[str] = []
    run: list[tuple[str, int]] = []

    def flush() -> None:
        if len(run) >= 3:
            out.append(f"{run[0][0]}{run[0][1]}-{run[-1][0]}{run[-1][1]}")
        else:
            out.extend(f"{p}{n}" for p, n in run)
        run.clear()

    for ref in sort_refs(refs):
        prefix, num, rest = _natural(ref)
        if num < 0 or rest:
            flush()
            out.append(ref)
            continue
        if run and (run[-1][0] != prefix or run[-1][1] + 1 != num):
            flush()
        run.append((prefix, num))
    flush()
    return ", ".join(out)


def _short(value: str) -> str:
    value = " ".join(value.split())
    return value if len(value) <= _MAX_VALUE_CHARS else value[: _MAX_VALUE_CHARS - 1] + "…"


def _what(rule: Mapping[str, Any], parts: list[dict[str, Any]]) -> str:
    label = rule["label"][0 if len(parts) == 1 else 1]
    refs = [p["ref"] for p in parts]
    values = {p["value"] for p in parts}
    if len(values) == 1 and next(iter(values)):
        return f"{label} {compress_refs(refs)} ({_short(next(iter(values)))})"
    if len(parts) <= _MAX_VALUES_SHOWN:
        return f"{label} " + ", ".join(f"{p['ref']} ({_short(p['value'])})" if p["value"] else p["ref"] for p in parts)
    return f"{label} {compress_refs(refs)}"


def _rules_by_kind() -> dict[str, tuple[int, dict[str, Any]]]:
    return {r["kind"]: (i, r) for i, r in enumerate(bom.rules()["kinds"])}


def _order_key(index: int, rule: Mapping[str, Any]) -> tuple[int, int, int, int]:
    return (1 if rule["mechanical"] else 0, int(rule["height_class"]), int(rule["sensitivity"]), index)


def _hint(code: str, severity: str, text: str, source_ids: Iterable[str],
          refs: Iterable[str] | None = None) -> dict[str, Any]:
    """A step hint. ``refs``: the parts the text already names at its start (a subset of the step refs); kept as the
    private ``_refs`` for the warnings and the summary, never stored (``_public``)."""
    if severity not in _SEVERITY_RANK:
        raise BenchError("rule_data_missing", f"bad severity {severity!r} in solder rules", "reinstall the plugin")
    out = {"code": code, "severity": severity, "text": text, "source_ids": list(source_ids)}
    if refs is not None:
        out["_refs"] = list(refs)
    return out


def _guessed(p: Mapping[str, Any]) -> bool:
    """True if the capacitor type comes from the value only (not named by the row, no type or package text)."""
    basis = p.get("_basis")
    if basis is not None:
        return basis == "value"
    return bom.classify(p["ref"], p["value"], p["package"]) == (p["kind"], "value")


_HEADER_TEXT = re.compile(r"header|pin strip|castellat|solder pad|\bpads?\b", re.I)
_STRIP_IN = ("supply", "gnd", "led_data_in", "digital_in", "spi_sdi", "spi_sck", "onewire")


def _catalog_entry(p: Mapping[str, Any]) -> Mapping[str, Any] | None:
    if not p.get("_module"):
        return None
    from . import modules
    try:
        return modules.catalog().get(p["_module"], p.get("_variant"))
    except Exception:  # noqa: BLE001 - an unknown module id keeps the plain step
        return None


def _is_strip(p: Mapping[str, Any]) -> bool:
    """A catalog addressable LED (category led.addressable) with qty > 1: a strip, wired at its input end."""
    entry = _catalog_entry(p)
    return bool(entry) and str(entry.get("category") or "").startswith("led.addressable") and (p.get("qty") or 1) > 1


def _mount_unknown(p: Mapping[str, Any]) -> bool:
    """A catalog module whose data says nothing about headers or pads (rfm95w): no female-header advice."""
    entry = _catalog_entry(p)
    if not entry:
        return False
    import json
    text = json.dumps({k: v for k, v in entry.items() if k in ("title", "notes", "pins", "variants")},
                      ensure_ascii=False)
    return not _HEADER_TEXT.search(text)


def _strip_wires(p: Mapping[str, Any]) -> list[str]:
    entry = _catalog_entry(p) or {}
    conn = p.get("_conn") or {}
    out = []
    for q in entry.get("pins") or []:
        if isinstance(q, Mapping) and q.get("signal") in _STRIP_IN:
            net = conn.get(q["name"])
            out.append(f"{q['name']} to {net}" if isinstance(net, str) and net.strip() else q["name"])
    return out


def _strip_step(p: Mapping[str, Any]) -> tuple[str, list[dict[str, Any]]]:
    """One step per strip: the wires at its input end (supply, ground, data inputs of the catalog pins; with the
    project nets when the row carries conn) and the data direction, instead of the bare-LED/IC steps."""
    data = bom.rules()
    wires = _strip_wires(p)
    qty = p.get("qty") or 1
    what = f"LED strip {p['ref']} ({_short(p['value'])}, {qty} LEDs)" if p["value"] else f"LED strip {p['ref']}"
    action = data["actions"]["led_strip"].format(what=what, count=len(wires), wires=", ".join(wires))
    hints = []
    for key in ("led_strip_data", "led_strip_supply"):
        h = data["extra_hints"][key]
        hints.append(_hint(h["code"], h["severity"], h["text"].format(refs=p["ref"]), h.get("source_ids", ()),
                           refs=[p["ref"]]))
    return action, sorted(hints, key=lambda h: _SEVERITY_RANK[h["severity"]])


def _step_hints(kind: str, rule: Mapping[str, Any], parts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    data = bom.rules()
    hints = [_hint(h["code"], h["severity"], h["text"], h.get("source_ids", ())) for h in rule["hints"]]
    if kind == "module":  # no female-header advice for catalog modules the data says nothing about
        unknown = [p["ref"] for p in parts if _mount_unknown(p)]
        if unknown:
            known = [p["ref"] for p in parts if p["ref"] not in unknown]
            hints = [h if h["code"] != "mechanical" else {**h, "text": f"{compress_refs(known)}: {h['text']}",
                                                          "_refs": known}
                     for h in hints if h["code"] != "mechanical" or known]
            extra = data["extra_hints"]["module_mount_unknown"]
            hints.append(_hint(extra["code"], extra["severity"], extra["text"].format(refs=compress_refs(unknown)),
                               extra.get("source_ids", ()), refs=unknown))
    catalog = [p for p in parts if p.get("_module")]
    if kind == "ic" and catalog:  # a catalog module stored as a bare chip: most are bought on a breakout board
        names = ", ".join(f"{p['ref']} ({p['_module']})" for p in catalog)
        hints.append(_hint("catalog_module", "info", f"{names}: from the module catalog. On a breakout board, solder "
                           "its pin headers and fit it last like a module (on headers, give kind module); the IC "
                           "steps here are for a bare chip (rule of thumb).", ["rule-of-thumb"],
                           refs=[p["ref"] for p in catalog]))
    if kind == "ceramic":  # electrolytics already carry the polarity danger hint
        guessed = [p["ref"] for p in parts if _guessed(p)]
        extra = data.get("extra_hints", {}).get("kind_by_value")
        if guessed and extra:
            hints.append(_hint(extra["code"], extra["severity"], extra["text"].format(refs=compress_refs(guessed)),
                               extra.get("source_ids", ()), refs=guessed))
    for tr in data.get("text_rules", []):
        hit = [p["ref"] for p in parts if re.search(tr["pattern"], f"{p['value']} {p['package'] or ''}", re.I)]
        if not hit:
            continue
        same = [i for i, h in enumerate(hints) if h["code"] == tr["code"]]
        if same and _SEVERITY_RANK[hints[same[0]]["severity"]] <= _SEVERITY_RANK[tr["severity"]]:
            continue  # the kind already carries this hint at the same or a higher severity
        new = _hint(tr["code"], tr["severity"], tr["text"].format(refs=compress_refs(hit)), tr.get("source_ids", ()),
                    refs=hit)
        if same:
            hints[same[0]] = new  # e.g. relay "low voltage only" caution -> danger when mains is mentioned
        else:
            hints.append(new)
    return sorted(hints, key=lambda h: _SEVERITY_RANK[h["severity"]])


def _public(step: Mapping[str, Any]) -> dict[str, Any]:
    """Step as stored in the project: hints with their source ids (the UI shows them as `src ›` lines)."""
    out = {k: step[k] for k in ("id", "n", "refs", "kind", "action")}
    out["hints"] = [{"code": h["code"], "severity": h["severity"], "text": h["text"], "source_ids": list(h["source_ids"])}
                    for h in step["hints"]]
    return out


def _build(parts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_kind = _rules_by_kind()
    groups: dict[str, list[dict[str, Any]]] = {}
    for p in parts:
        if p["kind"] not in by_kind:
            raise BenchError("rule_data_missing", f"no solder rule for kind {p['kind']!r}", "reinstall the plugin")
        if p["kind"] == "unknown":
            groups[f"unknown:{p['ref']}"] = [p]
        else:
            groups.setdefault(p["kind"], []).append(p)
    for key in [k for k in groups if not k.startswith("unknown:")]:  # LED strips get their own step
        strips = [p for p in groups[key] if _is_strip(p)]
        for p in strips:
            groups[key].remove(p)
            groups[f"{key}:strip:{p['ref']}"] = [p]
        if not groups[key]:
            del groups[key]
    raw = []
    for key, members in groups.items():
        kind = key.split(":", 1)[0]
        if ":strip:" in key:
            kind = "led"
        index, rule = by_kind[kind]
        members = sorted(members, key=lambda p: _natural(p["ref"]))
        refs = [p["ref"] for p in members]
        if ":strip:" in key:
            action, hints = _strip_step(members[0])
        else:
            action = rule["action"].format(what=_what(rule, members))
            if kind == "module" and any(_mount_unknown(p) for p in members):
                action = bom.rules()["actions"]["module_neutral"].format(what=_what(rule, members))
            hints = _step_hints(kind, rule, members)
        raw.append({
            "_key": (*_order_key(index, rule), _natural(refs[0])),
            "id": step_id(kind, refs),
            "refs": refs,
            "kind": kind,
            "action": action,
            "hints": hints,
            "_polarised": bool(rule.get("polarised")),
            "_label": rule["label"][0 if len(refs) == 1 else 1],
        })
    raw.sort(key=lambda s: s["_key"])
    for n, s in enumerate(raw, start=1):
        s["n"] = n
    return raw


def _warnings(steps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Plan warnings. A hint with ``_refs`` already starts with its refs; any other gets the step refs in front."""
    out: list[dict[str, Any]] = []
    oriented: list[tuple[str, list[str]]] = []
    for s in steps:
        refs = compress_refs(s["refs"])
        for h in s["hints"]:
            text = h["text"] if "_refs" in h else f"{refs}: {h['text']}"
            if h["severity"] == "danger":
                out.append(warning(h["code"], "danger", text, h["source_ids"]))
            elif h["code"] in ("kind_uncertain", "check_manually", "low_voltage_only"):
                out.append(warning(h["code"], "caution", text, h["source_ids"]))
        if s["_polarised"] and not any(h["severity"] == "danger" and h["code"] == "polarity" for h in s["hints"]):
            ids = [i for h in s["hints"] if h["code"] in _ORIENTATION_CODES for i in h["source_ids"]]
            oriented.append((f"{refs} ({s['_label']})", ids))
    if oriented:
        names = ", ".join(n for n, _ in oriented)
        ids = list(dict.fromkeys(i for _, group in oriented for i in group))
        out.append(warning("polarity", "caution", f"Orientation matters for {names}; check each mark before soldering.", ids))
    return sorted(out, key=lambda w: _SEVERITY_RANK[w["severity"]])


def _assumptions(parts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    data = bom.rules()
    out = [
        assumption("order", "mechanical parts last; low before tall; robust before heat-sensitive",
                   "practice rule, not a standard (rule-of-thumb)"),
        assumption("soldering_temperature", "not given",
                   "no iron temperature without the datasheets of your solder and parts; use their values"),
    ]
    elcos = sort_refs(p["ref"] for p in parts if p["kind"] == "electrolytic")
    if elcos:  # Nichicon CAT.8101H names over-voltage as a cause of a venting electrolytic
        out.append(assumption(
            "rated_voltage", f"{compress_refs(elcos)}: above its rail, with margin",
            "not in the BOM; over-voltage can vent it (Nichicon); the margin is a rule of thumb (datasheet)"))
    guessed = [(p["ref"], p["kind"]) for p in parts if p["kind"] in ("ceramic", "electrolytic") and _guessed(p)]
    if guessed:
        lim = data["classify"]["capacitor_by_value"]
        out.append(assumption(
            "capacitor_type", ", ".join(f"{r}: {k}" for r, k in guessed),
            f"no type or package in the BOM; below {format_si(lim['ceramic_below_f'], 'F')} ceramic, "
            f"from {format_si(lim['electrolytic_from_f'], 'F')} electrolytic (rule-of-thumb)"))
    return out


def _sources(ids: Iterable[str]) -> list[dict[str, Any]]:
    """Cited sources without the long audit notes (quotes stay in data/sources/solder.json), so the answer
    stays under 8 kB. The rule-of-thumb disclaimer note is kept."""
    out = []
    for s in sources.resolve(ids):
        if s["id"] != "rule-of-thumb":
            s.pop("note", None)
        out.append(s)
    return out


def _labels(steps: list[dict[str, Any]]) -> str:
    by_kind = _rules_by_kind()
    out: list[str] = []
    for s in steps:
        label = by_kind[s["kind"]][1]["label"][0 if len(s["refs"]) == 1 else 1]
        if label not in out:
            out.append(label)
    return ", ".join(out)


def _rows_by_ref(parts: Any) -> dict[str, dict[str, Any]]:
    """{ref: {variant, conn}} of project part rows (dicts); text BOMs carry neither."""
    out: dict[str, dict[str, Any]] = {}
    if isinstance(parts, list | tuple):
        for row in parts:
            if isinstance(row, Mapping) and isinstance(row.get("ref"), str):
                conn = row.get("conn") if isinstance(row.get("conn"), Mapping) else None
                var = row.get("variant") if isinstance(row.get("variant"), str) else None
                out[row["ref"].strip().upper()] = {"variant": var, "conn": conn}
    return out


def _danger_refs(steps: list[dict[str, Any]]) -> list[str]:
    """Per step with a danger hint: the refs those hints name (``_refs``, else the step refs), compressed; in step
    order, each ref once."""
    out: list[str] = []
    seen: set[str] = set()
    for s in steps:
        named: set[str] = set()
        for h in s["hints"]:
            if h["severity"] == "danger":
                named.update(h["_refs"] if "_refs" in h else s["refs"])
        refs = [r for r in s["refs"] if r in named and r not in seen]
        if refs:
            seen.update(refs)
            out.append(compress_refs(refs))
    return out


def plan(parts: Any) -> dict[str, Any]:
    """Solder plan for a BOM (text or rows) -> ``solder.plan`` envelope."""
    try:
        parsed, basis, mods = bom.parse_detail(parts)
        rows = _rows_by_ref(parts)
        parsed = [{**p, "_basis": basis.get(p["ref"]), "_module": mods.get(p["ref"]),
                   "_variant": rows.get(p["ref"], {}).get("variant"), "_conn": rows.get(p["ref"], {}).get("conn")}
                  for p in parsed]
        steps = _build(parsed)
        warns = _warnings(steps)
        ids = ["rule-of-thumb"] + [i for s in steps for h in s["hints"] for i in h["source_ids"]]
        srcs = _sources(ids)
    except BenchError as err:
        return from_error(ACTION_PLAN, err)
    unknown = sort_refs(p["ref"] for p in parsed if p["kind"] == "unknown")
    unclear = sort_refs(p["ref"] for p in parsed if p["kind"] == "capacitor")
    summary = f"{len(steps)} solder steps for {len(parsed)} parts: {_labels(steps)}"
    danger = _danger_refs(steps)
    if danger:
        summary += f"; danger at {', '.join(danger)}"
    if unknown or unclear:
        summary += f"; check manually: {compress_refs(unknown + unclear)}"
    result = {
        "steps": [_public(s) for s in steps],
        "parts_total": len(parsed),
        "unknown_parts": unknown,
        "unclear_parts": unclear,
    }
    return envelope(ACTION_PLAN, summary + ".", result, warnings=warns, assumptions=_assumptions(parsed), sources=srcs)


def _plan_parts(plan_obj: Any) -> tuple[list[dict[str, Any]], list[str]]:
    if not isinstance(plan_obj, Mapping):
        raise BenchError("invalid_args", "plan must be an object", _PLAN_HINT)
    body = plan_obj.get("result") if isinstance(plan_obj.get("result"), Mapping) else plan_obj
    steps = body.get("steps")
    done = body.get("done", plan_obj.get("done", []))
    if not isinstance(steps, list) or not steps:
        raise BenchError("invalid_args", "the plan has no steps", _PLAN_HINT)
    for s in steps:
        if not isinstance(s, Mapping) or not isinstance(s.get("id"), str) or not isinstance(s.get("refs"), list):
            raise BenchError("invalid_args", f"bad step in plan: {s!r}"[:200], _PLAN_HINT)
    if done is None:
        done = []
    if not isinstance(done, list) or not all(isinstance(d, str) for d in done):
        raise BenchError("invalid_args", "plan.done must be a list of step ids", _PLAN_HINT)
    return [dict(s) for s in steps], list(done)


def _hint_source_ids(kind: str, code: str) -> list[str]:
    data = bom.rules()
    for r in data["kinds"]:
        if r["kind"] == kind:
            for h in r["hints"]:
                if h["code"] == code:
                    return list(h.get("source_ids", ()))
    for tr in data.get("text_rules", []):
        if tr["code"] == code:
            return list(tr.get("source_ids", ()))
    extra = data.get("extra_hints", {}).get(code)
    return list(extra.get("source_ids", ())) if extra else []


def _step_label(s: Mapping[str, Any]) -> str:
    kind = str(s.get("kind", ""))
    rule = _rules_by_kind().get(kind)
    label = rule[1]["label"][0 if len(s["refs"]) == 1 else 1] if rule else kind.replace("_", " ")
    return f"step {s.get('n', '?')}, {label} {compress_refs(s['refs'])}".rstrip()


_REF_PREFIX_ENDS = (":", ",", " (", "–", "-")


def _has_ref_prefix(text: str, refs: Iterable[str]) -> bool:
    """True if ``text`` starts with one of ``refs`` followed by ``:``, ``,``, `` (`` or a dash (a range like R1-R4)."""
    return any(text.startswith(r) and text[len(r):].startswith(_REF_PREFIX_ENDS) for r in refs if r)


def step(plan_obj: Any, step_id_: Any, done: Any = True) -> dict[str, Any]:
    """Mark a step done (or not done) -> ``solder.step`` envelope with the new ``done`` list and the next step."""
    try:
        steps, prev = _plan_parts(plan_obj)
        if not isinstance(step_id_, str) or not step_id_:
            raise BenchError("invalid_args", "step_id must be a step id string", "use an id from solder.plan steps[].id")
        if not isinstance(done, bool):
            raise BenchError("invalid_args", "done must be true or false", "pass done=true to tick a step, false to untick")
        ids = [s["id"] for s in steps]
        if step_id_ not in ids:
            raise BenchError("invalid_args", f"unknown step id {step_id_!r}",
                             "valid ids: " + ", ".join(ids[:12]) + (" …" if len(ids) > 12 else ""))
        marked = (set(prev) & set(ids)) | {step_id_} if done else (set(prev) & set(ids)) - {step_id_}
        new_done = [i for i in ids if i in marked]
        current = next(s for s in steps if s["id"] == step_id_)
        nxt = next((s for s in steps if s["id"] not in marked), None)
        warns, src_ids = [], []
        if nxt is not None:
            for h in nxt.get("hints", []):
                if isinstance(h, Mapping) and h.get("severity") in ("danger", "caution"):
                    ids_h = _hint_source_ids(str(nxt.get("kind", "")), str(h.get("code", "")))
                    src_ids += ids_h
                    text = str(h.get("text", ""))
                    if not _has_ref_prefix(text, [str(r) for r in nxt["refs"]]):
                        text = f"{compress_refs(nxt['refs'])}: {text}"
                    warns.append(warning(str(h.get("code") or "hint"), h["severity"], text, ids_h))
        srcs = _sources(src_ids)
    except BenchError as err:
        return from_error(ACTION_STEP, err)
    total, count = len(steps), len(new_done)
    verb = "done" if done else "not done"
    if nxt is None:
        summary = f"All {total} solder steps done."
    else:
        label = _step_label(current)
        summary = f"{label[0].upper()}{label[1:]} marked {verb}; {count}/{total} done, next: {_step_label(nxt)}."
    result = {
        "step": current,
        "done": new_done,
        "progress": {"done": count, "total": total},
        "next_step": nxt,
        "complete": nxt is None,
    }
    return envelope(ACTION_STEP, summary, result, warnings=sorted(warns, key=lambda w: _SEVERITY_RANK[w["severity"]]),
                    sources=srcs)


ROW_KEYS = ("ref", "kind", "value", "package", "qty", "module", "variant", "conn")


def rows_from_parts(parts: Any) -> list[dict[str, Any]]:
    """BOM rows for ``plan`` from a project's parts: per part ``ROW_KEYS`` that are set (not None), nothing else.
    ``module``, ``variant`` and ``conn`` let a catalog module get its own advice (strip wires with their nets)."""
    return [{k: p[k] for k in ROW_KEYS if p.get(k) is not None}
            for p in parts or [] if isinstance(p, Mapping)]


def plan_state(project: Mapping[str, Any]) -> dict[str, Any]:
    """Does the project's stored solder plan cover its parts? -> ``{"state", "missing", "gone"}``.

    ``no_parts``: no part with a ref. ``none``: parts but no steps. ``stale``: part refs not in any step
    (``missing``, in part order) or step refs no part has (``gone``, in step order). ``current``: otherwise."""
    parts = [p for p in project.get("parts") or [] if isinstance(p, Mapping) and p.get("ref")]
    solder_obj = project.get("solder") if isinstance(project.get("solder"), Mapping) else {}
    steps = [s for s in solder_obj.get("steps") or [] if isinstance(s, Mapping)]
    if not parts:
        return {"state": "no_parts", "missing": [], "gone": []}
    if not steps:
        return {"state": "none", "missing": [], "gone": []}
    in_plan = list(dict.fromkeys(r for s in steps for r in s.get("refs") or []))
    have, planned = {p["ref"] for p in parts}, set(in_plan)
    missing = [p["ref"] for p in parts if p["ref"] not in planned]
    gone = [r for r in in_plan if r not in have]
    return {"state": "stale" if missing or gone else "current", "missing": missing, "gone": gone}


__all__ = ["compress_refs", "plan", "plan_state", "rows_from_parts", "sort_refs", "step", "step_id"]
