# Beta Installer + In-App Auto-Update Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A Discord-able installer (+ shipped uninstaller) that puts a self-updating Warframe Toolbox on any Windows machine, pulling from the private repo via an embedded read-only token; the app checks for updates at launch behind a Settings toggle.

**Architecture:** Auth lives in the clone's git remote URL (token-embedded HTTPS), never in app code. `app/core/updater.py` is a stdlib-only core module with an injected command-runner for tests; `ui/app.py` triggers it from a deferred background job; Settings/Home/About surface the toggle and results. The installer/uninstaller are batch files that shell out to PowerShell for downloads, zip-extraction, and shortcuts.

**Tech Stack:** Python 3.11 (python.org), git (system or bundled MinGit), PySide6, plain-script test suite (no pytest), Windows batch + PowerShell.

## Global Constraints

- Spec: `docs/superpowers/specs/2026-08-04-beta-installer-auto-update-design.md` — read it first.
- `core/` may never import from `ui/`. `core/updater.py` must be importable with no Qt installed.
- Tests are plain scripts using the repo's `check(name, got, want)` pattern; run via `python tests/run_all.py`; every task ends suite-green.
- No test may hit the network or run a real `git fetch`/`pull` — the updater's tests inject a fake runner.
- All subprocess git/pip calls: `creationflags=0x08000000` (CREATE_NO_WINDOW) on Windows, explicit `timeout`, `cwd=paths.ROOT`.
- Wire background results to **bound methods, never lambdas** (Qt drops queued signals whose receiver died).
- New user-visible strings follow the existing tone; new settings key must be added to `config.DEFAULTS` (unknown keys are dropped on reload).
- Install layout on a target machine: `%LOCALAPPDATA%\Programs\WarframeToolbox\` containing `mingit\` (optional) and `app-repo\` (the clone). Repo remote URL format: `https://x-access-token:<TOKEN>@github.com/mortefix/Warframe-Toolbox.git`.
- Commit after every task; end git commit messages with the session trailer already used in this repo.

---

### Task 1: `core/updater.py` — decision logic + update flow (TDD)

**Files:**
- Create: `app/core/updater.py`
- Test: `tests/test_updater.py`

**Interfaces:**
- Consumes: `core.paths.ROOT`, `core.version.__version__`.
- Produces (later tasks rely on these exact names):
  - `UpdateResult` dataclass: `checked: bool`, `updated: bool = False`, `new_version: str | None = None`, `error: str | None = None`
  - `find_git(run=_run) -> str | None`
  - `should_check(settings: dict, run=_run, git: str | None = None) -> bool`
  - `check_and_update(settings: dict, run=_run) -> UpdateResult`
  - `pending_version() -> str | None`
  - `_run(cmd: list[str], timeout: int = 60) -> tuple[int, str]` (returncode, stdout+stderr text)

- [ ] **Step 1: Write the failing test**

`tests/test_updater.py` (follow the repo's existing test-file shape — sys.path insert, `check()`, exit non-zero on fail):

```python
"""core.updater decision rules + update flow, all against a FAKE runner -
no network, no real git, no real pip ever runs in this file."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "app"))

from core import updater
from core import paths

fails = []


def check(name, got, want=True):
    ok = got == want
    if not ok:
        fails.append(f"{name}: got {got!r}, want {want!r}")
    print(f"  {'ok  ' if ok else 'FAIL'} {name}")


class FakeRun:
    """Scripted runner: maps the first two words of a git command to a
    (rc, out) reply, and records every call for assertions."""
    def __init__(self, replies):
        self.replies = replies
        self.calls = []

    def __call__(self, cmd, timeout=60):
        self.calls.append(cmd)
        key = " ".join(cmd[1:3]) if len(cmd) > 2 else " ".join(cmd[1:])
        return self.replies.get(key, (0, ""))


GIT = "git"          # the fake never executes anything, any string works
ON = {"check_updates": True}
OFF = {"check_updates": False}

CLEAN = {
    "rev-parse --abbrev-ref": (0, "main\n"),
    "status --porcelain": (0, ""),
}

print("should_check")
check("toggle off -> False", updater.should_check(OFF, run=FakeRun(CLEAN), git=GIT), False)
check("clean main + toggle on -> True", updater.should_check(ON, run=FakeRun(CLEAN), git=GIT), True)
check("no git found -> False", updater.should_check(ON, run=FakeRun(CLEAN), git=None), False)
branchy = dict(CLEAN); branchy["rev-parse --abbrev-ref"] = (0, "feature/x\n")
check("non-main branch -> False", updater.should_check(ON, run=FakeRun(branchy), git=GIT), False)
dirty = dict(CLEAN); dirty["status --porcelain"] = (0, " M app/core/x.py\n")
check("dirty tree -> False", updater.should_check(ON, run=FakeRun(dirty), git=GIT), False)

print("\ncheck_and_update")
current = dict(CLEAN)
current["fetch --quiet"] = (0, "")
current["rev-list --count"] = (0, "0\n")
r = updater.check_and_update(ON, run=FakeRun(current))
check("up to date: checked, not updated", (r.checked, r.updated, r.error), (True, False, None))

behind = dict(current)
behind["rev-list --count"] = (0, "2\n")
behind["pull --ff-only"] = (0, "Updating abc..def\n")
fake = FakeRun(behind)
r = updater.check_and_update(ON, run=fake)
check("behind: updated", (r.checked, r.updated, r.error), (True, True, None))
check("behind: pull was actually invoked",
      any(c[1:3] == ["pull", "--ff-only"] for c in fake.calls))
check("behind: reports the on-disk version", r.new_version,
      updater.pending_version() or __import__("core.version", fromlist=["v"]).__version__)

failing = dict(current)
failing["fetch --quiet"] = (1, "fatal: could not read from remote\n")
r = updater.check_and_update(ON, run=FakeRun(failing))
check("fetch failure: error result, no raise",
      (r.checked, r.updated, r.error is not None), (True, False, True))

print("\npending_version")
check("pending is None when file matches running version",
      updater.pending_version(), None)

if fails:
    print(f"\n{len(fails)} FAILURES:")
    [print(" -", f) for f in fails]
    raise SystemExit(1)
print("\nall updater checks passed")
```

- [ ] **Step 2: Run it to verify it fails**

Run: `python tests\test_updater.py` (from the repo root)
Expected: FAIL with `ImportError: cannot import name 'updater'` (module does not exist yet).

- [ ] **Step 3: Implement `app/core/updater.py`**

```python
"""
core/updater.py - launch-time self-update from the git remote.

The install IS a git clone; auth (if any) is baked into the remote URL by
the installer, so everything here is plain git. All decision logic takes an
injected `run` callable so tests never execute a real process.

Safety rails (should_check): the updater silently refuses unless the
check_updates setting is on, the app root is a git repo, a git binary
exists, the branch is main, and the tree is clean. The branch/dirty rules
are what keep a dev clone from self-updating mid-feature.

Degrade-to-silence: every failure becomes an UpdateResult.error, never an
exception into the caller.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from core import paths
from core import version as _version

_NO_WINDOW = 0x08000000 if os.name == "nt" else 0

#: The installer's bundled MinGit, relative to the install root
#: (<root>\mingit\cmd\git.exe beside the app-repo clone).
_MINGIT = paths.ROOT.parent / "mingit" / "cmd" / "git.exe"

_VERSION_FILE = paths.APP_DIR / "core" / "version.py"
_RX_VERSION = re.compile(r'__version__\s*=\s*"([^"]+)"')


@dataclass
class UpdateResult:
    checked: bool
    updated: bool = False
    new_version: str | None = None
    error: str | None = None


def _run(cmd: list[str], timeout: int = 60) -> tuple[int, str]:
    """(returncode, combined output). cwd is ALWAYS the repo root."""
    try:
        p = subprocess.run(cmd, cwd=str(paths.ROOT), capture_output=True,
                           text=True, timeout=timeout,
                           creationflags=_NO_WINDOW)
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except (OSError, subprocess.SubprocessError) as exc:
        return 1, str(exc)


def find_git(run=_run) -> str | None:
    """System git first, then the installer's bundled MinGit."""
    path = shutil.which("git")
    if path:
        return path
    if _MINGIT.is_file():
        return str(_MINGIT)
    return None


def should_check(settings: dict, run=_run, git: str | None = None) -> bool:
    if not settings.get("check_updates"):
        return False
    if not (paths.ROOT / ".git").exists():
        return False
    git = git if git is not None else find_git(run)
    if not git:
        return False
    rc, out = run([git, "rev-parse", "--abbrev-ref", "HEAD"])
    if rc != 0 or out.strip() != "main":
        return False
    rc, out = run([git, "status", "--porcelain"])
    return rc == 0 and out.strip() == ""


def file_version() -> str | None:
    """The version string in core/version.py ON DISK (the running process
    keeps its imported module, so after a pull these differ)."""
    try:
        m = _RX_VERSION.search(_VERSION_FILE.read_text(encoding="utf-8"))
        return m.group(1) if m else None
    except OSError:
        return None


def pending_version() -> str | None:
    """The freshly-pulled version awaiting a restart, or None."""
    on_disk = file_version()
    if on_disk and on_disk != _version.__version__:
        return on_disk
    return None


def check_and_update(settings: dict, run=_run) -> UpdateResult:
    """fetch -> behind? -> pull --ff-only -> pip if requirements changed."""
    if not should_check(settings, run=run):
        return UpdateResult(checked=False)
    git = find_git(run) or "git"
    rc, out = run([git, "fetch", "--quiet", "origin"], timeout=120)
    if rc != 0:
        return UpdateResult(checked=True, error=out.strip() or "fetch failed")
    rc, out = run([git, "rev-list", "--count", "HEAD..origin/main"])
    if rc != 0:
        return UpdateResult(checked=True, error=out.strip() or "rev-list failed")
    if out.strip() == "0":
        return UpdateResult(checked=True)

    req = paths.ROOT / "requirements.txt"
    try:
        before = req.read_bytes()
    except OSError:
        before = b""
    rc, out = run([git, "pull", "--ff-only", "--quiet"], timeout=300)
    if rc != 0:
        return UpdateResult(checked=True, error=out.strip() or "pull failed")
    try:
        after = req.read_bytes()
    except OSError:
        after = before
    if after != before:
        # deps changed with this update - install them for next launch;
        # a failure is non-fatal (next launch's check retries the pip).
        run([sys.executable, "-m", "pip", "install", "--quiet",
             "--disable-pip-version-check", "-r", str(req)], timeout=600)
    return UpdateResult(checked=True, updated=True,
                        new_version=file_version())
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `python tests\test_updater.py`
Expected: all checks pass, exit 0.

- [ ] **Step 5: Full suite green, then commit**

Run: `python tests\run_all.py` → 34 files pass (33 + the new one).

```bash
git add app/core/updater.py tests/test_updater.py
git commit -m "Updater core: launch-time self-update with injected runner"
```

---

### Task 2: `check_updates` setting + Settings > Display toggle

**Files:**
- Modify: `app/core/config.py` (DEFAULTS dict, after `"close_to_tray"` entry)
- Modify: `app/ui/settings.py` (`DisplayPage.__init__` — follow the existing bound-checkbox pattern used by `start_with_windows` / `minimize_to_tray`)
- Test: extend `tests/test_json_guards.py`-style coverage inside `tests/test_updater.py` (settings default) — plus the existing `test_qt_settings.py` must stay green.

**Interfaces:**
- Consumes: `config.DEFAULTS`, DisplayPage's existing `self.checkbox(...)`/bound-key helper (read the file; reuse whatever `start_with_windows` uses).
- Produces: settings key `"check_updates"` (bool, default True) — Task 3 reads it via the app's loaded settings dict.

- [ ] **Step 1: Add the failing check to `tests/test_updater.py`** (append before the FAILURES footer):

```python
print("\nsettings default")
from core import config
check("check_updates defaults ON", config.DEFAULTS.get("check_updates"), True)
```

Run: `python tests\test_updater.py` → FAIL (`None != True`).

- [ ] **Step 2: Add to `config.DEFAULTS`** (keep the dict's comment style):

```python
    "check_updates": True,         # launch-time git self-update (core.updater)
```

- [ ] **Step 3: Add the checkbox to `DisplayPage`**

Open `app/ui/settings.py`, find how `minimize_to_tray` renders its checkbox in `DisplayPage.__init__`, and add directly after it, same helper, key `"check_updates"`, label `"Check for updates at launch"`, blurb line (same voice as neighbours): `"At startup the Toolbox quietly pulls the newest version from its update channel; changes apply on the next launch."`

- [ ] **Step 4: Suite green, commit**

Run: `python tests\run_all.py` → all pass (includes `test_qt_settings.py`).

```bash
git add app/core/config.py app/ui/settings.py tests/test_updater.py
git commit -m "Settings: check-for-updates-at-launch toggle (default on)"
```

---

### Task 3: wire the updater into launch + Home notice + About pending version

**Files:**
- Modify: `app/ui/app.py` (`main()` deferred jobs area ~line 900, and `MainWindow`)
- Modify: `app/ui/home.py` (status panel — add a hidden update-note line)
- Modify: `app/ui/settings.py` (`AboutPage` — pending version line)
- Test: `tests/test_home_status.py` stays green; add a pending-version check to `tests/test_updater.py`.

**Interfaces:**
- Consumes: `updater.check_and_update(settings) -> UpdateResult`, `updater.pending_version()`, the app's existing background-work helper `ui/work` (read `app/ui/work.py` for the exact submit signature — the collector warmup in `MainWindow._refresh_collected_data` is the pattern to copy).
- Produces: `HomeView.set_update_note(text: str)` (shows a small muted line; empty string hides it).

- [ ] **Step 1: HomeView note.** In `app/ui/home.py`, inside the status-panel construction, add a `role="small"` muted label `self._update_note`, hidden by default, plus:

```python
    def set_update_note(self, text: str) -> None:
        """One quiet line under the status lights - '' hides it."""
        self._update_note.setText(text)
        self._update_note.setVisible(bool(text))
```

- [ ] **Step 2: MainWindow wiring.** In `app/ui/app.py`, next to `_refresh_collected_data`, add (copying that method's worker-submission shape exactly):

```python
    def _check_updates(self) -> None:
        """Launch-time self-update, off-thread; silent unless it updated."""
        from core import updater as core_updater

        def job():
            return core_updater.check_and_update(self.settings)

        # same ui.work submission pattern as _refresh_collected_data,
        # delivering to the BOUND METHOD below
        ...

    def _update_check_done(self, result) -> None:
        if getattr(result, "updated", False) and result.new_version:
            home = self._views.get("home")   # use the real view registry name
            if home is not None:
                home.set_update_note(
                    f"Updated to {result.new_version} — takes effect next launch.")
```

(The `...` is the one place the implementer must transplant the repo's real worker call — it is three lines in `_refresh_collected_data`; keep the receiver a bound method.) Then in `main()`, after the `QTimer.singleShot(1500, win._refresh_collected_data)` line:

```python
    QTimer.singleShot(3000, win._check_updates)
```

- [ ] **Step 3: About pending version.** In `AboutPage` (app/ui/settings.py ~1123), where the version renders, append when applicable:

```python
        from core import updater as core_updater
        pending = core_updater.pending_version()
        # e.g. "Version 1.0.0   (1.0.1 installed — restart to apply)"
```

Render with the page's existing label helpers; only shown when `pending` is not None.

- [ ] **Step 4: Suite green, commit**

Run: `python tests\run_all.py` → all pass (Qt tests confirm nothing regressed; no test executes `main()`, so no fetch can occur).

```bash
git add app/ui/app.py app/ui/home.py app/ui/settings.py tests/test_updater.py
git commit -m "Launch update check wired: Home notice + About pending version"
```

---

### Task 4: installer template + generator + uninstaller

**Files:**
- Create: `tools/installer/install-template.bat` (placeholder `__GITHUB_TOKEN__`)
- Create: `tools/installer/make_installer.py`
- Create: `uninstall.bat` (repo root)

**Interfaces:**
- Consumes: nothing from the app (standalone batch/PowerShell).
- Produces: `python tools/installer/make_installer.py <token> [-o OUTFILE]` → writes `Install Warframe Toolbox.bat` (default beside the script); `uninstall.bat` is shipped as-is.

- [ ] **Step 1: `tools/installer/install-template.bat`**

```bat
@echo off
setlocal EnableDelayedExpansion
rem == Warframe Toolbox beta installer ==========================================
rem Installs per-user: Python 3.11 (python.org) if missing, portable MinGit if
rem no git exists, clones the app, installs deps, creates shortcuts.
rem Nothing here needs administrator rights.

set "ROOT=%LOCALAPPDATA%\Programs\WarframeToolbox"
set "REPO=%ROOT%\app-repo"
set "PYEXE=%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
set "PYURL=https://www.python.org/ftp/python/3.11.9/python-3.11.9-amd64.exe"
set "GITURL=https://github.com/git-for-windows/git/releases/download/v2.47.1.windows.1/MinGit-2.47.1-64-bit.zip"
set "CLONEURL=https://x-access-token:__GITHUB_TOKEN__@github.com/mortefix/Warframe-Toolbox.git"

echo == Warframe Toolbox installer ==
if not exist "%ROOT%" mkdir "%ROOT%"

rem -- 1) Python ---------------------------------------------------------------
if exist "%PYEXE%" (
    echo [1/5] Python 3.11 already installed.
) else (
    echo [1/5] Downloading Python 3.11 ...
    powershell -NoProfile -Command "[Net.ServicePointManager]::SecurityProtocol='Tls12'; Invoke-WebRequest -Uri '%PYURL%' -OutFile $env:TEMP+'\wftb-python.exe'" || goto :fail
    echo        Installing (per-user, silent) ...
    "%TEMP%\wftb-python.exe" /quiet InstallAllUsers=0 PrependPath=1 Include_launcher=1 InstallLauncherAllUsers=0 Include_test=0
    if not exist "%PYEXE%" goto :fail
)

rem -- 2) Git ------------------------------------------------------------------
set "GITEXE=git"
where git >nul 2>nul
if %errorlevel%==0 (
    echo [2/5] Using the git already on this machine.
) else (
    if exist "%ROOT%\mingit\cmd\git.exe" (
        echo [2/5] Bundled MinGit already present.
    ) else (
        echo [2/5] Downloading portable Git ^(MinGit^) ...
        powershell -NoProfile -Command "[Net.ServicePointManager]::SecurityProtocol='Tls12'; Invoke-WebRequest -Uri '%GITURL%' -OutFile $env:TEMP+'\wftb-mingit.zip'; Expand-Archive -Force ($env:TEMP+'\wftb-mingit.zip') '%ROOT%\mingit'" || goto :fail
    )
    set "GITEXE=%ROOT%\mingit\cmd\git.exe"
)

rem -- 3) Clone (or update an existing install) --------------------------------
if exist "%REPO%\.git" (
    echo [3/5] App already present - pulling the latest instead.
    "!GITEXE!" -C "%REPO%" pull --ff-only
) else (
    echo [3/5] Downloading Warframe Toolbox ...
    "!GITEXE!" clone --quiet "%CLONEURL%" "%REPO%" || goto :fail
)

rem -- 4) Dependencies ----------------------------------------------------------
echo [4/5] Installing Python packages ^(PySide6 is ~200 MB, please wait^) ...
"%PYEXE%" -m pip install --quiet --disable-pip-version-check -r "%REPO%\requirements.txt" || goto :fail

rem -- 5) Shortcuts -------------------------------------------------------------
echo [5/5] Creating shortcuts ...
powershell -NoProfile -Command ^
  "$ws = New-Object -ComObject WScript.Shell;" ^
  "$py = '%LOCALAPPDATA%\Programs\Python\Python311\pythonw.exe';" ^
  "$app = '%REPO%\Warframe Toolbox.pyw';" ^
  "$ico = '%REPO%\app\assets\logo.ico';" ^
  "$sm = Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs\Warframe Toolbox';" ^
  "New-Item -ItemType Directory -Force $sm | Out-Null;" ^
  "foreach ($p in @((Join-Path $ws.SpecialFolders('Desktop') 'Warframe Toolbox.lnk'), (Join-Path $sm 'Warframe Toolbox.lnk'))) {" ^
  "  $s = $ws.CreateShortcut($p); $s.TargetPath = $py;" ^
  "  $s.Arguments = '\"' + $app + '\"'; $s.IconLocation = $ico;" ^
  "  $s.WorkingDirectory = '%REPO%'; $s.Save() };" ^
  "$u = $ws.CreateShortcut((Join-Path $sm 'Uninstall Warframe Toolbox.lnk'));" ^
  "$u.TargetPath = '%REPO%\uninstall.bat'; $u.Save()" || goto :fail

echo.
echo Done. Warframe Toolbox is installed - shortcut on the Desktop.
choice /C YN /M "Launch it now"
if %errorlevel%==1 start "" "%LOCALAPPDATA%\Programs\Python\Python311\pythonw.exe" "%REPO%\Warframe Toolbox.pyw"
exit /b 0

:fail
echo.
echo Something went wrong - please screenshot this window and send it to Daniel.
pause
exit /b 1
```

- [ ] **Step 2: `tools/installer/make_installer.py`**

```python
"""Generate the Discord-able installer from the template + a GitHub token.

    python tools/installer/make_installer.py github_pat_XXX [-o out.bat]

The token is a fine-grained PAT (repo-scoped, Contents: Read-only). It is
embedded in the clone URL, so it never touches app code."""
import argparse
from pathlib import Path

HERE = Path(__file__).resolve().parent
TEMPLATE = HERE / "install-template.bat"
PLACEHOLDER = "__GITHUB_TOKEN__"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("token")
    ap.add_argument("-o", "--out",
                    default=str(HERE / "Install Warframe Toolbox.bat"))
    args = ap.parse_args()
    if not args.token.startswith("github_pat_"):
        raise SystemExit("that does not look like a fine-grained PAT "
                         "(expected github_pat_...)")
    text = TEMPLATE.read_text(encoding="utf-8")
    if PLACEHOLDER not in text:
        raise SystemExit("placeholder missing from template")
    Path(args.out).write_text(text.replace(PLACEHOLDER, args.token),
                              encoding="utf-8")
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: `uninstall.bat`** (repo root)

```bat
@echo off
setlocal
rem == Warframe Toolbox uninstaller =============================================
rem Removes the app install. Your DATA (session, logins, settings in
rem %LOCALAPPDATA%\WarframeToolbox) is KEPT unless you explicitly say yes.

set "ROOT=%LOCALAPPDATA%\Programs\WarframeToolbox"

rem A batch file cannot delete its own folder - re-exec from TEMP once.
if /I not "%~dp0"=="%TEMP%\" (
    copy /Y "%~f0" "%TEMP%\wftb-uninstall.bat" >nul
    start "" cmd /c ""%TEMP%\wftb-uninstall.bat""
    exit /b 0
)

echo == Warframe Toolbox uninstaller ==
echo Stopping the app if it is running ...
powershell -NoProfile -Command ^
  "Get-CimInstance Win32_Process | Where-Object { $_.Name -like 'python*' -and $_.CommandLine -like ('*' + 'WarframeToolbox\app-repo' + '*') } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }"

echo Removing autostart entries that point at this install ...
powershell -NoProfile -Command ^
  "$k = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run';" ^
  "foreach ($n in 'WarframeToolbox','WarframeToolboxWatcher') {" ^
  "  $v = (Get-ItemProperty $k -ErrorAction SilentlyContinue).$n;" ^
  "  if ($v -like '*WarframeToolbox\app-repo*') { Remove-ItemProperty $k -Name $n } }"

echo Removing shortcuts ...
powershell -NoProfile -Command ^
  "$ws = New-Object -ComObject WScript.Shell;" ^
  "Remove-Item -Force -ErrorAction SilentlyContinue (Join-Path $ws.SpecialFolders('Desktop') 'Warframe Toolbox.lnk');" ^
  "Remove-Item -Recurse -Force -ErrorAction SilentlyContinue (Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs\Warframe Toolbox')"

echo Removing the application folder ...
rd /s /q "%ROOT%" 2>nul

choice /C YN /D N /T 30 /M "Also delete your Warframe Toolbox DATA (session, logins, settings)? Default No"
if %errorlevel%==1 (
    rd /s /q "%LOCALAPPDATA%\WarframeToolbox"
    echo Data deleted.
) else (
    echo Data kept at %LOCALAPPDATA%\WarframeToolbox
)
echo.
echo Uninstalled. (Python 3.11 was left installed - other apps may use it.)
pause
exit /b 0
```

- [ ] **Step 4: Static sanity + URL check**

- `cmd /c "echo off"`-level syntax check: run each .bat with a guard var, e.g. `cmd /c ""tools\installer\install-template.bat"" ` is NOT safe to run wholesale — instead verify: `powershell -Command "Get-Content 'tools/installer/install-template.bat' | Select-String '__GITHUB_TOKEN__'"` shows the placeholder, and `curl -sI` (Bash) both download URLs → `HTTP/2 200` (or 302).
- Run: `python tools/installer/make_installer.py github_pat_TESTTOKEN -o "%TEMP%\t.bat"` → wrote file; confirm the placeholder is gone and the test token present; delete the temp file.

- [ ] **Step 5: Suite green, commit**

```bash
git add tools/installer/ uninstall.bat
git commit -m "Beta installer template + generator, shipped uninstaller"
```

---

### Task 5: docs

**Files:**
- Modify: `docs/DEVELOPMENT.md` ("Releasing to the beta tester" section — replace the clone-by-hand instructions)
- Modify: `README.md` ("Running" section note about update.bat)

**Interfaces:** none (prose).

- [ ] **Step 1: DEVELOPMENT.md** — replace the release section body with: how to mint the fine-grained PAT (Settings → Developer settings → Fine-grained tokens; only `Warframe-Toolbox`; Contents: Read-only; No expiration), `python tools/installer/make_installer.py <token>`, Discord the produced `.bat`; the friend double-clicks it; updates thereafter are automatic (launch check, toggle in Settings > Display); uninstall via Start Menu. Note update.bat is now a fallback/manual path, not the primary channel. Keep the existing dev/live-split section but note Daniel's live copy is now the installed one at `%LOCALAPPDATA%\Programs\WarframeToolbox\app-repo`.
- [ ] **Step 2: README.md** — in "Running", change the beta-tester sentence to point at the installer + auto-update; keep `update.bat` documented as the manual fallback.
- [ ] **Step 3: Commit**

```bash
git add docs/DEVELOPMENT.md README.md
git commit -m "Docs: installer-based beta channel, auto-update as primary"
```

---

### Task 6: Daniel's machine convergence + live verification (interactive)

**Files:** none (operational task; needs the real token and Daniel present).

- [ ] **Step 1:** Receive the fine-grained PAT from Daniel; run `python tools/installer/make_installer.py <token> -o "D:\Install Warframe Toolbox.bat"`. Tell Daniel that exact path — this same file is what he Discords to his friend.
- [ ] **Step 2:** Push all commits (`git push`). Then run the installer on this machine (`cmd /c "D:\Install Warframe Toolbox.bat"` — Python step will skip, git step will skip, clone+pip+shortcuts run). Verify `%LOCALAPPDATA%\Programs\WarframeToolbox\app-repo` exists and `git -C ... remote -v` shows the token URL.
- [ ] **Step 3:** Close the old copy's app if running; launch the installed copy via the new Desktop shortcut. Verify: logged in (existing data adopted), no launch-error.log, Home fine.
- [ ] **Step 4:** Re-register autostart from the installed copy: in its Settings > Display, toggle "Start with Windows" / "Launch with Warframe" off and on (whichever were enabled); verify both HKCU Run entries now contain `app-repo`.
- [ ] **Step 5:** End-to-end update proof: make a trivial commit in the old working repo (e.g. bump a comment), push; relaunch the installed copy; expect the Home notice "Updated to … — takes effect next launch" (or confirm `git -C ...\app-repo log --oneline -1` advanced). Toggle the setting off, push another trivial commit, relaunch, verify NO pull happened; toggle back on.
- [ ] **Step 6:** Retire `D:\Projects_AI\Warframe Toolbox`: confirm `git -C "D:\Projects_AI\Warframe Toolbox" status --porcelain` is empty and fully pushed, then delete the folder. Future feature work: `D:\Projects_AI\Warframe Toolbox Dev`.
- [ ] **Step 7:** Update memories: `working-directory` (sessions start in the Dev clone now), `wf-market-app` (live copy = installed at `%LOCALAPPDATA%\Programs\WarframeToolbox\app-repo`), MEMORY.md index lines.

---

## Self-review notes

- Spec coverage: installer (T4), uninstaller (T4), updater module + rails (T1), toggle (T2), wiring/notice/About (T3), docs (T5), convergence + verification (T6). Testing section satisfied by T1/T2/T3 suite gates.
- The fake-runner keying (`cmd[1:3]`) matches every git invocation the module makes (`rev-parse --abbrev-ref`, `status --porcelain`, `fetch --quiet`, `rev-list --count`, `pull --ff-only`).
- `find_git` in `should_check` is bypassed in tests via the `git=` parameter, so `shutil.which` never interferes with the fake.
- Batch files use PowerShell for anything fragile (downloads, zip, shortcuts, registry) — batch stays a thin driver.
