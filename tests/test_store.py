"""core.store - the local cache-of-record. Redirects the store dir to a temp
folder so the real .wf_data/ is never touched."""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "data"))
from core import store

fails = []


def check(name, got, want):
    ok = got == want
    if not ok:
        fails.append(f"{name}: got {got!r}, want {want!r}")
    print(f"  {'ok  ' if ok else 'FAIL'} {name}")


with tempfile.TemporaryDirectory() as d:
    store.WF_DATA_DIR = Path(d)

    print("absent namespace")
    check("read None", store.read("profile"), None)
    check("has False", store.has("profile"), False)
    check("age None", store.age("profile"), None)
    check("envelope None", store.envelope("profile"), None)

    print("\nwrite / read back")
    store.write("profile", {"PlayerLevel": 17}, source_mtime=123.0)
    check("read payload", store.read("profile"), {"PlayerLevel": 17})
    check("has True", store.has("profile"), True)
    check("source_mtime kept", store.source_mtime("profile"), 123.0)
    w = store.written_at("profile")
    check("written_at set", isinstance(w, float), True)
    check("age from injected now", store.age("profile", now=w + 5), 5.0)

    print("\ngrouped namespace -> subfolder")
    store.write("export/Warframes", [1, 2, 3])
    check("grouped read", store.read("export/Warframes"), [1, 2, 3])
    check("nested file on disk",
          (Path(d) / "export" / "Warframes.json").exists(), True)

    print("\nself-healing + safety")
    (Path(d) / "profile.json").write_text("{ not json", encoding="utf-8")
    check("corrupt reads as None", store.read("profile"), None)
    rejected = False
    try:
        store.write("../evil", {"x": 1})
    except ValueError:
        rejected = True
    check("rejects .. escape", rejected, True)
    abs_rejected = False
    try:
        store.write("/etc/passwd", {"x": 1})
    except ValueError:
        abs_rejected = True
    check("rejects absolute", abs_rejected, True)

if fails:
    print("\n" + "\n".join(fails))
    raise SystemExit(1)
print("\nall store checks passed")
