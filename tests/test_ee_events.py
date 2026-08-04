"""core.ee_events - the read-only EE.log event tail. Driven against a synthetic
log file (never the real EE.log); the store is redirected to a temp dir."""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "app"))
from core import ee_events, store

fails = []


def check(name, got, want):
    ok = got == want
    if not ok:
        fails.append(f"{name}: got {got!r}, want {want!r}")
    print(f"  {'ok  ' if ok else 'FAIL'} {name}")


LOG1 = (
    "0.100 Sys [Info]: Logging in as\n"
    "14.938 Sys [Info]: Logged in Dzwsin\n"
    "17.047 Net [Info]: AddSquadMember: Dzwsin, mm=ABC, squadCount=1\n"
    "17.050 Net [Info]: AddSquadMember: Friend, mm=DEF, squadCount=2\n"
    "20.000 Sys [Info]: unrelated noise that matches nothing\n"
    "99.000 Sys [Info]: Host migration in progress\n"
    "100.000 Game [Info]: OnStateStarted MissionState\n"
)


def types(evs):
    return [e["type"] for e in evs]


with tempfile.TemporaryDirectory() as d:
    store.WF_DATA_DIR = Path(d) / ".wf_data"
    log = Path(d) / "EE.log"
    log.write_text(LOG1, encoding="utf-8")

    print("first tail parses the recognised events")
    evs = ee_events.tail(path=log)
    check("event types",
          types(evs),
          ["login", "squad_join", "squad_join", "host_migration",
           "state_started"])
    check("login captured player", evs[0].get("player"), "Dzwsin")
    check("squad_join captured friend", evs[2].get("player"), "Friend")
    check("timestamp parsed", evs[0].get("t"), 14.938)
    check("latest_login accessor", ee_events.latest_login(), "Dzwsin")

    print("\nre-tail with no new bytes -> no duplicates")
    evs2 = ee_events.tail(path=log)
    check("still five events", len(evs2), 5)

    print("\nappend -> only new lines are read")
    with open(log, "a", encoding="utf-8") as fh:
        fh.write("200.000 Game [Info]: OnStateStarted SecondState\n")
    evs3 = ee_events.tail(path=log)
    check("six events now", len(evs3), 6)
    check("last is the new state", evs3[-1]["type"], "state_started")

    print("\nring cap trims oldest")
    saved_cap = ee_events.MAX_EVENTS
    ee_events.MAX_EVENTS = 3
    with open(log, "a", encoding="utf-8") as fh:
        fh.write("300.000 Game [Info]: OnStateStarted ThirdState\n")
    evs4 = ee_events.tail(path=log)
    check("capped to three", len(evs4), 3)
    ee_events.MAX_EVENTS = saved_cap

    print("\nrotation (log shrinks) resets offset + events")
    log.write_text("5.000 Sys [Info]: Logged in NewSession\n", encoding="utf-8")
    evs5 = ee_events.tail(path=log)
    check("only the new session's event", types(evs5), ["login"])
    check("new session player", evs5[0].get("player"), "NewSession")

    print("\nmissing log keeps cached events")
    log.unlink()
    evs6 = ee_events.tail(path=log)
    check("cache survives a missing log", types(evs6), ["login"])

if fails:
    print("\n" + "\n".join(fails))
    raise SystemExit(1)
print("\nall ee_events checks passed")
