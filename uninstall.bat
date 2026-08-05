@echo off
setlocal
rem == Warframe Toolbox uninstaller =============================================
rem Removes the installed app. Your DATA (session, logins, settings in
rem %LOCALAPPDATA%\WarframeToolbox) is KEPT unless you explicitly say yes.

set "ROOT=%LOCALAPPDATA%\Programs\WarframeToolbox"

rem A batch file cannot delete its own folder - re-exec a copy from TEMP once.
if /I not "%~dp0"=="%TEMP%\" (
    copy /Y "%~f0" "%TEMP%\wftb-uninstall.bat" >nul
    start "" cmd /c ""%TEMP%\wftb-uninstall.bat""
    exit /b 0
)

echo == Warframe Toolbox uninstaller ==
echo Stopping the app if it is running ...
powershell -NoProfile -Command ^
  "Get-CimInstance Win32_Process | Where-Object { $_.Name -like 'python*' -and $_.CommandLine -like '*WarframeToolbox\app-repo*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"

echo Removing autostart entries that point at this install ...
powershell -NoProfile -Command ^
  "$k = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run';" ^
  "foreach ($n in 'WarframeToolbox','WarframeToolboxWatcher') {" ^
  "  $v = (Get-ItemProperty $k -ErrorAction SilentlyContinue).$n;" ^
  "  if ($v -like '*WarframeToolbox\app-repo*') { Remove-ItemProperty $k -Name $n } }"

echo Removing shortcuts ...
powershell -NoProfile -Command ^
  "Remove-Item -Force -ErrorAction SilentlyContinue (Join-Path ([Environment]::GetFolderPath('Desktop')) 'Warframe Toolbox.lnk');" ^
  "Remove-Item -Recurse -Force -ErrorAction SilentlyContinue (Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs\Warframe Toolbox')"

echo Removing the application folder ...
rd /s /q "%ROOT%" 2>nul

echo.
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
