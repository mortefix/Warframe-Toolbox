"""
core/presence.py - your online status on warframe.market.

Status there is presence-based, driven by a websocket. The site connects to

    wss://ws.warframe.market/socket        (websocket subprotocol "wfm")

then authenticates over the socket and pushes status changes:

    ->  {"route": "@wfm|cmd/auth/signIn", "payload": {"token": "<jwt>"}}
    <-  {"route": "@wfm|cmd/auth/signIn:ok"}
    ->  {"route": "@wfm|cmd/status/set",  "payload": {"status": "ingame"}}
    <-  {"route": "@wfm|cmd/status/set:ok", "payload": {"status": "ingame", ...}}

Statuses are "online", "ingame", "invisible". This app maps its three-way
toggle to: online -> online, ingame -> ingame, offline -> close the socket
(true offline; "invisible" would keep you connected but appear offline).

This manager keeps at most one background connection and exposes
set_state("online" | "ingame" | "offline"). Everything runs off the UI thread;
callers watch on_change(state, connected, detail) and marshal it back onto
their own UI thread. Like the rest of the host it talks to WFM directly (it
owns the session); tools never do.
"""

from __future__ import annotations

import json
import ssl
import threading
import time
from typing import Callable

import websocket

from core import session as wfm_session

WS_URL = "wss://ws.warframe.market/socket"
SUBPROTOCOL = "wfm"

AUTH_CMD = "@wfm|cmd/auth/signIn"
STATUS_CMD = "@wfm|cmd/status/set"

# What we send WFM for a live socket. "offline" isn't one of these - real
# offline is just closing the connection.
_PAYLOAD = {"online": "online", "ingame": "ingame"}
KEEPALIVE_SEC = 25


class Presence:
    STATES = ("offline", "online", "ingame")

    def __init__(self) -> None:
        self.session: wfm_session.Session | None = None
        self.state = "offline"          # last state we told listeners about
        self.connected = False
        self.on_change: Callable[[str, bool, str | None], None] | None = None

        self._want = "offline"          # desired state
        self._pending: str | None = None  # status the worker still owes WFM
        self._ws: websocket.WebSocket | None = None
        self._thread: threading.Thread | None = None
        self._send_lock = threading.Lock()
        # guards the (_ws, connected) pair so a cancelled worker can't
        # publish "connected" after set_state("offline") already cleared it
        self._state_lock = threading.Lock()
        self._stop = threading.Event()

    # -- public API --------------------------------------------------------

    @property
    def want(self) -> str:
        """The state the user asked for - the toggle's source of truth.
        (Public accessor: UI code must not reach into _want.)"""
        return self._want

    def set_session(self, sess: wfm_session.Session | None) -> None:
        if sess is None and self._want != "offline":
            self.set_state("offline")
        self.session = sess

    def set_state(self, state: str) -> None:
        if state not in self.STATES:
            return
        self._want = state

        if state == "offline":
            self._pending = None
            self._stop.set()
            self._close_ws()
            self._notify("offline", False, "offline")
            return

        if self.session is None:
            self._notify("offline", False, "link an account first")
            return

        if self._thread and self._thread.is_alive() \
                and not self._stop.is_set():
            # Socket already up (or coming up). Hand the status to the
            # worker instead of sending from here: this is the Tk thread,
            # and ws.send blocks on _send_lock (shared with the keepalive
            # ping and the up-to-8s auth exchange). The worker applies it
            # as soon as it is authenticated - and _run re-applies _want
            # right after auth anyway, so a mid-auth toggle still lands.
            self._pending = state
            if self.connected:
                self._send_status(state)
            self._notify(state, self.connected,
                         None if self.connected else "connecting…")
        else:
            # Fresh connection. The previous worker (if any) is winding down
            # with ITS stop event; give this connection a brand-new one so a
            # rapid offline->online flip can never strand us on a dead
            # socket (the old worker can't clear a flag it doesn't own).
            stop = threading.Event()
            self._stop = stop
            self._thread = threading.Thread(target=self._run, args=(stop,),
                                            daemon=True, name="wfm-presence")
            self._thread.start()
            self._notify(state, False, "connecting…")

    def shutdown(self) -> None:
        self._want = "offline"
        self._pending = None
        self._stop.set()
        self._close_ws()

    # -- worker ------------------------------------------------------------

    def _run(self, stop: threading.Event) -> None:
        """One connection's lifetime. `stop` is THIS connection's own stop
        event - a replacement connection gets a fresh one, so a dying worker
        can never confuse (or close) its successor's socket.

        TLS certificates are verified against the system trust store
        (websocket-client's default) - the JWT rides this socket as a
        cookie, so an unverified connection would hand it to any MITM."""
        sess = self.session
        if sess is None:
            return
        token = sess.bearer.split(" ", 1)[1]
        try:
            ws = websocket.create_connection(
                WS_URL, timeout=10, subprotocols=[SUBPROTOCOL],
                header=[f"User-Agent: {wfm_session.USER_AGENT}"],
                cookie=f"JWT={token}")
        except ssl.SSLCertVerificationError:
            # Distinct from an outage: a failed chain means a broken trust
            # store or something intercepting TLS - say so, don't blame
            # the network.
            if not stop.is_set():
                self._notify("offline", False,
                             "TLS certificate verification failed")
            return
        except Exception:                                   # noqa: BLE001
            if not stop.is_set():
                self._notify("offline", False,
                             "couldn't reach warframe.market")
            return

        if stop.is_set():           # cancelled/superseded while connecting -
            self._detach(ws)        # stand down without touching shared state
            return
        # NOTE: _ws is published only AFTER authentication. Publishing it
        # earlier let set_state push a status onto a not-yet-authenticated
        # socket, whose error reply landed in _authenticate's recv loop and
        # was read as a rejection. Anything requested meanwhile is captured
        # in _pending and applied below.
        if not self._authenticate(ws, token):
            self._detach(ws)
            if not stop.is_set():
                self._notify("offline", False, "sign-in rejected")
            return
        if stop.is_set():           # went offline (or re-toggled) mid-auth
            self._detach(ws)
            return

        # Publish + announce as one step, guarded by the same stop check:
        # a worker cancelled a moment ago must never report "connected".
        # NOTE: _detach/_notify take _state_lock themselves, so they are
        # called outside this block - never inside it.
        with self._state_lock:
            cancelled = stop.is_set()
            if not cancelled:
                self._ws = ws
                self.connected = True
                state = self._pending or self._want
                self._pending = None
        if cancelled:
            self._detach(ws)
            return
        self._send_status(state, ws)
        if stop.is_set():           # went offline while we were sending
            self._detach(ws)
            return
        self._notify(state, True, None)

        ws.settimeout(1.0)
        last_ping = time.monotonic()
        while not stop.is_set():
            try:
                ws.recv()                       # drain events (status/online…)
            except websocket.WebSocketTimeoutException:
                pass
            except Exception:                   # noqa: BLE001
                break                           # socket dropped
            # a status requested while we were mid-auth (or between recvs)
            pending, self._pending = self._pending, None
            if pending:
                self._send_status(pending, ws)
            if time.monotonic() - last_ping > KEEPALIVE_SEC:
                try:
                    with self._send_lock:
                        ws.ping()
                except Exception:               # noqa: BLE001
                    break
                last_ping = time.monotonic()

        was_current = self._ws is ws
        self._detach(ws)
        if was_current and not stop.is_set() and self._want != "offline":
            self._notify("offline", False, "disconnected")

    def _authenticate(self, ws: websocket.WebSocket, token: str) -> bool:
        """Send the socket sign-in and wait for :ok (a few seconds)."""
        try:
            ws.settimeout(6.0)
            with self._send_lock:
                ws.send(json.dumps({"route": AUTH_CMD,
                                    "payload": {"token": token}}))
            deadline = time.monotonic() + 8
            while time.monotonic() < deadline:
                msg = ws.recv()
                route = (json.loads(msg).get("route") or "") if msg else ""
                if route == AUTH_CMD + ":ok":
                    return True
                if route == AUTH_CMD + ":error" or route.startswith(
                        "@wfm|protect/error"):
                    return False
        except Exception:                                   # noqa: BLE001
            return False
        return False

    # -- helpers -----------------------------------------------------------

    def _send_status(self, state: str,
                     ws: websocket.WebSocket | None = None) -> None:
        """Push a status. Callers inside a worker pass THEIR socket, so a
        superseded worker can never write to its successor's connection."""
        payload = _PAYLOAD.get(state)
        sock = ws if ws is not None else self._ws
        if not payload or sock is None:
            return
        try:
            with self._send_lock:
                sock.send(json.dumps({"route": STATUS_CMD,
                                      "payload": {"status": payload}}))
        except Exception:                                   # noqa: BLE001
            pass

    def _close_ws(self) -> None:
        with self._state_lock:
            ws, self._ws = self._ws, None
            self.connected = False
        if ws is not None:
            try:
                ws.close()
            except Exception:                               # noqa: BLE001
                pass

    def _detach(self, ws: websocket.WebSocket) -> None:
        """Close one worker's socket; clear the shared handle/state only if
        it is still the CURRENT connection (a replacement may be live)."""
        with self._state_lock:
            if self._ws is ws:
                self._ws = None
                self.connected = False
        try:
            ws.close()
        except Exception:                                   # noqa: BLE001
            pass

    def _notify(self, state: str, connected: bool, detail: str | None) -> None:
        # Under _state_lock: a worker announcing "connected" must not
        # overwrite a set_state("offline") that landed a moment earlier -
        # the flag would stay True with no socket behind it.
        with self._state_lock:
            self.state = state
            self.connected = connected
        if self.on_change:
            self.on_change(state, connected, detail)
