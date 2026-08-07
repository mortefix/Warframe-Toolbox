"""Settings: a collapsible tree of pages, each owning its own controls.

Two rules carried over from the Tk original because they are decisions, not
plumbing:

  * **Nothing has a Save button.** Every control persists itself the moment it
    changes. A settings screen with a Save button invites you to close it
    without pressing one.
  * **Destructive actions come in two tiers.** Reversible ones ask a plain
    yes/no whose question names the CONSEQUENCE ("you stay signed in
    everywhere"), not just the act. Irreversible ones make you type the word,
    and always say what is *not* destroyed as well as what is.

What is new here: every page sits in a scroll area. The Tk version had none,
so the WF Toolbox page - which grows a row per user file - simply overflowed
off the bottom of the window.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QProcess, Qt, QTimer, Signal
from PySide6.QtWidgets import (QApplication, QCheckBox, QDialog, QFileDialog,
                               QFrame, QGridLayout, QHBoxLayout, QLabel,
                               QLineEdit,
                               QMessageBox, QPlainTextEdit, QPushButton,
                               QScrollArea, QStackedWidget, QVBoxLayout,
                               QWidget)

from core import bookmarks as core_bookmarks
from core import config as core_config
from core import theme as t
from core import updater as core_updater
from core import version as core_version
from core import wf_local
from core import wf_profile
from registry import TOOLS
from ui import work
from ui.widgets import (Dropdown, WrapLabel, glyph_icon, hairline, label,
                        panel, restyle)

#: (section label, [(page key, page label), ...]).
#:
#: SORTED, not hand-ordered. A settings tree is a place people go looking for
#: one named thing, and alphabetical is the only order a stranger can predict.
#: Sorting here rather than in the literal means a page added below lands in
#: the right place without anyone having to remember to put it there.
_PAGES = [("Display", [("window", "Window")]),
          ("Data", [("warframe", "Warframe"),
                    ("market", "Market"),
                    ("web", "Web apps"),
                    ("toolbox", "WF Toolbox")]),
          ("Market", [("messaging", "Messaging")]),
          # Read-only inspectors over the collected-data store. Dev-only panels,
          # not player inventory UI (large libraries show counts).
          ("DevTools", [("dev_worldstate", "WorldState"),
                        ("dev_profile", "Profile"),
                        ("dev_eelog", "EE.log"),
                        ("dev_inventory", "Inventory"),
                        ("dev_mods", "Mods DB")])]

TREE = sorted(((section, sorted(pages, key=lambda kv: kv[1].lower()))
               for section, pages in _PAGES),
              key=lambda sp: sp[0].lower())

NAV_WIDTH = 168
LABEL_COL = 190
#: Bottom inset for the explorer column. MUST match ui.app.NAV_RAIL_MARGIN (the
#: main navbar's bottom margin) so the bottom-pinned About link lines up exactly
#: with the bottom-pinned Settings row across the two columns - measured 8px too
#: low without it, since the explorer otherwise sits flush to the window bottom.
_NAV_BOTTOM = 8


class GoodbyeDialog(QDialog):
    """The type-the-word gate for anything irreversible.

    Kept from Tk deliberately. A yes/no box for a destructive action is one
    reflex click away from gone; typing a word requires reading the sentence
    it is in. The message always states what SURVIVES too, because "delete all
    data" without a boundary reads as "uninstall the app".
    """

    WORD = "goodbye"

    def __init__(self, parent: QWidget, title: str, body: str) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self.setMinimumWidth(t.DIALOG_MIN_W)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(t.SP_XL, t.SP_XL, t.SP_XL, t.SP_XL)
        lay.setSpacing(t.SP_MD)
        head = label(title, role="h2")
        head.setStyleSheet(f"color: {t.WFM_RED};")
        lay.addWidget(head)
        blurb = label(body, role="small")
        blurb.setWordWrap(True)
        lay.addWidget(blurb)
        lay.addWidget(label(f"Type '{self.WORD}' to confirm:", role="small"))
        self.entry = QLineEdit()
        self.entry.textChanged.connect(self._typed)
        lay.addWidget(self.entry)
        row = QHBoxLayout()
        row.addStretch(1)
        cancel = QPushButton("Cancel")
        cancel.setAutoDefault(False)
        cancel.clicked.connect(self.reject)
        row.addWidget(cancel)
        self.ok = QPushButton("Delete")
        self.ok.setEnabled(False)
        self.ok.setDefault(True)     # Enter confirms once the word is typed
        # returnPressed in the field also fires it, but only when it is enabled
        self.entry.returnPressed.connect(
            lambda: self.ok.isEnabled() and self.ok.click())
        self.ok.setStyleSheet(
            f"QPushButton {{ background: {t.WFM_RED_DIM}; color: {t.TEXT};"
            f" padding: 5px 16px; border: none; }}"
            f"QPushButton:disabled {{ background: {t.PANEL};"
            f" color: {t.WFM_EDGE}; }}")
        self.ok.clicked.connect(self.accept)
        row.addWidget(self.ok)
        lay.addLayout(row)

    def _typed(self, text: str) -> None:
        self.ok.setEnabled(text.strip().lower() == self.WORD)

    @classmethod
    def confirmed(cls, parent, title: str, body: str) -> bool:
        dlg = cls(parent, title, body)
        accepted = dlg.exec() == QDialog.Accepted
        dlg.deleteLater()           # else it lingers as a hidden child until app exit
        return accepted


class Note(QLabel):
    """A muted status line that takes no space until it has something to say.

    An empty QLabel still claims a row's height, so three of these sitting
    idle inside a card push its checkboxes apart and make the page's spacing
    look arbitrary. Hiding on empty means the gap appears exactly when the
    text does.
    """

    def __init__(self, text: str = "") -> None:
        super().__init__(text)
        self.setVisible(bool(text))

    def setText(self, text: str) -> None:
        super().setText(text)
        self.setVisible(bool(text))


class Page(QWidget):
    """A settings page: a scrolling body plus one status line at the foot.

    The status line is pinned OUTSIDE the scroll area on purpose - it reports
    what just happened, and a confirmation you have to scroll to find has not
    reported anything.
    """

    def __init__(self, view, title: str) -> None:
        super().__init__()
        self.view = view
        self.setAttribute(Qt.WA_StyledBackground, True)
        #: settings keys this page owns a control for. Recorded by the
        #: helpers below rather than declared, so the list cannot drift from
        #: the widgets - a test asserts every default has a home.
        self.bound_keys: set[str] = set()
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setFrameShape(QFrame.NoFrame)
        # A settings page that scrolls sideways has a layout bug, not a
        # scrolling need: turning the bar off makes the bug show up as
        # clipped text during development instead of shipping as a scrollbar.
        area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        inner = panel()
        self.body = QVBoxLayout(inner)
        self.body.setContentsMargins(t.SP_SCREEN, t.SP_LG, t.SP_SCREEN,
                                     t.SP_LG)
        # ONE gap between sections, everywhere. Explanatory text lives
        # INSIDE the card it explains, so the page is a stack of evenly
        # spaced boxes rather than boxes separated by stray paragraphs.
        self.body.setSpacing(t.SP_LG)
        self.body.addWidget(label(title, role="h1"))
        area.setWidget(inner)
        outer.addWidget(area, 1)

        self.status = label("", role="small")
        self.status.setContentsMargins(t.SP_SCREEN, t.SP_SM, t.SP_SCREEN,
                                       t.SP_MD)
        outer.addWidget(self.status)

    # -- building blocks -----------------------------------------------------

    @property
    def settings(self) -> dict:
        return self.view.settings

    def save(self) -> None:
        core_config.save_settings(self.settings)

    def say(self, text: str, level: str = "ok") -> None:
        self.status.setText(text)
        self.status.setProperty("level", level)
        restyle(self.status)

    def note(self, lay, text: str = ""):
        """A status line inside a section. Takes the section's layout, not
        the page's - a note dropped between two cards reads as belonging to
        neither and breaks the page's rhythm."""
        w = Note(text)
        w.setProperty("role", "muted")
        w.setWordWrap(True)
        lay.addWidget(w)
        return w

    def blurb(self, lay, text: str):
        """Explanatory copy inside a card. WRAPPED and capped to a reading
        measure (610px ~ 76 chars, STYLE_GUIDE §6b) via WrapLabel, whose height
        is computed FOR that cap - a plain capped QLabel is measured at the wider
        cell and the box ends up too short, clipping the copy top and bottom."""
        w = WrapLabel(text)
        w.setProperty("role", "muted")
        lay.addWidget(w)
        return w

    def box(self, title: str) -> QVBoxLayout:
        card = panel("card")
        lay = QVBoxLayout(card)
        lay.setContentsMargins(t.SP_XL, t.SP_LG, t.SP_XL, t.SP_LG)
        lay.setSpacing(t.SP_MD)
        lay.addWidget(label(title, role="h2"))
        self.body.addWidget(card)
        return lay

    def check(self, lay, text: str, key: str, on_change=None) -> QCheckBox:
        """A checkbox bound to a settings key. Saves on every flip."""
        self.bound_keys.add(key)
        cb = QCheckBox(text)
        cb.setChecked(bool(self.settings.get(key,
                                             core_config.DEFAULTS.get(key))))

        def flip(state: bool) -> None:
            self.settings[key] = bool(state)
            self.save()
            if on_change:
                on_change(bool(state))
        cb.toggled.connect(flip)
        lay.addWidget(cb)
        return cb

    def picker(self, lay, text: str, key: str, values: list[str],
               on_change=None) -> Dropdown:
        self.bound_keys.add(key)
        row = QHBoxLayout()
        cap = label(text, role="muted")
        cap.setMinimumWidth(LABEL_COL)
        row.addWidget(cap)
        d = Dropdown(values)
        d.setMinimumWidth(144)     # stacked pickers share a right edge (144 = Fib)
        cur = str(self.settings.get(key, core_config.DEFAULTS.get(key)))
        # A stale or hand-edited value is normalised to the shipped default
        # rather than silently added to the list - the picker is the
        # definition of what is valid.
        d.setCurrentText(cur if cur in values
                         else str(core_config.DEFAULTS.get(key)))
        row.addWidget(d)
        row.addStretch(1)
        lay.addLayout(row)

        def changed(value: str) -> None:
            if value not in values:
                return
            self.settings[key] = value
            self.save()
            if on_change:
                on_change(value)
        d.currentTextChanged.connect(changed)
        return d

    def button(self, text: str, on_click, colour: str = "",
               icon: str = "", danger: bool = False) -> QPushButton:
        b = QPushButton(text)
        if icon:
            b.setIcon(glyph_icon(icon, color=colour or t.TEXT))
        b.setProperty("size", "small")
        b.setCursor(Qt.PointingHandCursor)
        if danger:
            b.setStyleSheet(
                f"QPushButton {{ background: {t.WFM_RED_DIM}; color: {t.TEXT};"
                f" border: none; padding: 5px 14px; }}")
        elif colour:
            b.setStyleSheet(f"color: {colour}; background: transparent;"
                            f"border: {t.CTRL_BORDER_W}px solid {t.BORDER};"
                            f"padding: 4px 12px;")
        b.clicked.connect(on_click)
        return b

    def on_show(self) -> None:
        """Pages that read the disk re-read it here."""


# -- Display -----------------------------------------------------------------

class DisplayPage(Page):
    def __init__(self, view) -> None:
        super().__init__(view, "Window")
        lay = self.box("Current display")
        self.check(lay, "Launch fullscreen (maximized)", "fullscreen")
        self.picker(lay, "Window size", "window_size",
                    core_config.WINDOW_SIZES, self._resize)
        screens = QApplication.screens()
        self.picker(lay, "Open on monitor", "monitor",
                    [str(i + 1) for i in range(len(screens))])
        dpr = QApplication.primaryScreen().devicePixelRatio()
        self.note(lay,
                  f"{len(screens)} display(s) detected · scaling "
                  f"{dpr * 100:.0f}%, rendered at native resolution · "
                  f"monitor applies at launch, size applies immediately "
                  f"when not maximized")

        appear = self.box("Appearance")
        dev_on = bool(self.settings.get(
            "dev_panels", core_config.DEFAULTS.get("dev_panels")))
        # the Dev-* themes are a developer feature: drop back to the base default
        # if one is saved while developer features are off, then offer only the
        # themes valid for the current mode.
        self._enforce_theme_allowed(dev_on)
        self.theme_picker = self.picker(appear, "Theme", "theme",
                                        t.theme_choices(dev_on),
                                        self._apply_theme_live)
        self.note(appear, "Applies immediately.")

        sysbox = self.box("System")
        self.startup = self.check(sysbox, "Launch on Windows startup",
                                  "start_with_windows", self._startup)
        # The REGISTRY is the source of truth, not the JSON. Someone can
        # remove the Run entry from outside the app, and the box must show
        # what is actually true rather than what we last wrote.
        self.startup.blockSignals(True)
        self.startup.setChecked(core_config.start_with_windows_enabled())
        self.startup.blockSignals(False)
        self.startup_note = self.note(sysbox)

        self.watcher = self.check(sysbox,
                                  "Launch the Toolbox when Warframe starts",
                                  "launch_with_warframe", self._watcher)
        self.watcher.blockSignals(True)
        self.watcher.setChecked(core_config.watch_warframe_enabled())
        self.watcher.blockSignals(False)
        self.watcher_note = self.note(sysbox)

        self.check(sysbox, "Send to tray when minimized", "minimize_to_tray")
        self.check(sysbox, "Minimize to system tray on window close",
                   "close_to_tray")
        self.check(sysbox, "Check for updates at launch", "check_updates")
        self.check(sysbox, "Enable Developer Panels", "dev_panels",
                   self._toggle_dev_panels)
        self.body.addStretch(1)

    def _toggle_dev_panels(self, enabled: bool) -> None:
        self.view.set_devtools_visible(enabled)
        self._refresh_theme_choices(enabled)

    def _apply_theme_live(self, name: str) -> None:
        """Ask the shell to switch theme without a restart. Guarded so the
        settings screen still stands up in tests, where the view is a stub with
        no shell."""
        shell = getattr(self.view, "shell", None)
        if shell is not None and hasattr(shell, "apply_theme"):
            shell.apply_theme(name)

    def _enforce_theme_allowed(self, dev_on: bool) -> bool:
        """A dev theme is itself a developer feature: if one is selected while
        developer features are off, revert the saved theme to the base default
        so the app never launches into a theme its own picker no longer offers.
        Returns True when it changed the theme."""
        cur = str(self.settings.get("theme", core_config.DEFAULTS.get("theme")))
        if cur not in t.theme_choices(dev_on):
            self.settings["theme"] = core_config.DEFAULTS.get("theme")
            self.save()
            return True
        return False

    def _refresh_theme_choices(self, dev_on: bool) -> None:
        """Re-offer the theme options for the current developer-features state
        (the Dev-* themes appear only when it is on). Signals are blocked so the
        repopulation is not mistaken for a user theme change - that would save,
        and worse, fire while the list is half-rebuilt. If turning dev off
        dropped a live dev theme, apply the reverted base theme immediately."""
        reverted = self._enforce_theme_allowed(dev_on)
        choices = t.theme_choices(dev_on)
        cur = str(self.settings.get("theme", core_config.DEFAULTS.get("theme")))
        d = self.theme_picker
        d.blockSignals(True)
        d.clear()
        d.addItems(choices)
        d.setCurrentText(cur if cur in choices
                         else str(core_config.DEFAULTS.get("theme")))
        d.blockSignals(False)
        if reverted:
            self._apply_theme_live(cur)

    def _resize(self, value: str) -> None:
        win = self.window()
        if win and not win.isMaximized():
            w, h = value.split("x")
            win.resize(int(w), int(h))

    def _startup(self, on: bool) -> None:
        if core_config.set_start_with_windows(on):
            self.startup_note.setText("added to startup" if on
                                      else "removed from startup")
            self.say("startup entry updated")
            return
        # revert: the checkbox must never claim a registry write that failed
        self.startup.blockSignals(True)
        self.startup.setChecked(not on)
        self.startup.blockSignals(False)
        self.settings["start_with_windows"] = not on
        self.save()
        self.say("couldn't write the registry entry", "err")

    def _watcher(self, on: bool) -> None:
        if not core_config.set_watch_warframe(on):
            self.watcher.blockSignals(True)
            self.watcher.setChecked(not on)
            self.watcher.blockSignals(False)
            self.settings["launch_with_warframe"] = not on
            self.save()
            self.say("couldn't write the registry entry", "err")
            return
        if on:
            # start it NOW rather than at the next reboot, or the setting
            # appears to do nothing until you restart Windows
            core_config.spawn_watcher()
        self.watcher_note.setText("watching for Warframe" if on
                                  else "not watching")
        self.say("watcher updated")


# -- Market > Messaging ------------------------------------------------------

class MessagingPage(Page):
    FIELDS = (("msg_buy", "Buying — copied from a WTS row (you purchase)"),
              ("msg_sell", "Selling — copied from a WTB row (you supply)"))

    def __init__(self, view) -> None:
        super().__init__(view, "Messaging")
        lay = self.box("Whisper templates")
        self.blurb(lay,
                   "Placeholders: {user} the other tenno · {item} the "
                   "item · {price} the posted price. The /w prefix "
                   "makes the paste a whisper in-game.")
        self.entries = {}
        self.bound_keys.update(k for k, _c in self.FIELDS)
        for key, caption in self.FIELDS:
            lay.addWidget(label(caption, role="small"))
            e = QLineEdit(str(self.settings.get(key,
                                                core_config.DEFAULTS[key])))
            e.editingFinished.connect(lambda k=key: self._commit(k))
            lay.addWidget(e)
            self.entries[key] = e
        row = QHBoxLayout()
        row.addWidget(self.button("Reset to defaults", self._reset))
        row.addStretch(1)
        lay.addLayout(row)
        self.body.addStretch(1)

    def _commit(self, key: str) -> None:
        # blank reverts to the shipped default rather than saving an empty
        # template, which would paste a bare "/w" and look broken in-game
        text = self.entries[key].text().strip() or core_config.DEFAULTS[key]
        self.entries[key].setText(text)
        self.settings[key] = text
        self.save()
        self.say("saved")

    def _reset(self) -> None:
        for key, _cap in self.FIELDS:
            self.settings[key] = core_config.DEFAULTS[key]
            self.entries[key].setText(core_config.DEFAULTS[key])
        self.save()
        self.say("reset to defaults")


# -- Data > Warframe ---------------------------------------------------------

class WarframePage(Page):
    def __init__(self, view) -> None:
        super().__init__(view, "Warframe")
        lay = self.box("Install location")
        self.blurb(lay,
                   "Where Warframe is installed. Recorded so features "
                   "that need the game folder don't have to guess.")
        row = QHBoxLayout()
        self.entry = QLineEdit(str(wf_local.load_prefs().get("install_dir")
                                   or ""))
        self.entry.editingFinished.connect(self._commit)
        row.addWidget(self.entry, 1)
        row.addWidget(self.button("Auto-detect", self._detect))
        row.addWidget(self.button("Browse…", self._browse))
        lay.addLayout(row)
        self.check_note = self.note(lay)
        self._check()

        self._account_box()
        self.body.addStretch(1)

    # -- Warframe.com account (public profile API) ---------------------------

    def _account_box(self) -> None:
        """Your Digital Extremes account id, for the public profile endpoint
        (mastery rank, loadout, progression). No password and no game files -
        the id is public and the request is the same one the in-game 'view
        profile' makes. Empty until set, and the app falls back to AlecaFrame
        for mastery rank meanwhile."""
        box = self.box("Warframe.com account")
        self.blurb(box,
                   "Your account ID lets the Toolbox read your public "
                   "profile (mastery rank, loadout, progression) straight "
                   "from Warframe's own servers — no login, no game files, "
                   "no AlecaFrame. Connect to grab it automatically, or paste "
                   "it from warframe.com/api/user-data.")

        self.bound_keys.add("wf_account_id")
        row = QHBoxLayout()
        cap = label("Account ID", role="muted")
        cap.setMinimumWidth(LABEL_COL)
        row.addWidget(cap)
        self.account_entry = QLineEdit(
            str(self.settings.get("wf_account_id", "")))
        self.account_entry.setPlaceholderText("24-character ID")
        self.account_entry.editingFinished.connect(self._commit_account)
        row.addWidget(self.account_entry, 1)
        box.addLayout(row)

        # Platform picker is bound via the base helper (records wf_platform).
        self.picker(box, "Platform", "wf_platform",
                    list(wf_profile.PLATFORM_HOSTS.keys()))

        btns = QHBoxLayout()
        btns.addWidget(self.button("Connect Warframe.com…", self._connect_wf))
        btns.addWidget(self.button("Get ID manually", self._open_user_data))
        btns.addStretch(1)
        box.addLayout(btns)
        self.account_note = self.note(box)
        self._check_account()

    def _commit_account(self) -> None:
        """Validate + persist the pasted id. Blank clears it; a malformed id is
        refused with a message rather than saved as a doomed request."""
        raw = self.account_entry.text().strip().lower()
        if raw and not wf_profile.valid_account_id(raw):
            self._check_account()
            self.say("that is not a valid account ID "
                     "(24 hex characters)", "err")
            return
        # Manage the view's settings dict directly (like check()/picker()), so
        # the in-memory copy and disk never drift - wf_profile.set_account_id
        # would load/save its OWN copy and desync this page's view.settings.
        self.account_entry.setText(raw)
        self.settings["wf_account_id"] = raw
        self.save()
        self._check_account()
        if raw:
            self.say("account ID saved")

    def _check_account(self) -> None:
        raw = self.settings.get("wf_account_id", "")
        if not raw:
            self.account_note.setText("Not set — using AlecaFrame for "
                                      "mastery rank.")
        elif wf_profile.valid_account_id(raw):
            self.account_note.setText("Saved. Profile data will refresh from "
                                      "Warframe's servers.")
        else:
            self.account_note.setText("Stored ID looks malformed.")

    def _open_user_data(self) -> None:
        """Open the page that shows the id, for a manual copy-paste."""
        import webbrowser
        webbrowser.open("https://www.warframe.com/api/user-data")
        self.say("sign in, then copy \"user_id\" into the box above")

    def _connect_wf(self) -> None:
        """Auto-capture the account id via an embedded warframe.com login. Falls
        back to the manual route if the web engine can't be brought up."""
        try:
            from ui.wf_connect import ConnectWarframeDialog
        except Exception:                                   # noqa: BLE001
            self._open_user_data()
            return
        ConnectWarframeDialog(self, self._captured_account).exec()

    def _captured_account(self, account_id: str) -> None:
        """Called by the capture dialog with a validated id: fill the field and
        save it through the same path as a manual paste."""
        self.account_entry.setText(account_id)
        self._commit_account()

    def _commit(self) -> None:
        prefs = wf_local.load_prefs()
        # empty means "not set", stored as None rather than "" so the two
        # cannot drift apart in the file
        prefs["install_dir"] = self.entry.text().strip() or None
        wf_local.save_prefs(prefs)
        self._check(announce=True)

    def _check(self, announce: bool = False) -> None:
        """Repaint the note. `announce` controls the transient status line,
        so opening the page (which validates) does not claim you just saved
        something you did not touch."""
        raw = self.entry.text().strip()
        if not raw:
            self.check_note.setText("Not set.")
            return
        if Path(raw).is_dir():
            self.check_note.setText("Folder found — saved.")
            if announce:
                self.say("install location saved")
        else:
            self.check_note.setText("Folder does not exist.")
            if announce:
                self.say("that folder does not exist", "err")

    def _detect(self) -> None:
        found = wf_local.detect_install()
        if found is None:
            self.say("couldn't auto-detect — use Browse…", "warn")
            return
        self.entry.setText(str(found))
        self._commit()

    def _browse(self) -> None:
        chosen = QFileDialog.getExistingDirectory(
            self, "Warframe install folder", self.entry.text() or "")
        if chosen:
            self.entry.setText(chosen)
            self._commit()


# -- Data > Web apps ---------------------------------------------------------

class WebPage(Page):
    def __init__(self, view) -> None:
        super().__init__(view, "Web apps")
        lay = self.box("Ad blocking")
        self.check(lay, "Block ads and trackers in the web apps", "adblock",
                   self._set_adblock)
        self.blocked_note = self.note(lay)

        data = self.box("Browsing data")
        self.blurb(data,
                   "Cookies keep you signed in to the embedded sites; "
                   "the cache is just downloaded page resources.")
        self.size_note = self.note(data)
        row = QHBoxLayout()
        row.setSpacing(t.SP_SM)
        row.addWidget(self.button("Clear cache", self._clear_cache,
                                  t.WARN, icon="delete"))
        row.addWidget(self.button("Clear cookies", self._clear_cookies,
                                  t.WARN, icon="delete"))
        row.addStretch(1)
        row.addWidget(self.button("Clear ALL web data", self._clear_all,
                                  danger=True))
        data.addLayout(row)

        # Bookmarks are web-app data, so they live on this page - and they are
        # deliberately NOT swept by "Clear ALL web data" above, which is about
        # the browser profile. A saved page is something you made; a cookie is
        # something a site left.
        marks = self.box("Bookmarks")
        self.blurb(marks,
                   "Pages you saved with the ribbon in a web app's "
                   "toolbar. Each app keeps its own list; one app's "
                   "list can also be cleared from its Bookmarks panel.")
        self.mark_note = self.note(marks)
        mrow = QHBoxLayout()
        self.clear_marks = self.button("Delete all bookmarks",
                                       self._clear_bookmarks, t.WFM_RED,
                                       icon="delete")
        mrow.addWidget(self.clear_marks)
        mrow.addStretch(1)
        marks.addLayout(mrow)
        self.body.addStretch(1)
        self.on_show()

    def _set_adblock(self, enabled: bool) -> None:
        from ui import web as ui_web
        ui_web.set_adblock(enabled)      # live, not just at next launch
        self.say("ad blocking on" if enabled else "ad blocking off")

    def on_show(self) -> None:
        from ui import web as ui_web
        inter = ui_web.interceptor()
        self.blocked_note.setText(
            f"{inter.blocked} requests blocked this session"
            if inter else "nothing blocked yet this session")
        n_files, total = self._profile_size()
        self.size_note.setText(
            f"profile: {core_config.human_size(total)} across {n_files} files"
            if n_files else "no browsing data stored yet")
        self._paint_marks()

    def _profile_size(self) -> tuple[int, int]:
        from ui import web as ui_web
        root = ui_web.PROFILE_DIR
        if not root.exists():
            return 0, 0
        # the running engine constantly creates and deletes cache files here,
        # so a file can vanish between the listing and the stat - tolerate it
        n = total = 0
        for f in root.rglob("*"):
            try:
                if f.is_file():
                    total += f.stat().st_size
                    n += 1
            except OSError:
                continue
        return n, total

    def _paint_marks(self) -> None:
        data = core_bookmarks.load()
        n = core_bookmarks.count(data)
        per = ", ".join(f"{k.replace('web_', '')}: {len(v)}"
                        for k, v in sorted(data.items()) if v)
        self.mark_note.setText(f"{n} saved ({per})" if n else "none saved")
        self.clear_marks.setEnabled(bool(n))

    def _clear_cache(self) -> None:
        if QMessageBox.question(
                self, "Clear cache?",
                "Clear the web apps' cached page resources?\n"
                "You stay signed in everywhere.",
                QMessageBox.Yes | QMessageBox.No) != QMessageBox.Yes:
            return
        from ui import web as ui_web
        ui_web.clear_cache()
        self.say("cache cleared")
        QTimer.singleShot(1500, self.on_show)   # the clear is asynchronous

    def _clear_cookies(self) -> None:
        if QMessageBox.question(
                self, "Clear cookies?",
                "Clear all cookies?\n"
                "This signs you out of every site in the web apps.",
                QMessageBox.Yes | QMessageBox.No) != QMessageBox.Yes:
            return
        from ui import web as ui_web
        ui_web.clear_cookies()
        self.say("cookies cleared")
        QTimer.singleShot(1500, self.on_show)

    def _clear_all(self) -> None:
        if not GoodbyeDialog.confirmed(
                self, "Clear ALL web data",
                "Every cookie, cached file and site setting in the embedded "
                "web apps will be deleted, and you will be signed out of all "
                "of them.\n\nYour bookmarks, your warframe.market account and "
                "the Toolbox itself are not affected."):
            return
        from ui import web as ui_web
        ui_web.clear_all_data()
        self.say("all web data cleared")
        QTimer.singleShot(1500, self.on_show)

    def _clear_bookmarks(self) -> None:
        data = core_bookmarks.load()
        n = core_bookmarks.count(data)
        if not n:
            return
        if not GoodbyeDialog.confirmed(
                self, "Delete all bookmarks",
                f"All {n} saved {'page' if n == 1 else 'pages'} will be "
                f"removed, across every web app.\n\nCookies, cache and your "
                f"sign-ins are not affected - only the saved links."):
            return
        core_bookmarks.save(core_bookmarks.clear_all())
        self._paint_marks()
        self.say(f"{n} bookmark(s) deleted")
        self.view.bookmarks_changed()


# -- Data > Market -----------------------------------------------------------

class MarketPage(Page):
    def __init__(self, view) -> None:
        super().__init__(view, "Market")
        acct = self.box("warframe.market profile")
        self.grid = QGridLayout()
        # LABEL_COL to match the picker captions on the other pages, and a
        # trailing stretch column so leftover width falls to the RIGHT instead
        # of being wedged between each label and its value (which floated the
        # values out to mid-card).
        self.grid.setColumnMinimumWidth(0, LABEL_COL)
        self.grid.setColumnStretch(2, 1)
        self.grid.setHorizontalSpacing(t.SP_MD)
        acct.addLayout(self.grid)
        self.rows = {}
        for i, cap in enumerate(("Account", "Session", "Active orders")):
            c = label(cap, role="muted")
            self.grid.addWidget(c, i, 0)
            v = label("—", role="small")
            self.grid.addWidget(v, i, 1)
            self.rows[cap] = v
        rail = QHBoxLayout()
        rail.addWidget(self.button("Refresh counts", self._counts,
                                   icon="refresh"))
        rail.addStretch(1)
        self.unlink = self.button("Unlink account", self._unlink,
                                  danger=True)
        rail.addWidget(self.unlink)
        acct.addLayout(rail)

        api = self.box("API status")
        self.blurb(api,
                   "Runs the API check tool: confirms every "
                   "warframe.market endpoint this app depends on still "
                   "answers in the shape it expects. Run it before "
                   "trusting a reprice after a WFM update.")
        arow = QHBoxLayout()
        self.run_btn = self.button("Run check", self._run_api)
        arow.addWidget(self.run_btn)
        self.api_state = label("", role="small")
        arow.addWidget(self.api_state)
        arow.addStretch(1)
        api.addLayout(arow)
        self.console = QPlainTextEdit()
        self.console.setReadOnly(True)
        self.console.setMinimumHeight(150)
        self.console.setPlaceholderText("Run the check to see output.")
        self.console.setProperty("surface", "console")
        api.addWidget(self.console)
        self._proc = None
        self._jobs = []
        self.body.addStretch(1)
        self.on_show()

    def on_show(self) -> None:
        s = self.view.session
        self.rows["Account"].setText(
            f"{s.username} ({s.platform})" if s else "not signed in")
        self.rows["Session"].setText("valid" if s else "none")
        self.unlink.setEnabled(s is not None)
        self.rows["Active orders"].setText("—")

    def _counts(self) -> None:
        client = self.view.market
        if client is None:
            self.say("no account linked", "warn")
            return
        self.rows["Active orders"].setText("loading…")
        self._jobs.append(work.run(
            client.my_listings,
            lambda b: self.rows["Active orders"].setText(
                f"{len(b['sell'])} WTS · {len(b['buy'])} WTB"),
            lambda msg: self.rows["Active orders"].setText(msg)))

    def _unlink(self) -> None:
        if not GoodbyeDialog.confirmed(
                self, "Unlink account",
                "The saved warframe.market session token will be deleted and "
                "you will be signed out.\n\nYour orders on warframe.market "
                "are not touched - you can sign in again at any time."):
            return
        self.view.unlink_account()
        self.on_show()
        self.say("account unlinked")

    def _run_api(self) -> None:
        """QProcess, not a thread with a queue and a polling drain. The Tk
        version needed ToolRunner plus an `after(80)` loop to pump stdout;
        readyReadStandardOutput does the same thing with no thread at all."""
        tool = next((x for x in TOOLS if x.id == "api_check"), None)
        if tool is None or not tool.exists:
            self.say("the API check tool is not installed", "err")
            return
        import os as _os
        import sys as _sys
        from PySide6.QtCore import QProcessEnvironment
        self.console.clear()
        self.run_btn.setEnabled(False)
        self.api_state.setText("running…")
        self._proc = QProcess(self)
        self._proc.setProcessChannelMode(QProcess.MergedChannels)
        self._proc.readyReadStandardOutput.connect(self._api_out)
        self._proc.finished.connect(self._api_done)
        self._proc.setWorkingDirectory(str(tool.workdir))
        # Tools reach warframe.market ONLY through the host's gateway, and
        # find it through these variables. Launched without them the tool
        # exits with "must run through the helper" - which is the tool
        # working correctly and the caller not.
        env = QProcessEnvironment()
        for k, v in self.view.gateway_env(dict(_os.environ)).items():
            env.insert(k, str(v))
        self._proc.setProcessEnvironment(env)
        self._proc.start(_sys.executable, ["-u", str(tool.script)])

    def _api_out(self) -> None:
        """Insert at the cursor rather than appendPlainText.

        `appendPlainText` starts a NEW paragraph on every call, so a tool
        whose lines already end in a newline comes out double-spaced - the
        chunk's own break plus the one the append adds. Inserting reproduces
        the tool's output exactly, which is the whole point of a console.
        """
        chunk = bytes(self._proc.readAllStandardOutput()).decode(
            "utf-8", "replace")
        cursor = self.console.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        cursor.insertText(chunk)
        self.console.setTextCursor(cursor)

    def _api_done(self, code: int, _status) -> None:
        self.run_btn.setEnabled(True)
        ok = code == 0
        self.api_state.setText("all checks passed" if ok
                               else f"FAILED (exit {code})")
        self.api_state.setStyleSheet(f"color: {t.OK if ok else t.ERR};")


# -- Data > WF Toolbox -------------------------------------------------------

class ToolboxPage(Page):
    def __init__(self, view) -> None:
        super().__init__(view, "WF Toolbox")
        self.files_box = self.box("Your data")
        self.blurb(self.files_box,
                   "Everything this app has written. Click a name to "
                   "open it; the ✕ deletes just that file.")
        self.file_host = QVBoxLayout()
        self.file_host.setSpacing(t.SP_XXS)
        self.files_box.addLayout(self.file_host)

        cache = self.box("Cached images")
        self.cache_note = self.note(cache)
        crow = QHBoxLayout()
        crow.addWidget(self.button("Delete cached images", self._del_images,
                                   t.WARN, icon="delete"))
        crow.addStretch(1)
        cache.addLayout(crow)

        wfd = self.box("Collected game data")
        self.blurb(wfd,
                   "Your profile, world state and item data pulled from "
                   "Warframe's own servers, cached so the app is instant and "
                   "works offline. Deleting it just makes the app re-fetch on "
                   "the next refresh; nothing is lost.")
        self.wf_data_note = self.note(wfd)
        wrow = QHBoxLayout()
        wrow.addWidget(self.button("Delete collected data", self._del_wf_data,
                                   t.WARN, icon="delete"))
        wrow.addStretch(1)
        wfd.addLayout(wrow)

        nuke = self.box("Everything")
        self.blurb(nuke,
                   "Deletes every file above, the image cache, the collected "
                   "game data and the web-app profile, and turns off both "
                   "startup entries.")
        nrow = QHBoxLayout()
        nrow.addStretch(1)
        nrow.addWidget(self.button("Delete ALL user data", self._del_all,
                                   danger=True))
        nuke.addLayout(nrow)
        self.body.addStretch(1)
        self.on_show()

    def on_show(self) -> None:
        while self.file_host.count():
            item = self.file_host.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        files = core_config.user_data_files()
        if not files:
            self.file_host.addWidget(label("Nothing written yet.",
                                           role="small"))
        for name, path, desc, size in files:
            self.file_host.addWidget(self._row(name, path, desc, size))
        n, total = core_config.thumb_cache_size()
        self.cache_note.setText(
            f"{n} image(s), {core_config.human_size(total)}" if n else "no cached images")
        wn, wtotal = core_config.wf_data_size()
        self.wf_data_note.setText(
            f"{wn} file(s), {core_config.human_size(wtotal)}"
            if wn else "nothing collected yet")

    def _row(self, name: str, path: Path, desc: str, size: int) -> QWidget:
        row = panel()
        row.setStyleSheet(f"background: {t.WFM_CARD};")
        h = QHBoxLayout(row)
        h.setContentsMargins(t.SP_LG, t.SP_SM, t.SP_MD, t.SP_SM)
        h.setSpacing(t.SP_SM)
        open_btn = QPushButton(name)
        open_btn.setProperty("kind", "flat")
        # a floor width so the description column starts at one x on every row,
        # instead of sliding with each filename's length
        open_btn.setMinimumWidth(210)
        open_btn.setCursor(Qt.PointingHandCursor)
        open_btn.setToolTip(f"{desc}\n{path}")
        open_btn.setStyleSheet(f"color: {t.WFM_TEAL}; text-align: left;"
                               f"background: transparent; padding: 3px 2px;")
        open_btn.clicked.connect(lambda _c=False, p=path: self._open(p))
        h.addWidget(open_btn)
        h.addWidget(label(desc, role="small"), 1)
        h.addWidget(label(core_config.human_size(size), role="small"))
        rm = QPushButton(glyph_icon("close", color=t.WFM_RED), "")
        rm.setFixedSize(*t.REMOVE_BTN)
        rm.setCursor(Qt.PointingHandCursor)
        rm.setToolTip(f"delete {name}")
        rm.setStyleSheet(f"QPushButton {{ background: transparent;"
                         f" border: {t.CTRL_BORDER_W}px solid {t.BORDER}; }}"
                         f"QPushButton:hover {{ border-color: {t.WFM_RED}; }}")
        rm.clicked.connect(lambda _c=False, n=name, p=path: self._del_one(n, p))
        h.addWidget(rm)
        return row

    def _open(self, path: Path) -> None:
        err = core_config.open_in_default_app(path)
        if err:
            self.say(f"couldn't open: {err}", "err")

    def _del_one(self, name: str, path: Path) -> None:
        if QMessageBox.question(
                self, "Delete file", f"Delete {name}?",
                QMessageBox.Yes | QMessageBox.No) != QMessageBox.Yes:
            return
        # deleting the session file behind the app's back would leave a live
        # client pointing at a token that no longer exists
        if name == "wfm_session.json" and self.view.session is not None:
            self.view.unlink_account()
        elif not core_config.delete_user_file(path):
            self.say(f"{name} could not be deleted", "err")
            return
        self.on_show()
        self.say(f"{name} deleted")

    def _del_images(self) -> None:
        if not GoodbyeDialog.confirmed(
                self, "Delete cached images",
                "Every item thumbnail the app has downloaded will be "
                "removed.\n\nThey re-download as needed; nothing is lost "
                "permanently."):
            return
        n = core_config.clear_thumb_cache()
        self.on_show()
        self.say(f"{n} cached image(s) deleted")

    def _del_wf_data(self) -> None:
        if not GoodbyeDialog.confirmed(
                self, "Delete collected game data",
                "Your cached profile, world state and item data will be "
                "removed.\n\nIt re-fetches from Warframe's servers on the next "
                "refresh; nothing is lost permanently."):
            return
        n = core_config.clear_wf_data()
        self.on_show()
        self.say(f"{n} collected file(s) deleted")

    def _del_all(self) -> None:
        if not GoodbyeDialog.confirmed(
                self, "Delete ALL user data",
                "Every file listed above, the image cache, the web-app "
                "browser profile and your bookmarks will be deleted, and both "
                "startup entries will be turned off.\n\nThe Toolbox itself "
                "and its program assets are not affected."):
            return
        self.view.wipe_everything()
        self.on_show()
        self.say("all user data deleted")


#: The version string lives in core.version; this is just the local alias.
_APP_VERSION = core_version.__version__

#: Developer identity. Name and the GitHub link share ONE line, spaced apart.
_DEV_NAME = "Mortefix"
_DEV_GITHUB = "https://github.com/mortefix/Warframe-Toolbox"

#: A readable digest of every bundled licence. The CANONICAL, per-file registry
#: is app/assets/licenses/README.md (with the full OFL/Apache text beside it) -
#: keep this in step with that file when a bundled asset changes.
_LICENSING = (
    "Warframe Toolbox — © the Warframe Toolbox authors. An independent, "
    "non-commercial fan project; Warframe is © Digital Extremes Ltd.\n\n"
    "Licensed under the GNU General Public License v3, with a special "
    "exception permitting linking against — and distribution through — the "
    "proprietary Overwolf platform, SDK, and APIs. The full licence and the "
    "exception text ship in LICENSE at the project root.\n\n"
    "Built with PySide6 (Qt for Python) — LGPL v3.\n\n"
    "Icons — Material Symbols\n"
    "  Apache License 2.0 · © Google LLC\n\n"
    "Bundled UI fonts\n"
    "  Be Vietnam Pro — OFL 1.1 · © 2021 The Be Vietnam Pro Project Authors\n"
    "  Marcellus — OFL 1.1 · © 2012 Astigmatic (AOETI)\n"
    "  Cormorant Garamond — OFL 1.1 · © 2015 The Cormorant Project Authors\n"
    "  Cinzel Decorative — OFL 1.1 · © 2012 Natanael Gama\n"
    "  Spectral — OFL 1.1 · © 2017 The Spectral Project Authors\n"
    "  Orbitron — OFL 1.1 · © 2018 The Orbitron Project Authors\n"
    "  Rajdhani — OFL 1.1 · © 2014 Indian Type Foundry\n"
    "  Chakra Petch — OFL 1.1 · © 2018 The Chakra Petch Project Authors\n"
    "  Exo 2 — OFL 1.1 · © 2013 The Exo 2 Project Authors\n"
    "  VT323 — OFL 1.1 · © 2011 The VT323 Project Authors\n"
    "  Mountains of Christmas — Apache 2.0 · © 2010–2011 Font Diner, Inc.\n\n"
    "App icon, crest, and platinum gem\n"
    "  Warframe © Digital Extremes. Fan-project use; not redistributed as a "
    "Digital Extremes work.\n\n"
    "Full licence text ships in app/assets/licenses/ (OFL.txt, Apache-2.0.txt) "
    "with a per-file registry in README.md.")


class AboutPage(QWidget):
    """About: developer info, changelog, and licensing.

    Unlike every other settings page it does NOT sit in one page-wide scroll
    area. The page is self-contained - Developer Info holds its natural height
    at the top, and only the Changelog and Licensing cards scroll internally
    (they share the leftover height, licensing taking the larger share). That
    keeps a long licence list from pushing the whole page into a scroll.
    """

    def __init__(self, view) -> None:
        super().__init__()
        self.view = view
        self.setAttribute(Qt.WA_StyledBackground, True)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(t.SP_SCREEN, t.SP_LG, t.SP_SCREEN, t.SP_LG)
        outer.setSpacing(t.SP_LG)
        outer.addWidget(label("About", role="h1"))

        # All three sections share ONE structure - a card with its h2 title
        # INSIDE it, the same shape every other settings page uses (`box()`) -
        # so the in-app headers read identically and never diverge.

        # -- Developer Info: natural height, one compact identity line --
        dev = self._section("Developer Info")
        row = QHBoxLayout()
        row.setSpacing(t.SP_SM)
        row.addWidget(label("Developer:", role="muted"))
        row.addWidget(label(_DEV_NAME, role=""))
        row.addSpacing(t.SP_XL)      # gap before the GitHub pair
        row.addWidget(label("GitHub:", role="muted"))
        # a real clickable link (opens the system browser, not the web tab),
        # coloured with the accent token and still selectable to copy
        link = label(f'<a href="{_DEV_GITHUB}" style="color: {t.ACCENT};">'
                     f'{_DEV_GITHUB}</a>', role="")
        link.setOpenExternalLinks(True)
        link.setTextInteractionFlags(Qt.LinksAccessibleByMouse
                                     | Qt.TextSelectableByMouse)
        row.addWidget(link)
        row.addSpacing(t.SP_XL)      # gap before the version
        row.addWidget(label("App Version:", role="muted"))
        # a freshly self-updated copy shows what is waiting for the restart
        pending = core_updater.pending_version()
        row.addWidget(label(_APP_VERSION + (f"  ({pending} installed — "
                                            f"restart to apply)"
                                            if pending else ""), role=""))
        row.addStretch(1)
        dev.addLayout(row)

        # -- Changelog and Licensing: each scrolls INSIDE its own card, so the
        #    page never scrolls. Equal stretch => equal container height. --
        self._scroll_section("Changelog", core_version.changelog_text(), 1)
        self._scroll_section("Licensing", _LICENSING, 1)

    def _section(self, title: str) -> QVBoxLayout:
        """A titled card added to the page; returns its layout to fill. Same
        shape as the settings `box()` helper: h2 title inside a `panel("card")`."""
        card = panel("card")
        lay = QVBoxLayout(card)
        lay.setContentsMargins(t.SP_XL, t.SP_LG, t.SP_XL, t.SP_LG)
        lay.setSpacing(t.SP_MD)
        lay.addWidget(label(title, role="h2"))
        self.layout().addWidget(card)
        return lay

    def _scroll_section(self, title: str, text: str, stretch: int) -> None:
        """A titled card whose body text scrolls INSIDE it. The title + border
        stay put; only the plain inner panel scrolls (the Vosfor collections
        idiom), so the page itself never scrolls."""
        lay = self._section(title)
        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setFrameShape(QFrame.NoFrame)
        area.setMinimumHeight(90)     # always show several lines, even when short
        area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        inner = panel()
        il = QVBoxLayout(inner)
        il.setContentsMargins(0, 0, 0, 0)
        il.setSpacing(0)
        body = label(text, role="small")
        body.setWordWrap(True)
        body.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        body.setTextInteractionFlags(Qt.TextSelectableByMouse)
        il.addWidget(body)
        il.addStretch(1)
        area.setWidget(inner)
        lay.addWidget(area)
        # the card is the last widget added by _section; give it the stretch so
        # Changelog and Licensing split the leftover height evenly
        self.layout().setStretchFactor(self.layout().itemAt(
            self.layout().count() - 1).widget(), stretch)


def _dev_pages() -> dict:
    """The DevTools pages, imported lazily so a settings import doesn't drag in
    the whole data stack (and the QtWebEngine-free dev views stay optional)."""
    from ui.dev_eelog import EELogDevView
    from ui.dev_inventory import InventoryDevView
    from ui.dev_profile import ProfileDevView
    from ui.dev_worldstate import WorldStateDevView
    from ui.mods import ModsView

    class ModsDevView(ModsView):
        """The R&D mods-database explorer, retired from the sidebar when the
        player-facing Mods app shipped; lives on here as a dev panel."""

        def __init__(self, view) -> None:
            # getattr: test shells are minimal fakes without the link hooks
            super().__init__(
                getattr(view.shell, "open_wiki", None) or (lambda name: None),
                getattr(view.shell, "open_overframe", None))

    return {"dev_worldstate": WorldStateDevView, "dev_profile": ProfileDevView,
            "dev_eelog": EELogDevView, "dev_inventory": InventoryDevView,
            "dev_mods": ModsDevView}


PAGES = {"window": DisplayPage, "warframe": WarframePage,
         "market": MarketPage, "web": WebPage, "toolbox": ToolboxPage,
         "messaging": MessagingPage, **_dev_pages(), "about": AboutPage}


class SettingsView(QWidget):
    """The tree, the pages, and the hooks back into the shell."""

    bookmarks_cleared = Signal()

    def __init__(self, shell) -> None:
        super().__init__()
        self.shell = shell
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.settings = shell.settings
        self._open_section = ""
        self.current = ""

        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        nav = panel("sidebar")
        nav.setFixedWidth(NAV_WIDTH)
        self.nav = QVBoxLayout(nav)
        # top gap matches the other columns; the bottom inset matches the main
        # navbar so the pinned About link aligns with the pinned Settings row
        self.nav.setContentsMargins(0, t.SP_LG, 0, _NAV_BOTTOM)
        self.nav.setSpacing(0)
        title = label("SETTINGS", role="caps")
        title.setContentsMargins(t.SP_LG, 0, 0, t.SP_SM)
        self.nav.addWidget(title)

        search_row = QWidget()
        sr = QHBoxLayout(search_row)
        sr.setContentsMargins(t.SP_SM, 0, t.SP_SM, t.SP_SM)
        sr.setSpacing(t.SP_SM)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search settings")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._search)
        sr.addWidget(self.search)
        self.nav.addWidget(search_row)
        self.hits = label("", role="small")
        self.hits.setContentsMargins(t.SP_LG, 0, t.SP_SM, t.SP_SM)
        self.nav.addWidget(self.hits)
        self._highlighted = None

        self.headers, self.leaves, self.leaf_hosts = {}, {}, {}
        self.section_rows: dict[str, QWidget] = {}
        self._hidden_sections: set[str] = set()
        for section, pages in TREE:
            hdr = self._header(section)
            self.section_rows[section] = hdr
            self.nav.addWidget(hdr)
            host = QWidget()
            hv = QVBoxLayout(host)
            hv.setContentsMargins(0, 0, 0, 0)
            hv.setSpacing(0)
            for key, text in pages:
                b = self._leaf(key, text)
                self.leaves[key] = b
                hv.addWidget(b)
            host.hide()
            self.leaf_hosts[section] = host
            self.nav.addWidget(host)
        # About is a TOP-LEVEL page with no section/dropdown, pinned to the
        # bottom of the explorer the way the navbar pins Settings: the stretch
        # pushes everything above it up, and this link sits under it.
        self.nav.addStretch(1)
        self.nav.addWidget(self._about_link())
        lay.addWidget(nav)
        lay.addWidget(self._vline())

        self.stack = QStackedWidget()
        self.stack.setProperty("surface", "app")
        self._built = {}
        # Where the user was before a search jumped them away (page key, scroll),
        # captured on the first keystroke so clearing the box can undo the jump.
        self._pre_search = None
        lay.addWidget(self.stack, 1)

        # opens on the first section's first page, with only that section
        # expanded - the same landing the Tk version had
        self._header_click(TREE[0][0])
        # DevTools is gated behind the "Enable Developer Panels" setting
        self._apply_devtools_visibility(self.settings.get("dev_panels", False))

    def _apply_devtools_visibility(self, visible: bool) -> None:
        """Show or hide the whole DevTools section (its header + pages). When
        hiding while a DevTools page is open, fall back to the first page so the
        content area never shows a page whose tree entry has vanished."""
        section = "DevTools"
        if section not in self.section_rows:
            return
        if visible:
            self._hidden_sections.discard(section)
        else:
            self._hidden_sections.add(section)
        self.section_rows[section].setVisible(visible)
        if not visible:
            self.leaf_hosts[section].setVisible(False)
            dev_keys = {k for k, _t in dict(TREE)[section]}
            if self.current in dev_keys:
                self.select(TREE[0][1][0][0])

    def set_devtools_visible(self, visible: bool) -> None:
        """Called by the Display page's toggle. Persistence is the toggle's job;
        this just reflects the change in the tree immediately."""
        self._apply_devtools_visibility(visible)

    def _vline(self) -> QFrame:
        f = QFrame()
        f.setProperty("surface", "vline")
        f.setFixedWidth(t.BORDER_W)
        return f

    def _header(self, section: str) -> QWidget:
        row = QWidget()
        row.setAttribute(Qt.WA_StyledBackground, True)
        h = QHBoxLayout(row)
        h.setContentsMargins(t.SP_SM, 0, 0, 0)
        h.setSpacing(0)
        arrow = label(t.glyph("collapse"), role="icon")
        arrow.setFixedWidth(t.DISCLOSURE_W)
        arrow.setCursor(Qt.PointingHandCursor)
        arrow.mouseReleaseEvent = lambda _e, s=section: self._toggle(s)
        h.addWidget(arrow)
        btn = QPushButton(section)
        btn.setProperty("nav", "item")
        btn.setCursor(Qt.PointingHandCursor)
        btn.clicked.connect(lambda _c=False, s=section: self._header_click(s))
        h.addWidget(btn, 1)
        self.headers[section] = (arrow, btn)
        return row

    def _leaf(self, key: str, text: str) -> QPushButton:
        b = QPushButton(text)
        b.setProperty("nav", "leaf")
        b.setCursor(Qt.PointingHandCursor)
        b.setStyleSheet(f"text-align: left; padding: 5px 8px 5px 34px;"
                        f"border: none; background: transparent;"
                        f"color: {t.MUTED};")
        b.clicked.connect(lambda _c=False, k=key: self.select(k))
        return b

    def _about_link(self) -> QPushButton:
        """The bottom-pinned About entry: a lone FULL-WIDTH link, no arrow, no
        leaves. It has no dropdown, so its highlight spans the whole row rather
        than leaving an arrow column uncovered; its text is indented to line up
        with the section names above it."""
        btn = QPushButton("About")
        btn.setProperty("nav", "item")
        btn.setCursor(Qt.PointingHandCursor)
        btn.setStyleSheet(self._about_style(False))
        btn.clicked.connect(lambda: self.select("about"))
        self.about_btn = btn
        return btn

    def _about_style(self, active: bool) -> str:
        """Full-row style for the About link. The left inset matches where a
        section header puts its text - past the SP_SM row margin, the arrow
        (DISCLOSURE_W) and the nav button's own SP_SM pad - so the two align,
        while the background fills the entire row."""
        indent = t.SP_SM + t.DISCLOSURE_W + t.SP_SM
        return (f"text-align: left; border: none;"
                f" padding: 11px 8px 11px {indent}px;"
                f" background: {t.SIDEBAR_ACTIVE if active else 'transparent'};"
                f" color: {t.TEXT if active else t.MUTED};")

    # -- tree ----------------------------------------------------------------

    def _toggle(self, section: str) -> None:
        """The ARROW only opens and closes. It does not change the page -
        looking at what a section contains is not the same as choosing one."""
        self._set_open("" if self._open_section == section else section)

    def _header_click(self, section: str) -> None:
        """The header TEXT expands and opens the section's first page, which
        is what someone clicking a category name is asking for."""
        self._set_open(section)
        pages = dict(TREE)[section]
        if pages:
            self.select(pages[0][0])

    def _set_open(self, section: str) -> None:
        self._open_section = section
        for name, host in self.leaf_hosts.items():
            # a hidden section (DevTools when disabled) never shows its pages,
            # even if something selects one of them directly
            host.setVisible(name == section and name not in self._hidden_sections)
            arrow, _btn = self.headers[name]
            arrow.setText(t.glyph("expand" if name == section else "collapse"))

    # -- search --------------------------------------------------------

    def _index(self) -> list[tuple[str, QWidget, str]]:
        """(page key, widget, searchable text) for every control.

        Built by walking the REAL widgets rather than from a hand-written
        list of terms, so a control added to a page is searchable without
        anyone remembering to index it. Building every page to do that costs
        one pass and only happens the first time someone types.
        """
        for key in PAGES:
            if key not in self._built:
                self._built[key] = self.stack.addWidget(PAGES[key](self))
        out = []
        for key, index in self._built.items():
            page = self.stack.widget(index)
            for w in page.findChildren(QWidget):
                text = ""
                if isinstance(w, (QCheckBox, QPushButton)):
                    text = w.text()
                elif w.metaObject().className() == "QLabel":
                    text = w.text()
                if text and len(text) < 90:
                    out.append((key, w, text))
        return out

    def _clear_highlight(self) -> None:
        if self._highlighted is not None:
            self._highlighted.setStyleSheet(self._highlight_was)
            self._highlighted = None

    def _search(self, query: str) -> None:
        """Jump to the first match on every keystroke.

        Deliberately a JUMP rather than a filter of the tree: settings are
        already few enough to see, and hiding the ones that do not match
        makes it impossible to tell "no such setting" from "you typed it
        differently". Landing on the closest thing and saying how many others
        matched answers both.
        """
        self._clear_highlight()
        q = query.strip().lower()
        if not q:
            self.hits.setText("")
            # clearing the box undoes the jump - go back to where the search
            # started, like My Listings' search does, instead of stranding the
            # user mid-page wherever the last match happened to land
            if self._pre_search is not None:
                key, offset = self._pre_search
                self._pre_search = None
                self.select(key)
                self._set_scroll(offset)
            return
        # remember the starting position on the FIRST keystroke of a search
        if self._pre_search is None:
            self._pre_search = (self.current, self._scroll_value())
        matches = [(k, w, txt) for k, w, txt in self._index()
                   if q in txt.lower()]
        if not matches:
            self.hits.setText("no match")
            self.hits.setStyleSheet(f"color: {t.WARN};")
            return
        # prefer a match that STARTS with what was typed - "web" should find
        # "Web apps" before "the web apps' cached page resources"
        starts = [m for m in matches if m[2].lower().startswith(q)]
        key, widget, _txt = (starts or matches)[0]
        self.hits.setText(f"{len(matches)} match"
                          f"{'' if len(matches) == 1 else 'es'}")
        self.hits.setStyleSheet(f"color: {t.MUTED};")
        self.select(key)
        self._reveal(widget)

    def _scroll_value(self) -> int:
        area = self.stack.currentWidget().findChild(QScrollArea)
        return area.verticalScrollBar().value() if area is not None else 0

    def _set_scroll(self, value: int) -> None:
        area = self.stack.currentWidget().findChild(QScrollArea)
        if area is not None:
            area.verticalScrollBar().setValue(value)

    def _reveal(self, widget: QWidget) -> None:
        page = self.stack.currentWidget()
        area = page.findChild(QScrollArea)
        if area is not None:
            area.ensureWidgetVisible(widget, 40, 60)
        self._highlight_was = widget.styleSheet()
        widget.setStyleSheet(self._highlight_was +
                             f";color: {t.ACCENT};")
        self._highlighted = widget

    def select(self, key: str) -> None:
        if key not in PAGES:
            return
        # A search highlight belongs to the page it was found on; navigating
        # away (tree click or another search) must not leave it tinted gold.
        self._clear_highlight()
        if key not in self._built:
            page = PAGES[key](self)
            self._built[key] = self.stack.addWidget(page)
        self.stack.setCurrentIndex(self._built[key])
        self.current = key
        # a page selected from elsewhere must reveal itself in the tree
        for section, pages in TREE:
            if key in [k for k, _t in pages]:
                self._set_open(section)
        for k, b in self.leaves.items():
            active = k == key
            b.setStyleSheet(
                f"text-align: left; padding: 5px 8px 5px 34px; border: none;"
                f"background: {t.SIDEBAR_ACTIVE if active else 'transparent'};"
                f"color: {t.TEXT if active else t.MUTED};")
        # the bottom-pinned About link is not a leaf, so it carries its own
        # full-row active tint
        self.about_btn.setStyleSheet(self._about_style(key == "about"))
        page = self.stack.currentWidget()
        if hasattr(page, "on_show"):
            page.on_show()

    # -- shell hooks ---------------------------------------------------------

    @property
    def session(self):
        return self.shell.session

    @property
    def market(self):
        return self.shell.market

    def gateway_env(self, base: dict) -> dict:
        return self.shell.gateway.child_env(base)

    def unlink_account(self) -> None:
        self.shell.unlink_account()

    def bookmarks_changed(self) -> None:
        self.bookmarks_cleared.emit()
        self.shell.bookmarks_changed()

    def wipe_everything(self) -> None:
        self.shell.wipe_user_data()
