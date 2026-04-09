"""Tests for the IPC socket server."""

import json
import socket
import time

import pytest

from nuphy_rgb.ipc import IPCServer, control_socket_path
from nuphy_rgb.state import DaemonState


@pytest.fixture()
def state():
    return DaemonState(
        num_effects=3,
        effect_names=["Alpha", "Beta", "Gamma"],
        num_sidelights=2,
        sidelight_names=["Pulse", "Wave"],
    )


@pytest.fixture()
def server(state, tmp_path, monkeypatch):
    """Start an IPC server on a temp socket and yield it."""
    sock_path = tmp_path / "control.sock"
    monkeypatch.setattr(
        "nuphy_rgb.ipc.control_socket_path", lambda: sock_path
    )
    srv = IPCServer(state)
    srv.start()
    yield srv
    srv.stop()


def _send(sock_path, request: dict) -> dict:
    """Send a JSON-RPC request and return the parsed response."""
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.connect(str(sock_path))
    s.sendall(json.dumps(request).encode() + b"\n")
    data = b""
    while b"\n" not in data:
        chunk = s.recv(4096)
        if not chunk:
            break
        data += chunk
    s.close()
    return json.loads(data)


def _sock_path(monkeypatch, tmp_path):
    """Helper to get the monkeypatched socket path."""
    # The path was set in the server fixture
    return tmp_path / "control.sock"


class TestGetStatus:
    def test_returns_current_effect(self, server, tmp_path) -> None:
        resp = _send(tmp_path / "control.sock", {
            "jsonrpc": "2.0", "method": "get_status", "id": 1,
        })
        assert resp["result"]["effect"] == "Alpha"
        assert resp["result"]["sidelight"] == "Pulse"
        assert resp["result"]["running"] is True

    def test_running_false_after_quit(self, server, state, tmp_path) -> None:
        state.request_quit()
        resp = _send(tmp_path / "control.sock", {
            "jsonrpc": "2.0", "method": "get_status", "id": 1,
        })
        assert resp["result"]["running"] is False


class TestListEffects:
    def test_returns_all_names(self, server, tmp_path) -> None:
        resp = _send(tmp_path / "control.sock", {
            "jsonrpc": "2.0", "method": "list_effects", "id": 1,
        })
        assert resp["result"]["effects"] == ["Alpha", "Beta", "Gamma"]
        assert resp["result"]["sidelights"] == ["Pulse", "Wave"]


class TestSetEffect:
    def test_set_by_name(self, server, state, tmp_path) -> None:
        resp = _send(tmp_path / "control.sock", {
            "jsonrpc": "2.0", "method": "set_effect",
            "params": {"name": "Beta"}, "id": 1,
        })
        assert resp["result"]["name"] == "Beta"
        assert state.key.index == 1

    def test_unknown_effect_returns_error(self, server, tmp_path) -> None:
        resp = _send(tmp_path / "control.sock", {
            "jsonrpc": "2.0", "method": "set_effect",
            "params": {"name": "Nope"}, "id": 1,
        })
        assert "error" in resp
        assert "unknown effect" in resp["error"]["message"]

    def test_missing_param_returns_error(self, server, tmp_path) -> None:
        resp = _send(tmp_path / "control.sock", {
            "jsonrpc": "2.0", "method": "set_effect", "id": 1,
        })
        assert "error" in resp
        assert "missing required param" in resp["error"]["message"]


class TestNextPrev:
    def test_next_effect(self, server, state, tmp_path) -> None:
        resp = _send(tmp_path / "control.sock", {
            "jsonrpc": "2.0", "method": "next_effect", "id": 1,
        })
        assert resp["result"]["name"] == "Beta"
        assert state.key.index == 1

    def test_prev_effect_wraps(self, server, state, tmp_path) -> None:
        resp = _send(tmp_path / "control.sock", {
            "jsonrpc": "2.0", "method": "prev_effect", "id": 1,
        })
        assert resp["result"]["name"] == "Gamma"
        assert state.key.index == 2

    def test_next_sidelight(self, server, state, tmp_path) -> None:
        resp = _send(tmp_path / "control.sock", {
            "jsonrpc": "2.0", "method": "next_sidelight", "id": 1,
        })
        assert resp["result"]["name"] == "Wave"


class TestQuit:
    def test_quit_sets_event(self, server, state, tmp_path) -> None:
        resp = _send(tmp_path / "control.sock", {
            "jsonrpc": "2.0", "method": "quit", "id": 1,
        })
        assert resp["result"]["ok"] is True
        assert state.quit_event.is_set()


class TestErrorHandling:
    def test_unknown_method(self, server, tmp_path) -> None:
        resp = _send(tmp_path / "control.sock", {
            "jsonrpc": "2.0", "method": "nonexistent", "id": 1,
        })
        assert resp["error"]["code"] == -32601

    def test_malformed_json(self, server, tmp_path) -> None:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.connect(str(tmp_path / "control.sock"))
        s.sendall(b"not json\n")
        data = s.recv(4096)
        s.close()
        resp = json.loads(data)
        assert resp["error"]["code"] == -32700


class TestStaleSockets:
    def test_removes_stale_socket_on_start(self, state, tmp_path, monkeypatch) -> None:
        sock_path = tmp_path / "control.sock"
        monkeypatch.setattr(
            "nuphy_rgb.ipc.control_socket_path", lambda: sock_path
        )
        # Create a stale socket file (not listening).
        sock_path.touch()

        srv = IPCServer(state)
        returned_path = srv.start()
        assert returned_path == sock_path
        assert sock_path.exists()
        srv.stop()


class TestNoSidelights:
    def test_sidelight_methods_error_when_disabled(self, tmp_path, monkeypatch) -> None:
        state = DaemonState(2, effect_names=["A", "B"], num_sidelights=0)
        sock_path = tmp_path / "control.sock"
        monkeypatch.setattr(
            "nuphy_rgb.ipc.control_socket_path", lambda: sock_path
        )
        srv = IPCServer(state)
        srv.start()
        try:
            resp = _send(sock_path, {
                "jsonrpc": "2.0", "method": "next_sidelight", "id": 1,
            })
            assert "error" in resp
            assert "not enabled" in resp["error"]["message"]

            status = _send(sock_path, {
                "jsonrpc": "2.0", "method": "get_status", "id": 2,
            })
            assert status["result"]["sidelight"] is None
        finally:
            srv.stop()
