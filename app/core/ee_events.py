"""core/ee_events.py - a read-only incremental tail of Warframe's EE.log,
turning the game's own session log into a stream of structured player events.

wf_local already reads the account line from EE.log; this module reads the rest -
incrementally. It remembers the byte offset it last reached, reads ONLY the bytes
the game has appended since (never re-scanning a multi-hundred-MB log), and
matches each new line against a small rule table. Matched events accumulate in
the local store under the "ee_events" namespace, ring-capped so the store can't
grow without bound.

Read-only, always: every byte comes through wf_local.read_from_readonly (an
os.O_RDONLY handle), so the tail physically cannot alter a game file - the same
ToS-safe guarantee the account reader keeps.

Two log realities are handled explicitly:
  * ROTATION - the game rewrites EE.log from empty on each launch. When the file
    is shorter than our stored offset, that's a new session: the offset resets to
    0 and the event list is cleared, so ee_events reflects the CURRENT session.
  * PARTIAL LINES - a read capped at MAX_TAIL_BYTES may end mid-line; the offset
    still advances past it, so the next pass simply continues. A best-effort tail,
    not a guaranteed-every-line parser.

The rule table is deliberately small and made of structurally-stable lines
(login, squad joins, host migration, state changes). Adding an event type is one
row in _RULES - no other change - which is the point: the collection layer is a
superset a future feature reads from, never something a feature has to extend.
"""

from __future__ import annotations

import re
from typing import Callable

from core import store, wf_local

NAMESPACE = "ee_events"

#: Cap a single tail read (a long session's log is huge; the account/event lines
#: we care about are sparse, so a few MB per pass is ample).
MAX_TAIL_BYTES = 4 * 1024 * 1024

#: Ring-buffer cap on stored events, so the namespace stays small.
MAX_EVENTS = 2000

#: Every EE.log line is "<seconds> <Subsystem> [<Level>]: <message>".
_LINE = re.compile(r"^(\d+\.\d+)\s+(\w+)\s+\[(\w+)\]:\s*(.*)$")

#: (pattern searched in the MESSAGE, event type, names for the pattern's groups).
#: Keep these structurally stable - matched against the game's own log wording.
_RULES: list[tuple[re.Pattern, str, tuple[str, ...]]] = [
    (re.compile(r"Logged in (\S+)"), "login", ("player",)),
    (re.compile(r"AddSquadMember: ([^,]+),"), "squad_join", ("player",)),
    (re.compile(r"Host migration"), "host_migration", ()),
    (re.compile(r"OnStateStarted"), "state_started", ()),
]


def _parse_line(line: str) -> dict | None:
    """A structured event for a recognised line, else None. The event carries the
    relative timestamp (seconds since game start), the subsystem, the type, a
    trimmed message, and any named fields the rule captured."""
    m = _LINE.match(line)
    if not m:
        return None
    ts, subsystem, _level, msg = m.groups()
    for pattern, etype, fields in _RULES:
        hit = pattern.search(msg)
        if hit:
            ev = {"t": float(ts), "sub": subsystem, "type": etype,
                  "msg": msg[:300]}
            for i, field in enumerate(fields):
                ev[field] = hit.group(i + 1)
            return ev
    return None


def _load_state() -> dict:
    d = store.read(NAMESPACE)
    if isinstance(d, dict) and isinstance(d.get("events"), list):
        return {
            "offset": int(d.get("offset") or 0),
            "log_size": int(d.get("log_size") or 0),
            "events": d["events"],
        }
    return {"offset": 0, "log_size": 0, "events": []}


def _save_state(offset: int, log_size: int, events: list) -> None:
    store.write(NAMESPACE, {"offset": offset, "log_size": log_size,
                            "events": events})


def tail(path=wf_local.EE_LOG,
         _size: Callable[..., int | None] = None) -> list[dict]:
    """Read newly-appended EE.log lines, append recognised events to the store,
    and return the full current event list. Safe to call from a worker thread;
    a no-op returning the cached events when the log is absent. `_size` is
    injectable for tests."""
    state = _load_state()
    size = (_size or _file_size)(path)
    if size is None:                       # log gone: keep what we have
        return state["events"]

    offset, events = state["offset"], state["events"]
    if size < offset:                      # rotated: a new session started
        offset, events = 0, []

    if size > offset:
        chunk = wf_local.read_from_readonly(path, offset,
                                            min(size - offset, MAX_TAIL_BYTES))
        offset += len(chunk)
        for line in chunk.decode("utf-8", "replace").splitlines():
            ev = _parse_line(line)
            if ev is not None:
                events.append(ev)
        events = events[-MAX_EVENTS:]

    _save_state(offset, size, events)
    return events


def _file_size(path) -> int | None:
    try:
        return path.stat().st_size
    except OSError:
        return None


# ---- accessors -------------------------------------------------------------

def events(event_type: str | None = None) -> list:
    """Stored events, optionally filtered to one type. Reads the store only -
    instant, offline; call tail() to pull in anything new first."""
    d = store.read(NAMESPACE)
    evs = d.get("events", []) if isinstance(d, dict) else []
    if event_type is None:
        return evs
    return [e for e in evs if e.get("type") == event_type]


def latest_login() -> str | None:
    """The most recent logged-in player name seen in the tail, or None."""
    logins = events("login")
    return logins[-1].get("player") if logins else None
