"""Error reporting, ambiguous parameter names, browser tree depth, cue playhead, group clips."""
import types
from unittest.mock import MagicMock, patch

import pytest

from MCP_Server import server
from AbletonMCP_Remote_Script import AbletonMCP


class TestToolErrors:
    def test_error_strings_raise_for_mcp_clients(self):
        registered = []
        with patch.object(server.mcp, "tool", return_value=registered.append):
            @server.tool()
            def demo(ok: bool) -> str:
                return "fine" if ok else "Error: nope"

        wrapper = registered[0]
        assert wrapper(True) == "fine"
        with pytest.raises(server.ToolError, match="nope"):
            wrapper(False)
        # The module-level function keeps returning strings for direct callers.
        assert demo(False) == "Error: nope"


class TestParameterMatching:
    def _device(self, *names):
        params = [types.SimpleNamespace(name=n) for n in names]
        return types.SimpleNamespace(name="Wavetable", parameters=params)

    def test_unique_partial_match(self):
        rs = AbletonMCP.__new__(AbletonMCP)
        p, kind = rs._find_parameter(self._device("Device On", "Filter 1 Freq"), name="freq")
        assert (p.name, kind) == ("Filter 1 Freq", "partial")

    def test_ambiguous_partial_match_lists_candidates(self):
        rs = AbletonMCP.__new__(AbletonMCP)
        with pytest.raises(ValueError, match="Filter 1 Freq, Filter 2 Freq"):
            rs._find_parameter(self._device("Filter 1 Freq", "Filter 2 Freq"), name="freq")

    def test_exact_match_beats_partial(self):
        rs = AbletonMCP.__new__(AbletonMCP)
        p, kind = rs._find_parameter(self._device("Freq", "Filter 2 Freq"), name="freq")
        assert (p.name, kind) == ("Freq", "case_insensitive")


class _Item:
    def __init__(self, name, children=()):
        self.name, self.uri = name, name
        self.children = list(children)
        self.is_device = self.is_loadable = not children


def test_browser_tree_includes_subfolders():
    synths = _Item("Synths", [_Item("Bass", [_Item("Sub")]), _Item("loose device")])
    browser = types.SimpleNamespace(instruments=_Item("Instruments", [synths]))
    rs = AbletonMCP.__new__(AbletonMCP)
    rs.application = lambda: types.SimpleNamespace(browser=browser)
    tree = rs.get_browser_tree("instruments")
    root = tree["categories"][0]
    assert root["children"][0]["name"] == "Synths"
    assert root["children"][0]["children"][0]["name"] == "Bass"
    assert root["children"][0]["children"][0]["has_more"] is True  # depth limit
    assert tree["total_folders"] >= 3


def test_cue_point_restores_playhead():
    class _Song:
        def __init__(self):
            self.current_song_time = 33.0
            self.cue_points = []

        def set_or_delete_cue(self):
            self.cue_points.append(types.SimpleNamespace(time=self.current_song_time, name=""))

    rs = AbletonMCP.__new__(AbletonMCP)
    rs._song = _Song()
    rs._create_cue_point(16.0, "Chorus")
    assert rs._song.current_song_time == 33.0
    assert rs._song.cue_points[0].name == "Chorus"


def test_group_track_cannot_hold_arrangement_clips():
    group = types.SimpleNamespace(name="Drum Bus", is_foldable=True, arrangement_clips=[])
    rs = AbletonMCP.__new__(AbletonMCP)
    rs._song = types.SimpleNamespace(tracks=[group])
    with pytest.raises(ValueError, match="group track"):
        rs._create_arrangement_clip(0, 0.0, 4.0)
