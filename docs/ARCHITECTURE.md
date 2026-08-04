# Architecture

One-page map of how Warframe Toolbox is put together. The style/design rules
live in `STYLE_GUIDE.md`; the working agreements for AI-assisted development
live in `../CLAUDE.md`; day-to-day workflows live in `DEVELOPMENT.md`.

## The shape of the tree

```
Warframe Toolbox/
├─ Warframe Toolbox.pyw     launcher: data-root setup + migration, then ui.app.main()
├─ update.bat               beta channel: git pull --ff-only, then launch
├─ requirements.txt         requests, websocket-client, PySide6-Essentials/-Addons
├─ app/                     THE APP - pure code + shipped assets, no user data ever
│  ├─ registry.py           tool catalogue: one Tool() entry = sidebar item + Home card
│  ├─ warframe_watcher.pyw  standalone watcher (opens the Toolbox when the game starts)
│  ├─ vosfor_collections.json  shipped Vosfor data (not user data - stays here)
│  ├─ core/                 backend + every UI-agnostic rule (see below)
│  ├─ ui/                   the PySide6 front end (the ONLY front end)
│  ├─ tools/<name>/         tool scripts run as subprocesses through the gateway
│  └─ assets/               fonts (+ licenses/), logo
├─ tests/                   33 plain-script test files; python tests/run_all.py
├─ tools/                   dev-only helpers (screenshots, gallery) - not shipped ideas
├─ docs/                    this file, STYLE_GUIDE, DEVELOPMENT, OVERWOLF_PLAN
└─ overwolf-companion/      Overwolf app template (see OVERWOLF_PLAN.md)
```

`core/` may **never** import from `ui/` - the dependency runs one way.

## Where user data lives: core/paths.py

`app/core/paths.py` is a stdlib-only leaf that resolves the data root ONCE at
import, with no side effects (no mkdir, no file I/O at import time):

1. `WFTOOLBOX_DATA` env var - explicit override. `tests/run_all.py` sets it to
   a temp dir so no test can ever touch real data.
2. `<root>/userdata/` exists - the **portable/dev override** (gitignored).
   A dev clone runs `mkdir userdata` once and is fully isolated from the live
   install on the same machine.
3. Default: `%LOCALAPPDATA%\WarframeToolbox` on Windows,
   `$XDG_DATA_HOME/WarframeToolbox` (else `~/.local/share/WarframeToolbox`)
   elsewhere. **Linux support is exactly this one branch.**

Exports: `APP_DIR` (app/), `ROOT` (project root), `USERDATA`, `COMPANION_DIR`,
`is_portable()`, `ensure_dirs()` (launcher-called), `migrate_legacy()`
(launcher-called; idempotent per-item moves, skip-if-target-exists,
OSError-tolerant so a locked file just retries next launch).

Every module keeps its file location as a **module-level constant** derived
from `paths.USERDATA` (`session.SESSION_PATH`, `config.SETTINGS_PATH`, ...).
Constants, not functions, on purpose: the test suite monkeypatches them.

File names in the data root have **no dot prefix** (`wfm_session.json`, not
`.wfm_session.json`) - the dots only existed to hide user files among code.

`COMPANION_DIR` is always the *platform* dir, never `USERDATA`: the Overwolf
companion writes `inventory.json` there unconditionally (its manifest bakes
the path), so the reader must look there even when the app runs portable.
When the app uses the platform default, both are the same folder and the
companion's file coexists with ours.

### Microsoft Store Python caveat (measured 2026-08-04)

Under the **Microsoft Store** Python, writes to `%LOCALAPPDATA%` are
redirected by MSIX filesystem virtualization into
`%LOCALAPPDATA%\Packages\PythonSoftwareFoundation.Python.3.11_…\LocalCache\Local\WarframeToolbox`.
There is no opt-out from inside the process. Consequences:

- The app is fully **coherent** - it reads back exactly what it writes.
- Reads of paths the package never wrote (AlecaFrame's `lastData.dat`, a
  companion-written `inventory.json` with no shadowing copy) fall through to
  the real location, so the provider seam still works.
- But the *physical* files are not at the documented path in Explorer, and
  the "one canonical folder shared with the companion" story is weakened.

The clean fix is a python.org interpreter (also required for the planned
PyInstaller packaging): install it, move the data folder once from the
`LocalCache` path above to the real `%LOCALAPPDATA%\WarframeToolbox`, and
`config.repair_run_entries()` heals the autostart entries on next launch.

## core/ module map

| Area | Modules | Notes |
|---|---|---|
| Paths & identity | `paths`, `version`, `config` | `version.py` is the single source of `__version__`/`USER_AGENT`; `config` owns settings, the USER_FILES registry (the Settings > Data page and the deletion allowlist), and Windows integration (HKCU Run entries, `repair_run_entries`) |
| warframe.market | `session`, `market`, `gateway`, `presence`, `repricer`, `floors` | `session` owns the JWT; tools only ever see the localhost gateway with a per-launch token |
| Game data (DE) | `wf_http`, `wf_profile`, `worldstate`, `public_export`, `ee_events`, `collect`, `store` | the collected-data store (`wf_data/` namespaces); `collect.run_startup_refresh()` wired into app start |
| Local game files | `wf_local` (READ-ONLY enforced via `_open_readonly`), `mastery` | |
| Inventory seam | `wf_inventory`, `arcane_inv`, `aes` | see next section |
| Vosfor | `vosfor`, `vosfor_vm`, `arcane_market` | shipped collection data in app/, user check-offs in USERDATA |
| View-models | `market_vm`, `listings_vm`, `home`, `nav`, `webapps`, `wiki`, `bookmarks`, `adblock` | UI-agnostic derivations; Qt code stays in ui/ |
| Plumbing | `atomic`, `assets`, `theme` | `theme.py` is the app's entire visual vocabulary (palette + metrics + fonts) |

## The inventory provider seam (core/wf_inventory.py)

Owned inventory has **no credential-free public source** - only Overwolf's
game-events plugin (or a future memory reader) can supply it. The seam:

```
OverwolfCompanionProvider   preferred the moment COMPANION_DIR/inventory.json exists
  └─ AlecaFrameProvider     working fallback: decrypts AlecaFrame's lastData.dat
       └─ LinuxGepProvider  reserved stub (no Linux game-events source exists yet)
```

- Every provider yields the same shape - the game's inventory dict - so the
  pure helpers in `arcane_inv` (`build_overview`, `arcanes_from_inv`,
  `counts_from_inv`, `_inventory_of`) serve ALL providers. They must survive
  any future AlecaFrame removal.
- Vosfor, Market count_owned, the Home light and the collector all go through
  the seam. The **one intentional direct AlecaFrame call** outside it is the
  guarded mastery fallback in `ui/home.py` (~line 313): mastery comes from the
  profile API first, AlecaFrame's `PlayerLevel` as fallback. Keep it until the
  companion path is proven end-to-end.
- Do not remove the AES decrypt path (`core/aes.py`) while AlecaFrame is the
  working fallback.

## Data flow, launch to screen

1. Launcher: `paths.ensure_dirs()` → `paths.migrate_legacy()` → register
   itself (`config.set_launcher`) → `ui.app.main()`.
2. `main()`: single-instance `QLockFile` in USERDATA →
   `config.repair_run_entries()` → stylesheet from `core.theme` via `ui/qss` →
   `MainWindow` → deferred web-engine warmup → deferred
   `collect.run_startup_refresh()` (profile, worldState, EE.log events,
   Public Export - each self-throttles into `store`).
3. Screens read through view-models in core/; anything slow runs via
   `ui/work` off the GUI thread; results come back on bound methods (never
   lambdas - Qt drops queued signals whose receiver died).

## Tests

`python tests/run_all.py` - 33 plain-script files, no pytest. The runner
exports `WFTOOLBOX_DATA` to a fresh temp dir (no test can touch real data),
runs each file in its own process with a 180 s cap (a hung Qt modal fails
instead of freezing the suite), and Qt tests run offscreen with
`ui.web.isolate_for_tests()` so the real browser profile is never opened.
