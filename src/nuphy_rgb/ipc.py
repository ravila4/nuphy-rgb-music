"""IPC socket server — JSON-RPC 2.0 over Unix domain socket.

The daemon exposes a control socket that GUI apps and CLI tools use to
query state, switch effects, and receive push notifications.

Protocol: line-delimited JSON-RPC 2.0 (newline-terminated).
Transport: Unix domain socket.

Socket path:
  Linux:  $XDG_RUNTIME_DIR/nuphy-rgb/control.sock
  macOS:  $TMPDIR/nuphy-rgb/control.sock
  Fallback: /tmp/nuphy-rgb-<uid>/control.sock
"""

from __future__ import annotations

import errno
import json
import logging
import os
import socket
import socketserver
import sys
import threading
from pathlib import Path
from typing import Any

from nuphy_rgb.state import DaemonState

log = logging.getLogger(__name__)

JSONRPC_VERSION = "2.0"

# JSON-RPC error codes (standard + app-specific).
ERR_PARSE = -32700
ERR_INVALID_REQUEST = -32600
ERR_METHOD_NOT_FOUND = -32601
ERR_INVALID_PARAMS = -32602


# ---------------------------------------------------------------------------
# Socket path
# ---------------------------------------------------------------------------


def control_socket_path() -> Path:
    """Return the platform-appropriate path for the control socket."""
    if sys.platform == "darwin":
        base = os.environ.get("TMPDIR", "/tmp")
    else:
        base = os.environ.get("XDG_RUNTIME_DIR", "")
    if not base:
        base = f"/tmp/nuphy-rgb-{os.getuid()}"
    return Path(base) / "nuphy-rgb" / "control.sock"


# ---------------------------------------------------------------------------
# JSON-RPC helpers
# ---------------------------------------------------------------------------


def _ok_response(result: Any, request_id: int | str | None) -> dict:
    return {"jsonrpc": JSONRPC_VERSION, "result": result, "id": request_id}


def _error_response(
    code: int, message: str, request_id: int | str | None = None
) -> dict:
    return {
        "jsonrpc": JSONRPC_VERSION,
        "error": {"code": code, "message": message},
        "id": request_id,
    }


def _notification(method: str, params: dict) -> dict:
    """Server->client push notification (no id)."""
    return {"jsonrpc": JSONRPC_VERSION, "method": method, "params": params}


# ---------------------------------------------------------------------------
# Method dispatcher
# ---------------------------------------------------------------------------


class _Dispatcher:
    """Routes JSON-RPC method calls to DaemonState operations."""

    def __init__(self, state: DaemonState) -> None:
        self._state = state
        self._methods: dict[str, Any] = {
            "get_status": self._get_status,
            "list_effects": self._list_effects,
            "set_effect": self._set_effect,
            "set_sidelight": self._set_sidelight,
            "next_effect": self._next_effect,
            "prev_effect": self._prev_effect,
            "next_sidelight": self._next_sidelight,
            "prev_sidelight": self._prev_sidelight,
            "quit": self._quit,
        }

    def dispatch(self, method: str, params: dict | None) -> Any:
        """Call a method by name. Returns the result or raises ValueError."""
        handler = self._methods.get(method)
        if handler is None:
            raise LookupError(f"unknown method: {method}")
        return handler(params)

    def _get_status(self, _params: dict | None) -> dict:
        s = self._state
        return {
            "effect": s.key.name,
            "sidelight": s.side.name if s.side is not None else None,
            "running": not s.quit_event.is_set(),
        }

    def _list_effects(self, _params: dict | None) -> dict:
        s = self._state
        return {
            "effects": list(s.key.names),
            "sidelights": list(s.side.names) if s.side is not None else [],
        }

    def _set_effect(self, params: dict | None) -> dict:
        name = _require_param(params, "name")
        if not self._state.key.set_by_name(name):
            raise ValueError(f"unknown effect: {name}")
        return {"name": self._state.key.name}

    def _set_sidelight(self, params: dict | None) -> dict:
        if self._state.side is None:
            raise ValueError("sidelights not enabled")
        name = _require_param(params, "name")
        if not self._state.side.set_by_name(name):
            raise ValueError(f"unknown sidelight: {name}")
        return {"name": self._state.side.name}

    def _next_effect(self, _params: dict | None) -> dict:
        self._state.key.next()
        return {"name": self._state.key.name}

    def _prev_effect(self, _params: dict | None) -> dict:
        self._state.key.prev()
        return {"name": self._state.key.name}

    def _next_sidelight(self, _params: dict | None) -> dict:
        if self._state.side is None:
            raise ValueError("sidelights not enabled")
        self._state.side.next()
        return {"name": self._state.side.name}

    def _prev_sidelight(self, _params: dict | None) -> dict:
        if self._state.side is None:
            raise ValueError("sidelights not enabled")
        self._state.side.prev()
        return {"name": self._state.side.name}

    def _quit(self, _params: dict | None) -> dict:
        self._state.request_quit()
        return {"ok": True}


def _require_param(params: dict | None, key: str) -> Any:
    if params is None or key not in params:
        raise ValueError(f"missing required param: {key}")
    return params[key]


# ---------------------------------------------------------------------------
# Client handler
# ---------------------------------------------------------------------------


class _ClientHandler(socketserver.StreamRequestHandler):
    """Handles one connected client. Reads line-delimited JSON-RPC requests."""

    server: _IPCSocketServer  # type narrowing

    def setup(self) -> None:
        super().setup()
        self._write_lock = threading.Lock()
        self.server.ipc.register_client(self)

    def finish(self) -> None:
        self.server.ipc.unregister_client(self)
        super().finish()

    def handle(self) -> None:
        for raw_line in self.rfile:
            line = raw_line.strip()
            if not line:
                continue
            try:
                request = json.loads(line)
            except json.JSONDecodeError:
                self._send(_error_response(ERR_PARSE, "parse error"))
                continue
            self._handle_request(request)

    def _handle_request(self, request: dict) -> None:
        request_id = request.get("id")
        if request.get("jsonrpc") != JSONRPC_VERSION:
            self._send(
                _error_response(
                    ERR_INVALID_REQUEST, "invalid jsonrpc version", request_id
                )
            )
            return
        method = request.get("method")
        if not isinstance(method, str):
            self._send(
                _error_response(ERR_INVALID_REQUEST, "missing method", request_id)
            )
            return
        params = request.get("params")
        try:
            result = self.server.ipc.dispatcher.dispatch(method, params)
            self._send(_ok_response(result, request_id))
        except LookupError:
            self._send(
                _error_response(
                    ERR_METHOD_NOT_FOUND,
                    f"unknown method: {method}",
                    request_id,
                )
            )
        except ValueError as exc:
            self._send(
                _error_response(ERR_INVALID_PARAMS, str(exc), request_id)
            )

    def _send(self, msg: dict) -> None:
        try:
            with self._write_lock:
                self.wfile.write(json.dumps(msg).encode() + b"\n")
                self.wfile.flush()
        except OSError:
            pass


# ---------------------------------------------------------------------------
# Server
# ---------------------------------------------------------------------------


class _IPCSocketServer(
    socketserver.ThreadingMixIn, socketserver.UnixStreamServer
):
    """ThreadingUnixStreamServer with a typed back-reference to IPCServer."""

    daemon_threads = True
    allow_reuse_address = True
    ipc: IPCServer


class IPCServer:
    """IPC socket server for daemon control.

    Usage::

        server = IPCServer(state)
        server.start()
        # ... daemon runs ...
        server.stop()
    """

    def __init__(self, state: DaemonState) -> None:
        self.dispatcher = _Dispatcher(state)
        self._state = state
        self._clients: set[_ClientHandler] = set()
        self._clients_lock = threading.Lock()
        self._server: _IPCSocketServer | None = None
        self._thread: threading.Thread | None = None
        self._sock_path: Path | None = None

    def start(self) -> Path:
        """Bind the socket and start the server thread. Returns socket path."""
        sock_path = control_socket_path()
        sock_path.parent.mkdir(parents=True, exist_ok=True)

        # Handle stale socket from a previous crash.
        if sock_path.exists():
            self._probe_or_remove(sock_path)

        self._server = _IPCSocketServer(str(sock_path), _ClientHandler)
        self._server.ipc = self
        self._sock_path = sock_path
        self._thread = threading.Thread(
            target=self._server.serve_forever, daemon=True
        )
        self._thread.start()
        log.debug("IPC server listening on %s", sock_path)
        return sock_path

    @staticmethod
    def _probe_or_remove(sock_path: Path) -> None:
        """Probe an existing socket. Remove if stale, raise if live."""
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as probe:
            try:
                probe.connect(str(sock_path))
            except OSError as exc:
                if exc.errno not in (errno.ECONNREFUSED, errno.ENOENT):
                    raise
                log.debug("Removing stale socket: %s", sock_path)
                sock_path.unlink()
                return
        raise RuntimeError(
            f"Another daemon is already listening on {sock_path}"
        )

    def stop(self) -> None:
        """Shut down the server and clean up the socket file."""
        if self._server is not None:
            self._server.shutdown()
            if self._sock_path is not None and self._sock_path.exists():
                self._sock_path.unlink()
            log.debug("IPC server stopped")

    def register_client(self, handler: _ClientHandler) -> None:
        with self._clients_lock:
            self._clients.add(handler)
        log.debug("IPC client connected (%d total)", len(self._clients))

    def unregister_client(self, handler: _ClientHandler) -> None:
        with self._clients_lock:
            self._clients.discard(handler)
        log.debug("IPC client disconnected (%d total)", len(self._clients))

    def broadcast(self, event: dict) -> None:
        """Push a notification to all connected clients."""
        with self._clients_lock:
            clients = list(self._clients)
        for client in clients:
            client._send(event)

    def notify_effect_changed(self, name: str) -> None:
        self.broadcast(_notification("effect_changed", {"name": name}))

    def notify_sidelight_changed(self, name: str) -> None:
        self.broadcast(_notification("sidelight_changed", {"name": name}))
