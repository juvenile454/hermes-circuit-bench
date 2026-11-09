"""Serial over REST and WebSocket.

- ``POST /serial/open {port, baud?, reset?, project?}``: ``guard.check_serial(via="route")``, then the process
  broker opens the port (``serialport.open_port``; DTR/RTS stay inactive unless ``reset: true``).
- ``POST /serial/close {port}``.
- ``GET /serial/tail?port=&after=<seq>&limit=``: the mandatory polling fallback (same ``seq`` as the socket).
- ``WS /serial/stream?port=``: server -> client only. On every connect: ``state`` (with ``epoch``), the last
  <= 200 lines and the last panic; then live ``line``/``panic``/``state`` messages. The socket never opens a port.

``epoch`` identifies the broker's process: ``seq`` counts per epoch and starts again at 1 after a backend restart.
Serial access goes only through the serialport module functions (the second package copy has its own
exception classes). A panic on a port opened here also goes out as the event ``panic.detected``.

Query names are never ``token`` or ``native_dial`` (the Desktop SDK adds ``native_dial``).
"""
import asyncio
import contextlib
import logging
import secrets
import threading
import time
from collections.abc import Mapping
from typing import Any

from fastapi import APIRouter, Request, WebSocket
from starlette.websockets import WebSocketDisconnect

from .common import Core, bool_field, guarded, read_json, refuse, respond, threaded

logger = logging.getLogger("circuit_bench.dashboard")

SNAPSHOT_LINES = 200
QUEUE_MAX = 5000
WS_POLICY_VIOLATION = 1008


def epoch(core: Core) -> str:
    """Start id of this process's broker (shared by every package copy through runtime)."""
    return core.runtime.get("serial.epoch", lambda: f"{int(time.time()):x}-{secrets.token_hex(4)}")


def ws_authorized(websocket: WebSocket) -> bool:
    """Hermes' plugin WebSocket gate redeems the Desktop's one-use native grant (header, never in the URL) and stamps
    the principal on the connection (``scope["state"]["native_http_principal"]``). Only such sockets are served.

    Other credentials (``?token=`` of token-mode remotes) cannot be checked through a public Hermes API (catalog
    rule 9); those clients use the polling fallback ``GET /serial/tail``."""
    try:
        return bool(getattr(websocket.state, "native_http_principal", None))
    except Exception:  # noqa: BLE001 - an unreadable connection state refuses
        return False


# --------------------------------------------------------------------------------------------- panic relay

def _relays(core: Core) -> dict[str, Any]:
    return core.runtime.get("api.panic_relays", lambda: {"lock": threading.Lock(), "ports": {}})


def watch_panics(core: Core, port: str, project_id: str | None) -> None:
    """Send ``panic.detected`` for panics on ``port`` (once per port; the newest project id wins)."""
    relays = _relays(core)
    with relays["lock"]:
        entry = relays["ports"].get(port)
        if entry is not None:
            entry["project"] = project_id
            return
        entry = {"project": project_id}

        def on_message(msg: Mapping[str, Any]) -> None:
            if msg.get("t") != "panic":
                return
            try:
                core.events.emit("panic.detected", {"project": entry["project"], "port": port,
                                                    "reason": msg.get("summary"), "top_frame": None,
                                                    "log_ref": msg.get("log_ref"), "seq": msg.get("seq")})
            except Exception as e:  # noqa: BLE001 - an event never stops the reader
                logger.debug("circuit-bench: panic.detected not sent (%s)", type(e).__name__)

        entry["unsubscribe"] = core.serialport.subscribe(port, on_message)
        relays["ports"][port] = entry


def unwatch_panics(core: Core, port: str) -> None:
    relays = _relays(core)
    with relays["lock"]:
        entry = relays["ports"].pop(port, None)
    if entry is not None:
        with contextlib.suppress(Exception):
            entry["unsubscribe"]()


# --------------------------------------------------------------------------------------------- REST

def _port_arg(core: Core, action: str, value: Any) -> str:
    """The normalised port (serialport.normalize_port: realpath of /dev links, only serial devices)."""
    if not isinstance(value, str) or not value.strip() or len(value) > 256:
        raise refuse(core, action, "invalid_args", "port is required (a device path like /dev/ttyACM0 or a sim:// port)")
    try:
        return core.serialport.normalize_port(value)
    except Exception as e:
        err = core.serialport.local_error(e)
        if err is None:
            raise
        raise refuse(core, action, err.code, err.message, err.hint) from None


def open_serial(core: Core, body: dict[str, Any]) -> dict[str, Any]:
    action = "serial.open"
    port = _port_arg(core, action, body.get("port"))
    reset = bool_field(core, action, body, "reset", False)
    baud = body.get("baud")
    pid = body.get("project")
    if pid is not None and not isinstance(pid, str):
        raise refuse(core, action, "invalid_args", "project must be a bench project id")
    refused = core.guard.check_serial(via="route", settings=core.settings.load(), port=port, cron=False, action=action)
    if refused is not None:
        return refused
    simulated = core.guard.is_sim(port)
    try:
        status = core.serialport.open_port(port, baud, reset=reset)
    except Exception as e:
        err = core.serialport.local_error(e)
        if err is None:
            raise
        return core.contracts.from_error(action, err, simulated=simulated)
    watch_panics(core, port, pid)
    result = {**status, "epoch": epoch(core)}
    warns = []
    if reset:
        warns.append(core.contracts.warning("board_reset", "info", f"{port}: DTR/RTS reset requested; the board restarted"))
    tag = " (simulated)" if result.get("simulated") else ""
    summary = f"{port} is {result.get('state')} at {result.get('baud')} baud{tag}."
    return core.contracts.envelope(action, summary, result, warnings=warns, simulated=bool(result.get("simulated")))


def close_serial(core: Core, body: dict[str, Any]) -> dict[str, Any]:
    action = "serial.close"
    port = _port_arg(core, action, body.get("port"))
    unwatch_panics(core, port)
    status = core.serialport.close_port(port)
    result = {**status, "epoch": epoch(core)}
    return core.contracts.envelope(action, f"{port} is {result.get('state')}.", result,
                                   simulated=bool(result.get("simulated")))


def _int_arg(core: Core, action: str, query: Mapping[str, str], key: str, lo: int, hi: int) -> int | None:
    raw = query.get(key)
    if raw is None or raw == "":
        return None
    try:
        value = int(raw)
    except ValueError:
        raise refuse(core, action, "invalid_args", f"{key} must be a whole number") from None
    if not lo <= value <= hi:
        raise refuse(core, action, "invalid_args", f"{key} must be between {lo} and {hi}")
    return value


def tail_serial(core: Core, query: Mapping[str, str]) -> dict[str, Any]:
    action = "serial.tail"
    port = _port_arg(core, action, query.get("port"))
    after = _int_arg(core, action, query, "after", 0, 1 << 62)
    limit = _int_arg(core, action, query, "limit", 1, core.serialport.TAIL_LIMIT) or core.serialport.TAIL_LIMIT
    res = core.serialport.tail(port, after, limit)
    result = {**res, "epoch": epoch(core)}
    n = len(result["lines"])
    summary = f"{port}: {n} line{'s' if n != 1 else ''}"
    if result.get("panic"):
        summary += f", panic at seq {result['panic'].get('seq')}"
    return core.contracts.envelope(action, summary + ".", result, simulated=bool(result.get("simulated")))


# --------------------------------------------------------------------------------------------- WebSocket

async def stream(core: Core, websocket: WebSocket) -> None:
    if not ws_authorized(websocket):
        await websocket.close(code=WS_POLICY_VIOLATION)
        return
    raw_port = websocket.query_params.get("port", "")
    try:
        status = core.serialport.port_status(raw_port)
    except Exception:  # noqa: BLE001 - a bad port name ends the socket before it is accepted
        await websocket.close(code=WS_POLICY_VIOLATION)
        return
    port = status["port"]
    await websocket.accept()
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=QUEUE_MAX)
    dropped = [0]

    def put(msg: dict[str, Any]) -> None:
        try:
            queue.put_nowait(msg)
        except asyncio.QueueFull:
            dropped[0] += 1

    def on_message(msg: dict[str, Any]) -> None:  # reader thread
        with contextlib.suppress(RuntimeError):  # loop closed: the socket is gone
            loop.call_soon_threadsafe(put, msg)

    unsubscribe = core.serialport.subscribe(port, on_message)
    disconnect = core.portwatch.watcher().connect()
    ep = epoch(core)
    receiver: asyncio.Future | None = None
    getter: asyncio.Future | None = None
    try:
        snap = core.serialport.tail(port, None, SNAPSHOT_LINES)
        status = core.serialport.port_status(port)
        await websocket.send_json({"t": "state", "port": port, "state": snap["state"], "detail": status.get("detail", ""),
                                   "epoch": ep, "simulated": bool(snap.get("simulated")),
                                   "next_seq": snap.get("next_seq")})
        last_seq = 0
        for line in snap["lines"]:
            await websocket.send_json(line)
            last_seq = line["seq"]
        if snap.get("panic"):
            await websocket.send_json(dict(snap["panic"]))
        receiver = asyncio.ensure_future(websocket.receive())
        while True:
            if getter is None:
                getter = asyncio.ensure_future(queue.get())
            done, _pending = await asyncio.wait({receiver, getter}, return_when=asyncio.FIRST_COMPLETED)
            if receiver in done:
                msg = receiver.result()
                if msg.get("type") == "websocket.disconnect":
                    break
                receiver = asyncio.ensure_future(websocket.receive())  # client messages are ignored
            if getter in done:
                msg = getter.result()
                getter = None
                if msg.get("t") == "line":
                    if msg.get("seq", 0) <= last_seq:
                        continue  # already in the snapshot
                    last_seq = msg["seq"]
                elif msg.get("t") == "state":
                    msg = {**msg, "epoch": ep}
                if dropped[0]:
                    await websocket.send_json({"t": "state", "port": port, "state": "open", "epoch": ep,
                                               "detail": f"lagging: {dropped[0]} messages dropped, reload the tail"})
                    dropped[0] = 0
                await websocket.send_json(msg)
    except (WebSocketDisconnect, ConnectionError, RuntimeError, asyncio.CancelledError):
        pass
    except Exception:  # never crash the dashboard worker (logged)
        logger.exception("circuit-bench: serial stream for %s failed", port)
        with contextlib.suppress(Exception):
            await websocket.close()
    finally:
        unsubscribe()
        disconnect()
        for task in (receiver, getter):
            if task is not None and not task.done():
                task.cancel()


def register(router: APIRouter, core: Core) -> None:
    @router.post("/serial/open")
    @guarded(core, "serial.open")
    async def serial_open(request: Request):
        body = await read_json(core, request, "serial.open", allowed=("port", "baud", "reset", "project"))
        return respond(await threaded(open_serial, core, body))

    @router.post("/serial/close")
    @guarded(core, "serial.close")
    async def serial_close(request: Request):
        body = await read_json(core, request, "serial.close", allowed=("port",))
        return respond(await threaded(close_serial, core, body))

    @router.get("/serial/tail")
    @guarded(core, "serial.tail")
    async def serial_tail(request: Request):
        return respond(await threaded(tail_serial, core, dict(request.query_params)))

    @router.websocket("/serial/stream")
    async def serial_stream(websocket: WebSocket):
        await stream(core, websocket)
