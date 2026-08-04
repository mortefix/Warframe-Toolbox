"""
core/gateway.py - the host's API gateway. ALL tool networking goes through
here; tools have no credentials and no direct line to warframe.market.

The host starts a tiny HTTP server on 127.0.0.1 (random port) and hands each
tool two environment variables at launch:

    WFM_GATEWAY        e.g. http://127.0.0.1:51234
    WFM_GATEWAY_TOKEN  a per-launch secret; requests without it are rejected

A tool calls the gateway exactly as it would call api.warframe.market
(same paths, same methods, plus the X-Gateway-Token header). The gateway:

  * rejects anything without the token, from anywhere but localhost, or
    outside /v1/ and /v2/,
  * injects the identifying User-Agent and platform headers,
  * injects Authorization from the host's linked session - the JWT never
    enters a tool process,
  * enforces ONE shared rate limit across every running tool, so three tools
    together still stay far under WFM's public ceiling.

If a tool is started outside the host, these variables don't exist and the
tool must exit immediately - by design it cannot function alone.
"""

from __future__ import annotations

import hmac
import json
import posixpath
import secrets
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote

import requests

from core import session as wfm_session

API = "https://api.warframe.market"
USER_AGENT = wfm_session.USER_AGENT

ENV_GATEWAY = "WFM_GATEWAY"
ENV_TOKEN = "WFM_GATEWAY_TOKEN"
ENV_NAME = "WFM_INGAME_NAME"
ENV_PLATFORM = "WFM_PLATFORM"

ALLOWED_PREFIXES = ("/v1/", "/v2/")
# PATCH is how v2 order updates are written (PATCH /v2/order/{id}) - the
# host<->tool contract promises it, so it must stay proxied here.
ALLOWED_METHODS = ("GET", "POST", "PUT", "PATCH", "DELETE")

# A tool's request body is bounded: order writes are a few hundred bytes.
MAX_BODY = 10 * 1024 * 1024


def path_allowed(path: str) -> bool:
    """Is this request path inside /v1/ or /v2/ - even after dot-segments
    and percent-encoding are resolved?

    A bare startswith() check passes '/v1/../anything', and neither
    requests/urllib3 nor the upstream CDN keep that path intact - it
    resolves to '/anything', with the host's Authorization attached. The
    allowlist is the tool-facing control, so it normalises first."""
    raw = path.split("?", 1)[0]
    # decode twice: '%252e%252e' would otherwise survive one unquote
    decoded = unquote(unquote(raw))
    if "\\" in decoded:                     # backslash is not a separator
        return False
    normalised = posixpath.normpath(decoded)
    if not normalised.endswith("/") and decoded.endswith("/"):
        normalised += "/"                   # normpath strips the trailing /
    return (normalised.startswith(ALLOWED_PREFIXES)
            and raw.startswith(ALLOWED_PREFIXES))


class _SharedLimiter:
    """One request at a time, minimum spacing between upstream calls -
    shared by every tool the host is running."""

    def __init__(self, min_interval: float = 0.6):
        self.min_interval = min_interval
        self._lock = threading.Lock()
        self._last = 0.0

    def wait(self) -> None:
        with self._lock:
            now = time.monotonic()
            gap = self.min_interval - (now - self._last)
            if gap > 0:
                time.sleep(gap)
            self._last = time.monotonic()


class Gateway:
    def __init__(self) -> None:
        self.token = secrets.token_urlsafe(24)
        self.session: wfm_session.Session | None = None
        self.limiter = _SharedLimiter()
        self._httpd: ThreadingHTTPServer | None = None
        self.port: int = 0
        # One upstream connection pool for all tools.
        self._upstream = requests.Session()

    # -- lifecycle -------------------------------------------------------

    def start(self) -> None:
        gateway = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"
            timeout = 30        # a stalled tool can't hold a thread forever

            def log_message(self, *args) -> None:   # keep the console quiet
                pass

            def _handle(self) -> None:
                gateway._proxy(self)

        # THIS binding is the method allowlist: BaseHTTPRequestHandler
        # dispatches on do_<METHOD>, answering 501 for anything unbound.
        # Derived from ALLOWED_METHODS so the two cannot drift.
        for _method in ALLOWED_METHODS:
            setattr(Handler, f"do_{_method}", Handler._handle)

        self._httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = self._httpd.server_port
        threading.Thread(target=self._httpd.serve_forever,
                         daemon=True, name="wfm-gateway").start()

    def stop(self) -> None:
        if self._httpd:
            self._httpd.shutdown()
            self._httpd = None

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    # -- request handling --------------------------------------------------

    def _proxy(self, rq: BaseHTTPRequestHandler) -> None:
        # Constant-time compare, on BYTES: http.server decodes headers as
        # latin-1, and compare_digest raises TypeError on a non-ASCII str -
        # which would kill the handler thread inside the auth check itself.
        if not hmac.compare_digest(
                (rq.headers.get("X-Gateway-Token") or "").encode(
                    "latin-1", "ignore"),
                self.token.encode("ascii")):
            self._reply(rq, 403, b'{"error":"bad or missing gateway token"}')
            return
        path = rq.path
        if not path_allowed(path):
            self._reply(rq, 404, b'{"error":"path not allowed"}')
            return
        # Client-supplied length: a non-numeric value would kill the handler
        # thread, and a negative one would make read() block until the peer
        # closes - on a keep-alive connection, forever.
        raw_len = rq.headers.get("Content-Length") or "0"
        try:
            length = int(raw_len)
        except ValueError:
            self._reply(rq, 400, b'{"error":"bad content-length"}')
            return
        if length < 0 or length > MAX_BODY:
            self._reply(rq, 413, b'{"error":"body too large"}')
            return
        body = rq.rfile.read(length) if length else None

        # Snapshot the session ONCE. This runs on a handler thread while the GUI
        # thread may reassign self.session to None (unlink) or a new session
        # (relink) at any instant; reading it repeatedly lets a passed `if sess`
        # check be followed by a None dereference of .bearer on the next line.
        sess = self.session
        platform = sess.platform if sess else "pc"
        headers = {
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
            "Content-Type": "application/json; charset=utf-8",
            "platform": platform,
            "language": "en",
            "crossplay": "true",
        }
        if sess:
            # v2 expects 'Bearer <token>'; v1 (signin surface only, unauthed
            # in practice) historically used 'JWT <token>'. session.bearer
            # normalises the stored token, so derive the v1 form from it.
            if path.startswith("/v2/"):
                headers["Authorization"] = sess.bearer
            else:
                headers["Authorization"] = "JWT " + sess.bearer.split(" ", 1)[1]

        self.limiter.wait()
        try:
            # allow_redirects=False: the allowlist is checked once, against
            # the inbound path. Following a 3xx would carry the tool's body
            # and our injected headers to a location we never vetted - relay
            # the redirect instead and let the tool re-request through here.
            up = self._upstream.request(
                rq.command, f"{API}{path}", headers=headers, data=body,
                timeout=25, allow_redirects=False)
        except requests.RequestException as exc:
            # json.dumps, not an f-string: exception text carries quotes and
            # backslashes, and slicing encoded bytes could cut mid-sequence
            self._reply(rq, 502, json.dumps(
                {"error": f"upstream: {exc}"[:400]}).encode())
            return

        extra = {}
        if "Retry-After" in up.headers:
            extra["Retry-After"] = up.headers["Retry-After"]
        if "Location" in up.headers:            # relayed, not followed
            extra["Location"] = up.headers["Location"]
        # body was drained above, so this reply can keep the connection
        self._reply(rq, up.status_code, up.content, extra, drained=True)

    @staticmethod
    def _reply(rq: BaseHTTPRequestHandler, status: int, body: bytes,
               extra: dict[str, str] | None = None,
               drained: bool = False) -> None:
        """`drained` says the request body was already read. When it wasn't
        (every early-reject path), the unread bytes would be parsed as the
        next request line on this keep-alive connection - so close rather
        than desync. Relayed upstream replies stay on keep-alive, whatever
        their status: a 404 for an unknown slug is routine, not a reason to
        drop the tool's connection."""
        try:
            if not drained:
                rq.close_connection = True
            rq.send_response(status)
            rq.send_header("Content-Type", "application/json")
            rq.send_header("Content-Length", str(len(body)))
            for k, v in (extra or {}).items():
                rq.send_header(k, v)
            rq.end_headers()
            rq.wfile.write(body)
        except (ConnectionError, BrokenPipeError, OSError):
            pass    # tool went away mid-reply; nothing to do

    # -- hand-off ----------------------------------------------------------

    def child_env(self, base: dict[str, str]) -> dict[str, str]:
        """Environment for a tool subprocess. Note: no JWT in here - only the
        gateway address and its launch token."""
        env = dict(base)
        env[ENV_GATEWAY] = self.url
        env[ENV_TOKEN] = self.token
        env[ENV_PLATFORM] = self.session.platform if self.session else "pc"
        if self.session:
            env[ENV_NAME] = self.session.username
        else:
            env.pop(ENV_NAME, None)
        return env
