"""MHXY 中控 · 帧源层（我们自己的实现）

设计依据（本机实测，不引用任何外部项目）：
    adb exec-out screencap   392 ms   ← 否决
    GDI BitBlt(window DC)      4.1 ms  ← 主通道（窗口可见/未被完全遮挡）
    PrintWindow(FULLCONTENT)  18.7 ms  ← 兜底（被遮挡/BitBlt 出黑帧时）
    MuMu 游戏窗口客户端       960x580（底部 960x540 是游戏画面，上方 40px 是 MuMu 自绘标题栏）

三个硬约束：
 1. 只认 pid：窗口按进程归属识别，不靠标题匹配（标题会被改、会被多开器加后缀）。
 2. 黑帧/丢帧显式返回失败，绝不把空帧往下游传。
 3. 输出永远是"原始像素帧 + 该帧的坐标原点"，归一化交给 viewport 层，抓帧层不做缩放。
"""
from __future__ import annotations

import ctypes
import time
from ctypes import wintypes as wt
from dataclasses import dataclass

import numpy as np

user32 = ctypes.WinDLL("user32", use_last_error=True)
gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)

# ---- 64 位下句柄必须显式声明返回类型，否则被截断成 32 位 ----
user32.GetClientRect.argtypes = [wt.HWND, ctypes.POINTER(wt.RECT)]
user32.GetWindowRect.argtypes = [wt.HWND, ctypes.POINTER(wt.RECT)]
user32.GetDC.argtypes = [wt.HWND]
user32.GetDC.restype = wt.HDC
user32.ReleaseDC.argtypes = [wt.HWND, wt.HDC]
user32.PrintWindow.argtypes = [wt.HWND, wt.HDC, wt.UINT]
user32.GetWindowThreadProcessId.argtypes = [wt.HWND, ctypes.POINTER(wt.DWORD)]
user32.IsWindow.argtypes = [wt.HWND]
user32.IsIconic.argtypes = [wt.HWND]
user32.SetProcessDPIAware.restype = wt.BOOL

gdi32.CreateCompatibleDC.argtypes = [wt.HDC]
gdi32.CreateCompatibleDC.restype = wt.HDC
gdi32.CreateCompatibleBitmap.argtypes = [wt.HDC, ctypes.c_int, ctypes.c_int]
gdi32.CreateCompatibleBitmap.restype = wt.HBITMAP
gdi32.SelectObject.argtypes = [wt.HDC, wt.HGDIOBJ]
gdi32.SelectObject.restype = wt.HGDIOBJ
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


class _BMIH(ctypes.Structure):
    _fields_ = [("biSize", wt.DWORD), ("biWidth", wt.LONG), ("biHeight", wt.LONG),
                ("biPlanes", wt.WORD), ("biBitCount", wt.WORD),
                ("biCompression", wt.DWORD), ("biSizeImage", wt.DWORD),
                ("biXPelsPerMeter", wt.LONG), ("biYPelsPerMeter", wt.LONG),
                ("biClrUsed", wt.DWORD), ("biClrImportant", wt.DWORD)]


class _BMI(ctypes.Structure):
    _fields_ = [("bmiHeader", _BMIH), ("bmiColors", wt.DWORD * 3)]


@dataclass
class WinTarget:
    hwnd: int
    pid: int
    client_w: int
    client_h: int
    screen_x: int          # 客户区左上角在屏幕上的坐标（日志/排错用）
    screen_y: int
    title: str = ""

    def __str__(self) -> str:
        return (f"0x{self.hwnd:08X} pid={self.pid} client={self.client_w}x{self.client_h} "
                f"at=({self.screen_x},{self.screen_y})")


def dpi_aware() -> None:
    """声明 DPI 感知，避免系统把窗口坐标虚拟化成 1.25/1.5 倍。"""
    try:
        ctypes.WinDLL("shcore").SetProcessDpiAwareness(2)   # PER_MONITOR_AWARE
    except Exception:
        user32.SetProcessDPIAware()


def windows_of_pid(pid: int, min_w: int = 320, min_h: int = 240) -> list[WinTarget]:
    """该进程所有可见、尺寸达标的顶层窗口，按面积降序。"""
    found: list[WinTarget] = []
    proto = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)

    def cb(hwnd, _):
        owner = wt.DWORD(0)
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        if owner.value != pid or not user32.IsWindow(hwnd):
            return True
        cr, wr = wt.RECT(), wt.RECT()
        user32.GetClientRect(hwnd, ctypes.byref(cr))
        user32.GetWindowRect(hwnd, ctypes.byref(wr))
        cw, ch = cr.right - cr.left, cr.bottom - cr.top
        if cw < min_w or ch < min_h:
            return True
        n = user32.GetWindowTextLengthW(hwnd)
        buf = ctypes.create_unicode_buffer(n + 2)
        user32.GetWindowTextW(hwnd, buf, n + 2)
        found.append(WinTarget(hwnd=hwnd, pid=pid, client_w=cw, client_h=ch,
                               screen_x=wr.left, screen_y=wr.top, title=buf.value))
        return True

    user32.EnumWindows(proto(cb), 0)
    found.sort(key=lambda t: t.client_w * t.client_h, reverse=True)
    return found


def _bitmap_to_np(hwnd: int, w: int, h: int, mode: str) -> tuple[bool, np.ndarray]:
    hdc = user32.GetDC(hwnd)
    if not hdc:
        return False, np.empty((0, 0, 3), np.uint8)
    mdc = gdi32.CreateCompatibleDC(hdc)
    bmp = gdi32.CreateCompatibleBitmap(hdc, w, h)
    old = gdi32.SelectObject(mdc, bmp)
    try:
        if mode == "print":
            ok = user32.PrintWindow(hwnd, mdc, PW_CLIENTONLY | PW_RENDERFULLCONTENT)
        else:
            ok = gdi32.BitBlt(mdc, 0, 0, w, h, hdc, 0, 0, SRCCOPY)
        bmi = _BMI()
        bmi.bmiHeader.biSize = ctypes.sizeof(_BMIH)
        bmi.bmiHeader.biWidth = w
        bmi.bmiHeader.biHeight = -h          # 负数 = 自上而下，省一次翻转
        bmi.bmiHeader.biPlanes = 1
        bmi.bmiHeader.biBitCount = 32
        buf = (ctypes.c_ubyte * (w * h * 4))()
        gdi32.GetDIBits(mdc, bmp, 0, h, buf, ctypes.byref(bmi), DIB_RGB_COLORS)
        arr = np.frombuffer(bytes(buf), np.uint8).reshape(h, w, 4)[:, :, :3].copy()
        return bool(ok), arr
    finally:
        gdi32.SelectObject(mdc, old)
        gdi32.DeleteObject(bmp)
        gdi32.DeleteDC(mdc)
        user32.ReleaseDC(hwnd, hdc)


@dataclass
class Frame:
    image: np.ndarray        # HxWx3 BGR，未缩放
    t: float                 # 抓帧时刻（monotonic）
    mode: str                # "bitblt" | "print"
    cost_ms: float

    @property
    def size(self) -> tuple[int, int]:
        h, w = self.image.shape[:2]
        return w, h


class FrameSource:
    """帧源：BitBlt 优先，黑帧自动降级 PrintWindow；连续失败抛异常而不是返回空帧。"""

    def __init__(self, pid: int, prefer: str = "bitblt", black_ratio: float = 0.995):
        self.pid = pid
        self.prefer = prefer
        self.black_ratio = black_ratio
        self.target: WinTarget | None = None
        self._fails = 0
        self._mode_lock: str | None = None

    # ---------- 目标发现 ----------
    def refresh_target(self) -> WinTarget:
        """候选阶梯：不是"最大的窗口"，而是"能抓到有内容画面的窗口"。

        实测教训：MuMuNxDevice 进程下同时存在 1424x720 的宿主窗口（全黑）和
        960x580 的实例窗口（有效画面）。按面积排序会选错，必须用内容验证。
        """
        cands = windows_of_pid(self.pid)
        if not cands:
            raise RuntimeError(f"pid {self.pid} 没有可用窗口（模拟器没起来/最小化了？）")

        best: tuple[float, WinTarget, str] | None = None
        for tgt in cands[:6]:
            for mode in ("bitblt", "print"):
                ok, img = _bitmap_to_np(tgt.hwnd, tgt.client_w, tgt.client_h, mode)
                if not ok or img.size == 0 or self._is_black(img):
                    continue
                score = float(img.std())          # 有内容的画面复杂度明显更高
                if score < 6.0:                   # 近乎纯色的窗口（贴图未渲染）不算
                    continue
                if best is None or score > best[0]:
                    best = (score, tgt, mode)
                break                              # 该窗口 bitblt 有效就不必再试 print
        if best is None:
            raise RuntimeError(
                f"pid {self.pid} 的 {len(cands)} 个窗口都抓不到有效画面"
                f"（窗口最小化/被独占全屏遮挡？）")
        _, self.target, mode = best
        self._mode_lock = mode
        return self.target

    def ensure(self) -> WinTarget:
        if self.target is None or not user32.IsWindow(self.target.hwnd):
            return self.refresh_target()
        return self.target

    # ---------- 抓帧 ----------
    def _is_black(self, img: np.ndarray) -> bool:
        return float((img.max(axis=2) <= 8).mean()) > self.black_ratio

    def grab(self) -> Frame:
        tgt = self.ensure()
        order = [self._mode_lock] if self._mode_lock else [self.prefer, "bitblt", "print"]
        last_err = ""
        for mode in [m for m in dict.fromkeys(order) if m]:
            t0 = time.perf_counter()
            ok, img = _bitmap_to_np(tgt.hwnd, tgt.client_w, tgt.client_h, mode)
            cost = (time.perf_counter() - t0) * 1000
            if not ok or img.size == 0:
                last_err = f"{mode}: GDI 调用失败"
                continue
            if self._is_black(img):
                last_err = f"{mode}: 黑帧"
                continue
            self._fails = 0
            self._mode_lock = mode if self._mode_lock != mode else mode
            return Frame(image=img, t=time.monotonic(), mode=mode, cost_ms=cost)

        self._fails += 1
        if self._fails >= 3 and self._mode_lock == "bitblt":
            self._mode_lock = "print"        # 连续失败就长期切到 PrintWindow
        raise RuntimeError(f"抓帧失败（pid={self.pid} hwnd=0x{tgt.hwnd:08X}）：{last_err}")


if __name__ == "__main__":
    import sys
    dpi_aware()
    pid = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    if not pid:
        print("usage: python -m mhxy_console.win <mumu_pid>")
        raise SystemExit(2)
    src = FrameSource(pid)
    t = src.refresh_target()
    print("target:", t)
    for i in range(10):
        f = src.grab()
        print(f"  #{i} {f.mode:7s} {f.cost_ms:6.2f} ms  {f.size[0]}x{f.size[1]}")
    if "cv2" in sys.modules or True:
        import cv2
        cv2.imwrite("E:\\out\\win_frame.png", f.image)
        print("saved E:\\out\\win_frame.png")
