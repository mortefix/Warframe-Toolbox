# Beta installer + in-app auto-update — design

Approved in discussion 2026-08-04. Goal: the beta tester (and Daniel himself)
runs an installed copy of Warframe Toolbox that keeps itself current from the
private GitHub repo, with no GitHub account, no collaborator invite, and no
manual update steps.

## Decisions (locked)

- **Repo access**: a GitHub **fine-grained PAT** — repository access limited
  to `mortefix/Warframe-Toolbox` only, permissions **Contents: Read-only**,
  expiration **No expiration**. Daniel creates it in the GitHub UI and can
  revoke it there at any time (revocation is the kill switch). The token is
  baked into the clone's HTTPS remote URL
  (`https://x-access-token:<TOKEN>@github.com/mortefix/Warframe-Toolbox.git`),
  so plain `git fetch/pull` authenticates and **app code never handles
  credentials**.
- **Update UX**: auto-install in the background at launch, apply next launch,
  one quiet notice. No dialogs, no clicks.
- **Toggle**: `check_updates` (default `True`) in `config.DEFAULTS`, shown as
  "Check for updates at launch" on Settings > Display.
- **Daniel's live copy = the installer's output too.** His data home
  (`%LOCALAPPDATA%\WarframeToolbox`) is app-location-independent, so the
  installed copy finds his existing data with zero migration. The old live
  folder `D:\Projects_AI\Warframe Toolbox` is retired afterwards; feature work
  happens in `D:\Projects_AI\Warframe Toolbox Dev`.

## Component 1 — installer: `Install Warframe Toolbox.bat`

One self-contained batch file, small enough for Discord, generated from a
template with the token inserted. On any Windows machine it:

1. **Python**: if `%LOCALAPPDATA%\Programs\Python\Python311\python.exe` is
   missing, download `python-3.11.9-amd64.exe` from python.org and run
   `/quiet InstallAllUsers=0 PrependPath=1 Include_launcher=1
   InstallLauncherAllUsers=0 Include_test=0` (per-user, no UAC).
2. **Git**: if no usable `git` on PATH, download the **MinGit** zip (portable
   Git for Windows) and extract to `%LOCALAPPDATA%\Programs\WarframeToolbox\
   mingit\` — no system install, no elevation. (MinGit lives INSIDE the app
   dir; it is not put on PATH.)
3. **Clone**: `git clone <token-URL> "%LOCALAPPDATA%\Programs\WarframeToolbox\app-repo"`
   — cloning into a subfolder keeps the MinGit dir out of the repo tree.
   (Exact layout: `WarframeToolbox\mingit\` + `WarframeToolbox\app-repo\
   <the repo>`.)
4. **Deps**: `python -m pip install -r app-repo\requirements.txt`.
5. **Shortcuts**: Desktop + Start Menu "Warframe Toolbox" →
   `pythonw.exe "…\app-repo\Warframe Toolbox.pyw"` (PowerShell-generated
   `.lnk`, icon = `app\assets\logo.ico`).
6. Prints a success line and offers to launch.

Re-running the installer on a machine that already has everything is
harmless: each step is skip-if-present (idempotent).

Failure handling: each step checks its outcome and stops with a plain-English
message ("Python install failed — send Daniel this window") rather than
continuing broken.

## Component 2 — updater: `app/core/updater.py`

Stdlib-only core module (subprocess + paths); no UI imports. All git calls
run with `CREATE_NO_WINDOW`, a timeout, and `cwd=paths.ROOT`.

- `find_git() -> str | None`: `git` on PATH, else the bundled
  `<install root>\mingit\cmd\git.exe` (resolved relative to `paths.ROOT`'s
  parent), else None.
- `should_check(settings) -> bool`: False unless ALL hold — setting on,
  `paths.ROOT/.git` exists, git found, current branch is `main`, working
  tree clean (`git status --porcelain` empty). The branch/dirty rules are
  what keep the Dev clone from self-updating mid-feature.
- `check_and_update() -> UpdateResult`: `git fetch` → if
  `git rev-list --count HEAD..origin/main` > 0: `git pull --ff-only`; if
  `requirements.txt` changed in the pull (compare hash before/after),
  `python -m pip install -r requirements.txt --quiet`. Returns a small
  dataclass: `checked/updated/new_version/error` (new_version parsed from the
  pulled `app/core/version.py` text, NOT imported — the running process keeps
  its old module).
- Wired in `ui/app.py` beside the collector warmup: a deferred
  `ui.work`-style background job a few seconds after the window shows;
  result marshalled back on a bound method (never a lambda).

Degrade-to-silence: any git error, network failure, or timeout returns an
error result that is logged to the collect/debug path and shows nothing —
an offline launch must feel identical to a current one.

## Component 3 — surfaces

- `config.DEFAULTS["check_updates"] = True`; Settings > Display checkbox
  "Check for updates at launch" (standard bound-checkbox pattern).
- After a successful pull: one line on the Home status panel —
  "Updated to <version> — takes effect next launch." Nothing else changes
  until restart.
- About page (Settings explorer): shows the pending version next to the
  running one when they differ.
- Per [[surfaces-track-source-changes]]: docs/DEVELOPMENT.md release section
  updated (release = merge to main + push; delivery is automatic), README
  "Running" note updated.

## Component 4 — Daniel's machine convergence (execution steps, this chapter)

1. Daniel creates the fine-grained PAT (UI steps in DEVELOPMENT.md).
2. Generate `Install Warframe Toolbox.bat` from the template + token; he
   keeps the file to Discord to the friend.
3. Run the installer on Daniel's machine → installed live copy at
   `%LOCALAPPDATA%\Programs\WarframeToolbox\app-repo`, which adopts his
   existing data home untouched.
4. Verify: app launches, logged in, updater pulls a test commit.
5. Re-register autostart + watcher from the new copy (Settings toggles
   off/on), THEN retire `D:\Projects_AI\Warframe Toolbox` (the old live
   clone). Dev clone stays at `D:\Projects_AI\Warframe Toolbox Dev`.
6. Update memories: working-directory (sessions now start in the Dev clone),
   wf-market-app (live copy location).

## Not in scope (explicitly)

- No .exe/PyInstaller packaging (next chapter, unchanged).
- No update channel/branch selection — `main` is the only channel.
- No rollback UI — a bad release is fixed by pushing a fix (or
  `git reset` guidance in DEVELOPMENT.md).
- The token grants read to whoever has the installer file — accepted for a
  trusted friend; revocation is the mitigation.

## Testing

- `tests/test_updater.py`: pure-logic tests with a fake git runner —
  should_check matrix (toggle off / no .git / no git / branch≠main / dirty),
  update flow (behind → pull called; current → no pull; requirements change
  → pip called; git error → error result, no raise). No network, no real
  git required beyond what exists.
- Settings toggle test alongside the existing bound-checkbox tests.
- Suite stays green offline; no test can trigger a real fetch because the
  updater runs only from `main()`'s deferred startup job, which no test
  executes — `test_updater.py` drives the module directly with a fake
  runner instead.

## Verification (end of chapter)

1. Suite green (incl. new tests) in Dev clone.
2. Friend-simulation: run the installer in a scratch VM-like state (or at
   minimum on Daniel's machine) → app installs, launches, logs in fresh.
3. Push a trivial commit → installed copy's next launch pulls it and shows
   the notice; version visible in About after restart.
4. Toggle off → no fetch happens (verify via reflog/absence).
5. Dev clone on a dirty feature branch → updater skips.
6. Old live folder retired; autostart entries point at the installed copy.
