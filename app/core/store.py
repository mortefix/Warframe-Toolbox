"""core/store.py - the local cache-of-record for all collected game data.

Every data source (the profile API, EE.log, worldState.php, Public Export,
inventory) is a background REFRESHER that writes its normalized output here; the
rest of the app reads ONLY from here. That decoupling is deliberate and is what
lets the app stay useful when a source is unavailable - a closed game, a down
endpoint, or an OS without the source (Overwolf on Linux) just leaves one
namespace stale, never a broken screen. Reads are instant and work offline.

Files live under app/.wf_data/, one JSON per namespace. Each is wrapped in an
envelope that records WHEN it was written and the source's own mtime/version, so
a refresher can decide "do I even need to re-fetch?" from a single cheap read.
Writes go through core.atomic, so a crash mid-write can never corrupt a
namespace - a torn file simply reads back as absent and is re-earned on the next
refresh, the same self-healing contract the older per-feature caches use.

A namespace may contain '/' to group related files (e.g. "export/Warframes");
the segments become a subdirectory under .wf_data/. Absolute paths and '..'
escapes are refused so a namespace can never point outside the store.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from core import atomic
from core import paths

#: One folder holds every collected namespace, so the Settings > Data page can
#: show and wipe it as a single group (see config.WF_DATA_DIR), the way the
#: thumbnail cache is handled - not as dozens of individual USER_FILES rows.
WF_DATA_DIR = paths.USERDATA / "wf_data"

#: Envelope version. Bump ONLY if the envelope shape below changes; the payload
#: under "data" is free to evolve without touching this.
SCHEMA = 1


def _path(namespace: str) -> Path:
    """The on-disk file for `namespace`, kept strictly inside WF_DATA_DIR.

    '/' groups into subfolders; anything that could point outside the store is
    refused so a caller - or a manifest name arriving from the network - can
    never write elsewhere. The early checks reject the obvious cases; the
    containment check is authoritative and also catches the Windows quirk where
    `WF_DATA_DIR / "/etc/x"` silently resets to the drive root (a leading-slash
    path is NOT is_absolute() on Windows, but `.anchor` is truthy, and the
    relative_to() guard rejects it regardless)."""
    rel = Path(namespace)
    if rel.is_absolute() or rel.anchor or ".." in rel.parts or not rel.parts:
        raise ValueError(f"unsafe store namespace: {namespace!r}")
    p = (WF_DATA_DIR / rel).with_suffix(".json")
    try:
        p.resolve().relative_to(WF_DATA_DIR.resolve())
    except ValueError:
        raise ValueError(f"unsafe store namespace: {namespace!r}") from None
    return p


def write(namespace: str, data: Any, *, source_mtime: float | None = None,
          source_version: str | None = None) -> None:
    """Store `data` under `namespace` atomically, stamped with the write time
    and (optionally) the source's own mtime/version for cheap staleness checks.

    Raises on I/O failure - the caller decides whether that is fatal or merely
    a status line; the data was already delivered live either way."""
    p = _path(namespace)
    p.parent.mkdir(parents=True, exist_ok=True)
    atomic.write_json(p, {
        "schema": SCHEMA,
        "namespace": namespace,
        "source_mtime": source_mtime,
        "source_version": source_version,
        "written_at": time.time(),
        "data": data,
    })


def envelope(namespace: str) -> dict | None:
    """The full stored record (envelope + payload), or None if absent/corrupt.

    A corrupt namespace reads as absent so the next refresh simply re-earns it;
    the loader never raises into the UI."""
    try:
        d = json.loads(_path(namespace).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(d, dict) or "data" not in d:
        return None
    return d


def read(namespace: str) -> Any | None:
    """Just the payload for `namespace` (None if absent/corrupt)."""
    env = envelope(namespace)
    return env["data"] if env is not None else None


def source_mtime(namespace: str) -> float | None:
    """The source's own mtime stamp recorded at write time, if any."""
    env = envelope(namespace)
    return env.get("source_mtime") if env is not None else None


def source_version(namespace: str) -> str | None:
    """The source's own version string recorded at write time, if any (e.g. a
    Public Export manifest's hashed line - lets a refresher skip an unchanged
    manifest)."""
    env = envelope(namespace)
    return env.get("source_version") if env is not None else None


def written_at(namespace: str) -> float | None:
    """When this namespace was last written (epoch seconds), or None."""
    env = envelope(namespace)
    return env.get("written_at") if env is not None else None


def age(namespace: str, *, now: float | None = None) -> float | None:
    """Seconds since `namespace` was last written, or None if never written.
    `now` is injectable for tests."""
    w = written_at(namespace)
    if w is None:
        return None
    return (time.time() if now is None else now) - w


def has(namespace: str) -> bool:
    """Does this namespace exist on disk? (Does not validate its contents.)"""
    try:
        return _path(namespace).exists()
    except ValueError:
        return False
