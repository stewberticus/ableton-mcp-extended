"""Convert Xfer Serum 2 ``.SerumPreset`` files into VST3 ``.vstpreset`` files.

Why this exists: Live's Python API can't hand a plugin a preset file. A
PluginDevice only exposes the programs the plugin reports (Serum 2 reports one,
"Default"), and the only load call is ``Browser.load_item``, which takes items
from Live's browser. Live's browser ignores ``.SerumPreset`` files but lists
``.vstpreset`` files saved under ``~/Library/Audio/Presets/<vendor>/<plugin>/``,
and loading one passes its state straight to the plugin.

A ``.SerumPreset`` holds both halves of Serum's VST3 state merged together:

- the processor state (the sound: oscillators, envelopes, LFOs, FX, macros), and
- the controller state (preset name/author, oscillator editor and GUI settings).

Both are ``XferJson`` containers: ``b"XferJson\\x00"``, ``<II`` (metadata
length, 0), JSON metadata, ``<II`` (CBOR length, 2), zstd-compressed CBOR.
This module splits the merged CBOR back into the two halves and writes them as
the ``Comp`` and ``Cont`` chunks of a ``.vstpreset``. Checked by hand against
Serum 2.1.5 in Live 12.4.5: a file built this way loads and Serum shows the
preset's name.
"""

from __future__ import annotations

import json
import os
import re
import struct
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

MAGIC = b"XferJson\x00"
_U32X2 = struct.Struct("<II")

# Serum 2's VST3 processor class ID (Serum2.vst3/Contents/Resources/moduleinfo.json).
SERUM2_CLASS_ID = "56534558667350736572756D20320000"

# Top-level keys that only exist in the controller half of Serum's state.
CONTROLLER_KEYS = frozenset({
    "ClipPlayer", "Filter", "GranularOsc", "MultiSampleOsc", "Osc", "SerumGUI",
    "SpectralOsc", "WTOsc", "arpBankDisplayName", "clipBankDisplayName",
})
# Preset-file-only metadata that belongs in neither state half's body.
PRESET_ONLY_KEYS = frozenset({
    "fileType", "presetName", "presetAuthor", "presetComment", "presetDescription",
})
_STATE_VERSION = 7.0

DEFAULT_PRESET_ROOTS = (
    "/Library/Audio/Presets/Xfer Records/Serum 2 Presets/Presets",
    "~/Library/Audio/Presets/Xfer Records/Serum 2 Presets/Presets",
)
# Live lists .vstpreset files found here under Plugins > VST3 > Xfer Records > Serum 2.
DEFAULT_OUTPUT_DIR = "~/Library/Audio/Presets/Xfer Records/Serum 2/MCP"


class SerumPresetError(Exception):
    """Raised when a preset can't be found, read or converted."""


def _codecs():
    try:
        import cbor2
        import zstandard
    except ImportError as e:  # pragma: no cover - depends on the environment
        raise SerumPresetError(
            "loading Serum presets needs the 'cbor2' and 'zstandard' packages; "
            "install them into the Ableton MCP server's environment with "
            "`pip install cbor2 zstandard`, then restart the server"
        ) from e
    return cbor2, zstandard


def unpack_xferjson(raw: bytes) -> Tuple[Dict[str, Any], Any]:
    """Return (metadata, decoded CBOR body) of an XferJson container."""
    if not raw.startswith(MAGIC):
        raise SerumPresetError("not a Serum 2 preset (missing XferJson header)")
    cbor2, zstandard = _codecs()
    try:
        offset = len(MAGIC)
        meta_len, _ = _U32X2.unpack_from(raw, offset)
        offset += _U32X2.size
        meta = json.loads(raw[offset:offset + meta_len])
        offset += meta_len
        body_len, _ = _U32X2.unpack_from(raw, offset)
        offset += _U32X2.size
        cbor_bytes = zstandard.ZstdDecompressor().decompress(
            raw[offset:], max_output_size=max(body_len, 1))
        return meta, cbor2.loads(cbor_bytes)
    except SerumPresetError:
        raise
    except Exception as e:
        raise SerumPresetError("could not decode Serum preset: {0}".format(e)) from e


def pack_xferjson(meta: Dict[str, Any], body: Any) -> bytes:
    cbor2, zstandard = _codecs()
    meta_bytes = json.dumps(meta, separators=(",", ":")).encode("utf-8")
    cbor_bytes = cbor2.dumps(body)
    compressed = zstandard.ZstdCompressor(level=3).compress(cbor_bytes)
    return (MAGIC + _U32X2.pack(len(meta_bytes), 0) + meta_bytes
            + _U32X2.pack(len(cbor_bytes), 2) + compressed)


def split_preset(meta: Dict[str, Any], body: Dict[str, Any],
                 source_path: str = "") -> Tuple[bytes, bytes]:
    """Split a preset's merged body into (processor_state, controller_state)."""
    if meta.get("fileType") != "SerumPreset" or not isinstance(body, dict):
        raise SerumPresetError("not a Serum 2 preset (fileType is {0!r})".format(
            meta.get("fileType")))
    common = {k: meta[k] for k in ("product", "productVersion", "url", "vendor") if k in meta}
    names = {
        "presetAuthor": meta.get("presetAuthor", ""),
        "presetDescription": meta.get("presetDescription", ""),
        "presetName": meta.get("presetName", ""),
    }

    processor = {k: v for k, v in body.items()
                 if k not in CONTROLLER_KEYS and k not in PRESET_ONLY_KEYS}
    processor["component"] = "processor"
    processor_meta = dict(component="processor", hash=meta.get("hash", ""),
                          version=_STATE_VERSION, **common)

    controller = {k: v for k, v in body.items() if k in CONTROLLER_KEYS}
    controller.update(common)
    controller.update(names)
    controller.update(component="controller", presetHasBeenEdited=False,
                      selectedPresetPath=source_path, version=_STATE_VERSION)
    controller_meta = dict(component="controller", hash=meta.get("hash", ""),
                           version=_STATE_VERSION, **names, **common)

    return (pack_xferjson(processor_meta, processor),
            pack_xferjson(controller_meta, controller))


def build_vstpreset(class_id: str, chunks: List[Tuple[bytes, bytes]]) -> bytes:
    """Write a VST3 preset file: header, chunk data, then the chunk list."""
    if len(class_id) != 32:
        raise ValueError("class_id must be 32 hex characters")
    header_len = 4 + 4 + 32 + 8
    data = b"".join(chunk for _, chunk in chunks)
    out = bytearray(b"VST3")
    out += struct.pack("<i", 1)
    out += class_id.encode("ascii")
    out += struct.pack("<q", header_len + len(data))
    out += data
    out += b"List" + struct.pack("<i", len(chunks))
    offset = header_len
    for chunk_id, chunk in chunks:
        out += chunk_id + struct.pack("<qq", offset, len(chunk))
        offset += len(chunk)
    return bytes(out)


def serum_preset_to_vstpreset(raw: bytes, source_path: str = "") -> bytes:
    meta, body = unpack_xferjson(raw)
    processor, controller = split_preset(meta, body, source_path)
    return build_vstpreset(SERUM2_CLASS_ID, [(b"Comp", processor), (b"Cont", controller)])


def preset_roots() -> List[Path]:
    """Folders searched for presets: $SERUM_PRESETS_DIRS (os.pathsep-separated) or Serum's defaults."""
    env = os.environ.get("SERUM_PRESETS_DIRS", "")
    raw = [p for p in env.split(os.pathsep) if p.strip()] or list(DEFAULT_PRESET_ROOTS)
    return [Path(p).expanduser() for p in raw]


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def find_serum_preset(query: str, roots: Optional[Iterable[Path]] = None) -> Path:
    """Resolve a preset by file path, or by name searched under the preset roots.

    A name may include folders ("User/DnB Wub Bass"). An exact name match wins;
    otherwise a single partial match is accepted and several are reported.
    """
    query = (query or "").strip()
    if not query:
        raise SerumPresetError("preset is required")
    direct = Path(query).expanduser()
    if direct.suffix.lower() == ".serumpreset" or direct.is_absolute():
        if direct.is_file():
            return direct
        raise SerumPresetError("preset file not found: {0}".format(direct))

    roots = [Path(r) for r in (roots if roots is not None else preset_roots())]
    candidates: List[Path] = []
    for root in roots:
        if root.is_dir():
            candidates.extend(p for p in root.rglob("*") if p.suffix.lower() == ".serumpreset")
    if not candidates:
        raise SerumPresetError("no .SerumPreset files found under: {0}".format(
            ", ".join(str(r) for r in roots)))

    wanted = _norm(query)
    wanted_parts = [_norm(part) for part in re.split(r"[\\/]", query) if part.strip()]

    def rel_parts(p: Path) -> List[str]:
        return [_norm(part) for part in p.with_suffix("").parts]

    exact = [p for p in candidates
             if rel_parts(p)[-len(wanted_parts):] == wanted_parts]
    if len(exact) == 1:
        return exact[0]
    pool = exact or [p for p in candidates if wanted in _norm(p.stem)]
    if len(pool) == 1:
        return pool[0]
    if not pool:
        raise SerumPresetError("no Serum preset matches '{0}'".format(query))
    shown = ", ".join(sorted(str(p) for p in pool)[:8])
    more = "" if len(pool) <= 8 else " (+{0} more)".format(len(pool) - 8)
    raise SerumPresetError(
        "{0} Serum presets match '{1}': {2}{3}. Pass a folder-qualified name "
        "(e.g. 'User/<name>') or the full path.".format(len(pool), query, shown, more))


def output_dir() -> Path:
    return Path(os.environ.get("SERUM_VSTPRESET_DIR", DEFAULT_OUTPUT_DIR)).expanduser()


def write_vstpreset(source: Path, out_dir: Optional[Path] = None) -> Path:
    """Convert ``source`` and write ``<stem>.vstpreset`` into the output folder.

    The file is only rewritten when the source is newer or the content differs,
    so Live's browser index isn't churned on repeat loads.
    """
    out_dir = Path(out_dir) if out_dir is not None else output_dir()
    data = serum_preset_to_vstpreset(source.read_bytes(), str(source))
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / (source.stem + ".vstpreset")
    if not target.exists() or target.read_bytes() != data:
        tmp = target.with_suffix(".vstpreset.tmp")
        tmp.write_bytes(data)
        os.replace(tmp, target)
    return target
