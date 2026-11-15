"""MIDI note read/edit tools: server command construction and Remote Script logic."""
import json
import os
import sys
import types
from unittest.mock import MagicMock, patch

import pytest


from MCP_Server import server  # noqa: E402
import AbletonMCP_Remote_Script as rs_module  # noqa: E402
from AbletonMCP_Remote_Script import AbletonMCP  # noqa: E402


# ── Fake Live clips ─────────────────────────────────────────────────

class _Note:
    def __init__(self, pitch, start_time, duration, velocity=100, mute=False,
                 probability=1.0, velocity_deviation=0.0, release_velocity=64):
        self.pitch = pitch
        self.start_time = start_time
        self.duration = duration
        self.velocity = velocity
        self.mute = mute
        self.probability = probability
        self.velocity_deviation = velocity_deviation
        self.release_velocity = release_velocity


class _ModernClip:
    """Live 11+ clip API."""
    is_midi_clip = True

    def __init__(self, name="Lead", notes=()):
        self.name = name
        self.length = 8.0
        self.loop_start = 0.0
        self.loop_end = 8.0
        self.notes = list(notes)

    def add_new_notes(self, specs):
        self.notes.extend(_Note(**vars(s)) for s in specs)

    def get_notes_extended(self, from_pitch, pitch_span, from_time, time_span):
        return [n for n in self.notes
                if from_pitch <= n.pitch < from_pitch + pitch_span
                and from_time <= n.start_time < from_time + time_span]

    def remove_notes_extended(self, from_pitch, pitch_span, from_time, time_span):
        doomed = self.get_notes_extended(from_pitch, pitch_span, from_time, time_span)
        self.notes = [n for n in self.notes if n not in doomed]


class _LegacyClip:
    """Live 10 clip API: tuples only."""
    is_midi_clip = True

    def __init__(self, notes=()):
        self.name = "Old"
        self.length = 4.0
        self.loop_start = 0.0
        self.loop_end = 4.0
        self.notes = list(notes)

    def set_notes(self, tuples):
        self.notes.extend(tuples)

    def get_notes(self, from_time, from_pitch, time_span, pitch_span):
        return tuple(n for n in self.notes
                     if from_pitch <= n[0] < from_pitch + pitch_span
                     and from_time <= n[1] < from_time + time_span)

    def remove_notes(self, from_time, from_pitch, time_span, pitch_span):
        doomed = self.get_notes(from_time, from_pitch, time_span, pitch_span)
        self.notes = [n for n in self.notes if n not in doomed]


class _Spec:
    def __init__(self, **kw):
        self.__dict__.update(kw)


@pytest.fixture
def fake_live(monkeypatch):
    monkeypatch.setattr(rs_module, "Live", types.SimpleNamespace(
        Clip=types.SimpleNamespace(MidiNoteSpecification=_Spec)))


def _rs_with_clip(clip):
    rs = AbletonMCP.__new__(AbletonMCP)
    slot = types.SimpleNamespace(has_clip=True, clip=clip)
    empty = types.SimpleNamespace(has_clip=False, clip=None)
    track = types.SimpleNamespace(name="Keys", clip_slots=[slot, empty],
                                  arrangement_clips=[clip])
    rs._song = types.SimpleNamespace(tracks=[track])
    return rs


# ── Remote Script ───────────────────────────────────────────────────

class TestRemoteScriptNotes:
    def test_add_uses_modern_api_with_extras(self, fake_live):
        clip = _ModernClip()
        rs = _rs_with_clip(clip)
        rs._add_notes(0, 0, [{"pitch": 60, "start_time": 0, "duration": 1,
                              "velocity": 90, "probability": 0.5}])
        assert len(clip.notes) == 1
        assert clip.notes[0].probability == 0.5

    def test_add_falls_back_to_set_notes(self, monkeypatch):
        monkeypatch.setattr(rs_module, "Live", None)
        clip = _LegacyClip()
        rs = _rs_with_clip(clip)
        rs._add_notes(0, 0, [{"pitch": 62, "start_time": 1, "duration": 0.5}])
        assert clip.notes == [(62, 1.0, 0.5, 100.0, False)]

    def test_replace_clears_first(self, fake_live):
        clip = _ModernClip(notes=[_Note(40, 0, 1), _Note(41, 1, 1)])
        rs = _rs_with_clip(clip)
        result = rs._add_notes(0, 0, [{"pitch": 72, "start_time": 0, "duration": 1}],
                               replace=True)
        assert result["removed"] == 2
        assert [n.pitch for n in clip.notes] == [72]

    def test_bad_note_rejected_before_replace(self, fake_live):
        clip = _ModernClip(notes=[_Note(40, 0, 1)])
        rs = _rs_with_clip(clip)
        with pytest.raises(ValueError, match="pitch"):
            rs._add_notes(0, 0, [{"pitch": 200}], replace=True)
        assert len(clip.notes) == 1  # untouched

    def test_get_notes_sorted(self):
        clip = _ModernClip(notes=[_Note(64, 1, 1), _Note(60, 0, 1), _Note(55, 1, 1)])
        result = _rs_with_clip(clip)._get_clip_notes(0, 0)
        assert [(n["start_time"], n["pitch"]) for n in result["notes"]] == [(0, 60), (1, 55), (1, 64)]

    def test_get_notes_legacy(self):
        clip = _LegacyClip(notes=[(60, 0.0, 1.0, 100, False)])
        result = _rs_with_clip(clip)._get_clip_notes(0, 0)
        assert result["notes"][0]["pitch"] == 60

    def test_get_notes_arrangement_by_name(self):
        clip = _ModernClip(name="Verse", notes=[_Note(60, 0, 1)])
        result = _rs_with_clip(clip)._get_clip_notes(0, 0, arrangement=True, clip_name="Verse")
        assert result["clip_name"] == "Verse"

    def test_session_clip_by_name(self):
        clip = _ModernClip(name="Hook")
        track, found = _rs_with_clip(clip)._resolve_any_clip(0, None, False, "Hook")
        assert found is clip

    def test_empty_slot_errors(self):
        rs = _rs_with_clip(_ModernClip())
        with pytest.raises(ValueError, match="No clip"):
            rs._get_clip_notes(0, 1)

    def test_remove_pitch_range(self):
        clip = _ModernClip(notes=[_Note(36, 0, 1), _Note(60, 0, 1), _Note(62, 1, 1)])
        result = _rs_with_clip(clip)._remove_clip_notes(0, 0, pitch_from=60, pitch_to=61)
        assert result["removed"] == 1
        assert sorted(n.pitch for n in clip.notes) == [36, 62]

    def test_remove_time_range(self):
        clip = _ModernClip(notes=[_Note(60, 0, 1), _Note(60, 2, 1), _Note(60, 4, 1)])
        _rs_with_clip(clip)._remove_clip_notes(0, 0, time_from=1.0, time_to=4.0)
        assert sorted(n.start_time for n in clip.notes) == [0, 4]

    def test_transpose(self, fake_live):
        clip = _ModernClip(notes=[_Note(60, 0, 1, velocity=80), _Note(64, 1, 1)])
        _rs_with_clip(clip)._transpose_clip_notes(0, 0, 12)
        assert sorted(n.pitch for n in clip.notes) == [72, 76]
        assert any(n.velocity == 80 for n in clip.notes)

    def test_transpose_out_of_range_is_rejected(self, fake_live):
        clip = _ModernClip(notes=[_Note(120, 0, 1)])
        with pytest.raises(ValueError, match="out of range"):
            _rs_with_clip(clip)._transpose_clip_notes(0, 0, 12)
        assert clip.notes[0].pitch == 120

    def test_quantize_full_and_half_strength(self, fake_live):
        clip = _ModernClip(notes=[_Note(60, 0.3, 0.5)])
        _rs_with_clip(clip)._quantize_clip_notes(0, 0, 0.25, strength=1.0)
        assert clip.notes[0].start_time == pytest.approx(0.25)

        clip = _ModernClip(notes=[_Note(60, 0.3, 0.5)])
        _rs_with_clip(clip)._quantize_clip_notes(0, 0, 0.25, strength=0.5)
        assert clip.notes[0].start_time == pytest.approx(0.275)


# ── Server ──────────────────────────────────────────────────────────

class TestServerNoteTools:
    @patch('MCP_Server.server.get_ableton_connection')
    def test_get_clip_notes_adds_names(self, mock_conn):
        ableton = MagicMock()
        ableton.send_command.return_value = {
            "clip_name": "Lead", "track_name": "Keys", "length": 4.0,
            "loop_start": 0, "loop_end": 4,
            "notes": [{"pitch": 60, "start_time": 0, "duration": 1, "velocity": 100, "mute": False}],
        }
        mock_conn.return_value = ableton

        out = server.get_clip_notes(MagicMock(), track_index=2, clip_index=3)

        ableton.send_command.assert_called_once_with(
            "get_clip_notes", {"track_index": 1, "arrangement": False, "clip_index": 2})
        notes = json.loads(out.split("\n", 1)[1])
        assert notes[0]["name"] == "C3"

    @patch('MCP_Server.server.get_ableton_connection')
    def test_add_notes_replace_flag(self, mock_conn):
        ableton = MagicMock()
        ableton.send_command.return_value = {"note_count": 1, "removed": 4}
        mock_conn.return_value = ableton

        out = server.add_notes_to_clip(MagicMock(), 1, 1, [{"pitch": 60}], replace=True)

        params = ableton.send_command.call_args[0][1]
        assert params["replace"] is True
        assert "replaced 4" in out

    @patch('MCP_Server.server.get_ableton_connection')
    def test_arrangement_notes_by_name(self, mock_conn):
        ableton = MagicMock()
        ableton.send_command.return_value = {"note_count": 2}
        mock_conn.return_value = ableton

        server.add_notes_to_arrangement_clip(MagicMock(), 1, [{"pitch": 60}, {"pitch": 62}],
                                             clip_name="Verse")

        name, params = ableton.send_command.call_args[0]
        assert name == "add_notes_to_arrangement_clip"
        assert params["clip_name"] == "Verse"
        assert params["arrangement"] is True

    @patch('MCP_Server.server.get_ableton_connection')
    def test_remove_end_beat_zero_means_open(self, mock_conn):
        ableton = MagicMock()
        ableton.send_command.return_value = {"removed": 3}
        mock_conn.return_value = ableton

        server.remove_clip_notes(MagicMock(), 1, 1, pitch_from=36, pitch_to=36)

        params = ableton.send_command.call_args[0][1]
        assert params["time_to"] is None
        assert params["pitch_from"] == 36

    @patch('MCP_Server.server.get_ableton_connection')
    def test_quantize_grid_names(self, mock_conn):
        ableton = MagicMock()
        ableton.send_command.return_value = {"note_count": 8, "strength": 1.0}
        mock_conn.return_value = ableton

        server.quantize_clip_notes(MagicMock(), 1, grid="1/8T")
        assert ableton.send_command.call_args[0][1]["grid"] == pytest.approx(1 / 3)

        out = server.quantize_clip_notes(MagicMock(), 1, grid="1/7")
        assert "unknown grid" in out

    def test_note_name(self):
        assert server.note_name(60) == "C3"
        assert server.note_name(0) == "C-2"
        assert server.note_name(69) == "A3"


class TestNoteWriteFailures:
    def test_failed_replace_restores_original_notes(self, fake_live):
        clip = _ModernClip(notes=[_Note(40, 0, 1), _Note(43, 1, 1)])
        rs = _rs_with_clip(clip)
        real_add = clip.add_new_notes
        calls = {"n": 0}

        def flaky_add(specs):
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("Live rejected the notes")
            real_add(specs)
        clip.add_new_notes = flaky_add

        with pytest.raises(RuntimeError, match="rejected"):
            rs._add_notes(0, 0, [{"pitch": 72}], replace=True)
        assert sorted(n.pitch for n in clip.notes) == [40, 43]

    def test_spec_signature_mismatch_falls_back_to_set_notes(self, monkeypatch):
        class _StrictSpec:
            def __init__(self, pitch, start_time, duration, velocity, mute):
                pass
        monkeypatch.setattr(rs_module, "Live", types.SimpleNamespace(
            Clip=types.SimpleNamespace(MidiNoteSpecification=_StrictSpec)))
        clip = _ModernClip()
        written = []
        clip.set_notes = lambda tuples: written.extend(tuples)
        _rs_with_clip(clip)._add_notes(0, 0, [{"pitch": 60, "probability": 0.5}])
        assert written == [(60, 0.0, 0.25, 100.0, False)]
