"""Mastery-rank badge images, fetched on demand and cached locally.

The player's rank is their inventory PlayerLevel (see arcane_inv.read_mastery).
Rather than ship all ~52 rank icons (~15 MB), only the badge for the CURRENT
rank is downloaded from the Warframe wiki and cached under `.mastery_badges/`;
when the player ranks up their new rank simply isn't in the cache yet, so the
same code path re-fetches it. Everything degrades to a text label offline.

The wiki hosts one PNG per rank at a flat, predictable path
(`/images/IconRank{N}.png`, N = PlayerLevel), which is how one URL covers both
Mastery Ranks (0-30) and Legendary Ranks (31+ -> LR1..).
"""

from __future__ import annotations

import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent      # data/
BADGE_DIR = ROOT / ".mastery_badges"
_UA = {"User-Agent": "WarframeToolbox (personal fan tool; wiki.warframe.com)"}
_BADGE_URL = "https://wiki.warframe.com/images/IconRank{n}.png"


def rank_label(rank: int) -> str:
    """'Mastery Rank 30' up to MR 30, then 'Legendary Rank 1' at PlayerLevel
    31 and up - so Legendary ranks are named and counted correctly, not shown
    as 'MR 31'."""
    return f"Legendary Rank {rank - 30}" if rank > 30 else f"Mastery Rank {rank}"


def badge_path(rank: int) -> Path:
    return BADGE_DIR / f"IconRank{rank}.png"


def cached_badge(rank: int) -> Path | None:
    """The badge's local path if it is already cached, else None - a cheap
    stat() with no network, for callers that must not block."""
    p = badge_path(rank)
    return p if p.is_file() else None


def ensure_badge(rank: int | None, timeout: float = 15.0) -> Path | None:
    """The local path to `rank`'s badge, downloading + caching it from the wiki
    on first need. None if it cannot be fetched (offline, or an unknown rank) -
    the caller then falls back to a text label. Does network I/O, so call it
    from a worker thread; the write is atomic so a killed download can't leave a
    half-file the app would later serve as a broken image."""
    if rank is None or rank < 0:
        return None
    p = badge_path(rank)
    if p.is_file():
        return p
    try:
        req = urllib.request.Request(_BADGE_URL.format(n=rank), headers=_UA)
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = r.read()
        if data[:8] != b"\x89PNG\r\n\x1a\n":       # not an image (404 page etc.)
            return None
        BADGE_DIR.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".tmp")
        tmp.write_bytes(data)
        tmp.replace(p)                             # atomic on NTFS and POSIX
        return p
    except Exception:                              # noqa: BLE001 - offline etc.
        return None
