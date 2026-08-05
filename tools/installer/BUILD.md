# Building the installer

The installer is `tools/installer/installer.iss`, compiled with **Inno Setup 6.3+**.

1. Install Inno Setup once: `winget install JRSoftware.InnoSetup`
2. Build: `iscc "tools\installer\installer.iss"`
3. Ship `tools\installer\Install Warframe Toolbox.exe` (e.g. over Discord).

The repo is public, so the installer clones anonymously — there is no token to
inject and the `.exe` is identical for everyone. The tester double-clicks it (a
one-time Windows SmartScreen "More info → Run anyway", since it is unsigned); it
accepts the GPL license, installs per-user with no admin, sets up Python 3.11 if
missing, uses the machine's git or drops a portable MinGit, clones the app, and
creates the chosen Desktop/Start Menu shortcuts. It closes a running copy first,
so reinstalling over a running app is safe.

The app then auto-updates itself at launch via git pull. Uninstall is via "Add
or remove programs" (or the Start Menu entry): it stops a running copy, sweeps
the Start Menu/Desktop for the app's shortcuts (even if moved), and asks before
deleting user data.

Notes:

- `license.txt` (GPLv3 + Overwolf linking exception) is shown as the license
  page — keep it committed alongside the script.
- The built `Install Warframe Toolbox.exe` is a throwaway artifact — it is
  gitignored, do not commit it.
- Process control and shortcut cleanup shell out to Windows PowerShell by its
  **full path** (`{sys}\WindowsPowerShell\v1.0\powershell.exe`) — Inno's `Exec`
  does not PATH-search, so the bare name silently fails.
