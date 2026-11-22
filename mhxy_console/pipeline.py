"""三线程流水线：采集 / 中断检测 / 主线决策，全部点击走单一出口。

为什么这么拆（这是踩坑后的结论）：
  · 单线程轮询时，OCR 一次要 0.5~1.5 s，这段时间弹窗、跳过按钮、对话选项全没人管；
  · 主线和"处理弹窗"如果抢同一个线程，必然漏掉高频干扰；
  · 但如果两个线程各自 adb_tap，又会互相插队（点了A又点B）。

所以：
  CaptureThread   只负责抓帧（6~10 ms/帧），把最新帧放进 latest 槽（不排队，只要最新）
  Interrupter     20 Hz 用**低成本模板**（不做 OCR）盯"使用/领取/跳过快进/关闭/对话选项"
                  命中 → 往执行器塞一个高优先级动作
  QuestBrain      慢速（2 Hz）跑主线状态机，需要动作时也塞执行器（低优先级）
  Executor        单线程消费动作队列，真打 adb_tap（全局唯一出口，避免插队）

优先级：中断(0) > 主线(5)。中断触发后 quest 的动作会被丢弃（1 秒内的旧计划）。
"""
from __future__ import annotations

import queue
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from .win import FrameSource, dpi_aware

ADB, SERIAL = "adb", "127.0.0.1:16384"
TEMPLATES = Path("templates")


def tap(x: int, y: int) -> float:
    t0 = time.perf_counter()
    subprocess.run([ADB, "-s", SERIAL, "shell", "input", "tap", str(int(x)), str(int(y))],
                   capture_output=True, timeout=20)
    return (time.perf_counter() - t0) * 1000


@dataclass
class Action:
    prio: int
    x: int
    y: int
    label: str
    t: float


# ---------------------------------------------------------------- 采集
class Capture(threading.Thread):
    def __init__(self, pid: int, fps: float = 6.0):
        super().__init__(daemon=True)
        dpi_aware()
        self.src = FrameSource(pid)
        self.latest: np.ndarray | None = None
        self.stamp = 0.0
        self.lock = threading.Lock()
        self.interval = 1.0 / fps
        self.running = True
        self.err = ""

    def run(self) -> None:
        while self.running:
            t0 = time.time()
            try:
                f = self.src.grab()
                with self.lock:
                    self.latest = f.image
                    self.stamp = time.time()
            except Exception as e:
                self.err = str(e)
            dt = self.interval - (time.time() - t0)
            if dt > 0:
                time.sleep(dt)

    def get(self) -> tuple[np.ndarray | None, float]:
        with self.lock:
            return self.latest, self.stamp


# ---------------------------------------------------------------- 执行
class Executor(threading.Thread):
    def __init__(self):
        super().__init__(daemon=True)
        self.q: queue.PriorityQueue = queue.PriorityQueue()
        self.running = True
        self.done: list[Action] = []
        self._seq = 0

    def push(self, prio: int, x: int, y: int, label: str) -> None:
        self._seq += 1
        self.q.put((prio, self._seq, Action(prio, x, y, label, time.time())))

    def run(self) -> None:
        while self.running:
            try:
                prio, _seq, a = self.q.get(timeout=0.2)
            except queue.Empty:
                continue
            if time.time() - a.t > 1.5:          # 过期动作丢弃（状态早变了）
                continue
            tap(a.x, a.y)
            self.done.append(a)
            time.sleep(0.15)


# ---------------------------------------------------------------- 中断检测
class Interrupter(threading.Thread):
    """低成本模板匹配（不做 OCR），20 Hz 找"必须马上点"的东西。"""

    SPECS = [
        ("use_btn", 0.86),      # 弹窗「使用」
        ("claim_btn", 0.86),    # 弹窗「领取」
        ("cut_ff2", 0.85),      # 过场 ▶▶
        ("hero_close2", 0.88),  # 面板 ✕
        ("hero_close", 0.88),
        ("popup_use", 0.86),
        ("popup_close", 0.86),
    ]

    # 这些只在"没有 HUD"的界面（过场/面板）才允许点
    NO_HUD_ONLY = {"cut_ff2", "cut_ff", "hero_close2", "hero_close"}

    def __init__(self, cap: Capture, ex: Executor, hz: float = 20.0, dry: bool = False):
        super().__init__(daemon=True)
        self.cap, self.ex, self.dry = cap, ex, dry
        self.interval = 1.0 / hz
        self.running = True
        self.tpls: list[tuple[str, np.ndarray, float]] = []
        for name, th in self.SPECS:
            p = TEMPLATES / f"{name}.png"
            if not p.exists():
                continue
            img = cv2.imread(str(p), cv2.IMREAD_GRAYSCALE)
            if img is not None:
                self.tpls.append((name, img, th))
        self.cooldown: dict[str, float] = {}
        self.hits = 0
        self.hud_tpl = None
        hp = TEMPLATES / "task_btn.png"
        if hp.exists():
            self.hud_tpl = cv2.imread(str(hp), cv2.IMREAD_GRAYSCALE)

    def run(self) -> None:
        while self.running:
            t0 = time.time()
            frame, stamp = self.cap.get()
            if frame is not None and time.time() - stamp < 1.0:
                g = cv2.cvtColor(frame[40:580, :], cv2.COLOR_BGR2GRAY)
                # HUD 判定：主界面必有任务按钮。有 HUD 时禁止点跳过/关闭，
                # 否则会"点头像开面板 → 关面板"无限循环（实测 40 次）。
                has_hud = False
                if self.hud_tpl is not None:
                    rh = cv2.matchTemplate(g, self.hud_tpl, cv2.TM_CCOEFF_NORMED)
                    has_hud = float(rh.max()) > 0.90
                for name, tpl, th in self.tpls:
                    if has_hud and name in self.NO_HUD_ONLY:
                        continue
                    if time.time() - self.cooldown.get(name, 0) < 2.0:
                        continue
                    res = cv2.matchTemplate(g, tpl, cv2.TM_CCOEFF_NORMED)
                    _, mx, _, loc = cv2.minMaxLoc(res)
                    if mx >= th:
                        cx = loc[0] + tpl.shape[1] // 2
                        cy = loc[1] + tpl.shape[0] // 2
                        self.cooldown[name] = time.time()
                        self.hits += 1
                        if not self.dry:
                            self.ex.push(0, cx, cy, f"interrupt:{name}")
                        print(f"  [int] {name} {mx:.2f} -> ({cx},{cy})", flush=True)
                        break
            dt = self.interval - (time.time() - t0)
            if dt > 0:
                time.sleep(dt)


if __name__ == "__main__":
    import subprocess as sp
    pid = int(sp.run(["powershell", "-NoProfile", "-Command",
                      "(Get-Process MuMuNxDevice | Select-Object -First 1).Id"],
                     capture_output=True, text=True, encoding="utf-8",
                     errors="replace").stdout.strip())
    cap, ex, itr = Capture(pid, fps=8), Executor(), Interrupter(Capture(pid), Executor())
    ex.start()
    cap.start()
    itr.cap = cap
    itr.ex = ex
    itr.start()
    print(f"pipeline up: pid={pid} templates={len(itr.tpls)}")
    try:
        while True:
            time.sleep(5)
            f, _ = cap.get()
            print(f"  frame={'ok' if f is not None else 'none'} hits={itr.hits} "
                  f"actions={len(ex.done)}", flush=True)
    except KeyboardInterrupt:
        pass
