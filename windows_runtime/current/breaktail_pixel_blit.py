"""Copy a tiny RGB pixel-art frame onto a Windows canvas with nearest scaling."""
from __future__ import annotations

import ctypes
from ctypes import wintypes


class BitmapInfoHeader(ctypes.Structure):
    _fields_ = [("size", wintypes.DWORD), ("width", wintypes.LONG),
                ("height", wintypes.LONG), ("planes", wintypes.WORD),
                ("bit_count", wintypes.WORD), ("compression", wintypes.DWORD),
                ("size_image", wintypes.DWORD), ("x_pels_per_meter", wintypes.LONG),
                ("y_pels_per_meter", wintypes.LONG), ("clr_used", wintypes.DWORD),
                ("clr_important", wintypes.DWORD)]


class BitmapInfo(ctypes.Structure):
    _fields_ = [("header", BitmapInfoHeader), ("colors", wintypes.DWORD * 3)]


_user32 = ctypes.WinDLL("user32", use_last_error=True)
_gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
_user32.GetDC.argtypes = (wintypes.HWND,)
_user32.GetDC.restype = wintypes.HDC
_user32.ReleaseDC.argtypes = (wintypes.HWND, wintypes.HDC)
_gdi32.SetStretchBltMode.argtypes = (wintypes.HDC, ctypes.c_int)
_gdi32.StretchDIBits.argtypes = (wintypes.HDC, ctypes.c_int, ctypes.c_int,
                                ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                ctypes.c_void_p, ctypes.POINTER(BitmapInfo),
                                wintypes.UINT, wintypes.DWORD)
_gdi32.StretchDIBits.restype = ctypes.c_int


def blit(canvas, image, width: int, height: int):
    source_width, source_height = image.size
    info = BitmapInfo()
    info.header.size = ctypes.sizeof(BitmapInfoHeader)
    info.header.width = source_width
    info.header.height = -source_height  # top-down RGB pixels
    info.header.planes = 1
    info.header.bit_count = 32
    info.header.compression = 0  # BI_RGB
    rgb = image.tobytes("raw", "BGRX")
    hwnd = canvas.winfo_id()
    dc = _user32.GetDC(hwnd)
    if not dc:
        raise OSError(ctypes.get_last_error(), "GetDC failed")
    try:
        _gdi32.SetStretchBltMode(dc, 3)  # COLORONCOLOR; preserve hard pixels
        lines = _gdi32.StretchDIBits(dc, 0, 0, width, height,
                                     0, 0, source_width, source_height,
                                     ctypes.c_char_p(rgb), ctypes.byref(info),
                                     0, 0x00CC0020)  # DIB_RGB_COLORS, SRCCOPY
        if lines == 0 or lines == -1:
            raise OSError(ctypes.get_last_error(), "StretchDIBits failed")
    finally:
        _user32.ReleaseDC(hwnd, dc)

