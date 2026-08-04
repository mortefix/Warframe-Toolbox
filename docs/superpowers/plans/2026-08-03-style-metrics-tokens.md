# Style Metrics Tokens — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the app a CSS-equivalent single source of truth for every *reused* dimension (border widths, button/control sizes, scrollbar metrics, radii, weights, dialog widths), so future apps stay cohesive and the palette becomes swappable for future theming.

**Architecture:** Extend `data/core/theme.py` with a toolkit-free `metrics` section (peer to the existing palette / spacing / typography sections). `data/ui/qss.py` and the per-widget sizing code reference those tokens instead of literals. Item-card buttons move from runtime `sizeHint` derivation to a CSS-style cascade of tokens (shared height → icon-width class → per-button width override) with **zero visual change** (values measured from the current render and locked). Enforced by new assertions in `tests/test_style_guide.py`.

**Tech Stack:** Python 3.11, PySide6 (Qt), plain-script tests run via `python tests/run_all.py`.

## Global Constraints

- **No version control.** The repo is not a git repository. Ignore the skill's `git commit` steps — the per-task checkpoint is instead: **`python tests/run_all.py` is green** (currently 32 files), plus the screenshot checks where noted. A full backup already exists at `backup_style_tokens_2026-08-03/` (project root) for revert/diff.
- **`data/core/theme.py` must not import any toolkit** (no PySide6/tkinter). Metrics are plain ints/strings, like `SP_*`.
- **No raw `#hex` in `data/ui/`** (existing rule). This plan adds the analogous rule for the tokenized dimensions.
- **Real-DPI verification only.** Verify visuals by grabbing the REAL app on the native `windows` platform (NOT `offscreen`, which is DPR-1 + font-substituted and misleading).
- **Cross-scale method (validated on this machine):** `QT_SCALE_FACTOR` is a MULTIPLIER off the native DPR (this machine = 3.0), so to render at a target DPR use **`QT_SCALE_FACTOR = target / 3`**: `0.3333`→1×, `0.6667`→2×, `1.0`→3×. This yields faithful logical-96, real-font renders (verified: DPR 1.00/2.00/3.00). The window must be un-maximized (`setWindowState(Qt.WindowNoState)`) before `resize()`, and the footprint must fit at 3× — use **1280×680** (→ 1280×680 / 2560×1360 / 3840×2040). NOT OS display settings (a true OS DPI change needs a sign-out that would sever the remote session). `tools/shot.py` implements this.
- **Baseline-first (Task 0):** capture the full cross-scale baseline BEFORE any edit. Every later visual check diffs against the SAME-scale baseline — a difference already present in the baseline is a pre-existing rendering quirk, NOT a regression from this work.
- **Test runner:** whole suite `python tests/run_all.py`; a single file `python tests/<name>.py` (prints PASS/FAIL, exits non-zero on fail). Not pytest.
- **Zero visual change except one:** the ONLY intended visual change in the whole plan is the web-tab buttons (24/30 → 28). Everything else — including the item cards — must render identically.

---

## File map

- **Modify `data/core/theme.py`** — add the `metrics` token section. One responsibility: design tokens as data.
- **Modify `data/ui/qss.py`** — interpolate border/scrollbar/radius/weight tokens.
- **Modify per-widget sizing sites** — `data/ui/home.py`, `listings.py`, `market.py`, `settings.py`, `vosfor.py`, `web.py`, `dialogs.py`, `runner.py`, `widgets.py` — re-point literals at tokens.
- **Modify `tests/test_style_guide.py`** — add the "dimension discipline" checks.
- **Create `tools/shot.py`** — a reusable cross-DPI screenshot harness for verification.
- **Create `tests/test_metrics.py`** — asserts the token section exists with expected names/values.

---

## Task 0: Baseline harness + full pre-change cross-scale baseline

**Files:**
- Create: `tools/shot.py`
- Create: `backup_style_tokens_2026-08-03/baseline/` (the reference images)

**Interfaces:**
- Produces: `tools/shot.py`, run as `QT_SCALE_FACTOR=<n> python tools/shot.py <page> <w> <h> <out.png>`.

Purpose: a frame of reference. These images are captured with ZERO code changes, so any later
difference at the same scale is attributable to this work — and any imperfection visible HERE is
a pre-existing design/render quirk, not something this plan introduced.

- [ ] **Step 1: Create `tools/shot.py`** (scale comes from `QT_SCALE_FACTOR`, set before `QApplication`):

```python
"""Grab the real app at a forced per-app scale + window size, for cross-DPI
verification. OS display settings are never touched.
Usage: QT_SCALE_FACTOR=2 python tools/shot.py market 1280 720 out.png
"""
import os, sys
os.environ.pop("QT_QPA_PLATFORM", None)          # native platform, real fonts
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "data"))

page, w, h, out = sys.argv[1], int(sys.argv[2]), int(sys.argv[3]), sys.argv[4]
from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import QApplication
app = QApplication(sys.argv[:1])
from ui import qss
app.setStyleSheet(qss.build(set(QFontDatabase.families())))
from ui.app import MainWindow
win = MainWindow(); win.show_configured(); win.resize(w, h); win.navigate(page)
for _ in range(30):
    app.processEvents()
win.grab().save(out)
print(f"saved {out}  scale={os.environ.get('QT_SCALE_FACTOR','1')} {w}x{h} page={page}")
```

- [ ] **Step 2: Capture the baseline matrix** (before ANY token work). Scales 1×/2×/3× × the key pages, into the baseline dir:

```bash
BASE="backup_style_tokens_2026-08-03/baseline"; mkdir -p "$BASE"
for SF in 1x:0.3333 2x:0.6667 3x:1.0; do L=${SF%:*}; F=${SF#*:}; \
  for P in home market listings vosfor settings web_wiki; do \
    QT_SCALE_FACTOR=$F python tools/shot.py $P 1280 680 "$BASE/${P}_${L}.png"; \
done; done
```
(Done: DPR verified 1.00/2.00/3.00; grabs 1280×680 / 2560×1360 / 3840×2040. Note: the listings
page shows "loading your orders…" with no cards — no session — so the item card is verified via an
isolated harness in Task 6, not this page.)

- [ ] **Step 3: Post a representative baseline set to the user.** `SendUserFile` at least the 3×
  row (the user's real DPI) for each page, plus any scale that already looks off, with a caption
  noting these are the pre-change reference. Invite comment. (This is also where pre-existing
  scale imperfections get named, so they aren't later mistaken for regressions.)

- [ ] **Step 4: Checkpoint** — `python tests/run_all.py` still green (no code changed; `tools/` is outside `data/ui/` and `tests/`, so nothing scans it).

---

## Task 1: Add the `metrics` token section to `theme.py`

**Files:**
- Modify: `data/core/theme.py` (add a `metrics` section after the spacing scale, ~line 53)
- Test: `tests/test_metrics.py` (create)

**Interfaces:**
- Produces: `theme.BORDER_W:int`, `SP_XXS:int`, `SCROLLBAR_THICK:int`, `SCROLLBAR_HANDLE_MIN:int`, `RADIUS_HANDLE:int`, `ICON_BTN:int`, `REMOVE_BTN:tuple[int,int]`, `DISCLOSURE_W:int`, `TABLE_ROW_H:int`, `DIALOG_MIN_W:int`, `WEIGHT_BOLD:str`, `WEIGHT_SEMI:int`. (`CONTROL_H` is added later, in Task 6, after measurement.)

- [ ] **Step 1: Write the failing test** — `tests/test_metrics.py`

```python
"""The metrics token section: every reused dimension has one definition."""
import sys
from pathlib import Path
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "data"))
from core import theme as t

fails = []
def check(name, got, want=True):
    ok = got == want
    if not ok:
        fails.append(f"{name}: got {got!r}, want {want!r}")
    print(f"  {'ok  ' if ok else 'FAIL'} {name}")

print("metrics tokens exist with expected types/values")
check("BORDER_W", t.BORDER_W, 1)
check("SP_XXS", t.SP_XXS, 2)
check("SCROLLBAR_THICK", t.SCROLLBAR_THICK, 12)
check("SCROLLBAR_HANDLE_MIN", t.SCROLLBAR_HANDLE_MIN, 30)
check("RADIUS_HANDLE", t.RADIUS_HANDLE, 3)
check("ICON_BTN", t.ICON_BTN, 28)
check("REMOVE_BTN", t.REMOVE_BTN, (24, 22))
check("DISCLOSURE_W", t.DISCLOSURE_W, 20)
check("TABLE_ROW_H", t.TABLE_ROW_H, 26)
check("DIALOG_MIN_W", t.DIALOG_MIN_W, 460)
check("WEIGHT_BOLD", t.WEIGHT_BOLD, "bold")
check("WEIGHT_SEMI", t.WEIGHT_SEMI, 600)

if fails:
    print("\n" + "\n".join(fails)); raise SystemExit(1)
print("\nall metrics checks passed")
```

- [ ] **Step 2: Run it, expect FAIL** — `python tests/test_metrics.py` → `AttributeError: module 'core.theme' has no attribute 'BORDER_W'`.

- [ ] **Step 3: Add the metrics section** to `data/core/theme.py`, immediately after the spacing scale block (after `SP_SM = 4`, ~line 52):

```python
# ---- metrics (dimensions; theme-INVARIANT - a light theme keeps these) -----
# Unlike the palette, these do not change between themes. They are the reused
# sizes the app draws with; put a dimension here the moment a second widget
# needs the same value.
BORDER_W = 1                 # every 1px border / hairline
SP_XXS = 2                   # micro-gap below SP_SM (extends the spacing scale)
SCROLLBAR_THICK = 12         # scrollbar track thickness (v width / h height)
SCROLLBAR_HANDLE_MIN = 30    # scrollbar handle min extent
RADIUS_HANDLE = 3            # the ONLY non-zero corner radius (scrollbar handle)
ICON_BTN = 28                # icon-button width (visibility/wiki/trash + the
                             # contract/market/web icon buttons)
REMOVE_BTN = (24, 22)        # small remove/close button (w, h)
DISCLOSURE_W = 20            # disclosure-arrow column width
TABLE_ROW_H = 26             # market table row height
DIALOG_MIN_W = 460           # every dialog's minimum width
WEIGHT_BOLD = "bold"         # qss font-weight: the listing badge label
WEIGHT_SEMI = 600            # qss font-weight: the money button
```

- [ ] **Step 4: Run it, expect PASS** — `python tests/test_metrics.py` → `all metrics checks passed`.

- [ ] **Step 5: Checkpoint** — `python tests/run_all.py` → all files pass (now 33). No visual change (nothing consumes the tokens yet).

---

## Task 2: Route `qss.py` borders, scrollbar, radius, and weights through tokens

**Files:**
- Modify: `data/ui/qss.py` (border/scrollbar/radius/weight literals)
- Modify: `tests/test_style_guide.py` (add "dimension discipline" checks)

**Interfaces:**
- Consumes: the Task 1 tokens (`t.BORDER_W`, `t.SCROLLBAR_THICK`, `t.SCROLLBAR_HANDLE_MIN`, `t.RADIUS_HANDLE`, `t.WEIGHT_BOLD`, `t.WEIGHT_SEMI`).

- [ ] **Step 1: Write the failing assertions** — append to `tests/test_style_guide.py` before the final `if fails:` block:

```python
print("\ndimension discipline (metrics tokens)")
qss = text.get("qss.py", "")
# Border WIDTHS come from t.BORDER_W, never a raw "Npx solid".
raw_border = re.findall(r"border(?:-\w+)?:\s*\d+px", qss)
check("qss has no raw border-width px (use t.BORDER_W)", raw_border, [])
# Scrollbar metrics + handle radius come from tokens, not raw 12/30/3.
check("qss scrollbar thickness is a token",
      "width: 12px" not in qss and "height: 12px" not in qss)
check("qss scrollbar handle-min is a token",
      "min-height: 30px" not in qss and "min-width: 30px" not in qss)
check("qss handle radius is a token", "border-radius: 3px" not in qss)
# Font weights come from tokens.
check("qss font-weight uses tokens",
      "font-weight: bold" not in qss and "font-weight: 600" not in qss)
```

- [ ] **Step 2: Run it, expect FAIL** — `python tests/test_style_guide.py` → the new checks FAIL (literals still present).

- [ ] **Step 3: Refactor `qss.py`.** Replace each literal with its token interpolation. Exact edits:
  - Every `border: 1px solid {t.X}` and `border-top/-bottom/... : 1px solid {t.X}` → `border: {t.BORDER_W}px solid {t.X}`.
  - The hairline/vline frames `max-height: 1px` / `max-width: 1px` → `max-height: {t.BORDER_W}px` / `max-width: {t.BORDER_W}px`.
  - `QScrollBar:vertical { width: 12px; ... }` → `width: {t.SCROLLBAR_THICK}px`.
  - `QScrollBar:horizontal { height: 12px; ... }` → `height: {t.SCROLLBAR_THICK}px`.
  - `QScrollBar::handle:vertical { min-height: 30px; border-radius: 3px; }` → `min-height: {t.SCROLLBAR_HANDLE_MIN}px; border-radius: {t.RADIUS_HANDLE}px;`.
  - `QScrollBar::handle:horizontal { min-width: 30px; border-radius: 3px; }` → `min-width: {t.SCROLLBAR_HANDLE_MIN}px; border-radius: {t.RADIUS_HANDLE}px;`.
  - `QLabel[role="badge"] { ... font-weight: bold; }` → `font-weight: {t.WEIGHT_BOLD};`.
  - `QPushButton[kind="money"] { ... font-weight: 600; }` → `font-weight: {t.WEIGHT_SEMI};`.
  - Leave `border: none`, `width: 0`, `height: 0`, and the `padding`/`margin` px values alone (paddings are mostly unique — not in scope).

- [ ] **Step 4: Run the style-guide test, expect PASS** — `python tests/test_style_guide.py` → all checks pass.

- [ ] **Step 5: Checkpoint** — `python tests/run_all.py` green. Then a quick visual: grab the app on a page with a scrollbar (e.g. Vosfor) natively and confirm scrollbar/borders look identical to before (compare against `backup_style_tokens_2026-08-03/` render if unsure).

---

## Task 3: Add `SP_XXS` and route the `setSpacing(2)` micro-gaps

**Files:**
- Modify: `data/ui/market.py` (lines ~779, 907), `data/ui/web.py` (line ~316), `data/ui/settings.py` (line ~881)

**Interfaces:**
- Consumes: `t.SP_XXS`.

Note: this is a low-risk convenience pass. Convert only the clear `setSpacing(2)` calls (a `2` used as a layout gap). Leave the mixed vertical-margin `2`s inside `setContentsMargins(..., 2, ..., 2)` alone for now (they read fine as detail-range literals and the style-guide test still permits raw 1–3). No new test assertion — `SP_XXS` is a convenience token.

- [ ] **Step 1: Convert the calls.** In each file, change `setSpacing(2)` → `setSpacing(t.SP_XXS)`. Confirm `theme` is imported as `t` in each (it is, app-wide). Exact sites:
  - `market.py`: the ContractsTab rows `setSpacing(2)` and WatchlistTab col `setSpacing(2)`.
  - `web.py`: the web col `setSpacing(2)`.
  - `settings.py`: `self.file_host.setSpacing(2)`.

- [ ] **Step 2: Checkpoint** — `python tests/run_all.py` green. No visual change (2 == SP_XXS).

---

## Task 4: Re-point cross-file duplicate literals at their tokens (no visual change)

**Files:**
- Modify: `data/ui/home.py` (SCROLLBAR_H), `data/ui/market.py` (REMOVE_BTN, TABLE_ROW_H, icon `msg`), `data/ui/settings.py` (REMOVE_BTN, DISCLOSURE_W, dialog 460), `data/ui/vosfor.py` (DISCLOSURE_W), `data/ui/listings.py` (contract-card icon buttons, 2 dialogs), `data/ui/dialogs.py` (dialog). Dialog-width sites are exactly: `dialogs.py`, `listings.py` ×2, `market.py` ×1 (all `430`), and `settings.py` (`460`) — no others.

**Interfaces:**
- Consumes: `t.SCROLLBAR_THICK`, `t.REMOVE_BTN`, `t.DISCLOSURE_W`, `t.TABLE_ROW_H`, `t.ICON_BTN`, `t.DIALOG_MIN_W`.

All edits below are value-preserving (each literal already equals its token), so the app is pixel-identical.

- [ ] **Step 1: Scrollbar thickness single-source.** `home.py`: change `SCROLLBAR_H = 12` → `SCROLLBAR_H = t.SCROLLBAR_THICK` (keep the name; its usages are unchanged).

- [ ] **Step 2: Remove buttons.** Replace `setFixedSize(24, 22)` → `setFixedSize(*t.REMOVE_BTN)` at `market.py` (WatchlistTab remove) and `settings.py` (file-row remove).

- [ ] **Step 3: Disclosure arrows.** Replace `arrow.setFixedWidth(20)` → `arrow.setFixedWidth(t.DISCLOSURE_W)` at `settings.py` (tree arrow) and `vosfor.py` (section arrow).

- [ ] **Step 4: Table row height.** In `market.py`, the module const `ROW_HEIGHT = 26` → `ROW_HEIGHT = t.TABLE_ROW_H` (keeps `TABLE_ROWS * ROW_HEIGHT` working in all three tables).

- [ ] **Step 5: External icon buttons → `ICON_BTN`.** Replace `setFixedWidth(28)` → `setFixedWidth(t.ICON_BTN)` at: `listings.py` ContractCard wiki/edit/vis/rm (4 sites), `market.py` order-row `msg` and contracts `msg` (2 sites). (These are already 28 → invisible.) Do NOT touch `ListingCard.showEvent` — that is Task 6.

- [ ] **Step 6: Dialog widths → `DIALOG_MIN_W` (widen 430 → 460).** Replace `setMinimumWidth(430)` → `setMinimumWidth(t.DIALOG_MIN_W)` at `dialogs.py`, `listings.py` (EditListingDialog + EditContractDialog), `market.py` (PostOrderDialog). Replace the settings dialog `setMinimumWidth(460)` → `setMinimumWidth(t.DIALOG_MIN_W)` (already 460, invisible).

- [ ] **Step 7: Checkpoint** — `python tests/run_all.py` green.

- [ ] **Step 8: Visual spot check.** Open an edit/post dialog natively (e.g. from My Listings) and confirm it renders at 460 without layout breakage.

---

## Task 5: Unify the web-tab buttons (the one visual change)

**Files:**
- Modify: `data/ui/web.py` (shut/remove/star/generic button widths: `28`/`24`/`30` → `t.ICON_BTN`)

**Interfaces:**
- Consumes: `t.ICON_BTN`. Uses the `tools/shot.py` harness from Task 0.

- [ ] **Step 1: The before-image already exists** — `backup_style_tokens_2026-08-03/baseline/web_wiki_{1,2,3}x.png` from Task 0. That is the before for comparison.

- [ ] **Step 2: Unify the web-tab buttons.** In `data/ui/web.py`, replace the icon-button widths with the token:
  - web shut button `setFixedWidth(28)` → `setFixedWidth(t.ICON_BTN)`
  - web remove button `setFixedWidth(24)` → `setFixedWidth(t.ICON_BTN)`
  - web star button `setFixedWidth(30)` → `setFixedWidth(t.ICON_BTN)`
  - the generic web `b.setFixedWidth(30)` → `setFixedWidth(t.ICON_BTN)`
  Confirm `from core import theme as t` (or the file's alias) is present.

- [ ] **Step 3: Checkpoint** — `python tests/run_all.py` green.

- [ ] **Step 4: Cross-DPI capture, diff against baseline, post to chat.** Grab the web tab at 1×/2×/3× (same footprint as Task 0):

```
for SF in 1x:0.3333 2x:0.6667 3x:1.0; do L=${SF%:*}; F=${SF#*:}; \
  QT_SCALE_FACTOR=$F python tools/shot.py web_wiki 1280 680 "$CLAUDE_JOB_DIR/tmp/web_after_${L}.png"; done
```
Compare each against `backup_style_tokens_2026-08-03/baseline/web_wiki_${L}.png`. The ONLY difference should be the button widths (24/30 → 28); anything else that differs at a given scale but was ALSO present in the baseline is a pre-existing quirk, not this change. `SendUserFile` the baseline-vs-after pair at 3× (and 1× if anything looks off) with a caption noting the intended change, and confirm the buttons read as one size at every scale with no glyph clipping.

---

## Task 6: Item-card button cascade (measure → tokenize → prove pixel-identical)

**Files:**
- Modify: `data/core/theme.py` (add `CONTROL_H`, and a card-scoped icon width only if needed)
- Modify: `data/ui/listings.py` (`ListingCard.showEvent`, ~lines 308-321)
- Modify: `tests/test_metrics.py` (assert `CONTROL_H` exists)

**Interfaces:**
- Consumes: `t.CONTROL_H`, `t.ICON_BTN`, `t.SP_SM`.

The current `showEvent` derives everything from `sizeHint()`:
```python
H = self.up.sizeHint().height()      # shared control height
wide = self.up.sizeHint().width()    # stepper width (also badge/limit)
icon_w = H + 6                        # eye/wiki/trash width
# eye/wiki/trash: setFixedSize(icon_w, H); reprice: setFixedSize(2*wide + t.SP_SM, H)
# badge: setFixedSize(wide, H); limit: setFixedSize(wide, H)
```

**Card-rendering note:** the My Listings PAGE shows "loading your orders…" with no cards unless a
warframe.market session with orders exists — so `tools/shot.py listings` will NOT show the item card.
Build an isolated harness `tools/card_shot.py` that constructs a single `ListingCard` with dummy data
(read `ListingCard.__init__`'s real signature from `data/ui/listings.py`), shows it, and grabs it. This
removes the network variable from the pixel-identical proof. Use the same `QT_SCALE_FACTOR = target/3`
scaling as `tools/shot.py`.

- [ ] **Step 1: Capture the immediate-before** with the isolated card harness (3 scales):

```
for SF in 1x:0.3333 2x:0.6667 3x:1.0; do L=${SF%:*}; F=${SF#*:}; \
  QT_SCALE_FACTOR=$F python tools/card_shot.py "$CLAUDE_JOB_DIR/tmp/card_before_${L}.png"; done
```
This is the definitive before; capture it AFTER Tasks 1–5 (which don't touch `ListingCard`) and just
before the Step 5 rewrite.

- [ ] **Step 2: Measure the current logical sizes.** Add a temporary print in a scratch run (do NOT commit it) to read one card's values:

```python
# scratch: python - <<'PY' (native platform)
#   ... build MainWindow, navigate("listings"), processEvents ...
#   card = <first ListingCard>; print(card.up.sizeHint().height(), card.up.sizeHint().width())
# PY
```
Record `H` (→ `CONTROL_H`) and `wide` (stepper width). Compute `icon_w = H + 6` and note whether it equals `28` (`t.ICON_BTN`).

- [ ] **Step 3: Add `CONTROL_H` to `theme.py` metrics** with the measured value, e.g.:

```python
CONTROL_H = 22               # shared control/button height (MEASURED at the app
                             # font; logical px, DPI-invariant). All item-card
                             # buttons inherit this; future buttons reference it.
```
If `icon_w` (`CONTROL_H + 6`) did NOT equal 28, also add:
```python
CARD_ICON_W = 28             # item-card icon-button width (CONTROL_H + 6), kept
                             # distinct from ICON_BTN so the card does not move
```
(If it DID equal 28, reuse `t.ICON_BTN` for the card icon width — no new token.)

- [ ] **Step 4: Assert `CONTROL_H` in the metrics test.** Add to `tests/test_metrics.py`:
```python
check("CONTROL_H is a positive int", isinstance(t.CONTROL_H, int) and t.CONTROL_H > 0)
```

- [ ] **Step 5: Rewrite `ListingCard.showEvent` sizing as the cascade** (replace the derived block; keep the same widget wiring). Using the measured tokens:

```python
def showEvent(self, event):
    super().showEvent(event)
    H = t.CONTROL_H                       # base: shared height (was up.sizeHint().height())
    wide = self.up.sizeHint().width()     # stepper width: shared by +/-1, badge, limit
    icon_w = t.ICON_BTN                   # icon class width (or t.CARD_ICON_W per Step 3)
    for b in (self.eye, self.wiki, self.trash):
        b.setFixedSize(icon_w, H)         # .btn-icon { width; height }
    self.rp.setFixedSize(2 * wide + t.SP_SM, H)   # .btn-reprice { height:inherit; width:own }
    self.badge.setFixedSize(wide, H)
    self.limit.setFixedSize(wide, H)
```
(Keep whatever the current attribute names are — `self.up`, `self.eye`, etc. — matching the existing code; only the *height source* changes from `sizeHint()` to `t.CONTROL_H`, and `icon_w` from `H + 6` to the token.)

- [ ] **Step 6: Checkpoint** — `python tests/run_all.py` green (32 + test_metrics).

- [ ] **Step 7: Prove pixel-identical + cross-DPI.** Re-grab the card via the same harness at all three scales:
```
for SF in 1x:0.3333 2x:0.6667 3x:1.0; do L=${SF%:*}; F=${SF#*:}; \
  QT_SCALE_FACTOR=$F python tools/card_shot.py "$CLAUDE_JOB_DIR/tmp/card_after_${L}.png"; done
```
Compare `card_before_${L}.png` vs `card_after_${L}.png` at each scale. They must be identical. `SendUserFile` the 3× before/after pair to the user for confirmation. **If any pair differs**, the measured `CONTROL_H` is wrong — adjust the token to the value that reproduces the before, re-verify. If it cannot be made identical (font makes the derived height genuinely dynamic at some scale), revert `showEvent` to `sizeHint()` for the height and keep `CONTROL_H` documented as the reference-only value; note this in the plan's outcome.

---

## Task 7: Lock everything in the style guide + full cross-DPI verification matrix

**Files:**
- Modify: `tests/test_style_guide.py` (broaden the duplicate-literal locks)

**Interfaces:**
- Consumes: all tokens.

- [ ] **Step 1: Add duplicate-literal regression locks** to `tests/test_style_guide.py` (after the dimension-discipline block). These assert the tokenized raw literals no longer appear as independent definitions in `data/ui/`:

```python
print("\ncross-file duplicates are tokenized")
ui_no_qss = {n: s for n, s in text.items() if n != "qss.py"}
def none_contain(substr):
    return {n for n, s in ui_no_qss.items() if substr in s}
check("no raw setFixedSize(24, 22) (use t.REMOVE_BTN)",
      none_contain("setFixedSize(24, 22)"), set())
check("no raw setMinimumWidth(430) (use t.DIALOG_MIN_W)",
      none_contain("setMinimumWidth(430)"), set())
check("no raw disclosure setFixedWidth(20) (use t.DISCLOSURE_W)",
      none_contain("setFixedWidth(20)"), set())
check("no raw icon-button setFixedWidth(28) (use t.ICON_BTN)",
      none_contain("setFixedWidth(28)"), set())
check("SCROLLBAR_H references the token",
      any("SCROLLBAR_H = t.SCROLLBAR_THICK" in s for s in ui_no_qss.values()))
```

- [ ] **Step 2: Run the style-guide test, expect PASS** — `python tests/test_style_guide.py`. If any check fails, a literal was missed in Tasks 4–6 — fix it, re-run.

- [ ] **Step 3: Full checkpoint** — `python tests/run_all.py` green.

- [ ] **Step 4: Full cross-DPI matrix, diffed against the Task 0 baseline, posted to chat.** Grab the key surfaces at 1×/2×/3×:
```
for SF in 1x:0.3333 2x:0.6667 3x:1.0; do L=${SF%:*}; F=${SF#*:}; \
  for P in home market listings vosfor settings web_wiki; do \
    QT_SCALE_FACTOR=$F python tools/shot.py $P 1280 680 "$CLAUDE_JOB_DIR/tmp/final_${P}_${L}.png"; \
done; done
```
For each, compare against `backup_style_tokens_2026-08-03/baseline/${P}_${L}.png` (same scale).
**Attribution rule (the user's point):** the ONLY expected differences anywhere are the web-tab
buttons (Task 5). Any other difference must be checked against the baseline — if it is ALSO present
in the baseline at that scale, it is a pre-existing rendering quirk, not a regression from this
work; if it is NEW, it is a bug to fix. Review each for: no NEW clipped text, borders present,
buttons uniform, scrollbars intact, dialogs at 460. `SendUserFile` a representative set (the 3× row
+ any scale with a NEW difference) with a short analysis separating "intended change," "pre-existing
quirk (also in baseline)," and "regression (fix it)." Flag anything for the user to comment on.

- [ ] **Step 5: Update memory.** Record the new token layer in `wf-toolbox-core-rules` (or a new `wf-toolbox-style-tokens` memory): theme.py now owns metrics tokens; `test_style_guide` enforces them; the cascade model for item-card buttons; backup location.

---

## Self-review notes (for the implementer)

- **Spec coverage:** Tier 1 → Tasks 1–2; SP_XXS → Task 3; Tier 2/3 duplicates → Task 4; the one visual change (web tabs) → Task 5; item-card cascade → Task 6; enforcement + cross-DPI verification → Tasks 2/7. Tier 4 and light-theme are explicitly out of scope.
- **`CONTROL_H` value is a placeholder (`22`) until Step 6.2 measures it** — the measurement step sets the real number; do not trust the placeholder.
- **The only intended visual change is Task 5** (web tabs 24/30→28). Every other task must be pixel-identical; the screenshots are how you prove it.
