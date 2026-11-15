"""Track management: group-safe delete, duplicate, color, fold, return deletion."""
import os
import sys
import types
from unittest.mock import MagicMock, patch

import pytest


from MCP_Server import server  # noqa: E402
from AbletonMCP_Remote_Script import AbletonMCP  # noqa: E402


class _T:
    def __init__(self, name, group=None, foldable=False):
        self.name = name
        self.group_track = group
        self.is_grouped = group is not None
        self.is_foldable = foldable
        self.fold_state = False
        self.color = 0


def _rs(tracks):
    rs = AbletonMCP.__new__(AbletonMCP)
    song = types.SimpleNamespace(tracks=tracks, return_tracks=[])
    song.delete_track = lambda i: tracks.pop(i)
    song.duplicate_track = lambda i: tracks.insert(i + 1, _T(tracks[i].name + " copy"))
    rs._song = song
    return rs


class TestRemoteScript:
    def test_group_delete_needs_confirmation(self):
        bus = _T("Drum Bus", foldable=True)
        tracks = [bus, _T("Kick", bus), _T("Snare", bus), _T("Bass")]
        rs = _rs(tracks)
        with pytest.raises(ValueError, match="Kick, Snare"):
            rs._delete_track(0)
        result = rs._delete_track(0, delete_group_contents=True)
        assert result["deleted_group_contents"] == ["Kick", "Snare"]

    def test_group_delete_refused_if_it_would_empty_the_set(self):
        bus = _T("Bus", foldable=True)
        rs = _rs([bus, _T("Only", bus)])
        with pytest.raises(ValueError, match="every session track"):
            rs._delete_track(0, delete_group_contents=True)

    def test_empty_group_deletes_without_flag(self):
        rs = _rs([_T("Empty Group", foldable=True), _T("Bass")])
        assert rs._delete_track(0)["deleted_track"] == "Empty Group"

    def test_duplicate_reports_new_index(self):
        rs = _rs([_T("Drums"), _T("Bass")])
        assert rs._duplicate_track(1) == {"index": 2, "name": "Bass copy"}

    def test_fold_requires_group(self):
        rs = _rs([_T("Bass")])
        with pytest.raises(ValueError, match="not a group"):
            rs._set_track_fold(0, True)


class TestServer:
    @patch('MCP_Server.server.get_ableton_connection')
    def test_ambiguous_name(self, mock_conn):
        ableton = MagicMock()
        ableton.send_command.return_value = {"track_count": 3, "tracks": [
            {"index": 0, "name": "Pad"}, {"index": 1, "name": "pad"}, {"index": 2, "name": "x"}]}
        mock_conn.return_value = ableton
        out = server.delete_track(MagicMock(), track_name="Pad")
        assert "tracks 1, 2" in out
        assert ableton.send_command.call_count == 1

    @patch('MCP_Server.server.get_ableton_connection')
    def test_hex_color(self, mock_conn):
        ableton = MagicMock()
        ableton.send_command.return_value = {"track_name": "Bass", "color": 0xFF0000}
        mock_conn.return_value = ableton
        out = server.set_track_color(MagicMock(), 1, "#ff0000")
        assert ableton.send_command.call_args[0][1]["color"] == 0xFF0000
        assert "#FF0000" in out
