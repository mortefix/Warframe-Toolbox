# .exe Installer (Inno Setup) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the Python-generated `.bat` installer with a single Inno Setup `.exe` that installs Python (if missing), clones the now-public app repo, installs dependencies, and creates shortcuts — runnable from any directory, no admin, no token.

**Architecture:** One Inno Setup script (`tools/installer/installer.iss`) compiled by `iscc` to `Install Warframe Toolbox.exe`. `[Setup]` fixes a per-user install root; `[Files]` ships only the shortcut icon; `[Icons]` makes the Desktop/Start-Menu shortcuts; a `[Code]` (Pascal) section downloads/installs Python and MinGit as needed, clones/pulls the repo, and pip-installs. Uninstall is Inno-native ("Add or remove programs") plus a small code step for the runtime-created files and autostart entries. The installed copy remains a git clone, so the existing in-app updater is untouched.

**Tech Stack:** Inno Setup 6.1+ (Pascal scripting, `TDownloadWizardPage`), Windows PowerShell (zip extraction), git (system or portable MinGit), python.org Python 3.11.9.

## Global Constraints

- **Inno Setup 6.1 or newer** — required for `CreateDownloadPage` / `TDownloadWizardPage`.
- **Per-user, no admin:** `PrivilegesRequired=lowest`. Nothing may require UAC.
- **Install root:** `{localappdata}\Programs\WarframeToolbox` (= Inno `{app}`). App clones into `{app}\app-repo`; portable git into `{app}\mingit`.
- **Python path (per-user python.org):** `{localappdata}\Programs\Python\Python311\python.exe` / `pythonw.exe`. Install flags: `/quiet InstallAllUsers=0 PrependPath=1 Include_launcher=1 InstallLauncherAllUsers=0 Include_test=0`.
- **Repo clone is anonymous (public):** `https://github.com/mortefix/Warframe-Toolbox.git`. No token, no SSH, no credentials anywhere.
- **User data is sacred:** it lives in `{localappdata}\WarframeToolbox` (a *different* dir from `{app}`). Uninstall must never touch it.
- **Autostart entry names:** HKCU `Software\Microsoft\Windows\CurrentVersion\Run` values `WarframeToolbox` and `WarframeToolboxWatcher` — only delete when the value's command points inside `{app}`.
- **Small exe:** MinGit is downloaded at runtime, never bundled (keeps the `.exe` a couple MB, Discord-friendly).
- **Idempotent:** re-running the installer pulls instead of clones and never duplicates shortcuts.
- **Icon source:** `app/assets/logo.ico` (already in the repo), referenced from the `.iss` at `..\..\app\assets\logo.ico`.

---

## File Structure

- **Create** `tools/installer/installer.iss` — the entire installer (Setup, Files, Icons, install Code, uninstall Code). One cohesive file.
- **Create** `tools/installer/BUILD.md` — how to build and ship the `.exe`.
- **Delete** `tools/installer/make_installer.py` — the retired token/template generator.
- **Delete** `tools/installer/install-template.bat` — the retired batch installer body.
- **Modify** `docs/DEVELOPMENT.md` — "Releasing to the beta tester" + "Packaging" sections point at the `.exe` workflow.
- **Modify** `README.md` — "Running" note points at the `.exe`.

Verification for an installer is inherently manual (it is a build artifact, not unit-testable). Each task therefore ends in a **compile + targeted smoke check**, not a pytest run. The Python test suite is not affected by any task here.

---

### Task 1: The installer script (install path)

**Files:**
- Create: `tools/installer/installer.iss`

**Interfaces:**
- Consumes: `app/assets/logo.ico` (icon), the public repo URL, python.org + MinGit download URLs.
- Produces: `Install Warframe Toolbox.exe` (in the current dir when compiled). Establishes install layout `{app}\app-repo`, `{app}\mingit`, `{app}\logo.ico` that Task 2 (uninstall) and the shortcuts rely on.

- [ ] **Step 1: Write `tools/installer/installer.iss`** with the full install-side script:

```pascal
; Warframe Toolbox — bootstrapper installer (requires Inno Setup 6.1+)
; Public repo: clones anonymously, no token. Per-user, no admin.
; Build:  iscc tools\installer\installer.iss   ->  Install Warframe Toolbox.exe

#define AppName        "Warframe Toolbox"
#define AppPublisher   "mortefix"
#define RepoURL        "https://github.com/mortefix/Warframe-Toolbox.git"
#define PyVersion      "3.11.9"
#define PyInstallerURL "https://www.python.org/ftp/python/3.11.9/python-3.11.9-amd64.exe"
#define MinGitURL      "https://github.com/git-for-windows/git/releases/download/v2.47.1.windows.1/MinGit-2.47.1-64-bit.zip"

[Setup]
AppId={{A1F5C7E2-4B93-4D6A-9C0E-3F2B1A8D7E6C}
AppName={#AppName}
AppVersion={#PyVersion}
AppPublisher={#AppPublisher}
DefaultDirName={localappdata}\Programs\WarframeToolbox
DisableDirPage=yes
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=.
OutputBaseFilename=Install Warframe Toolbox
SetupIconFile=..\..\app\assets\logo.ico
UninstallDisplayIcon={app}\logo.ico
UninstallDisplayName={#AppName}
WizardStyle=modern

[Files]
Source: "..\..\app\assets\logo.ico"; DestDir: "{app}"; DestName: "logo.ico"; Flags: ignoreversion

[Icons]
Name: "{autodesktop}\Warframe Toolbox";  Filename: "{localappdata}\Programs\Python\Python311\pythonw.exe"; Parameters: """{app}\app-repo\Warframe Toolbox.pyw"""; WorkingDir: "{app}\app-repo"; IconFilename: "{app}\logo.ico"
Name: "{autoprograms}\Warframe Toolbox"; Filename: "{localappdata}\Programs\Python\Python311\pythonw.exe"; Parameters: """{app}\app-repo\Warframe Toolbox.pyw"""; WorkingDir: "{app}\app-repo"; IconFilename: "{app}\logo.ico"

[Code]
var
  DownloadPage: TDownloadWizardPage;

function PythonExe(): String;
begin
  Result := ExpandConstant('{localappdata}\Programs\Python\Python311\python.exe');
end;

function PythonInstalled(): Boolean;
begin
  Result := FileExists(PythonExe());
end;

function SystemGitPresent(): Boolean;
var
  ResultCode: Integer;
begin
  Result := Exec('cmd.exe', '/C where git', '', SW_HIDE, ewWaitUntilTerminated, ResultCode) and (ResultCode = 0);
end;

function GitExe(): String;
begin
  if SystemGitPresent() then
    Result := 'git'
  else
    Result := ExpandConstant('{app}\mingit\cmd\git.exe');
end;

procedure InitializeWizard();
begin
  DownloadPage := CreateDownloadPage(SetupMessage(msgWizardPreparing), SetupMessage(msgPreparingDesc), nil);
end;

function NextButtonClick(CurPageID: Integer): Boolean;
begin
  Result := True;
  if CurPageID = wpReady then begin
    DownloadPage.Clear;
    if not PythonInstalled() then
      DownloadPage.Add('{#PyInstallerURL}', 'python-{#PyVersion}-amd64.exe', '');
    if not SystemGitPresent() then
      DownloadPage.Add('{#MinGitURL}', 'mingit.zip', '');
    DownloadPage.Show;
    try
      try
        DownloadPage.Download;
        Result := True;
      except
        if not DownloadPage.AbortedByUser then
          SuppressibleMsgBox(AddPeriod(GetExceptionMessage), mbCriticalError, MB_OK, IDOK);
        Result := False;
      end;
    finally
      DownloadPage.Hide;
    end;
  end;
end;

procedure Fail(const Msg: String);
begin
  MsgBox(Msg + #13#10 + 'Please screenshot this window and send it to Daniel.', mbCriticalError, MB_OK);
  Abort();
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  ResultCode: Integer;
  RepoDir, PyInst, MinGitZip: String;
begin
  if CurStep <> ssPostInstall then Exit;

  { 1) Python (per-user, no UAC) }
  if not PythonInstalled() then begin
    WizardForm.StatusLabel.Caption := 'Installing Python {#PyVersion} ...';
    PyInst := ExpandConstant('{tmp}\python-{#PyVersion}-amd64.exe');
    if (not Exec(PyInst, '/quiet InstallAllUsers=0 PrependPath=1 Include_launcher=1 InstallLauncherAllUsers=0 Include_test=0', '', SW_SHOW, ewWaitUntilTerminated, ResultCode)) or (not PythonInstalled()) then
      Fail('Python install failed.');
  end;

  { 2) Git (portable MinGit if the machine has none) }
  if (not SystemGitPresent()) and (not FileExists(ExpandConstant('{app}\mingit\cmd\git.exe'))) then begin
    WizardForm.StatusLabel.Caption := 'Setting up Git ...';
    MinGitZip := ExpandConstant('{tmp}\mingit.zip');
    if (not Exec('powershell.exe', '-NoProfile -Command "Expand-Archive -Force ''' + MinGitZip + ''' ''' + ExpandConstant('{app}\mingit') + '''"', '', SW_HIDE, ewWaitUntilTerminated, ResultCode)) or (ResultCode <> 0) then
      Fail('Git setup failed.');
  end;

  { 3) The app: clone (or pull if re-running) }
  RepoDir := ExpandConstant('{app}\app-repo');
  WizardForm.StatusLabel.Caption := 'Downloading Warframe Toolbox ...';
  if DirExists(RepoDir + '\.git') then begin
    Exec(GitExe(), 'pull --ff-only', RepoDir, SW_HIDE, ewWaitUntilTerminated, ResultCode);
  end else begin
    if (not Exec(GitExe(), 'clone --quiet "{#RepoURL}" "' + RepoDir + '"', '', SW_HIDE, ewWaitUntilTerminated, ResultCode)) or (ResultCode <> 0) then
      Fail('Download of the app failed (network?).');
  end;

  { 4) Python packages (PySide6 is large) }
  WizardForm.StatusLabel.Caption := 'Installing packages (this takes a bit) ...';
  if (not Exec(PythonExe(), '-m pip install --quiet --disable-pip-version-check -r "' + RepoDir + '\requirements.txt"', '', SW_HIDE, ewWaitUntilTerminated, ResultCode)) or (ResultCode <> 0) then
    Fail('Installing Python packages failed.');
end;
```

- [ ] **Step 2: Compile it**

Run: `iscc "tools\installer\installer.iss"`
Expected: `Successful compile` and `Install Warframe Toolbox.exe` appears in `tools\installer\`. If `iscc` isn't found, install Inno Setup first (`winget install JRSoftware.InnoSetup`).

- [ ] **Step 3: Smoke-test a full install from an unrelated directory**

Copy `Install Warframe Toolbox.exe` to `D:\Downloads`, double-click it there (proves it runs from any directory), click through the wizard.
Expected: no UAC prompt; wizard shows "Downloading Warframe Toolbox" / "Installing packages"; on finish, `%LOCALAPPDATA%\Programs\WarframeToolbox\app-repo\` contains the cloned repo, a Desktop shortcut "Warframe Toolbox" exists, and launching it starts the app.

- [ ] **Step 4: Verify idempotency**

Run the same `.exe` again.
Expected: it completes without error, `app-repo` is `git pull`-ed (not re-cloned), and there are no duplicate shortcuts.

- [ ] **Step 5: Commit**

```bash
git add tools/installer/installer.iss
git commit -m "feat(installer): Inno Setup .exe bootstrapper (install side)"
```

---

### Task 2: Uninstall (Add/Remove Programs, data-safe)

**Files:**
- Modify: `tools/installer/installer.iss` (add `[UninstallDelete]` + `CurUninstallStepChanged`)

**Interfaces:**
- Consumes: the install layout from Task 1 (`{app}\app-repo`, `{app}\mingit`) and the autostart value names from Global Constraints.
- Produces: a clean uninstall that removes the app but preserves `{localappdata}\WarframeToolbox`.

- [ ] **Step 1: Add an `[UninstallDelete]` section** to `installer.iss` (place it after `[Icons]`):

```pascal
[UninstallDelete]
Type: filesandordirs; Name: "{app}\app-repo"
Type: filesandordirs; Name: "{app}\mingit"
```

- [ ] **Step 2: Add `CurUninstallStepChanged`** to the `[Code]` section (removes autostart entries only when they point at this install; best-effort stop of a running instance first):

```pascal
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  ResultCode: Integer;
  RunKey, Cmd, AppLow: String;
begin
  if CurUninstallStep <> usUninstall then Exit;

  { Best-effort: stop a running instance launched from this install so its
    files unlock before deletion. Matches on the app-repo path in the command line. }
  Exec('powershell.exe',
    '-NoProfile -Command "Get-CimInstance Win32_Process | ' +
    'Where-Object { $_.CommandLine -like ''*' + ExpandConstant('{app}\app-repo') + '*'' } | ' +
    'ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"',
    '', SW_HIDE, ewWaitUntilTerminated, ResultCode);

  RunKey := 'Software\Microsoft\Windows\CurrentVersion\Run';
  AppLow := LowerCase(ExpandConstant('{app}'));
  if RegQueryStringValue(HKCU, RunKey, 'WarframeToolbox', Cmd) then
    if Pos(AppLow, LowerCase(Cmd)) > 0 then
      RegDeleteValue(HKCU, RunKey, 'WarframeToolbox');
  if RegQueryStringValue(HKCU, RunKey, 'WarframeToolboxWatcher', Cmd) then
    if Pos(AppLow, LowerCase(Cmd)) > 0 then
      RegDeleteValue(HKCU, RunKey, 'WarframeToolboxWatcher');
end;
```

- [ ] **Step 3: Recompile**

Run: `iscc "tools\installer\installer.iss"`
Expected: `Successful compile`, no Pascal errors.

- [ ] **Step 4: Smoke-test uninstall**

Reinstall with the new `.exe`, launch once (so the app writes user data to `%LOCALAPPDATA%\WarframeToolbox`), close it, then uninstall via Settings → Apps → "Warframe Toolbox" → Uninstall.
Expected: `%LOCALAPPDATA%\Programs\WarframeToolbox` (app-repo + mingit + logo) is gone, Desktop/Start-Menu shortcuts are gone, and **`%LOCALAPPDATA%\WarframeToolbox` (your session/settings) still exists**. Confirm any `WarframeToolbox*` HKCU Run values that pointed at the install are removed.

- [ ] **Step 5: Commit**

```bash
git add tools/installer/installer.iss
git commit -m "feat(installer): native uninstall, data-preserving"
```

---

### Task 3: Docs + retire the old installer

**Files:**
- Create: `tools/installer/BUILD.md`
- Delete: `tools/installer/make_installer.py`, `tools/installer/install-template.bat`
- Modify: `docs/DEVELOPMENT.md`, `README.md`

**Interfaces:**
- Consumes: the build command and repo-public fact.
- Produces: no code interface; documentation only.

- [ ] **Step 1: Write `tools/installer/BUILD.md`**

```markdown
# Building the installer

The installer is `tools/installer/installer.iss`, compiled with **Inno Setup 6.1+**.

1. Install Inno Setup once: `winget install JRSoftware.InnoSetup`
2. Build: `iscc "tools\installer\installer.iss"`
3. Ship `tools\installer\Install Warframe Toolbox.exe` (e.g. over Discord).

The repo is public, so the installer clones anonymously — there is no token to
inject and the `.exe` is identical for everyone. The tester double-clicks it
(one-time Windows SmartScreen "More info → Run anyway", since it is unsigned);
it installs per-user with no admin, sets up Python if missing, clones the app,
and makes shortcuts. The installed app then auto-updates itself via git pull.
```

- [ ] **Step 2: Remove the retired generator + template**

```bash
git rm "tools/installer/make_installer.py" "tools/installer/install-template.bat"
```

- [ ] **Step 3: Update `docs/DEVELOPMENT.md`**

In the "Releasing to the beta tester" section, replace the token/`make_installer.py` steps (the `python tools/installer/make_installer.py <token>` line and the fine-grained-PAT paragraph) with:

```markdown
The beta channel is the public git repo. Build the installer once with Inno
Setup (`iscc "tools\installer\installer.iss"` — see tools/installer/BUILD.md)
and send `Install Warframe Toolbox.exe` to the tester. It installs per-user
(no admin), sets up Python if missing, clones the app, and creates shortcuts;
the app then updates itself at launch via git pull. No token or GitHub account
is involved because the repo is public.

Ship a release: merge to `main`, push. The tester's app pulls it on next launch.
```

In the "Packaging (.exe)" section, update the opening line so it no longer says packaging is "not started": note the Inno Setup bootstrapper `.exe` now exists, and that a fully *frozen* PyInstaller build (no Python needed on the tester's machine) remains the future chapter.

- [ ] **Step 4: Update `README.md`**

In the "Running" section, replace the installer sentence so it describes the `.exe`: "Run `Install Warframe Toolbox.exe` (built from `tools/installer/installer.iss`); it installs Python if needed, downloads the app, and makes a Desktop shortcut. The app keeps itself up to date at launch."

- [ ] **Step 5: Commit**

```bash
git add tools/installer/BUILD.md docs/DEVELOPMENT.md README.md
git commit -m "docs(installer): .exe build workflow; retire .bat generator"
```

---

## Final End-to-End Verification

Run through the spec's verification list on a real machine:

1. **Pre-flight (done):** `git clone https://github.com/mortefix/Warframe-Toolbox.git` succeeds with no credentials.
2. **Build:** `iscc "tools\installer\installer.iss"` → `Install Warframe Toolbox.exe`.
3. **Install from an arbitrary folder**, no admin: Python installs if absent, repo clones, deps install, Desktop + Start-Menu shortcuts appear.
4. **Launch** via the shortcut; the app runs and logs in against existing data.
5. **Update path (unchanged):** push a trivial commit → next launch pulls it; Home shows the update notice; About shows the new version after restart.
6. **Idempotent re-run:** installer pulls instead of clones; no duplicate shortcuts.
7. **Uninstall** via Add/Remove Programs: `app-repo`, `mingit`, shortcuts, and matching HKCU Run entries gone; `{localappdata}\WarframeToolbox` user data intact.
8. **Suite:** `python tests/run_all.py` green (unaffected by this change).

## Notes / known follow-ups (not this plan)

- **CLAUDE.md is stale** on one point — it says the project is "not a git repository," but it now is (14 commits, `origin` set). Worth a one-line fix in a separate change; commits in this plan depend on git being present, which it is.
- **Frozen-app `.exe`** (PyInstaller, no Python needed on the tester's box) remains a future chapter, unchanged by this plan.
- **Code signing** to remove the SmartScreen prompt is a future option.
