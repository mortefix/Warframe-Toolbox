# UI/UX Polish Audit — Findings (2026-08)

First application of `docs/STYLE_GUIDE.md`. Findings from a visual audit of 20
surface/state screenshots captured at true 300% DPI (`tools/gallery.py`), judged
by four independent vision passes against the style guide, then synthesized and
de-duplicated. **No UI changed** — this is the review; implementation is a
separate, approved pass.

Screenshots: `$CLAUDE_JOB_DIR/gallery/`. Each finding names the responsible code
constant. Severity: **HIGH** = reads as broken / a large jarring void; **MED** =
cross-screen inconsistency or notable imbalance; **LOW** = refinement.

---

## Theme 1 — Sparse content inflates into hollow voids (systemic) — HIGH

The dominant finding, on four screens, one root cause: containers carry
`stretch=1` with **no trailing spacer**, so when content is sparse the slack
inflates the *content bands* instead of pooling below them. The result is
hollow cards and tables — the opposite of the guide's §5 "empty-but-right-sized
reads as *waiting*, not broken."

- **Listing cards** (`40/41/42`): ~40% hollow vertical void per card when few
  orders exist; worst on WTB (2 orders) where each card fills the whole viewport
  with three thin bands stranded top/middle/bottom. — `listings.py` card grid,
  no trailing row stretch; `ListingCard` `QFrame` expands to fill.
- **Market order-book & Watchlist cards** (`10/12`): ~85% empty umber; the 312px
  (12×26) "waiting" reserve balloons to ~470 logical under `stretch=1`. —
  `market.py:246/255-256`, `:793-797`.
- **Home tool cards** (`01`): short cards (1-line Wiki) stretched to match the
  tallest card in the row, leaving a dead band above the button. — `home.py:77`
  `addWidget(blurb, 1)`.
- **Edit dialog** (`43`): vertical slack inflates the "wts" badge (renders
  ~110×175, taller than wide vs the ~55×40 card pill) and every caption gap. —
  `listings.py` `EditListingDialog`, no trailing `addStretch`.

**Fix pattern (one idea, four screens):** after placing content, pin slack to a
trailing `addStretch(1)` / `setRowStretch(last+1, 1)` and give cards a vertical
`QSizePolicy.Maximum`, so slack collects *below* the content. Top-align the badge.

---

## Theme 2 — Center voids / "barbell" layout — MED

Right-aligned info + actions with a single `addStretch` open a large empty
middle, orphaning the key datum from its label.

- **Listing card** (`40`): `info.addStretch` + `acts.addStretch` push the price
  line ("120 plat each · ⚠ low 110p") to the far right while the title sits far
  left; the card stacks three different horizontal alignments. — `listings.py`
  `ListingCard` info/acts leading stretch. **Fix:** left-align the price/market
  line under the title; keep the action row right-aligned.
- **Vosfor rows** (`21`): name far-left, price/farm/drop far-right, enormous gap
  at wide widths. — `vosfor.py:105` unbounded `addStretch`. **Fix:** cap row
  content to a max readable (window-rooted) width; keep numeric columns
  right-aligned within it.
- **Market toolbar** (`11`): ~396 logical-px empty mid-band between the filter
  cluster and the action cluster. — `market.py:174/578`. **Fix (optional):**
  a fixed `SP_XL` gap instead of one large stretch.
- **Settings "market profile" grid** (`51`): label→value ~40% gap; also uses
  column width 130 vs the standard `LABEL_COL=190`. — `MarketPage` grid, no
  stretch column. **Fix:** col0=`LABEL_COL`, add a trailing stretch column.

---

## Theme 3 — Off-scale spacing literals (violates §4) — MED

Raw non-`SP_*` values have crept into two files; the §4 "spacing is always a
token" rule is not yet linted (still a §10 candidate).

- **Home caption** margins `(28,22,0,8)` and **grid** `(20,0,6,16)` — `20`≠
  `SP_SCREEN=24`, so Home sits 4px tighter to the sidebar than every other
  screen. — `home.py:118,131`.
- **Home card** margins `(16,14,16,14)`, head spacing `8`, `addSpacing(12/10/4)`.
  — `home.py:43,54,78,51,63`.
- **Vosfor reco panel** margins `(14,10,14,10)` — `14` off-scale, and it throws
  the panel text 4px off the collection rows beneath it. — `vosfor.py:292`.

**Fix:** snap all to `SP_*` tokens, **and extend `tests/test_style_guide.py` to
lint `setContentsMargins`/`setSpacing` integer literals** (this theme is the
evidence the candidate check is needed).

---

## Theme 4 — Cross-screen inconsistency (sibling drift) — MED

The exact failure mode the guide exists to prevent.

- **Market active-tab underline** is teal / pink / gold across the three tabs
  (`10/11/12`); one is the money-reserved `ACCENT` gold. Reads arbitrary. —
  `market.py:41-42` `TAB_ACCENTS`. **Decision needed:** unify to gold (matches
  the "active-nav finial" rule), or document per-tab tinting as a deliberate
  WFM-parity rule in the guide.
- **Market card headers**: h2 (Market) / caps (Watchlist) / none (Contracts) —
  three treatments for the same role. — `market.py:218` vs `:786`. **Fix:** one
  header role on all three.
- **Contracts empty-state** prompt sits *above* an empty card; Market/Watchlist
  place their placeholder *inside* the card. — `market.py:596-598`. **Fix:**
  center the prompt inside the card.
- **Vosfor** two refresh buttons: "Update inventory" is `wide`, "Refresh prices"
  is not — 4px padding delta. — `vosfor.py:245` vs `:279`. **Fix:** match them.

---

## Theme 5 — Alignment / gutter drift — MED / LOW

- **Home "AVAILABLE TOOLS" caption** floats in no-man's-land — indented more than
  the card border, less than the card content. — `home.py:118` (overlaps T3).
- **Market tab bar** is full-bleed while the title and content are inset by
  `SP_SCREEN`; the tab thirds don't align to the content column. — `market.py:998`
  margins `(0,0,0,0)`. **Fix:** inset the bar to `SP_SCREEN`, or commit to a
  deliberate full-width segmented control.
- **Settings nav** left edges stair-step: caps title (~10), search (~4), section
  headers (~24). — `settings.py` `_header`. **Fix:** one nav gutter (leaves stay
  indented at 34 for hierarchy).

---

## Theme 6 — Empty state reads as blank, not waiting — LOW / MED

- **Market API console** (`51`) is a blank black rectangle before a run. —
  `MarketPage` console, no placeholder. **Fix:** `setPlaceholderText("Run the
  check to see output.")` — parallels §5's own precedent.

---

## Theme 7 — Over-wide text measure — LOW / MED

- **Settings blurbs** (`51/52/54`) wrap only at the card edge — 100+ char lines
  across ~80% of a wide window. — `Page.blurb()`, no `setMaximumWidth`.
  **Fix:** cap measure at ~560-620 logical px in the one helper (fixes all pages).

---

## Theme 8 — Control sizing / grouping nits — LOW

- **Warframe row** (`55`): Auto-detect / Browse buttons render a few px taller
  than the 22px-capped field beside them. — `Page.button()` vertical padding.
- **Display pickers** (`50`): stacked "Window size" and "Open on monitor"
  dropdowns have mismatched widths → ragged right edge. — `Page.picker()` no
  shared min width.
- **Toolbox file rows** (`53`): filenames aren't a fixed-width column, so the
  gray descriptions start at a different x on every row. — `ToolboxPage._row`.
- **Edit dialog** (`43`): label→field gap == inter-field gap (loose stack, §4
  says control→label should be `SP_SM`); and no `setMinimumWidth` (§9). —
  `EditListingDialog`.
- **Listings control row** (`40`): Sort / Show / Visibility groups separated by
  the same `SP_SM` used *within* a group, so they run together. — `ListingsTab`
  `ctl`. **Fix:** `SP_LG` between groups.

---

## Golden-ratio verdict — φ correctly applies NOWHERE here

All four passes independently concluded that **no window-rooted φ split is
warranted** on any surface. Every imbalance lives in a §6-excluded zone —
space-filling frames (cards, tables, console), data tables, search fields, and
the fixed spacing tokens. The remedies are spacer/stretch, max-width, and
token-snap corrections, not proportion splits. **This validates the "sparingly"
policy: the audit actively looked for φ opportunities and found none appropriate
— the correct outcome, not a gap.**

---

## Tooling note (not an app finding)

`PrintWindow` faithfully captures every native Qt surface but **cannot capture a
window containing a QtWebEngine view** (Chromium's native child surface
overpaints the client area white). The web chrome is captured via
`QWidget.grab()` instead; `tools/gallery.py` now does this for the web scene.

---

## Suggested implementation order

1. **Theme 1** (the biggest, most jarring void — one pattern, four screens).
2. **Theme 4** + **Theme 3** (cheap, high consistency payoff; T3 also earns a
   lint).
3. **Theme 2** (center voids), **Theme 6/7** (one-line fixes each).
4. **Theme 5** (gutters), **Theme 8** (nits).

Theme 4's tab-underline colour is a **design decision for the user**, not a
mechanical fix.

---

## Resolution (2026-08) — all themes worked through

- **Theme 1** — listings cards (trailing stretch row) + edit-dialog badge (AlignVCenter) + minWidth FIXED. Home short-card void (button-baseline, commented intent) and market order-book (space-filling list) **sanctioned as intentional**.
- **Theme 2** — listings price line (left-aligned under name) + settings profile grid (stretch column + LABEL_COL) FIXED. Vosfor rows (data table) and market toolbar (status-text location) **sanctioned**.
- **Theme 3** — off-scale spacing in home/vosfor/market/settings **snapped to SP_\* tokens**, and a **spacing lint added to `test_style_guide.py`** (raw layout spacing ≥ 4 now fails the suite). Bonus: fixed Theme 5's home-caption (M1) and vosfor-reco (M3) alignment for free.
- **Theme 4** — vosfor's two refresh buttons unified (`wide`). Tab colours **kept and documented** as WFM-parity (user decision). Market card headers (h2/caps/none = differentiated roles) and the full-width tab bar (deliberate segmented control, per its own code comment) **sanctioned**.
- **Theme 5** — home caption + vosfor reco done via Theme 3; market tab bar sanctioned.
- **Theme 6** — API console `setPlaceholderText` FIXED.
- **Theme 7** — settings blurb capped to a **610px (Fibonacci) measure** with `heightForWidth` (no clipping) FIXED.
- **Theme 8** — settings picker shared min-width (144), toolbox filename floor-width (210), listings control-row grouping (SP_LG) FIXED. Edit-dialog label→field micro-spacing and the ~2px button-height nit **deferred** (LOW; restructure / global-button risk outweighs payoff).

**Guardrail now enforced** (`tests/test_style_guide.py`, green): no raw hex, corners 0-except-scrollbar, fonts by role, spacing by token. Style guide is the measuring stick; these four are mechanical.
