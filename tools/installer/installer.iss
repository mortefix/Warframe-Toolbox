; Warframe Toolbox - bootstrapper installer (requires Inno Setup 6.3+)
; Public repo: clones anonymously, no token. Per-user, no admin.
; Build:  iscc "tools\installer\installer.iss"   ->  Install Warframe Toolbox.exe

#define AppName        "Warframe Toolbox"
#define AppPublisher   "mortefix"
#define RepoURL        "https://github.com/mortefix/Warframe-Toolbox.git"
#define IssuesURL      "https://github.com/mortefix/Warframe-Toolbox/issues/new"
#define PyVersion      "3.11.9"
#define PyInstallerURL "https://www.python.org/ftp/python/3.11.9/python-3.11.9-amd64.exe"
#define MinGitURL      "https://github.com/git-for-windows/git/releases/download/v2.47.1.windows.1/MinGit-2.47.1-64-bit.zip"

[Setup]
AppId={{A1F5C7E2-4B93-4D6A-9C0E-3F2B1A8D7E6C}
AppName={#AppName}
AppVersion={#PyVersion}
AppPublisher={#AppPublisher}
DefaultDirName={localappdata}\Programs\WarframeToolbox
DisableDirPage=no
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=.
OutputBaseFilename=Install Warframe Toolbox
SetupIconFile=..\..\app\assets\logo.ico
UninstallDisplayIcon={app}\logo.ico
UninstallDisplayName={#AppName}
WizardStyle=modern
LicenseFile=license.txt

[Files]
Source: "..\..\app\assets\logo.ico"; DestDir: "{app}"; DestName: "logo.ico"; Flags: ignoreversion

[Icons]
Name: "{autodesktop}\Warframe Toolbox"; Filename: "{localappdata}\Programs\Python\Python311\pythonw.exe"; Parameters: """{app}\app-repo\Warframe Toolbox.pyw"""; WorkingDir: "{app}\app-repo"; IconFilename: "{app}\logo.ico"; Check: WantDesktopIcon
Name: "{autoprograms}\Warframe Toolbox\Warframe Toolbox"; Filename: "{localappdata}\Programs\Python\Python311\pythonw.exe"; Parameters: """{app}\app-repo\Warframe Toolbox.pyw"""; WorkingDir: "{app}\app-repo"; IconFilename: "{app}\logo.ico"; Check: WantStartMenuIcon
Name: "{autoprograms}\Warframe Toolbox\Uninstall Warframe Toolbox"; Filename: "{uninstallexe}"; IconFilename: "{app}\logo.ico"; Check: WantStartMenuIcon

[Run]
Filename: "{localappdata}\Programs\Python\Python311\pythonw.exe"; Parameters: """{app}\app-repo\Warframe Toolbox.pyw"""; WorkingDir: "{app}\app-repo"; Description: "Launch Warframe Toolbox now"; Flags: postinstall nowait skipifsilent

[UninstallDelete]
Type: filesandordirs; Name: "{app}\app-repo"
Type: filesandordirs; Name: "{app}\mingit"
Type: dirifempty; Name: "{autoprograms}\Warframe Toolbox"
Type: dirifempty; Name: "{app}"

[Code]
var
  DownloadPage: TDownloadWizardPage;
  ProgressPage: TOutputProgressWizardPage;
  DesktopCheck: TNewCheckBox;
  StartMenuCheck: TNewCheckBox;

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

{ Full path - Inno's Exec does not PATH-search, and powershell.exe lives in a
  PATH subdirectory (WindowsPowerShell\v1.0), not System32 itself. }
function PowerShellExe(): String;
begin
  Result := ExpandConstant('{sys}\WindowsPowerShell\v1.0\powershell.exe');
end;

{ Stop a running copy launched from THIS install (matched by the app-repo path,
  so a separate dev copy elsewhere is never touched). Kills the whole process
  tree so QtWebEngine children release their lock on app-repo too. }
procedure StopInstalledApp();
var
  ResultCode: Integer;
  Repo, ScriptPath, Content: String;
begin
  Repo := ExpandConstant('{app}\app-repo');
  ScriptPath := ExpandConstant('{tmp}\wftb-stop.ps1');
  { Written to a file (not an inline one-liner) so nested quoting can't break it.
    Recursively kills the pythonw launched from THIS install and its whole tree
    (QtWebEngine children included); a dev copy elsewhere never matches. }
  Content :=
    '$repo = ''' + Repo + '''' + #13#10 +
    'function Kill-Tree($procId) {' + #13#10 +
    '  Get-CimInstance Win32_Process -Filter "ParentProcessId=$procId" -ErrorAction SilentlyContinue | ForEach-Object { Kill-Tree $_.ProcessId }' + #13#10 +
    '  Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue' + #13#10 +
    '}' + #13#10 +
    'Get-CimInstance Win32_Process | Where-Object { ($_.Name -eq ''pythonw.exe'' -or $_.Name -eq ''python.exe'') -and $_.CommandLine -like "*$repo*" } | ForEach-Object { Kill-Tree $_.ProcessId }' + #13#10;
  SaveStringToFile(ScriptPath, Content, False);
  Exec(PowerShellExe(), '-NoProfile -ExecutionPolicy Bypass -File "' + ScriptPath + '"', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  Sleep(3000);  { let QtWebEngine helpers release their file handles }
end;

{ Delete every Start Menu / Desktop shortcut that points at this install,
  wherever the user may have moved or renamed it. Inno only removes shortcuts
  at the exact path it created, so a moved one would otherwise be orphaned. }
procedure RemoveStrayShortcuts();
var
  ResultCode: Integer;
  AppDir, ScriptPath, Content: String;
begin
  AppDir := ExpandConstant('{app}');
  ScriptPath := ExpandConstant('{tmp}\wftb-shortcuts.ps1');
  Content :=
    '$app = ''' + AppDir + '''' + #13#10 +
    '$ws = New-Object -ComObject WScript.Shell' + #13#10 +
    '$roots = @([Environment]::GetFolderPath(''Programs''), [Environment]::GetFolderPath(''CommonPrograms''), [Environment]::GetFolderPath(''Desktop''), [Environment]::GetFolderPath(''CommonDesktopDirectory''))' + #13#10 +
    'foreach ($root in $roots) {' + #13#10 +
    '  if (-not (Test-Path $root)) { continue }' + #13#10 +
    '  Get-ChildItem -Path $root -Filter *.lnk -Recurse -ErrorAction SilentlyContinue | ForEach-Object {' + #13#10 +
    '    try {' + #13#10 +
    '      $sc = $ws.CreateShortcut($_.FullName)' + #13#10 +
    '      if ("$($sc.TargetPath) $($sc.Arguments)" -like "*$app*") { Remove-Item -LiteralPath $_.FullName -Force -ErrorAction SilentlyContinue }' + #13#10 +
    '    } catch {}' + #13#10 +
    '  }' + #13#10 +
    '}' + #13#10;
  SaveStringToFile(ScriptPath, Content, False);
  Exec(PowerShellExe(), '-NoProfile -ExecutionPolicy Bypass -File "' + ScriptPath + '"', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
end;

function ByteToHex(B: Integer): String;
begin
  Result := Copy('0123456789ABCDEF', (B div 16) + 1, 1) + Copy('0123456789ABCDEF', (B mod 16) + 1, 1);
end;

function UrlEncode(const S: String): String;
var
  i: Integer;
  c: Char;
begin
  Result := '';
  for i := 1 to Length(S) do begin
    c := S[i];
    if ((c >= 'A') and (c <= 'Z')) or ((c >= 'a') and (c <= 'z')) or ((c >= '0') and (c <= '9')) then
      Result := Result + c
    else
      Result := Result + '%' + ByteToHex(Ord(c));
  end;
end;

{ Failure dialog: a "Report on GitHub" button (opens a pre-filled issue) and a
  "Close" button. }
procedure ShowFailure(const StepMsg: String);
var
  Buttons: TArrayOfString;
  ResultCode: Integer;
  Url: String;
begin
  SetArrayLength(Buttons, 2);
  Buttons[0] := 'Report on GitHub';
  Buttons[1] := 'Close';
  if TaskDialogMsgBox('Installation failed',
       StepMsg + #13#10#13#10 + 'Nothing was installed. You can open a pre-filled bug report on GitHub, or close Setup and try again.',
       mbCriticalError, MB_YESNO, Buttons, 0) = IDYES then
  begin
    Url := '{#IssuesURL}?title=' + UrlEncode('Installer error') +
           '&body=' + UrlEncode('Step that failed: ' + StepMsg + #13#10#13#10 +
                                 'What happened (please add any details):' + #13#10);
    ShellExecAsOriginalUser('open', Url, '', '', SW_SHOWNORMAL, ewNoWait, ResultCode);
  end;
end;

function WantDesktopIcon: Boolean;
begin
  Result := DesktopCheck.Checked;
end;

function WantStartMenuIcon: Boolean;
begin
  Result := StartMenuCheck.Checked;
end;

procedure InitializeWizard();
begin
  DownloadPage := CreateDownloadPage(SetupMessage(msgWizardPreparing), SetupMessage(msgPreparingDesc), nil);
  ProgressPage := CreateOutputProgressPage('Setting up Warframe Toolbox', 'Please wait while the app is downloaded and set up.');

  { Put the shortcut options on the SAME page as the install location. }
  DesktopCheck := TNewCheckBox.Create(WizardForm);
  DesktopCheck.Parent := WizardForm.SelectDirPage;
  DesktopCheck.Left := WizardForm.DirEdit.Left;
  DesktopCheck.Width := WizardForm.DirEdit.Width;
  DesktopCheck.Height := ScaleY(20);
  DesktopCheck.Top := WizardForm.DirEdit.Top + WizardForm.DirEdit.Height + ScaleY(28);
  DesktopCheck.Caption := 'Create a desktop shortcut';
  DesktopCheck.Checked := True;

  StartMenuCheck := TNewCheckBox.Create(WizardForm);
  StartMenuCheck.Parent := WizardForm.SelectDirPage;
  StartMenuCheck.Left := WizardForm.DirEdit.Left;
  StartMenuCheck.Width := WizardForm.DirEdit.Width;
  StartMenuCheck.Height := ScaleY(20);
  StartMenuCheck.Top := DesktopCheck.Top + ScaleY(26);
  StartMenuCheck.Caption := 'Create a Start Menu shortcut';
  StartMenuCheck.Checked := True;
end;

{ Does the real work: stop a running copy, Python, Git, clone/pull, pip. Returns
  False (and shows a failure dialog) on any error. Runs from the Ready page, so a
  failure never reaches the "finished / launch" page. }
function DoInstallWork(): Boolean;
var
  ResultCode: Integer;
  AppDir, RepoDir, PyInst, MinGitZip: String;
begin
  Result := False;
  AppDir := ExpandConstant('{app}');
  ForceDirectories(AppDir);
  RepoDir := AppDir + '\app-repo';

  ProgressPage.Show;
  try
    { 0) Close any running copy so its files/folder unlock (updates, reinstalls). }
    ProgressPage.SetText('Closing any running copy of Warframe Toolbox...', '');
    ProgressPage.SetProgress(0, 4);
    StopInstalledApp();

    { 1) Python (per-user, no UAC) }
    ProgressPage.SetText('Setting up Python...', '');
    ProgressPage.SetProgress(1, 4);
    if not PythonInstalled() then begin
      PyInst := ExpandConstant('{tmp}\python-{#PyVersion}-amd64.exe');
      if (not Exec(PyInst, '/quiet InstallAllUsers=0 PrependPath=1 Include_launcher=1 InstallLauncherAllUsers=0 Include_test=0', '', SW_SHOW, ewWaitUntilTerminated, ResultCode)) or (not PythonInstalled()) then begin
        ShowFailure('Python could not be installed.');
        Exit;
      end;
    end;

    { 2) Git (portable MinGit if the machine has none) }
    ProgressPage.SetText('Setting up Git...', '');
    ProgressPage.SetProgress(2, 4);
    if (not SystemGitPresent()) and (not FileExists(AppDir + '\mingit\cmd\git.exe')) then begin
      MinGitZip := ExpandConstant('{tmp}\mingit.zip');
      if (not Exec(PowerShellExe(), '-NoProfile -Command "Expand-Archive -Force ''' + MinGitZip + ''' ''' + AppDir + '\mingit''"', '', SW_HIDE, ewWaitUntilTerminated, ResultCode)) or (ResultCode <> 0) then begin
        ShowFailure('Git could not be set up.');
        Exit;
      end;
    end;

    { 3) The app: pull a valid existing clone, else wipe any stale leftover
         and clone fresh (git refuses to clone into a non-empty folder). }
    ProgressPage.SetText('Downloading Warframe Toolbox...', '');
    ProgressPage.SetProgress(3, 4);
    if DirExists(RepoDir + '\.git') then begin
      Exec(GitExe(), 'pull --ff-only', RepoDir, SW_HIDE, ewWaitUntilTerminated, ResultCode);
    end else begin
      if DirExists(RepoDir) then begin
        DelTree(RepoDir, True, True, True);
        if DirExists(RepoDir) then begin  { a lock may not have released yet - retry once }
          Sleep(2000);
          DelTree(RepoDir, True, True, True);
        end;
      end;
      if (not Exec(GitExe(), 'clone --quiet "{#RepoURL}" "' + RepoDir + '"', '', SW_HIDE, ewWaitUntilTerminated, ResultCode)) or (ResultCode <> 0) then begin
        ShowFailure('The app could not be downloaded. Check your internet connection and try again.');
        Exit;
      end;
    end;

    { 4) Python packages (PySide6 is large) }
    ProgressPage.SetText('Installing packages (this can take a few minutes)...', '');
    ProgressPage.SetProgress(4, 4);
    if (not Exec(PythonExe(), '-m pip install --quiet --disable-pip-version-check -r "' + RepoDir + '\requirements.txt"', '', SW_HIDE, ewWaitUntilTerminated, ResultCode)) or (ResultCode <> 0) then begin
      ShowFailure('Installing the Python packages failed.');
      Exit;
    end;
  finally
    ProgressPage.Hide;
  end;
  Result := True;
end;

function NextButtonClick(CurPageID: Integer): Boolean;
begin
  Result := True;
  if CurPageID <> wpReady then Exit;

  { 1) Download any missing prerequisites (Python installer / portable Git). }
  DownloadPage.Clear;
  if not PythonInstalled() then
    DownloadPage.Add('{#PyInstallerURL}', 'python-{#PyVersion}-amd64.exe', '');
  if not SystemGitPresent() then
    DownloadPage.Add('{#MinGitURL}', 'mingit.zip', '');
  DownloadPage.Show;
  try
    try
      DownloadPage.Download;
    except
      if not DownloadPage.AbortedByUser then
        ShowFailure('A required download failed: ' + GetExceptionMessage);
      Result := False;
      Exit;
    end;
  finally
    DownloadPage.Hide;
  end;

  { 2) Do the install work. On failure, stay on the Ready page (Cancel to exit) -
       never advance to the finished/launch page. }
  Result := DoInstallWork();
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  RunKey, Cmd, AppLow, DataDir: String;
  DataButtons: TArrayOfString;
begin
  if CurUninstallStep <> usUninstall then Exit;

  { Stop a running copy first so its files/folder unlock before deletion. }
  StopInstalledApp();

  { Remove any shortcut pointing at this install, even if moved/renamed. }
  RemoveStrayShortcuts();

  RunKey := 'Software\Microsoft\Windows\CurrentVersion\Run';
  AppLow := LowerCase(ExpandConstant('{app}'));
  if RegQueryStringValue(HKCU, RunKey, 'WarframeToolbox', Cmd) then
    if Pos(AppLow, LowerCase(Cmd)) > 0 then
      RegDeleteValue(HKCU, RunKey, 'WarframeToolbox');
  if RegQueryStringValue(HKCU, RunKey, 'WarframeToolboxWatcher', Cmd) then
    if Pos(AppLow, LowerCase(Cmd)) > 0 then
      RegDeleteValue(HKCU, RunKey, 'WarframeToolboxWatcher');

  { Ask before removing user data. The default button is Keep, so a stray Enter
    or reflexive click never destroys data - only an explicit choice does. }
  DataDir := ExpandConstant('{localappdata}\WarframeToolbox');
  if DirExists(DataDir) and (not UninstallSilent()) then begin
    SetArrayLength(DataButtons, 2);
    DataButtons[0] := 'Keep my data';
    DataButtons[1] := 'Delete my data';
    if TaskDialogMsgBox('Remove your data?',
         'Do you also want to delete your Warframe Toolbox data (login session and settings)?' + #13#10#13#10 +
         'Keeping it means a future reinstall picks up right where you left off.',
         mbConfirmation, MB_YESNO, DataButtons, 0) = IDNO then
      DelTree(DataDir, True, True, True);
  end;
end;
