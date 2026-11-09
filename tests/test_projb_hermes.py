"""Plugin and tool schemas against a real Hermes checkout (marker hermes).

- the tool schemas pass Hermes' schema sanitizer unchanged and keep every property through the Gemini legacy and
  Moonshot translators (no structure loss);
- register() only uses PluginContext methods and keywords that exist in this core.
"""
import inspect

import pytest

from circuit_bench import schemas

pytestmark = pytest.mark.hermes


def _props(node, path="$"):
    """Every (path, sorted property names) of the object nodes, anyOf branches and array items included."""
    if not isinstance(node, dict):
        return []
    out = []
    if isinstance(node.get("properties"), dict):
        out.append((path, sorted(node["properties"])))
        for k, v in node["properties"].items():
            out += _props(v, f"{path}.{k}")
    if isinstance(node.get("items"), dict):
        out += _props(node["items"], f"{path}[]")
    for i, branch in enumerate(node.get("anyOf") or []):
        out += _props(branch, f"{path}|{i}")
    return out


def test_sanitizer_leaves_the_schemas_unchanged():
    sanitizer = pytest.importorskip("tools.schema_sanitizer")
    tools = [{"type": "function", "function": s} for s in schemas.ALL]
    assert sanitizer.sanitize_tool_schemas(tools) == tools


@pytest.mark.parametrize("schema", schemas.ALL, ids=lambda s: s["name"])
def test_gemini_and_moonshot_keep_the_structure(schema):
    gemini = pytest.importorskip("agent.gemini_schema")
    moonshot = pytest.importorskip("agent.moonshot_schema")
    params = schema["parameters"]
    assert _props(gemini.sanitize_gemini_tool_parameters(params)) == _props(params)
    assert _props(gemini.prepare_gemini_tool_parameters(params)) == _props(params)
    assert moonshot.sanitize_moonshot_tool_parameters(params) == params


def test_cost_measured_like_hermes():
    import json
    sanitizer = pytest.importorskip("tools.schema_sanitizer")
    tools = sanitizer.sanitize_tool_schemas([{"type": "function", "function": s} for s in schemas.ALL])
    assert len(json.dumps([t["function"] for t in tools])) <= 10000  # schema cost ceiling


def test_plugin_context_signatures_fit_register():
    plugins = pytest.importorskip("hermes_cli.plugins")
    ctx = plugins.PluginContext
    calls = {
        "register_tool": {"name", "toolset", "schema", "handler", "emoji"},
        "register_hook": {"hook_name", "callback"},
        "register_command": {"name", "handler", "description", "args_hint"},
        "register_skill": {"name", "path", "description", "frontmatter"},
    }
    for method, kwargs in calls.items():
        params = set(inspect.signature(getattr(ctx, method)).parameters) - {"self"}
        assert kwargs <= params, (method, kwargs - params)
    assert callable(ctx.current_cron_execution)
    assert "pre_tool_call" in plugins.VALID_HOOKS
