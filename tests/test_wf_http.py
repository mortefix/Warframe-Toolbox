"""core.wf_http - DE endpoint helper. No network: a fake requests.Session is
injected and time.sleep is captured, so retry/backoff is exercised instantly."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "data"))
import requests
from core import wf_http

fails = []


def check(name, got, want):
    ok = got == want
    if not ok:
        fails.append(f"{name}: got {got!r}, want {want!r}")
    print(f"  {'ok  ' if ok else 'FAIL'} {name}")


_NO_JSON = object()


class Resp:
    def __init__(self, status=200, json_data=None, content=b"", headers=None):
        self.status_code = status
        self._json = json_data
        self.content = content
        self.headers = headers or {}

    def json(self):
        if self._json is _NO_JSON:
            raise ValueError("not json")
        return self._json


class FakeSession:
    """Yields a scripted sequence of Resp objects (or raises a queued
    exception) per get() call."""
    def __init__(self, script):
        self.script = list(script)

    def get(self, url, timeout=None):
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def arm(script):
    wf_http._session = FakeSession(script)
    sleeps = []
    return sleeps, (lambda s: sleeps.append(s))


URL = "https://api.warframe.com/cdn/getProfileViewingData.php?playerId=x"

print("success, no retry")
sleeps, sleep = arm([Resp(200, {"ok": 1})])
check("get_json returns body", wf_http.get_json(URL, _sleep=sleep), {"ok": 1})
check("no sleeps", sleeps, [])

print("\ntransient 500 then 200")
sleeps, sleep = arm([Resp(500), Resp(200, {"ok": 2})])
check("retried to success", wf_http.get_json(URL, _sleep=sleep), {"ok": 2})
check("slept once", len(sleeps), 1)

print("\nnetwork error then 200")
sleeps, sleep = arm([requests.ConnectionError("boom"), Resp(200, {"ok": 3})])
check("retried past net error", wf_http.get_json(URL, _sleep=sleep), {"ok": 3})
check("slept once", len(sleeps), 1)

print("\npersistent 500 -> raises after retries")
sleeps, sleep = arm([Resp(500), Resp(500), Resp(500), Resp(500)])
raised = None
try:
    wf_http.get_json(URL, _sleep=sleep)
except wf_http.WFHttpError as e:
    raised = e
check("raised WFHttpError", raised is not None, True)
check("status carried", getattr(raised, "status", None), 500)
check("slept 3 times (4 attempts)", len(sleeps), 3)

print("\n404 is final, not retried")
sleeps, sleep = arm([Resp(404)])
raised = None
try:
    wf_http.get_json(URL, _sleep=sleep)
except wf_http.WFHttpError as e:
    raised = e
check("404 raises", raised is not None, True)
check("404 status", getattr(raised, "status", None), 404)
check("no retry on 404", sleeps, [])

print("\n200 but not JSON")
sleeps, sleep = arm([Resp(200, _NO_JSON)])
raised = None
try:
    wf_http.get_json(URL, _sleep=sleep)
except wf_http.WFHttpError as e:
    raised = e
check("non-JSON raises", raised is not None, True)

print("\ncache_max_age parsing")
check("parses max-age",
      wf_http.cache_max_age(Resp(headers={"Cache-Control": "public, max-age=3600"})),
      3600)
check("absent -> None", wf_http.cache_max_age(Resp(headers={})), None)
check("malformed -> None",
      wf_http.cache_max_age(Resp(headers={"Cache-Control": "max-age=abc"})), None)

wf_http._session = None          # leave no fake session behind

if fails:
    print("\n" + "\n".join(fails))
    raise SystemExit(1)
print("\nall wf_http checks passed")
