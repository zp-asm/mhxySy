"""六路 worker：一个线程只干一件事，互不阻塞，共用一个点击出口。

    Capture          8 Hz 抓帧（只留最新帧，不排队）
    Executor         唯一点击出口（优先级 0 中断 / 5 主线；>1.5s 过期丢弃）

    SkipWorker       ▶▶ 跳过剧情        —— 只在"没有 HUD"时动作（防误点头像）
    PanelCloseWorker ✕ 关闭面板         —— 人物属性/福利/任务面板…
    PopupUseWorker   使用 / 领取        —— 弹窗里的可点按钮
    BattleWorker     攻击 + 点目标      —— 战斗中
    MonitorWorker    HP / MP / 等级     —— 只读，不动手
    QuestWorker      追踪条 / 任务面板  —— 主线推进

为什么必须拆（都是实测踩出来的）：
    ① 主线一次 OCR 0.5~1.5 s，期间弹窗/过场全漏；
    ② 多线程各自 adb_tap 会互相插队 → 点击统一走 Executor；
    ③ ▶▶ 模板在主界面头像区也会命中 → SkipWorker 必须有 HUD 门控，
       否则\"点头像开面板 → 关面板\"死循环（实测 40 次）。
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np

from .pipeline import Capture, Executor
from .win import dpi_aware

TEMPLATES = Path("templates")


def _load(name: str) -> np.ndarray | None:
    p = TEMPLATES / f"{name}.png"
    return cv2.imread(str(p), cv2.IMREAD_GRAYSCALE) if p.exists() else None


def _find(g: np.ndarray, tpl: np.ndarray | None, th: float) -> tuple[int, int, float] | None:
    if tpl is None or tpl.shape[0] >= g.shape[0] or tpl.shape[1] >= g.shape[1]:
        return None
    res = cv2.matchTemplate(g, tpl, cv2.TM_CCOEFF_NORMED)
    _, mx, _, loc = cv2.minMaxLoc(res)
    if mx < th:
        return None
    return loc[0] + tpl.shape[1] // 2, loc[1] + tpl.shape[0] // 2, float(mx)


class BaseWorker(threading.Thread):
    name_ = "base"
    hz = 5.0

    def __init__(self, cap: Capture, ex: Executor):
        super().__init__(daemon=True, name=self.name_)
        self.cap, self.ex = cap, ex
        self.interval = 1.0 / self.hz
        self.running = True
        self.log: list[str] = []
        self.cool: dict[str, float] = {}

    def say(self, msg: str) -> None:
        line = f"[{time.strftime('%H:%M:%S')}] {self.name_:6s} {msg}"
        self.log.append(line)
        print(line, flush=True)

    def frame(self) -> np.ndarray | None:
        f, stamp = self.cap.get()
        if f is None or time.time() - stamp > 1.2:
            return None
        return f[40:580, :] if f.shape[0] > 540 else f

    def ready(self, key: str, gap: float) -> bool:
        if time.time() - self.cool.get(key, 0) < gap:
            return False
        self.cool[key] = time.time()
        return True

    # ---- 子类实现 step()；loop() 负责节拍与异常兜底
    def step(self) -> None:
        raise NotImplementedError

    def run(self) -> None:
        while self.running:
            t0 = time.time()
            try:
                self.step()
            except Exception as e:          # 单个 worker 崩了不影响别人
                self.say(f"错误: {e}")
            dt = self.interval - (time.time() - t0)
            if dt > 0:
                time.sleep(dt)


class HudProbe:
    """\"有没有 HUD\"：主界面必有任务/好友按钮。"""

    def __init__(self):
        self.tpls = [t for n in ("task_btn", "friend_btn") if (t := _load(n)) is not None]

    def has_hud(self, g: np.ndarray) -> bool:
        return any(_find(g, t, 0.90) is not None for t in self.tpls)


# ---------------------------------------------------------------- 1 剧情跳过
class SkipWorker(BaseWorker):
    name_, hz = "skip", 6.0

    def __init__(self, cap, ex, hud: HudProbe):
        super().__init__(cap, ex)
        self.hud = hud
        self.tpls = [t for n in ("cut_ff2", "cut_ff", "cut_manual") if (t := _load(n)) is not None]
        self.fixed = (920, 27)
        self.count = 0

    def step(self) -> None:
        f = self.frame()
        if f is None:
            return
        g = cv2.cvtColor(f, cv2.COLOR_BGR2GRAY)
        if self.hud.has_hud(g):
            return                                  # 主界面绝不点
        for tpl in self.tpls:
            hit = _find(g, tpl, 0.85)
            if hit and self.ready("skip", 2.0):
                self.ex.push(0, hit[0], hit[1], "skip")
                self.count += 1
                self.say(f"▶▶ 跳过 {hit[2]:.2f} ({hit[0]},{hit[1]})")
                return
        if self.ready("skip-fixed", 2.0):
            self.ex.push(0, *self.fixed, "skip-fixed")
            self.count += 1
            self.say(f"▶▶ 跳过(固定坐标) {self.fixed}")


# ---------------------------------------------------------------- 2 面板关闭
class PanelCloseWorker(BaseWorker):
    name_, hz = "close", 5.0

    def __init__(self, cap, ex):
        super().__init__(cap, ex)
        self.tpls = [t for n in ("hero_close2", "hero_close", "panel_close", "panel_close2")
                     if (t := _load(n)) is not None]
        self.count = 0

    def step(self) -> None:
        f = self.frame()
        if f is None:
            return
        g = cv2.cvtColor(f, cv2.COLOR_BGR2GRAY)
        for tpl in self.tpls:
            hit = _find(g, tpl, 0.88)
            if hit and self.ready("close", 2.5):
                self.ex.push(0, hit[0], hit[1], "close")
                self.count += 1
                self.say(f"✕ 关面板 {hit[2]:.2f} ({hit[0]},{hit[1]})")
                return


# ---------------------------------------------------------------- 3 弹窗使用
class PopupUseWorker(BaseWorker):
    name_, hz = "use", 5.0

    def __init__(self, cap, ex):
        super().__init__(cap, ex)
        self.tpls = [t for n in ("use_btn", "claim_btn", "popup_use") if (t := _load(n)) is not None]
        self.count = 0

    def step(self) -> None:
        f = self.frame()
        if f is None:
            return
        g = cv2.cvtColor(f, cv2.COLOR_BGR2GRAY)
        for tpl in self.tpls:
            hit = _find(g, tpl, 0.86)
            if hit and self.ready("use", 2.0):
                self.ex.push(0, hit[0], hit[1], "use")
                self.count += 1
                self.say(f"使用/领取 {hit[2]:.2f} ({hit[0]},{hit[1]})")
                return


# ---------------------------------------------------------------- 4 战斗
class BattleWorker(BaseWorker):
    name_, hz = "battle", 2.0

    def __init__(self, cap, ex):
        super().__init__(cap, ex)
        self.atk = _load("btn_attack")
        self.skill = _load("btn_skill")
        self.count = 0

    def step(self) -> None:
        f = self.frame()
        if f is None:
            return
        g = cv2.cvtColor(f, cv2.COLOR_BGR2GRAY)
        a = _find(g, self.atk, 0.85)
        s = _find(g, self.skill, 0.85)
        if not (a and s):
            return
        if self.ready("battle", 2.0):
            self.ex.push(5, a[0], a[1], "battle:attack")
            time.sleep(0.4)
            self.ex.push(5, 245, 255, "battle:target")
            self.count += 1
            self.say("攻击 + 点目标")


# ---------------------------------------------------------------- 5 监控
class MonitorWorker(BaseWorker):
    name_, hz = "monitor", 1.0
    HP_ROI = (824, 2, 62, 12)        # 5x 放大实测
    MP_ROI = (824, 14, 62, 12)
    LV_ROI = (846, 38, 42, 26)

    def __init__(self, cap, ex):
        super().__init__(cap, ex)
        self.hp = self.mp = self.level = None
        self.events: list[str] = []

    @staticmethod
    def _bar(f, roi, lo, hi) -> float | None:
        x, y, w, h = roi
        if y + h > f.shape[0] or x + w > f.shape[1]:
            return None
        hsv = cv2.cvtColor(f[y:y + h, x:x + w], cv2.COLOR_BGR2HSV)
        m = cv2.inRange(hsv, np.array(lo), np.array(hi))
        cols = np.where(m.any(axis=0))[0]
        return float(cols.max() + 1) / w if cols.size else 0.0

    def step(self) -> None:
        f = self.frame()
        if f is None:
            return
        hp = self._bar(f, self.HP_ROI, (0, 90, 90), (12, 255, 255))
        mp = self._bar(f, self.MP_ROI, (100, 90, 90), (130, 255, 255))
        if hp is not None and (self.hp is None or abs(hp - self.hp) > 0.05):
            self.hp = hp
            self.say(f"HP {hp:.0%}")
            if hp < 0.3:
                self.events.append(f"LOW_HP {hp:.0%}")
                self.say("⚠ 血量低")
        if mp is not None and (self.mp is None or abs(mp - self.mp) > 0.05):
            self.mp = mp
            self.say(f"MP {mp:.0%}")
        if self.ready("lv", 20.0):
            lv = _ocr_level(f, self.LV_ROI)
            if lv and lv != self.level:
                self.say(f"LV {self.level} -> {lv}")
                self.level = lv


def _ocr_level(f: np.ndarray, roi) -> int | None:
    x, y, w, h = roi
    crop = f[y:y + h, x:x + w]
    if crop.size == 0:
        return None
    try:
        from rapidocr_onnxruntime import RapidOCR
        big = cv2.resize(crop, None, fx=4, fy=4, interpolation=cv2.INTER_CUBIC)
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


# ---------------------------------------------------------------- 6 主线
class QuestWorker(BaseWorker):
    name_, hz = "quest", 1.0

    def __init__(self, cap, ex, stuck_sec: float = 12.0):
        super().__init__(cap, ex)
        self.track = _load("quest_track")
        self.task = _load("task_btn")
        self.stuck_sec = stuck_sec
        self.last = time.time()
        self.count = 0

    def step(self) -> None:
        f = self.frame()
        if f is None:
            return
        g = cv2.cvtColor(f, cv2.COLOR_BGR2GRAY)
        task = _find(g, self.task, 0.90)
        if task is None:
            return                                  # 不在主界面，主线不动作
        idle = time.time() - self.last
        if idle < self.stuck_sec:
            return
        hit = _find(g, self.track, 0.85)
        if hit:
            self.ex.push(5, hit[0], hit[1] + 30, "quest:track")
            self.say(f"卡住 {idle:.0f}s → 点追踪条目标行 ({hit[0]},{hit[1] + 30})")
        else:
            self.ex.push(5, task[0], task[1], "quest:open-task")
            self.say(f"卡住 {idle:.0f}s → 打开任务面板")
        self.count += 1
        self.last = time.time()


# ---------------------------------------------------------------- 编排
@dataclass
class Fleet:
    cap: Capture
    ex: Executor
    workers: list[BaseWorker] = field(default_factory=list)

    @classmethod
    def start(cls, pid: int, fps: float = 8.0) -> "Fleet":
        dpi_aware()
        cap = Capture(pid, fps=fps)
        ex = Executor()
        hud = HudProbe()
        fleet = cls(cap=cap, ex=ex)
        fleet.workers = [
            SkipWorker(cap, ex, hud),
            PanelCloseWorker(cap, ex),
            PopupUseWorker(cap, ex),
            BattleWorker(cap, ex),
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


if __name__ == "__main__":
    import subprocess as sp
    pid = int(sp.run(["powershell", "-NoProfile", "-Command",
                      "(Get-Process MuMuNxDevice | Select-Object -First 1).Id"],
                     capture_output=True, text=True, encoding="utf-8",
                     errors="replace").stdout.strip())
    fleet = Fleet.start(pid)
    print("fleet:", [w.name for w in fleet.workers])
    try:
        while True:
            time.sleep(10)
            print(f"  {fleet.summary()} actions={len(fleet.ex.done)}", flush=True)
    except KeyboardInterrupt:
        fleet.stop()
