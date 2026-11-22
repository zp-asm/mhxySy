"""单实例 worker：抓帧 → 识别 → 决策 → 输入，带人类化节流。

挂机搬砖的骨架：把"循环里该做什么"塞进 Step 列表即可。
"""
from __future__ import annotations

import asyncio
import random
import time
from dataclasses import dataclass, field
from typing import Awaitable, Callable

import cv2
import numpy as np

from .adb import AdbDevice
from .vision import Match, Vision

PACKAGE = "com.netease.my"


@dataclass
class Step:
    """一步可执行动作。返回 True 表示本步完成。"""
    name: str
    run: Callable[["InstanceWorker"], Awaitable[bool]]
    cooldown: float = 1.0


@dataclass
class Stats:
    frames: int = 0
    taps: int = 0
    started_at: float = field(default_factory=time.time)
    errors: int = 0


class InstanceWorker:
    def __init__(self, serial: str, name: str = "", vision: Vision | None = None,
                 throttle: tuple[float, float] = (0.8, 2.4)):
        self.serial = serial
        self.name = name or serial
        self.dev = AdbDevice(serial)
        self.vision = vision or Vision()
        self.throttle = throttle
        self.stats = Stats()
        self._stop = asyncio.Event()
        self._frame: np.ndarray | None = None

    # ---------- 基础 ----------
    async def frame(self, fresh: bool = True) -> np.ndarray:
        if fresh or self._frame is None:
            png = await asyncio.to_thread(self.dev.screencap_png)
            arr = np.frombuffer(png, dtype=np.uint8)
            img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
            if img is None:
                raise RuntimeError("抓帧失败")
            self._frame = img
            self.stats.frames += 1
        return self._frame

    async def find(self, name: str, threshold: float | None = None) -> Match | None:
        img = await self.frame()
        return self.vision.find(img, name, threshold)

    async def tap(self, x: int, y: int, jitter: int = 3):
        await asyncio.to_thread(self.dev.tap, x, y, jitter)
        self.stats.taps += 1

    async def tap_match(self, name: str, threshold: float | None = None) -> bool:
        hit = await self.find(name, threshold)
        if not hit:
            return False
        cx, cy = hit.center
        await self.tap(cx, cy)
        return True

    async def sleep_h(self, lo: float | None = None, hi: float | None = None):
        lo = self.throttle[0] if lo is None else lo
        hi = self.throttle[1] if hi is None else hi
        await asyncio.sleep(random.uniform(lo, hi))

    async def idle(self, chance: float = 0.2, lo: float = 2.0, hi: float = 8.0):
        """随机发呆：打断"完美周期性"，行为模型最怕这个。"""
        if random.random() < chance:
            await asyncio.sleep(random.uniform(lo, hi))

    # ---------- 生命周期 ----------
    def stop(self):
        self._stop.set()

    async def run(self, steps: list[Step], loops: int | None = None):
        if not await asyncio.to_thread(self.dev.connect):
            raise RuntimeError(f"{self.serial} 连接失败")
        await asyncio.to_thread(self.dev.ensure_started if False else lambda: None)

        loops_done = 0
        while not self._stop.is_set():
            if loops is not None and loops_done >= loops:
                break
            acted = False
            for step in steps:
                if self._stop.is_set():
                    break
                try:
                    ok = await step.run(self)
                except Exception:
                    self.stats.errors += 1
                    ok = False
                if ok:
                    acted = True
                    await asyncio.sleep(step.cooldown + random.uniform(0, 0.6))
                    break
            if not acted:
                await self.idle(chance=1.0, lo=1.5, hi=4.0)
            loops_done += 1
            await self.sleep_h()

    # ---------- 常用判定 ----------
    async def in_game(self) -> bool:
        fg = await asyncio.to_thread(self.dev.foreground)
        return "MessiahNativeActivity" in fg

    async def pid(self) -> int | None:
        return await asyncio.to_thread(self.dev.pid_of, PACKAGE)


# ---------------- 现成的 Step 示例 ----------------
async def step_click_if_found(worker: InstanceWorker, template: str,
                              threshold: float = 0.88) -> bool:
    return await worker.tap_match(template, threshold)


def make_click_step(template: str, threshold: float = 0.88,
                    cooldown: float = 1.2) -> Step:
    async def _run(w: InstanceWorker) -> bool:
        return await step_click_if_found(w, template, threshold)

    return Step(name=f"click:{template}", run=_run, cooldown=cooldown)


async def step_recover(worker: InstanceWorker) -> bool:
    """卡住/掉线恢复：强杀应用再拉起（用 MuMuManager 更稳，见 main.py）。"""
    if await worker.in_game():
        return False
    await asyncio.to_thread(worker.dev.key, 4)  # BACK
    return True
