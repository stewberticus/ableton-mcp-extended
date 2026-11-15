"""Tests for .SerumPreset -> .vstpreset conversion and the load_serum_preset tool."""
import json
import struct
from unittest.mock import MagicMock, patch

import pytest

from MCP_Server import serum_presets as sp
from MCP_Server.server import (
    _collect_external_plugins_from_root,
    _invalidate_external_plugin_cache,
    load_serum_preset,
)

PRESET_META = {
    "fileType": "SerumPreset", "hash": "abc123", "presetAuthor": "Me",
    "presetComment": "", "presetDescription": "Wobbly", "presetName": "Test Wub",
    "product": "Serum2", "productVersion": "2.1.5", "tags": ["Bass"],
    "url": "https://xferrecords.com/", "vendor": "Xfer Records", "version": 11.0,
}
PRESET_BODY = {
    "Oscillator0": {"WTOsc0": {"plainParams": {"kParamTablePos": 32.0}}},
    "Env0": {"plainParams": {"kParamAttack": 0.1}},
    "Macro0": {"plainParams": {}},
    "Osc": [{"kUIParamZoomToStartEnd": 0.0}],
    "SerumGUI": {"zoom": 1.0},
    "WTOsc": {"x": 1},
    "arpBankDisplayName": "Bank",
    "tags": ["Bass"],
    "fileType": "SerumPreset",
    "presetName": "Test Wub",
    "product": "Serum2", "productVersion": "2.1.5",
    "url": "https://xferrecords.com/", "vendor": "Xfer Records", "version": 11.0,
}


def make_preset(meta=None, body=None) -> bytes:
    return sp.pack_xferjson(meta or PRESET_META, body or PRESET_BODY)


def parse_vstpreset(data: bytes):
    assert data[:4] == b"VST3"
    version, = struct.unpack_from("<i", data, 4)
    class_id = data[8:40].decode("ascii")
    list_offset, = struct.unpack_from("<q", data, 40)
    assert data[list_offset:list_offset + 4] == b"List"
    count, = struct.unpack_from("<i", data, list_offset + 4)
    chunks = {}
    pos = list_offset + 8
    for _ in range(count):
        cid = data[pos:pos + 4]
        off, size = struct.unpack_from("<qq", data, pos + 4)
        chunks[cid] = data[off:off + size]
        pos += 20
    return version, class_id, chunks


class TestConversion:
    def test_xferjson_round_trip(self):
        meta, body = sp.unpack_xferjson(make_preset())
        assert meta == PRESET_META
        assert body == PRESET_BODY

    def test_rejects_non_serum_data(self):
        with pytest.raises(sp.SerumPresetError, match="XferJson"):
            sp.unpack_xferjson(b"not a preset")

    def test_rejects_state_that_is_not_a_preset_file(self):
        raw = make_preset(meta={"component": "processor"})
        with pytest.raises(sp.SerumPresetError, match="fileType"):
            sp.serum_preset_to_vstpreset(raw)

    def test_vstpreset_layout_and_class_id(self):
        version, class_id, chunks = parse_vstpreset(
            sp.serum_preset_to_vstpreset(make_preset(), "/x/Test Wub.SerumPreset"))
        assert version == 1
        assert class_id == sp.SERUM2_CLASS_ID
        assert set(chunks) == {b"Comp", b"Cont"}

    def test_split_into_processor_and_controller_states(self):
        _, _, chunks = parse_vstpreset(
            sp.serum_preset_to_vstpreset(make_preset(), "/x/Test Wub.SerumPreset"))
        p_meta, proc = sp.unpack_xferjson(chunks[b"Comp"])
        c_meta, ctrl = sp.unpack_xferjson(chunks[b"Cont"])

        assert p_meta["component"] == "processor"
        assert proc["component"] == "processor"
        # Sound data stays in the processor; UI and preset-only keys don't.
        assert proc["Oscillator0"] == PRESET_BODY["Oscillator0"]
        assert proc["Env0"] == PRESET_BODY["Env0"]
        for key in ("Osc", "SerumGUI", "WTOsc", "arpBankDisplayName",
                    "fileType", "presetName"):
            assert key not in proc

        assert c_meta["component"] == "controller"
        assert c_meta["presetName"] == "Test Wub"
        assert ctrl["presetName"] == "Test Wub"
        assert ctrl["presetAuthor"] == "Me"
        assert ctrl["selectedPresetPath"] == "/x/Test Wub.SerumPreset"
        assert ctrl["Osc"] == PRESET_BODY["Osc"]
        assert "Oscillator0" not in ctrl

    def test_write_vstpreset_skips_unchanged_rewrites(self, tmp_path):
        src = tmp_path / "Test Wub.SerumPreset"
        src.write_bytes(make_preset())
        out = tmp_path / "out"
        target = sp.write_vstpreset(src, out)
        assert target == out / "Test Wub.vstpreset"
        first_mtime = target.stat().st_mtime_ns
        sp.write_vstpreset(src, out)
        assert target.stat().st_mtime_ns == first_mtime
        assert not list(out.glob("*.tmp"))


class TestFindPreset:
    @pytest.fixture
    def library(self, tmp_path):
        for rel in ("User/DnB Wub Bass.SerumPreset", "User/DnB Wub Bass 2.SerumPreset",
                    "Factory/Bass/Wub.SerumPreset", "User/Wub.SerumPreset",
                    "User/notes.txt"):
            path = tmp_path / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"x")
        return tmp_path

    def test_exact_name_beats_partial_matches(self, library):
        assert sp.find_serum_preset("dnb wub bass", [library]) == \
            library / "User/DnB Wub Bass.SerumPreset"

    def test_single_partial_match(self, library):
        assert sp.find_serum_preset("Bass 2", [library]) == \
            library / "User/DnB Wub Bass 2.SerumPreset"

    def test_ambiguous_name_lists_candidates(self, library):
        with pytest.raises(sp.SerumPresetError, match="2 Serum presets match 'Wub'"):
            sp.find_serum_preset("Wub", [library])

    def test_folder_qualified_name(self, library):
        assert sp.find_serum_preset("Factory/Bass/Wub", [library]) == \
            library / "Factory/Bass/Wub.SerumPreset"

    def test_full_path(self, library):
        path = library / "User/Wub.SerumPreset"
        assert sp.find_serum_preset(str(path), []) == path

    def test_missing_path_and_name(self, library):
        with pytest.raises(sp.SerumPresetError, match="not found"):
            sp.find_serum_preset(str(library / "nope.SerumPreset"), [])
        with pytest.raises(sp.SerumPresetError, match="no Serum preset matches"):
            sp.find_serum_preset("Lead", [library])

    def test_roots_from_environment(self, library, monkeypatch):
        monkeypatch.setenv("SERUM_PRESETS_DIRS", str(library / "Factory"))
        assert sp.find_serum_preset("Wub") == library / "Factory/Bass/Wub.SerumPreset"


class TestLoadSerumPresetTool:
    @pytest.fixture
    def preset_file(self, tmp_path, monkeypatch):
        src = tmp_path / "presets" / "Test Wub.SerumPreset"
        src.parent.mkdir()
        src.write_bytes(make_preset())
        monkeypatch.setenv("SERUM_PRESETS_DIRS", str(src.parent))
        monkeypatch.setenv("SERUM_VSTPRESET_DIR", str(tmp_path / "vst"))
        return src

    @patch("MCP_Server.server.time.sleep", lambda s: None)
    @patch("MCP_Server.server.get_ableton_connection")
    def test_converts_waits_for_index_and_loads(self, mock_conn, preset_file, tmp_path):
        ableton = MagicMock()
        listings = [
            {"items": []},  # path probe
            {"items": []},  # not indexed yet
            {"items": [{"name": "Test Wub.vstpreset", "uri": "uri:wub"}]},
        ]

        def send(cmd, params=None):
            if cmd == "get_browser_items_at_path":
                return listings.pop(0)
            if cmd == "load_browser_item":
                return {"loaded": True}
            raise AssertionError(cmd)

        ableton.send_command.side_effect = send
        mock_conn.return_value = ableton

        result = load_serum_preset(None, track_index=2, preset="Test Wub")

        assert result.startswith("Loaded Serum preset 'Test Wub' on track 2")
        assert (tmp_path / "vst" / "Test Wub.vstpreset").is_file()
        ableton.send_command.assert_called_with("load_browser_item", {
            "track_index": 1, "track_type": "track", "item_uri": "uri:wub",
            "path": "plugins/VST3/Xfer Records/Serum 2/Test Wub.vstpreset",
        })

    @patch("MCP_Server.server._SERUM_BROWSER_WAIT_SECONDS", 0)
    @patch("MCP_Server.server.get_ableton_connection")
    def test_reports_when_live_never_indexes_the_file(self, mock_conn, preset_file):
        ableton = MagicMock()
        ableton.send_command.return_value = {"items": []}
        mock_conn.return_value = ableton
        result = load_serum_preset(None, track_index=1, preset="Test Wub")
        assert result.startswith("Error loading Serum preset")
        assert "hasn't indexed" in result

    @patch("MCP_Server.server.get_ableton_connection")
    def test_unknown_preset_never_touches_live(self, mock_conn, preset_file):
        result = load_serum_preset(None, track_index=1, preset="Nothing Like This")
        assert result.startswith("Error loading Serum preset")
        mock_conn.assert_not_called()


def test_plugin_discovery_skips_preset_files():
    _invalidate_external_plugin_cache()
    tree = {
        "plugins": {"items": [{"name": "Serum 2", "is_folder": True, "is_loadable": True,
                               "is_device": False, "uri": "uri:serum"}]},
        "plugins/Serum 2": {"items": [{"name": "Wub.vstpreset", "is_folder": False,
                                       "is_loadable": True, "is_device": False,
                                       "uri": "uri:wub"}]},
    }
    ableton = MagicMock()
    ableton.send_command.side_effect = lambda cmd, params: tree.get(params["path"], {"items": []})
    names = [p["name"] for p in _collect_external_plugins_from_root(ableton, "plugins")]
    assert names == ["Serum 2"]
