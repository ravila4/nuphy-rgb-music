"""Tests for the IPC socket server."""

import json
import shutil
import socket
import tempfile
from pathlib import Path

import pytest

from nuphy_rgb.ipc import IPCServer
from nuphy_rgb.state import DaemonState
from nuphy_rgb.visualizer_params import VisualizerParam


@pytest.fixture()
def state():
    return DaemonState(
        num_effects=3,
        effect_names=["Alpha", "Beta", "Gamma"],
        num_sidelights=2,
        sidelight_names=["Pulse", "Wave"],
    )


def _short_sock_dir() -> Path:
    """Create a short temp directory that stays within macOS's 104-byte
    sun_path limit (pytest's tmp_path includes the full test name and
    exceeds it on Darwin)."""
    return Path(tempfile.mkdtemp(prefix="nrgb-"))


@pytest.fixture()
def sock_dir():
    d = _short_sock_dir()
    yield d
    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture()
def server(state, sock_dir, monkeypatch):
    """Start an IPC server on a temp socket and yield (server, sock_path)."""
    sock_path = sock_dir / "ctl.sock"
    monkeypatch.setattr(
        "nuphy_rgb.ipc.control_socket_path", lambda: sock_path
    )
    srv = IPCServer(state)
    srv.start()
    yield srv, sock_path
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


class TestGetStatus:
    def test_returns_current_effect(self, server) -> None:
        srv, sock_path = server
        resp = _send(sock_path, {
            "jsonrpc": "2.0", "method": "get_status", "id": 1,
        })
        assert resp["result"]["effect"] == "Alpha"
        assert resp["result"]["sidelight"] == "Pulse"
        assert resp["result"]["running"] is True

    def test_running_false_after_quit(self, server, state) -> None:
        srv, sock_path = server
        state.request_quit()
        resp = _send(sock_path, {
            "jsonrpc": "2.0", "method": "get_status", "id": 1,
        })
        assert resp["result"]["running"] is False


class TestListEffects:
    def test_returns_all_names(self, server) -> None:
        srv, sock_path = server
        resp = _send(sock_path, {
            "jsonrpc": "2.0", "method": "list_effects", "id": 1,
        })
        assert resp["result"]["effects"] == ["Alpha", "Beta", "Gamma"]
        assert resp["result"]["sidelights"] == ["Pulse", "Wave"]

    def test_descriptions_empty_without_visualizers(self, server) -> None:
        srv, sock_path = server
        resp = _send(sock_path, {
            "jsonrpc": "2.0", "method": "list_effects", "id": 1,
        })
        assert resp["result"]["effect_descriptions"] == {}

    def test_descriptions_from_visualizer_attribute(
        self, param_server,
    ) -> None:
        srv, sock_path = param_server
        resp = _send(sock_path, {
            "jsonrpc": "2.0", "method": "list_effects", "id": 1,
        })
        # _FakeWithParams / _FakeNoParams don't declare description → "".
        descs = resp["result"]["effect_descriptions"]
        assert descs == {"Fancy": "", "Plain": ""}


class TestSetEffect:
    def test_set_by_name(self, server, state) -> None:
        srv, sock_path = server
        resp = _send(sock_path, {
            "jsonrpc": "2.0", "method": "set_effect",
            "params": {"name": "Beta"}, "id": 1,
        })
        assert resp["result"]["name"] == "Beta"
        assert state.key.index == 1

    def test_unknown_effect_returns_error(self, server) -> None:
        srv, sock_path = server
        resp = _send(sock_path, {
            "jsonrpc": "2.0", "method": "set_effect",
            "params": {"name": "Nope"}, "id": 1,
        })
        assert "error" in resp
        assert "unknown effect" in resp["error"]["message"]

    def test_missing_param_returns_error(self, server) -> None:
        srv, sock_path = server
        resp = _send(sock_path, {
            "jsonrpc": "2.0", "method": "set_effect", "id": 1,
        })
        assert "error" in resp
        assert "missing required param" in resp["error"]["message"]


class TestNextPrev:
    def test_next_effect(self, server, state) -> None:
        srv, sock_path = server
        resp = _send(sock_path, {
            "jsonrpc": "2.0", "method": "next_effect", "id": 1,
        })
        assert resp["result"]["name"] == "Beta"
        assert state.key.index == 1

    def test_prev_effect_wraps(self, server, state) -> None:
        srv, sock_path = server
        resp = _send(sock_path, {
            "jsonrpc": "2.0", "method": "prev_effect", "id": 1,
        })
        assert resp["result"]["name"] == "Gamma"
        assert state.key.index == 2

    def test_next_sidelight(self, server, state) -> None:
        srv, sock_path = server
        resp = _send(sock_path, {
            "jsonrpc": "2.0", "method": "next_sidelight", "id": 1,
        })
        assert resp["result"]["name"] == "Wave"


class TestQuit:
    def test_quit_sets_event(self, server, state) -> None:
        srv, sock_path = server
        resp = _send(sock_path, {
            "jsonrpc": "2.0", "method": "quit", "id": 1,
        })
        assert resp["result"]["ok"] is True
        assert state.quit_event.is_set()


class TestErrorHandling:
    def test_unknown_method(self, server) -> None:
        srv, sock_path = server
        resp = _send(sock_path, {
            "jsonrpc": "2.0", "method": "nonexistent", "id": 1,
        })
        assert resp["error"]["code"] == -32601

    def test_malformed_json(self, server) -> None:
        srv, sock_path = server
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.connect(str(sock_path))
        s.sendall(b"not json\n")
        data = s.recv(4096)
        s.close()
        resp = json.loads(data)
        assert resp["error"]["code"] == -32700

    def test_missing_jsonrpc_version(self, server) -> None:
        srv, sock_path = server
        resp = _send(sock_path, {
            "method": "get_status", "id": 1,
        })
        assert resp["error"]["code"] == -32600
        assert "version" in resp["error"]["message"]


class TestStaleSockets:
    def test_removes_stale_socket_on_start(self, state, sock_dir, monkeypatch) -> None:
        sock_path = sock_dir / "ctl.sock"
        monkeypatch.setattr(
            "nuphy_rgb.ipc.control_socket_path", lambda: sock_path
        )
        # Create a real stale socket (bound but not listening).
        stale = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        stale.bind(str(sock_path))
        stale.close()

        srv = IPCServer(state)
        returned_path = srv.start()
        assert returned_path == sock_path
        assert sock_path.exists()
        srv.stop()


class TestNoSidelights:
    def test_sidelight_methods_error_when_disabled(self, sock_dir, monkeypatch) -> None:
        state = DaemonState(2, effect_names=["A", "B"], num_sidelights=0)
        sock_path = sock_dir / "ctl.sock"
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


class TestPushNotifications:
    def test_broadcast_reaches_connected_client(self, server) -> None:
        srv, sock_path = server
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.connect(str(sock_path))
        # Send a request to confirm connection is established.
        s.sendall(json.dumps({
            "jsonrpc": "2.0", "method": "get_status", "id": 1,
        }).encode() + b"\n")
        # Read the response.
        data = b""
        while b"\n" not in data:
            data += s.recv(4096)
        # Clear buffer.
        data = b""

        # Trigger a notification from the server.
        srv.notify_effect_changed("Beta")

        # Read the pushed notification.
        s.settimeout(2.0)
        while b"\n" not in data:
            data += s.recv(4096)
        s.close()

        notification = json.loads(data)
        assert notification["jsonrpc"] == "2.0"
        assert notification["method"] == "effect_changed"
        assert notification["params"] == {"name": "Beta"}
        assert "id" not in notification

    def test_audio_level_notification(self, server) -> None:
        srv, sock_path = server
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.connect(str(sock_path))
        # Establish connection with a request.
        s.sendall(json.dumps({
            "jsonrpc": "2.0", "method": "get_status", "id": 1,
        }).encode() + b"\n")
        data = b""
        while b"\n" not in data:
            data += s.recv(4096)
        data = b""

        # Trigger audio level notification.
        srv.notify_audio_level(0.12345)

        s.settimeout(2.0)
        while b"\n" not in data:
            data += s.recv(4096)
        s.close()

        notification = json.loads(data)
        assert notification["jsonrpc"] == "2.0"
        assert notification["method"] == "audio_level"
        assert notification["params"] == {"raw_rms": 0.1235}
        assert "id" not in notification


# -- Param tests --


class _FakeWithParams:
    name = "Fancy"

    def __init__(self):
        self.params = {
            "speed": VisualizerParam(
                value=0.5, default=0.5, min=0.0, max=1.0,
                description="How fast",
            ),
        }

    def render(self, frame):
        return []


class _FakeNoParams:
    name = "Plain"

    def render(self, frame):
        return []


class _FakeSideWithParams:
    name = "Glow"

    def __init__(self):
        self.params = {
            "brightness": VisualizerParam(
                value=0.1, default=0.1, min=0.0, max=1.0,
                description="Brightness",
            ),
        }

    def render(self, frame):
        return []


@pytest.fixture()
def param_state():
    visualizers = [_FakeWithParams(), _FakeNoParams()]
    side_visualizers = [_FakeSideWithParams()]
    return DaemonState(
        num_effects=2,
        effect_names=["Fancy", "Plain"],
        visualizers=visualizers,
        num_sidelights=1,
        sidelight_names=["Glow"],
        side_visualizers=side_visualizers,
    )


@pytest.fixture()
def param_server(param_state, sock_dir, monkeypatch):
    sock_path = sock_dir / "ctl.sock"
    monkeypatch.setattr(
        "nuphy_rgb.ipc.control_socket_path", lambda: sock_path
    )
    srv = IPCServer(param_state)
    srv.start()
    yield srv, sock_path
    srv.stop()


class TestGetParams:
    def test_returns_params_for_active_effect(self, param_server) -> None:
        srv, sock_path = param_server
        resp = _send(sock_path, {
            "jsonrpc": "2.0", "method": "get_params", "id": 1,
        })
        result = resp["result"]
        assert "speed" in result
        assert result["speed"]["value"] == 0.5
        assert result["speed"]["min"] == 0.0
        assert result["speed"]["max"] == 1.0
        assert result["speed"]["description"] == "How fast"

    def test_returns_empty_for_no_params(self, param_server, param_state) -> None:
        srv, sock_path = param_server
        param_state.key.set(1)  # switch to Plain
        resp = _send(sock_path, {
            "jsonrpc": "2.0", "method": "get_params", "id": 1,
        })
        assert resp["result"] == {}


class TestSetParam:
    def test_set_valid_value(self, param_server) -> None:
        srv, sock_path = param_server
        resp = _send(sock_path, {
            "jsonrpc": "2.0", "method": "set_param",
            "params": {"name": "speed", "value": 0.8}, "id": 1,
        })
        assert resp["result"] == {"name": "speed", "value": 0.8}

    def test_mutation_visible_on_get(self, param_server) -> None:
        srv, sock_path = param_server
        _send(sock_path, {
            "jsonrpc": "2.0", "method": "set_param",
            "params": {"name": "speed", "value": 0.3}, "id": 1,
        })
        resp = _send(sock_path, {
            "jsonrpc": "2.0", "method": "get_params", "id": 2,
        })
        assert resp["result"]["speed"]["value"] == 0.3

    def test_out_of_range_returns_error(self, param_server) -> None:
        srv, sock_path = param_server
        resp = _send(sock_path, {
            "jsonrpc": "2.0", "method": "set_param",
            "params": {"name": "speed", "value": 5.0}, "id": 1,
        })
        assert "error" in resp
        assert "out of range" in resp["error"]["message"]

    def test_unknown_param_returns_error(self, param_server) -> None:
        srv, sock_path = param_server
        resp = _send(sock_path, {
            "jsonrpc": "2.0", "method": "set_param",
            "params": {"name": "nonexistent", "value": 0.5}, "id": 1,
        })
        assert "error" in resp
        assert "unknown param" in resp["error"]["message"]

    def test_missing_name_returns_error(self, param_server) -> None:
        srv, sock_path = param_server
        resp = _send(sock_path, {
            "jsonrpc": "2.0", "method": "set_param",
            "params": {"value": 0.5}, "id": 1,
        })
        assert "error" in resp
        assert "missing required param" in resp["error"]["message"]


class TestGetParamsFor:
    def test_returns_params_for_named_effect(self, param_server) -> None:
        srv, sock_path = param_server
        # Active effect is Fancy; query Plain (inactive, no params)
        resp = _send(sock_path, {
            "jsonrpc": "2.0", "method": "get_params_for",
            "params": {"name": "Plain"}, "id": 1,
        })
        assert resp["result"] == {}

    def test_returns_params_for_inactive_effect(
        self, param_server, param_state,
    ) -> None:
        srv, sock_path = param_server
        param_state.key.set(1)  # active = Plain
        resp = _send(sock_path, {
            "jsonrpc": "2.0", "method": "get_params_for",
            "params": {"name": "Fancy"}, "id": 1,
        })
        assert "speed" in resp["result"]
        assert resp["result"]["speed"]["value"] == 0.5

    def test_unknown_effect_returns_empty(self, param_server) -> None:
        srv, sock_path = param_server
        resp = _send(sock_path, {
            "jsonrpc": "2.0", "method": "get_params_for",
            "params": {"name": "Nope"}, "id": 1,
        })
        assert resp["result"] == {}


class TestSetParamFor:
    def test_sets_param_on_inactive_effect(
        self, param_server, param_state,
    ) -> None:
        srv, sock_path = param_server
        param_state.key.set(1)  # active = Plain; tune Fancy
        resp = _send(sock_path, {
            "jsonrpc": "2.0", "method": "set_param_for",
            "params": {"name": "Fancy", "param": "speed", "value": 0.9},
            "id": 1,
        })
        assert resp["result"]["value"] == 0.9
        # Verify via get_params_for
        resp2 = _send(sock_path, {
            "jsonrpc": "2.0", "method": "get_params_for",
            "params": {"name": "Fancy"}, "id": 2,
        })
        assert resp2["result"]["speed"]["value"] == 0.9

    def test_unknown_effect_errors(self, param_server) -> None:
        srv, sock_path = param_server
        resp = _send(sock_path, {
            "jsonrpc": "2.0", "method": "set_param_for",
            "params": {"name": "Nope", "param": "speed", "value": 0.5},
            "id": 1,
        })
        assert "error" in resp
        assert "unknown effect" in resp["error"]["message"]

    def test_unknown_param_errors(self, param_server) -> None:
        srv, sock_path = param_server
        resp = _send(sock_path, {
            "jsonrpc": "2.0", "method": "set_param_for",
            "params": {"name": "Fancy", "param": "nope", "value": 0.5},
            "id": 1,
        })
        assert "error" in resp
        assert "unknown param" in resp["error"]["message"]

    def test_out_of_range_errors(self, param_server) -> None:
        srv, sock_path = param_server
        resp = _send(sock_path, {
            "jsonrpc": "2.0", "method": "set_param_for",
            "params": {"name": "Fancy", "param": "speed", "value": 5.0},
            "id": 1,
        })
        assert "error" in resp
        assert "out of range" in resp["error"]["message"]


class TestResetParamsFor:
    def test_resets_inactive_effect(self, param_server, param_state) -> None:
        srv, sock_path = param_server
        _send(sock_path, {
            "jsonrpc": "2.0", "method": "set_param_for",
            "params": {"name": "Fancy", "param": "speed", "value": 0.9},
            "id": 1,
        })
        param_state.key.set(1)  # active = Plain
        resp = _send(sock_path, {
            "jsonrpc": "2.0", "method": "reset_params_for",
            "params": {"name": "Fancy"}, "id": 2,
        })
        assert "error" not in resp
        resp2 = _send(sock_path, {
            "jsonrpc": "2.0", "method": "get_params_for",
            "params": {"name": "Fancy"}, "id": 3,
        })
        assert resp2["result"]["speed"]["value"] == 0.5

    def test_unknown_effect_errors(self, param_server) -> None:
        srv, sock_path = param_server
        resp = _send(sock_path, {
            "jsonrpc": "2.0", "method": "reset_params_for",
            "params": {"name": "Nope"}, "id": 1,
        })
        assert "error" in resp
        assert "unknown effect" in resp["error"]["message"]


class TestResetParams:
    def test_resets_all_params_to_defaults(self, param_server) -> None:
        srv, sock_path = param_server
        _send(sock_path, {
            "jsonrpc": "2.0", "method": "set_param",
            "params": {"name": "speed", "value": 0.9}, "id": 1,
        })
        resp = _send(sock_path, {
            "jsonrpc": "2.0", "method": "reset_params", "id": 2,
        })
        assert "error" not in resp
        get_resp = _send(sock_path, {
            "jsonrpc": "2.0", "method": "get_params", "id": 3,
        })
        assert get_resp["result"]["speed"]["value"] == 0.5

    def test_no_params_is_not_an_error(self, param_server, param_state) -> None:
        srv, sock_path = param_server
        param_state.key.set(1)  # switch to Plain (no params)
        resp = _send(sock_path, {
            "jsonrpc": "2.0", "method": "reset_params", "id": 1,
        })
        assert "error" not in resp


class TestSetEffectAndGetParams:
    def test_switches_and_returns_params(self, param_server) -> None:
        srv, sock_path = param_server
        resp = _send(sock_path, {
            "jsonrpc": "2.0", "method": "set_effect_and_get_params",
            "params": {"name": "Fancy"}, "id": 1,
        })
        result = resp["result"]
        assert result["name"] == "Fancy"
        assert "speed" in result["params"]
        assert result["params"]["speed"]["value"] == 0.5

    def test_switches_to_effect_without_params(self, param_server) -> None:
        srv, sock_path = param_server
        resp = _send(sock_path, {
            "jsonrpc": "2.0", "method": "set_effect_and_get_params",
            "params": {"name": "Plain"}, "id": 1,
        })
        assert resp["result"]["name"] == "Plain"
        assert resp["result"]["params"] == {}

    def test_unknown_effect_returns_error(self, param_server) -> None:
        srv, sock_path = param_server
        resp = _send(sock_path, {
            "jsonrpc": "2.0", "method": "set_effect_and_get_params",
            "params": {"name": "Nope"}, "id": 1,
        })
        assert "error" in resp
        assert "unknown effect" in resp["error"]["message"]


class TestSetPaused:
    def test_pause(self, server, state) -> None:
        srv, sock_path = server
        resp = _send(sock_path, {
            "jsonrpc": "2.0", "method": "set_paused",
            "params": {"paused": True}, "id": 1,
        })
        assert resp["result"]["paused"] is True
        assert state.paused is True

    def test_resume(self, server, state) -> None:
        srv, sock_path = server
        state.set_paused(True)
        resp = _send(sock_path, {
            "jsonrpc": "2.0", "method": "set_paused",
            "params": {"paused": False}, "id": 1,
        })
        assert resp["result"]["paused"] is False
        assert state.paused is False

    def test_rejects_non_boolean(self, server) -> None:
        srv, sock_path = server
        resp = _send(sock_path, {
            "jsonrpc": "2.0", "method": "set_paused",
            "params": {"paused": "false"}, "id": 1,
        })
        assert "error" in resp
        assert "boolean" in resp["error"]["message"]

    def test_get_status_includes_paused(self, server, state) -> None:
        srv, sock_path = server
        resp = _send(sock_path, {
            "jsonrpc": "2.0", "method": "get_status", "id": 1,
        })
        assert resp["result"]["paused"] is False

        state.set_paused(True)
        resp = _send(sock_path, {
            "jsonrpc": "2.0", "method": "get_status", "id": 2,
        })
        assert resp["result"]["paused"] is True

    def test_paused_changed_notification(self, server) -> None:
        srv, sock_path = server
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.connect(str(sock_path))
        # Establish connection.
        s.sendall(json.dumps({
            "jsonrpc": "2.0", "method": "get_status", "id": 1,
        }).encode() + b"\n")
        data = b""
        while b"\n" not in data:
            data += s.recv(4096)
        data = b""

        srv.notify_paused_changed(True)

        s.settimeout(2.0)
        while b"\n" not in data:
            data += s.recv(4096)
        s.close()

        notification = json.loads(data)
        assert notification["jsonrpc"] == "2.0"
        assert notification["method"] == "paused_changed"
        assert notification["params"] == {"paused": True}
        assert "id" not in notification


class TestGetSideParams:
    def test_returns_side_params(self, param_server) -> None:
        srv, sock_path = param_server
        resp = _send(sock_path, {
            "jsonrpc": "2.0", "method": "get_side_params", "id": 1,
        })
        result = resp["result"]
        assert "brightness" in result
        assert result["brightness"]["value"] == 0.1


class TestSetSideParam:
    def test_set_valid_value(self, param_server) -> None:
        srv, sock_path = param_server
        resp = _send(sock_path, {
            "jsonrpc": "2.0", "method": "set_side_param",
            "params": {"name": "brightness", "value": 0.4}, "id": 1,
        })
        assert resp["result"] == {"name": "brightness", "value": 0.4}

    def test_out_of_range_returns_error(self, param_server) -> None:
        srv, sock_path = param_server
        resp = _send(sock_path, {
            "jsonrpc": "2.0", "method": "set_side_param",
            "params": {"name": "brightness", "value": 2.0}, "id": 1,
        })
        assert "error" in resp
        assert "out of range" in resp["error"]["message"]
