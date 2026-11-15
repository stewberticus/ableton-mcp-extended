"""Device loading: path hints, URI cache, new-device reporting, load_device by name."""
import types
from unittest.mock import MagicMock, patch

from MCP_Server import server
from AbletonMCP_Remote_Script import AbletonMCP


class _Item:
    def __init__(self, name, uri=None, children=None):
        self.name = name
        self.uri = uri or name
        self.children = children or []
        self.is_folder = bool(children)
        self.is_device = not children
        self.is_loadable = not children


class _Browser:
    def __init__(self, instruments, audio_effects=None):
        self.instruments = instruments
        self.sounds = _Item("Sounds", children=[_Item("x")])
        self.drums = _Item("Drums", children=[_Item("y")])
        self.audio_effects = audio_effects or _Item("Audio Effects", children=[_Item("z")])
        self.midi_effects = _Item("MIDI Effects", children=[_Item("w")])
        self.plugins = _Item("Plugins", children=[_Item("v")])
        self.loaded = []

    def load_item(self, item):
        self.loaded.append(item)
        self.track.devices.append(types.SimpleNamespace(name=item.name))


def _rs(browser):
    rs = AbletonMCP.__new__(AbletonMCP)
    track = types.SimpleNamespace(name="Keys", devices=[types.SimpleNamespace(name="EQ Eight")])
    browser.track = track
    rs._song = types.SimpleNamespace(tracks=[track], view=types.SimpleNamespace(selected_track=None))
    rs.application = lambda: types.SimpleNamespace(browser=browser)
    return rs


def test_path_hint_avoids_full_walk_and_reports_new_devices():
    operator = _Item("Operator", uri="op-uri")
    browser = _Browser(_Item("Instruments", children=[_Item("Synths", children=[operator])]))
    rs = _rs(browser)
    rs._find_browser_item_by_uri = MagicMock(side_effect=AssertionError("full walk"))

    result = rs._load_browser_item(0, "op-uri", path="instruments/Synths")

    assert browser.loaded == [operator]
    assert result["new_devices"] == ["Operator"]
    assert result["devices_after"] == ["EQ Eight", "Operator"]


def test_uri_cache_skips_second_walk():
    operator = _Item("Operator", uri="op-uri")
    browser = _Browser(_Item("Instruments", children=[operator]))
    rs = _rs(browser)
    rs._load_browser_item(0, "op-uri")
    rs._find_browser_item_by_uri = MagicMock(side_effect=AssertionError("full walk"))
    rs._load_browser_item(0, "op-uri")
    assert len(browser.loaded) == 2


@patch('MCP_Server.server.get_ableton_connection')
def test_load_device_by_name(mock_conn):
    server._native_device_cache.clear()
    ableton = MagicMock()

    def send(cmd, params=None):
        if cmd == "get_browser_items_at_path":
            if params["path"] == "audio_effects":
                return {"items": [
                    {"name": "Reverb", "uri": "rv", "is_loadable": True, "is_device": True},
                    {"name": "Hybrid Reverb", "uri": "hrv", "is_loadable": True, "is_device": True},
                ]}
            return {"items": []}
        if cmd == "load_browser_item":
            return {"loaded": True, "devices_after": ["Reverb"]}
        raise AssertionError(cmd)
    ableton.send_command.side_effect = send
    mock_conn.return_value = ableton

    out = server.load_device(MagicMock(), 1, "reverb", category="audio_effects")

    load_params = ableton.send_command.call_args[0][1]
    assert load_params["item_uri"] == "rv"  # exact name beats "Hybrid Reverb"
    assert load_params["path"] == "audio_effects/Reverb"
    assert "Loaded Reverb" in out


@patch('MCP_Server.server.get_ableton_connection')
def test_load_device_ambiguous(mock_conn):
    server._native_device_cache.clear()
    ableton = MagicMock()
    ableton.send_command.return_value = {"items": [
        {"name": "Auto Filter", "uri": "a", "is_loadable": True, "is_device": True},
        {"name": "Auto Pan", "uri": "b", "is_loadable": True, "is_device": True},
    ]}
    mock_conn.return_value = ableton
    out = server.load_device(MagicMock(), 1, "auto", category="audio_effects")
    assert "several devices" in out
