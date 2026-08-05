# Development

How to set up, test, and ship changes. The module map is in
`ARCHITECTURE.md`; design rules in `STYLE_GUIDE.md`.

## Setup

```bash
git clone git@github.com:mortefix/Warframe-Toolbox.git
cd Warframe-Toolbox
pip install -r requirements.txt      # requests, websocket-client, PySide6-{Essentials,Addons}
python tests/run_all.py              # must be green before you start
```

Requires Python 3.11+. Launch with a double-click on `Warframe Toolbox.pyw`
(or `python "Warframe Toolbox.pyw"` from a terminal). Startup errors land in
`<data root>/launch-error.log` (beside the launcher only if `core.paths`
itself failed to import).

## Dev / live split

The **live copy** is the working install; its data lives in the per-machine
home (`%LOCALAPPDATA%\WarframeToolbox` - see the Store-Python caveat in
ARCHITECTURE.md). A **dev clone** opts into portable data instead:

```bash
git clone git@github.com:mortefix/Warframe-Toolbox.git "Warframe Toolbox Dev"
cd "Warframe Toolbox Dev"
mkdir userdata          # gitignored portable override - THIS makes it a dev copy
```

With `userdata/` present, every file the dev copy writes stays inside the
clone: both copies run simultaneously (separate locks, separate browser
profiles), and nothing you do in dev can touch live data.

Workflow: branch in the dev clone → make it work → `python tests/run_all.py`
green → merge/push → in the live copy `git pull --ff-only` (or just run
`update.bat`).

## Versioning

`app/core/version.py` is the only place a version number lives
(`__version__`, `APP_NAME`, and the derived warframe.market `USER_AGENT`).
Bump `__version__` and the About page and every HTTP surface follow. The
Overwolf companion's `manifest.json` versions independently.

## Releasing to the beta tester

The beta channel is the **public** git repo: the tester runs an Inno Setup
`.exe` installer, and the app **updates itself at launch** (`core/updater.py`;
toggle in Settings > Display, default on).

Build the installer (one-time: `winget install JRSoftware.InnoSetup`):

    iscc "tools\installer\installer.iss"   ->  tools\installer\Install Warframe Toolbox.exe

Send `Install Warframe Toolbox.exe` over Discord. No token, no GitHub account,
and no per-tester build - the repo is public, so the installer clones
anonymously and one `.exe` works for everyone. Full note:
`tools/installer/BUILD.md`.

The tester double-clicks it (a one-time SmartScreen "More info -> Run anyway",
since it is unsigned). With no admin rights it accepts the GPL license,
installs python.org Python 3.11 per-user if missing, uses the machine's git or
drops a portable MinGit beside the app, clones to
`%LOCALAPPDATA%\Programs\WarframeToolbox\app-repo`, installs deps, and creates
the chosen Desktop/Start Menu shortcuts. It **closes a running copy first**, so
reinstalling over a running app is safe. Uninstall is via "Add or remove
programs" (or the Start Menu entry) and **asks before deleting user data**.

Ship a release: merge to `main`, push. Their app pulls it on next launch;
new deps are pip-installed automatically when `requirements.txt` changed.
Their data lives in their own `%LOCALAPPDATA%\WarframeToolbox` - a pull can
never touch it.

`update.bat` remains as the manual fallback path (pull-then-launch) - e.g.
when the toggle is off or a launch-time pull failed.

## Packaging

The shipping installer is an **Inno Setup bootstrapper**
(`tools/installer/installer.iss`) that installs Python and clones the app - see
"Releasing to the beta tester" above and `tools/installer/BUILD.md`. The app
still runs as `.pyw` under python.org `pythonw.exe`.

A fully **frozen** build (no Python needed on the tester's machine) is the
next chapter, not yet started:

- PyInstaller **onedir** (not onefile); entry point = the launcher.
- `config.set_launcher(...)` already exists precisely so a frozen .exe can
  register ITSELF in the HKCU Run entries instead of the .pyw.
- A frozen build embeds python.org Python, which also retires the
  Store-Python data-virtualization caveat.
- Updates then shift from git-pull to release zips.

## Things that bite (project-specific)

- **Never run two processes against one browser profile.** The Chromium
  profile is single-process; the app guards with a QLockFile in the data
  root. Tests must call `ui.web.isolate_for_tests()`.
- **The test runner isolates data.** `run_all.py` exports `WFTOOLBOX_DATA`
  to a temp dir. If a test "worked yesterday" and fails on data access, it
  was probably depending on real user data - fix the test, not the guard
  (this happened: test_qt_shell silently read the developer's real session).
- **Store Python virtualizes `%LOCALAPPDATA%` writes** - see
  ARCHITECTURE.md. Explorer won't show the data at the documented path while
  the app runs under Store Python.
- **HKCU Run entries bake absolute paths.** After moving the folder or
  switching interpreters, the first real launch heals them
  (`config.repair_run_entries`).
- Windows Store aliases: `Stop-Process -Name pythonw` silently no-ops; the
  real process names are `python3.11` / `pythonw3.11`.
