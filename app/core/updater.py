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
exception into the caller. An offline launch must feel identical to a
current one.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass

from core import paths
from core import version as _version

_NO_WINDOW = 0x08000000 if os.name == "nt" else 0

#: The installer's bundled MinGit, beside the app-repo clone
#: (<install root>\mingit\cmd\git.exe). Absent on machines with system git.
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


def find_git() -> str | None:
    """System git first, then the installer's bundled MinGit."""
    path = shutil.which("git")
    if path:
        return path
    if _MINGIT.is_file():
        return str(_MINGIT)
    return None


def should_check(settings: dict, run=_run, git: str | None = None) -> bool:
    """All rails must hold; `git=` lets tests bypass find_git()."""
    if not settings.get("check_updates"):
        return False
    if not (paths.ROOT / ".git").exists():
        return False
    git = git if git is not None else find_git()
    if not git:
        return False
    rc, out = run([git, "rev-parse", "--abbrev-ref", "HEAD"])
    if rc != 0 or out.strip() != "main":
        return False
    rc, out = run([git, "status", "--porcelain"])
    return rc == 0 and out.strip() == ""


def file_version() -> str | None:
    """The version string in core/version.py ON DISK (the running process
    keeps its imported module, so after a pull these can differ)."""
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
    """fetch -> behind? -> pull --ff-only -> pip only if requirements
    changed. Returns rather than raises, always."""
    if not should_check(settings, run=run):
        return UpdateResult(checked=False)
    git = find_git() or "git"
    rc, out = run([git, "fetch", "--quiet", "origin"], timeout=120)
    if rc != 0:
        return UpdateResult(checked=True, error=out.strip() or "fetch failed")
    rc, out = run([git, "rev-list", "--count", "HEAD..origin/main"])
    if rc != 0:
        return UpdateResult(checked=True,
                            error=out.strip() or "rev-list failed")
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
        # Deps changed with this update - install them for next launch.
        # A failure is non-fatal: the next launch's check retries the pip.
        run([sys.executable, "-m", "pip", "install", "--quiet",
             "--disable-pip-version-check", "-r", str(req)], timeout=600)
    return UpdateResult(checked=True, updated=True,
                        new_version=file_version())
