"""Background window capture via Win32 PrintWindow.

Captures a specific HWND's real, composited pixels at the display's true DPI
WITHOUT bringing the window to the foreground or grabbing the whole screen -
PrintWindow(PW_RENDERFULLCONTENT) asks the window to render itself, so it works
even when the window is parked off-screen or occluded.

This is the UI/UX audit's capture primitive: it records what the app ACTUALLY
renders at 300% scaling, not what QWidget.grab() predicts it will.
"""
from __future__ import annotations

import ctypes
from ctypes import byref, c_int, c_void_p, create_string_buffer, sizeof, wintypes

_user32 = ctypes.windll.user32
_gdi32 = ctypes.windll.gdi32

# 64-bit safety: handles are pointers. Without these, ctypes truncates them to
# 32-bit ints and the calls corrupt or crash.
_user32.GetWindowDC.restype = c_void_p
_user32.GetWindowDC.argtypes = [c_void_p]
_user32.GetDC.restype = c_void_p
_user32.GetDC.argtypes = [c_void_p]
_user32.ReleaseDC.argtypes = [c_void_p, c_void_p]
_user32.GetWindowRect.argtypes = [c_void_p, c_void_p]
_user32.PrintWindow.argtypes = [c_void_p, c_void_p, wintypes.UINT]
_user32.PrintWindow.restype = wintypes.BOOL
_gdi32.CreateCompatibleDC.restype = c_void_p
_gdi32.CreateCompatibleDC.argtypes = [c_void_p]
_gdi32.CreateCompatibleBitmap.restype = c_void_p
_gdi32.CreateCompatibleBitmap.argtypes = [c_void_p, c_int, c_int]
_gdi32.SelectObject.restype = c_void_p
_gdi32.SelectObject.argtypes = [c_void_p, c_void_p]
_gdi32.DeleteObject.argtypes = [c_void_p]
_gdi32.DeleteDC.argtypes = [c_void_p]
_gdi32.GetDIBits.argtypes = [c_void_p, c_void_p, wintypes.UINT, wintypes.UINT,
                             c_void_p, c_void_p, wintypes.UINT]
_gdi32.GetDIBits.restype = c_int

PW_RENDERFULLCONTENT = 0x00000002
BI_RGB = 0
DIB_RGB_COLORS = 0


class _BMIH(ctypes.Structure):
    _fields_ = [("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG),
                ("biHeight", wintypes.LONG), ("biPlanes", wintypes.WORD),
                ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
                ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", wintypes.LONG),
                ("biYPelsPerMeter", wintypes.LONG), ("biClrUsed", wintypes.DWORD),
                ("biClrImportant", wintypes.DWORD)]


def capture(hwnd: int, path: str) -> tuple[int, int, bool, int]:
    """PrintWindow `hwnd` to `path` (PNG via QImage). Returns
    (width, height, printwindow_ok, distinct_row0_pixels). The last value is a
    cheap non-blank signal: a solid/black capture has 1."""
    from PySide6.QtGui import QImage

    rect = wintypes.RECT()
    _user32.GetWindowRect(c_void_p(hwnd), byref(rect))
    w, h = rect.right - rect.left, rect.bottom - rect.top
    if w <= 0 or h <= 0:
        return (w, h, False, 0)

    screen_dc = _user32.GetDC(None)
    mem_dc = _gdi32.CreateCompatibleDC(screen_dc)
    bmp = _gdi32.CreateCompatibleBitmap(screen_dc, w, h)
    old = _gdi32.SelectObject(mem_dc, bmp)
    ok = bool(_user32.PrintWindow(c_void_p(hwnd), mem_dc, PW_RENDERFULLCONTENT))

    bmi = _BMIH()
    bmi.biSize = sizeof(_BMIH)
    bmi.biWidth = w
    bmi.biHeight = -h            # negative => top-down rows
    bmi.biPlanes = 1
    bmi.biBitCount = 32
    bmi.biCompression = BI_RGB
    buf = create_string_buffer(w * h * 4)
    _gdi32.GetDIBits(mem_dc, bmp, 0, h, buf, byref(bmi), DIB_RGB_COLORS)

    # GDI gives BGRX with no alpha; Format_RGB32 reads exactly that and ignores
    # the 4th byte, so the PNG is opaque and correctly coloured.
    img = QImage(buf, w, h, QImage.Format_RGB32).copy()   # copy: outlive buf
    img.save(path)

    distinct = len({buf.raw[i:i + 4] for i in range(0, min(w, 400) * 4, 4)})

    _gdi32.SelectObject(mem_dc, old)
    _gdi32.DeleteObject(bmp)
    _gdi32.DeleteDC(mem_dc)
    _user32.ReleaseDC(None, screen_dc)
    return (w, h, ok, distinct)
