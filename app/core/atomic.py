"""Write a JSON file so a crash mid-write cannot corrupt it.

Every persistent store in the app is saved on an ordinary edit - a floor
typed, an item watched, a bookmark added - so a plain `write_text` that is
interrupted (power loss, a full disk, the file open in another program) can
leave a half-written file. The loaders all read a truncated JSON file as
"no data" and silently replace it with defaults, so the failure is invisible
until the user notices their settings reset.

The fix is the pattern `session.save` already used and nothing else did:
write a sibling temp file, then `os.replace` it into place. `os.replace` is
atomic on both Windows and POSIX - the destination is either the old file or
the whole new one, never a mix.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


def write_json(path: Path, obj: Any, *, indent: int = 2) -> None:
    """Serialise `obj` to `path` atomically. Raises on I/O failure - the
    caller decides whether that is fatal or merely worth a status line."""
    # A per-process temp name: a fixed '.tmp' is the SAME name two writers of
    # the same file would share, so overlapping saves could interleave into one
    # garbage temp file.
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    try:
        tmp.write_text(json.dumps(obj, indent=indent), encoding="utf-8")
        os.replace(tmp, path)
    except OSError:
        # A failed write (full disk, read-only dir) must not leave a stray
        # '.tmp' behind - the sibling atomic writers already clean up this way.
        tmp.unlink(missing_ok=True)
        raise
