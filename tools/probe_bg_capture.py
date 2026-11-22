"""后台能力实测 A：抓屏在三种窗口状态下的可用性。

状态：
  1) 正常（前台/可见）
  2) 被遮挡（用一块 topmost 无边框黑窗盖住）
  3) 最小化（SW_MINIMIZE）
每种状态各测 BitBlt 与 PrintWindow(PW_RENDERFULLCONTENT)，输出 nonblack / std。

结论判据：
  nonblack > 0.9 且 std > 6  → 该状态可用
"""
from __future__ import annotations

import ctypes
import tkinter as tk
from ctypes import wintypes as wt

import numpy as np

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mhxy_console.win import (FrameSource, dpi_aware, _bitmap_to_np,  # noqa: E402
                              windows_of_pid)

user32 = ctypes.WinDLL("user32", use_last_error=True)
SW_MINIMIZE = 6
SW_RESTORE = 9
SW_SHOW = 5


def stats(img: np.ndarray) -> tuple[float, float]:
    if img.size == 0:
        return 0.0, 0.0
    nonblack = float((img.max(axis=2) > 8).mean())
    return nonblack, float(img.std())


def cap(tgt, mode: str) -> tuple[bool, float, float]:
    ok, img = _bitmap_to_np(tgt.hwnd, tgt.client_w, tgt.client_h, mode)
    nb, sd = stats(img)
    return ok, nb, sd


def overlay(tgt, duration_ms: int = 1500):
    """在目标窗口上方盖一块 topmost 黑窗，返回后 1.5s 自动销毁。"""
    root = tk.Tk()
    root.overrideredirect(True)
    root.attributes("-topmost", True)
    root.geometry(f"{tgt.client_w}x{tgt.client_h}+{tgt.screen_x}+{tgt.screen_y}")
    root.configure(bg="black")
    root.update()
    root.after(duration_ms, root.destroy)
    return root


def main() -> int:
    dpi_aware()
    import subprocess, json
    mm = subprocess.run(["powershell", "-NoProfile", "-Command",
                         "(Get-Process MuMuNxDevice | Select-Object -First 1).Id"],
                        capture_output=True, text=True)
    pid = int(mm.stdout.strip())
    print(f"MuMuNxDevice pid = {pid}")

    src = FrameSource(pid)
    tgt = src.refresh_target()
    print(f"target: hwnd=0x{tgt.hwnd:08X} client={tgt.client_w}x{tgt.client_h} "
          f"at=({tgt.screen_x},{tgt.screen_y}) mode_lock={src._mode_lock}")
    print()

    def report(state: str):
        line = f"[{state:10s}]"
        for mode in ("bitblt", "print"):
            ok, nb, sd = cap(tgt, mode)
            verdict = "OK" if (ok and nb > 0.9 and sd > 6) else "FAIL"
            line += f"  {mode}: ok={int(ok)} nonblack={nb:5.1%} std={sd:5.2f} {verdict}"
        print(line)

    report("正常")

    root = overlay(tgt, 2500)
    root.update()
    report("被遮挡")
    root.destroy()

    user32.ShowWindow(tgt.hwnd, SW_MINIMIZE)
    ctypes.windll.user32.Sleep(700) if False else __import__("time").sleep(0.7)
    report("最小化")
    user32.ShowWindow(tgt.hwnd, SW_RESTORE)
    __import__("time").sleep(0.7)
    report("恢复后")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
