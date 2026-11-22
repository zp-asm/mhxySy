"""后台能力实测 B：能否在不抢前台的情况下把输入送进模拟器。

方法：向 MuMu 窗口 PostMessage 鼠标移动/按键，同时用 `adb shell getevent` 监听
guest 内的输入设备，看事件有没有真的进到 Android 里。

判据：
  有 EV_ABS/EV_KEY 事件  → PostMessage 走通了 MuMu 的输入管线（后台可用）
  没有事件               → MuMu 不认合成消息，只能走 adb input / scrcpy 控制通道
"""
from __future__ import annotations

import ctypes
import subprocess
import sys
import threading
import time
from ctypes import wintypes as wt
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mhxy_console.win import FrameSource, dpi_aware  # noqa: E402

user32 = ctypes.WinDLL("user32", use_last_error=True)
user32.PostMessageW.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM]

WM_MOUSEMOVE = 0x0200
WM_LBUTTONDOWN = 0x0201
WM_LBUTTONUP = 0x0202
WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101
MK_LBUTTON = 0x0001

ADB = "adb"
SERIAL = "127.0.0.1:16384"


def sh(cmd: str, timeout: int = 20) -> str:
    try:
        r = subprocess.run([ADB, "-s", SERIAL, "shell", cmd],
                           capture_output=True, text=True, timeout=timeout)
        return (r.stdout or "") + (r.stderr or "")
    except Exception as e:
        return f"<err {e}>"


def post(hwnd, msg, wparam, lparam) -> bool:
    return bool(user32.PostMessageW(hwnd, msg, wparam, lparam))


def main() -> int:
    dpi_aware()
    pid_out = subprocess.run(
        ["powershell", "-NoProfile", "-Command",
         "(Get-Process MuMuNxDevice | Select-Object -First 1).Id"],
        capture_output=True, text=True).stdout.strip()
    pid = int(pid_out)
    src = FrameSource(pid)
    tgt = src.refresh_target()
    print(f"target: hwnd=0x{tgt.hwnd:08X} client={tgt.client_w}x{tgt.client_h}")

    print("\n--- guest 输入设备 ---")
    devs = sh("getevent -pl 2>/dev/null | grep -E 'add device|name:' | head -20")
    print(devs.strip()[:600] or "(读不到)")

    # 起一个后台监听：只抓 30 个事件
    collected: list[str] = []

    def listen():
        try:
            r = subprocess.run([ADB, "-s", SERIAL, "shell", "getevent -lt -c 30"],
                               capture_output=True, text=True, timeout=12)
            collected.append((r.stdout or "") + (r.stderr or ""))
        except subprocess.TimeoutExpired as e:
            collected.append((e.stdout or b"").decode("utf-8", "replace")
                             if isinstance(e.stdout, bytes) else str(e.stdout or ""))

    th = threading.Thread(target=listen, daemon=True)
    th.start()
    time.sleep(1.0)

    cx, cy = tgt.client_w // 2, int(tgt.client_h * 0.7)   # 画面中下部（多为地面/空地）
    print(f"\n--- 向窗口 PostMessage（坐标 {cx},{cy}） ---")

    lp = (cy << 16) | (cx & 0xFFFF)
    print("  WM_MOUSEMOVE :", post(tgt.hwnd, WM_MOUSEMOVE, 0, lp))
    time.sleep(0.15)
    print("  WM_MOUSEMOVE2:", post(tgt.hwnd, WM_MOUSEMOVE, 0, ((cy + 8) << 16) | ((cx + 8) & 0xFFFF)))
    time.sleep(0.15)
    print("  WM_LBUTTONDOWN:", post(tgt.hwnd, WM_LBUTTONDOWN, MK_LBUTTON, lp))
    time.sleep(0.08)
    print("  WM_LBUTTONUP  :", post(tgt.hwnd, WM_LBUTTONUP, 0, lp))
    time.sleep(0.3)

    # 一个不常用的键，避免在游戏里触发功能（F15 一般未绑定）
    VK_F15 = 0x7E
    print("  WM_KEYDOWN(F15):", post(tgt.hwnd, WM_KEYDOWN, VK_F15, 0x00000001))
    time.sleep(0.08)
    print("  WM_KEYUP(F15)  :", post(tgt.hwnd, WM_KEYUP, VK_F15, 0xC0000001))
    time.sleep(0.3)

    # 对照：adb input 一定会进 guest
    print("\n--- 对照组：adb input keyevent ---")
    t0 = time.perf_counter()
    sh("input keyevent 0")     # KEYCODE_UNKNOWN，零副作用，只用来产生事件
    print(f"  adb input cost = {(time.perf_counter()-t0)*1000:.0f} ms")

    th.join(timeout=13)
    log = collected[0] if collected else ""
    print("\n--- getevent 抓到的 guest 事件（节选） ---")
    lines = [ln for ln in log.splitlines() if ln.strip()]
    print("\n".join(lines[:20]) if lines else "(没有事件)")
    print(f"\n总事件行数 = {len(lines)}")

    verdict = "PostMessage 有效（后台输入可用）" if len(lines) > 3 else \
        "PostMessage 无效（MuMu 不认合成消息，需走 adb/scrcpy 通道）"
    print("\n结论:", verdict)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
