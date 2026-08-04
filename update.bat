@echo off
rem Warframe Toolbox - update then launch (the beta channel).
rem git pull is fast-forward only, so a locally modified clone is never
rem silently merged; offline (or any pull failure) still launches the app.
cd /d "%~dp0"
git pull --ff-only
if errorlevel 1 echo (update skipped - offline or pull failed; launching anyway)
start "" pythonw "Warframe Toolbox.pyw"
