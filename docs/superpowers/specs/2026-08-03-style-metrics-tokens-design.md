# Design: Universal Style Metrics — a CSS-equivalent for the Python app

**Date:** 2026-08-03
**Status:** Design (awaiting user review)
**Scope:** Warframe Toolbox PySide6 app (`D:\Projects_AI\Warframe Toolbox`)

## Purpose

Give the app the equivalent of a **CSS stylesheet**: one file where every reused visual
parameter is defined, so the whole app draws from a shared vocabulary. The motivation is
forward-looking — **as more apps are added to Warframe Toolbox, they stay cohesive by
construction** (they reference the same tokens) rather than by hand-matching values.

A second, deliberately-future benefit: a single source of truth **for colors** makes **theming**
possible. Today's palette is "Orokin Dark"; once every color is unified in the sheet, an
"Orokin Light" theme could be introduced by swapping the palette section alone. Not built in
this pass, and not a requirement — but the design must not preclude it.

## Problem (current state)

`data/core/theme.py` already centralizes **colors**, **fonts** (family + size per role), and the
**spacing scale** (`SP_*`), and `tests/test_style_guide.py` enforces it (no raw `#hex` in
`data/ui/`, one hand-written `font-size`, layout spacing ≥4 must be `SP_*`).

But that discipline stops at colors/fonts/spacing. **Every *dimension*** — border widths,
element sizes, corner radii, font weights, and the paddings inside `qss.py` rules — **is a raw
literal**, and several identical concepts are defined independently in different files with no
link, so they drift:

- Scrollbar thickness `12` lives in `home.py` (`SCROLLBAR_H`) **and again** in `qss.py`.
- Web-tab icon buttons are `24`/`30` while the same concept is `28` in the market rows and
  contract cards — an unplanned inconsistency.
- The `24×22` remove button and the `20` disclosure arrow are each defined twice, identically.
- `1px` borders appear ~10× in `qss.py` plus `hairline`/`vline`/nav/vosfor.

Grounded in a full code audit of `qss.py` and every `data/ui/*.py` (exact values + locations),
cross-checked visually — not measured from screenshots.

## Goal / non-goal

**Goal:** one file (`theme.py`) holds every *reused* dimension in a `metrics` section, and
`qss.py` + the per-widget sizing code reference those tokens. Cross-file duplicates collapse to
one definition. Colors stay a cohesive, theme-swappable palette section (separate from metrics,
which are theme-invariant).

**Non-goal:** tokenizing genuinely single-use values (`CARD_W=260`, `NAV_WIDTH=168`,
`LABEL_COL=190`, checkbox `14/12` box-model math). Already single-source in their module;
relocating them adds indirection without benefit. They stay local. Also non-goal: building the
light theme (future), and *changing the appearance* of the tuned item cards — they get tokenized
as a cascade with zero visual change (see Decision 1 / "Button sizing cascade").

## Where the tokens live

Extend `data/core/theme.py` with a new `---- metrics ----` section (peer to spacing / palette /
typography). `theme.py` stays toolkit-free — metrics are plain ints like `SP_*`. Palette and
metrics live in separate sections precisely so a future theme swaps colors without touching
metrics. Split to `core/metrics.py` only if it later grows unwieldy — not now.

## The token taxonomy

### Tier 1 — True globals (one value, app-wide)

| Token | Value | Replaces |
|---|---|---|
| `BORDER_W` | `1` | all `1px` borders in qss (~10) + `hairline`/`vline`/`NAV_SECTION_BORDER`/vosfor insets |
| `SP_XXS` | `2` | the sub-`SP_SM` micro-gap: `setSpacing(2)` + `(…,2,…,2)` insets (8+ sites); extends the spacing scale |
| `SCROLLBAR_THICK` | `12` | qss `width/height: 12px` **and** `home.py SCROLLBAR_H` |
| `SCROLLBAR_HANDLE_MIN` | `30` | qss handle `min-height`/`min-width` |
| `RADIUS_HANDLE` | `3` | the only non-zero corner radius (scrollbar handles) |

### Tier 2 — Contextual tokens (a category's canonical value, maybe one variant)

| Token | Value | Replaces / notes |
|---|---|---|
| `CONTROL_H` | measured | the shared button/control **height** — the item card's `H` (`sizeHint().height()`) locked to its current value; the global "reference height" future buttons inherit |
| `ICON_BTN` | `28` (verify vs `CONTROL_H + 6`) | icon-button **width** class (visibility/wiki/trash + external contract/market/web icon buttons). Web-tab `24`/`30` → `28` is the one visual change; all others already 28. If the item card's icon width (`H + 6`) measures to 28 it shares this token; if not, item-card icons get a card-scoped width token so they don't move. |
| `REMOVE_BTN` | `(24, 22)` | market watchlist + settings file-row remove buttons |
| `DISCLOSURE_W` | `20` | settings tree arrow + vosfor section arrow |
| `TABLE_ROW_H` | `26` | the 3 market tables' `ROW_HEIGHT` |
| `DIALOG_MIN_W` | `460` | **all** dialogs (the four currently `430` widen to `460` — user decision) |
| `WEIGHT_BOLD` | `"bold"` | qss badge label |
| `WEIGHT_SEMI` | `600` | qss money-button |

### Tier 3 — Cross-file duplicates → re-point at the Tier 1/2 tokens

No new tokens; these sites currently define a value independently and must reference the shared
token instead:

- `home.py SCROLLBAR_H` → `SCROLLBAR_THICK` (qss stops hardcoding `12`)
- the four dialog `setMinimumWidth(430)` + settings `460` → `DIALOG_MIN_W`
- the `24×22` remove buttons (market, settings) → `REMOVE_BTN`
- the `20` arrows (settings, vosfor) → `DISCLOSURE_W`
- the icon buttons **outside item cards** (contract card, market `msg`, web tabs) → `ICON_BTN`

### Tier 4 — DEFERRED (user decision)

Repeated-but-already-token-based page-layout patterns (card-grid geometry; page header
`(SCREEN,LG,SCREEN,LG)`; content holder `(SCREEN,0,SCREEN,XL)`; top-gap `(0,LG,0,0)`). Correct
today, just repeated — low visual payoff, many files. Out of scope; revisit later.

## Button sizing cascade (item cards)

Modeled on CSS class inheritance + inline override. Today `ListingCard.showEvent` derives every
size from `sizeHint()` at runtime (`H = up.sizeHint().height()`, `wide = up.sizeHint().width()`,
`icon_w = H + 6`). The refactor keeps the *result* identical but expresses it as a cascade of
tokens:

- **Base (shared height):** `CONTROL_H` — every action button on the card. `≡ .btn { height }`.
- **Icon class (shared width+height):** visibility / wiki / trash → `ICON_BTN` width + `CONTROL_H`
  height. `≡ .btn-icon { width; height }`. Shared with the external icon buttons iff the measured
  widths match (see Tier 2).
- **Stepper width (shared within the card):** +1 / −1 and the badge + limit field share one width
  (`wide`) → a card-scoped width token. `≡ .btn-step { width }`. Not global (only this card uses
  it).
- **Reprice (unique override):** inherits `CONTROL_H`, sets its own width (`2 × stepper + SP_SM`),
  which is reused nowhere → stays a local override, no global token. `≡ .btn-reprice { height:
  inherit; width: <own> }`.

Rule captured here: **a value earns a token when it is shared (height → global, icon width →
class, stepper width → card-scoped); it stays an override when it is unique (Reprice width).**
Implementation measures the current values, locks the tokens to them, and proves the card is
pixel-identical before/after.

## Key decisions (locked with the user)

1. **Item cards ARE tokenized — as a CSS-style cascade, with zero visual change.** The item card's
   button sizing (`ListingCard.showEvent`) moves from runtime `sizeHint` derivation to named
   tokens arranged as a cascade (see "Button sizing cascade" below): a shared `CONTROL_H`, an
   `ICON_BTN` width class for visibility/wiki/trash, and per-button width overrides (Reprice) that
   inherit `CONTROL_H`. Values are **measured from the current 300%-DPI render and locked into the
   tokens**, so the cards are pixel-identical afterward — the Reprice button keeps its intentional
   unique width, and all buttons keep their shared height. This is centralization of *structure*,
   not a visual change. The sole visual change anywhere is the web-tab buttons (`24`/`30` → `28`).
   If a size can't be made pixel-identical as a fixed token, that button stays derived and the
   token documents it as a reference (expected to be rare).
2. **All dialogs → `DIALOG_MIN_W = 460`.** The 460 was the settings *dialog* width (a modal,
   unrelated to the settings *page's* nav sidebar); the user chose to widen the other dialogs to
   match. The "why the settings *page* feels refined" question is a separate page-layout
   investigation (see follow-ups).
3. **Tier 4 deferred.**

## Enforcement (tests)

Extend `tests/test_style_guide.py` with a "dimension discipline" section, locking the new tokens
the way colors/fonts are locked:

- **No raw border width in qss:** `qss.py` must not contain a literal `Npx` border width — widths
  come from `t.BORDER_W`. (`border: none` and the hairline `max-height/-width` frames either stay
  or route through `BORDER_W`.)
- **Scrollbar/handle/radius from tokens:** `qss.py` must not hardcode `12`/`30`/`3` for scrollbar
  metrics.
- **Cross-file duplicates gone:** narrowly-scoped greps assert the tokenized literals (`24, 22`;
  arrow `20`; dialog `430`; `SCROLLBAR_H = 12`) no longer appear as independent definitions.

Existing color/font/spacing checks stay unchanged.

## Migration approach (token-group by token-group, each independently verifiable)

1. Add the `metrics` section to `theme.py` (Tier 1 + Tier 2 tokens).
2. Route `qss.py` through them (borders, scrollbar metrics, radius, weights, the `2` paddings that
   map to `SP_XXS`).
3. Re-point the per-widget sites (Tier 3): named consts (`SCROLLBAR_H`, dialog widths) + the
   inline `setFixedWidth(28)` / `setFixedSize(24,22)` / arrow `20` calls.
4. Widen the four `430` dialogs to `DIALOG_MIN_W`.
5. **Item-card cascade:** measure the current `H` / `wide` / `icon_w` on the real render, add
   `CONTROL_H` (+ any card-scoped width token), and rewrite `ListingCard.showEvent` to reference
   the cascade tokens instead of the raw `sizeHint` derivation. Prove pixel-identical.
6. Extend the style-guide test.

## Safety: backup before changes (no git)

The repo is not under version control, so before any edit, back up every file in the migration
scope to a timestamped folder at the project root (`backup_style_tokens_2026-08-03/`), mirroring
`data/core/theme.py`, `data/ui/*.py`, and `tests/*.py`. The folder sits outside `data/ui/` and
`tests/`, so neither the app nor the test runner picks it up; it exists purely for revert/diff if
a structural change looks worse.

## Verification

- `python tests/run_all.py` green (currently 32 files) after each token group.
- Real 300%-DPI native-platform screenshots (per the verify-real-DPI rule, NOT offscreen) of what
  changes:
  - **Web tabs** — shut/remove/star buttons now `28` (were `24`/`30`); confirm they look right.
  - **Dialogs** — an edit/post dialog at `460`.
  - **Item cards** — before/after must be **pixel-identical** (the cascade tokenizes structure, not
    appearance). Capture the card before the refactor, again after, and compare; any difference is
    a bug in the measured token values.
  - **Scrollbars** — unchanged thickness, now single-sourced.

## Out of scope / follow-ups

- **Tier 4** (page-layout DRY constants).
- **"Why does the settings *page* feel refined?"** — a page-layout-token investigation
  (label-column alignment, card padding rhythm) the user raised. Separate project.
- **Light theme** — enabled by this work's color single-source, but built later.
- Single-use component constants stay local.
