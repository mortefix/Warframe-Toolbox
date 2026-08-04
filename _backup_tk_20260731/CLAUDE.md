# CLAUDE.md

Warframe Toolbox — a **PySide6** desktop host for warframe.market trading
tools (Windows-first; the Qt front end is the portable one). One host process
owns the account, all networking, and the persistent chrome; screens load into
a `QStackedWidget`. No build system, **not a git repo** — see the warning at
the end of this file.

## Commands

```bash
pip install -r data/requirements.txt   # requests, websocket-client, PySide6-{Essentials,Addons}
python "Warframe Toolbox.pyw"          # normal launch (Qt; errors -> data/launch-error.log)
python "Warframe Toolbox.pyw" --tk     # the legacy Tkinter front end
python -m py_compile data/ui/*.py data/core/*.py   # syntax sanity check
python tests/run_all.py                            # 16 test files, no pytest needed
```

Requires Python 3.11+. QtWebEngine (PySide6-Addons) carries the three embedded
web apps; without it those tabs fail to build and the rest of the app is
unaffected.

## Architecture

```
Warframe Toolbox.pyw        launcher: chdir to data/, run host, log crashes
data/wf_market_helper.py    LEGACY Tk host (~5500 lines), reachable via --tk
data/registry.py            tool catalogue: one Tool() entry = sidebar item + Home card
data/warframe_watcher.pyw   standalone watcher process (launch Toolbox with the game)
data/core/                  ALL backend AND all UI-agnostic rules:
                            session, market, gateway, presence, webhost, config,
                            wf_local, arcane_inv, arcane_market, aes, vosfor,
                            wiki, tray, assets, theme, webapps, floors,
                            repricer, vosfor_vm, listings_vm
data/ui/                    THE FRONT END: app (shell), home, listings, market,
                            vosfor, settings, web, runner, dialogs, overlay,
                            suggest, icons, qss, widgets, work, bridge
data/tools/<name>/          tool scripts, run as subprocesses through the gateway
tests/                      plain-script test suite; `python tests/run_all.py`
```

**Two front ends.** Qt (`ui/`) is the default and complete. Tk
(`wf_market_helper.py`) is kept for one release behind `--tk` as a way back.
`core/` is shared and may **never** import from either — the dependency runs
one way, and that is what made the second front end affordable at all.

Qt-specific traps, every one of which has cost real time here:
- A bare `QWidget` ignores a QSS `background` unless `WA_StyledBackground` is
  set. Use `ui.widgets.panel()`, never a raw `QWidget`, for a coloured surface.
- Qt does **not** repaint on `setProperty()`. Every state property (`active`,
  `level`, `kind`) must be followed by `ui.widgets.restyle(w)`.
- `ui/qss.py` is generated from `core.theme`. **Never type a hex digit in it** —
  a test asserts every colour in the sheet traces back to a token.
- In a style sheet, `width`/`height` set the **content** box; border and
  padding are added on top. `width: 14px` plus `padding: 2px` when checked
  made every checkbox grow 4px on click.
- A `QStackedWidget`'s minimum size is the **maximum** of its pages'. One
  unwrapped label reported a 1440px minimum and pushed the whole window's
  floor to 2173px, wider than the desktop — which is why "window size"
  appeared to do nothing. Long labels get `setWordWrap(True)`; the shell also
  pins `setMinimumSize(MIN_WIDTH, MIN_HEIGHT)` so no page can hold the window
  hostage.
- Connect signals to **bound methods, not lambdas**. Qt drops a queued signal
  whose receiver has been deleted, and for a bound method the receiver is the
  widget — a lambda has none, so it still fires during teardown and touches a
  dead C++ object.
- Icons are **Material Symbols ligatures** (`core.theme.ICONS`), rendered in
  the shipped font. A label showing one must keep `role="icon"`: strip the
  role and it draws the WORD. Grey it with colour, never by re-roling.
- `ui.icons.icon()` draws into a logical rect, not `pm.rect()` — a pixmap's
  rect is in physical pixels and at 300% scaling centres the glyph off-canvas.
  A blank QIcon is not a null one, so `isNull()` will not catch it.

**Design philosophy (the standard for all changes):**
1. Persistent chrome — custom title bar + header + sidebar built once in
   `App.__init__`, never rebuilt; only `App.content` children change.
2. Core owns backend AND rules — networking/auth/caching/file-I/O live in
   `data/core/*`, and so does every decision, derivation and piece of copy
   that does not need a widget. A view class **places widgets and nothing
   else**. If you can write it without touching Tk, it does not belong in
   `wf_market_helper.py`. Concretely, already extracted:
   - `theme.py` — every colour, spacing step and font role. The host
     re-exports them, so its ~638 `bg=`/`fg=` sites are unchanged. **Never
     redefine a token locally**; a shadowing assignment silently forks the
     design system.
   - `floors.py` — `Limits` owns the baseline + overrides + offset as ONE
     object. Do not split them and do not write `app.listing_baseline` or
     `prefs["floors"]/["caps"]` anywhere else.
   - `repricer.py` — the reprice decision + `better_than(side, …)`, which is
     the single source for the sell/buy asymmetry (a seller is beaten by a
     LOWER price, a buyer by a HIGHER one).
   - `listings_vm.py` — `SIDES` holds every WTS-vs-WTB difference except
     colour. Add side-aware behaviour there, not as a new `if side ==`.
   - `vosfor_vm.py` — every row derivation. Returns severity as
     `"ok"`/`"warn"`, **never a colour**; the front end maps it via `theme`.
   This is what makes the PySide6 port affordable: a screen's behaviour is a
   `core/` module, its view is placement.
3. Apps in container — each sidebar key resolves to a Frame packed into
   `App.content` (`_view_for`), or re-parents a persistent WebView2 browser.
4. Home widgets — every app gets a Home card EXCEPT Settings and API
   Status (both live inside Settings > Data > Market).
5. Inventory data (AlecaFrame) is cached to disk; apps that need it refresh
   on open (mtime-gated); manual refresh buttons remain.
6. Nothing loads at launch but Home. An app builds on first visit and then
   stays alive for the session, so tab-hopping never reloads. Web tabs get
   their windows up front (a pywebview constraint) but load no site until
   visited.

**View lifecycle** (`App.navigate`): **Home is the only view built at
launch**; every app builds on first visit. `listings`, `vosfor` and `market`
are the persistent views (`App._persistent` — pack_forget on switch-away,
re-packed on return), so tab-hopping never reloads. `listings` and `market`
are account-scoped and dropped by `_drop_account_views()` on link/unlink —
`market` bakes `market_any()` into all three of its tabs at build time.
`home` stays rebuilt (it bakes the account link state into every card; its
scroll offset lives on `App._home_scroll`) and `settings` stays rebuilt
(`MarketDataPage` owns an `api_check` subprocess torn down on `<Destroy>`).
A `WebAppView` must `park()` its browser BEFORE its frame is destroyed
(Win32 kills child windows with their parent) — that is why the `park` test
comes FIRST in `navigate()`'s teardown chain, and why no web key may join
`_persistent` without reordering it. Web tabs don't need to: the browser
itself persists in `web_holder`, so only the thin Tk wrapper is rebuilt.

Two hooks, called by `navigate()`:
- `on_show()` after packing (and after an `update_idletasks()`, so
  `winfo_ismapped()` is true) — cheap staleness checks, never unconditional
  refetches; re-claim the wheel here.
- `on_hide()` on the outgoing view while it is still packed and mapped,
  before park/pack_forget/destroy. **Stop, not save**: cancel every repeating
  or idle `after` job, drop tooltips and suggestion lists, release the wheel.
  Must be idempotent (show/hide can fire back-to-back) and must not raise.

Views may also define `update_session()` / `update_presence()`; the shell
calls them via getattr duck-typing on `_active_view` only.

## Style guide — "Orokin Treasury"

Token constants + full rules live at the TOP of `wf_market_helper.py`
(lines ~92–276). Reference them for every UI change. Non-negotiables:
- Gold `ACCENT #c9a860` is inlay, never plating: hairlines, focus ring,
  active-tab underline, the finial, and money-action buttons ONLY. WARN is
  orange so it can't read as gold.
- Every non-money button is built with `secondary_style(font, wide=?)`;
  every input with `field_style(inside=?)`. Never hand-roll either.
- Plat/Vosfor numerals: `price` font role + `PLAT #cdd5da`.
- Colors come from named tokens (`RARITY_BRONZE`, `WEB_ACCENT`, …) — no raw
  hex at a call site. `registry.Tool.accent` defaults to slate, not gold.
- Two refresh glyphs by convention: `⟳` = money action, `↻` = data refresh.
- Fonts are probed at startup — always use `App.fonts` roles
  (h1/h2/body/small/price/mono/icon), never hardcoded families.
- Icons are Segoe Fluent Icons codepoints; NO color emoji anywhere in-app.
- Scrolling: use `ScrollArea` — never hand-roll a Canvas/Scrollbar pair. It
  owns the glide animation, its cancellation, the device-pixel scroll step
  and the wheel convention. Put content in `.body`; forward the view's
  `on_show()`/`on_hide()` to `claim_wheel()`/`stop()` + `release_wheel()`.
  (Its scrollbar is ttk with `style="Toolbox.Vertical.TScrollbar"` — plain
  tk.Scrollbar is native-drawn and unthemable.)
- Wiki affordance: `wiki_link(parent, app, name, bg)` — a `WIKI_ICON` glyph
  in `WEB_ACCENT` that opens the item in the app's own Wiki tab. Always its
  own widget, never a binding added to a label that already does something.
- Spacing tokens `SP_XL/LG/MD/SM`; inputs use `field_style()`.

## Threading rules

**Use `ui/work.py`. Do not spawn a bare thread.** Qt queues a cross-thread
`Signal.emit()` to the receiver's thread automatically and drops it if the
receiver has been deleted, so the `after(0, ...)` + `winfo_exists()` dance is
gone. What is left:

- `work.run(fn, on_done, on_error)` for one call; `work.run_stepped(...)` when
  a sweep should report per item. Both return a `Job` with `cancel()`.
- **Keep the returned Job alive.** `work` holds in-flight Jobs in a module set
  because a caller's attribute dies with its page, and a garbage-collected Job
  whose thread is still running emits into a deleted C++ object.
- The guard you still need is **staleness, not liveness**: "did the user ask
  for something else while this was in flight?" (`slug != self.slug`). Widget
  lifetime is Qt's problem now.
- Subprocesses use `QProcess` (`ui/runner.py`, Settings ▸ Data ▸ Market) —
  `readyReadStandardOutput` and `finished` replace the thread, the queue, the
  sentinel and the poll loop entirely.
- Console output uses `insertText`, never `appendPlainText`: append starts a
  new paragraph per call and double-spaces output that already ends in `\n`.

Long backend calls still stay off the GUI thread even when they look local —
the AlecaFrame decrypt parses tens of MB.

## Load-bearing invariants (do not "fix" these)

**Qt front end:**
- Tools reach warframe.market **only** through the host's gateway, and find it
  through `WFM_GATEWAY` / `WFM_GATEWAY_TOKEN` in their environment. A tool
  started without them exits by design; build its env with
  `gateway.child_env(dict(os.environ))`.
- The web profile must be a **named** `QWebEngineProfile`. The no-argument
  constructor is off-the-record and silently discards every cookie on exit.
- The web user agent must present as plain **Chrome**. Claiming to be Edge is
  what *triggers* overframe.gg's Cloudflare challenge — Edge sends `Sec-CH-UA`
  hints QtWebEngine does not, and the mismatch reads as a bot.
- `core/` owns every UI-agnostic rule. A screen's behaviour belongs in a `_vm`
  module; its view places widgets. Severity crosses the boundary as a ROLE
  WORD ("ok", "warn", "err"), never a hex colour.
- `config.load_settings()` **deep**-copies DEFAULTS. A shallow copy shared the
  nested `vosfor_methods` dict with the defaults themselves.
- Autostart: `config.set_launcher()` must be called by whichever launcher is
  running, or the HKCU Run entry points at the other front end.

**Legacy Tk front end (`--tk`) only — these do not apply to `ui/`:**
- `SetProcessDpiAwareness(0)` must run FIRST in `App.__init__` — WebView2's
  .NET side otherwise flips DPI mode mid-session and shrinks the UI.
- Custom titlebar strips WS_CAPTION|WS_THICKFRAME (no overrideredirect);
  Tk re-adds styles on some state changes, so `_strip_native_frame` re-runs
  on every `<Map>`. Maximize must use native `state('zoomed')` — hand-rolled
  geometry fights Tk's phantom frame metrics.
- `SetProcessDpiAwareness(0)` also means Windows bitmap-stretches the window
  on a scaled display, so a 1-logical-pixel scroll lands on a fraction of a
  device pixel and every frame leaves a seam. `display_scale()` reports the
  true factor (`GetDpiForMonitor` is not virtualized) and `scroll_unit()`
  gives the smallest step that stays whole; `ScrollArea` scrolls in those
  units. Settings > Display shows the detected factor.
- `webhost.py`: all three browser windows are created in ONE batch at launch
  (creating one later while another is embedded breaks pywebview) but they
  sit on `about:blank`. A site loads only when a view asks (`open_site()`)
  AND that browser's blocker is armed — `_arm_adblock` no longer navigates
  on its own, it just marks keys armed (in a `finally:`, so a key is never
  left unarmed and unnavigable). `open_site(key, url)` also re-points a
  browser, which is how wiki deep links work. `_navigated` is set only on a
  load that actually succeeded, and `_navigating` reserves a key before the
  Invoke — the embed poll runs every 120ms, so without that reservation one
  first visit re-issued `load_url` dozens of times, each cancelling the last.
  The
  runner thread is deliberately NAMED 'MainThread' (pywebview gates on the
  name); ad-block .NET delegates are kept referenced in `_adblock_hooks`
  (GC would silently unsubscribe them); `WebHost.shutdown()` must run before
  exit or the .NET UI thread outlives the process; `main()` uses
  `os._exit(0)` after a WebView2 run — atexit/finalizers will NOT run.
- `arcane_inv._IV` is CORRECT and is used as-is. (This rule used to say byte 0
  was "knowingly wrong" and that the true IV must be recovered from a
  `{"InventoryJson"` prefix. It was not wrong, and that recovery *caused* a
  silent outage: when AlecaFrame moved the inventory to the top level on
  2026-07-29 the prefix stopped matching, so a bad IV was derived, block 0 was
  corrupted, and every read returned None behind the stale disk cache. Fixed
  2026-07-30.) Prefix recovery survives only as a fallback over
  `_KNOWN_PREFIXES`; if the format shifts again, add an entry there.
- `arcane_inv` accepts BOTH inventory shapes — the object itself, or nested
  under `InventoryJson` — via `_inventory_of`, which identifies it
  structurally (`RawUpgrades`/`Upgrades` present) rather than by key name.
- AES lives in `core/aes.py`, pure Python, decrypt-only. It replaced a
  `bcrypt.dll` ctypes binding that pinned the module to Windows for nothing
  but an AES primitive. Verified against the FIPS-197 C.1 vector and
  byte-identical to the CNG code over the real 1.33 MB file. It costs ~900 ms
  for that file (~1.5 MB/s), so it must stay behind the mtime cache and must
  NOT be called on a UI thread.
- `wf_local.py`: ALL game-file access goes through `_open_readonly()`
  (O_RDONLY at the OS level). Never open a game path any other way.
- `Session.bearer` is the only auth normalizer: v2 wants `Bearer <t>`, v1
  wants `JWT <t>`. Never store/compare the prefixed string.
- Gateway binds 127.0.0.1 + per-launch token (compared with
  `hmac.compare_digest`); tools get ONLY the gateway URL and token via
  `gateway.child_env` — the JWT never reaches a tool env. It proxies
  GET/POST/PUT/PATCH/DELETE, and `path_allowed()` normalizes dot-segments
  and double-encoding before the /v1/ /v2/ check — keep that guard.
- `Presence`: each connection owns its own stop `Event`, `_ws` is published
  only AFTER auth succeeds, and `(_ws, connected)` transitions happen under
  `_state_lock`. Status changes from the UI thread go through `_pending`,
  never a blocking send. Don't reintroduce a shared stop flag.
- Anything that invalidates a persistent view's source data (a wipe) must
  call `App.drop_persistent_views()` — they hold state in memory and write
  it back on interaction.
- Both rate limiters sleep while holding their lock — that IS the
  serialization; don't move the sleep out.

## Adding things

- **New tool**: script under `data/tools/<name>/` + one `Tool()` entry in
  `registry.py` → sidebar item + Home card appear. `requires_session=True`
  gates launch. Tools call the gateway with WFM paths; they exit without it.
- **New native app**: view class + entry in `App._nav_items` + Home card in
  `HomeView` (philosophy #4 — cards for native apps/web apps are manual;
  only registry tools are automatic) + `_view_for` branch (decide persistent
  vs rebuilt; a persistent view MUST implement `on_hide()`, and `on_show()`
  if it has anything to refresh or re-claim). If it holds account-derived
  state, add it to `_drop_account_views()`.
- **New setting**: MUST be added to `config.DEFAULTS` — `load_settings()`
  drops unknown keys, so an unregistered key silently vanishes on reload.
- **New generated user file**: add to `config.USER_FILES` (Settings > Data
  lists/deletes from it) and check the delete-all fan-out in
  `ToolboxDataPage`.

## Gotchas

- `USER_AGENT` in `core/session.py` is the app-wide client identity (WFM
  rules require an honest one) — change it there only, everything imports it.
- UI code must use the public accessors `Presence.want` and
  `MarketClient.name_of(slug)` — never reach into `_want`/`_name_index`.
- `.wfm_session.json` also stores the login EMAIL (form prefill), not just
  the JWT — the docstring and README document this. `chmod 600` is a no-op
  on Windows, so the folder's ACLs are the real protection (see "Known
  limitations"). Deleting the session file must route through
  `unlink_account()` (ToolboxDataPage special-cases this).
- AlecaFrame inventory: `arcane_inv.read_arcanes_cached()` is the road in —
  disk cache `.arcane_inv.json`, staleness = one stat() of lastData.dat's
  mtime (`cache_is_stale`), falls back to the cache when AlecaFrame is gone.
  VosforView refreshes via `on_show()`; ↻ button forces (`force=True`).
  Manual overrides (`.vosfor_owned.json`) always beat the auto-read.
- `bind_all("<MouseWheel>")` is last-writer-wins app-wide — `ScrollArea`
  handles it via `claim_wheel()` (from `on_show`) and `release_wheel()`
  (from `on_hide`, while still mapped). Never `unbind_all` from a hidden
  widget: it steals the wheel from the visible page.
- **NEVER call `update_idletasks()` in `navigate()` or `select_tab()`.** It does
  not flush "this widget" — it synchronously drains every pending idle task in
  the interpreter. Two such calls cost 770ms of a 1106ms startup and turned a
  lap of tab switches from 308ms into 3920ms. Measured; see the git-less
  history in the plan file. Nothing in the navigation path may depend on the
  map having already happened.
- Because of that, a view asks "would drawing be seen?" **structurally**, not
  from Tk: `ListingsView._tab_live()` / `MarketView.tab_live()` combine an
  explicit `_shown` flag (set in `on_show`/`on_hide`) with "is this the
  selected tab". `winfo_ismapped()` is only trustworthy once layout has
  settled — fine in a background callback or a wheel handler, wrong
  immediately after `pack()`.
- Anything that repaints a whole view (`_render`, `_rebuild`, `reload`) must
  bail when it would not be seen and set a `_dirty` flag that `on_show()` (or
  `_flush_dirty()`) drains.
  Background results land on hidden views routinely — the AlecaFrame decrypt
  takes seconds and a listings refresh feeds all three tabs — and rebuilding
  ~1000 widgets on a hidden canvas races whatever the visible view is
  painting.
- Wiki links route through `App.open_wiki()` → the Wiki tab. Never
  `webbrowser.open()`; the only external-browser path is `WebAppView`'s
  fallback, which exists solely when embedding is impossible.
- Tk quirks already worked around: Canvas defaults to ~265px height (create
  with height=1, draw on `<Configure>`); Spinbox with `values=` resets to
  the first entry on creation (re-assert the saved value).
- The watcher duplicates `config.py`'s process-detection on purpose (it must
  be a dependency-free standalone); change game-exe detection in BOTH. It
  finds the Toolbox by exact window title "Warframe Toolbox".
- HKCU Run entries bake in absolute pythonw.exe + folder paths — moving the
  folder leaves stale entries that still show as enabled.
- `.vosfor_prices.json` never refreshes on its own — the Vosfor view shows
  the cache's age and ↻ Refresh prices re-runs the sweep.
- A persistent view's `<Destroy>` never fires, so `on_hide()` is its ONLY
  teardown. Anything scheduled with `after`/`after_idle` that touches
  geometry must keep its id and be cancelled there — an uncancelled
  animation kept scrolling a hidden canvas while the next view mapped, which
  is what the "artifacts on tab change" bug was. Code that destroys a
  persistent view outside `navigate()` (`_drop_account_views`,
  `drop_persistent_views`) must route through `_stop_view()` first, or those
  jobs fire against deleted Tcl commands.
- `ScrollArea.GLIDE_*` are tuned for smoothness, not thrift: a scroll frame
  costs 1.7ms median inside a real mainloop. Do not coarsen them on the
  strength of a benchmark that calls `update_idletasks()` in a loop — that
  never lets a repaint coalesce and reports ~100x the real cost.

## Known limitations (deliberate, documented)

- **Session file ACLs**: `.wfm_session.json` (a trading credential) is only
  as protected as the folder. Outside the user profile — e.g. on a data
  drive — other local accounts may read it. `session.exposed_location()`
  detects this and Settings > Data > WF Toolbox warns.
- **Rate limits are split**: the gateway's 0.6s limiter covers tools; each
  host `MarketClient` spaces itself 0.35s independently, and thumbnail
  fetches skip spacing. Host + tools are not under one ceiling.
- `.wfm_listings.json` floors/caps are keyed by slug and not account-scoped.
- Contracts tab is a placeholder; contract counts are not reported anywhere.


## No version control

This project is **not a git repository**. There is no undo for a bad edit and
no way to recover a deleted file. Two consequences:

1. Nothing large gets deleted without `git init` first. The Tk view classes
   (~5,500 lines) are still on disk for exactly this reason, not because they
   are still needed — every screen is ported.
2. Prefer additive changes and keep the `--tk` path working until there is a
   history to fall back on.
