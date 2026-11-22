"""探测：MuMu 窗口能不能后台抓（PrintWindow / BitBlt），以及耗时。

MuMu 是 VirtualBox + DX 渲染，PrintWindow 很可能拿到黑帧 —— 这里实测给结论。
ASCII-only 输出，避免控制台编码问题。
"""
from __future__ import annotations

import ctypes
import time
from ctypes import wintypes as wt

import numpy as np

user32 = ctypes.WinDLL("user32", use_last_error=True)
gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)

user32.GetClientRect.argtypes = [wt.HWND, ctypes.POINTER(wt.RECT)]
user32.GetWindowRect.argtypes = [wt.HWND, ctypes.POINTER(wt.RECT)]
user32.GetDC.argtypes = [wt.HWND]; user32.GetDC.restype = wt.HDC
user32.ReleaseDC.argtypes = [wt.HWND, wt.HDC]
user32.PrintWindow.argtypes = [wt.HWND, wt.HDC, wt.UINT]
gdi32.CreateCompatibleDC.argtypes = [wt.HDC]; gdi32.CreateCompatibleDC.restype = wt.HDC
gdi32.CreateCompatibleBitmap.argtypes = [wt.HDC, ctypes.c_int, ctypes.c_int]
gdi32.CreateCompatibleBitmap.restype = wt.HBITMAP
gdi32.SelectObject.argtypes = [wt.HDC, wt.HGDIOBJ]; gdi32.SelectObject.restype = wt.HGDIOBJ
gdi32.DeleteObject.argtypes = [wt.HGDIOBJ]
gdi32.DeleteDC.argtypes = [wt.HDC]
gdi32.BitBlt.argtypes = [wt.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                         wt.HDC, ctypes.c_int, ctypes.c_int, wt.DWORD]
gdi32.GetDIBits.argtypes = [wt.HDC, wt.HBITMAP, wt.UINT, wt.UINT, ctypes.c_void_p,
                            ctypes.c_void_p, wt.UINT]
gdi32.GetDIBits.restype = ctypes.c_int

PW_CLIENTONLY = 0x1
PW_RENDERFULLCONTENT = 0x2
SRCCOPY = 0x00CC0020
DIB_RGB_COLORS = 0


class BMIH(ctypes.Structure):
    _fields_ = [("biSize", wt.DWORD), ("biWidth", wt.LONG), ("biHeight", wt.LONG),
                ("biPlanes", wt.WORD), ("biBitCount", wt.WORD), ("biCompression", wt.DWORD),
                ("biSizeImage", wt.DWORD), ("biXPelsPerMeter", wt.LONG),
                ("biYPelsPerMeter", wt.LONG), ("biClrUsed", wt.DWORD), ("biClrImportant", wt.DWORD)]


class BMI(ctypes.Structure):
    _fields_ = [("bmiHeader", BMIH), ("bmiColors", wt.DWORD * 3)]


def grab(hwnd, w, h, mode):
    hdc = user32.GetDC(hwnd)
    mdc = gdi32.CreateCompatibleDC(hdc)
    bmp = gdi32.CreateCompatibleBitmap(hdc, w, h)
    old = gdi32.SelectObject(mdc, bmp)
    ok = 0
    if mode == "print":
        ok = user32.PrintWindow(hwnd, mdc, PW_CLIENTONLY | PW_RENDERFULLCONTENT)
    else:
        ok = gdi32.BitBlt(mdc, 0, 0, w, h, hdc, 0, 0, SRCCOPY)
    bmi = BMI()
    bmi.bmiHeader.biSize = ctypes.sizeof(BMIH)
    bmi.bmiHeader.biWidth = w
    bmi.bmiHeader.biHeight = -h
    bmi.bmiHeader.biPlanes = 1
    bmi.bmiHeader.biBitCount = 32
    buf = (ctypes.c_ubyte * (w * h * 4))()
    gdi32.GetDIBits(mdc, bmp, 0, h, buf, ctypes.byref(bmi), DIB_RGB_COLORS)
    gdi32.SelectObject(mdc, old)
    gdi32.DeleteObject(bmp)
    gdi32.DeleteDC(mdc)
    user32.ReleaseDC(hwnd, hdc)
    arr = np.frombuffer(bytes(buf), np.uint8).reshape(h, w, 4)[:, :, :3]
    return bool(ok), arr


def find_mumu():
    out = []
    EnumProc = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)

    def cb(hwnd, _):
        n = user32.GetWindowTextLengthW(hwnd)
        if n == 0:
            return True
        buf = ctypes.create_unicode_buffer(n + 2)
        user32.GetWindowTextW(hwnd, buf, n + 2)
        r = wt.RECT()
        user32.GetClientRect(hwnd, ctypes.byref(r))
        w, h = r.right - r.left, r.bottom - r.top
        if w >= 320 and h >= 240:
            out.append((hwnd, buf.value, w, h, bool(user32.IsWindowVisible(hwnd))))
        return True

    user32.EnumWindows(EnumProc(cb), 0)
    return out


def main() -> None:
    wins = find_mumu()
    print(f"visible windows >=320x240: {len(wins)}")
    cands = []
    for hwnd, title, w, h, vis in wins:
        if vis and any(k in title for k in ("MuMu", "mumu", "模拟", "梦幻", "Player")):
            cands.append((hwnd, title, w, h))
    if not cands:
        cands = [(h, t, w, hh) for h, t, w, hh, v in wins if v][:3]
    for hwnd, title, w, h in cands:
        print(f"\n=== hwnd=0x{hwnd:08X} client={w}x{h} title={title!r}")
        for mode in ("print", "bitblt"):
            t0 = time.perf_counter()
            ok, img = grab(hwnd, w, h, mode)
            dt = (time.perf_counter() - t0) * 1000
            mean = float(img.mean())
            nz = float((img.max(axis=2) > 8).mean())
            print(f"  {mode:7s} ok={ok} {dt:7.1f} ms  mean={mean:6.2f}  nonblack={nz:6.1%}")
            fn = f"E:\\out\\cap_{mode}_{hwnd:08X}.png"
            try:
                import cv2
                cv2.imwrite(fn, img)
                print(f"          saved {fn}")
            except Exception as e:
                print("          save failed:", e)


if __name__ == "__main__":
    main()
