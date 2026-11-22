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

Two phases, because the app keeps running while its own source changes:
check() only talks to the remote (fetch never touches the working tree);
apply() fast-forwards the files. Between them the caller runs
preload_modules() on the GUI thread, so every module the running process
could still import lazily (a tab opened later, a function-level import) is
already loaded from the OLD tree - new code is never mixed into an old
process. check_and_update() is the two phases back to back, for callers
with nothing to preload.
"""

from __future__ import annotations

import importlib
import os
import pkgutil
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

#: Exists while a dependency install is owed: written before pip runs, removed
#: only when pip succeeds. A failed (or interrupted) install is therefore
#: retried on every later launch until it lands, instead of leaving new code
#: running against old packages forever.
_DEPS_MARKER = paths.USERDATA / "deps_pending"

#: Top-level packages/modules that make up the app (see preload_modules).
_APP_PACKAGES = ("core", "ui", "registry")

_VERSION_FILE = paths.APP_DIR / "core" / "version.py"
_RX_VERSION = re.compile(r'__version__\s*=\s*"([^"]+)"')


@dataclass
class UpdateResult:
    checked: bool
    behind: bool = False          # check(): the remote has commits we lack
    updated: bool = False
    new_version: str | None = None
    error: str | None = None


def _run(cmd: list[str], timeout: int = 60) -> tuple[int, str]:
    """(returncode, combined output). cwd is ALWAYS the repo root.

    Never interactive: there is no console behind pythonw, so a git that
    stops to ask for credentials (an expired token, a remote gone private)
    would sit invisibly until the timeout on every launch. Prompts are
    disabled and stdin is closed, so that case fails at once instead."""
    env = dict(os.environ, GIT_TERMINAL_PROMPT="0", GCM_INTERACTIVE="Never")
    try:
        p = subprocess.run(cmd, cwd=str(paths.ROOT), capture_output=True,
                           text=True, timeout=timeout, env=env,
                           stdin=subprocess.DEVNULL,
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


def _install_deps(run=_run) -> bool:
    """pip-install requirements.txt. The marker goes down BEFORE pip starts
    and comes up only on success, so a failure, a timeout or a killed
    process all leave the install owed (see retry_pending_deps)."""
    req = paths.ROOT / "requirements.txt"
    try:
        _DEPS_MARKER.parent.mkdir(parents=True, exist_ok=True)
        _DEPS_MARKER.write_text("requirements.txt install pending\n",
                                encoding="utf-8")
    except OSError:
        pass                    # unwritable data root: still try the install
    rc, _out = run([sys.executable, "-m", "pip", "install", "--quiet",
                    "--disable-pip-version-check", "-r", str(req)],
                   timeout=600)
    if rc == 0:
        try:
            _DEPS_MARKER.unlink(missing_ok=True)
        except OSError:
            pass
    return rc == 0


def retry_pending_deps(run=_run) -> bool:
    """Finish a dependency install an earlier update left owed. Returns
    True when nothing is (any longer) pending."""
    if not _DEPS_MARKER.exists():
        return True
    return _install_deps(run)


def preload_modules() -> None:
    """Import every module of the app into the running process. Call on the
    GUI thread, after check() says an update is waiting and before apply():
    screens are imported lazily, and a tab first opened AFTER the files
    changed would otherwise load new code against the old modules already in
    memory. Import errors are swallowed - a module that cannot load now could
    not have loaded later either."""
    for name in _APP_PACKAGES:
        try:
            mod = importlib.import_module(name)
        except Exception:                                   # noqa: BLE001
            continue
        for info in pkgutil.walk_packages(getattr(mod, "__path__", []),
                                          name + "."):
            try:
                importlib.import_module(info.name)
            except Exception:                               # noqa: BLE001
                pass


def check(settings: dict, run=_run) -> UpdateResult:
    """Phase 1: fetch and compare. Touches no working-tree file. Also the
    place an owed dependency install is retried - once per launch, whether
    or not a new update exists."""
    if settings.get("check_updates"):
        retry_pending_deps(run)
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
    return UpdateResult(checked=True, behind=out.strip() != "0")


def apply(run=_run) -> UpdateResult:
    """Phase 2: fast-forward to the commit check() fetched, then install
    dependencies if requirements.txt changed.

    A local `merge --ff-only`, not `pull`: the network half already happened
    in check(), so nothing here can stall on a slow connection and be killed
    by the timeout halfway through rewriting files - which would leave a
    dirty tree, and a dirty tree makes should_check() refuse every later
    update."""
    git = find_git() or "git"
    req = paths.ROOT / "requirements.txt"
    try:
        before = req.read_bytes()
    except OSError:
        before = b""
    rc, out = run([git, "merge", "--ff-only", "--quiet", "origin/main"],
                  timeout=300)
    if rc != 0:
        return UpdateResult(checked=True, behind=True,
                            error=out.strip() or "merge failed")
    try:
        after = req.read_bytes()
    except OSError:
        after = before
    if after != before:
        # Deps changed with this update - install them for next launch. A
        # failure is non-fatal here: the marker makes the next launch retry.
        _install_deps(run)
    return UpdateResult(checked=True, updated=True,
                        new_version=file_version())


def check_and_update(settings: dict, run=_run) -> UpdateResult:
    """check() then apply(), for callers with no lazy imports to protect.
    Returns rather than raises, always."""
    result = check(settings, run=run)
    if not result.behind:
        return result
    return apply(run=run)
