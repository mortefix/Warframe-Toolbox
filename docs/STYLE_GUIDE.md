# Warframe Toolbox — Style Guide ("Orokin Treasury")

**This is the single source of truth for the app's visual design.** Every agent
session and every change is measured against it. When a rule here and the code
disagree, that is a bug to file — not a licence to freelance. Colour and
typography *values* live in `data/core/theme.py` (imported by everything); this
document owns the **rules, conventions, and dimensional system** that the tokens
alone don't express.

> Supersedes the prose in `README.md` and the checklist in `CLAUDE.md`. Those
> should point here, not restate it.

---

## 1. Design language

A **void-black lacquered cabinet**: panels are warm near-blacks (umber, *never*
blue), trimmed with **one metal — aged gold** — reserved for hairlines, the
active-nav finial, focus edges, and money actions. **Gold is inlay, never
plating.** Platinum numerals are cool silver, matching the in-game gem. The
warframe.market screens borrow WFM's teal/pink/blue accents for parity, but the
shell stays gold-and-umber.

Guiding feel: **solid, predictable, quiet.** Nothing flickers, nothing shifts
size on interaction, nothing competes with the game the app assists.

---

## 2. Colour

- **Source of truth:** the tokens in `data/core/theme.py`. **Never write a raw
  `#hex` in `data/ui/`** — `qss.py` enforces this, and a test asserts every
  colour in the generated sheet traces back to a token.
- **Gold discipline.** Filled-gold (`ACCENT` background, `INK` text) is for
  **money actions and the account link only** — Reprice, Sold, Sign in, Run.
  Everywhere else gold is a 1px inlay (`GOLD_DIM`/`FIELD_EDGE`), the focus edge,
  or the active-nav finial. Sanctioned exception: the Vosfor collection progress
  bar fills gold (`ACCENT`), turning jade (`OK`) when complete.
- **Severity is a role word, never a raw colour, across the core→ui boundary.**
  `OK`=jade, `WARN`=orange-amber (pushed to orange precisely so it can *never*
  read as the gold `ACCENT`), `ERR`=coral.
- **Platinum** (`PLAT`) for plat numerals only; **ducats/accent** for ducat
  values.
- **Contrast:** body/label text ≥ 4.5:1 on its background; muted/secondary
  ≥ 3:1. Any new colour pairing must clear this before it ships.

---

## 3. Typography

Eight roles, defined once in `theme.FONTS` as `(family-preference-chain, pt)`.
Use the **role**, never a raw font family or px size, via `label(text,
role=...)` / the `role="…"` QSS property. `size_of(role)` is the only place a
size is read.

| role | pt | use |
|---|---|---|
| `h1` | 18 | screen title (header) |
| `h2` | 13 | section headings, nav items |
| `body` | 11 | default text |
| `small` | 10 | secondary text, CAPS labels, dense rows |
| `price` | 11 | platinum / numeric emphasis |
| `mono` | 10 | console output |
| `icon` | 12 | inline nav/status glyphs |
| `msgbtn` | 15 | glyph-only action buttons |

The **only** sanctioned raw font size in `ui/` is the 30pt item-icon
placeholder glyph; treat any other raw `font-size:` as a finding.

---

## 4. Spacing scale — the rhythm

Five steps, defined once as `theme.SP_*`. **Every margin and layout spacing must
be one of these tokens** — no raw pixel spacing in layouts.

| token | px | when |
|---|---|---|
| `SP_SCREEN` | 24 | a screen's left/right content gutter (the widest step) |
| `SP_XL` | 16 | between major blocks; dialog & card outer margins |
| `SP_LG` | 10 | section padding, heading→content, screen top/bottom |
| `SP_MD` | 6 | between related rows |
| `SP_SM` | 4 | a control→its label, adjacent buttons |

Rule of thumb: **outer gutter `SP_SCREEN`, block gaps `SP_XL`, within a block
`SP_LG`, within a row `SP_MD`/`SP_SM`.** A screen's standard frame is
`margins(SP_SCREEN, SP_LG, SP_SCREEN, SP_LG)`.

---

## 5. Sizing conventions

Fixed pixel dimensions, used consistently. New surfaces reuse these; a one-off
value is a finding unless justified.

- **Input fields:** `max-height: 22px`; padding `2px 6px` (at 300% a 4px pad is
  12 real px — deliberately tight). `QComboBox` reserves `padding-right: 20px`
  for its painted `▾`.
- **Buttons:** default padding `5px 10px`; `wide` `5px 14px`; `size="small"`
  swaps to the small font. Glyph-only action buttons carry the `msgbtn` font.
- **Icon sizes:** item thumbnail **96×96** (listings) / the market-tab item
  imagery; inline glyph buttons **≈24–30px** fixed width (wiki `24`, whisper
  `28`, chrome nav `30`); the platinum gem `plat_icon(≈13–14)`; the crest
  `logo_pixmap(22)`.
- **Fixed data columns** right-align to constant widths so numbers line up down
  a list: market `COL_QTY=46 / COL_RANK=40 / COL_PLAT=46`; vosfor
  `COL_DROP=70 / COL_FARM=100 / COL_PRICE=78`; listings `LIMIT_FIELD_W=52 /
  OFFSET_FIELD_W=46`.
- **Reserved table height** = `TABLE_ROWS(12) × ROW_HEIGHT(26)` so an empty
  order book reads as "waiting", not "broken".
- **Min sizes / chrome:** window floor `900×560`; header height `44`; sidebar
  width derived (`max(150, widest-label + 64)`); settings nav `168`, label
  column `190`; slide-over drawer `320`; suggest popup `min 300`, max `8` rows.
- **Checkbox/radio indicators are size-stable:** unchecked = 14px box + 1px
  border (16px); checked shrinks content to 12px + 1px pad (still 16px). A
  control must **never change size** when toggled (guarded by
  `test_qt_sizing.py`).

---

## 6. Proportion, layout & mathematical grounding

Two different things live here, and conflating them is the mistake to avoid:
**adaptive layout** (how regions share space — a *constraint* problem) and the
**fixed detail values** the app is built from (radii, discrete paddings, step
counts — an *appearance* problem). Maths serves the second far more than the
first: it must never straitjacket a fluid layout, but it should keep fixed
details from being arbitrary.

### 6a. Adaptive layout — constraints
- **Default is uniform flex.** Regions that share space use equal `stretch=1`;
  fixed regions `stretch=0`; multi-column screens split evenly. Reach for a ratio
  only with cause.
- **Golden ratio (φ ≈ 1.618) as a layout constraint: sparingly, reactively,
  window-rooted.** Apply φ **only** to a *window-relative region proportion*
  where an even/arbitrary split reads as visibly off and φ demonstrably improves
  it — base unit from the current window size, so it scales. One intentional φ
  split beats sprinkling it. **Never force φ on:** search/entry fields (favour
  *length*), space-filling frames (favour *fill*), the spacing tokens (§4),
  control padding, or anywhere it would fight its neighbours. *(The 2026-08 audit
  looked for a φ split on every screen and found none warranted — that is the
  expected result, not a gap. The layout stays fluid.)*

### 6b. Fixed detail values — mathematical grounding
Adaptive elements must not be *constrained* by maths, but their fixed appearance
details should be *tuned* by it, so the UI reads as natural rather than picked by
feel. Draw discrete detail values from a coherent sequence:
- **The Fibonacci sequence (1, 2, 3, 5, 8, 13, 21, 34 …) is the well for discrete
  detail values** — corner radii, elevation/shadow sizes, tight in-grid paddings,
  icon-step sizes, and the count/steps of a set (e.g. how many weight stops).
  The scrollbar handle radius (`3`) is already a sequence member; keep new ones
  in the family.
- **For larger values, prefer a sequence-rooted base** — a big value should
  factor back to a sequence member (`sequence × factor`) rather than being a
  round decimal, so its root stays in the family (e.g. an 8-based value over a
  10-based one when the choice is free).
- **Derive related values by adding/subtracting sequence numbers.** Even from an
  *arbitrary* anchor, a family of sibling values for related assets/properties is
  reached by `anchor ± Fib`, so the **relationships** stay coherent when the
  anchor itself isn't a sequence member — the deltas carry the harmony, not the
  absolutes. E.g. from a 58px element, related sizes sit naturally at 50 (−8),
  45 (−13), or 79 (+21). This is the most usable of the three techniques for
  polishing an existing value into a coherent set.
- **Other constants are tools in the kit, not decoration:** φ for a deliberate
  proportion, π and self-similar / fractal ratios where a detail should feel
  organic. Reach for one where it genuinely makes a value sit right — **the test
  is always the eye**, and the layout underneath stays adaptive.

### 6c. The spacing scale is fixed
`SP_SCREEN/XL/LG/MD/SM = 24/16/10/6/4` is settled — already φ-rhythmed (its deltas
are the even sequence 2/4/6/8) — and is **not** re-derived; changing it touches
every screen. New *detail* values (6b) draw from the sequence; the *spacing*
scale stays as the five tokens.

---

## 7. Corners, borders, hairlines

- **Corner radius is 0 everywhere** — sharp lacquered edges — **except scrollbar
  handles (`3px`)**. A `border-radius` anywhere else in `ui/` is a finding.
- **Borders are 1px.** Field edge `FIELD_EDGE` (dim gold inlay); card edge
  `WFM_EDGE`; region separators `HAIRLINE`. Focus turns an edge `ACCENT`.
- **Separators:** a `hairline()` (1px `QFrame`) between stacked regions; a
  `vline()` (1px) between columns — a sibling, not a CSS border.

---

## 8. Icons & glyphs

- Dual-font, addressed by **semantic key** in `theme.ICONS` (Material Symbols
  Sharp primary, Segoe Fluent fallback) via `glyph()` / `glyph_icon()`. Never
  hardcode a codepoint; never a colour emoji.
- Two refresh glyphs carry meaning: **⟳ = a money action** (Reprice), **↻ = a
  plain data refresh**. Do not swap them.
- Controls sit **left** of their descriptive text. Dropdowns paint a `▾`; the
  Wiki affordance is the same glyph as the tab it opens.

---

## 9. Component patterns

- **Cards** (`surface="card"`): `WFM_CARD` fill, 1px `WFM_EDGE`, margins
  `SP_LG`, internal spacing `SP_MD`. A card is a self-contained unit; its
  controls live on it.
- **Content container** — the app's primary framing device, one and the same
  `surface="card"` box used everywhere a screen's body needs to read as an
  object on the page: the Home status/tools boxes, every Settings section, and
  the My Listings / Market / Vosfor bodies. Rules that keep it consistent:
  inset the box from the screen by `SP_SCREEN` (its border aligns to the page
  gutter and the screen's h1 header sits above it), give the box `SP_XL` inner
  padding so its `WFM_CARD` fill frames the content and the border actually
  shows (**a child laid flush to a `surface="card"` box overpaints the 1px
  border — always leave padding**), and title it with an h2 as the first child
  when it needs a heading (e.g. Vosfor's "Arcane Collection Progress"). One
  screen may hold several (Vosfor = planner + collections).
- **Buttons** carry intent via `kind`: `money` (filled gold), `danger` (deep
  red), `flat` (transparent), default (raised panel). `size="small"` /
  `wide="true"` tune density.
- **Nav rows** own their own highlight (the row, not the button, paints active),
  with the painted gold `Finial` marking the current screen.
- **Tabs.** The active sub-tab is marked with a 2px underline. On the shell this
  is gold (the active-nav convention). **On the warframe.market screen the tabs
  carry per-tab identity accents — Market = WFM teal, Contracts = WFM pink — a
  DELIBERATE warframe.market-parity cue players recognise** (a sanctioned,
  WFM-screen-scoped exception to the single-gold marker; do not "fix" it to gold).
  Where such a screen needs a further tab accent, prefer a **WFM-family colour
  over gold**, so gold stays reserved for money / active-nav.
- **Dialogs** (`QDialog`): outer margins `SP_XL`, spacing `SP_MD`; a sensible
  `setMinimumWidth` (login `430`, goodbye `460`); primary action is `kind=money`
  and the default button.
- **Overlays** slide in from the right (`SlideOver`, 320px, `OutCubic` 180ms)
  over a `SCRIM`; the scrim catches outside-clicks.

---

## 10. Enforcement (invariants — keep these mechanical where possible)

The guide is a **guardrail**, not a suggestion. Each rule below should be
checkable; mechanical ones get a test in `tests/`.

| invariant | how it's enforced |
|---|---|
| No raw `#hex` in `data/ui/*.py` | `qss.py` design + `test_qt_shell.py` sheet check; extend to all of `ui/` |
| Every sheet colour traces to a `theme` token | `test_qt_shell.py` |
| Controls don't resize on state change | `test_qt_sizing.py` (checkbox); widen coverage |
| No `border-radius` outside the scrollbar rule | *candidate* `test_style_guide.py` |
| No raw `font-size:` outside the 30pt placeholder | *candidate* `test_style_guide.py` |
| Layout spacing uses `SP_*` tokens, not raw px ≥ 4 (0–3 allowed for tight detail) | `test_style_guide.py` (lints `setContentsMargins`/`setSpacing`/`addSpacing` literals) |

---

## 11. Changing this guide

The guide leads; the code follows. To change a rule: update this file **and** the
token/enforcement in the same change, so the three (guide, tokens, tests) never
drift — that drift is the vibe-coding failure mode this document exists to end.
