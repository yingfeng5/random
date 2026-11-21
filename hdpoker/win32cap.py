"""Grab the HD Poker window on Windows.

Import this module only on Windows. It is not imported by vision, replay,
or the state machine. ``hdpoker.capture`` loads it inside the capture loop
after checking ``sys.platform``.
"""

from __future__ import annotations

from PIL import Image


def capture_window(title_contains: str = "HD Poker") -> Image.Image:
    """Return one full-window screenshot, title bar included.

    Layout fractions were measured on captures that include the title bar.
    """
    import win32con
    import win32gui
    import win32ui

    hwnd = _find_window(win32gui, title_contains)
    if not hwnd:
        raise RuntimeError(f"no window title contains {title_contains!r}")
    left, top, right, bottom = win32gui.GetWindowRect(hwnd)
    width, height = right - left, bottom - top
    if width <= 0 or height <= 0:
        raise RuntimeError("HD Poker window has no size")
    handle = win32gui.GetWindowDC(hwnd)
    source = win32ui.CreateDCFromHandle(handle)
    memory = source.CreateCompatibleDC()
    bitmap = win32ui.CreateBitmap()
    bitmap.CreateCompatibleBitmap(source, width, height)
    memory.SelectObject(bitmap)
    memory.BitBlt((0, 0), (width, height), source, (0, 0), win32con.SRCCOPY)
    raw = bitmap.GetBitmapBits(True)
    image = Image.frombuffer("RGB", (width, height), raw, "raw", "BGRX", 0, 1)
    memory.DeleteDC()
    source.DeleteDC()
    win32gui.ReleaseDC(hwnd, handle)
    win32gui.DeleteObject(bitmap.GetHandle())
    return image.copy()


def _find_window(win32gui, title_contains: str) -> int:
    found = []

    def visit(hwnd, _extra):
        if not win32gui.IsWindowVisible(hwnd):
            return
        title = win32gui.GetWindowText(hwnd) or ""
        if title_contains.lower() in title.lower():
            found.append(hwnd)

    win32gui.EnumWindows(visit, None)
    return found[0] if found else 0
