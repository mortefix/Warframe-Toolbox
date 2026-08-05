"""core.updater decision rules + update flow, all against a FAKE runner -
no network, no real git, no real pip ever runs in this file."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "app"))

from core import updater
from core import version as core_version

fails = []


def check(name, got, want=True):
    ok = got == want
    if not ok:
        fails.append(f"{name}: got {got!r}, want {want!r}")
    print(f"  {'ok  ' if ok else 'FAIL'} {name}")


class FakeRun:
    """Scripted runner: maps the first two words after the binary to a
    (rc, out) reply, and records every call for assertions."""
    def __init__(self, replies):
        self.replies = replies
        self.calls = []

    def __call__(self, cmd, timeout=60):
        self.calls.append(cmd)
        key = " ".join(cmd[1:3]) if len(cmd) > 2 else " ".join(cmd[1:])
        return self.replies.get(key, (0, ""))


GIT = "git"          # the fake never executes anything, any string works
ON = {"check_updates": True}
OFF = {"check_updates": False}

CLEAN = {
    "rev-parse --abbrev-ref": (0, "main\n"),
    "status --porcelain": (0, ""),
}

print("should_check")
check("toggle off -> False",
      updater.should_check(OFF, run=FakeRun(CLEAN), git=GIT), False)
check("clean main + toggle on -> True",
      updater.should_check(ON, run=FakeRun(CLEAN), git=GIT), True)
check("no git found -> False",
      updater.should_check(ON, run=FakeRun(CLEAN), git=""), False)
branchy = dict(CLEAN)
branchy["rev-parse --abbrev-ref"] = (0, "feature/x\n")
check("non-main branch -> False",
      updater.should_check(ON, run=FakeRun(branchy), git=GIT), False)
dirty = dict(CLEAN)
dirty["status --porcelain"] = (0, " M app/core/x.py\n")
check("dirty tree -> False",
      updater.should_check(ON, run=FakeRun(dirty), git=GIT), False)

print("\ncheck_and_update")
current = dict(CLEAN)
current["fetch --quiet"] = (0, "")
current["rev-list --count"] = (0, "0\n")
r = updater.check_and_update(ON, run=FakeRun(current))
check("up to date: checked, not updated",
      (r.checked, r.updated, r.error), (True, False, None))

behind = dict(current)
behind["rev-list --count"] = (0, "2\n")
behind["pull --ff-only"] = (0, "Updating abc..def\n")
fake = FakeRun(behind)
r = updater.check_and_update(ON, run=fake)
check("behind: updated", (r.checked, r.updated, r.error), (True, True, None))
check("behind: pull was actually invoked",
      any(c[1:3] == ["pull", "--ff-only"] for c in fake.calls))
check("behind: reports the on-disk version",
      r.new_version, core_version.__version__)

failing = dict(current)
failing["fetch --quiet"] = (1, "fatal: could not read from remote\n")
r = updater.check_and_update(ON, run=FakeRun(failing))
check("fetch failure: error result, no raise",
      (r.checked, r.updated, r.error is not None), (True, False, True))

toggled_off = updater.check_and_update(OFF, run=FakeRun(current))
check("toggle off: never even checked",
      (toggled_off.checked, toggled_off.updated), (False, False))

print("\nsettings default")
from core import config
check("check_updates defaults ON", config.DEFAULTS.get("check_updates"), True)

print("\npending_version")
check("pending is None when file matches running version",
      updater.pending_version(), None)

if fails:
    print(f"\n{len(fails)} FAILURES:")
    for f in fails:
        print(" -", f)
    raise SystemExit(1)
print("\nall updater checks passed")
