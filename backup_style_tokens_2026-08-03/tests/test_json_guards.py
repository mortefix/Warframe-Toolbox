"""Loaders must survive a valid-JSON-but-wrong-type file (audit finding).

A user can open these stores via Settings > Data and hand-edit them. A stray
'[]' or 'null' is VALID JSON, so it sails past the JSONDecodeError guard and
used to crash on .get()/iteration - taking out the screen or app startup. Each
loader must instead fall back to its default. We repoint each loader's PATH
constant at a temp file so the real user data is never touched.
"""
import json
import shutil
import sys
import tempfile
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "data"))
from core import atomic, market, session, wf_local

fails = []


def check(name, got, want=True):
    ok = got == want
    if not ok:
        fails.append(f"{name}: got {got!r}, want {want!r}")
    print(f"  {'ok  ' if ok else 'FAIL'} {name}")


tmp = Path(tempfile.mkdtemp(prefix="wftb_guard_"))


def write(p: Path, text: str) -> None:
    p.write_text(text, encoding="utf-8")


print("market.load_prefs falls back for a wrong-type file")
market.PREFS_PATH = tmp / "prefs.json"
for bad in ["[]", "null", "123", '"a string"']:
    write(market.PREFS_PATH, bad)
    r = market.load_prefs()
    check(f"{bad} -> dict of defaults",
          isinstance(r, dict) and "global_offset" in r and "floors" in r)

print("\nmarket.load_watchlist falls back for a wrong-type file")
market.WATCHLIST_PATH = tmp / "wl.json"
for bad in ["{}", "null", "123"]:
    write(market.WATCHLIST_PATH, bad)
    check(f"{bad} -> []", market.load_watchlist(), [])
write(market.WATCHLIST_PATH, '["a", "b", 5]')
check("a real list keeps only its strings", market.load_watchlist(), ["a", "b"])

print("\nmarket.load_contract_watchlist falls back for a wrong-type file")
market.CONTRACT_WATCHLIST_PATH = tmp / "cwl.json"
for bad in ["{}", "null", "123"]:
    write(market.CONTRACT_WATCHLIST_PATH, bad)
    check(f"{bad} -> []", market.load_contract_watchlist(), [])

print("\nwf_local.load_prefs falls back for a wrong-type file")
wf_local.PREFS_PATH = tmp / "wfl.json"
for bad in ["[]", "null", "123"]:
    write(wf_local.PREFS_PATH, bad)
    r = wf_local.load_prefs()
    check(f"{bad} -> dict with defaults",
          isinstance(r, dict) and "install_dir" in r)

print("\nsession.load returns None for a wrong-type or incomplete file")
session.SESSION_PATH = tmp / "sess.json"
for bad in ["[]", "null", "123", '{"jwt": "x"}']:   # last: username missing
    write(session.SESSION_PATH, bad)
    check(f"{bad} -> None", session.load(), None)
write(session.SESSION_PATH, json.dumps({"jwt": "j", "username": "u"}))
loaded = session.load()
check("a complete file loads", loaded is not None and loaded.username == "u")

print("\natomic.write_json round-trips and leaves no temp behind")
target = tmp / "atomic.json"
atomic.write_json(target, {"x": 1, "y": [2, 3]})
check("round-trips", json.loads(target.read_text()), {"x": 1, "y": [2, 3]})
check("no .tmp left after a successful write",
      sorted(p.name for p in tmp.glob("atomic.json.*.tmp")), [])

print()
shutil.rmtree(tmp, ignore_errors=True)
if fails:
    print(f"{len(fails)} FAILURES:")
    for f in fails:
        print("   ", f)
    sys.exit(1)
print("ALL JSON-GUARD CHECKS PASSED")
