# Changelog

All notable changes to Warframe Toolbox are recorded here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and the project uses [Semantic Versioning](https://semver.org/) — `MAJOR.MINOR.PATCH`.
The current version always lives in `app/core/version.py`.

## [Unreleased]

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
