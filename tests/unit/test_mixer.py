"""Mixer tools: mute/solo/arm, sends, return tracks, master, device tools on returns."""
import os
import sys
import types
from unittest.mock import MagicMock, patch

import pytest

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

from MCP_Server import server  # noqa: E402
from AbletonMCP_Remote_Script import AbletonMCP  # noqa: E402


class _Param:
    def __init__(self, value, name="p", lo=0.0, hi=1.0):
        self.value, self.name, self.min, self.max = value, name, lo, hi

    def __str__(self):
        return "{0:.2f} units".format(self.value)


class _Track:
    def __init__(self, name, sends=0, can_be_armed=True):
        self.name = name
        self.mute = self.solo = self.arm = False
        self.can_be_armed = can_be_armed
        self.devices = ["dev"]
        self.mixer_device = types.SimpleNamespace(
            volume=_Param(0.85, "Volume"), panning=_Param(0.0, "Pan", -1.0, 1.0),
            sends=[_Param(0.0, "Send") for _ in range(sends)])


def _rs(tracks, returns):
    rs = AbletonMCP.__new__(AbletonMCP)
    song = types.SimpleNamespace(tracks=tracks, return_tracks=returns,
                                 master_track=_Track("Master", can_be_armed=False))

    def create_return_track():
        returns.append(_Track("{0}-Return".format(chr(65 + len(returns))), can_be_armed=False))
        for t in tracks:
            t.mixer_device.sends.append(_Param(0.0, "Send"))
    song.create_return_track = create_return_track
    rs._song = song
    return rs


class TestRemoteScriptMixer:
    def test_mute_solo_arm(self):
        drums, bass = _Track("Drums"), _Track("Bass")
        rs = _rs([drums, bass], [])
        rs._set_track_flag(0, "mute", True)
        rs._set_track_flag(1, "arm", True)
        assert drums.mute and bass.arm

    def test_exclusive_solo(self):
        drums, bass = _Track("Drums"), _Track("Bass")
        drums.solo = True
        rs = _rs([drums, bass], [])
        rs._set_track_flag(1, "solo", True, exclusive=True)
        assert bass.solo and not drums.solo

    def test_group_cannot_be_armed(self):
        rs = _rs([_Track("Group", can_be_armed=False)], [])
        with pytest.raises(ValueError, match="cannot be armed"):
            rs._set_track_flag(0, "arm", True)

    def test_master_has_no_mute(self):
        rs = _rs([_Track("A")], [])
        with pytest.raises(ValueError, match="master"):
            rs._set_track_flag(0, "mute", True, "master")

    def test_send_level_clamped(self):
        keys = _Track("Keys", sends=2)
        rs = _rs([keys], [_Track("A-Reverb"), _Track("B-Delay")])
        result = rs._set_track_send(0, 1, 1.5)
        assert keys.mixer_device.sends[1].value == 1.0
        assert result["return_track"] == "B-Delay"

    def test_send_without_returns(self):
        rs = _rs([_Track("Keys")], [])
        with pytest.raises(ValueError, match="no sends"):
            rs._set_track_send(0, 0, 0.5)

    def test_create_return_track(self):
        rs = _rs([_Track("Keys")], [])
        assert rs._create_return_track() == {"index": 0, "name": "A-Return"}

    def test_volume_on_return_and_master(self):
        reverb = _Track("A-Reverb")
        rs = _rs([_Track("Keys")], [reverb])
        rs._set_track_volume(0, 0.5, "return")
        rs._set_track_volume(0, 0.6, "master")
        assert reverb.mixer_device.volume.value == 0.5
        assert rs._song.master_track.mixer_device.volume.value == 0.6

    def test_legacy_return_index_past_tracks(self):
        reverb = _Track("A-Reverb")
        rs = _rs([_Track("Keys")], [reverb])
        rs._set_track_volume(1, 0.4)
        assert reverb.mixer_device.volume.value == 0.4

    def test_device_on_return_track(self):
        reverb = _Track("A-Reverb")
        rs = _rs([_Track("Keys")], [reverb])
        track, device = rs._resolve_device(0, 0, track_type="return")
        assert track is reverb

    def test_device_track_rejects_return_index_for_session_type(self):
        rs = _rs([_Track("Keys")], [_Track("A-Reverb")])
        with pytest.raises(IndexError):
            rs._resolve_device(1, 0)


class TestServerMixer:
    @patch('MCP_Server.server.get_ableton_connection')
    def test_send_letter(self, mock_conn):
        ableton = MagicMock()
        ableton.send_command.return_value = {"track_name": "Keys", "return_track": "B-Delay",
                                             "value": 0.5, "display": "-6.0 dB"}
        mock_conn.return_value = ableton

        out = server.set_track_send(MagicMock(), 2, send="B", level=0.5)

        ableton.send_command.assert_called_once_with("set_track_send", {
            "track_index": 1, "track_type": "track", "send_index": 1, "value": 0.5})
        assert "B-Delay" in out

    @patch('MCP_Server.server.get_ableton_connection')
    def test_send_by_return_name(self, mock_conn):
        ableton = MagicMock()
        ableton.send_command.side_effect = [
            {"return_tracks": [{"name": "A-Reverb"}, {"name": "B-Delay"}]},
            {"track_name": "Keys", "value": 0.3},
        ]
        mock_conn.return_value = ableton

        server.set_track_send(MagicMock(), 1, send="delay", level=0.3)

        assert ableton.send_command.call_args[0][1]["send_index"] == 1

    @patch('MCP_Server.server.get_ableton_connection')
    def test_master_volume_ignores_index(self, mock_conn):
        ableton = MagicMock()
        ableton.send_command.return_value = {"track_name": "Master", "volume": 0.8,
                                             "volume_display": "-1.2 dB"}
        mock_conn.return_value = ableton

        out = server.set_track_volume(MagicMock(), track_index=0, volume=0.8, track_type="master")

        ableton.send_command.assert_called_once_with(
            "set_track_volume", {"track_index": 0, "track_type": "master", "volume": 0.8})
        assert "-1.2 dB" in out

    @patch('MCP_Server.server.get_ableton_connection')
    def test_load_effect_on_return(self, mock_conn):
        ableton = MagicMock()
        ableton.send_command.return_value = {"loaded": True}
        mock_conn.return_value = ableton

        server.load_instrument_or_effect(MagicMock(), 1, "query:Reverb", track_type="return")

        params = ableton.send_command.call_args[0][1]
        assert params["track_type"] == "return"
        assert params["track_index"] == 0

    @patch('MCP_Server.server.get_ableton_connection')
    def test_bad_track_type(self, mock_conn):
        out = server.set_track_mute(MagicMock(), 1, track_type="bus")
        assert "track_type" in out
        mock_conn.return_value.send_command.assert_not_called()
