"""Scenes, session clip slots and clip properties."""
import os
import sys
import types
from unittest.mock import MagicMock, patch

import pytest


from MCP_Server import server  # noqa: E402
from AbletonMCP_Remote_Script import AbletonMCP  # noqa: E402


class _StrictClip:
    """Clip that, like Live, rejects loop_start >= loop_end at any step."""

    def __init__(self, audio=True):
        self.name = "Loop"
        self.is_audio_clip = audio
        self.is_midi_clip = not audio
        self.looping = True
        self._loop_start, self._loop_end = 0.0, 4.0
        self.warp_mode = 0

    @property
    def loop_start(self):
        return self._loop_start

    @loop_start.setter
    def loop_start(self, v):
        if v >= self._loop_end:
            raise RuntimeError("loop_start must be < loop_end")
        self._loop_start = v

    @property
    def loop_end(self):
        return self._loop_end

    @loop_end.setter
    def loop_end(self, v):
        if v <= self._loop_start:
            raise RuntimeError("loop_end must be > loop_start")
        self._loop_end = v


class _Slot:
    def __init__(self, clip=None):
        self.clip = clip
        self.copied_to = None

    @property
    def has_clip(self):
        return self.clip is not None

    def delete_clip(self):
        self.clip = None

    def duplicate_clip_to(self, target):
        target.clip = self.clip
        self.copied_to = target


def _rs(slots, scenes=None):
    rs = AbletonMCP.__new__(AbletonMCP)
    track = types.SimpleNamespace(name="Drums", clip_slots=slots, arrangement_clips=[])
    song = types.SimpleNamespace(tracks=[track], scenes=scenes or [])
    rs._song = song
    return rs


class TestClipProperties:
    def test_move_loop_past_old_end(self):
        clip = _StrictClip()
        rs = _rs([_Slot(clip)])
        rs._set_clip_properties(0, 0, {"loop_start": 8.0, "loop_end": 12.0})
        assert (clip.loop_start, clip.loop_end) == (8.0, 12.0)

    def test_shrink_loop(self):
        clip = _StrictClip()
        rs = _rs([_Slot(clip)])
        rs._set_clip_properties(0, 0, {"loop_start": 1.0, "loop_end": 2.0})
        assert (clip.loop_start, clip.loop_end) == (1.0, 2.0)

    def test_audio_only_props_rejected_on_midi(self):
        rs = _rs([_Slot(_StrictClip(audio=False))])
        with pytest.raises(ValueError, match="audio clips"):
            rs._set_clip_properties(0, 0, {"warp_mode": 4})

    def test_unknown_property(self):
        rs = _rs([_Slot(_StrictClip())])
        with pytest.raises(ValueError, match="not allowed"):
            rs._set_clip_properties(0, 0, {"tempo": 3})

    @patch('MCP_Server.server.get_ableton_connection')
    def test_server_warp_mode_by_name(self, mock_conn):
        ableton = MagicMock()
        ableton.send_command.return_value = {"properties": {"warp_mode": 6}}
        mock_conn.return_value = ableton
        server.set_clip_property(MagicMock(), 1, 2, warp_mode="Complex Pro", warping=True)
        name, params = ableton.send_command.call_args[0]
        assert name == "set_clip_properties"
        assert params["properties"] == {"warp_mode": 6, "warping": True}
        assert params["arrangement"] is False and params["clip_index"] == 1

    def test_bad_warp_mode(self):
        with patch('MCP_Server.server.get_ableton_connection'):
            out = server.set_clip_property(MagicMock(), 1, 1, warp_mode="stretchy")
        assert "Unknown warp mode" in out


class TestSlotsAndScenes:
    def test_delete_and_duplicate(self):
        clip = _StrictClip()
        src, dst = _Slot(clip), _Slot()
        rs = _rs([src, dst])
        rs._duplicate_clip_to_slot(0, 0, 0, 1)
        assert dst.clip is clip
        with pytest.raises(ValueError, match="already has a clip"):
            rs._duplicate_clip_to_slot(0, 0, 0, 1)
        rs._delete_clip(0, 1)
        assert dst.clip is None

    def test_scene_lifecycle(self):
        class _Scene:
            def __init__(self, name):
                self.name = name
                self.clip_slots = [_Slot(_StrictClip())]
                self.fired = False

            def fire(self):
                self.fired = True

        scenes = [_Scene("Intro")]
        rs = _rs([], scenes)
        rs._song.create_scene = lambda i: scenes.append(_Scene("")) if i == -1 else scenes.insert(i, _Scene(""))
        rs._song.delete_scene = lambda i: scenes.pop(i)

        assert rs._create_scene(-1)["index"] == 1
        rs._set_scene_name(1, "Drop")
        rs._fire_scene(1)
        assert scenes[1].fired and scenes[1].name == "Drop"
        assert [s["name"] for s in rs._get_scenes()["scenes"]] == ["Intro", "Drop"]
        rs._delete_scene(0)
        with pytest.raises(ValueError, match="last scene"):
            rs._delete_scene(0)

    @patch('MCP_Server.server.get_ableton_connection')
    def test_server_create_scene_with_name(self, mock_conn):
        ableton = MagicMock()
        ableton.send_command.side_effect = [{"index": 4, "name": ""}, {"name": "Outro"}]
        mock_conn.return_value = ableton
        out = server.create_scene(MagicMock(), name="Outro")
        assert ableton.send_command.call_args_list[0][0] == ("create_scene", {"index": -1})
        assert ableton.send_command.call_args_list[1][0] == (
            "set_scene_name", {"scene_index": 4, "name": "Outro"})
        assert "scene 5" in out
