"""The MCP server and the Remote Script must agree on command names.

Every command the server sends, and every name in its MODIFYING_COMMANDS /
LONG_COMMANDS sets, needs a handler in the Remote Script's command table.
"""
import os
import re
import sys
import types
from unittest.mock import MagicMock

_mock_fastmcp = MagicMock()
_mock_fastmcp.FastMCP.return_value.tool.return_value = lambda fn: fn
sys.modules.setdefault('mcp', MagicMock())
sys.modules.setdefault('mcp.server', MagicMock())
sys.modules.setdefault('mcp.server.fastmcp', _mock_fastmcp)


class _StubControlSurface:
    def __init__(self, c_instance):
        pass

    def log_message(self, msg):
        pass


_framework = types.ModuleType("_Framework")
_cs_module = types.ModuleType("_Framework.ControlSurface")
_cs_module.ControlSurface = _StubControlSurface
sys.modules.setdefault("_Framework", _framework)
sys.modules.setdefault("_Framework.ControlSurface", _cs_module)

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
sys.path.insert(0, REPO_ROOT)

from MCP_Server import server  # noqa: E402
from AbletonMCP_Remote_Script import AbletonMCP  # noqa: E402


def _remote_script_commands():
    rs = AbletonMCP.__new__(AbletonMCP)
    return set(rs._command_table().keys())


def _server_sent_commands():
    with open(os.path.join(REPO_ROOT, "MCP_Server", "server.py")) as f:
        source = f.read()
    return set(re.findall(r'send_command\(\s*"([a-z_]+)"', source))


def test_every_sent_command_has_a_handler():
    missing = _server_sent_commands() - _remote_script_commands()
    assert not missing, "Server sends commands the Remote Script cannot handle: %s" % sorted(missing)


def test_modifying_and_long_sets_name_real_commands():
    rs = _remote_script_commands()
    assert not (server.MODIFYING_COMMANDS - rs), sorted(server.MODIFYING_COMMANDS - rs)
    assert not (server.LONG_COMMANDS - rs), sorted(server.LONG_COMMANDS - rs)


def test_long_commands_match_between_layers():
    assert set(server.LONG_COMMANDS) == set(AbletonMCP.LONG_COMMANDS)


def test_server_waits_longer_than_remote_script():
    assert server.LONG_RESPONSE_TIMEOUT > AbletonMCP.LONG_TASK_TIMEOUT
    assert server.DEFAULT_RESPONSE_TIMEOUT > AbletonMCP.DEFAULT_TASK_TIMEOUT


# Handlers that exist in the Remote Script but have no MCP tool yet.
_NOT_YET_EXPOSED = {"add_notes_to_arrangement_clip"}


def test_every_remote_command_is_used_by_the_server():
    unused = _remote_script_commands() - _server_sent_commands() - _NOT_YET_EXPOSED
    assert not unused, "Remote Script handlers no tool sends: %s" % sorted(unused)


class TestDispatch:
    def _rs(self):
        rs = AbletonMCP.__new__(AbletonMCP)
        rs.log_message = lambda msg: None
        rs.schedule_message = lambda delay, fn: fn()
        return rs

    def test_unknown_command(self):
        resp = self._rs()._process_command({"type": "nope", "params": {}})
        assert resp["status"] == "error"
        assert "Unknown command" in resp["message"]

    def test_success_wraps_result(self):
        rs = self._rs()
        rs._set_tempo = lambda tempo: {"tempo": tempo}
        resp = rs._process_command({"type": "set_tempo", "params": {"tempo": 99}})
        assert resp == {"status": "success", "result": {"tempo": 99}}

    def test_handler_error_is_reported(self):
        rs = self._rs()

        def boom(tempo):
            raise ValueError("bad tempo")
        rs._set_tempo = boom
        resp = rs._process_command({"type": "set_tempo", "params": {"tempo": 1}})
        assert resp["status"] == "error"
        assert resp["message"] == "bad tempo"

    def test_timeout_cancels_unstarted_task(self):
        rs = self._rs()
        scheduled = []
        rs.schedule_message = lambda delay, fn: scheduled.append(fn)
        rs.DEFAULT_TASK_TIMEOUT = 0.01
        calls = []
        rs._set_tempo = lambda tempo: calls.append(tempo)

        resp = rs._process_command({"type": "set_tempo", "params": {"tempo": 1}})
        assert resp["status"] == "error"
        assert "cancelled" in resp["message"]

        scheduled[0]()  # Live gets round to it later
        assert calls == []
