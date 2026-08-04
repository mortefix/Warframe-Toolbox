"""Run every test in this folder. `python tests/run_all.py` from the repo root.

No pytest dependency on purpose - the app ships with nothing but the stdlib
plus pywebview, and a test suite that needs an install is a test suite that
stops being run. Each test file is a plain script that exits non-zero on
failure and prints one line per check.

The offscreen smoke test that drives the real Tk app is NOT here; it needs a
display and takes ~30s, so it stays a separate manual step.
"""

import os
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent

# Point every spawned test at a throwaway data root: any write a test forgot
# to monkeypatch lands in a temp dir, never in the real per-machine data.
# setdefault so an outer runner (CI, a debugging session) can still override.
os.environ.setdefault("WFTOOLBOX_DATA",
                      tempfile.mkdtemp(prefix="wftb_test_data_"))


def main() -> int:
    tests = sorted(p for p in HERE.glob("test_*.py"))
    if not tests:
        print("no tests found")
        return 1
    width = max(len(p.name) for p in tests)
    failed = []
    for path in tests:
        # A per-file cap so one hung test can never freeze the whole run.
        # A Qt test that opens a modal with no one to click it blocks on a
        # nested event loop forever; capture_output means it does so in total
        # silence. 180s is far above the slowest real file (the web tests, a
        # few seconds), so a timeout means genuinely stuck, not merely slow.
        try:
            r = subprocess.run([sys.executable, str(path)],
                               capture_output=True, text=True, timeout=180)
            ok = r.returncode == 0
            out, err = r.stdout, r.stderr
        except subprocess.TimeoutExpired as e:
            ok = False
            out = e.stdout or ""
            err = (e.stderr or "") + "\n*** TIMED OUT after 180s - a test hung " \
                  "(a modal with no one to dismiss it?). Marked FAIL. ***"
        print(f"{path.name.ljust(width)}  {'PASS' if ok else 'FAIL'}")
        if not ok:
            failed.append((path.name, out, err))

    if failed:
        for name, out, err in failed:
            print(f"\n{'=' * 60}\n{name}\n{'=' * 60}")
            print(out)
            if err:
                print(err)
        print(f"\n{len(failed)} of {len(tests)} test files FAILED")
        return 1
    print(f"\nall {len(tests)} test files passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
