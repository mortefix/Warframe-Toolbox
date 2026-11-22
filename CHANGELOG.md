# Changelog

All notable changes to Warframe Toolbox are recorded here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and the project uses [Semantic Versioning](https://semver.org/) — `MAJOR.MINOR.PATCH`.
The current version always lives in `app/core/version.py`.

## [Unreleased]

### Added
- Installer: a "Open the Toolbox automatically when Warframe starts" option,
  ticked by default on a first install, so the feature works straight after
  setup. Re-running Setup shows whatever it is currently set to.

### Changed
- Mods: the shade slides open and closed more slowly (0.42s, was 0.25s).
- Setup wizard: when the Warframe.com or warframe.market step succeeds, a
  green line beside the Back button says so and tells you to press Next.
- "Launch the Toolbox when Warframe starts" now follows the Windows startup
  entry alone. The background watcher keeps running only while that entry
  points at its own copy of the app, so an entry written by the installer
  (or repaired after a folder move) works without also flipping a setting.
  When an installed copy and a second copy of the Toolbox share a PC, the
  installed copy takes the entry over the next time it starts, and the
  checkboxes in Settings show whether the entry belongs to the copy you are
  looking at. Turning the option off in one copy no longer removes another
  copy's entry.
- Updates are applied more carefully. The app now downloads first and then
  fast-forwards its files in a separate, local step, and loads every screen
  from the old version before any file changes - so a tab you open after an
  update landed can no longer mix new code into the running session.
- Windows' "Installed apps" list shows the Toolbox's real version (it showed
  the bundled Python's, 3.11.9) and keeps it current after each self-update.
- Every screen's title now sits in the same place (Home, Vosfor and the
  DevTools pages sat a few pixels lower or further in than the rest), the
  setup wizard's text lines up with its button row, and the Warframe.com
  sign-in window uses the same padding as every other dialog.
- Buttons with their own colours (the outlined card buttons, the Settings
  and web-app buttons, the status chips) now show a hover state and look
  disabled when they are.
- Buttons and text fields are one height everywhere (26px; they were a mix
  of 24, 26, 28 and 30) and outlined buttons share one look.
- Small marks that were typed as symbols - the stock mark after a quantity,
  the undercut warning, reputation arrows, status dots, the dropdown arrow -
  are now drawn by the app instead of borrowed from a Windows symbol font,
  so they look the same on every PC.
- Mods database refreshed for Update 44 "Iceblade of Narin": the four new
  Warframe augments join their syndicate lists - Brood's Oversurge (Oraxia,
  Cephalon Suda / New Loka), Infernum (Uriel, Steel Meridian / Perrin
  Sequence), Cold Front (Frost) and Gastroparesis (Grendel) - each with its
  card art and Overframe deep link. Banshee's reworked augments carry their
  new names (Sonic Fracture is now Sonic Siphon, Resonating Quake is now
  Gaseous Quake), and Augmented Sonar is gone, as DE's own data no longer
  ships it.
- Arcanes re-verified against DE's export: Update 44 added none, and all
  nine Vosfor collections are unchanged. The update's new Warframes and
  weapons (Narin, Citrine Prime, Nunchasa, Aksondol, Steflos Prime,
  Corufell Prime) need no shipped data - the app already resolves them
  from the Public Export it syncs on its own.

### Fixed
- Mods: picking a collection no longer shows the previous collection's
  progress bar under the new name while it loads (the bar could rise and
  then fall for a single pick). It stays empty until the count is in.
- Connecting your Warframe.com profile never completed: the website removed
  the page the Toolbox read your account ID from, so the wizard and
  Settings sat on a signed-in page for ever and Home's Profile light stayed
  off. The ID is now read from the signed-in site directly, within a few
  seconds. The "Get ID manually" button, which opened that same dead page,
  is gone.
- Dialogs were unreadable when Windows' light/dark setting disagreed with the
  theme. The setup wizard, the sign-in form, every confirmation and error
  box and the tray menu took their background from Windows instead of from
  the theme - so a dark theme on light-mode Windows (or a light theme on
  dark-mode Windows) drew pale text on a pale window. They are themed now,
  as is the DevTools mod table.
- Switching theme no longer leaves pieces in the old theme's colours until a
  restart: the status chips, Home card accents, the My Listings and Market
  tab edges, the WTS/WTB badges and the order book's status dots all follow
  the switch at once.
- Mods: the top border of the collection area no longer disappears while
  the shade slides open or closed.
- Christmas Light: text fields, dropdowns and checkboxes get the green trim
  the theme was designed with (they were taking the red frame colour).
- Updates: if installing a new dependency failed (offline, antivirus), it
  was never tried again and the app could be left unable to start. It is
  now retried on every launch until it succeeds. A stalled connection can
  no longer interrupt an update halfway through and leave the app refusing
  all later updates, and git can no longer sit waiting for a password that
  nobody can see.
- "Delete ALL user data" left your mod collection, the cached mastery rank
  and the mastery badge images behind. All three are now listed on
  Settings > Data > WF Toolbox and removed by the wipe, and the wipe tells
  you if the embedded browser's profile could not be cleared instead of
  reporting success.
- Mods: the developer query console could change your collection. A
  statement that starts with WITH can still delete or update, and the
  console ran it; it is now strictly read-only.
- My Listings: sorting by "Market best", high to low, put every listing
  whose market price had not loaded yet at the top. They stay at the bottom
  in both directions.
- Presence: switching status while connected could freeze the window for a
  moment and sent the status twice; and when a connection failed instantly
  the toggle could stay on "connecting..." for ever.
- "Launch the Toolbox when Warframe starts" did nothing while an Explorer
  window showing a folder named "Warframe Toolbox" was open - the watcher
  mistook it for the app. Two watchers could also start side by side.
- warframe.market replies in an unexpected shape now produce a readable
  error instead of a blank screen or the bare text 'data'.
- Game log: a new Warframe session whose log had already grown past the
  point the last one ended at was not recognised as new, so the previous
  session's events were kept and the new one's first lines skipped.
- Vosfor: a platinum balance typed just before leaving the page or closing
  the app could be lost; a corrupt price cache (`"prices": null`) could
  never repair itself; and a failed inventory read now reports as failed.
- Mods: veiled rivens no longer appear as blank riven cards, and a card
  image that cannot be saved (disk full, file locked) is skipped instead of
  breaking the whole batch.
- Settings and the saved session are written through per-process temporary
  files, so two saves landing together cannot corrupt either one.
- Screens that were closed while a background request was still running
  (unlinking, wiping data, switching theme) no longer receive its result.
- Mods: Inaros's Scarab Shell augment showed as "Negation Swarm", the name
  it lost in Update 35.5 - the wiki keeps BOTH names for a renamed mod under
  one id, and the build picked between them by alphabetical accident. DE's
  export name now settles it, so a rename can no longer ship stale. (The
  same accident was about to ship "Resonating Quake" after Update 44.)
- Mods: Swift Bite, Vampiric Grasp and The Relentless Lost sat in the
  uncategorised bucket marked untradable. The wiki lists a path DE does not
  ship for each, which split every one into two rows and left the wrong row
  canonical; they now appear under the syndicate that sells them.

## [1.2.0] - 2026-09-13

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
