# AbletonMCP/init.py
from __future__ import absolute_import, print_function, unicode_literals

from _Framework.ControlSurface import ControlSurface
import socket
import json
import threading
import time
import traceback

# Change queue import for Python 2
try:
    import Queue as queue  # Python 2
except ImportError:
    import queue  # Python 3

# The Live module only exists inside Ableton; tests run without it.
try:
    import Live
except ImportError:
    Live = None

# Constants for socket communication
DEFAULT_PORT = 9877
HOST = "localhost"

def create_instance(c_instance):
    """Create and return the AbletonMCP script instance"""
    return AbletonMCP(c_instance)

class AbletonMCP(ControlSurface):
    """AbletonMCP Remote Script for Ableton Live"""
    
    def __init__(self, c_instance):
        """Initialize the control surface"""
        ControlSurface.__init__(self, c_instance)
        self.log_message("AbletonMCP Remote Script initializing...")
        
        # Socket server for communication
        self.server = None
        self.client_threads = []
        self.server_thread = None
        self.running = False
        
        # Cache the song reference for easier access
        self._song = self.song()
        
        # Start the socket server
        self.start_server()
        
        self.log_message("AbletonMCP initialized")
        
        # Show a message in Ableton
        self.show_message("AbletonMCP: Listening for commands on port " + str(DEFAULT_PORT))
    
    def disconnect(self):
        """Called when Ableton closes or the control surface is removed"""
        self.log_message("AbletonMCP disconnecting...")
        self.running = False
        
        # Stop the server
        if self.server:
            try:
                self.server.close()
            except:
                pass
        
        # Wait for the server thread to exit
        if self.server_thread and self.server_thread.is_alive():
            self.server_thread.join(1.0)
            
        # Clean up any client threads
        for client_thread in self.client_threads[:]:
            if client_thread.is_alive():
                # We don't join them as they might be stuck
                self.log_message("Client thread still alive during disconnect")
        
        ControlSurface.disconnect(self)
        self.log_message("AbletonMCP disconnected")
    
    def start_server(self):
        """Start the socket server in a separate thread"""
        try:
            self.server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.server.bind((HOST, DEFAULT_PORT))
            self.server.listen(5)  # Allow up to 5 pending connections
            
            self.running = True
            self.server_thread = threading.Thread(target=self._server_thread)
            self.server_thread.daemon = True
            self.server_thread.start()
            
            self.log_message("Server started on port " + str(DEFAULT_PORT))
        except Exception as e:
            self.log_message("Error starting server: " + str(e))
            self.show_message("AbletonMCP: Error starting server - " + str(e))
    
    def _server_thread(self):
        """Server thread implementation - handles client connections"""
        try:
            self.log_message("Server thread started")
            # Set a timeout to allow regular checking of running flag
            self.server.settimeout(1.0)
            
            while self.running:
                try:
                    # Accept connections with timeout
                    client, address = self.server.accept()
                    self.log_message("Connection accepted from " + str(address))
                    self.show_message("AbletonMCP: Client connected")
                    
                    # Handle client in a separate thread
                    client_thread = threading.Thread(
                        target=self._handle_client,
                        args=(client,)
                    )
                    client_thread.daemon = True
                    client_thread.start()
                    
                    # Keep track of client threads
                    self.client_threads.append(client_thread)
                    
                    # Clean up finished client threads
                    self.client_threads = [t for t in self.client_threads if t.is_alive()]
                    
                except socket.timeout:
                    # No connection yet, just continue
                    continue
                except Exception as e:
                    if self.running:  # Only log if still running
                        self.log_message("Server accept error: " + str(e))
                    time.sleep(0.5)
            
            self.log_message("Server thread stopped")
        except Exception as e:
            self.log_message("Server thread error: " + str(e))
    
    def _handle_client(self, client):
        """Handle communication with a connected client"""
        self.log_message("Client handler started")
        client.settimeout(None)  # No timeout for client socket
        buffer = ''  # Changed from b'' to '' for Python 2
        
        try:
            while self.running:
                try:
                    # Receive data
                    data = client.recv(8192)
                    
                    if not data:
                        # Client disconnected
                        self.log_message("Client disconnected")
                        break
                    
                    # Accumulate data in buffer with explicit encoding/decoding
                    try:
                        # Python 3: data is bytes, decode to string
                        buffer += data.decode('utf-8')
                    except AttributeError:
                        # Python 2: data is already string
                        buffer += data
                    
                    try:
                        # Try to parse command from buffer
                        command = json.loads(buffer)  # Removed decode('utf-8')
                        buffer = ''  # Clear buffer after successful parse
                        
                        self.log_message("Received command: " + str(command.get("type", "unknown")))
                        
                        # Process the command and get response
                        response = self._process_command(command)
                        
                        # Send the response with explicit encoding
                        try:
                            # Python 3: encode string to bytes
                            client.sendall(json.dumps(response).encode('utf-8'))
                        except AttributeError:
                            # Python 2: string is already bytes
                            client.sendall(json.dumps(response))
                    except ValueError:
                        # Incomplete data, wait for more
                        continue
                        
                except Exception as e:
                    self.log_message("Error handling client data: " + str(e))
                    self.log_message(traceback.format_exc())
                    
                    # Send error response if possible
                    error_response = {
                        "status": "error",
                        "message": str(e)
                    }
                    try:
                        # Python 3: encode string to bytes
                        client.sendall(json.dumps(error_response).encode('utf-8'))
                    except AttributeError:
                        # Python 2: string is already bytes
                        client.sendall(json.dumps(error_response))
                    except:
                        # If we can't send the error, the connection is probably dead
                        break
                    
                    # For serious errors, break the loop
                    if not isinstance(e, ValueError):
                        break
        except Exception as e:
            self.log_message("Error in client handler: " + str(e))
        finally:
            try:
                client.close()
            except:
                pass
            self.log_message("Client handler stopped")
    
    # ── Command dispatch ─────────────────────────────────────────────
    #
    # Every command the MCP server can send is listed exactly once in
    # _command_table(). All handlers run on Live's main thread: the Live
    # Object Model is not thread-safe, so even reads must not run on the
    # socket thread.

    # Default seconds to wait for a main-thread task before reporting a timeout.
    DEFAULT_TASK_TIMEOUT = 10.0
    # Commands that can legitimately take longer (browser walks, device loads).
    LONG_TASK_TIMEOUT = 30.0
    LONG_COMMANDS = frozenset([
        "load_browser_item",
        "get_browser_tree",
        "get_browser_items_at_path",
    ])

    def _command_table(self):
        """Map command name -> handler(params). The single source of truth."""
        def g(p, key, default=None):
            return p.get(key, default)

        return {
            # Session / transport
            "get_session_info": lambda p: self._get_session_info(),
            "set_tempo": lambda p: self._set_tempo(g(p, "tempo", 120.0)),
            "start_playback": lambda p: self._start_playback(),
            "stop_playback": lambda p: self._stop_playback(),
            "set_song_time": lambda p: self._set_song_time(g(p, "time", 0.0)),
            "set_arrangement_loop": lambda p: self._set_arrangement_loop(
                g(p, "enabled", True), g(p, "start"), g(p, "length")),
            "get_cue_points": lambda p: self._get_cue_points(),
            "jump_to_cue": lambda p: self._jump_to_cue(g(p, "direction"), g(p, "name")),
            "create_cue_point": lambda p: self._create_cue_point(
                g(p, "time", 0.0), g(p, "name", "")),
            "delete_cue_point": lambda p: self._delete_cue_point(g(p, "time", 0.0)),
            # Tracks
            "get_track_info": lambda p: self._get_track_info(
                g(p, "track_index", 0), g(p, "track_type", "track")),
            "create_midi_track": lambda p: self._create_midi_track(g(p, "index", -1)),
            "create_audio_track": lambda p: self._create_audio_track(g(p, "index", -1)),
            "set_track_name": lambda p: self._set_track_name(
                g(p, "track_index", 0), g(p, "name", "")),
            "delete_track": lambda p: self._delete_track(
                g(p, "track_index", 0), g(p, "delete_group_contents", False)),
            "delete_return_track": lambda p: self._delete_return_track(g(p, "return_index", 0)),
            "duplicate_track": lambda p: self._duplicate_track(g(p, "track_index", 0)),
            "set_track_color": lambda p: self._set_track_color(
                g(p, "track_index", 0), g(p, "color", 0)),
            "set_track_fold": lambda p: self._set_track_fold(
                g(p, "track_index", 0), g(p, "folded", True)),
            # Mixer
            "get_track_volume": lambda p: self._get_track_volume(
                g(p, "track_index", 0), g(p, "track_type", "track")),
            "set_track_volume": lambda p: self._set_track_volume(
                g(p, "track_index", 0), g(p, "volume", 0.85), g(p, "track_type", "track")),
            "set_track_panning": lambda p: self._set_track_panning(
                g(p, "track_index", 0), g(p, "panning", 0.0), g(p, "track_type", "track")),
            "set_track_mute": lambda p: self._set_track_flag(
                g(p, "track_index", 0), "mute", g(p, "mute", True), g(p, "track_type", "track")),
            "set_track_solo": lambda p: self._set_track_flag(
                g(p, "track_index", 0), "solo", g(p, "solo", True), g(p, "track_type", "track"),
                g(p, "exclusive", False)),
            "set_track_arm": lambda p: self._set_track_flag(
                g(p, "track_index", 0), "arm", g(p, "arm", True)),
            "set_track_send": lambda p: self._set_track_send(
                g(p, "track_index", 0), g(p, "send_index", 0), g(p, "value", 0.0),
                g(p, "track_type", "track")),
            "create_return_track": lambda p: self._create_return_track(),
            # Session clips
            "create_clip": lambda p: self._create_clip(
                g(p, "track_index", 0), g(p, "clip_index", 0), g(p, "length", 4.0)),
            "add_notes_to_clip": lambda p: self._add_notes(
                g(p, "track_index", 0), g(p, "clip_index", 0), g(p, "notes", []),
                False, g(p, "clip_name"), g(p, "replace", False)),
            "set_clip_name": lambda p: self._set_clip_name(
                g(p, "track_index", 0), g(p, "clip_index", 0), g(p, "name", "")),
            "fire_clip": lambda p: self._fire_clip(g(p, "track_index", 0), g(p, "clip_index", 0)),
            "stop_clip": lambda p: self._stop_clip(g(p, "track_index", 0), g(p, "clip_index", 0)),
            "delete_clip": lambda p: self._delete_clip(g(p, "track_index", 0), g(p, "clip_index", 0)),
            "duplicate_clip_to_slot": lambda p: self._duplicate_clip_to_slot(
                g(p, "track_index", 0), g(p, "clip_index", 0),
                g(p, "target_track_index", 0), g(p, "target_clip_index", 0)),
            "set_clip_properties": lambda p: self._set_clip_properties(
                g(p, "track_index", 0), g(p, "clip_index", 0), g(p, "properties", {}),
                g(p, "arrangement", False), g(p, "clip_name")),
            # Scenes
            "get_scenes": lambda p: self._get_scenes(),
            "create_scene": lambda p: self._create_scene(g(p, "index", -1)),
            "duplicate_scene": lambda p: self._duplicate_scene(g(p, "scene_index", 0)),
            "delete_scene": lambda p: self._delete_scene(g(p, "scene_index", 0)),
            "set_scene_name": lambda p: self._set_scene_name(
                g(p, "scene_index", 0), g(p, "name", "")),
            "fire_scene": lambda p: self._fire_scene(g(p, "scene_index", 0)),
            "stop_all_clips": lambda p: self._stop_all_clips(),
            # Browser
            "get_browser_tree": lambda p: self.get_browser_tree(g(p, "category_type", "all")),
            "get_browser_items_at_path": lambda p: self.get_browser_items_at_path(g(p, "path", "")),
            "load_browser_item": lambda p: self._load_browser_item(
                g(p, "track_index", 0), g(p, "item_uri", ""), g(p, "track_type", "track")),
            # Arrangement
            "get_arrangement_info": lambda p: self._get_arrangement_info(g(p, "track_index", -1)),
            "create_arrangement_clip": lambda p: self._create_arrangement_clip(
                g(p, "track_index", 0), g(p, "position", 0.0), g(p, "length", 4.0)),
            "create_arrangement_audio_clip": lambda p: self._create_arrangement_audio_clip(
                g(p, "track_index", 0), g(p, "position", 0.0), g(p, "file_path", "")),
            "duplicate_to_arrangement": lambda p: self._duplicate_to_arrangement(
                g(p, "track_index", 0), g(p, "clip_index", 0), g(p, "destination_time", 0.0)),
            "delete_arrangement_clip": lambda p: self._delete_arrangement_clip(
                g(p, "track_index", 0), g(p, "clip_index"), g(p, "clip_name")),

            "manage_clip_automation": lambda p: self._manage_clip_automation(
                g(p, "track_index", 0), g(p, "clip_index", 0), g(p, "action", "create"),
                g(p, "parameter_name", ""), g(p, "clip_name")),
            "add_notes_to_arrangement_clip": lambda p: self._add_notes(
                g(p, "track_index", 0), g(p, "clip_index", 0), g(p, "notes", []),
                True, g(p, "clip_name"), g(p, "replace", False)),
            # MIDI note editing (session or arrangement clips)
            "get_clip_notes": lambda p: self._get_clip_notes(
                g(p, "track_index", 0), g(p, "clip_index", 0), g(p, "arrangement", False),
                g(p, "clip_name")),
            "remove_clip_notes": lambda p: self._remove_clip_notes(
                g(p, "track_index", 0), g(p, "clip_index", 0), g(p, "arrangement", False),
                g(p, "clip_name"), g(p, "pitch_from", 0), g(p, "pitch_to", 127),
                g(p, "time_from", 0.0), g(p, "time_to")),
            "transpose_clip_notes": lambda p: self._transpose_clip_notes(
                g(p, "track_index", 0), g(p, "clip_index", 0), g(p, "semitones", 0),
                g(p, "arrangement", False), g(p, "clip_name")),
            "quantize_clip_notes": lambda p: self._quantize_clip_notes(
                g(p, "track_index", 0), g(p, "clip_index", 0), g(p, "grid", 0.25),
                g(p, "strength", 1.0), g(p, "quantize_ends", False),
                g(p, "arrangement", False), g(p, "clip_name")),
            # Views
            "set_view": lambda p: self._set_view(g(p, "view_name", "Arranger")),
            "control_arrangement_view": lambda p: self._control_arrangement_view(
                g(p, "action", ""), g(p, "track_index", 0)),
            # Devices
            "get_device_parameters": lambda p: self._get_device_parameters(
                g(p, "track_index", 0), g(p, "device_index", 0), g(p, "chain_index"),
                g(p, "show_all", False), track_type=g(p, "track_type", "track")),
            "set_device_parameter": lambda p: self._set_device_parameter(
                g(p, "track_index", 0), g(p, "device_index", 0), g(p, "chain_index"),
                g(p, "parameter_name"), g(p, "parameter_index"), g(p, "value", 0.0),
                track_type=g(p, "track_type", "track")),
            "set_device_enabled": lambda p: self._set_device_enabled(
                g(p, "track_index", 0), g(p, "device_index", 0), g(p, "chain_index"),
                g(p, "enabled", True), track_type=g(p, "track_type", "track")),
            "delete_device": lambda p: self._delete_device(
                g(p, "track_index", 0), g(p, "device_index", 0), track_type=g(p, "track_type", "track")),
            "navigate_preset": lambda p: self._navigate_preset(
                g(p, "track_index", 0), g(p, "device_index", 0), g(p, "chain_index"),
                g(p, "direction", "current"), track_type=g(p, "track_type", "track")),
            "get_chain_info": lambda p: self._get_chain_info(
                g(p, "track_index", 0), g(p, "device_index", 0), g(p, "chain_index"),
                track_type=g(p, "track_type", "track")),
            "get_drum_pad_info": lambda p: self._get_drum_pad_info(
                g(p, "track_index", 0), g(p, "device_index", 0), track_type=g(p, "track_type", "track")),
        }

    def _process_command(self, command):
        """Run a command on Live's main thread and return a response dict."""
        command_type = command.get("type", "")
        params = command.get("params", {}) or {}

        handler = self._command_table().get(command_type)
        if handler is None:
            return {"status": "error", "message": "Unknown command: " + command_type}

        response_queue = queue.Queue()
        # Lets a task that has not started yet be skipped once the caller gave up,
        # so a timed-out request does not later run behind the caller's back.
        state = {"cancelled": False, "started": False}

        def main_thread_task():
            if state["cancelled"]:
                self.log_message("Skipping cancelled command: " + command_type)
                return
            state["started"] = True
            try:
                result = handler(params)
                response_queue.put({"status": "success", "result": result if result is not None else {}})
            except Exception as e:
                self.log_message("Error in main thread task {0}: {1}".format(command_type, str(e)))
                self.log_message(traceback.format_exc())
                response_queue.put({"status": "error", "message": str(e)})

        try:
            self.schedule_message(0, main_thread_task)
        except AssertionError:
            # Already on the main thread: run directly.
            main_thread_task()

        timeout = (self.LONG_TASK_TIMEOUT if command_type in self.LONG_COMMANDS
                   else self.DEFAULT_TASK_TIMEOUT)
        try:
            return response_queue.get(timeout=timeout)
        except queue.Empty:
            state["cancelled"] = True
            if state["started"]:
                message = ("Timed out after {0:.0f}s waiting for '{1}'. It is still running "
                           "inside Live and may complete; check the session state before "
                           "retrying.").format(timeout, command_type)
            else:
                message = ("Timed out after {0:.0f}s waiting for Live to run '{1}'. "
                           "It was cancelled and will not run.").format(timeout, command_type)
            return {"status": "error", "message": message}

    # Arrangement helper methods

    def _get_arrangement_clip_info(self, clip):
        """Serialize a Clip object to ArrangementClipInfo dict."""
        try:
            return {
                "name": clip.name,
                "start_time": clip.start_time,
                "end_time": clip.end_time,
                "length": clip.end_time - clip.start_time,
                "is_midi": clip.is_midi_clip,
                "is_audio": clip.is_audio_clip,
                "muted": clip.muted,
                "color": clip.color,
                "looping": clip.looping,
                "loop_start": clip.loop_start,
                "loop_end": clip.loop_end,
            }
        except Exception as e:
            self.log_message("Error getting arrangement clip info: " + str(e))
            return {"name": "unknown", "error": str(e)}

    def _get_transport_info(self):
        """Serialize Song transport state to TransportInfo dict."""
        try:
            return {
                "is_playing": self._song.is_playing,
                "tempo": self._song.tempo,
                "signature_numerator": self._song.signature_numerator,
                "signature_denominator": self._song.signature_denominator,
                "current_time": self._song.current_song_time,
                "song_length": self._song.song_length,
                "loop_enabled": self._song.loop,
                "loop_start": self._song.loop_start,
                "loop_length": self._song.loop_length,
                "arrangement_overdub": self._song.arrangement_overdub,
                "back_to_arranger": self._song.back_to_arranger,
            }
        except Exception as e:
            self.log_message("Error getting transport info: " + str(e))
            raise

    def _resolve_arrangement_clip(self, track_index, clip_index=None, clip_name=None):
        """Resolve an arrangement clip by index or name.

        Returns (track, clip) tuple.
        """
        if track_index < 0 or track_index >= len(self._song.tracks):
            raise IndexError("Track index {0} out of range (0-{1})".format(
                track_index, len(self._song.tracks) - 1))

        track = self._song.tracks[track_index]
        clips = track.arrangement_clips

        if clip_name:
            matches = [(i, c) for i, c in enumerate(clips) if c.name == clip_name]
            if len(matches) == 0:
                raise ValueError("No arrangement clip named '{0}' on track '{1}'".format(
                    clip_name, track.name))
            if len(matches) > 1:
                raise ValueError("Ambiguous: {0} clips named '{1}' on track '{2}'".format(
                    len(matches), clip_name, track.name))
            return track, matches[0][1]

        if clip_index is None:
            raise ValueError("Either clip_index or clip_name must be provided")

        if clip_index < 0 or clip_index >= len(clips):
            raise IndexError("Clip index {0} out of range (0-{1}) on track '{2}'".format(
                clip_index, len(clips) - 1, track.name))

        return track, clips[clip_index]

    def _check_overlap(self, track, position, length):
        """Return list of clip names that overlap with [position, position+length)."""
        overlapped = []
        end = position + length
        for clip in track.arrangement_clips:
            if clip.start_time < end and clip.end_time > position:
                overlapped.append(clip.name or "(unnamed)")
        return overlapped

    # ── Track lookup helpers ─────────────────────────────────────────

    def _track_kind(self, track):
        if getattr(track, "is_foldable", False):
            return "group"
        if getattr(track, "has_midi_input", False):
            return "midi"
        return "audio"

    def _track_index_of(self, track):
        for i, t in enumerate(self._song.tracks):
            if t == track:
                return i
        return None

    def _group_info(self, track):
        """Return (is_grouped, group_index, group_name) for a session track."""
        if not getattr(track, "is_grouped", False):
            return False, None, None
        group = getattr(track, "group_track", None)
        if group is None:
            return True, None, None
        return True, self._track_index_of(group), group.name

    def _param_display(self, param):
        try:
            return str(param)
        except Exception:
            return None

    def _sends_info(self, track):
        sends = []
        returns = list(self._song.return_tracks)
        for i, send in enumerate(track.mixer_device.sends):
            sends.append({
                "index": i,
                "return_track": returns[i].name if i < len(returns) else send.name,
                "value": send.value,
                "display": self._param_display(send),
            })
        return sends

    def _resolve_mixer_track(self, track_index, track_type="track"):
        """Resolve a track for mixer operations.

        track_type: "track" (session track; indices past the last session
        track address return tracks, for backwards compatibility),
        "return", or "master".
        """
        if track_type == "master":
            return self._song.master_track
        if track_type == "return":
            returns = list(self._song.return_tracks)
            if track_index < 0 or track_index >= len(returns):
                raise IndexError("Return track index {0} out of range (0-{1})".format(
                    track_index, len(returns) - 1))
            return returns[track_index]
        if track_type == "track":
            all_tracks = list(self._song.tracks) + list(self._song.return_tracks)
            if track_index < 0 or track_index >= len(all_tracks):
                raise IndexError("Track index {0} out of range (0-{1})".format(
                    track_index, len(all_tracks) - 1))
            return all_tracks[track_index]
        raise ValueError("track_type must be 'track', 'return' or 'master'")

    # Command implementations

    def _get_session_info(self):
        """Session overview: transport, every track, return tracks and master."""
        try:
            tracks = []
            for i, track in enumerate(self._song.tracks):
                kind = self._track_kind(track)
                grouped, group_index, group_name = self._group_info(track)
                tracks.append({
                    "index": i,
                    "name": track.name,
                    "type": kind,
                    "mute": track.mute,
                    "solo": track.solo,
                    "arm": None if kind == "group" or not getattr(track, "can_be_armed", True) else track.arm,
                    "is_grouped": grouped,
                    "group_index": group_index,
                    "group_name": group_name,
                })
            return_tracks = []
            for i, rt in enumerate(self._song.return_tracks):
                return_tracks.append({
                    "index": i,
                    "name": rt.name,
                    "volume": rt.mixer_device.volume.value,
                    "volume_display": self._param_display(rt.mixer_device.volume),
                    "panning": rt.mixer_device.panning.value,
                    "mute": rt.mute,
                    "solo": rt.solo,
                })
            master = self._song.master_track.mixer_device
            return {
                "tempo": self._song.tempo,
                "signature_numerator": self._song.signature_numerator,
                "signature_denominator": self._song.signature_denominator,
                "is_playing": self._song.is_playing,
                "track_count": len(self._song.tracks),
                "return_track_count": len(self._song.return_tracks),
                "scene_count": len(self._song.scenes),
                "tracks": tracks,
                "return_tracks": return_tracks,
                "master_track": {
                    "name": "Master",
                    "volume": master.volume.value,
                    "volume_display": self._param_display(master.volume),
                    "panning": master.panning.value,
                },
            }
        except Exception as e:
            self.log_message("Error getting session info: " + str(e))
            raise

    def _get_track_info(self, track_index, track_type="track"):
        """Get information about a session, return or master track."""
        try:
            track = self._device_track(track_index, track_type)
            kind = self._track_kind(track) if track_type in (None, "", "track") else track_type

            clip_slots = []
            for slot_index, slot in enumerate(getattr(track, "clip_slots", [])):
                clip_info = None
                if slot.has_clip:
                    clip = slot.clip
                    clip_info = {
                        "name": clip.name,
                        "length": clip.length,
                        "is_playing": clip.is_playing,
                        "is_recording": clip.is_recording
                    }
                clip_slots.append({
                    "index": slot_index,
                    "has_clip": slot.has_clip,
                    "clip": clip_info
                })

            devices = []
            for device_index, device in enumerate(track.devices):
                devices.append({
                    "index": device_index,
                    "name": device.name,
                    "class_name": device.class_name,
                    "type": self._get_device_type(device)
                })

            if track_type in (None, "", "track"):
                grouped, group_index, group_name = self._group_info(track)
            else:
                grouped, group_index, group_name = False, None, None
            is_group = kind == "group"
            return {
                "index": track_index,
                "name": track.name,
                "type": kind,
                "is_audio_track": getattr(track, "has_audio_input", False),
                "is_midi_track": getattr(track, "has_midi_input", False),
                "is_group_track": is_group,
                "is_grouped": grouped,
                "group_index": group_index,
                "group_name": group_name,
                "fold_state": bool(getattr(track, "fold_state", False)) if is_group else None,
                "color": getattr(track, "color", None),
                "mute": getattr(track, "mute", None),
                "solo": getattr(track, "solo", None),
                "arm": (None if is_group or kind in ("return", "master")
                        or not getattr(track, "can_be_armed", True) else track.arm),
                "volume": track.mixer_device.volume.value,
                "volume_display": self._param_display(track.mixer_device.volume),
                "panning": track.mixer_device.panning.value,
                "sends": self._sends_info(track),
                "clip_slots": clip_slots,
                "devices": devices
            }
        except Exception as e:
            self.log_message("Error getting track info: " + str(e))
            raise

    def _create_midi_track(self, index):
        """Create a new MIDI track at the specified index"""
        try:
            # Create the track
            self._song.create_midi_track(index)
            
            # Get the new track
            new_track_index = len(self._song.tracks) - 1 if index == -1 else index
            new_track = self._song.tracks[new_track_index]
            
            result = {
                "index": new_track_index,
                "name": new_track.name
            }
            return result
        except Exception as e:
            self.log_message("Error creating MIDI track: " + str(e))
            raise

    def _create_audio_track(self, index):
        """Create a new audio track at the specified index"""
        try:
            self._song.create_audio_track(index)

            new_track_index = len(self._song.tracks) - 1 if index == -1 else index
            new_track = self._song.tracks[new_track_index]

            return {
                "index": new_track_index,
                "name": new_track.name
            }
        except Exception as e:
            self.log_message("Error creating audio track: " + str(e))
            raise
    
    
    def _set_track_name(self, track_index, name):
        """Set the name of a track"""
        try:
            if track_index < 0 or track_index >= len(self._song.tracks):
                raise IndexError("Track index out of range")
            
            # Set the name
            track = self._song.tracks[track_index]
            track.name = name
            
            result = {
                "name": track.name
            }
            return result
        except Exception as e:
            self.log_message("Error setting track name: " + str(e))
            raise

    def _get_track_volume(self, track_index, track_type="track"):
        """Get current volume and panning for a track's mixer fader."""
        try:
            track = self._resolve_mixer_track(track_index, track_type)
            vol_param = track.mixer_device.volume
            pan_param = track.mixer_device.panning
            return {
                "track_name": track.name,
                "volume": vol_param.value,
                "volume_display": self._param_display(vol_param),
                "volume_min": vol_param.min,
                "volume_max": vol_param.max,
                "panning": pan_param.value,
                "panning_display": self._param_display(pan_param),
                "panning_min": pan_param.min,
                "panning_max": pan_param.max,
            }
        except Exception as e:
            self.log_message("Error getting track volume: " + str(e))
            raise

    def _set_track_volume(self, track_index, volume, track_type="track"):
        """Set the mixer fader volume (normalized 0.0-1.0, 0.85 = 0 dB)."""
        try:
            track = self._resolve_mixer_track(track_index, track_type)
            vol_param = track.mixer_device.volume
            vol_param.value = max(vol_param.min, min(vol_param.max, float(volume)))
            return {
                "track_name": track.name,
                "volume": vol_param.value,
                "volume_display": self._param_display(vol_param),
            }
        except Exception as e:
            self.log_message("Error setting track volume: " + str(e))
            raise

    def _set_track_panning(self, track_index, panning, track_type="track"):
        """Set the mixer panning (-1.0 left .. +1.0 right)."""
        try:
            track = self._resolve_mixer_track(track_index, track_type)
            pan_param = track.mixer_device.panning
            pan_param.value = max(pan_param.min, min(pan_param.max, float(panning)))
            return {
                "track_name": track.name,
                "panning": pan_param.value,
                "panning_display": self._param_display(pan_param),
            }
        except Exception as e:
            self.log_message("Error setting track panning: " + str(e))
            raise

    def _set_track_flag(self, track_index, flag, value, track_type="track", exclusive=False):
        """Set mute, solo or arm on a track."""
        if flag not in ("mute", "solo", "arm"):
            raise ValueError("Unknown track flag: " + str(flag))
        if track_type == "master":
            raise ValueError("The master track has no {0} switch".format(flag))
        track = self._resolve_mixer_track(track_index, track_type)
        if flag == "arm":
            if not getattr(track, "can_be_armed", False):
                raise ValueError("Track '{0}' cannot be armed (group and return tracks "
                                 "have no arm button)".format(track.name))
        if flag == "solo" and exclusive and value:
            for other in list(self._song.tracks) + list(self._song.return_tracks):
                if other != track and other.solo:
                    other.solo = False
        setattr(track, flag, bool(value))
        return {"track_name": track.name, flag: getattr(track, flag)}

    def _set_track_send(self, track_index, send_index, value, track_type="track"):
        """Set a track's send level to a return track (normalized 0.0-1.0)."""
        if track_type == "master":
            raise ValueError("The master track has no sends")
        track = self._resolve_mixer_track(track_index, track_type)
        sends = list(track.mixer_device.sends)
        if not sends:
            raise ValueError("Track '{0}' has no sends (add a return track first)".format(track.name))
        if send_index < 0 or send_index >= len(sends):
            raise IndexError("Send index {0} out of range (0-{1})".format(send_index, len(sends) - 1))
        send = sends[send_index]
        send.value = max(send.min, min(send.max, float(value)))
        returns = list(self._song.return_tracks)
        return {
            "track_name": track.name,
            "return_track": returns[send_index].name if send_index < len(returns) else send.name,
            "value": send.value,
            "display": self._param_display(send),
        }

    def _create_return_track(self):
        """Append a new return track."""
        self._song.create_return_track()
        index = len(self._song.return_tracks) - 1
        return {"index": index, "name": self._song.return_tracks[index].name}

    def _create_clip(self, track_index, clip_index, length):
        """Create a new MIDI clip in the specified track and clip slot"""
        try:
            if track_index < 0 or track_index >= len(self._song.tracks):
                raise IndexError("Track index out of range")
            
            track = self._song.tracks[track_index]
            
            if clip_index < 0 or clip_index >= len(track.clip_slots):
                raise IndexError("Clip index out of range")
            
            clip_slot = track.clip_slots[clip_index]
            
            # Check if the clip slot already has a clip
            if clip_slot.has_clip:
                raise Exception("Clip slot already has a clip")
            
            # Create the clip
            clip_slot.create_clip(length)
            
            result = {
                "name": clip_slot.clip.name,
                "length": clip_slot.clip.length
            }
            return result
        except Exception as e:
            self.log_message("Error creating clip: " + str(e))
            raise
    
    # ── MIDI note editing ────────────────────────────────────────────
    #
    # Live 11+ exposes add_new_notes / get_notes_extended /
    # remove_notes_extended (with probability, velocity deviation and
    # release velocity). Older versions only have set_notes / get_notes /
    # remove_notes, so each helper falls back to those.

    # Wide enough to cover any clip; Live clips are far shorter than this.
    _NOTE_TIME_SPAN = 1000000.0
    _OPTIONAL_NOTE_FIELDS = ("probability", "velocity_deviation", "release_velocity")

    def _resolve_any_clip(self, track_index, clip_index, arrangement=False, clip_name=None):
        """Return (track, clip) for a session slot or an arrangement clip."""
        if arrangement:
            return self._resolve_arrangement_clip(track_index, clip_index, clip_name)

        if track_index < 0 or track_index >= len(self._song.tracks):
            raise IndexError("Track index {0} out of range (0-{1})".format(
                track_index, len(self._song.tracks) - 1))
        track = self._song.tracks[track_index]
        slots = list(track.clip_slots)

        if clip_name:
            matches = [s.clip for s in slots if s.has_clip and s.clip.name == clip_name]
            if not matches:
                raise ValueError("No session clip named '{0}' on track '{1}'".format(
                    clip_name, track.name))
            if len(matches) > 1:
                raise ValueError("Ambiguous: {0} session clips named '{1}' on track '{2}'".format(
                    len(matches), clip_name, track.name))
            return track, matches[0]

        if clip_index is None or clip_index < 0 or clip_index >= len(slots):
            raise IndexError("Clip slot index {0} out of range (0-{1})".format(
                clip_index, len(slots) - 1))
        slot = slots[clip_index]
        if not slot.has_clip:
            raise ValueError("No clip in slot {0} on track '{1}'".format(clip_index, track.name))
        return track, slot.clip

    @staticmethod
    def _clean_note(note):
        """Validate and normalize one note dict from the server."""
        pitch = int(note.get("pitch", 60))
        if pitch < 0 or pitch > 127:
            raise ValueError("Note pitch {0} out of range (0-127)".format(pitch))
        duration = float(note.get("duration", 0.25))
        if duration <= 0:
            raise ValueError("Note duration must be > 0, got {0}".format(duration))
        velocity = max(1.0, min(127.0, float(note.get("velocity", 100))))
        cleaned = {
            "pitch": pitch,
            "start_time": float(note.get("start_time", 0.0)),
            "duration": duration,
            "velocity": velocity,
            "mute": bool(note.get("mute", False)),
        }
        for key in AbletonMCP._OPTIONAL_NOTE_FIELDS:
            if note.get(key) is not None:
                cleaned[key] = float(note[key])
        return cleaned

    def _write_notes(self, clip, notes):
        """Add notes to a MIDI clip using the newest API available."""
        if not clip.is_midi_clip:
            raise ValueError("Clip '{0}' is not a MIDI clip".format(clip.name))
        cleaned = [self._clean_note(n) for n in notes]
        spec_cls = getattr(getattr(Live, "Clip", None), "MidiNoteSpecification", None) if Live else None
        if spec_cls is not None and hasattr(clip, "add_new_notes"):
            clip.add_new_notes(tuple(spec_cls(**n) for n in cleaned))
        else:
            clip.set_notes(tuple(
                (n["pitch"], n["start_time"], n["duration"], n["velocity"], n["mute"])
                for n in cleaned))
        return len(cleaned)

    def _read_notes(self, clip):
        """Return the clip's notes as dicts sorted by start time then pitch."""
        if not clip.is_midi_clip:
            raise ValueError("Clip '{0}' is not a MIDI clip".format(clip.name))
        notes = []
        if hasattr(clip, "get_notes_extended"):
            for n in clip.get_notes_extended(0, 128, 0.0, self._NOTE_TIME_SPAN):
                entry = {
                    "pitch": n.pitch,
                    "start_time": n.start_time,
                    "duration": n.duration,
                    "velocity": n.velocity,
                    "mute": bool(n.mute),
                }
                for key in self._OPTIONAL_NOTE_FIELDS:
                    if hasattr(n, key):
                        entry[key] = getattr(n, key)
                notes.append(entry)
        else:
            for pitch, start, duration, velocity, mute in clip.get_notes(
                    0.0, 0, self._NOTE_TIME_SPAN, 128):
                notes.append({"pitch": pitch, "start_time": start, "duration": duration,
                              "velocity": velocity, "mute": bool(mute)})
        notes.sort(key=lambda n: (n["start_time"], n["pitch"]))
        return notes

    def _remove_notes(self, clip, pitch_from=0, pitch_to=127, time_from=0.0, time_to=None):
        """Remove notes whose pitch and start time fall in the given ranges."""
        if not clip.is_midi_clip:
            raise ValueError("Clip '{0}' is not a MIDI clip".format(clip.name))
        pitch_from = max(0, int(pitch_from))
        pitch_to = min(127, int(pitch_to))
        pitch_span = pitch_to - pitch_from + 1
        time_from = float(time_from or 0.0)
        time_span = (self._NOTE_TIME_SPAN if time_to is None
                     else float(time_to) - time_from)
        if pitch_span <= 0 or time_span <= 0:
            raise ValueError("Empty note range")
        before = len(self._read_notes(clip))
        if hasattr(clip, "remove_notes_extended"):
            clip.remove_notes_extended(pitch_from, pitch_span, time_from, time_span)
        else:
            clip.remove_notes(time_from, pitch_from, time_span, pitch_span)
        return before - len(self._read_notes(clip))

    def _rewrite_notes(self, clip, transform):
        """Replace every note with transform(note_dict); returns the new notes."""
        notes = self._read_notes(clip)
        new_notes = [transform(dict(n)) for n in notes]
        self._remove_notes(clip)
        self._write_notes(clip, new_notes)
        return new_notes

    def _get_clip_notes(self, track_index, clip_index, arrangement=False, clip_name=None):
        track, clip = self._resolve_any_clip(track_index, clip_index, arrangement, clip_name)
        return {
            "track_name": track.name,
            "clip_name": clip.name,
            "length": clip.length,
            "loop_start": clip.loop_start,
            "loop_end": clip.loop_end,
            "notes": self._read_notes(clip),
        }

    def _add_notes(self, track_index, clip_index, notes, arrangement=False, clip_name=None,
                   replace=False):
        track, clip = self._resolve_any_clip(track_index, clip_index, arrangement, clip_name)
        # Validate everything before touching the clip so a bad note can't
        # leave a replaced clip half-written.
        for n in notes:
            self._clean_note(n)
        removed = self._remove_notes(clip) if replace else 0
        added = self._write_notes(clip, notes)
        return {"note_count": added, "removed": removed, "clip_name": clip.name}

    def _remove_clip_notes(self, track_index, clip_index, arrangement=False, clip_name=None,
                           pitch_from=0, pitch_to=127, time_from=0.0, time_to=None):
        track, clip = self._resolve_any_clip(track_index, clip_index, arrangement, clip_name)
        removed = self._remove_notes(clip, pitch_from, pitch_to, time_from, time_to)
        return {"removed": removed, "clip_name": clip.name}

    def _transpose_clip_notes(self, track_index, clip_index, semitones, arrangement=False,
                              clip_name=None):
        track, clip = self._resolve_any_clip(track_index, clip_index, arrangement, clip_name)
        semitones = int(semitones)
        for n in self._read_notes(clip):
            if not 0 <= n["pitch"] + semitones <= 127:
                raise ValueError("Transposing by {0} would push pitch {1} out of range".format(
                    semitones, n["pitch"]))

        def shift(n):
            n["pitch"] += semitones
            return n
        notes = self._rewrite_notes(clip, shift)
        return {"note_count": len(notes), "semitones": semitones, "clip_name": clip.name}

    def _quantize_clip_notes(self, track_index, clip_index, grid, strength=1.0,
                             quantize_ends=False, arrangement=False, clip_name=None):
        track, clip = self._resolve_any_clip(track_index, clip_index, arrangement, clip_name)
        grid = float(grid)
        if grid <= 0:
            raise ValueError("Grid must be > 0 beats")
        strength = max(0.0, min(1.0, float(strength)))

        def snap(t):
            return t + (round(t / grid) * grid - t) * strength

        def quantize(n):
            start = snap(n["start_time"])
            if quantize_ends:
                end = snap(n["start_time"] + n["duration"])
                n["duration"] = max(end - start, grid * 0.25)
            n["start_time"] = start
            return n
        notes = self._rewrite_notes(clip, quantize)
        return {"note_count": len(notes), "grid": grid, "strength": strength,
                "clip_name": clip.name}

    def _set_clip_name(self, track_index, clip_index, name):
        """Set the name of a clip"""
        try:
            if track_index < 0 or track_index >= len(self._song.tracks):
                raise IndexError("Track index out of range")
            
            track = self._song.tracks[track_index]
            
            if clip_index < 0 or clip_index >= len(track.clip_slots):
                raise IndexError("Clip index out of range")
            
            clip_slot = track.clip_slots[clip_index]
            
            if not clip_slot.has_clip:
                raise Exception("No clip in slot")
            
            clip = clip_slot.clip
            clip.name = name
            
            result = {
                "name": clip.name
            }
            return result
        except Exception as e:
            self.log_message("Error setting clip name: " + str(e))
            raise
    
    def _set_tempo(self, tempo):
        """Set the tempo of the session"""
        try:
            self._song.tempo = tempo
            
            result = {
                "tempo": self._song.tempo
            }
            return result
        except Exception as e:
            self.log_message("Error setting tempo: " + str(e))
            raise
    
    def _fire_clip(self, track_index, clip_index):
        """Fire a clip"""
        try:
            if track_index < 0 or track_index >= len(self._song.tracks):
                raise IndexError("Track index out of range")
            
            track = self._song.tracks[track_index]
            
            if clip_index < 0 or clip_index >= len(track.clip_slots):
                raise IndexError("Clip index out of range")
            
            clip_slot = track.clip_slots[clip_index]
            
            if not clip_slot.has_clip:
                raise Exception("No clip in slot")
            
            clip_slot.fire()
            
            result = {
                "fired": True
            }
            return result
        except Exception as e:
            self.log_message("Error firing clip: " + str(e))
            raise
    
    def _stop_clip(self, track_index, clip_index):
        """Stop a clip"""
        try:
            if track_index < 0 or track_index >= len(self._song.tracks):
                raise IndexError("Track index out of range")
            
            track = self._song.tracks[track_index]
            
            if clip_index < 0 or clip_index >= len(track.clip_slots):
                raise IndexError("Clip index out of range")
            
            clip_slot = track.clip_slots[clip_index]
            
            clip_slot.stop()
            
            result = {
                "stopped": True
            }
            return result
        except Exception as e:
            self.log_message("Error stopping clip: " + str(e))
            raise
    
    
    def _start_playback(self):
        """Start playing the session"""
        try:
            self._song.start_playing()
            
            result = {
                "playing": self._song.is_playing
            }
            return result
        except Exception as e:
            self.log_message("Error starting playback: " + str(e))
            raise
    
    def _stop_playback(self):
        """Stop playing the session"""
        try:
            self._song.stop_playing()
            
            result = {
                "playing": self._song.is_playing
            }
            return result
        except Exception as e:
            self.log_message("Error stopping playback: " + str(e))
            raise

    # ── Scenes ───────────────────────────────────────────────────────

    def _scene(self, scene_index):
        scenes = list(self._song.scenes)
        if scene_index < 0 or scene_index >= len(scenes):
            raise IndexError("Scene index {0} out of range (0-{1})".format(
                scene_index, len(scenes) - 1))
        return scenes[scene_index]

    def _get_scenes(self):
        scenes = []
        for i, scene in enumerate(self._song.scenes):
            filled = sum(1 for slot in scene.clip_slots if slot.has_clip)
            scenes.append({
                "index": i,
                "name": scene.name,
                "clip_count": filled,
                "is_triggered": bool(getattr(scene, "is_triggered", False)),
            })
        return {"scenes": scenes}

    def _create_scene(self, index=-1):
        self._song.create_scene(index)
        new_index = len(self._song.scenes) - 1 if index == -1 else index
        return {"index": new_index, "name": self._song.scenes[new_index].name}

    def _duplicate_scene(self, scene_index):
        self._scene(scene_index)
        self._song.duplicate_scene(scene_index)
        new_index = scene_index + 1
        return {"index": new_index, "name": self._song.scenes[new_index].name}

    def _delete_scene(self, scene_index):
        scene = self._scene(scene_index)
        if len(self._song.scenes) <= 1:
            raise ValueError("Cannot delete the last scene")
        name = scene.name
        self._song.delete_scene(scene_index)
        return {"deleted_scene": name, "remaining_scenes": len(self._song.scenes)}

    def _set_scene_name(self, scene_index, name):
        scene = self._scene(scene_index)
        scene.name = name
        return {"index": scene_index, "name": scene.name}

    def _fire_scene(self, scene_index):
        scene = self._scene(scene_index)
        scene.fire()
        return {"index": scene_index, "name": scene.name, "fired": True}

    def _stop_all_clips(self):
        self._song.stop_all_clips()
        return {"stopped": True}

    # ── Session clip slots ───────────────────────────────────────────

    def _clip_slot(self, track_index, clip_index):
        if track_index < 0 or track_index >= len(self._song.tracks):
            raise IndexError("Track index {0} out of range (0-{1})".format(
                track_index, len(self._song.tracks) - 1))
        track = self._song.tracks[track_index]
        slots = list(track.clip_slots)
        if clip_index < 0 or clip_index >= len(slots):
            raise IndexError("Clip slot index {0} out of range (0-{1})".format(
                clip_index, len(slots) - 1))
        return track, slots[clip_index]

    def _delete_clip(self, track_index, clip_index):
        track, slot = self._clip_slot(track_index, clip_index)
        if not slot.has_clip:
            raise ValueError("No clip in slot {0} on track '{1}'".format(clip_index, track.name))
        name = slot.clip.name
        slot.delete_clip()
        return {"deleted_clip": name}

    def _duplicate_clip_to_slot(self, track_index, clip_index, target_track_index, target_clip_index):
        track, slot = self._clip_slot(track_index, clip_index)
        if not slot.has_clip:
            raise ValueError("No clip in slot {0} on track '{1}'".format(clip_index, track.name))
        target_track, target = self._clip_slot(target_track_index, target_clip_index)
        if target.has_clip:
            raise ValueError("Target slot {0} on track '{1}' already has a clip".format(
                target_clip_index, target_track.name))
        slot.duplicate_clip_to(target)
        return {"source": slot.clip.name, "target_track": target_track.name,
                "target_slot": target_clip_index}

    # ── Clip properties (session or arrangement) ─────────────────────

    CLIP_PROPERTIES = ("name", "muted", "color", "looping", "loop_start", "loop_end",
                       "start_marker", "end_marker", "gain", "pitch_coarse", "pitch_fine",
                       "warping", "warp_mode")
    AUDIO_ONLY_PROPERTIES = ("gain", "pitch_coarse", "pitch_fine", "warping", "warp_mode")

    def _set_clip_properties(self, track_index, clip_index, properties, arrangement=False,
                             clip_name=None):
        """Set several clip properties at once, in an order Live accepts.

        loop/marker ranges must keep start < end at every step, so when a
        new start lies beyond the current end, the end is moved first.
        """
        unknown = [k for k in properties if k not in self.CLIP_PROPERTIES]
        if unknown:
            raise ValueError("Property {0} not allowed. Allowed: {1}".format(
                ", ".join(unknown), ", ".join(self.CLIP_PROPERTIES)))
        track, clip = self._resolve_any_clip(track_index, clip_index, arrangement, clip_name)
        if not getattr(clip, "is_audio_clip", False):
            audio_only = [k for k in properties if k in self.AUDIO_ONLY_PROPERTIES]
            if audio_only:
                raise ValueError("{0} only apply to audio clips; '{1}' is a MIDI clip".format(
                    ", ".join(audio_only), clip.name))

        props = dict(properties)
        ordered = []
        for start_key, end_key in (("loop_start", "loop_end"), ("start_marker", "end_marker")):
            if start_key in props and end_key in props:
                start, end = props.pop(start_key), props.pop(end_key)
                if start >= getattr(clip, end_key):
                    ordered += [(end_key, end), (start_key, start)]
                else:
                    ordered += [(start_key, start), (end_key, end)]
        # looping first so loop points apply to the right mode
        if "looping" in props:
            ordered.insert(0, ("looping", props.pop("looping")))
        ordered += list(props.items())

        for key, value in ordered:
            setattr(clip, key, value)
        return {
            "clip_name": clip.name,
            "properties": {key: getattr(clip, key) for key, _ in ordered},
        }

    # Browser helper methods

    def _normalize_browser_category_name(self, category_name):
        """Normalize browser category names for robust matching."""
        try:
            normalized = (category_name or "").strip().lower()
            normalized = normalized.replace("-", "_").replace(" ", "_")
            while "__" in normalized:
                normalized = normalized.replace("__", "_")
            normalized = normalized.strip("_")

            # Canonical category aliases
            alias_map = {
                "instrument": "instruments",
                "sound": "sounds",
                "drum": "drums",
                "audioeffects": "audio_effects",
                "audio_fx": "audio_effects",
                "audiofx": "audio_effects",
                "midieffects": "midi_effects",
                "midi_fx": "midi_effects",
                "midifx": "midi_effects",
                "plugin": "plugins",
                "vst": "plugins",
                "vst2": "plugins",
                "vst3": "plugins",
                "au": "plugins",
            }

            if normalized in alias_map:
                return alias_map[normalized]

            compact = normalized.replace("_", "")
            if compact in alias_map:
                return alias_map[compact]

            return normalized
        except Exception:
            return (category_name or "").strip().lower()

    def _split_browser_path(self, path):
        """Split a browser path into normalized path parts."""
        if not path:
            return []
        return [part.strip() for part in path.split("/") if part and part.strip()]

    def _resolve_browser_root_category(self, browser, root_category, browser_attrs=None):
        """Resolve a root browser category to the corresponding browser item."""
        normalized_root = self._normalize_browser_category_name(root_category)

        standard_roots = {
            "instruments": "instruments",
            "sounds": "sounds",
            "drums": "drums",
            "audio_effects": "audio_effects",
            "midi_effects": "midi_effects",
            "plugins": "plugins",
        }

        attr_name = standard_roots.get(normalized_root)
        if attr_name and hasattr(browser, attr_name):
            return getattr(browser, attr_name), attr_name

        attrs = browser_attrs if browser_attrs is not None else [a for a in dir(browser) if not a.startswith('_')]
        for attr in attrs:
            if self._normalize_browser_category_name(attr) == normalized_root:
                try:
                    return getattr(browser, attr), attr
                except Exception as e:
                    self.log_message("Error accessing browser attribute {0}: {1}".format(attr, str(e)))

        return None, normalized_root
    
    def _load_browser_item(self, track_index, item_uri, track_type="track"):
        """Load a browser item onto a track by its URI"""
        try:
            track = self._device_track(track_index, track_type)
            
            # Access the application's browser instance instead of creating a new one
            app = self.application()
            
            # Find the browser item by URI
            item = self._find_browser_item_by_uri(app.browser, item_uri)
            
            if not item:
                raise ValueError("Browser item with URI '{0}' not found".format(item_uri))
            
            # Select the track
            self._song.view.selected_track = track
            
            # Load the item
            app.browser.load_item(item)
            
            result = {
                "loaded": True,
                "item_name": item.name,
                "track_name": track.name,
                "uri": item_uri
            }
            return result
        except Exception as e:
            self.log_message("Error loading browser item: {0}".format(str(e)))
            self.log_message(traceback.format_exc())
            raise
    
    def _find_browser_item_by_uri(self, browser_or_item, uri, max_depth=10, current_depth=0):
        """Find a browser item by its URI"""
        try:
            # Check if this is the item we're looking for
            if hasattr(browser_or_item, 'uri') and browser_or_item.uri == uri:
                return browser_or_item
            
            # Stop recursion if we've reached max depth
            if current_depth >= max_depth:
                return None
            
            # Check if this is a browser with root categories
            if hasattr(browser_or_item, 'instruments'):
                # Check all main categories
                categories = [
                    browser_or_item.instruments,
                    browser_or_item.sounds,
                    browser_or_item.drums,
                    browser_or_item.audio_effects,
                    browser_or_item.midi_effects,
                    browser_or_item.plugins,
                ]
                
                for category in categories:
                    item = self._find_browser_item_by_uri(category, uri, max_depth, current_depth + 1)
                    if item:
                        return item
                
                return None
            
            # Check if this item has children
            if hasattr(browser_or_item, 'children') and browser_or_item.children:
                for child in browser_or_item.children:
                    item = self._find_browser_item_by_uri(child, uri, max_depth, current_depth + 1)
                    if item:
                        return item
            
            return None
        except Exception as e:
            self.log_message("Error finding browser item by URI: {0}".format(str(e)))
            return None
    
    # Arrangement command handlers

    def _get_arrangement_info(self, track_index):
        """Get arrangement clips and transport for one or all tracks."""
        try:
            transport = self._get_transport_info()
            tracks_data = []

            if track_index == -1:
                tracks = list(enumerate(self._song.tracks))
            else:
                if track_index < 0 or track_index >= len(self._song.tracks):
                    raise IndexError("Track index out of range")
                tracks = [(track_index, self._song.tracks[track_index])]

            for idx, track in tracks:
                is_group = bool(getattr(track, "is_foldable", False))
                if is_group and track_index == -1:
                    continue

                clips = []
                if not is_group:
                    for ci, clip in enumerate(track.arrangement_clips):
                        clip_info = self._get_arrangement_clip_info(clip)
                        clip_info["index"] = ci
                        clips.append(clip_info)

                tracks_data.append({
                    "index": idx,
                    "name": track.name,
                    "is_midi": track.has_midi_input,
                    "is_audio": track.has_audio_input,
                    "is_group_track": is_group,
                    "arrangement_clips": clips,
                    "clip_count": len(clips),
                })

            return {"transport": transport, "tracks": tracks_data}
        except Exception as e:
            self.log_message("Error getting arrangement info: " + str(e))
            raise

    def _get_cue_points(self):
        """Get all cue points."""
        try:
            cue_points = []
            for cp in self._song.cue_points:
                cue_points.append({"name": cp.name, "time": cp.time})
            return {"cue_points": cue_points}
        except Exception as e:
            self.log_message("Error getting cue points: " + str(e))
            raise

    def _set_song_time(self, time):
        """Set playback position."""
        try:
            self._song.current_song_time = time
            return {"time": self._song.current_song_time}
        except Exception as e:
            self.log_message("Error setting song time: " + str(e))
            raise

    def _set_arrangement_loop(self, enabled, start=None, length=None):
        """Set arrangement loop state and region."""
        try:
            self._song.loop = enabled
            if start is not None:
                self._song.loop_start = start
            if length is not None:
                self._song.loop_length = length
            return {
                "enabled": self._song.loop,
                "start": self._song.loop_start,
                "length": self._song.loop_length,
            }
        except Exception as e:
            self.log_message("Error setting arrangement loop: " + str(e))
            raise

    def _jump_to_cue(self, direction=None, name=None):
        """Jump to cue point by direction or name."""
        try:
            if direction == "next":
                self._song.jump_to_next_cue()
                return {"direction": "next", "time": self._song.current_song_time}
            elif direction == "prev":
                self._song.jump_to_prev_cue()
                return {"direction": "prev", "time": self._song.current_song_time}
            elif name:
                for cp in self._song.cue_points:
                    if cp.name == name:
                        cp.jump()
                        return {"name": cp.name, "time": cp.time}
                raise ValueError("Cue point '{0}' not found".format(name))
            else:
                raise ValueError("Provide direction ('next'/'prev') or name")
        except Exception as e:
            self.log_message("Error jumping to cue: " + str(e))
            raise

    def _create_cue_point(self, time, name=""):
        """Create a cue point at the given time."""
        try:
            for cp in tuple(self._song.cue_points):
                if abs(cp.time - time) < 0.01:
                    raise ValueError("Cue point already exists at this position: " + cp.name)
            self._song.current_song_time = time
            self._song.set_or_delete_cue()
            if name:
                for cp in tuple(self._song.cue_points):
                    if abs(cp.time - time) < 0.01:
                        cp.name = name
                        break
            return {"time": time, "name": name}
        except Exception as e:
            self.log_message("Error creating cue point: " + str(e))
            raise

    def _delete_cue_point(self, time):
        """Delete a cue point at the given time."""
        try:
            found = False
            for cp in self._song.cue_points:
                if abs(cp.time - time) < 0.01:
                    found = True
                    break
            if not found:
                raise ValueError("No cue point at this position")
            self._song.current_song_time = time
            self._song.set_or_delete_cue()
            return {"deleted": True}
        except Exception as e:
            self.log_message("Error deleting cue point: " + str(e))
            raise

    def _validate_not_return_or_master(self, track_index):
        """Raise if track is a return or master track."""
        track = self._song.tracks[track_index]
        # Return tracks and master track are separate in the Live API,
        # but if accessed via tracks list they are regular tracks.
        # Check by comparing against return_tracks and master_track.
        for rt in self._song.return_tracks:
            if track == rt:
                raise ValueError("Cannot create arrangement clips on return track '{0}'".format(track.name))
        if track == self._song.master_track:
            raise ValueError("Cannot create arrangement clips on master track")

    def _create_arrangement_clip(self, track_index, position, length):
        """Create MIDI clip in arrangement."""
        try:
            if track_index < 0 or track_index >= len(self._song.tracks):
                raise IndexError("Track index out of range")
            self._validate_not_return_or_master(track_index)
            track = self._song.tracks[track_index]
            overlapped = self._check_overlap(track, position, length)
            track.create_midi_clip(position, length)
            # Find the newly created clip
            result = {"start_time": position, "length": length, "is_midi": True}
            for clip in track.arrangement_clips:
                if abs(clip.start_time - position) < 0.01:
                    result = self._get_arrangement_clip_info(clip)
                    break
            result["overlapped_clips"] = overlapped
            return result
        except Exception as e:
            self.log_message("Error creating arrangement clip: " + str(e))
            raise

    def _create_arrangement_audio_clip(self, track_index, position, file_path):
        """Create audio clip in arrangement from file."""
        try:
            if track_index < 0 or track_index >= len(self._song.tracks):
                raise IndexError("Track index out of range")
            self._validate_not_return_or_master(track_index)
            track = self._song.tracks[track_index]
            track.create_audio_clip(file_path, position)
            # Find the newly created clip
            result = {"start_time": position, "file_path": file_path, "is_audio": True}
            for clip in track.arrangement_clips:
                if abs(clip.start_time - position) < 0.01:
                    result = self._get_arrangement_clip_info(clip)
                    break
            return result
        except Exception as e:
            self.log_message("Error creating arrangement audio clip: " + str(e))
            raise

    def _duplicate_to_arrangement(self, track_index, clip_index, destination_time):
        """Duplicate a session clip to arrangement."""
        try:
            if track_index < 0 or track_index >= len(self._song.tracks):
                raise IndexError("Track index out of range")
            track = self._song.tracks[track_index]
            if clip_index < 0 or clip_index >= len(track.clip_slots):
                raise IndexError("Clip slot index out of range")
            slot = track.clip_slots[clip_index]
            if not slot.has_clip:
                raise ValueError("No clip in slot {0}".format(clip_index))
            clip = slot.clip
            track.duplicate_clip_to_arrangement(clip, destination_time)
            # Find the duplicated clip
            result = {"start_time": destination_time, "duplicated": True}
            for arr_clip in track.arrangement_clips:
                if abs(arr_clip.start_time - destination_time) < 0.01:
                    result = self._get_arrangement_clip_info(arr_clip)
                    result["duplicated"] = True
                    break
            return result
        except Exception as e:
            self.log_message("Error duplicating to arrangement: " + str(e))
            raise

    def _delete_arrangement_clip(self, track_index, clip_index=None, clip_name=None):
        """Delete an arrangement clip."""
        try:
            track, clip = self._resolve_arrangement_clip(track_index, clip_index, clip_name)
            track.delete_clip(clip)
            return {"deleted": True}
        except Exception as e:
            self.log_message("Error deleting arrangement clip: " + str(e))
            raise

    def _set_view(self, view_name):
        """Switch Ableton view."""
        try:
            app = self.application()
            app.view.show_view(view_name)
            return {"visible": app.view.is_view_visible(view_name)}
        except Exception as e:
            self.log_message("Error setting view: " + str(e))
            raise

    def _control_arrangement_view(self, action, track_index=0):
        """Dispatch arrangement view control actions."""
        try:
            app = self.application()
            if action == "zoom_in":
                app.view.zoom_view(1, "Arranger", False)
            elif action == "zoom_out":
                app.view.zoom_view(0, "Arranger", False)
            elif action == "scroll_right":
                app.view.scroll_view(1, "Arranger", False)
            elif action == "scroll_left":
                app.view.scroll_view(0, "Arranger", False)
            elif action == "follow_on":
                self._song.view.follow_song = True
            elif action == "follow_off":
                self._song.view.follow_song = False
            elif action == "collapse_track":
                if track_index < 0 or track_index >= len(self._song.tracks):
                    raise IndexError("Track index out of range")
                self._song.tracks[track_index].view.is_collapsed = True
            elif action == "expand_track":
                if track_index < 0 or track_index >= len(self._song.tracks):
                    raise IndexError("Track index out of range")
                self._song.tracks[track_index].view.is_collapsed = False
            else:
                raise ValueError("Unknown action: " + action)
            return {"action": action, "done": True}
        except Exception as e:
            self.log_message("Error controlling arrangement view: " + str(e))
            raise

    def _manage_clip_automation(self, track_index, clip_index, action, parameter_name="",
                                clip_name=None):
        """Create or clear automation envelopes."""
        try:
            track, clip = self._resolve_arrangement_clip(track_index, clip_index, clip_name)
            if action == "clear_all":
                clip.clear_all_envelopes()
                return {"action": "clear_all", "done": True}
            # Find the parameter
            param = None
            # Check mixer device first
            mixer = track.mixer_device
            for p in [mixer.volume, mixer.panning]:
                if p.name.lower() == parameter_name.lower():
                    param = p
                    break
            # Check sends
            if param is None:
                for send in mixer.sends:
                    if send.name.lower() == parameter_name.lower():
                        param = send
                        break
            # Check track devices
            if param is None:
                for device in track.devices:
                    for p in device.parameters:
                        if p.name.lower() == parameter_name.lower():
                            param = p
                            break
                    if param:
                        break
            if param is None:
                raise ValueError("Parameter '{0}' not found on track '{1}'".format(
                    parameter_name, track.name))
            if action == "create":
                clip.create_automation_envelope(param)
                return {"action": "create", "parameter": param.name, "done": True}
            elif action == "clear":
                clip.clear_envelope(param)
                return {"action": "clear", "parameter": param.name, "done": True}
            else:
                raise ValueError("Unknown action: " + action)
        except Exception as e:
            self.log_message("Error managing clip automation: " + str(e))
            raise

    # ── Device command handlers ──────────────────────────────────────

    def _get_device_parameters(self, track_index, device_index, chain_index=None, show_all=False,
                               track_type="track"):
        """Return parameter list for a device."""
        try:
            track, device = self._resolve_device(track_index, device_index, track_type=track_type)

            # If chain_index, navigate into chain
            target_device = device
            if chain_index is not None:
                if not device.can_have_chains:
                    raise ValueError("Device '{0}' is not a rack".format(device.name))
                chains = device.chains
                if chain_index < 0 or chain_index >= len(chains):
                    raise IndexError("Chain index {0} out of range".format(chain_index))
                chain = chains[chain_index]
                if not chain.devices:
                    raise ValueError("Chain '{0}' has no devices".format(chain.name))
                target_device = chain.devices[0]

            params = target_device.parameters
            param_list = []
            for i, p in enumerate(params):
                pmin = p.min
                pmax = p.max
                raw_val = p.value
                norm = (raw_val - pmin) / (pmax - pmin) if pmax != pmin else 0.0
                entry = {
                    "index": i,
                    "name": p.name,
                    "value": round(norm, 4),
                    "min": pmin,
                    "max": pmax,
                    "display_value": str(p),
                    "is_enabled": p.is_enabled,
                    "is_quantized": p.is_quantized,
                    "value_items": list(p.value_items) if p.is_quantized else [],
                }
                param_list.append(entry)

            result = {
                "device_name": target_device.name,
                "device_class": target_device.class_name,
                "parameter_count": len(params),
                "parameters": param_list,
            }
            return result
        except Exception as e:
            self.log_message("Error getting device parameters: " + str(e))
            raise

    def _set_device_parameter(self, track_index, device_index, chain_index=None,
                              parameter_name=None, parameter_index=None, value=0.0,
                              track_type="track"):
        """Set a device parameter by name or index. Value is normalized 0.0-1.0."""
        try:
            track, device = self._resolve_device(track_index, device_index, track_type=track_type)

            target_device = device
            if chain_index is not None:
                if not device.can_have_chains:
                    raise ValueError("Device '{0}' is not a rack".format(device.name))
                chain = device.chains[chain_index]
                if not chain.devices:
                    raise ValueError("Chain '{0}' has no devices".format(chain.name))
                target_device = chain.devices[0]

            param, match_type = self._find_parameter(
                target_device, name=parameter_name, index=parameter_index)

            if not param.is_enabled:
                raise ValueError("Parameter '{0}' is currently disabled".format(param.name))

            pmin = param.min
            pmax = param.max
            old_norm = (param.value - pmin) / (pmax - pmin) if pmax != pmin else 0.0

            # Clamp normalized value
            clamped = max(0.0, min(1.0, value))
            was_clamped = (clamped != value)

            # Denormalize
            raw_value = pmin + clamped * (pmax - pmin)
            param.value = raw_value

            return {
                "parameter_name": param.name,
                "old_value": round(old_norm, 4),
                "new_value": round(clamped, 4),
                "display_value": str(param),
                "clamped": was_clamped,
            }
        except Exception as e:
            self.log_message("Error setting device parameter: " + str(e))
            raise

    def _set_device_enabled(self, track_index, device_index, chain_index=None, enabled=True,
                            track_type="track"):
        """Enable or disable a device via its 'Device On' parameter."""
        try:
            track, device = self._resolve_device(track_index, device_index, track_type=track_type)

            target_device = device
            if chain_index is not None:
                if not device.can_have_chains:
                    raise ValueError("Device '{0}' is not a rack".format(device.name))
                chain = device.chains[chain_index]
                if not chain.devices:
                    raise ValueError("Chain has no devices")
                target_device = chain.devices[0]

            # Use "Device On" parameter (always index 0) instead of
            # is_active which is read-only in the Live API.
            params = target_device.parameters
            if not params:
                raise ValueError("Device '{0}' has no parameters".format(target_device.name))
            on_param = params[0]
            on_param.value = on_param.max if enabled else on_param.min

            return {
                "device_name": target_device.name,
                "is_active": enabled,
            }
        except Exception as e:
            self.log_message("Error setting device enabled: " + str(e))
            raise

    def _get_chain_info(self, track_index, device_index, chain_index=None, track_type="track"):
        """Get chain information for a rack device."""
        try:
            track, device = self._resolve_device(track_index, device_index, track_type=track_type)

            if not device.can_have_chains:
                raise ValueError("Device '{0}' is not a rack and has no chains".format(device.name))

            if chain_index is not None:
                # Detail for a specific chain
                chains = device.chains
                if chain_index < 0 or chain_index >= len(chains):
                    raise IndexError("Chain index {0} out of range".format(chain_index))
                chain = chains[chain_index]
                devices = []
                for di, d in enumerate(chain.devices):
                    devices.append({
                        "index": di,
                        "name": d.name,
                        "class_name": d.class_name,
                        "type": self._get_device_type(d),
                        "is_active": d.is_active,
                        "parameter_count": len(d.parameters),
                    })
                return {
                    "chain_name": chain.name,
                    "devices": devices,
                }
            else:
                # List all chains
                chain_list = []
                for ci, chain in enumerate(device.chains):
                    chain_devices = []
                    for di, d in enumerate(chain.devices):
                        chain_devices.append({
                            "index": di,
                            "name": d.name,
                            "type": self._get_device_type(d),
                        })
                    chain_list.append({
                        "index": ci,
                        "name": chain.name,
                        "mute": chain.mute,
                        "solo": chain.solo,
                        "device_count": len(chain.devices),
                        "devices": chain_devices,
                    })
                return {
                    "device_name": device.name,
                    "chain_count": len(device.chains),
                    "chains": chain_list,
                }
        except Exception as e:
            self.log_message("Error getting chain info: " + str(e))
            raise

    def _get_drum_pad_info(self, track_index, device_index, track_type="track"):
        """Get drum pad info for a Drum Rack."""
        try:
            track, device = self._resolve_device(track_index, device_index, track_type=track_type)

            if not device.can_have_drum_pads:
                raise ValueError("Device '{0}' is not a Drum Rack".format(device.name))

            filled_pads = []
            for pad in device.drum_pads:
                if pad.chains:
                    pad_devices = []
                    for chain in pad.chains:
                        for d in chain.devices:
                            pad_devices.append({
                                "index": 0,
                                "name": d.name,
                                "type": self._get_device_type(d),
                            })
                    filled_pads.append({
                        "note": pad.note,
                        "name": pad.name,
                        "mute": pad.mute,
                        "solo": pad.solo,
                        "chains": [{
                            "name": c.name,
                            "devices": [{"index": di, "name": d.name, "type": self._get_device_type(d)}
                                        for di, d in enumerate(c.devices)]
                        } for c in pad.chains],
                    })

            return {
                "device_name": device.name,
                "filled_pads": filled_pads,
            }
        except Exception as e:
            self.log_message("Error getting drum pad info: " + str(e))
            raise

    def _delete_device(self, track_index, device_index, track_type="track"):
        """Delete a device from a track."""
        try:
            track, device = self._resolve_device(track_index, device_index, track_type=track_type)
            device_name = device.name
            track.delete_device(device_index)
            return {
                "deleted_device": device_name,
                "remaining_devices": len(track.devices),
            }
        except Exception as e:
            self.log_message("Error deleting device: " + str(e))
            raise

    def _grouped_children(self, group):
        """Session tracks nested (at any depth) inside a group track."""
        children = []
        for t in self._song.tracks:
            parent = getattr(t, "group_track", None)
            while parent is not None:
                if parent == group:
                    children.append(t)
                    break
                parent = getattr(parent, "group_track", None)
        return children

    def _delete_track(self, track_index, delete_group_contents=False):
        """Delete a session track.

        Deleting a group track in Live also removes the tracks inside it, so
        that needs delete_group_contents=True.
        """
        try:
            if len(self._song.tracks) <= 1:
                raise ValueError(
                    "Cannot delete the last remaining session track. "
                    "Ableton must always have at least one track."
                )
            if track_index < 0 or track_index >= len(self._song.tracks):
                raise IndexError("Track index {0} out of range (0-{1})".format(
                    track_index, len(self._song.tracks) - 1))
            track = self._song.tracks[track_index]
            track_name = track.name
            children = []
            if getattr(track, "is_foldable", False):
                children = [t.name for t in self._grouped_children(track)]
                if children and not delete_group_contents:
                    raise ValueError(
                        "'{0}' is a group track containing {1} track(s): {2}. Deleting it "
                        "deletes them too. Pass delete_group_contents=True to confirm.".format(
                            track_name, len(children), ", ".join(children)))
                if len(children) + 1 >= len(self._song.tracks):
                    raise ValueError("Deleting group '{0}' would remove every session track. "
                                     "Create another track first.".format(track_name))
            self._song.delete_track(track_index)
            return {
                "deleted_track": track_name,
                "deleted_group_contents": children,
                "remaining_tracks": len(self._song.tracks),
            }
        except Exception as e:
            self.log_message("Error deleting track: " + str(e))
            raise

    def _delete_return_track(self, return_index):
        returns = list(self._song.return_tracks)
        if return_index < 0 or return_index >= len(returns):
            raise IndexError("Return track index {0} out of range (0-{1})".format(
                return_index, len(returns) - 1))
        name = returns[return_index].name
        self._song.delete_return_track(return_index)
        return {"deleted_return_track": name, "remaining_return_tracks": len(self._song.return_tracks)}

    def _duplicate_track(self, track_index):
        if track_index < 0 or track_index >= len(self._song.tracks):
            raise IndexError("Track index {0} out of range (0-{1})".format(
                track_index, len(self._song.tracks) - 1))
        self._song.duplicate_track(track_index)
        # Live inserts the copy after the original (after a group's contents
        # for a group track).
        source = self._song.tracks[track_index]
        offset = 1 + (len(self._grouped_children(source)) if getattr(source, "is_foldable", False) else 0)
        new_index = track_index + offset
        return {"index": new_index, "name": self._song.tracks[new_index].name}

    def _set_track_color(self, track_index, color):
        track = self._device_track(track_index, "track")
        track.color = int(color)
        return {"track_name": track.name, "color": track.color}

    def _set_track_fold(self, track_index, folded):
        track = self._device_track(track_index, "track")
        if not getattr(track, "is_foldable", False):
            raise ValueError("Track '{0}' is not a group track".format(track.name))
        track.fold_state = bool(folded)
        return {"track_name": track.name, "folded": bool(track.fold_state)}

    def _navigate_preset(self, track_index, device_index, chain_index=None, direction="current",
                         track_type="track"):
        """Navigate device presets."""
        try:
            track, device = self._resolve_device(track_index, device_index, track_type=track_type)

            target_device = device
            if chain_index is not None:
                if not device.can_have_chains:
                    raise ValueError("Device '{0}' is not a rack".format(device.name))
                chain = device.chains[chain_index]
                if not chain.devices:
                    raise ValueError("Chain has no devices")
                target_device = chain.devices[0]

            if not hasattr(target_device, 'presets') or not target_device.presets:
                raise ValueError("Device '{0}' has no presets available".format(
                    target_device.name))

            presets = list(target_device.presets)
            current_idx = target_device.selected_preset_index

            if direction == "next":
                new_idx = min(current_idx + 1, len(presets) - 1)
                target_device.selected_preset_index = new_idx
            elif direction == "previous":
                new_idx = max(current_idx - 1, 0)
                target_device.selected_preset_index = new_idx
            elif direction == "current":
                new_idx = current_idx
            else:
                raise ValueError("Invalid direction: {0}".format(direction))

            return {
                "device_name": target_device.name,
                "preset_name": presets[new_idx] if new_idx < len(presets) else "",
                "preset_index": new_idx,
                "preset_count": len(presets),
            }
        except Exception as e:
            self.log_message("Error navigating preset: " + str(e))
            raise

    # Device helper methods

    def _device_track(self, track_index, track_type="track"):
        """Resolve the track that holds devices.

        track_type "track" addresses session tracks only; "return" and
        "master" address return tracks and the master track.
        """
        if track_type in (None, "", "track"):
            if track_index < 0 or track_index >= len(self._song.tracks):
                raise IndexError("Track index {0} out of range (0-{1})".format(
                    track_index, len(self._song.tracks) - 1))
            return self._song.tracks[track_index]
        return self._resolve_mixer_track(track_index, track_type)

    def _resolve_device(self, track_index, device_index, track_type="track"):
        """Resolve a top-level device reference to a (track, device) tuple.

        Raises IndexError or ValueError on invalid references.
        """
        track = self._device_track(track_index, track_type)

        if device_index < 0 or device_index >= len(track.devices):
            raise IndexError("Device index {0} out of range on track '{1}' (0-{2})".format(
                device_index, track.name,
                len(track.devices) - 1 if track.devices else 0))

        return track, track.devices[device_index]

    def _find_parameter(self, device, name=None, index=None):
        """Find a parameter on a device by name or index.

        Lookup order:
        1. Exact name match (case-sensitive)
        2. Case-insensitive exact match
        3. Case-insensitive partial match
        4. By 0-based index

        Returns (parameter, match_type) tuple where match_type is
        'exact', 'case_insensitive', 'partial', or 'index'.
        Raises ValueError if not found.
        """
        params = device.parameters

        if name is not None:
            # Step 1: exact match
            for p in params:
                if p.name == name:
                    return p, "exact"

            # Step 2: case-insensitive exact match
            name_lower = name.lower()
            for p in params:
                if p.name.lower() == name_lower:
                    return p, "case_insensitive"

            # Step 3: case-insensitive partial match
            for p in params:
                if name_lower in p.name.lower():
                    return p, "partial"

            raise ValueError("Parameter '{0}' not found on device '{1}'".format(
                name, device.name))

        if index is not None:
            if index < 0 or index >= len(params):
                raise IndexError("Parameter index {0} out of range on '{1}' (0-{2})".format(
                    index, device.name, len(params) - 1))
            return params[index], "index"

        raise ValueError("Either name or index must be provided")

    def _get_device_info(self, device):
        """Build a device info dict."""
        info = {
            "name": device.name,
            "class_name": device.class_name,
            "type": self._get_device_type(device),
            "is_active": device.is_active,
            "can_have_chains": device.can_have_chains,
            "can_have_drum_pads": device.can_have_drum_pads,
            "parameter_count": len(device.parameters),
        }
        try:
            info["class_display_name"] = device.class_display_name
        except Exception:
            info["class_display_name"] = device.class_name
        return info

    # General helper methods

    def _get_device_type(self, device):
        """Get the type of a device"""
        try:
            # Simple heuristic - in a real implementation you'd look at the device class
            if device.can_have_drum_pads:
                return "drum_machine"
            elif device.can_have_chains:
                return "rack"
            elif "instrument" in device.class_display_name.lower():
                return "instrument"
            elif "audio_effect" in device.class_name.lower():
                return "audio_effect"
            elif "midi_effect" in device.class_name.lower():
                return "midi_effect"
            else:
                return "unknown"
        except:
            return "unknown"
    
    def get_browser_tree(self, category_type="all"):
        """
        Get a simplified tree of browser categories.
        
        Args:
            category_type: Type of categories to get ('all', 'instruments', 'sounds', etc.)
            
        Returns:
            Dictionary with the browser tree structure
        """
        try:
            # Access the application's browser instance instead of creating a new one
            app = self.application()
            if not app:
                raise RuntimeError("Could not access Live application")
                
            # Check if browser is available
            if not hasattr(app, 'browser') or app.browser is None:
                raise RuntimeError("Browser is not available in the Live application")
            
            # Log available browser attributes to help diagnose issues
            browser_attrs = [attr for attr in dir(app.browser) if not attr.startswith('_')]
            self.log_message("Available browser attributes: {0}".format(browser_attrs))
            
            result = {
                "type": category_type,
                "categories": [],
                "available_categories": browser_attrs
            }
            
            # Helper function to process a browser item and its children
            def process_item(item, depth=0):
                if not item:
                    return None
                
                result = {
                    "name": item.name if hasattr(item, 'name') else "Unknown",
                    "is_folder": hasattr(item, 'children') and bool(item.children),
                    "is_device": hasattr(item, 'is_device') and item.is_device,
                    "is_loadable": hasattr(item, 'is_loadable') and item.is_loadable,
                    "uri": item.uri if hasattr(item, 'uri') else None,
                    "children": []
                }
                
                
                return result
            
            # Process based on category type and available attributes
            if (category_type == "all" or category_type == "instruments") and hasattr(app.browser, 'instruments'):
                try:
                    instruments = process_item(app.browser.instruments)
                    if instruments:
                        instruments["name"] = "Instruments"  # Ensure consistent naming
                        result["categories"].append(instruments)
                except Exception as e:
                    self.log_message("Error processing instruments: {0}".format(str(e)))
            
            if (category_type == "all" or category_type == "sounds") and hasattr(app.browser, 'sounds'):
                try:
                    sounds = process_item(app.browser.sounds)
                    if sounds:
                        sounds["name"] = "Sounds"  # Ensure consistent naming
                        result["categories"].append(sounds)
                except Exception as e:
                    self.log_message("Error processing sounds: {0}".format(str(e)))
            
            if (category_type == "all" or category_type == "drums") and hasattr(app.browser, 'drums'):
                try:
                    drums = process_item(app.browser.drums)
                    if drums:
                        drums["name"] = "Drums"  # Ensure consistent naming
                        result["categories"].append(drums)
                except Exception as e:
                    self.log_message("Error processing drums: {0}".format(str(e)))
            
            if (category_type == "all" or category_type == "audio_effects") and hasattr(app.browser, 'audio_effects'):
                try:
                    audio_effects = process_item(app.browser.audio_effects)
                    if audio_effects:
                        audio_effects["name"] = "Audio Effects"  # Ensure consistent naming
                        result["categories"].append(audio_effects)
                except Exception as e:
                    self.log_message("Error processing audio_effects: {0}".format(str(e)))
            
            if (category_type == "all" or category_type == "midi_effects") and hasattr(app.browser, 'midi_effects'):
                try:
                    midi_effects = process_item(app.browser.midi_effects)
                    if midi_effects:
                        midi_effects["name"] = "MIDI Effects"
                        result["categories"].append(midi_effects)
                except Exception as e:
                    self.log_message("Error processing midi_effects: {0}".format(str(e)))
            
            # Try to process other potentially available categories
            for attr in browser_attrs:
                if attr not in ['instruments', 'sounds', 'drums', 'audio_effects', 'midi_effects'] and \
                   (category_type == "all" or category_type == attr):
                    try:
                        item = getattr(app.browser, attr)
                        if hasattr(item, 'children') or hasattr(item, 'name'):
                            category = process_item(item)
                            if category:
                                category["name"] = attr.capitalize()
                                result["categories"].append(category)
                    except Exception as e:
                        self.log_message("Error processing {0}: {1}".format(attr, str(e)))
            
            self.log_message("Browser tree generated for {0} with {1} root categories".format(
                category_type, len(result['categories'])))
            return result
            
        except Exception as e:
            self.log_message("Error getting browser tree: {0}".format(str(e)))
            self.log_message(traceback.format_exc())
            raise
    
    def get_browser_items_at_path(self, path):
        """
        Get browser items at a specific path.
        
        Args:
            path: Path in the format "category/folder/subfolder"
                 where category is one of: instruments, sounds, drums, audio_effects, midi_effects
                 or any other available browser category
                 
        Returns:
            Dictionary with items at the specified path
        """
        try:
            # Access the application's browser instance instead of creating a new one
            app = self.application()
            if not app:
                raise RuntimeError("Could not access Live application")
                
            # Check if browser is available
            if not hasattr(app, 'browser') or app.browser is None:
                raise RuntimeError("Browser is not available in the Live application")
            
            # Log available browser attributes to help diagnose issues
            browser_attrs = [attr for attr in dir(app.browser) if not attr.startswith('_')]
            self.log_message("Available browser attributes: {0}".format(browser_attrs))
                
            # Parse the path
            path_parts = self._split_browser_path(path)
            if not path_parts:
                raise ValueError("Invalid path")
            
            # Determine the root category
            root_category = path_parts[0]
            current_item, resolved_root = self._resolve_browser_root_category(
                app.browser, root_category, browser_attrs
            )
            if current_item is None:
                # If we still haven't found the category, return available categories
                return {
                    "path": path,
                    "error": "Unknown or unavailable category: {0}".format(
                        self._normalize_browser_category_name(root_category)
                    ),
                    "available_categories": browser_attrs,
                    "items": []
                }

            # Keep path canonicalized to resolved root category
            path_parts[0] = resolved_root
            
            # Navigate through the path
            for i in range(1, len(path_parts)):
                part = path_parts[i]
                if not part:  # Skip empty parts
                    continue
                
                if not hasattr(current_item, 'children'):
                    return {
                        "path": path,
                        "error": "Item at '{0}' has no children".format('/'.join(path_parts[:i])),
                        "items": []
                    }
                
                found = False
                for child in current_item.children:
                    if hasattr(child, 'name') and child.name.lower() == part.lower():
                        current_item = child
                        found = True
                        break
                
                if not found:
                    return {
                        "path": path,
                        "error": "Path part '{0}' not found".format(part),
                        "items": []
                    }
            
            # Get items at the current path
            items = []
            if hasattr(current_item, 'children'):
                for child in current_item.children:
                    item_info = {
                        "name": child.name if hasattr(child, 'name') else "Unknown",
                        "is_folder": hasattr(child, 'children') and bool(child.children),
                        "is_device": hasattr(child, 'is_device') and child.is_device,
                        "is_loadable": hasattr(child, 'is_loadable') and child.is_loadable,
                        "uri": child.uri if hasattr(child, 'uri') else None
                    }
                    items.append(item_info)
            
            result = {
                "path": path,
                "name": current_item.name if hasattr(current_item, 'name') else "Unknown",
                "uri": current_item.uri if hasattr(current_item, 'uri') else None,
                "is_folder": hasattr(current_item, 'children') and bool(current_item.children),
                "is_device": hasattr(current_item, 'is_device') and current_item.is_device,
                "is_loadable": hasattr(current_item, 'is_loadable') and current_item.is_loadable,
                "items": items
            }
            
            self.log_message("Retrieved {0} items at path: {1}".format(len(items), path))
            return result
            
        except Exception as e:
            self.log_message("Error getting browser items at path: {0}".format(str(e)))
            self.log_message(traceback.format_exc())
            raise
