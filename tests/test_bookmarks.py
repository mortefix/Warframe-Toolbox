"""Saved-link rules for the web tabs - core.bookmarks, no widgets.

The interesting one is `normalize`. A toggle that reads as "not bookmarked"
on the very page you just saved feels broken rather than wrong, and the way
that happens is a trailing slash or a fragment the browser appended after you
clicked.
"""
import sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "app"))

from core import bookmarks as bm

fails = []


def check(name, got, want=True):
    ok = got == want
    if not ok:
        fails.append(f"{name}: got {got!r}, want {want!r}")
    print(f"  {'ok  ' if ok else 'FAIL'} {name}")


WIKI = "https://wiki.warframe.com/w/Rhino_Prime"

print("one page is one bookmark, however you arrived at it")
for variant, why in ((WIKI + "/", "trailing slash"),
                     (WIKI + "#Abilities", "fragment"),
                     (WIKI + "/#Abilities", "both"),
                     ("https://WIKI.warframe.com/w/Rhino_Prime", "host case"),
                     ("  " + WIKI + "  ", "surrounding space")):
    check(f"{why} normalises to the same key",
          bm.normalize(variant), bm.normalize(WIKI))

print("\nbut a different page is a different bookmark")
check("a different article", bm.normalize(WIKI) ==
      bm.normalize("https://wiki.warframe.com/w/Ash_Prime"), False)
# a query string CAN change what you see, so it is part of the identity
check("a query string is kept", bm.normalize(WIKI) ==
      bm.normalize(WIKI + "?oldid=42"), False)

print("\nadd / remove / toggle")
data = {}
data = bm.add(data, "web_wiki", WIKI, "Rhino Prime")
check("it is saved", bm.is_bookmarked(data, "web_wiki", WIKI))
check("and recognised through a fragment",
      bm.is_bookmarked(data, "web_wiki", WIKI + "#Abilities"))
data = bm.add(data, "web_wiki", WIKI, "Rhino Prime (again)")
check("saving twice does not duplicate it",
      len(bm.for_app(data, "web_wiki")), 1)
check("the newer title wins",
      bm.for_app(data, "web_wiki")[0]["title"], "Rhino Prime (again)")

data = bm.add(data, "web_wiki", "https://wiki.warframe.com/w/Ash_Prime",
              "Ash Prime")
# newest first: you are far likelier to want what you just saved
check("the newest is first",
      [e["title"] for e in bm.for_app(data, "web_wiki")],
      ["Ash Prime", "Rhino Prime (again)"])

data = bm.toggle(data, "web_wiki", WIKI + "/", "ignored")
check("toggling an existing one through a slash variant removes it",
      bm.is_bookmarked(data, "web_wiki", WIKI), False)
check("and leaves the other alone", len(bm.for_app(data, "web_wiki")), 1)
data = bm.toggle(data, "web_wiki", WIKI, "Rhino Prime")
check("toggling again puts it back", bm.is_bookmarked(data, "web_wiki", WIKI))

print("\nbookmarks are scoped PER WEB APP")
data = bm.add(data, "web_builds", "https://overframe.gg/builds/", "Top Builds")
check("the wiki list is unchanged", len(bm.for_app(data, "web_wiki")), 2)
check("overframe has its own", len(bm.for_app(data, "web_builds")), 1)
check("a wiki url is not bookmarked under overframe",
      bm.is_bookmarked(data, "web_builds", WIKI), False)
check("an app with nothing saved returns an empty list, not an error",
      bm.for_app(data, "web_nosuchapp"), [])

print("\nthe callers get COPIES, so a stale reference cannot mutate the store")
before = bm.for_app(data, "web_wiki")
before.append({"url": "x", "title": "y"})
check("appending to the returned list does not change the data",
      len(bm.for_app(data, "web_wiki")), 2)
after = bm.add(data, "web_wiki", "https://wiki.warframe.com/w/Volt", "Volt")
check("add returns a new dict and leaves the old one alone",
      (len(bm.for_app(data, "web_wiki")), len(bm.for_app(after, "web_wiki"))),
      (2, 3))

print("\nclearing is scoped, and counted")
many = {}
for i in range(3):
    many = bm.add(many, "web_wiki", f"https://wiki.warframe.com/w/A{i}", f"A{i}")
many = bm.add(many, "web_builds", "https://overframe.gg/x", "X")
check("counts one app", bm.count(many, "web_wiki"), 3)
check("counts everything", bm.count(many), 4)
check("an app with nothing counts zero", bm.count(many, "web_nosuchapp"), 0)

cleared = bm.clear_app(many, "web_wiki")
check("clearing one app empties it", bm.count(cleared, "web_wiki"), 0)
check("and leaves the others alone", bm.count(cleared, "web_builds"), 1)
# the key is dropped rather than left as an empty list, so a saved file
# carries no record of an app you have never bookmarked anything for
check("the emptied key is gone, not left as []",
      "web_wiki" in cleared, False)
check("the original dict is untouched", bm.count(many, "web_wiki"), 3)
check("clearing an app with nothing saved is a no-op",
      bm.clear_app(cleared, "web_nosuchapp"), cleared)
check("clear_all empties everything", bm.count(bm.clear_all()), 0)

print("\nrows always read as something")
check("a title is used when there is one",
      bm.label({"url": WIKI, "title": "Rhino Prime"}), "Rhino Prime")
# saved before the title loaded: fall back to the slug rather than a blank row
check("a missing title falls back to the page name",
      bm.label({"url": WIKI, "title": ""}), "Rhino Prime")
check("and an empty path falls back to the url",
      bm.label({"url": "https://overframe.gg/", "title": ""}),
      "https://overframe.gg/")

print("\na missing or corrupt file is empty, never an exception")
real = bm.BOOKMARKS_PATH
bm.BOOKMARKS_PATH = Path(__file__).parent / "__no_such_file.json"
check("missing file", bm.load(), {})
tmp = Path(__file__).parent / "__corrupt.json"
tmp.write_text("{not json at all")
bm.BOOKMARKS_PATH = tmp
check("corrupt file", bm.load(), {})
tmp.write_text('["a list, not an object"]')
check("wrong shape", bm.load(), {})
tmp.write_text('{"web_wiki": [{"title": "no url"}, {"url": "ok"}]}')
check("entries without a url are dropped",
      bm.load(), {"web_wiki": [{"url": "ok"}]})
tmp.unlink()
bm.BOOKMARKS_PATH = real

print()
if fails:
    print(f"{len(fails)} FAILURES:")
    for f in fails:
        print("   ", f)
    sys.exit(1)
print("ALL BOOKMARK CHECKS PASSED")
