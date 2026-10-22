"""Passive OS metadata only. No document, browser, input or clipboard access."""
from collections import Counter
from datetime import datetime
import ctypes
from ctypes import wintypes
import os
from typing import Protocol


class RuntimeObserver(Protocol):
    def observe(self) -> dict: ...


class OSRuntimeObserver:
    def __init__(self, foreground=False):
        self.foreground = foreground

    def observe(self):
        result = {"current_time": datetime.now().astimezone().isoformat(timespec="seconds"),
                  "uptime": None, "active_processes": None}
        if os.name != "nt":
            # Unsupported fields stay explicitly unknown; never read /proc files.
            return result
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.GetTickCount64.restype = ctypes.c_ulonglong
        result["uptime"] = kernel.GetTickCount64() / 1000
        try:
            result["active_processes"] = self._processes(kernel)
        except OSError:
            pass
        if self.foreground:
            try:
                user = ctypes.WinDLL("user32", use_last_error=True)
                user.GetForegroundWindow.restype = wintypes.HWND
                user.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
                buf = ctypes.create_unicode_buffer(1024)
                user.GetWindowTextW(user.GetForegroundWindow(), buf, len(buf))
                result["foreground_window_title"] = buf.value
            except OSError:
                result["foreground_window_title"] = None
        return result

    @staticmethod
    def _processes(kernel):
        class Entry(ctypes.Structure):
            _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD),
                        ("th32ProcessID", wintypes.DWORD), ("th32DefaultHeapID", ctypes.c_size_t),
                        ("th32ModuleID", wintypes.DWORD), ("cntThreads", wintypes.DWORD),
                        ("th32ParentProcessID", wintypes.DWORD), ("pcPriClassBase", wintypes.LONG),
                        ("dwFlags", wintypes.DWORD), ("szExeFile", wintypes.WCHAR * 260)]
        kernel.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
        kernel.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
        for name in ("Process32FirstW", "Process32NextW"):
            getattr(kernel, name).argtypes = [wintypes.HANDLE, ctypes.POINTER(Entry)]
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = kernel.CreateToolhelp32Snapshot(2, 0)
        if handle == ctypes.c_void_p(-1).value:
            raise ctypes.WinError(ctypes.get_last_error())
        counts = Counter()
        try:
            entry = Entry()
            entry.dwSize = ctypes.sizeof(Entry)
            if not kernel.Process32FirstW(handle, ctypes.byref(entry)):
                raise ctypes.WinError(ctypes.get_last_error())
            while True:
                counts[entry.szExeFile] += 1
                if not kernel.Process32NextW(handle, ctypes.byref(entry)):
                    if ctypes.get_last_error() != 18:  # ERROR_NO_MORE_FILES
                        raise ctypes.WinError(ctypes.get_last_error())
                    break
        finally:
            kernel.CloseHandle(handle)
        return dict(sorted(counts.items()))


def runtime_changed(previous, current):
    if previous is None:
        return True
    # Clock progression is expected, not a PC-state change. A reboot is a change.
    keys = ("active_processes", "foreground_window_title")
    reboot = (isinstance(previous.get("uptime"), (int, float))
              and isinstance(current.get("uptime"), (int, float))
              and current["uptime"] < previous["uptime"])
    return reboot or any(previous.get(k) != current.get(k) for k in keys)
