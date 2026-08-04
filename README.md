# Warframe Toolbox

A small desktop host for warframe.market trading tools. A **custom title bar**
(app name + minimise / maximise / close) tops a persistent **header** (the
current section + your pinned account widget + online-status toggle), above a
left **sidebar** that switches between apps, which open in the content area
beside it. **Home** is the app gallery; **My Listings** manages your orders;
registry tools (such as the **API Status** check on the Settings > Data >
Market page) stream their output into a console.

**The host owns the account AND all networking.** You link your
warframe.market account once in the app. Your password is used for a single
sign-in request and never stored — the cached session (`wfm_session.json`)
holds the token (JWT), username, platform, and the login email (kept only to
prefill the sign-in form), and the JWT never leaves the host process. Every API call
a tool makes is routed through the host's local gateway, which injects the
session, identifies the client, and enforces **one shared rate limit across
all running tools**. Each tool runs in its own process, so development and
runtime stay segregated: a broken tool can't take down the host or the
session.

**Tools cannot run standalone.** Launched outside the host, a tool finds no
gateway in its environment and exits immediately with an error — by design,
since it has no credentials and no API access of its own.

Built to grow: adding a new tool is a single entry in `registry.py` (name,
icon, script) — a sidebar item and a Home card appear automatically.

## App shell

- **Title bar** (Windows): a themed replacement for the OS title bar — the
  Warframe crest logo + "Warframe Toolbox" on the left, and minimise /
  maximise (restore) / close on the right. Drag it to move the window,
  double-click to maximise; a corner grip resizes. The window remains a
  fully managed app window — only the native caption is stripped from its
  Win32 style — so the taskbar button, **alt-tab**, and minimise animations
  all behave natively (icon: `assets/logo.ico`). On non-Windows systems the
  native title bar is used.
- **Header** (always on top): the current section name (Home / My Listings /
  …), your pinned account widget (username · session state · Link/Unlink), and
  an **online-status toggle** — Online / In-game / Offline. Status on
  warframe.market is presence-based over a websocket
  (`core/presence.py`, `wss://ws.warframe.market`): Online/In-game open an
  authenticated socket and set your status so your orders sort to the top of
  their band; Offline closes it. It starts Offline each launch.
- **Sidebar** (always visible): Home, My Listings, Market, Vosfor, the three
  web apps (WF Live, Wiki, Overframe), then one entry per registry tool
  (API Status excepted — it lives on the Settings > Data > Market page),
  with Settings last. Each item carries a Segoe Fluent Icons glyph (no color
  emoji anywhere in the app); the active item is marked by the gold
  **Orokin finial** on its left edge. Click to switch apps in the content
  area.
- **Content**: the selected app. Home is the app gallery — a scrolling grid
  with a card for every app **except Settings and API Status** (both live
  inside Settings); web-app cards come from the same table as their sidebar
  entries. Each card's action button sits in its bottom-right corner, and
  reads **Visit** for a web tab, **Open** for an app.

**Nothing loads until you open it.** Home is the only view built at launch;
every other app builds on its first visit and then stays alive for the rest
of the session, so switching back and forth never reloads anything.

## Design: "Orokin Treasury"

The visual system (defined at the top of `wf_market_helper.py` as the token
constants + style guide) frames the app as a Tenno's treasury ledger — a
void-black lacquered cabinet in warm near-blacks (umber, never blue), trimmed
with a single metal, **aged gold** (`ACCENT #c9a860`):

- **Gold is inlay, never plating** — it appears only as hairlines (titlebar
  trim, console rule), the focus ring/caret of inputs, the active-tab
  underline, the **finial** (active nav + the rule under every page title),
  and **money-action buttons** (Reprice, Sold, Sign in). All other buttons
  are quiet panel-toned secondaries. WARN is pushed to orange so it can
  never be mistaken for gold.
- **Platinum reads as itself** — plat numerals everywhere are set in the
  `price` font role (Bahnschrift SemiBold's tabular DIN digits, so money
  columns align) and colored `PLAT #cdd5da`, the cool silver of the gem icon.
- **Typography**: Bahnschrift SemiBold (DIN industrial) for h1/h2/price,
  Segoe UI for body/small, Cascadia Mono for the console, Segoe Fluent Icons
  for glyphs — all resolved by a startup probe with safe fallbacks.
- **The webview is a lit pane**: embedded sites sit in a deepest-black
  gutter with a 1px hairline frame, so warframe.market's cool blue-gray
  reads as a window set into the cabinet rather than a clash; the WTS plum /
  WTB blue badges and site-exact pink stay recognizable on the cards.
- **My Listings** shows the *ledger line* in its header: total plat listed
  across your sell orders, underscored with a 1px gold rule.
- All text/background pairs hold WCAG ≥ 4.5:1 (muted ≥ 3:1); scrollbars are
  ttk-themed to the palette (bone thumb, gilded under the pointer).

## Market

A read-only browser of warframe.market itself, in three tabs:

- **Market** — search any of the ~3800 tradeable items (an autocomplete
  dropdown suggests as you type: arrows browse it without closing or
  searching, Enter or a click picks and fills the search box) and see the
  live order book the way the site shows it: sellers cheapest-first, buyers
  highest-first, zebra-striped rows, status dots (in-game / online /
  offline), reputation, quantity and price. Filters: **Online only** (on by
  default) and **In-game only**. Your own orders are highlighted. Every row
  has a **✉** button that copies a ready-to-whisper trade message
  (`/w {user} Hello. I would like to purchase … / I have … available for
  …p. (warframe.market)` — templates editable in Settings > Market >
  Messaging). The **☆ Watch** button bookmarks the item onto the Watchlist.
- **Contracts** — the site's auction house: riven and lich contracts for any
  weapon (weapon pickers come from the API's own riven/lich weapon indexes),
  sorted by price either way. Riven rows show MR / rerolls / polarity and
  the attribute spread; lich rows show element, bonus damage, ephemera and
  quirk. Read-only — bidding stays on the site.
- **Watchlist** — your bookmarked items. One click **Open** jumps back to the
  full order book (no re-searching); **↻ Refresh prices** fills in each item's
  best online sell/buy. Persisted in `wfm_watchlist.json`.

Works with or without a linked account (public reads need no session).

## Vosfor

A planner for **Arcane Dissolution**: which Arcane Collection is worth
spending Vosfor on. Each of the nine collections (Cavia, Duviri, Eidolon,
Holdfasts, Höllvania, Necralisk, Ostron, Solaris, Steel) is shown as a
checklist of its arcanes grouped by rarity — ✔ maxed, ◐ owned but not
maxed, ✗ missing — with a progress bar and a **✔ COMPLETE** badge when
every arcane is maxed.

Each arcane row shows a monospace **copies fraction** — owned single
arcanes over the number needed to max (`05/21`). A ranked arcane counts as
the copies it embodies, not one: rank costs are cumulative 1, 3, 6, 10,
15, 21, so a rank-5 (maxed) arcane is `21/21` and a rank-4 is `15/21`
(6 more to max). Owned unranked spares add on top.

Above the list, a **recommendation** ranks all collections by *expected
still-needed copies per 200-Vosfor purchase*. A purchase yields 3 arcanes
drawn independently; arcane *i* is hit with probability `q_i` per pull, so
after *k* packs you expect `3·k·q_i` copies of it — capped at the copies
you still need. Summing over every not-yet-maxed arcane gives each
collection's value, and it flattens (diminishing returns) as arcanes fill
toward max. Completed collections score 0 and sort last.

**Purchase plan.** Enter **Your Vosfor** and the planner allocates your
budget (200 Vosfor/pack) greedily — each pack goes to whichever
collection's *next* pack yields the most needed copies, recomputed as pools
shrink — so it concentrates on the best collection, then splits to the
runner-up(s) once that one's value drops below theirs (e.g.
`Höllvania ×45 · Ostron ×30`). Without a budget it suggests how many packs
of the top collection to buy before another overtakes it.

**Acquisition-method weighting.** Two checkboxes — **Farming** and **Market
price** — change *what a pack is worth*, because an arcane you can easily
get another way isn't worth Vosfor:
- *Farming* discounts arcanes by how easily they **drop**, combining the
  WFCD drop chance with how often the **source actually spawns** — a 5% drop
  off an Eidolon (three per night) or a Steel Path Acolyte (one per mission)
  is far harder to farm than the same 5% off a common enemy, so encounter
  cadence shifts the score. Standing-shop-only arcanes floor near-zero (a
  real grind); open-world/mission drops score high. Each row's farm label
  has a hover tooltip naming the limiting source (Acolyte-gated, Eidolon
  night, Open-world, …). Turn it on and easy-to-farm collections (Höllvania)
  drop down the ranking while standing-locked ones (Solaris, Ostron) rise.
- *Market price* discounts arcanes that are **cheap to finish** on
  warframe.market — weighing the total buy-out cost (`price × copies still
  needed`), not one copy, because a 2p arcane you need 21 of is 42p. Prices
  are the cheapest online sell for the unranked copy, fetched live through
  the host's own market client (same rate limiter; the gateway is the
  tool-subprocess road only) and cached to `vosfor_prices.json` (first enable runs a
  one-time background sweep with progress). **↻ prices** re-runs the sweep
  on demand, and the row shows how old the cached prices are. A buy-out under ~60p is cheap
  enough that the market beats Vosfor; the row shows that total, teal when
  it's the better option.

With both on, an arcane's Vosfor worth is the difficulty of the *easiest*
alternative (you'd use that instead). Every arcane row shows its farm
rating and buy-out cost so you can see why the plan weights it. All method
choices and your Vosfor balance persist between sessions.

Data sources:
- **Collections + drop chances** — the wiki's Dissolution tables, cross-
  referenced against WFCD item data so every arcane carries its internal
  path and copies-to-max (`vosfor_collections.json`, 146 arcanes).
- **Your arcanes** — read **read-only** from AlecaFrame's inventory cache
  (`%LOCALAPPDATA%/AlecaFrame/lastData.dat`, AES-128-CBC, decrypted in
  process by `core/aes.py` — pure Python, no crypto dependency shipped and no
  OS binding either; `core/arcane_inv.py`).
  Nothing is ever written to AlecaFrame or the game. The parsed inventory is
  **cached** to `arcane_inv.json`: opening Vosfor re-reads **only when
  AlecaFrame's file has actually changed** (a timestamp check — switching
  apps stays instant), a fresh cache loads with no decrypt at all, and the
  last good inventory survives even if AlecaFrame disappears (shown as
  *cached · AlecaFrame unavailable*). **↻ Update inventory** still forces a
  re-read on demand and reports whether anything changed.
- Without AlecaFrame, every arcane starts unchecked and you **tick them off
  by hand** (click an arcane to cycle maxed / clear; saved to
  `vosfor_owned.json`). Manual check-offs always override the auto-read.

## Web apps (WF Live · Wiki · Overframe)

Three sidebar entries render live websites inside the content area:

- **🗓 WF Live** — <https://browse.wf/live> (world state / weekly resets)
- **📖 Wiki** — <https://wiki.warframe.com/>
- **🛠 Overframe** — <https://overframe.gg/>

How it works (`core/webhost.py`): the pages run in Microsoft **Edge
WebView2** (ships with Windows 11) driven by the `pywebview` package. All
three browser *windows* are created at app launch — pywebview builds later
windows through an existing one, which breaks once that one has been
re-parented into Tk, so they have to come up as a batch — but they sit on
`about:blank`. **No site is fetched until you open its tab.** From then on
the browser stays alive for the whole session: while a web app is open its
browser is re-parented into the Tk content pane, and when you switch away it
parks in a hidden holder frame — still running — so coming back is instant
and the page keeps its state (scroll position, logins). Cookies and cache
persist across launches in the data home's `webengine/` profile, managed on its own settings
page (below). If `pywebview` isn't installed the pages show an **Open in
browser** fallback instead (`pip install pywebview` to enable embedding).

**Wiki links.** Item names in My Listings, the Market order book, the
Watchlist and the Vosfor arcane checklists carry a small 📖 glyph. Clicking
it opens that item's article **in the Wiki tab** — never an external
browser, so you keep the ad blocker and the tab's state. Market listing
names aren't wiki titles ("Rhino Prime Set" is a listing; the article is
"Rhino Prime"), so `core/wiki.py` peels set/blueprint/component suffixes off
Prime listings before building the URL.

**Ad blocker** (on by default, two layers, `core/webhost.py` — browser
extensions can't be loaded in this environment, so the blocker is native):

1. **Network**: every request passes a WebView2 `WebResourceRequested`
   handler; requests to known ad/tracking hosts are answered locally with
   a 403 and never sent. Each browser starts on `about:blank` and only
   navigates to its real site **after** the filter is armed, so nothing
   slips through during launch. Built-in host list (AdThrive/Raptive —
   overframe.gg's ad network, scraped from its live DOM — plus the ad
   exchanges, video monetizers and trackers). To extend it, create
   `app/adblock-hosts.txt` yourself (one host per line, `#` comments) —
   it does not ship, and is read at launch if present.
2. **Cosmetic**: a script injected at document start (and on every
   navigation) **removes ad containers from the page** (removal blocked →
   forced to 0×0): a selector list for AdThrive/Raptive + Kargo, Google
   GPT/AdSense, Playwire and generic ad-slot names, PLUS a heuristic that
   walks up from every iframe — ad-network src or ad-named ancestor →
   the topmost ad container dies, so renamed/new ad units are caught
   without a selector update (content embeds like the wiki's YouTube
   players are untouched). Sweeps run from a MutationObserver and a 2s
   timer, which — unlike requestAnimationFrame — keeps firing while a
   browser is parked hidden.

Toggle + per-session blocked counter live in Settings > Data > WebView.

**Per-site tweaks** (`SITE_TWEAKS` in `core/webhost.py`): CSS injected the
same way as the ad filter, per site. Overframe currently hides the site
header's Download App button and Discord/Twitter links and centers the
home page's content column (the space its ad sidebar used to reserve).
Selectors use stable attributes (hrefs) because the site's class names
are build-hashed.

## Settings

The old Profile app was migrated here and retired. A settings tree on the
left picks a page:

```
Settings
▸ Display  ─ Window
▸ Data     ─ Warframe / Market / WebView / WF Toolbox
▸ Market   ─ Messaging
```

Sections are collapsible: children are hidden by default, the ▸ arrow
toggles a section, and clicking a header expands it **and** opens its first
page. The tree follows the app's style guide (top of `wf_market_helper.py`):
"SETTINGS" is a small-caps title, categories are headings, subcategories are
plain text — and every control sits left of its descriptive text.

- **Market > Messaging** — edit the two ✉ clipboard templates used by the
  Market browser (buying from a WTS row / selling to a WTB row).
  Placeholders: `{user}`, `{item}`, `{price}`; the default `/w {user} `
  prefix makes the pasted text a whisper in-game.

- **Display > Window** — launch fullscreen (maximized); window size (a wrap-around
  spinner over standard sizes from 640×480 to 2560×1440, applies
  immediately); which monitor to open on (spinner clamped to the displays
  actually detected, applied at launch); **launch on Windows startup**
  (current-user registry Run entry, no admin); **launch the Toolbox when
  Warframe starts** (a tiny background watcher — `warframe_watcher.pyw` —
  starts with Windows, notices the game process by its own executable name,
  and opens the Toolbox; nothing machine-specific, so the folder works on
  any PC it's copied to); **send to tray when minimized** (minimize
  hides the window to the notification area; click the tray icon to
  restore — `core/tray.py`, no extra packages); and a read-only **display
  scaling** read-out. The Toolbox deliberately renders unscaled (the
  embedded browser would otherwise flip the whole process's DPI mode
  mid-session and shrink the UI), so on a scaled display Windows stretches
  it — and scrolling is moved in whole device pixels to keep that stretch
  from smearing rows.
- **Data > Warframe** — the game install location with Auto-detect / Browse…
  (stored in `wf_local.json`; every game-file access in the app is strictly
  read-only — see `core/wf_local.py`), plus your **Warframe.com account**:
  the public account ID + platform that let the Toolbox read your profile
  (mastery rank, loadout, progression) straight from Warframe's own servers,
  with a Connect dialog that captures the ID automatically.
- **Data > Market** — your warframe.market profile: connected account,
  session validity, expanded online status (state **and** socket connection,
  updates live), active order counts (WTS / WTB), the **Unlink**
  button, and the embedded **API status** check (▶ Run check streams into a
  console; still a gateway-routed subprocess, still read-only). The header
  keeps **Link account** whenever no account is linked.
- **Data > WebView** — the embedded web apps' browser data: sizes on disk
  (all web data / cache / cookies), the **ad blocker toggle** with a
  per-session blocked-request counter, and three clear buttons — **Clear
  cache** (stays signed in), **Clear cookies** (signs you out of the web
  apps), and **Clear ALL web data** (`goodbye`-gated full profile wipe).
  Clearing works live via WebView2's own `ClearBrowsingDataAsync` — no
  restart needed — with a disk fallback when the browsers aren't running.
- **Data > WF Toolbox** — every file the app generates about you, listed with
  size and purpose. Click a name to open it in your default editor; ✕ deletes
  a single file (deleting the session file does a proper unlink). Below:
  **Delete cached images** (empties `cache/thumbs/` — downloaded item
  images only, never program assets) and **Delete ALL user data** (unlink +
  wipe every generated file, watchlist, floors/caps, settings, startup
  entry). Both buttons are pinned to the bottom of the page, and both wipes
  require typing **`goodbye`** into a centered confirmation dialog.

## Layout

The repository is pure code and shipped assets — it can be cloned, pulled,
zipped or run from a flash drive without ever carrying personal data. Every
file the app generates about you lives in a per-machine data home instead:
`%LOCALAPPDATA%\WarframeToolbox` (a gitignored `userdata/` folder inside the
project opts a dev clone into portable data; see `docs/DEVELOPMENT.md`).

```
Warframe Toolbox/
├─ Warframe Toolbox.pyw       # double-click launcher (no console) — start here
├─ update.bat                 # pull the latest, then launch (the beta channel)
├─ requirements.txt           # deps: requests, websocket-client, PySide6
├─ README.md                  # this file
├─ CLAUDE.md                  # working agreements, for AI assistants
├─ docs/                      # ARCHITECTURE, DEVELOPMENT, STYLE_GUIDE, OVERWOLF_PLAN
├─ tests/                     # 33 plain-script test files (run_all.py)
├─ overwolf-companion/        # Overwolf companion app template (pending approval)
└─ app/
   ├─ registry.py             # the tool catalogue; add new tools here
   ├─ warframe_watcher.pyw    # background watcher: opens the app with the game
   ├─ vosfor_collections.json # shipped Vosfor data (drop chances, paths)
   ├─ core/                   # backend + every UI-agnostic rule
   │  ├─ paths.py             #   WHERE user data lives (the one module that knows)
   │  ├─ version.py           #   the single source of the app version
   │  ├─ session.py           #   account link: login, token cache, validation
   │  ├─ market.py            #   authenticated warframe.market v2 client
   │  ├─ gateway.py           #   local API gateway — tools' only road to WFM
   │  ├─ presence.py          #   online-status websocket (online/ingame/offline)
   │  ├─ wf_inventory.py      #   inventory provider seam (companion → AlecaFrame)
   │  ├─ wf_profile.py        #   DE public profile API (mastery, loadout)
   │  ├─ wf_local.py          #   READ-ONLY reader for the game's local files
   │  └─ ...                  #   see docs/ARCHITECTURE.md for the full map
   ├─ ui/                     # the PySide6 front end (app, home, market, ...)
   ├─ tools/api_check/        # read-only API health check (runs via gateway)
   └─ assets/                 # fonts (+ licenses/), window icon

%LOCALAPPDATA%\WarframeToolbox\        (created on first launch)
   ├─ wfm_session.json        # cached session (created on link; delete = unlink)
   ├─ wfm_settings.json       # app settings
   ├─ wfm_listings.json       # My Listings prefs: floor/cap offsets + overrides
   ├─ wfm_watchlist.json      # Market watchlist  (+ contract watchlist)
   ├─ wf_local.json           # Warframe install path override
   ├─ vosfor_owned.json       # Vosfor planner manual check-offs (+ cached prices)
   ├─ cache/thumbs/           # downloaded item images (Settings can purge)
   ├─ wf_data/                # collected game data (profile, worldState, export)
   ├─ webengine/              # embedded browser profile (cookies, logins)
   └─ inventory.json          # written by the Overwolf companion, when present
```

> Under **Microsoft Store Python** the data home is transparently redirected
> into the Python package's `LocalCache` folder (MSIX virtualization) — the
> app behaves identically, but Explorer won't show the files at the path
> above. Details and the fix in `docs/ARCHITECTURE.md`.

## Host ↔ tool contract

Tools launched by the host receive:

| env var             | meaning                                          |
|---------------------|--------------------------------------------------|
| `WFM_GATEWAY`       | the host gateway, e.g. `http://127.0.0.1:51234`  |
| `WFM_GATEWAY_TOKEN` | per-launch secret; sent as `X-Gateway-Token`     |
| `WFM_INGAME_NAME`   | the linked account's in-game name (if linked)    |
| `WFM_PLATFORM`      | pc / xbox / ps4 / switch                         |

A tool calls the gateway with the same paths as api.warframe.market
(`GET /v2/orders/item/...`, `PATCH /v2/order/...`) plus the token header. The
gateway rejects wrong tokens, non-localhost callers, and any path outside
`/v1/`–`/v2/`; it injects the User-Agent, platform headers, and the session's
Authorization (**`Bearer <token>` for v2**, `JWT <token>` for v1), and spaces
all upstream calls on one shared limiter. No `WFM_JWT` is ever exported — the
token in a tool's environment is useless outside the running host.

> **API note:** warframe.market's v2 API requires `Authorization: Bearer …`.
> The v1 sign-in call returns the token prefixed with `JWT `; the host strips
> that and re-wraps per API version. The old v1 profile endpoints
> (`/v1/profile/{name}/orders`) were **retired and now 404** — everything the
> tools and the host read/write uses v2 (`/v2/me`, `/v2/orders/user/{id}`,
> `/v2/orders/item/{slug}`, `PATCH /v2/order/{id}`).

Mark a tool `requires_session=True` in `registry.py` and the host refuses to
launch it without a linked account. Tools without it (e.g. API Status) run
unauthenticated; the gateway still adds the session to their calls when one
is linked.

## Running

Requires Python 3.11+ (python.org build recommended — see the Store-Python
note in `docs/ARCHITECTURE.md`).

```
pip install -r requirements.txt
```

Then just **double-click `Warframe Toolbox.pyw`** — the `.pyw` extension runs
under `pythonw.exe`, so the app opens as a standalone window with no terminal
behind it. (If a startup error ever occurs before the window opens, it's
written to `launch-error.log` in the data home and shown in a dialog, since
there's no console to print to.) The app **keeps itself up to date**: at
launch it quietly pulls the newest version from its git remote (toggle in
Settings > Display); beta testers install via the generated installer (see
`docs/DEVELOPMENT.md`), and `update.bat` remains as a manual fallback.

An `.exe` build (PyInstaller onedir) is planned; see `docs/DEVELOPMENT.md`.

## Getting started

1. Double-click `Warframe Toolbox.pyw`.
2. Click **Link account** (top right) and sign in once. The session is cached
   and verified in the background on every launch — you won't be asked for your
   password again until the token actually expires (~60 days).
3. Open **Settings > Data > Market** and press **▶ Run check** (the API
   Status check) — confirms the warframe.market API is up and the linked
   session works, before anything touches your orders.
4. Open **My Listings** to manage and reprice your sell orders.

## My Listings

A host-native, **tabbed** dashboard of your account's orders, styled after
warframe.market's own listing cards (the host owns the account, so this lives
in the app itself, not as a subprocess tool). The view **builds on its first
visit and then persists across app switches** — the first open fetches your
orders (market best-prices fill in progressively behind them), and every
visit after that is instant and keeps whatever you were looking at; ↻
Refresh re-fetches on demand (the cache is rebuilt on link/unlink). The header (Back / title /
Refresh) is fixed; **Refresh reloads every tab without switching you off the
current one**. Tabs:

- **WTS** — your sell orders.
- **WTB** — your buy orders (mirror logic: Reprice matches the *highest*
  online buyer, never overbids, never above the item's **cap**).
- **Contracts** — placeholder, feature in development.

WTS and WTB each carry their own controls: default floor/cap offset, search,
sort, show filter, **bulk visibility** (👁 Show all / ◌ Hide all — sets every
order on the tab visible/hidden on the market, confirms first), listing
count, and Reprice all. Each card shows the item's icon (fixed 96×96 box,
aspect preserved), the wts/wtb tag inline before the title, quantity, price
with a platinum gem icon, and the **market best** (⚠ warning triangle when
you're beaten — undercut on WTS, outbid on WTB), with the same actions the
site offers:

- **✔ Sold** — mark one sold (closes the listing when the last unit goes;
  the sale is recorded on your profile).
- **🖉 Edit** — set price, quantity, visibility, and the item's floor in one
  dialog. A price you set by hand becomes the item's new *reference price*.
- **+1 / −1** — adjust the for-sale quantity.
- **👁 Visible / Hidden** — toggle the listing's visibility.
- **🗑** — delete the listing outright (confirms first; no sale recorded).
- **⟳ Reprice** — match the lowest online seller exactly (never undercuts),
  never below the item's floor, in a single write. The write also refreshes
  the order so it sorts to the top of its price band.

**Floors are absolute platinum.** By default an item's floor derives from its
reference price — the posted price when the session started, or the last
price you set by hand — plus the global **± offset** in the header (default
−2): `floor = reference + offset`. Typing a value into a card's floor field
overrides it for that item (shown as *set*, persisted in
`wfm_listings.json`); clearing the field returns to *auto*.

The top bar has **Refresh** (pull latest orders + market lows) and **Reprice
all** (reprice every listing once — it confirms first, since it writes real
price changes), plus a **Search** box that scrolls to and outlines the first
matching title as you type, **Sort** (Name / Price / Quantity / Market low,
▲/▼) and a **Show** filter (All / Visible / Hidden). Nothing loops.

## Tools

### API Status (embedded in Settings > Data > Market)
Read-only health check of every endpoint the tools depend on: the v2 item
index, the v2 order book, the signin surface, and — when an account is linked —
an authenticated v2 read of your account (`/v2/me`) and your own sell orders.
Never writes. Run it after any WFM update and before your first live run.
The script still lives at `tools/api_check/` and runs as a subprocess; only
its button moved onto the Settings > Data > Market page.

The identifying `USER_AGENT` lives in one place, `core/session.py` — edit it
there before heavy use (WFM's rules require identifying your client).

## Adding a new tool

Drop your script under `tools/<name>/` and add a `Tool(...)` entry to
`registry.py`. Its `flags` become checkboxes and its `args` become text fields
in the runner. No changes to `wf_market_helper.py` needed.
