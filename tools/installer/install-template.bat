@echo off
setlocal EnableDelayedExpansion
rem == Warframe Toolbox beta installer ==========================================
rem Installs per-user: Python 3.11 (python.org) if missing, portable MinGit if
rem no git exists, downloads the app, installs its packages, adds shortcuts.
rem Nothing here needs administrator rights. Re-running is safe.

set "ROOT=%LOCALAPPDATA%\Programs\WarframeToolbox"
set "REPO=%ROOT%\app-repo"
set "PYEXE=%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
set "PYWEXE=%LOCALAPPDATA%\Programs\Python\Python311\pythonw.exe"
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
    powershell -NoProfile -Command "[Net.ServicePointManager]::SecurityProtocol='Tls12'; Invoke-WebRequest -Uri '%PYURL%' -OutFile (Join-Path $env:TEMP 'wftb-python.exe')"
    if errorlevel 1 goto :fail
    echo        Installing Python ^(per-user, silent^) ...
    "%TEMP%\wftb-python.exe" /quiet InstallAllUsers=0 PrependPath=1 Include_launcher=1 InstallLauncherAllUsers=0 Include_test=0
    if not exist "%PYEXE%" goto :fail
)

rem -- 2) Git ------------------------------------------------------------------
set "GITEXE=git"
where git >nul 2>nul
if not errorlevel 1 (
    echo [2/5] Using the git already on this machine.
) else (
    if not exist "%ROOT%\mingit\cmd\git.exe" (
        echo [2/5] Downloading portable Git ^(MinGit^) ...
        powershell -NoProfile -Command "[Net.ServicePointManager]::SecurityProtocol='Tls12'; Invoke-WebRequest -Uri '%GITURL%' -OutFile (Join-Path $env:TEMP 'wftb-mingit.zip'); Expand-Archive -Force (Join-Path $env:TEMP 'wftb-mingit.zip') '%ROOT%\mingit'"
        if errorlevel 1 goto :fail
    ) else (
        echo [2/5] Bundled MinGit already present.
    )
    set "GITEXE=%ROOT%\mingit\cmd\git.exe"
)

rem -- 3) The app (clone, or update an existing install) -----------------------
if exist "%REPO%\.git" (
    echo [3/5] App already present - pulling the latest instead.
    "!GITEXE!" -C "%REPO%" pull --ff-only
) else (
    echo [3/5] Downloading Warframe Toolbox ...
    "!GITEXE!" clone --quiet "%CLONEURL%" "%REPO%"
    if errorlevel 1 goto :fail
)

rem -- 4) Python packages -------------------------------------------------------
echo [4/5] Installing Python packages ^(PySide6 is large, this takes a bit^) ...
"%PYEXE%" -m pip install --quiet --disable-pip-version-check -r "%REPO%\requirements.txt"
if errorlevel 1 goto :fail

rem -- 5) Shortcuts -------------------------------------------------------------
echo [5/5] Creating shortcuts ...
powershell -NoProfile -Command ^
  "$ws = New-Object -ComObject WScript.Shell;" ^
  "$py = Join-Path $env:LOCALAPPDATA 'Programs\Python\Python311\pythonw.exe';" ^
  "$app = Join-Path $env:LOCALAPPDATA 'Programs\WarframeToolbox\app-repo\Warframe Toolbox.pyw';" ^
  "$repo = Join-Path $env:LOCALAPPDATA 'Programs\WarframeToolbox\app-repo';" ^
  "$ico = Join-Path $repo 'app\assets\logo.ico';" ^
  "$sm = Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs\Warframe Toolbox';" ^
  "New-Item -ItemType Directory -Force $sm | Out-Null;" ^
  "$desk = [Environment]::GetFolderPath('Desktop');" ^
  "foreach ($p in @((Join-Path $desk 'Warframe Toolbox.lnk'), (Join-Path $sm 'Warframe Toolbox.lnk'))) {" ^
  "  $s = $ws.CreateShortcut($p); $s.TargetPath = $py;" ^
  "  $s.Arguments = ('\"' + $app + '\"'); $s.IconLocation = $ico;" ^
  "  $s.WorkingDirectory = $repo; $s.Save() };" ^
  "$u = $ws.CreateShortcut((Join-Path $sm 'Uninstall Warframe Toolbox.lnk'));" ^
  "$u.TargetPath = (Join-Path $repo 'uninstall.bat'); $u.Save()"
if errorlevel 1 goto :fail

echo.
echo Done. Warframe Toolbox is installed - shortcut is on the Desktop.
echo (It keeps itself up to date automatically each time it starts.)
choice /C YN /M "Launch it now"
if %errorlevel%==1 start "" "%PYWEXE%" "%REPO%\Warframe Toolbox.pyw"
exit /b 0

:fail
echo.
echo Something went wrong - please screenshot this window and send it to Daniel.
pause
exit /b 1
