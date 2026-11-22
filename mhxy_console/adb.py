"""adb 通道：输入注入 + 抓帧（无第三方依赖，纯 subprocess）。

实测（MuMu NX15 / 960x540）：
    screencap -p : 471-800 ms/帧（PNG 1.0-2.1 MB）
    input tap    : 40-120 ms

坐标约定（实测确认）：
    `wm size` 报 540x960（自然竖屏），但 `screencap -p` 返回的是**当前旋转后**的 960x540，
    `input tap x y` 用的也是 screencap 那套坐标 —— 两者一致，直接拿模板匹配坐标点即可。
    所以本类的 `screen` 只作参考，**尺寸以帧为准**（见 `frame_size()`）。

注入通道（重要）：
    VM 内只有一个触摸设备 `Xiaomi Touchscreen`(deviceId=3)，由 `nemuinput` 服务产生。
    `adb shell input tap` 是 InputManager 注入，`deviceId/source` 与真人不同，可被判定；
    走宿主窗口 (`render_wnd`) + pywin32 注入鼠标，经 MuMu 转换后落在同一个 uinput 设备上，
    游戏侧与真人触摸不可区分 —— 生产环境优先用那条路。
"""
from __future__ import annotations

import random
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

ADB = "adb"


def _run(serial: str, *args: str, timeout: float = 30.0) -> subprocess.CompletedProcess:
    return subprocess.run([ADB, "-s", serial, *args],
                          capture_output=True, timeout=timeout)


def _run_bytes(serial: str, *args: str, timeout: float = 30.0) -> bytes:
    return subprocess.run([ADB, "-s", serial, *args],
                          capture_output=True, timeout=timeout).stdout


@dataclass
class Screen:
    width: int
    height: int


class AdbDevice:
    def __init__(self, serial: str):
        self.serial = serial
        self._screen: Screen | None = None

    # ---------- 连接 ----------
    def connect(self) -> bool:
        subprocess.run([ADB, "connect", self.serial],
                       capture_output=True, timeout=15)
        out = _run(self.serial, "shell", "echo ok").stdout
        return b"ok" in out

    def ensure_root(self) -> bool:
        out = _run(self.serial, "shell", "id -u").stdout.strip()
        return out == b"0"

    # ---------- 屏幕 ----------
    @property
    def screen(self) -> Screen:
        if self._screen is None:
            out = _run(self.serial, "shell", "wm", "size").stdout.decode(errors="replace")
            w = h = 0
            for tok in out.replace("Physical size:", " ").split():
                if "x" in tok:
                    a, _, b = tok.partition("x")
                    if a.strip().isdigit() and b.strip().isdigit():
                        w, h = int(a), int(b)
                        break
            self._screen = Screen(w or 960, h or 540)
        return self._screen

    def screencap_png(self, path: str | Path | None = None) -> bytes:
        png = _run_bytes(self.serial, "exec-out", "screencap", "-p")
        if path:
            Path(path).write_bytes(png)
        return png

    # ---------- 输入 ----------
    def tap(self, x: int, y: int, jitter: int = 0, settle: tuple[int, int] = (40, 120)):
        if jitter:
            x += random.randint(-jitter, jitter)
            y += random.randint(-jitter, jitter)
        _run(self.serial, "shell", "input", "tap", str(int(x)), str(int(y)))
        time.sleep(random.randint(*settle) / 1000.0)

    def swipe(self, x1: int, y1: int, x2: int, y2: int, ms: int = 260,
              segments: int = 4, jitter: int = 4):
        """分段滑动，模拟人手（一次性长 swipe 特征太机械）。"""
        for i in range(1, segments + 1):
            t = i / segments
            x = x1 + (x2 - x1) * t + random.randint(-jitter, jitter)
            y = y1 + (y2 - y1) * t + random.randint(-jitter, jitter)
            _run(self.serial, "shell", "input", "swipe",
                 str(x1 if i == 1 else int(x1 + (x2 - x1) * (i - 1) / segments)),
                 str(y1 if i == 1 else int(y1 + (y2 - y1) * (i - 1) / segments)),
                 str(int(x)), str(int(y)), str(max(30, ms // segments)))
            time.sleep(random.uniform(0.02, 0.06))

    def key(self, code: int, settle: tuple[int, int] = (60, 160)):
        _run(self.serial, "shell", "input", "keyevent", str(code))
        time.sleep(random.randint(*settle) / 1000.0)

    def text(self, s: str):
        _run(self.serial, "shell", "input", "text", s.replace(" ", "%s"))

    # ---------- 进程 ----------
    def pid_of(self, package: str) -> int | None:
        out = _run(self.serial, "shell", "pidof", package).stdout.decode().split()
        return int(out[0]) if out else None

    def foreground(self) -> str:
        out = _run(self.serial, "shell", "dumpsys", "window").stdout.decode(errors="replace")
        for line in out.splitlines():
            if "mCurrentFocus" in line:
                return line.strip()
        return ""

    # ---------- 只读内存（x86/dalvik 区可行；Houdini 客户机段会 EIO） ----------
    def read_mem(self, pid: int, addr: int, size: int) -> bytes:
        return _run_bytes(self.serial, "shell",
                          f"dd if=/proc/{pid}/mem bs=1 skip={addr} count={size} 2>/dev/null",
                          timeout=60)

    def maps(self, pid: int) -> str:
        return _run(self.serial, "shell", "cat", f"/proc/{pid}/maps").stdout.decode(errors="replace")
