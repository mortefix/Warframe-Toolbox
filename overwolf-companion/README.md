# Warframe Toolbox Companion (Overwolf)

A tiny Overwolf app that reads your Warframe inventory through Overwolf's
**Game Events** provider and writes it to disk for Warframe Toolbox. This is how
the Toolbox gets owned-inventory data (mods, arcanes, relics, platinum, credits)
**without AlecaFrame** — it is the same underlying source (Overwolf's provider),
written as plain JSON for our own app.

- **No overlay, no screen capture.** Background page only.
- **No game files are written.** It reads Overwolf's event feed and writes one
  file of its own.
- Writes to `%LOCALAPPDATA%\WarframeToolbox\inventory.json`, which the Toolbox's
  `OverwolfCompanionProvider` reads (preferred over AlecaFrame when present).

## Install (developer / unpacked)

1. Install [Overwolf](https://www.overwolf.com/).
2. Open the Overwolf **Settings → About → Development options** (or the Overwolf
   dev console) and choose **Load unpacked extension**.
3. Select this `overwolf-companion/` folder.
4. Add an `icon.png` in this folder if Overwolf complains about the missing icon
   (any 256×256 PNG; the manifest references `icon.png`).
5. Start Warframe. On login / a loading screen the inventory is written; if the
   Toolbox shows nothing, travel to a relay or dojo and back to force a refresh
   (the game only pushes the full inventory at sync points).

## How it fits together

```
Warframe (running)
    │  Overwolf Game Events "inventory" feature
    ▼
overwolf-companion (background.js)
    │  overwolf.io.writeFileContents(...)
    ▼
%LOCALAPPDATA%\WarframeToolbox\inventory.json   (raw game-events inventory JSON)
    │  read by
    ▼
Warframe Toolbox  →  core/wf_inventory.py  OverwolfCompanionProvider
```

The JSON is the raw game-events inventory string — the same object AlecaFrame
caches (encrypted) as `lastData.dat`, so the Toolbox normalizes both through the
one code path (`arcane_inv.build_overview` / `_accumulate`).

## Status / caveats

This companion is written but has **not** been run end-to-end by the author (it
needs Overwolf + a running game, which the build environment doesn't have). Two
things to verify on first real load:

- **Path expansion.** Overwolf's `overwolf.io` is expected to expand
  `%LOCALAPPDATA%` in `OUT_PATH`. If it doesn't on your Overwolf version, either
  hardcode the absolute path or create the `WarframeToolbox` folder first.
- **Directory creation.** `writeFileContents(..., true, ...)` passes
  "create dirs if needed"; if your Overwolf version doesn't honour it, create
  `%LOCALAPPDATA%\WarframeToolbox\` once by hand.

Until this is loaded, the Toolbox automatically falls back to the AlecaFrame
provider, so nothing breaks in the meantime.
