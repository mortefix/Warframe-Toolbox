# Changelog

All notable changes to Warframe Toolbox are recorded here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and the project uses [Semantic Versioning](https://semver.org/) — `MAJOR.MINOR.PATCH`.
The current version always lives in `app/core/version.py`.

## [Unreleased]

## [1.1.1] - 2026-08-07

### Added
- Mods is now a full collection app. A pull-down category drawer (like a
  notification shade) covers a wall of mod item cards: real card art, rank,
  polarity mark, and per-mod wiki, price-check and open-in-Market buttons.
- Collection tracking everywhere: an obtainable-completion headline
  ("X/Y Obtainable +N Vaulted Mods Collected - Z% Complete"), progress bars
  for every arsenal category (including Sniper and Tennokai), every mod set
  (including Antivirus, Galvanized, Amalgam, Archon, Bond, Requiem and
  Lua Drift), and the named collections - now with Nightwave (including all
  32 seasonal weapon augments), a Syndicate aggregate, and Vaulted trophies.
- Rivens: a display-only shelf listing every unveiled riven with its weapon,
  compressed stat line, rank and polarity, and a tooltip carrying polarity
  school, MR requirement and reroll count. Rivens count toward no completion.
- Filters and sorting on the wall: per-collection search (Enter on the empty
  global box shows the whole catalogue), Show Unranked, Hide Owned with
  counts, parazon-specific antivirus/requiem/parazon splits, and sort by
  Name / Rank / Rarity / Polarity, ascending or descending.
- Mod card art downloads on demand and is cached locally
  (Settings > Data shows and clears the cache).

### Changed
- The database-style mods browser moved to Settings > DevTools > Mods DB;
  the sidebar's Mods entry now opens the collection app.
- Mods database refresh: Nightwave seasonal augments joined their set,
  flawed-mod wiki paths corrected, Striker recognised as BoomStick, and the
  base Transmute Core marked unobtainable.

## [1.1.0] - 2026-08-07

### Added
- Mods is now a full collection app. A pull-down category drawer (like a
  notification shade) covers a wall of mod item cards: real card art, rank,
  polarity mark, and per-mod wiki, price-check and open-in-Market buttons.
- Collection tracking everywhere: an obtainable-completion headline
  ("X/Y Obtainable +N Vaulted Mods Collected - Z% Complete"), progress bars
  for every arsenal category (including Sniper and Tennokai), every mod set
  (including Antivirus, Galvanized, Amalgam, Archon, Bond, Requiem and
  Lua Drift), and the named collections - now with Nightwave (including all
  32 seasonal weapon augments), a Syndicate aggregate, and Vaulted trophies.
- Rivens: a display-only shelf listing every unveiled riven with its weapon,
  compressed stat line, rank and polarity, and a tooltip carrying polarity
  school, MR requirement and reroll count. Rivens count toward no completion.
- Filters and sorting on the wall: per-collection search (Enter on the empty
  global box shows the whole catalogue), Show Unranked, Hide Owned with
  counts, parazon-specific antivirus/requiem/parazon splits, and sort by
  Name / Rank / Rarity / Polarity, ascending or descending.
- Mod card art downloads on demand and is cached locally
  (Settings > Data shows and clears the cache).

### Changed
- The database-style mods browser moved to Settings > DevTools > Mods DB;
  the sidebar's Mods entry now opens the collection app.
- Mods database refresh: Nightwave seasonal augments joined their set,
  flawed-mod wiki paths corrected, Striker recognised as BoomStick, and the
  base Transmute Core marked unobtainable.

## [1.0.2] - 2026-08-06



## [1.0.1] - 2026-08-05

### Added
- Windows installer (`Install Warframe Toolbox.exe`): installs per-user with no
  admin, sets up Python and the app, and keeps it updated automatically.

### Changed
- New-user default settings: the app launches maximized, the window's close
  button quits instead of hiding to the tray, and the trade-whisper templates
  are signed `(Warframe Toolbox)`.
- About page: the Changelog panel now populates live from the project changelog,
  the Licensing panel states the GPLv3 + Overwolf linking exception, and
  Developer Info links the GitHub repository.
- Home: the self-update notice now sits beside the title. About > Developer Info
  drops the fan-project disclaimer (it remains in the Licensing section).

## [1.0.0]

- Baseline release.
