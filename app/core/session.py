"""
core/session.py - the host's single source of truth for the warframe.market
account link.

The host application owns the credentials and the live session. Tools never
log in themselves and never see the JWT at all: every API call a tool makes
goes through the host's local gateway (core/gateway.py), which injects the
Authorization header on the way out.

Security posture:
  * The password is used for exactly one signin request and is never written
    to disk, never logged, and never passed to a tool.
  * The cached session (.wfm_session.json) holds the JWT, username, platform,
    and the login EMAIL - the email solely to prefill the sign-in form.
    Delete the file - or use Unlink in the app - to revoke the link locally.
    chmod 600 is applied best-effort; on Windows it only clears the read-only
    bit, so the real protection is the user profile's ACLs.
  * The JWT lives only in the host process; tools get a per-launch gateway
    token instead, valid only against 127.0.0.1 and only while the host runs.

The file lives in the per-machine data root (core.paths.USERDATA) - never
inside the app folder, so a copy of the app on a flash drive or in a git
push can never carry the token. The data folder's ACLs (the user profile's,
in the default location) are what protect it.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path


import requests

from core import paths
# Re-exported so the HTTP modules keep importing it from here; the actual
# string is derived in core.version (one bump updates every surface).
from core.version import USER_AGENT  # noqa: F401

SESSION_PATH = paths.USERDATA / "wfm_session.json"

API = "https://api.warframe.market"

class AuthError(Exception):
    """Login or session validation failed; .args[0] is a printable reason."""


@dataclass
class Session:
    jwt: str
    username: str
    platform: str = "pc"
    email: str = ""          # remembered only to prefill the login form

    @property
    def bearer(self) -> str:
        """warframe.market's v2 API wants 'Bearer <token>'. The signin call
        (v1) hands the token back prefixed with 'JWT '; strip that and re-wrap
        so the raw token is the single source we format from."""
        raw = self.jwt
        for prefix in ("JWT ", "Bearer "):
            if raw.startswith(prefix):
                raw = raw[len(prefix):]
                break
        return f"Bearer {raw}"

    @property
    def v1_auth(self) -> str:
        """The v1 API (the auction house) wants the signin's original
        'JWT <token>' form, not v2's 'Bearer'. Same raw token, same
        normalise-then-wrap dance as `bearer`."""
        raw = self.jwt
        for prefix in ("JWT ", "Bearer "):
            if raw.startswith(prefix):
                raw = raw[len(prefix):]
                break
        return f"JWT {raw}"


def _headers(platform: str) -> dict[str, str]:
    return {
        "User-Agent": USER_AGENT,
        "Accept": "application/json",
        "Content-Type": "application/json; charset=utf-8",
        "platform": platform,
        "language": "en",
        "crossplay": "true",
    }


# ---------------------------------------------------------------- lifecycle

def login(email: str, password: str, platform: str = "pc") -> Session:
    """One signin call. The password lives only in this frame."""
    h = _headers(platform)
    h["Authorization"] = "JWT"
    try:
        r = requests.post(
            f"{API}/v1/auth/signin",
            headers=h,
            data=json.dumps({"email": email, "password": password,
                             "auth_type": "header"}),
            timeout=20,
        )
    except requests.RequestException as exc:
        raise AuthError(f"network error: {exc}") from exc

    if not r.ok:
        raise AuthError(f"login failed ({r.status_code}): {r.text[:200]}")
    jwt = r.headers.get("Authorization")
    if not jwt:
        raise AuthError("no Authorization header returned from signin")

    # The signin body is WFM's most change-prone surface (and can be an
    # HTML interstitial). Anything unexpected must surface as AuthError -
    # a raw KeyError here would kill the login worker thread and leave the
    # dialog stuck on "Signing in…" forever.
    try:
        username = r.json()["payload"]["user"]["ingame_name"]
    except (ValueError, KeyError, TypeError) as exc:
        raise AuthError(f"unexpected signin response: {exc}") from exc
    sess = Session(jwt=jwt, username=username, platform=platform, email=email)
    save(sess)
    return sess


def validate(sess: Session) -> bool:
    """Cheap authenticated read to confirm the cached token still works.

    Uses the v2 /me endpoint. The old v1 profile endpoint was retired and now
    404s, which used to make every cached session look 'expired' and force a
    needless re-login."""
    h = _headers(sess.platform)
    h["Authorization"] = sess.bearer
    try:
        r = requests.get(f"{API}/v2/me", headers=h, timeout=20)
    except requests.RequestException:
        return False
    return r.ok


def save(sess: Session) -> None:
    """Write the session atomically: this is the single most valuable file
    the app owns, and a truncated one reads as 'no account' - silently
    unlinking you. The temp file is locked down BEFORE it holds the JWT."""
    tmp = SESSION_PATH.with_suffix(".tmp")
    payload = json.dumps({
        "jwt": sess.jwt,
        "username": sess.username,
        "platform": sess.platform,
        "email": sess.email,
    })
    tmp.touch()
    # Best-effort (never fail a good sign-in over file metadata):
    # meaningful on POSIX; on Windows this only clears the read-only bit -
    # the folder's ACLs are the real protection.
    try:
        os.chmod(tmp, 0o600)
    except OSError:
        pass
    tmp.write_text(payload)
    os.replace(tmp, SESSION_PATH)       # atomic on NTFS and POSIX
    try:
        os.chmod(SESSION_PATH, 0o600)
    except OSError:
        pass


def load() -> Session | None:
    if not SESSION_PATH.exists():
        return None
    try:
        data = json.loads(SESSION_PATH.read_text())
    except (json.JSONDecodeError, OSError):
        return None
    if not isinstance(data, dict):
        return None                 # []/null is valid JSON but .get would crash
    if not data.get("jwt") or not data.get("username"):
        return None
    return Session(jwt=data["jwt"], username=data["username"],
                   platform=data.get("platform", "pc"),
                   email=data.get("email", ""))


def logout() -> None:
    """Forget the local session. (WFM has no token-revoke endpoint; the JWT
    simply expires server-side.)"""
    SESSION_PATH.unlink(missing_ok=True)
