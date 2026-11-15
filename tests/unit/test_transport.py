"""Recording, metronome, quantization, time signature, undo/redo."""
import types
from unittest.mock import MagicMock, patch

import pytest

from MCP_Server import server
from AbletonMCP_Remote_Script import AbletonMCP


def _rs(**song_attrs):
    rs = AbletonMCP.__new__(AbletonMCP)
    defaults = dict(is_playing=False, tempo=120.0, signature_numerator=4,
                    signature_denominator=4, current_song_time=0.0, loop=False,
                    record_mode=False, session_record=False, arrangement_overdub=False,
                    session_automation_record=False, metronome=False,
                    clip_trigger_quantization=4, can_undo=True, can_redo=False)
    defaults.update(song_attrs)
    rs._song = types.SimpleNamespace(**defaults)
    return rs


class TestRemoteScript:
    def test_record_switches_only_change_given(self):
        rs = _rs()
        state = rs._set_record_state(arrangement_record=True, overdub=None)
        assert state["arrangement_record"] is True
        assert state["session_record"] is False

    def test_quantization_name_roundtrip(self):
        rs = _rs()
        rs._set_launch_quantization(7)
        assert rs._get_transport_state()["launch_quantization"] == "1/4"

    def test_time_signature_validation(self):
        rs = _rs()
        assert rs._set_time_signature(7, 8) == {"signature_numerator": 7, "signature_denominator": 8}
        with pytest.raises(ValueError):
            rs._set_time_signature(4, 3)

    def test_undo_and_nothing_to_redo(self):
        calls = []
        rs = _rs()
        rs._song.undo = lambda: calls.append("undo")
        assert rs._undo()["done"] == "undo"
        with pytest.raises(ValueError, match="Nothing to redo"):
            rs._undo(redo=True)
        assert calls == ["undo"]


class TestServer:
    @patch('MCP_Server.server.get_ableton_connection')
    def test_record_state_omits_unset(self, mock_conn):
        ableton = MagicMock()
        ableton.send_command.return_value = dict(arrangement_record=True, session_record=False,
                                                 arrangement_overdub=False,
                                                 session_automation_record=False)
        mock_conn.return_value = ableton
        server.set_record_state(MagicMock(), arrangement_record=True)
        ableton.send_command.assert_called_once_with("set_record_state", {"arrangement_record": True})

    @patch('MCP_Server.server.get_ableton_connection')
    def test_quantization_names(self, mock_conn):
        ableton = MagicMock()
        ableton.send_command.return_value = {"launch_quantization": "1/16"}
        mock_conn.return_value = ableton
        server.set_launch_quantization(MagicMock(), "1/16")
        assert ableton.send_command.call_args[0][1] == {"index": 11}
        assert "unknown" in server.set_launch_quantization(MagicMock(), "3 bars")
