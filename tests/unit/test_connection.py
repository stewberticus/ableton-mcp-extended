"""AbletonConnection keeps the socket on Live-side errors, drops it on transport errors."""
import json
import os
import socket
import sys
from unittest.mock import MagicMock

import pytest


from MCP_Server.server import (  # noqa: E402
    AbletonConnection, AbletonCommandError, _socket_is_alive,
    LONG_RESPONSE_TIMEOUT, DEFAULT_RESPONSE_TIMEOUT,
)


def _conn_with_reply(payload):
    conn = AbletonConnection(host="localhost", port=0)
    sock = MagicMock()
    sock.recv.return_value = json.dumps(payload).encode("utf-8")
    conn.sock = sock
    return conn, sock


def test_live_error_keeps_socket():
    conn, sock = _conn_with_reply({"status": "error", "message": "Track index out of range"})
    with pytest.raises(AbletonCommandError, match="out of range"):
        conn.send_command("get_track_info", {"track_index": 99})
    assert conn.sock is sock
    sock.close.assert_not_called()


def test_timeout_closes_socket():
    conn = AbletonConnection(host="localhost", port=0)
    sock = MagicMock()
    sock.recv.side_effect = socket.timeout()
    conn.sock = sock
    with pytest.raises(Exception, match="Timeout"):
        conn.send_command("get_session_info")
    assert conn.sock is None
    sock.close.assert_called_once()


def test_long_commands_use_long_timeout():
    conn, sock = _conn_with_reply({"status": "success", "result": {"loaded": True}})
    conn.send_command("load_browser_item", {"track_index": 0, "item_uri": "x"})
    sock.settimeout.assert_called_with(LONG_RESPONSE_TIMEOUT)

    conn, sock = _conn_with_reply({"status": "success", "result": {}})
    conn.send_command("get_session_info")
    sock.settimeout.assert_called_with(DEFAULT_RESPONSE_TIMEOUT)


def test_socket_liveness_probe():
    assert _socket_is_alive(None) is False
    a, b = socket.socketpair()
    try:
        assert _socket_is_alive(a) is True
        b.close()
        assert _socket_is_alive(a) is False
    finally:
        a.close()
