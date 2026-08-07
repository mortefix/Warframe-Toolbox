"""core/mod_images.py - disk cache of wiki mod-card art.

mods.db stores each mod's wiki image FILENAME (e.g. "PrimedRedirectionMod
.png"); the wiki serves the file itself through the stable
Special:FilePath/<name> redirect. This module owns the download and the
on-disk cache (config.MOD_IMG_CACHE, sized/wiped with the thumbnail cache
from Settings > Data) so views only ever deal in local paths.

Callers use `cached(filename)` for a no-network lookup and `fetch(filename)`
from a worker thread (ui/work.py) when a miss should be filled. Nothing here
touches Qt - a view turns the returned path into a QPixmap itself.
"""

from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import quote

import requests

from core import config
from core.session import USER_AGENT

BASE = "https://wiki.warframe.com/w/Special:FilePath/"

_SAFE = re.compile(r"[^A-Za-z0-9._-]")


def _local(filename: str) -> Path:
    # wiki filenames are already flat ("XMod.png"), but never trust a path
    # component from data - flatten anything else defensively
    return config.MOD_IMG_CACHE / _SAFE.sub("_", filename)


def cached(filename: str | None) -> Path | None:
    """The local file for a wiki image name, or None if not downloaded yet.
    Never touches the network - safe on the GUI thread."""
    if not filename:
        return None
    p = _local(filename)
    return p if p.is_file() and p.stat().st_size > 0 else None


def fetch(filename: str | None, timeout: int = 20) -> Path | None:
    """Download-and-cache one image; returns the local path or None.
    Blocking - call from ui/work, never the GUI thread."""
    if not filename:
        return None
    hit = cached(filename)
    if hit is not None:
        return hit
    config.MOD_IMG_CACHE.mkdir(parents=True, exist_ok=True)
    try:
        r = requests.get(BASE + quote(filename), timeout=timeout,
                         headers={"User-Agent": USER_AGENT})
        if not r.ok or not r.content:
            return None
    except requests.RequestException:
        return None
    p = _local(filename)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_bytes(r.content)
    tmp.replace(p)
    return p
