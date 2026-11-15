"""Unit tests for track-level MCP tools."""
import sys
import os
from unittest.mock import MagicMock, patch


from MCP_Server.server import create_audio_track, delete_track, get_track_deletion_status


class TestDeleteTrackSafetyGuard:
    """Prevent deleting the final remaining session track."""

    @patch('MCP_Server.server.get_ableton_connection')
    def test_blocks_delete_by_index_when_only_one_track_remains(self, mock_conn):
        mock_ableton = MagicMock()
        mock_ableton.send_command.return_value = {"track_count": 1}
        mock_conn.return_value = mock_ableton

        result = delete_track(MagicMock(), track_index=1)

        assert "Cannot delete the last remaining session track" in result
        assert "Create a new track before deleting" in result
        mock_ableton.send_command.assert_called_once_with("get_session_info")

    @patch('MCP_Server.server.get_ableton_connection')
    def test_blocks_delete_by_name_when_only_one_track_remains(self, mock_conn):
        mock_ableton = MagicMock()
        mock_ableton.send_command.return_value = {"track_count": 1}
        mock_conn.return_value = mock_ableton

        result = delete_track(MagicMock(), track_index=0, track_name="My Track")

        assert "Cannot delete the last remaining session track" in result
        assert "Create a new track before deleting" in result
        mock_ableton.send_command.assert_called_once_with("get_session_info")


class TestDeleteTrackBehavior:
    """Normal delete behavior when more than one track exists."""

    @patch('MCP_Server.server.get_ableton_connection')
    def test_delete_by_index_still_works_with_multiple_tracks(self, mock_conn):
        mock_ableton = MagicMock()
        mock_ableton.send_command.side_effect = [
            {"track_count": 3},  # get_session_info
            {"deleted_track": "Bass", "remaining_tracks": 2},  # delete_track
        ]
        mock_conn.return_value = mock_ableton

        result = delete_track(MagicMock(), track_index=2)

        assert "Deleted track 'Bass'" in result
        calls = mock_ableton.send_command.call_args_list
        assert calls[1][0][0] == "delete_track"
        assert calls[1][0][1]["track_index"] == 1  # 2 -> 1

    @patch('MCP_Server.server.get_ableton_connection')
    def test_delete_by_name_resolves_and_deletes(self, mock_conn):
        mock_ableton = MagicMock()
        mock_ableton.send_command.side_effect = [
            {"track_count": 3, "tracks": [  # get_session_info
                {"index": 0, "name": "Drums"},
                {"index": 1, "name": "Bass"},
                {"index": 2, "name": "Keys"},
            ]},
            {"deleted_track": "Bass", "remaining_tracks": 2},  # delete_track
        ]
        mock_conn.return_value = mock_ableton

        result = delete_track(MagicMock(), track_index=0, track_name="Bass")

        assert "Deleted track 'Bass'" in result
        delete_call = mock_ableton.send_command.call_args_list[-1]
        assert delete_call[0][0] == "delete_track"
        assert delete_call[0][1]["track_index"] == 1


class TestTrackDeletionStatus:
    """Tests for get_track_deletion_status precheck tool."""

    @patch('MCP_Server.server.get_ableton_connection')
    def test_reports_blocked_when_one_track_remains(self, mock_conn):
        mock_ableton = MagicMock()
        mock_ableton.send_command.return_value = {"track_count": 1}
        mock_conn.return_value = mock_ableton

        result = get_track_deletion_status(MagicMock())

        assert "Track deletion blocked" in result
        assert "Create a new track before deleting" in result

    @patch('MCP_Server.server.get_ableton_connection')
    def test_reports_max_deletions_when_multiple_tracks_exist(self, mock_conn):
        mock_ableton = MagicMock()
        mock_ableton.send_command.return_value = {"track_count": 4}
        mock_conn.return_value = mock_ableton

        result = get_track_deletion_status(MagicMock())

        assert "Track deletion available" in result
        assert "up to 3 more track(s)" in result


class TestCreateAudioTrack:
    """create_audio_track forwards to the Remote Script."""

    @patch('MCP_Server.server.get_ableton_connection')
    def test_creates_audio_track_at_end_by_default(self, mock_conn):
        mock_ableton = MagicMock()
        mock_ableton.send_command.return_value = {"index": 3, "name": "4-Audio"}
        mock_conn.return_value = mock_ableton

        result = create_audio_track(MagicMock())

        mock_ableton.send_command.assert_called_once_with("create_audio_track", {"index": -1})
        assert "Created new audio track: 4-Audio" in result

    @patch('MCP_Server.server.get_ableton_connection')
    def test_insert_index_is_one_based(self, mock_conn):
        mock_ableton = MagicMock()
        mock_ableton.send_command.return_value = {"index": 0, "name": "1-Audio"}
        mock_conn.return_value = mock_ableton

        result = create_audio_track(MagicMock(), index=1)

        mock_ableton.send_command.assert_called_once_with("create_audio_track", {"index": 0})
        assert "(track 1)" in result
        assert "moved down by one" in result

    @patch('MCP_Server.server.get_ableton_connection')
    def test_zero_and_minus_one_mean_end(self, mock_conn):
        mock_ableton = MagicMock()
        mock_ableton.send_command.return_value = {"index": 5, "name": "6-Audio"}
        mock_conn.return_value = mock_ableton

        create_audio_track(MagicMock(), index=0)
        result = create_audio_track(MagicMock(), index=-1)

        for call in mock_ableton.send_command.call_args_list:
            assert call[0][1] == {"index": -1}
        assert "(track 6)" in result
        assert "moved down" not in result

    @patch('MCP_Server.server.get_ableton_connection')
    def test_midi_track_uses_same_convention(self, mock_conn):
        from MCP_Server.server import create_midi_track
        mock_ableton = MagicMock()
        mock_ableton.send_command.return_value = {"index": 2, "name": "3-MIDI"}
        mock_conn.return_value = mock_ableton

        result = create_midi_track(MagicMock(), index=3)

        mock_ableton.send_command.assert_called_once_with("create_midi_track", {"index": 2})
        assert "Created new MIDI track: 3-MIDI (track 3)" in result

    @patch('MCP_Server.server.get_ableton_connection')
    def test_reports_errors(self, mock_conn):
        mock_ableton = MagicMock()
        mock_ableton.send_command.side_effect = Exception("boom")
        mock_conn.return_value = mock_ableton

        result = create_audio_track(MagicMock())

        assert "Error creating audio track: boom" in result
