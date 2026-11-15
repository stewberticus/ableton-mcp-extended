"""Replies must describe what actually happened, in the 1-based terms tools use.

Each test here pins a mismatch found by a live smoke test of the connector.
"""
import types
from unittest.mock import MagicMock, patch

import pytest

from MCP_Server import server
from AbletonMCP_Remote_Script import AbletonMCP


class _StaleLoopSong:
    """A song whose loop settings read back the old values, as Live did."""

    def __init__(self):
        self._loop, self._start, self._length = False, 0.0, 16.0

    loop = property(lambda self: self._loop, lambda self, v: None)
    loop_start = property(lambda self: self._start, lambda self, v: None)
    loop_length = property(lambda self: self._length, lambda self, v: None)


def _track(name):
    return types.SimpleNamespace(name=name)


# ── set_arrangement_loop ─────────────────────────────────────────────

def test_remote_loop_reports_requested_values_not_stale_readback():
    rs = AbletonMCP.__new__(AbletonMCP)
    rs._song = _StaleLoopSong()
    assert rs._set_arrangement_loop(True, start=4.0, length=8.0) == {
        "enabled": True, "start": 4.0, "length": 8.0}


def test_remote_loop_reads_back_values_it_did_not_set():
    rs = AbletonMCP.__new__(AbletonMCP)
    rs._song = _StaleLoopSong()
    assert rs._set_arrangement_loop(False) == {"enabled": False, "start": 0.0, "length": 16.0}


@patch("MCP_Server.server._get_time_signature", return_value=(4, 4))
@patch("MCP_Server.server.get_ableton_connection")
def test_server_loop_reply_uses_requested_state(mock_conn, _ts):
    ableton = MagicMock()
    # The reply that produced "Loop disabled: bars 1-4" after enabling it.
    ableton.send_command.return_value = {"enabled": False, "start": 0.0, "length": 16.0}
    mock_conn.return_value = ableton
    reply = server.set_arrangement_loop(MagicMock(), enabled=True, start_bar=1, end_bar=4)
    assert reply == "Loop enabled: bars 1-4"


# ── get_session_info numbering ───────────────────────────────────────

def test_session_info_is_one_based():
    raw = {
        "track_count": 3,
        "tracks": [
            {"index": 0, "name": "1-Group", "group_index": None},
            {"index": 1, "name": "Bass", "group_index": 0},
            {"index": 2, "name": "Lead", "group_index": None},
        ],
        "return_tracks": [{"index": 0, "name": "A-Reverb"}],
    }
    out = server._session_info_one_based(raw)
    assert [t["index"] for t in out["tracks"]] == [1, 2, 3]
    assert out["tracks"][1]["group_index"] == 1
    assert out["tracks"][0]["group_index"] is None
    assert out["return_tracks"][0]["index"] == 1
    assert raw["tracks"][0]["index"] == 0  # internal callers keep the raw reply


@patch("MCP_Server.server.get_ableton_connection")
def test_get_session_info_tool_returns_one_based(mock_conn):
    ableton = MagicMock()
    ableton.send_command.return_value = {"tracks": [{"index": 0, "name": "Bass"}],
                                         "return_tracks": []}
    mock_conn.return_value = ableton
    assert '"index": 1' in server.get_session_info(MagicMock())


def test_session_info_uses_lives_master_name():
    rs = AbletonMCP.__new__(AbletonMCP)
    vol = types.SimpleNamespace(value=0.85, name="Volume", min=0.0, max=1.0)
    master = types.SimpleNamespace(name="Main", mixer_device=types.SimpleNamespace(
        volume=vol, panning=types.SimpleNamespace(value=0.0)))
    rs._song = types.SimpleNamespace(tracks=[], return_tracks=[], scenes=[], tempo=120,
                                     signature_numerator=4, signature_denominator=4,
                                     is_playing=False, master_track=master)
    assert rs._get_session_info()["master_track"]["name"] == "Main"


# ── reply wording for return / master targets ────────────────────────

@pytest.mark.parametrize("index,kind,label", [
    (3, "track", "track 3"),
    (3, "return", "return C"),
    (1, "RETURN", "return A"),
    (1, "master", "the master"),
])
def test_target_label(index, kind, label):
    assert server._target_label(index, kind) == label


# ── undo / redo say what changed ─────────────────────────────────────

def _snap(quant="1/4", tracks=("Bass", "Lead"), sig=(4, 4)):
    return {
        "transport": {"tempo": 120.0, "launch_quantization": quant, "metronome": False,
                      "signature_numerator": sig[0], "signature_denominator": sig[1]},
        "info": {"scene_count": 8, "tracks": [{"name": n, "mute": False} for n in tracks],
                 "return_tracks": [], "master_track": {"volume_display": "0.0 dB"}},
    }


def test_describe_undo_changes():
    assert server._describe_undo_changes(_snap(), _snap(quant="1 bar")) == [
        "launch quantization 1/4 -> 1 bar"]
    assert server._describe_undo_changes(_snap(sig=(7, 8)), _snap()) == [
        "time signature 7/8 -> 4/4"]
    assert server._describe_undo_changes(_snap(), _snap(tracks=("Bass",))) == [
        "tracks 2 -> 1; removed 'Lead'"]
    assert server._describe_undo_changes(_snap(), _snap()) == []
    assert server._describe_undo_changes(None, _snap()) == []


def _undo_conn(before, after, result):
    ableton = MagicMock()
    ableton.send_command.side_effect = [
        before["transport"], before["info"], result, after["transport"], after["info"]]
    return ableton


@patch("MCP_Server.server.get_ableton_connection")
def test_undo_reply_names_the_change(mock_conn):
    mock_conn.return_value = _undo_conn(_snap(), _snap(quant="1 bar"),
                                        {"can_undo": True, "can_redo": True})
    reply = server.undo(MagicMock())
    assert reply.startswith("Undone. Changed: launch quantization 1/4 -> 1 bar.")
    assert "redo available: True" in reply
    sent = [c[0][0] for c in mock_conn.return_value.send_command.call_args_list]
    assert sent[2] == "undo"


@patch("MCP_Server.server.get_ableton_connection")
def test_redo_reply_when_nothing_visible_changed(mock_conn):
    mock_conn.return_value = _undo_conn(_snap(), _snap(), {"can_undo": True, "can_redo": False})
    reply = server.redo(MagicMock())
    assert reply.startswith("Redone. No change seen")
    assert mock_conn.return_value.send_command.call_args_list[2][0][0] == "redo"


@patch("MCP_Server.server.get_ableton_connection")
def test_undo_still_runs_when_snapshot_fails(mock_conn):
    ableton = MagicMock()
    ableton.send_command.side_effect = [RuntimeError("busy"), {"can_undo": False},
                                        RuntimeError("busy")]
    mock_conn.return_value = ableton
    reply = server.undo(MagicMock())
    assert reply.startswith("Undone. Couldn't read the set")


# ── out-of-range track errors ────────────────────────────────────────

def test_track_out_of_range_error_gives_the_track_count():
    rs = AbletonMCP.__new__(AbletonMCP)
    rs._song = types.SimpleNamespace(tracks=[_track(str(i)) for i in range(6)],
                                     return_tracks=[_track("A")])
    with pytest.raises(IndexError, match=r"Track 99 out of range: the set has 6 tracks \(1-6\)"):
        rs._set_track_name(98, "x")
    with pytest.raises(IndexError, match=r"Return track 4 out of range: the set has 1 return track \(1-1\)"):
        rs._delete_return_track(3)
