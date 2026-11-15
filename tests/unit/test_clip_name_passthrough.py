"""clip_name must reach the Remote Script and select the named clip.

Regression: set_arrangement_clip_property and manage_clip_automation accepted
clip_name but never sent it, so the edit silently hit clip #1.
"""
import os
import sys
import types
from unittest.mock import MagicMock, patch

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

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from MCP_Server.server import set_arrangement_clip_property, manage_clip_automation  # noqa: E402
from AbletonMCP_Remote_Script import AbletonMCP  # noqa: E402


class _Clip:
    def __init__(self, name):
        self.name = name
        self.muted = False
        self.envelopes_cleared = False

    def clear_all_envelopes(self):
        self.envelopes_cleared = True


def _make_rs(clips):
    rs = AbletonMCP.__new__(AbletonMCP)
    track = MagicMock()
    track.name = "Keys"
    track.arrangement_clips = clips
    rs._song = MagicMock()
    rs._song.tracks = [track]
    return rs


class TestServerSendsClipName:
    @patch('MCP_Server.server.get_ableton_connection')
    def test_set_property_sends_clip_name(self, mock_conn):
        ableton = MagicMock()
        ableton.send_command.return_value = {}
        mock_conn.return_value = ableton

        set_arrangement_clip_property(MagicMock(), track_index=1, clip_name="Chorus", muted=True)

        params = ableton.send_command.call_args[0][1]
        assert params["clip_name"] == "Chorus"
        assert params["properties"] == {"muted": True}

    @patch('MCP_Server.server.get_ableton_connection')
    def test_automation_sends_clip_name(self, mock_conn):
        ableton = MagicMock()
        ableton.send_command.return_value = {}
        mock_conn.return_value = ableton

        result = manage_clip_automation(MagicMock(), track_index=1, clip_name="Chorus",
                                        action="clear_all")

        params = ableton.send_command.call_args[0][1]
        assert params["clip_name"] == "Chorus"
        assert "'Chorus'" in result


class TestRemoteScriptUsesClipName:
    def test_set_property_targets_named_clip(self):
        intro, chorus = _Clip("Intro"), _Clip("Chorus")
        rs = _make_rs([intro, chorus])

        rs._set_clip_properties(0, 0, {"muted": True}, arrangement=True, clip_name="Chorus")

        assert chorus.muted is True
        assert intro.muted is False

    def test_automation_targets_named_clip(self):
        intro, chorus = _Clip("Intro"), _Clip("Chorus")
        rs = _make_rs([intro, chorus])

        rs._manage_clip_automation(0, 0, "clear_all", "", "Chorus")

        assert chorus.envelopes_cleared is True
        assert intro.envelopes_cleared is False
