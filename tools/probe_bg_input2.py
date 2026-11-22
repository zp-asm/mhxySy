"""后台能力实测 B（严格版）：PostMessage 到底能不能把输入送进 Android。

方法：持续 `getevent -lt`，分相位注入，按相位统计真实 EV_ 事件条数。
  phase0 静默基线      —— 不应有事件
  phase1 PostMessage   —— 鼠标移动/点击 + 按键
  phase2 adb input tap —— 正对照（一定进 guest）
  phase3 PostMessage 再试一次（换坐标/换消息）

判据：phase1 的 EV_ 条数 ≈ 0 且 phase2 明显 > 0  → PostMessage 无效
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

WM_MOUSEMOVE, WM_LBUTTONDOWN, WM_LBUTTONUP = 0x0200, 0x0201, 0x0202
WM_KEYDOWN, WM_KEYUP = 0x0100, 0x0101
MK_LBUTTON = 0x0001
ADB, SERIAL = "adb", "127.0.0.1:16384"


class EventTap:
    """持续读 getevent，按相位打点计数。"""

    def __init__(self):
        self.proc = subprocess.Popen(
            [ADB, "-s", SERIAL, "shell", "getevent -lt"],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
        self.events: list[tuple[float, str]] = []
        self.marks: list[tuple[str, float]] = []
        self._stop = False
        self.th = threading.Thread(target=self._loop, daemon=True)
        self.th.start()

    def _loop(self):
        for line in self.proc.stdout:
            if self._stop:
                break
            if "EV_" in line:
                self.events.append((time.perf_counter(), line.rstrip()))

    def mark(self, name: str):
        self.marks.append((name, time.perf_counter()))

    def stop(self) -> None:
        self._stop = True
        try:
            self.proc.terminate()
        except Exception:
            pass
        self.th.join(timeout=2)

    def per_phase(self) -> dict[str, int]:
        out: dict[str, int] = {}
        bounds = self.marks + [("__end__", 1e18)]
        for i in range(len(bounds) - 1):
            name, t0 = bounds[i]
            _, t1 = bounds[i + 1]
            out[name] = sum(1 for t, _ in self.events if t0 <= t < t1)
        return out

    def sample(self, n: int = 6) -> list[str]:
        return [ln for _, ln in self.events[:n]]


def post(hwnd, msg, wp, lp) -> bool:
    return bool(user32.PostMessageW(hwnd, msg, wp, lp))


def adb(*args: str) -> None:
    subprocess.run([ADB, "-s", SERIAL, "shell", *args], capture_output=True, timeout=20)


def main() -> int:
    dpi_aware()
    pid = int(subprocess.run(
        ["powershell", "-NoProfile", "-Command",
         "(Get-Process MuMuNxDevice | Select-Object -First 1).Id"],
        capture_output=True, text=True).stdout.strip())
    src = FrameSource(pid)
    tgt = src.refresh_target()
    print(f"target hwnd=0x{tgt.hwnd:08X} client={tgt.client_w}x{tgt.client_h}")

    tap = EventTap()
    time.sleep(1.2)                      # 等 getevent 起来

    # phase0 基线
    tap.mark("p0_idle")
    time.sleep(1.5)

    # phase1 PostMessage
    cx, cy = tgt.client_w // 2, int(tgt.client_h * 0.72)
    lp = (cy << 16) | (cx & 0xFFFF)
    tap.mark("p1_postmsg")
    for i in range(6):
        post(tgt.hwnd, WM_MOUSEMOVE, 0, ((cy + i * 6) << 16) | ((cx + i * 6) & 0xFFFF))
        time.sleep(0.05)
    post(tgt.hwnd, WM_LBUTTONDOWN, MK_LBUTTON, lp); time.sleep(0.05)
    post(tgt.hwnd, WM_LBUTTONUP, 0, lp); time.sleep(0.05)
    post(tgt.hwnd, WM_KEYDOWN, 0x41, 0x001E0001); time.sleep(0.05)   # 'A'
    post(tgt.hwnd, WM_KEYUP, 0x41, 0xC01E0001); time.sleep(0.05)
    time.sleep(1.2)

    # phase2 正对照：adb input
    tap.mark("p2_adb")
    adb("input", "tap", str(cx), str(cy))
    time.sleep(0.6)
    adb("input", "keyevent", "24")      # VOLUME_UP，零副作用
    time.sleep(1.5)

    # phase3 PostMessage 变体：WM_CHAR / 带 focus 的 key
    tap.mark("p3_postmsg2")
    for vk in (0x0D, 0x1B):             # Enter / Esc
        post(tgt.hwnd, WM_KEYDOWN, vk, 0x001C0001); time.sleep(0.05)
        post(tgt.hwnd, WM_KEYUP, vk, 0xC01C0001); time.sleep(0.05)
    time.sleep(1.2)

    tap.mark("p4_end")
    time.sleep(0.3)
    tap.stop()

    counts = tap.per_phase()
    print("\n--- 各相位 guest 事件数（EV_ 行）---")
    for k, v in counts.items():
        print(f"  {k:14s} {v}")
    print("\n--- 事件样本 ---")
    for ln in tap.sample():
        print("  ", ln)

    p1, p2 = counts.get("p1_postmsg", 0), counts.get("p2_adb", 0)
    print("\n判据：p2（adb 正对照）明显 > 0，p1（PostMessage）≈ 0 → PostMessage 无效")
    if p2 == 0:
        print("结论：连 adb 对照都没抓到事件，说明 getevent 抓错设备/权限不足，本次测量作废")
        return 2
    if p1 <= max(2, p2 // 10):
        print("结论：❌ PostMessage 不产生 guest 输入 —— 后台输入必须走 adb/scrcpy 通道")
        return 1
    print("结论：✅ PostMessage 能进 guest —— 后台窗口可以直接点")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
