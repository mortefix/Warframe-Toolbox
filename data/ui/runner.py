"""Run a registry tool and stream its output.

The Tk version needed `ToolRunner` - a thread pumping stdout into a
`queue.Queue`, drained by a self-rescheduling `after(80)` loop, with a `None`
sentinel to signal the end. QProcess replaces all of it: `readyReadStandard-
Output` fires on the GUI thread when there is something to read, and
`finished` fires when there is not. No thread, no queue, no polling, no
sentinel, and no window in which a late drain can touch a destroyed widget.

Tools reach warframe.market ONLY through the host's gateway, and find it
through the environment this builds. A tool started without those variables
exits immediately by design - which is correct, and was how the API check
first appeared "broken" when Settings launched it bare.
"""

from __future__ import annotations

import os
import sys

from PySide6.QtCore import QProcess, QProcessEnvironment, Qt
from PySide6.QtWidgets import (QCheckBox, QHBoxLayout, QLineEdit,
                               QPlainTextEdit, QPushButton, QVBoxLayout,
                               QWidget)

from core import theme as t
from ui.widgets import glyph_icon, hairline, label, panel


class RunnerView(QWidget):
    """One tool: its flags, its arguments, a Run button and a console."""

    def __init__(self, shell, tool) -> None:
        super().__init__()
        self.shell = shell
        self.tool = tool
        self.setAttribute(Qt.WA_StyledBackground, True)
        self._proc: QProcess | None = None

        lay = QVBoxLayout(self)
        lay.setContentsMargins(*t.PAGE_HEADER_MARGINS)
        lay.setSpacing(t.SP_MD)

        head = QHBoxLayout()
        head.setSpacing(t.SP_SM)
        mark = label(t.glyph(tool.icon), role="icon")
        mark.setStyleSheet(f"color: {tool.accent};")
        head.addWidget(mark)
        head.addWidget(label(tool.name, role="h1"))
        head.addStretch(1)
        if tool.requires_session:
            linked = shell.session is not None
            who = label(f"as {shell.session.username}" if linked
                        else "no account linked", role="small",
                        level="ok" if linked else "err")
            head.addWidget(who)
        lay.addLayout(head)

        blurb = label(tool.description, role="muted")
        blurb.setWordWrap(True)
        lay.addWidget(blurb)
        lay.addWidget(hairline())

        self.flags: dict[str, QCheckBox] = {}
        self.args: dict[str, QLineEdit] = {}
        if tool.flags or tool.args:
            box = panel("card")
            bl = QVBoxLayout(box)
            bl.setContentsMargins(t.SP_XL, t.SP_LG, t.SP_XL, t.SP_LG)
            bl.setSpacing(t.SP_SM)
            for flag in tool.flags:
                cb = QCheckBox(flag.label)
                cb.setChecked(flag.default)
                if flag.help:
                    cb.setToolTip(flag.help)
                bl.addWidget(cb)
                self.flags[flag.flag] = cb
            for arg in tool.args:
                row = QHBoxLayout()
                cap = label(arg.label, role="muted")
                cap.setMinimumWidth(150)
                row.addWidget(cap)
                field = QLineEdit()
                field.setPlaceholderText(arg.placeholder)
                row.addWidget(field, 1)
                bl.addLayout(row)
                self.args[arg.key] = field
            lay.addWidget(box)

        rail = QHBoxLayout()
        self.run_btn = QPushButton(" Run")
        self.run_btn.setIcon(glyph_icon("reprice", color=t.INK))
        self.run_btn.setProperty("kind", "money")
        self.run_btn.setCursor(Qt.PointingHandCursor)
        self.run_btn.clicked.connect(self.run)
        rail.addWidget(self.run_btn)
        self.stop_btn = QPushButton("Stop")
        self.stop_btn.setProperty("size", "small")
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self.stop)
        rail.addWidget(self.stop_btn)
        self.state = label("", role="small")
        rail.addWidget(self.state)
        rail.addStretch(1)
        lay.addLayout(rail)

        self.console = QPlainTextEdit()
        self.console.setReadOnly(True)
        self.console.setProperty("surface", "console")
        lay.addWidget(self.console, 1)

        if not tool.exists:
            self.run_btn.setEnabled(False)
            self._say(f"script missing: {tool.script}", t.ERR)

    # -- command -------------------------------------------------------------

    def argv(self) -> list[str]:
        """The tool's arguments. An empty field is OMITTED entirely rather
        than passed as an empty string - a tool cannot tell "" from "not
        given", and the difference usually matters."""
        out: list[str] = []
        for flag, box in self.flags.items():
            if box.isChecked():
                out.append(flag)
        for arg in self.tool.args:
            value = self.args[arg.key].text().strip()
            if not value:
                continue
            if arg.flag:
                out += [arg.flag, value]
            else:
                out.append(value)
        return out

    def run(self) -> None:
        if self._proc is not None:
            return
        self.console.clear()
        self.run_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self._say("running…", t.OK)

        proc = QProcess(self)
        proc.setProcessChannelMode(QProcess.MergedChannels)
        proc.readyReadStandardOutput.connect(self._out)
        proc.finished.connect(self._done)
        # QProcess does NOT emit finished on a failed start (bad interpreter
        # path, missing script), so without this the Run button stays disabled
        # and "running…" shows forever
        proc.errorOccurred.connect(self._error)
        proc.setWorkingDirectory(str(self.tool.workdir))
        env = QProcessEnvironment()
        for key, value in self.shell.gateway.child_env(dict(os.environ)).items():
            env.insert(key, str(value))
        proc.setProcessEnvironment(env)
        self._proc = proc
        proc.start(sys.executable, ["-u", str(self.tool.script)] + self.argv())

    def stop(self) -> None:
        if self._proc is None:
            return
        self._proc.kill()

    def _out(self) -> None:
        # insert, never appendPlainText: append starts a new paragraph per
        # call, so output that already ends in a newline comes out doubled
        chunk = bytes(self._proc.readAllStandardOutput()).decode(
            "utf-8", "replace")
        cursor = self.console.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        cursor.insertText(chunk)
        self.console.setTextCursor(cursor)

    def _done(self, code: int, _status) -> None:
        self._proc = None
        self.run_btn.setEnabled(self.tool.exists)
        self.stop_btn.setEnabled(False)
        self._say("finished" if code == 0 else f"exited with code {code}",
                  t.OK if code == 0 else t.ERR)

    def _error(self, err) -> None:
        if err == QProcess.ProcessError.FailedToStart:
            self._proc = None
            self.run_btn.setEnabled(self.tool.exists)
            self.stop_btn.setEnabled(False)
            self._say("failed to start", t.ERR)

    def _say(self, text: str, colour: str) -> None:
        self.state.setText(text)
        self.state.setStyleSheet(f"color: {colour};")

    def hideEvent(self, event) -> None:
        """Stop the tool when the user NAVIGATES away - a subprocess against a
        screen nobody can see holds a gateway slot and writes to a console
        that will never be read.

        But NOT when the whole window is just minimised (including to the
        tray): hiding the window delivers hideEvent to every visible child, so
        the old unconditional stop() killed a running tool the moment you
        minimised. A minimise leaves the window merely not-visible; a real
        navigation swaps the stacked page while the window stays up.
        """
        super().hideEvent(event)
        window = self.window()
        if window is not None and (window.isMinimized()
                                   or not window.isVisible()):
            return                          # minimised/tray - leave it running
        self.stop()

    def closeEvent(self, event) -> None:
        # the app really is going away now
        self.stop()
        super().closeEvent(event)
