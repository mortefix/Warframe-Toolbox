"""core.collect - the startup background refresh coordinator. Each source is
monkeypatched (this file runs as its own process, so the patches are isolated);
no network, no store writes."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "data"))
from core import collect, ee_events, public_export, store, wf_profile, worldstate

fails = []


def check(name, got, want):
    ok = got == want
    if not ok:
        fails.append(f"{name}: got {got!r}, want {want!r}")
    print(f"  {'ok  ' if ok else 'FAIL'} {name}")


print("all sources run, results reported")
calls = []
wf_profile.refresh_if_stale = lambda **k: calls.append("profile") or {"x": 1}
worldstate.refresh_if_stale = lambda **k: calls.append("world") or {"y": 1}
ee_events.tail = lambda *a, **k: calls.append("tail") or [{"type": "login"}]
store.age = lambda ns, **k: None                      # forces export sync
public_export.sync = lambda **k: calls.append("export") or {"index": True}

res = collect.run_startup_refresh()
check("every source ran", sorted(calls),
      ["export", "profile", "tail", "world"])
check("profile true", res["profile"], True)
check("worldstate true", res["worldstate"], True)
check("ee_events true", res["ee_events"], True)
check("export true", res["export"], True)

print("\na failing source is swallowed, others still run")
def boom(**k):
    raise RuntimeError("down")
worldstate.refresh_if_stale = boom
res2 = collect.run_startup_refresh()
check("worldstate error -> False", res2["worldstate"], False)
check("profile still ran", res2["profile"], True)

print("\nexport skips when checked recently")
store.age = lambda ns, **k: 100                       # < EXPORT_MIN_INTERVAL
called = []
public_export.sync = lambda **k: called.append(1) or {"index": True}
res3 = collect.run_startup_refresh()
check("export skipped", res3["export"], False)
check("sync not called", called, [])

if fails:
    print("\n" + "\n".join(fails))
    raise SystemExit(1)
print("\nall collect checks passed")
