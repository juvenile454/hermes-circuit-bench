"""Desktop events: ``emit(event, payload)`` -> ``plugin.circuit-bench.<event>``.

Inside Hermes the call goes to the public bridge ``hermes_cli.plugin_events.broadcast_plugin_event`` (imported
lazily on every call). Without Hermes (tests, scripts) the import fails and ``emit`` is a no-op with a debug log;
without a connected Desktop client (CLI, cron, Telegram) Hermes itself drops the event with a debug log.

Programming errors are loud: an event name outside ``EVENTS``, a malformed name, a payload that is not an object, lacks
a contract key or is not JSON-serializable raises ``ValueError``. Delivery problems never raise: an event must not
break the write that caused it.
"""
from __future__ import annotations

import json
import logging
import re
from collections.abc import Mapping
from typing import Any

logger = logging.getLogger(__name__)

PLUGIN_ID = "circuit-bench"

# Event name -> payload keys required by the contract. Extra keys are allowed.
EVENTS: dict[str, tuple[str, ...]] = {
    "project.updated": ("id", "rev", "changed", "by"),
    "board.changed": ("port", "state", "simulated"),
    "panic.detected": ("project", "port", "reason", "top_frame", "log_ref"),
    "job.updated": ("job_id", "kind", "state", "progress"),
}

# Same rule as hermes_cli.plugin_events (dot-separated segments of [A-Za-z0-9_-], at most 128 characters).
_EVENT_RE = re.compile(r"^[A-Za-z0-9_-]+(?:\.[A-Za-z0-9_-]+)*$")


def wire_name(event: str) -> str:
    """The name the Desktop half subscribes to: ``plugin.circuit-bench.<event>``."""
    _check_name(event)
    return f"plugin.{PLUGIN_ID}.{event}"


def _check_name(event: Any) -> str:
    if not isinstance(event, str) or len(event) > 128 or not _EVENT_RE.match(event):
        raise ValueError(f"invalid event name {event!r}: expected dot-separated segments of [A-Za-z0-9_-]")
    if event not in EVENTS:
        raise ValueError(f"unknown event {event!r}: known events are {', '.join(EVENTS)}")
    return event


def _check_payload(event: str, payload: Any) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        raise ValueError(f"payload of {event} must be an object, not {type(payload).__name__}")
    missing = [k for k in EVENTS[event] if k not in payload]
    if missing:
        raise ValueError(f"payload of {event} lacks {', '.join(missing)}")
    try:
        return json.loads(json.dumps(dict(payload), allow_nan=False))  # plain JSON, detached from the caller's objects
    except (TypeError, ValueError) as e:
        raise ValueError(f"payload of {event} is not JSON-serializable ({e})") from None


def emit(event: str, payload: Mapping[str, Any]) -> bool:
    """Send ``plugin.circuit-bench.<event>`` to the connected Desktop clients.

    True: handed to Hermes (which drops it with a debug log when no client is connected). False: no Hermes in this
    process or delivery failed (debug log). Raises ``ValueError`` only for an invalid name or payload."""
    event = _check_name(event)
    data = _check_payload(event, payload)
    try:
        from hermes_cli.plugin_events import broadcast_plugin_event  # public plugin API (lazy: no Hermes in tests)
    except ImportError:
        logger.debug("circuit-bench: event %s not sent (no Hermes in this process)", event)
        return False
    try:
        broadcast_plugin_event(PLUGIN_ID, event, data)
    except Exception as e:  # noqa: BLE001 - delivery must never break the caller
        logger.debug("circuit-bench: event %s not sent (%s)", event, type(e).__name__)
        return False
    return True
