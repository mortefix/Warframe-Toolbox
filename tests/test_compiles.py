"""Every .py in the app parses.

The behavioural suites import the modules they exercise, so a syntax error in
anything they touch surfaces at once. But the standalone tools under
`app/tools/` are launched as separate processes and imported by nothing here,
so a broken one is invisible until a user opens it - which is exactly how a
mangled string literal (`""Warframe Toolbox.pyw"`) sat in api_check.py while
all 16 other files stayed green. Compiling the whole tree closes that hole:
it is fast, needs no display, and catches the one class of bug - "does not
even parse" - that behaviour tests structurally cannot reach for code they
never import.
"""

import sys
from pathlib import Path
from py_compile import PyCompileError, compile as _compile

ROOT = Path(__file__).resolve().parent.parent
# The whole shipped surface: the app package and the launcher beside it.
TARGETS = sorted(
    list((ROOT / "app").rglob("*.py"))
    + list(ROOT.glob("*.pyw"))
    + list(ROOT.glob("*.py"))
)

fails = []
for path in TARGETS:
    try:
        _compile(str(path), doraise=True)
        print(f"  ok   {path.relative_to(ROOT)}")
    except PyCompileError as e:
        fails.append((path, e))
        print(f"  FAIL {path.relative_to(ROOT)}")

print()
if fails:
    print(f"{len(fails)} FILE(S) DO NOT COMPILE:")
    for path, e in fails:
        print(f"\n{'=' * 60}\n{path.relative_to(ROOT)}\n{'=' * 60}\n{e}")
    sys.exit(1)
print(f"ALL {len(TARGETS)} PYTHON FILES COMPILE")
