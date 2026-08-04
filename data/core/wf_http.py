"""core/wf_http.py - a small HTTP helper for Digital Extremes' public endpoints.

Used by the DE-data refreshers (getProfileViewingData, worldState.php, Public
Export). Kept separate from core.market's client on purpose: that one carries a
warframe.market JWT, a WFM rate limiter and an auction-house error taxonomy -
none of which apply to DE's open, unauthenticated CDN. What these calls DO need,
and market didn't, is retry/backoff (the CDN returns the odd 502/timeout under
load) and honouring Cache-Control so a refresher can back off politely instead
of hammering a value that hasn't changed.

One shared requests.Session pools connections across every DE call. Every
request carries the same honest User-Agent the WFM client uses (identify your
client), reused from core.session so there is one definition, not a fourth copy.

Read-only by nature: only GET is exposed. Nothing here writes anywhere.
"""

from __future__ import annotations

import time
from typing import Any, Callable

import requests

from core.session import USER_AGENT

# DE's CDN is plain HTTP GET with no auth; a browserish UA + JSON Accept is all
# it wants. Platform/language mirror the WFM client's honesty, harmless here.
_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "application/json",
}

# Retry only the failures a retry can fix: transient 5xx and network/timeout
# errors. A 404 (wrong id, private profile) is final and returned to the caller.
_RETRY_STATUS = frozenset({500, 502, 503, 504})
_DEFAULT_TIMEOUT = 20.0
_DEFAULT_RETRIES = 3
_BACKOFF_BASE = 0.5          # 0.5s, 1s, 2s - short; the UI reads cache meanwhile


class WFHttpError(Exception):
    """A DE request failed after retries; .args[0] is a printable reason and
    .status is the last HTTP status (None for a network/timeout failure)."""

    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


_session: requests.Session | None = None


def _sess() -> requests.Session:
    """The shared connection pool, built lazily so importing this module costs
    nothing until the first real request."""
    global _session
    if _session is None:
        s = requests.Session()
        s.headers.update(_HEADERS)
        _session = s
    return _session


def get(url: str, *, timeout: float = _DEFAULT_TIMEOUT,
        retries: int = _DEFAULT_RETRIES,
        _sleep: Callable[[float], None] = time.sleep) -> requests.Response:
    """GET `url` with retry/backoff on transient failures. Returns the Response
    on any final status (including 4xx) so the caller can branch on .status_code;
    raises WFHttpError only when every attempt was a retryable failure.

    `_sleep` is injectable so tests exercise the backoff path without waiting."""
    last_status: int | None = None
    last_reason = "request failed"
    for attempt in range(retries + 1):
        try:
            resp = _sess().get(url, timeout=timeout)
        except requests.RequestException as exc:
            last_status, last_reason = None, str(exc) or exc.__class__.__name__
        else:
            if resp.status_code not in _RETRY_STATUS:
                return resp            # final (2xx/3xx/4xx) - caller decides
            last_status = resp.status_code
            last_reason = f"HTTP {resp.status_code}"
        if attempt < retries:
            _sleep(_BACKOFF_BASE * (2 ** attempt))
    raise WFHttpError(f"{url}: {last_reason}", status=last_status)


def get_json(url: str, **kw: Any) -> Any:
    """GET and parse JSON. Raises WFHttpError on a non-200 or non-JSON body -
    a refresher treats that as 'no fresh data' and keeps the cached value."""
    resp = get(url, **kw)
    if resp.status_code != 200:
        raise WFHttpError(f"{url}: HTTP {resp.status_code}",
                          status=resp.status_code)
    try:
        return resp.json()
    except ValueError as exc:
        raise WFHttpError(f"{url}: response was not JSON ({exc})",
                          status=resp.status_code) from exc


def get_bytes(url: str, **kw: Any) -> bytes:
    """GET raw bytes (for the LZMA Public Export index/manifests). Raises
    WFHttpError on a non-200."""
    resp = get(url, **kw)
    if resp.status_code != 200:
        raise WFHttpError(f"{url}: HTTP {resp.status_code}",
                          status=resp.status_code)
    return resp.content


def cache_max_age(resp: requests.Response) -> int | None:
    """The `max-age` from a response's Cache-Control, in seconds, or None if
    absent/unparseable. A refresher uses this to avoid re-fetching a value the
    server says is still fresh (browse.wf's etiquette for the profile CDN)."""
    cc = resp.headers.get("Cache-Control", "")
    for part in cc.split(","):
        part = part.strip().lower()
        if part.startswith("max-age="):
            try:
                return int(part[len("max-age="):])
            except ValueError:
                return None
    return None
