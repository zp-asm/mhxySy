"""多线程分工（按职责拆开，互不阻塞，共用一个点击出口）。

    Capture        只抓帧（8 Hz，6~10 ms/帧），latest 槽
    Executor       唯一点击出口（优先级队列：0=中断 5=主线 9=杂项）
    PopupWorker    5 Hz：使用/领取/确定/关闭 —— 弹窗专用
    CutsceneWorker 5 Hz：▶▶ 跳过 / 面板 ✕ —— 只在"没有 HUD"时动作
    MonitorWorker  1 Hz：血量 / 蓝量 / 等级，超阈值发事件
    QuestWorker    1 Hz：主线状态机（战斗/面板/对话/主界面）

每个 worker 都只做自己的事，谁也不会因为别人在跑 OCR 而被堵住。
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np

from .pipeline import Action, Capture, Executor
from .quest import Sense, read_panel
from .win import FrameSource

TEMPLATES = Path("templates")


def _load(name: str) -> np.ndarray | None:
    p = TEMPLATES / f"{name}.png"
    if not p.exists():
        return None
    return cv2.imread(str(p), cv2.IMREAD_GRAYSCALE)


class BaseWorker(threading.Thread):
    def __init__(self, cap: Capture, ex: Executor, hz: float, name: str):
        super().__init__(daemon=True, name=name)
        self.cap, self.ex = cap, ex
        self.interval = 1.0 / hz
        self.running = True
        self.log: list[str] = []

    def say(self, msg: str) -> None:
        line = f"[{time.strftime('%H:%M:%S')}] {self.name}: {msg}"
        self.log.append(line)
        print(line, flush=True)

    def frame(self) -> np.ndarray | None:
        f, stamp = self.cap.get()
        if f is None or time.time() - stamp > 1.2:
            return None
        return f[40:580, :] if f.shape[0] > 540 else f


# ---------------------------------------------------------------- 弹窗
class PopupWorker(BaseWorker):
    """只处理"使用/领取/确定/关闭"。"""

    SPECS = [("use_btn", 0.86), ("claim_btn", 0.86),
             ("popup_use", 0.86), ("popup_close", 0.86)]

    def __init__(self, cap, ex, hz=5.0):
        super().__init__(cap, ex, hz, "popup")
        self.tpls = [(n, t, th) for n, th in self.SPECS if (t := _load(n)) is not None]
        self.cool: dict[str, float] = {}
        self.count = 0

    def run(self):
        while self.running:
            t0 = time.time()
            f = self.frame()
            if f is not None:
                g = cv2.cvtColor(f, cv2.COLOR_BGR2GRAY)
                for name, tpl, th in self.tpls:
                    if time.time() - self.cool.get(name, 0) < 2.5:
                        continue
                    if tpl.shape[0] >= g.shape[0] or tpl.shape[1] >= g.shape[1]:
                        continue
                    res = cv2.matchTemplate(g, tpl, cv2.TM_CCOEFF_NORMED)
                    _, mx, _, loc = cv2.minMaxLoc(res)
                    if mx >= th:
                        cx = loc[0] + tpl.shape[1] // 2
                        cy = loc[1] + tpl.shape[0] // 2
                        self.cool[name] = time.time()
                        self.ex.push(0, cx, cy, f"popup:{name}")
                        self.count += 1
                        self.say(f"点 {name} {mx:.2f} -> ({cx},{cy})")
                        break
            dt = self.interval - (time.time() - t0)
            if dt > 0:
                time.sleep(dt)


# ---------------------------------------------------------------- 过场/面板
class CutsceneWorker(BaseWorker):
    """只在"没有 HUD"时点 ▶▶ / ✕（否则会点头像开面板，实测死循环 40 次）。"""

    def __init__(self, cap, ex, hz=5.0):
        super().__init__(cap, ex, hz, "cutscene")
        self.skip = [t for n in ("cut_ff2", "cut_ff") if (t := _load(n)) is not None]
        self.close = [t for n in ("hero_close2", "hero_close") if (t := _load(n)) is not None]
        self.hud = _load("task_btn")
        self.cool: dict[str, float] = {}
        self.count = 0

    def run(self):
        while self.running:
            t0 = time.time()
            f = self.frame()
            if f is not None:
                g = cv2.cvtColor(f, cv2.COLOR_BGR2GRAY)
                dark = float((f.max(axis=2) > 8).mean()) < 0.35
                has_hud = False
                if self.hud is not None and self.hud.shape[0] < g.shape[0]:
                    rh = cv2.matchTemplate(g, self.hud, cv2.TM_CCOEFF_NORMED)
                    has_hud = float(rh.max()) > 0.90

                if not has_hud or dark:
                    # 面板 ✕ 优先（面板开着时点击最安全）
                    for tpl in self.close:
                        if self._fire(g, tpl, "close", 2.5):
                            break
                    else:
                        for tpl in self.skip:
                            if self._fire(g, tpl, "skip", 2.0):
                                break
                elif has_hud:
                    # 主界面：只允许点"面板 ✕"（面板会盖住 HUD 的一部分，但任务按钮仍可见）
                    pass
            dt = self.interval - (time.time() - t0)
            if dt > 0:
                time.sleep(dt)

    def _fire(self, g: np.ndarray, tpl: np.ndarray, tag: str, gap: float) -> bool:
        if time.time() - self.cool.get(tag, 0) < gap:
            return False
        if tpl.shape[0] >= g.shape[0] or tpl.shape[1] >= g.shape[1]:
            return False
        res = cv2.matchTemplate(g, tpl, cv2.TM_CCOEFF_NORMED)
        _, mx, _, loc = cv2.minMaxLoc(res)
        if mx < 0.85:
            return False
        cx = loc[0] + tpl.shape[1] // 2
        cy = loc[1] + tpl.shape[0] // 2
        self.cool[tag] = time.time()
        self.ex.push(0, cx, cy, f"{tag}")
        self.count += 1
        self.say(f"{tag} {mx:.2f} -> ({cx},{cy})")
        return True


# ---------------------------------------------------------------- 监控
class MonitorWorker(BaseWorker):
    """血量 / 蓝量 / 等级，超阈值发事件。不点任何东西。"""

    HP_ROI = (824, 2, 62, 12)      # 红条（放大 5x 实测）
    MP_ROI = (824, 14, 62, 12)     # 蓝条
    LV_ROI = (846, 38, 42, 26)     # 等级角标

    def __init__(self, cap, ex, hz=1.0):
        super().__init__(cap, ex, hz, "monitor")
        self.hp = self.mp = None
        self.level = None
        self.events: list[str] = []
        self._last_lv_check = 0.0

    @staticmethod
    def _ratio(f: np.ndarray, roi, lo, hi) -> float | None:  # noqa: D401
        x, y, w, h = roi
        if y + h > f.shape[0] or x + w > f.shape[1]:
            return None
        crop = f[y:y + h, x:x + w]
        hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
        m = cv2.inRange(hsv, np.array(lo), np.array(hi))
        cols = np.where(m.any(axis=0))[0]
        return float(cols.max() + 1) / w if cols.size else 0.0

    def run(self):
        while self.running:
            t0 = time.time()
            f = self.frame()
            if f is not None:
                hp = self._ratio(f, self.HP_ROI, (0, 90, 90), (12, 255, 255))
                mp = self._ratio(f, self.MP_ROI, (100, 90, 90), (130, 255, 255))
                if hp is not None and (self.hp is None or abs(hp - self.hp) > 0.05):
                    self.say(f"HP {hp:.0%}")
                    if hp < 0.3:
                        self.events.append(f"LOW_HP {hp:.0%}")
                        self.say("⚠ 血量低")
                    self.hp = hp
                if mp is not None and (self.mp is None or abs(mp - self.mp) > 0.05):
                    self.say(f"MP {mp:.0%}")
                    self.mp = mp
                # 等级每 15 秒查一次
                if time.time() - self._last_lv_check > 15:
                    self._last_lv_check = time.time()
                    try:
                        from .welfare import read_level_badge
                        from .quest import Eyes
                        # 复用当前帧，不重新抓
                        d = Sense(base=f, viewport=None, hits={})   # type: ignore[arg-type]
                        lv = read_level_badge_raw(f, self.LV_ROI)
                        if lv and lv != self.level:
                            self.say(f"LV {self.level} -> {lv}")
                            self.level = lv
                    except Exception as e:
                        self.say(f"等级读取失败: {e}")
            dt = self.interval - (time.time() - t0)
            if dt > 0:
                time.sleep(dt)


def read_level_badge_raw(frame: np.ndarray, roi) -> int | None:
    x, y, w, h = roi
    crop = frame[y:y + h, x:x + w]
    if crop.size == 0:
        return None
    try:
        from rapidocr_onnxruntime import RapidOCR
        big = cv2.resize(crop, None, fx=4.0, fy=4.0, interpolation=cv2.INTER_CUBIC)
        out = RapidOCR()(big)
    except Exception:
        return None
    if not out or not out[0]:
        return None
    for _b, txt, sc in out[0]:
        d = "".join(ch for ch in txt if ch.isdigit())
        if d and float(sc) > 0.5 and 1 <= int(d) <= 175:
            return int(d)
    return None


# ---------------------------------------------------------------- 主线
class QuestWorker(BaseWorker):
    """主线专用：战斗 / 面板 / 对话选项 / 卡住时点追踪条。"""

    def __init__(self, cap, ex, hz=1.0, stuck_sec: float = 12.0):
        super().__init__(cap, ex, hz, "quest")
        self.stuck_sec = stuck_sec
        self.last_progress = time.time()
        self.count = 0

    def run(self):
        from .quest import Locator
        loc = Locator()
        while self.running:
            t0 = time.time()
            f = self.frame()
            if f is not None:
                hits, _ms = loc.find_all(f)
                st = "MAIN_UI" if "task_btn" in hits else "OTHER"
                if "btn_attack" in hits and "btn_skill" in hits:
                    st = "BATTLE"
                if "btn_attack" in hits:
                    self.ex.push(5, 930, 390, "quest:attack")
                    time.sleep(0.5)
                    self.ex.push(5, 245, 255, "quest:target")
                    self.count += 1
                    self.say("战斗：攻击+点目标")
                    self.last_progress = time.time()
                elif st == "MAIN_UI":
                    idle = time.time() - self.last_progress
                    if idle > self.stuck_sec:
                        box = hits["quest_track"].box if "quest_track" in hits else (760, 134, 190, 64)
                        self.ex.push(5, box[0] + box[2] // 2, box[1] + int(box[3] * 0.72), "quest:track")
                        self.count += 1
                        self.say(f"卡住 {idle:.0f}s → 点追踪条目标行")
                        self.last_progress = time.time()
                elif st == "OTHER":
                    # 面板类：交给 cutscene/popup worker，这里不动
                    pass
            dt = self.interval - (time.time() - t0)
            if dt > 0:
                time.sleep(dt)


# ---------------------------------------------------------------- 编排
@dataclass
class Fleet:
    cap: Capture
    ex: Executor
    workers: list[BaseWorker] = field(default_factory=list)

    @classmethod
    def start(cls, pid: int, fps: float = 8.0, dry: bool = False) -> "Fleet":
        cap = Capture(pid, fps=fps)
        ex = Executor() if not dry else _NullExecutor()
        fleet = cls(cap=cap, ex=ex)
        fleet.workers = [
            PopupWorker(cap, ex),
            CutsceneWorker(cap, ex),
            MonitorWorker(cap, ex),
            QuestWorker(cap, ex),
        ]
        ex.start()
        cap.start()
        for w in fleet.workers:
            w.start()
        return fleet

    def stop(self) -> None:
        for w in self.workers:
            w.running = False
        self.cap.running = False
        self.ex.running = False

    def summary(self) -> dict:
        return {w.name: len(w.log) for w in self.workers}


class _NullExecutor(Executor):
    def run(self):
        while getattr(self, "running", True):
            try:
                _p, _s, a = self.q.get(timeout=0.2)
            except Exception:
                continue
            self.done.append(a)


if __name__ == "__main__":
    import subprocess as sp
    pid = int(sp.run(["powershell", "-NoProfile", "-Command",
                      "(Get-Process MuMuNxDevice | Select-Object -First 1).Id"],
                     capture_output=True, text=True, encoding="utf-8",
                     errors="replace").stdout.strip())
    fleet = Fleet.start(pid)
    print(f"fleet up: pid={pid} workers={[w.name for w in fleet.workers]}")
    try:
        while True:
            time.sleep(10)
            print(f"  summary={fleet.summary()} actions={len(fleet.ex.done)}", flush=True)
    except KeyboardInterrupt:
        fleet.stop()
