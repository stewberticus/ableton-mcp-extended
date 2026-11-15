# Tool reference

Generated from `MCP_Server/server.py` by `python scripts/gen_tools_doc.py`;
do not edit by hand. Each tool's full parameter documentation is its
docstring, which MCP clients show.

Conventions: track, clip slot, scene, device and parameter numbers are
1-based. Bar ranges are inclusive (bars 1-4 is four bars). Tools that
act on mixer or devices take `track_type` = `track` / `return` / `master`.

81 tools.

| Tool | Parameters | What it does |
| --- | --- | --- |
| `get_session_info` | - | Get detailed information about the current Ableton session |
| `get_track_info` | `track_index`, `track_type='track'` | Get detailed information about a specific track in Ableton. |
| `create_midi_track` | `index=0` | Create a new MIDI track in the Ableton session. |
| `create_audio_track` | `index=0` | Create a new audio track in the Ableton session. |
| `set_track_name` | `track_index`, `name` | Set the name of a track. |
| `get_track_volume` | `track_index=1`, `track_type='track'` | Get the current fader volume (with Live's dB readout) and panning for a track. |
| `set_track_volume` | `track_index=1`, `volume=0.85`, `track_type='track'` | Set the mixer fader volume for a track, return track or the master. |
| `set_track_panning` | `track_index=1`, `panning=0.0`, `track_type='track'` | Set the mixer panning for a track, return track or the master. |
| `set_track_mute` | `track_index`, `mute=True`, `track_type='track'` | Mute or unmute a track (track activator off/on). |
| `set_track_solo` | `track_index`, `solo=True`, `exclusive=False`, `track_type='track'` | Solo or unsolo a track. |
| `set_track_arm` | `track_index`, `arm=True` | Arm or disarm a session track for recording. |
| `set_track_send` | `track_index`, `send='A'`, `level=0.0`, `track_type='track'` | Set how much of a track is sent to a return track (reverb/delay buses). |
| `create_return_track` | - | Add a new return track (for a shared reverb or delay bus). |
| `create_clip` | `track_index`, `clip_index`, `length=4.0` | Create a new MIDI clip in the specified track and clip slot. |
| `add_notes_to_clip` | `track_index`, `clip_index`, `notes`, `replace=False`, `clip_name=''` | Add MIDI notes to a session clip. |
| `add_notes_to_arrangement_clip` | `track_index`, `notes`, `clip_index=1`, `clip_name=''`, `replace=False` | Add MIDI notes to an arrangement clip (create one first with create_arrangement_midi_clip). |
| `get_clip_notes` | `track_index`, `clip_index=1`, `clip_name=''`, `arrangement=False` | Read the MIDI notes in a clip, so you can inspect, vary or fix a part. |
| `remove_clip_notes` | `track_index`, `clip_index=1`, `clip_name=''`, `arrangement=False`, `pitch_from=0`, `pitch_to=127`, `start_beat=0.0`, `end_beat=0.0` | Remove MIDI notes from a clip. With no ranges given, clears the clip. |
| `transpose_clip_notes` | `track_index`, `semitones`, `clip_index=1`, `clip_name=''`, `arrangement=False` | Transpose every note in a clip by a number of semitones (12 = one octave up). |
| `quantize_clip_notes` | `track_index`, `grid='1/16'`, `strength=1.0`, `quantize_ends=False`, `clip_index=1`, `clip_name=''`, `arrangement=False` | Quantize note start times in a clip to a grid. |
| `set_clip_name` | `track_index`, `clip_index`, `name` | Set the name of a clip. |
| `set_tempo` | `tempo` | Set the tempo of the Ableton session. |
| `load_instrument_or_effect` | `track_index`, `uri`, `track_type='track'`, `path=''` | Load an instrument or effect onto a track using its URI. |
| `fire_clip` | `track_index`, `clip_index` | Start playing a clip. |
| `stop_clip` | `track_index`, `clip_index` | Stop playing a clip. |
| `start_playback` | - | Start playing the Ableton session. |
| `stop_playback` | - | Stop playing the Ableton session. |
| `get_transport_state` | - | Show transport and recording state: playing, tempo, time signature, record/overdub/automation switches, metronome, launch quantization and whether undo/redo/capture are available. |
| `set_record_state` | `arrangement_record=None`, `session_record=None`, `overdub=None`, `automation_record=None` | Turn recording switches on or off. Only the switches you pass change. |
| `capture_midi` | `destination='auto'` | Capture MIDI: turn what was just played on an armed/monitored MIDI track into a clip, even if recording was off. |
| `set_metronome` | `enabled=True` | Turn the metronome on or off. |
| `set_launch_quantization` | `quantization='1 bar'` | Set global clip launch quantization (when fired clips/scenes start). |
| `set_time_signature` | `numerator=4`, `denominator=4` | Set the song's time signature. |
| `undo` | - | Undo the last change in Live (same as Cmd/Ctrl+Z). |
| `redo` | - | Redo the last undone change in Live. The reply says what changed. |
| `get_browser_tree` | `category_type='all'` | Get a hierarchical tree of browser categories from Ableton. |
| `get_browser_items_at_path` | `path` | Get browser items at a specific path in Ableton's browser. |
| `list_external_plugins` | `query=''`, `max_results=50`, `refresh_cache=False` | List discovered external plugins (VST/AU), optionally filtered by name query. |
| `load_external_plugin` | `track_index`, `plugin_name`, `exact_match=False`, `refresh_cache=False`, `track_type='track'` | Load an external plugin onto a track by plugin name (no URI required). |
| `load_serum_preset` | `track_index`, `preset`, `track_type='track'` | Load a Serum 2 preset (.SerumPreset) onto a track as a ready-to-play Serum 2 device. |
| `load_device` | `track_index`, `name`, `category='auto'`, `track_type='track'` | Load one of Live's built-in devices by name, e.g. "Operator", "Wavetable", "Drift", "Reverb", "EQ Eight", "Compressor", "Arpeggiator". |
| `load_drum_kit` | `track_index`, `rack_uri`, `kit_path`, `track_type='track'` | Load a drum rack and then load a specific drum kit into it. |
| `get_arrangement_info` | `track_index=0` | Get arrangement clips and transport state. |
| `get_cue_points` | - | List all cue points (locators) with bar positions. |
| `set_song_time` | `bar=0`, `beat=0.0` | Jump playback to a position. |
| `set_arrangement_loop` | `enabled=True`, `start_bar=0`, `end_bar=0`, `start_beat=None`, `length_beats=None` | Enable/disable arrangement loop and set region. |
| `jump_to_cue_point` | `direction=''`, `name=''` | Jump to a cue point. |
| `create_cue_point` | `bar=0`, `beat=0.0`, `name=''` | Create a cue point at a position. |
| `delete_cue_point` | `bar=0`, `beat=0.0` | Delete a cue point at a position. |
| `create_arrangement_midi_clip` | `track_index`, `start_bar=0`, `end_bar=0`, `start_beat=0.0`, `length_beats=4.0`, `name=''` | Create an empty MIDI clip in the arrangement. |
| `create_arrangement_audio_clip` | `track_index`, `file_path`, `start_bar=0`, `start_beat=0.0` | Place an audio file as a clip in the arrangement. |
| `duplicate_clip_to_arrangement` | `track_index`, `clip_index`, `destination_bar=0`, `destination_beat=0.0` | Copy a session clip to the arrangement. |
| `delete_arrangement_clip` | `track_index`, `clip_index=0`, `clip_name=''` | Delete an arrangement clip. |
| `set_clip_property` | `track_index`, `clip_index=1`, `clip_name=''`, `name=''`, `muted=None`, `color=None`, `looping=None`, `loop_start=None`, `loop_end=None`, `start_marker=None`, `end_marker=None`, `gain=None`, `pitch_coarse=None`, `pitch_fine=None`, `warping=None`, `warp_mode=None` | Set properties on a session clip (loop, length, gain, warp, pitch, color...). |
| `set_arrangement_clip_property` | `track_index`, `clip_index=1`, `clip_name=''`, `name=''`, `muted=None`, `color=None`, `looping=None`, `loop_start=None`, `loop_end=None`, `start_marker=None`, `end_marker=None`, `gain=None`, `pitch_coarse=None`, `pitch_fine=None`, `warping=None`, `warp_mode=None` | Set properties on an arrangement clip. Only the properties you pass change. |
| `delete_clip` | `track_index`, `clip_index` | Delete the clip in a session clip slot. |
| `duplicate_clip_to_slot` | `track_index`, `clip_index`, `target_clip_index`, `target_track_index=0` | Copy a session clip into another (empty) clip slot. |
| `get_scenes` | - | List the session's scenes (rows) with how many clips each holds. |
| `create_scene` | `index=0`, `name=''` | Insert a new empty scene. |
| `duplicate_scene` | `scene_index` | Duplicate a scene (and all its clips) into a new scene right below it. |
| `delete_scene` | `scene_index` | Delete a scene and the clips in it. |
| `set_scene_name` | `scene_index`, `name` | Rename a scene. |
| `fire_scene` | `scene_index` | Launch every clip in a scene. |
| `stop_all_clips` | - | Stop every playing session clip (like the Stop All Clips button). |
| `set_ableton_view` | `view='Arranger'` | Switch Ableton's main view. |
| `control_arrangement_view` | `action`, `track_index=0` | Control the arrangement view. |
| `manage_clip_automation` | `track_index`, `clip_index=1`, `clip_name=''`, `action='create'`, `parameter_name='volume'` | Create or clear automation envelopes on arrangement clips. |
| `get_device_parameters` | `track_index`, `device_index=1`, `chain_index=0`, `chain_device_index=1`, `category=''`, `show_all=False`, `track_type='track'` | List parameters for a device on a track. |
| `set_device_parameter` | `track_index`, `device_index=1`, `chain_index=0`, `chain_device_index=1`, `parameter_name=''`, `parameter_index=0`, `value=0.0`, `track_type='track'` | Set a device parameter value. |
| `enable_device` | `track_index`, `device_index=0`, `device_name=''`, `chain_index=0`, `chain_device_index=1`, `track_type='track'` | Enable (activate) a device on a track. |
| `disable_device` | `track_index`, `device_index=0`, `device_name=''`, `chain_index=0`, `chain_device_index=1`, `track_type='track'` | Disable (bypass) a device on a track. |
| `get_chain_info` | `track_index`, `device_index=1`, `chain_index=0`, `track_type='track'` | List chains in a rack device, or devices within a specific chain. |
| `get_drum_pad_info` | `track_index`, `device_index=1`, `track_type='track'` | List filled drum pads in a Drum Rack. |
| `delete_device` | `track_index`, `device_index=0`, `device_name=''`, `track_type='track'` | Delete a device from a track. |
| `get_track_deletion_status` | - | Check whether session tracks can be deleted right now. |
| `delete_track` | `track_index=0`, `track_name=''`, `delete_group_contents=False` | Delete a track from the Ableton session. |
| `delete_return_track` | `return_index` | Delete a return track. Sends to it are removed from every track. |
| `duplicate_track` | `track_index` | Duplicate a track with its devices and clips. The copy goes right after it. |
| `set_track_color` | `track_index`, `color` | Set a track's color. |
| `set_group_folded` | `track_index`, `folded=True` | Fold (collapse) or unfold a group track. |
| `navigate_device_preset` | `track_index`, `device_index=1`, `chain_index=0`, `chain_device_index=1`, `direction='next'`, `track_type='track'` | Navigate device presets (next/previous/current). |
