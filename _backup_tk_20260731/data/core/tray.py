"""
core/tray.py - a Windows notification-area (tray) icon, pure ctypes.

Used by Settings > Display > "Send to tray when minimized": the app hides its
window and shows this icon; clicking the icon calls on_click (the app then
restores itself and removes the icon). No third-party packages - just
Shell_NotifyIconW plus a tiny hidden message window on a background thread.
"""

from __future__ import annotations

import ctypes
import threading
from ctypes import wintypes
from typing import Callable

WM_DESTROY = 0x0002
WM_CLOSE = 0x0010
WM_LBUTTONUP = 0x0202
WM_LBUTTONDBLCLK = 0x0203
WM_USER = 0x0400
WM_TRAY = WM_USER + 20

NIM_ADD, NIM_DELETE = 0x0, 0x2
NIF_MESSAGE, NIF_ICON, NIF_TIP = 0x1, 0x2, 0x4
IMAGE_ICON, LR_LOADFROMFILE, LR_DEFAULTSIZE = 1, 0x10, 0x40

WNDPROC = ctypes.WINFUNCTYPE(ctypes.c_longlong, wintypes.HWND, wintypes.UINT,
                             wintypes.WPARAM, wintypes.LPARAM)

# Explicit prototype: without it ctypes passes lparam as a 32-bit int and
# 64-bit values (e.g. pointer-sized lparams) overflow.
_DefWindowProc = ctypes.windll.user32.DefWindowProcW
_DefWindowProc.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM,
                           wintypes.LPARAM]
_DefWindowProc.restype = ctypes.c_longlong


class WNDCLASSW(ctypes.Structure):
    _fields_ = [("style", wintypes.UINT), ("lpfnWndProc", WNDPROC),
                ("cbClsExtra", ctypes.c_int), ("cbWndExtra", ctypes.c_int),
                ("hInstance", wintypes.HINSTANCE), ("hIcon", wintypes.HICON),
                ("hCursor", ctypes.c_void_p), ("hbrBackground", wintypes.HBRUSH),
                ("lpszMenuName", wintypes.LPCWSTR),
                ("lpszClassName", wintypes.LPCWSTR)]


class NOTIFYICONDATAW(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("hWnd", wintypes.HWND),
                ("uID", wintypes.UINT), ("uFlags", wintypes.UINT),
                ("uCallbackMessage", wintypes.UINT), ("hIcon", wintypes.HICON),
                ("szTip", wintypes.WCHAR * 128)]


class TrayIcon:
    """One tray icon. show() adds it (idempotent), hide() removes it.
    on_click fires on a left click or double click - marshal it onto your UI
    thread yourself (e.g. app.after(0, ...))."""

    _seq = 0

    def __init__(self, tooltip: str, icon_path: str,
                 on_click: Callable[[], None]) -> None:
        self.tooltip = tooltip[:127]
        self.icon_path = icon_path
        self.on_click = on_click
        self._hwnd: int | None = None
        self._thread: threading.Thread | None = None
        self._ready = threading.Event()
        self.visible = False

    # -- public ------------------------------------------------------------

    def show(self) -> None:
        if self.visible:
            return
        self._ready.clear()
        self._thread = threading.Thread(target=self._run, daemon=True,
                                        name="tray-icon")
        self._thread.start()
        self._ready.wait(timeout=3)
        self.visible = True

    def hide(self) -> None:
        if self._hwnd:
            ctypes.windll.user32.PostMessageW(self._hwnd, WM_CLOSE, 0, 0)
            self._hwnd = None
        self.visible = False

    # -- worker --------------------------------------------------------------

    def _run(self) -> None:
        u = ctypes.windll.user32
        TrayIcon._seq += 1
        cls_name = f"WFToolboxTray{TrayIcon._seq}"
        nid: NOTIFYICONDATAW | None = None

        def proc(hwnd, msg, wparam, lparam):
            if msg == WM_TRAY and lparam in (WM_LBUTTONUP, WM_LBUTTONDBLCLK):
                try:
                    self.on_click()
                except Exception:                           # noqa: BLE001
                    pass
                return 0
            if msg == WM_CLOSE:
                u.DestroyWindow(hwnd)
                return 0
            if msg == WM_DESTROY:
                if nid is not None:
                    ctypes.windll.shell32.Shell_NotifyIconW(
                        NIM_DELETE, ctypes.byref(nid))
                u.PostQuitMessage(0)
                return 0
            return _DefWindowProc(hwnd, msg, wparam, lparam)

        wndproc = WNDPROC(proc)                 # keep a reference alive
        wc = WNDCLASSW()
        wc.lpfnWndProc = wndproc
        wc.lpszClassName = cls_name
        wc.hInstance = ctypes.windll.kernel32.GetModuleHandleW(None)
        u.RegisterClassW(ctypes.byref(wc))
        hwnd = u.CreateWindowExW(0, cls_name, cls_name, 0, 0, 0, 0, 0,
                                 None, None, wc.hInstance, None)
        self._hwnd = hwnd

        hicon = u.LoadImageW(None, self.icon_path, IMAGE_ICON, 0, 0,
                             LR_LOADFROMFILE | LR_DEFAULTSIZE)
        nid = NOTIFYICONDATAW()
        nid.cbSize = ctypes.sizeof(NOTIFYICONDATAW)
        nid.hWnd = hwnd
        nid.uID = 1
        nid.uFlags = NIF_MESSAGE | NIF_ICON | NIF_TIP
        nid.uCallbackMessage = WM_TRAY
        nid.hIcon = hicon
        nid.szTip = self.tooltip
        ctypes.windll.shell32.Shell_NotifyIconW(NIM_ADD, ctypes.byref(nid))
        self._ready.set()

        msg = wintypes.MSG()
        while u.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            u.TranslateMessage(ctypes.byref(msg))
            u.DispatchMessageW(ctypes.byref(msg))
        u.UnregisterClassW(cls_name, wc.hInstance)
