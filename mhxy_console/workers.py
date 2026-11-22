"""单一职责 worker 集 —— 一个线程只做一件事。

原则（用户要求，也是踩坑结论）：
    · 不解析任务文本，只认界面类型；
    · 每个 worker 只负责**一个动作**（跳过 / 关闭 / 使用 / 领取 / 自动 / 普攻 / 对话 / 选项 / 追踪 / 血蓝 / 等级）；
    · 所有点击只经 Executor 一个出口，优先级 0=中断 5=主线；
    · 任何 worker 崩了不影响其它 worker。

线程清单（11 个，全部无状态或只存自身阈值状态）：
    skip         ▶▶ 跳过过场（仅无 HUD 时）
    close        ✕ 关闭面板
    use          使用（道具/礼包）
    claim        领取（任务/活动奖励）
    battle_auto  战斗 → 点「自动」
    battle_atk   战斗 → 普攻 + 点目标（无自动按钮时兜底）
    dialog_auto  对话 → 点「自动」
    dialog_opt   对话 → 点选项
    tracker      主线 → 点追踪条（游戏自己寻路）
    hpmp         血/蓝条变化（只读）
    level        等级角标（只读 OCR）
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
    """只提供节拍 + 帧 + 冷却 + 日志；不含任何业务判断。"""

    name_ = "base"
    hz = 5.0
    gap = 2.0

    def __init__(self, cap: Capture, ex: Executor):
        super().__init__(daemon=True, name=self.name_)
        self.cap, self.ex = cap, ex
        self.interval = 1.0 / self.hz
        self.running = True
        self.log: list[str] = []
        self._last = 0.0

    def say(self, msg: str) -> None:
        line = f"[{time.strftime('%H:%M:%S')}] {self.name_:11s} {msg}"
        self.log.append(line)
        print(line, flush=True)

    def frame_gray(self) -> np.ndarray | None:
        f, stamp = self.cap.get()
        if f is None or time.time() - stamp > 1.2:
            return None
        crop = f[40:580, :] if f.shape[0] > 540 else f
        return cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)

    def frame_bgr(self):
        f, stamp = self.cap.get()
        if f is None or time.time() - stamp > 1.2:
            return None
        return f[40:580, :] if f.shape[0] > 540 else f

    def cooled(self) -> bool:
        if time.time() - self._last < self.gap:
            return False
        self._last = time.time()
        return True

    def step(self) -> None:
        raise NotImplementedError

    def run(self) -> None:
        while self.running:
            t0 = time.time()
            try:
                self.step()
            except Exception as e:
                self.say(f"错误: {e}")
            dt = self.interval - (time.time() - t0)
            if dt > 0:
                time.sleep(dt)


# ---------------------------------------------------------------- 共用探测
class Probes:
    def __init__(self):
        self.task = _load("task_btn")
        self.friend = _load("friend_btn")
        self.atk = _load("btn_attack")
        self.skill = _load("btn_skill")
        self.speaker = _load("dlg_speaker")

    def has_hud(self, g) -> bool:
        return _find(g, self.task, 0.90) is not None or _find(g, self.friend, 0.90) is not None

    def in_battle(self, g) -> bool:
        return _find(g, self.atk, 0.82) is not None and _find(g, self.skill, 0.82) is not None

    def in_dialog(self, g) -> bool:
        return _find(g, self.speaker, 0.85) is not None


PROBES: Probes | None = None


def probes() -> Probes:
    global PROBES
    if PROBES is None:
        PROBES = Probes()
    return PROBES


# ---------------------------------------------------------------- 1 跳过过场
class SkipWorker(BaseWorker):
    name_, hz, gap = "skip", 6.0, 2.0

    def __init__(self, cap, ex):
        super().__init__(cap, ex)
        self.tpls = [t for n in ("cut_ff2", "cut_ff", "cut_manual") if (t := _load(n)) is not None]
        self.fixed = (920, 27)

    def step(self) -> None:
        g = self.frame_gray()
        if g is None or probes().has_hud(g) or not self.cooled():
            return
        for tpl in self.tpls:
            hit = _find(g, tpl, 0.85)
            if hit:
                self.ex.push(0, hit[0], hit[1], "skip")
                self.say(f"▶▶ ({hit[0]},{hit[1]})")
                return
        self.ex.push(0, *self.fixed, "skip")
        self.say(f"▶▶ 固定坐标 {self.fixed}")


# ---------------------------------------------------------------- 2 关闭面板
class CloseWorker(BaseWorker):
    name_, hz, gap = "close", 5.0, 2.5

    def __init__(self, cap, ex):
        super().__init__(cap, ex)
        self.tpls = [t for n in ("hero_close2", "hero_close", "panel_close", "panel_close2")
                     if (t := _load(n)) is not None]

    def step(self) -> None:
        g = self.frame_gray()
        if g is None or not self.cooled():
            return
        for tpl in self.tpls:
            hit = _find(g, tpl, 0.88)
            if hit:
                self.ex.push(0, hit[0], hit[1], "close")
                self.say(f"✕ ({hit[0]},{hit[1]})")
                return


# ---------------------------------------------------------------- 3 使用
class UseWorker(BaseWorker):
    name_, hz, gap = "use", 5.0, 2.0

    def __init__(self, cap, ex):
        super().__init__(cap, ex)
        self.tpls = [t for n in ("use_btn", "popup_use") if (t := _load(n)) is not None]

    def step(self) -> None:
        g = self.frame_gray()
        if g is None or not self.cooled():
            return
        for tpl in self.tpls:
            hit = _find(g, tpl, 0.86)
            if hit:
                self.ex.push(0, hit[0], hit[1], "use")
                self.say(f"使用 ({hit[0]},{hit[1]})")
                return


# ---------------------------------------------------------------- 4 领取
class ClaimWorker(BaseWorker):
    name_, hz, gap = "claim", 5.0, 2.5

    def __init__(self, cap, ex):
        super().__init__(cap, ex)
        self.tpl = _load("claim_btn")

    def step(self) -> None:
        g = self.frame_gray()
        if g is None or not self.cooled():
            return
        hit = _find(g, self.tpl, 0.86)
        if hit:
            self.ex.push(0, hit[0], hit[1], "claim")
            self.say(f"领取 ({hit[0]},{hit[1]})")


# ---------------------------------------------------------------- 5 战斗→自动
class BattleAutoWorker(BaseWorker):
    name_, hz, gap = "battle_auto", 2.0, 6.0

    def __init__(self, cap, ex):
        super().__init__(cap, ex)
        self.auto = _load("battle_auto")

    def step(self) -> None:
        g = self.frame_gray()
        if g is None or not probes().in_battle(g) or not self.cooled():
            return
        hit = _find(g, self.auto, 0.85)
        if hit:
            self.ex.push(0, hit[0], hit[1], "battle:auto")
            self.say(f"点自动 ({hit[0]},{hit[1]})")


# ---------------------------------------------------------------- 6 战斗→普攻
class BattleAttackWorker(BaseWorker):
    name_, hz, gap = "battle_atk", 2.0, 2.2

    def __init__(self, cap, ex):
        super().__init__(cap, ex)
        self.auto = _load("battle_auto")

    def step(self) -> None:
        g = self.frame_gray()
        if g is None or not probes().in_battle(g) or not self.cooled():
            return
        if _find(g, self.auto, 0.85):
            return                       # 有自动按钮就交给 battle_auto
        atk = _find(g, probes().atk, 0.82)
        if atk:
            self.ex.push(5, atk[0], atk[1], "battle:attack")
            time.sleep(0.3)
            self.ex.push(5, 245, 255, "battle:target")
            self.say("普攻 + 点目标")


# ---------------------------------------------------------------- 7 对话→自动
class DialogAutoWorker(BaseWorker):
    name_, hz, gap = "dialog_auto", 3.0, 8.0

    def __init__(self, cap, ex):
        super().__init__(cap, ex)
        self.auto = _load("dlg_auto")

    def step(self) -> None:
        g = self.frame_gray()
        if g is None or not probes().in_dialog(g) or not self.cooled():
            return
        hit = _find(g, self.auto, 0.85)
        if hit:
            self.ex.push(0, hit[0], hit[1], "dialog:auto")
            self.say(f"点自动 ({hit[0]},{hit[1]})")


# ---------------------------------------------------------------- 8 对话→选项
class DialogOptionWorker(BaseWorker):
    name_, hz, gap = "dialog_opt", 3.0, 2.5

    def __init__(self, cap, ex):
        super().__init__(cap, ex)
        self.opt = _load("dialog_option")
        self.fixed = (790, 356)

    def step(self) -> None:
        g = self.frame_gray()
        if g is None or not probes().in_dialog(g) or not self.cooled():
            return
        hit = _find(g, self.opt, 0.85)
        if hit:
            self.ex.push(5, hit[0], hit[1], "dialog:option")
            self.say(f"点选项 ({hit[0]},{hit[1]})")
        else:
            self.ex.push(5, *self.fixed, "dialog:option")
            self.say(f"点选项(固定) {self.fixed}")


# ---------------------------------------------------------------- 9 主线→追踪条
class TrackerWorker(BaseWorker):
    name_, hz, gap = "tracker", 0.2, 8.0

    def __init__(self, cap, ex):
        super().__init__(cap, ex)
        self.track = _load("quest_track")

    def step(self) -> None:
        g = self.frame_gray()
        if g is None or not self.cooled():
            return
        if _find(g, probes().task, 0.90) is None:
            return
        if probes().in_battle(g) or probes().in_dialog(g):
            return
        hit = _find(g, self.track, 0.85)
        target = (hit[0], hit[1] + 30) if hit else (855, 180)
        self.ex.push(5, *target, "tracker")
        self.say(f"点追踪条 {target}")


# ---------------------------------------------------------------- 10 血蓝监控
class HpMpWorker(BaseWorker):
    name_, hz, gap = "hpmp", 1.0, 0.0
    HP_ROI = (824, 2, 62, 12)
    MP_ROI = (824, 14, 62, 12)

    def __init__(self, cap, ex):
        super().__init__(cap, ex)
        self.hp = self.mp = None
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
        f = self.frame_bgr()
        if f is None:
            return
        hp = self._bar(f, self.HP_ROI, (0, 90, 90), (12, 255, 255))
        mp = self._bar(f, self.MP_ROI, (100, 90, 90), (130, 255, 255))
        if hp is not None and (self.hp is None or abs(hp - self.hp) > 0.05):
            self.hp = hp
            self.say(f"HP {hp:.0%}")
            if hp < 0.3:
                self.events.append(f"LOW_HP {hp:.0%}")
        if mp is not None and (self.mp is None or abs(mp - self.mp) > 0.05):
            self.mp = mp
            self.say(f"MP {mp:.0%}")


# ---------------------------------------------------------------- 11 等级监控
class LevelWorker(BaseWorker):
    name_, hz, gap = "level", 0.05, 0.0      # 20 秒一次
    LV_ROI = (846, 38, 42, 26)

    def __init__(self, cap, ex):
        super().__init__(cap, ex)
        self.level = None

    def step(self) -> None:
        f = self.frame_bgr()
        if f is None:
            return
        x, y, w, h = self.LV_ROI
        crop = f[y:y + h, x:x + w]
        if crop.size == 0:
            return
        try:
            from rapidocr_onnxruntime import RapidOCR
            big = cv2.resize(crop, None, fx=4, fy=4, interpolation=cv2.INTER_CUBIC)
            out = RapidOCR()(big)
        except Exception:
            return
        if not out or not out[0]:
            return
        for _b, txt, sc in out[0]:
            d = "".join(ch for ch in txt if ch.isdigit())
            if d and float(sc) > 0.5 and 1 <= int(d) <= 175:
                if int(d) != self.level:
                    self.say(f"LV {self.level} -> {int(d)}")
                    self.level = int(d)
                return


# ---------------------------------------------------------------- 编排
WORKER_CLASSES = [
    SkipWorker, CloseWorker, UseWorker, ClaimWorker,
    BattleAutoWorker, BattleAttackWorker,
    DialogAutoWorker, DialogOptionWorker,
    TrackerWorker, HpMpWorker, LevelWorker,
]


@dataclass
class Fleet:
    cap: Capture
    ex: Executor
    workers: list[BaseWorker] = field(default_factory=list)

    @classmethod
    def start(cls, pid: int, fps: float = 8.0) -> "Fleet":
        dpi_aware()
        cap, ex = Capture(pid, fps=fps), Executor()
        probes()                                  # 预热模板
        fleet = cls(cap=cap, ex=ex)
        fleet.workers = [cls_(cap, ex) for cls_ in WORKER_CLASSES]
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
    print("workers:", [w.name for w in fleet.workers])
    try:
        while True:
            time.sleep(10)
            print(f"  {fleet.summary()} actions={len(fleet.ex.done)}", flush=True)
    except KeyboardInterrupt:
        fleet.stop()
