# Overwolf / data-source status

Where the "own the inventory pipeline" effort stands (updated 2026-08-04).
The goal: market the app through Overwolf, with our own companion app as the
inventory source and AlecaFrame as a fallback only.

## The three-phase migration off AlecaFrame

### Phase 1 - DE profile API: COMPLETE

- `core/store.py`: namespaced JSON cache-of-record (`wf_data/`).
- `core/wf_http.py`: DE HTTP helper (UA, retry/backoff, Cache-Control).
- `core/wf_profile.py`: `getProfileViewingData` fetch/refresh/accessors.
- Config keys `wf_account_id` / `wf_platform`; QtWebEngine account-id
  auto-capture (`ui/wf_connect.py` ConnectWarframeDialog +
  `wf_profile.extract_account_id`).
- Home mastery cutover: profile API primary → AlecaFrame fallback
  (`ui/home.py` ~line 313 - the one intentional direct AlecaFrame call).
- Home "Profile" status light.

### Phase 2 - worldState / PublicExport / EE.log: COMPLETE

- `core/worldstate.py` (60 s throttle).
- `core/public_export.py`: LZMA index with DE's missing-end-marker quirk
  handled; per-manifest cache under `export/<stem>`; `resolve_name()` for
  `/Lotus/...` paths.
- `core/ee_events.py`: incremental read-only tail with rotation detection.
- `core/collect.py` `run_startup_refresh()` wired into app start.

### Phase 3 - own Overwolf companion: seam landed, cutover PENDING

- `core/wf_inventory.py` provider seam:
  `OverwolfCompanionProvider` (preferred) → `AlecaFrameProvider` (fallback) →
  `LinuxGepProvider` (reserved stub).
- Vosfor + Market count_owned + Home light + collector all read through the
  seam; the companion takes over automatically the moment its file appears.
- `overwolf-companion/` (manifest v0.1.0, game id 8954, GameInfo+FileSystem
  permissions, background-only; writes
  `%LOCALAPPDATA%\WarframeToolbox\inventory.json`) is **template status**:
  it has NEVER run end-to-end, pending Overwolf developer-approval
  requirements.
- First-load verifications when it does run:
  1. Does overwolf.io actually expand `%LOCALAPPDATA%` in the write path?
  2. Directory creation: `background.js` uses the 4-arg
     `writeFileContents` without the create-directories flag - confirm the
     folder exists or create it first.
- Store-Python caveat: while the Toolbox runs under Microsoft Store Python,
  it reads the REAL `%LOCALAPPDATA%\WarframeToolbox\inventory.json` through
  MSIX read-fallthrough (its own writes are virtualized elsewhere). Expected
  to work like the AlecaFrame reads do; verify on first companion run.

## Design intent (do not undo)

- AlecaFrame stays a fully working fallback until the companion is proven.
  Do not remove the AES decrypt path (`core/aes.py`).
- The pure helpers in `arcane_inv.py` (`build_overview`, `arcanes_from_inv`,
  `counts_from_inv`, `_inventory_of`) serve BOTH providers and must survive
  any future AlecaFrame removal.
- `wf_inventory` reads `paths.COMPANION_DIR`, never `paths.USERDATA` - the
  companion's output path is a fixed contract even in portable mode.

## Public-data facts worth keeping

- `getProfileViewingData` is no-auth but has **no owned inventory**.
- Twitch `getActiveLoadout` is auth-gated (abandoned).
- Owned inventory has **no credential-free public source** - only Overwolf
  GEP (or a future own memory reader).
- The modern EE.log does not contain the account id.
