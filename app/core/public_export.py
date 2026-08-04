"""core/public_export.py - Digital Extremes' sanctioned item/mod/relic database.

The "Public Export" is DE's own machine-readable dump of the game's static data:
warframes, weapons, mods (Upgrades), relics/arcanes, resources, recipes, regions
and more. It is the legitimate, DE-blessed alternative to datamining a local
cache, and it is what turns the terse `/Lotus/...` unique names that appear in
the profile API, world state and (later) inventory into human-readable names.

Shape of the feed:
  * An INDEX (index_en.txt.lzma) lists the current manifest files, each line
    "ExportWarframes_en.json!00_<hash>" - the hash changes only when DE ships
    new data, so it doubles as a cache-busting version.
  * Each MANIFEST (…/Manifest/<line>) is a JSON object whose single top-level
    key (e.g. "ExportWarframes") holds a list of entries with `uniqueName` and
    `name`.

This adapter is a REFRESHER. sync() refreshes the index, then fetches only the
manifests whose version changed (or are missing), writing each raw under
"export/<stem>" in the local store. On a normal run - no game update since last
sync - every manifest is skipped, so it costs one small index fetch. Everything
is DE-sanctioned public data; no credentials.

The one non-obvious bit is DE's LZMA: the index declares an uncompressed size but
omits the end marker Python's sized-mode decoder expects, so decode fails as
"corrupt". Blanking the 8-byte size field to 0xFF forces end-marker mode, which
decodes cleanly - see _decompress_index.
"""

from __future__ import annotations

import hashlib
import json
import lzma
from typing import Any, Callable

from core import store, wf_http

INDEX_URL = "https://content.warframe.com/PublicExport/index_en.txt.lzma"
MANIFEST_BASE = "https://content.warframe.com/PublicExport/Manifest/"

INDEX_NS = "export/_index"
_SUFFIX = "_en.json"            # stripped from a manifest filename to get its stem

BytesGetter = Callable[[str], bytes]


# ---- index -----------------------------------------------------------------

def _decompress_index(raw: bytes) -> str:
    """Decompress DE's LZMA index. The header's 8-byte uncompressed-size field
    (bytes 5..12) is blanked to 0xFF so the decoder runs in end-marker mode -
    DE's stream lacks the marker that sized mode needs, and decodes as 'corrupt'
    otherwise."""
    patched = raw[:5] + b"\xff" * 8 + raw[13:]
    dec = lzma.LZMADecompressor(format=lzma.FORMAT_ALONE)
    return dec.decompress(patched).decode("utf-8", "replace")


def _parse_index(text: str) -> list[dict]:
    """Index text -> [{"stem": "ExportWarframes", "line": "<name>!00_<hash>"}]."""
    out = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        name = line.split("!", 1)[0]                # ExportWarframes_en.json
        stem = name[:-len(_SUFFIX)] if name.endswith(_SUFFIX) else name
        out.append({"stem": stem, "line": line})
    return out


def fetch_index(*, _get_bytes: BytesGetter = wf_http.get_bytes) -> list[dict]:
    """Fetch + decompress + parse the manifest index. Raises wf_http.WFHttpError
    on a transport failure or lzma.LZMAError on a bad body."""
    return _parse_index(_decompress_index(_get_bytes(INDEX_URL)))


def refresh_index(*, _get_bytes: BytesGetter = wf_http.get_bytes) \
        -> list[dict] | None:
    """Fetch and store the index. Returns the entries, or None (cache untouched)
    on failure. The stored source_version is a hash of the whole index, so a
    caller can tell at a glance whether the item DB moved at all."""
    try:
        entries = fetch_index(_get_bytes=_get_bytes)
    except (wf_http.WFHttpError, lzma.LZMAError):
        return None
    if not entries:
        return None
    version = hashlib.sha1(
        "\n".join(e["line"] for e in entries).encode("utf-8")).hexdigest()
    store.write(INDEX_NS, entries, source_version=version)
    return entries


def index() -> list[dict]:
    """The stored index entries, or [] if never refreshed."""
    data = store.read(INDEX_NS)
    return data if isinstance(data, list) else []


# ---- manifests -------------------------------------------------------------

def fetch_manifest(line: str, *,
                   _get_bytes: BytesGetter = wf_http.get_bytes) -> dict | None:
    """Fetch and parse one manifest by its index line. Parsed leniently
    (strict=False) because DE occasionally emits raw control characters that a
    strict JSON parser rejects. Returns None if the body isn't JSON."""
    raw = _get_bytes(MANIFEST_BASE + line)
    try:
        data = json.loads(raw.decode("utf-8", "replace"), strict=False)
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def refresh_manifest(entry: dict, *,
                     _get_bytes: BytesGetter = wf_http.get_bytes) -> dict | None:
    """Fetch one manifest and store it under export/<stem>, stamped with its
    versioned line so sync() can skip it next time. Returns the data or None."""
    try:
        data = fetch_manifest(entry["line"], _get_bytes=_get_bytes)
    except wf_http.WFHttpError:
        return None
    if data is None:
        return None
    store.write(f"export/{entry['stem']}", data, source_version=entry["line"])
    return data


def sync(*, _get_bytes: BytesGetter = wf_http.get_bytes) -> dict:
    """Refresh the index, then fetch only the manifests whose version changed or
    are missing. On a run with no game update, every manifest is skipped for the
    cost of one index fetch. Returns a summary dict:
      {"index": bool, "fetched": [...stems], "skipped": [...], "failed": [...]}.
    Invalidates the in-process name index so the next resolve() sees new data."""
    entries = refresh_index(_get_bytes=_get_bytes)
    if entries is None:
        return {"index": False, "fetched": [], "skipped": [], "failed": []}
    fetched, skipped, failed = [], [], []
    for e in entries:
        ns = f"export/{e['stem']}"
        if store.has(ns) and store.source_version(ns) == e["line"]:
            skipped.append(e["stem"])
            continue
        if refresh_manifest(e, _get_bytes=_get_bytes) is not None:
            fetched.append(e["stem"])
        else:
            failed.append(e["stem"])
    invalidate_name_index()
    return {"index": True, "fetched": fetched, "skipped": skipped,
            "failed": failed}


# ---- accessors -------------------------------------------------------------

def manifest(stem: str) -> dict | None:
    """The raw stored manifest object for a stem (e.g. 'ExportWarframes')."""
    data = store.read(f"export/{stem}")
    return data if isinstance(data, dict) else None


def category(stem: str) -> list:
    """The entry list inside a manifest (its single top-level key equals the
    stem, e.g. manifest['ExportWarframes'])."""
    m = manifest(stem)
    if not isinstance(m, dict):
        return []
    val = m.get(stem)
    return val if isinstance(val, list) else []


_NAME_INDEX: dict[str, str] | None = None


def _build_name_index() -> dict[str, str]:
    idx: dict[str, str] = {}
    for entry in index():
        for row in category(entry["stem"]):
            if isinstance(row, dict):
                uid, name = row.get("uniqueName"), row.get("name")
                if isinstance(uid, str) and isinstance(name, str):
                    idx.setdefault(uid, name)
    return idx


def invalidate_name_index() -> None:
    """Drop the in-process uniqueName->name map (rebuilt on next resolve)."""
    global _NAME_INDEX
    _NAME_INDEX = None


def resolve_name(unique_name: str) -> str | None:
    """Human-readable name for a `/Lotus/...` uniqueName, from the cached
    manifests, or None if unknown. Builds a uniqueName->name map once and reuses
    it; call invalidate_name_index() (sync does) after the DB changes."""
    global _NAME_INDEX
    if _NAME_INDEX is None:
        _NAME_INDEX = _build_name_index()
    return _NAME_INDEX.get(unique_name)
