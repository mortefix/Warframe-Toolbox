# Changelog

All notable changes to Warframe Toolbox are recorded here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and the project uses [Semantic Versioning](https://semver.org/) — `MAJOR.MINOR.PATCH`.
The current version always lives in `app/core/version.py`.

## [Unreleased]

### Added
- Listings: a fourth "Saved For Later" tab. The new park button on every
  WTS/WTB card (top right, beside the wiki button) hides the listing on
  warframe.market and moves it to the saved tab, where the repricer,
  "Reprice All" and bulk visibility never touch it. Saved cards keep their
  thumbnails and their Edit and ±1 buttons, and the unpark button returns
  the listing to its original tab (still hidden, ready to re-show).
- Saved For Later: an optional per-listing Target Price replaces the
  repricer minimum. When a market sweep finds the price has reached a
  target (risen to it for sells, fallen to it for buys), a red dot appears
  on the tab header. The saved list is local to this PC — stored per
  account in `wfm_archive.json` and reconciled against your live orders on
  every listings refresh.
- Listings: the Repricer Min / Target Price field gains a checkmark commit
  button in a shared frame. It lights up as soon as you type, applies the
  value on click or Enter, and grays back out; Escape or clicking anywhere
  else abandons the edit and restores the stored value.
- Listings: every WTS/WTB card gains a Market button (left of Reprice) that
  jumps straight to that item in the Market app — no lookup, the listing
  already knows its slug.

### Changed
- Mods database refreshed for Update 43.5 "Amir's Shockwave" (Fables &
  Frontiers): Primed Polar Magazine (Baro), plus the EFV augments Prototype
  Shock Coils and Overpressured Rounds as Nightwave rank rewards, with their
  Overframe deep-link ids. Arcane collections verified against the wiki —
  all nine rosters unchanged (the new Update 43 arcanes drop from Uranus
  Proxima and are not in any Vosfor collection).
- Listings: order errors (reprice, sold, ±1, visibility) now open a popup
  titled with the item name; the card shows a short "failed" marker with the
  full message in its tooltip. "Reprice all" collects failures into a single
  summary popup instead of one per order.
- Listings: card and dialog labels now use Title Case throughout
  ("Repricer Min:", "Repricer Max:", "Target Price:" and friends).
- Market/Listings: a 403 from warframe.market now quotes the API's own
  reason in the error popup instead of a bare status code.

### Fixed
- Market: posting a listing no longer sends the retired "per trade" field —
  the warframe.market API started rejecting it, which made every new
  posting fail. The field is gone from the post dialog too.
- Listings: a long error message could widen a card's result label and push
  every card's buttons out of the grid. The label no longer drives the card's
  width — long text clips (and lives in the tooltip) instead of resizing the
  layout.

## [1.1.2] - 2026-08-13

### Added
- First-launch setup wizard: welcome, Warframe.com profile connect,
  warframe.market sign-in, and an AlecaFrame data check — every step
  skippable, re-runnable from Settings > Data (Warframe or Market).

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
