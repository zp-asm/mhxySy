"""6 个职责域 worker（不是按动作拆，是按"一类界面"拆）。

职责域划分（每个线程 = 一类界面的全部处理，内部可以有分支，但不跨域）：
    1 skip     过场/剧情      → ▶▶ 跳过（仅无 HUD 时）
    2 popup    弹窗域         → ✕ 关闭 / 使用 / 领取（都是弹窗上的控件）
    3 battle   战斗域         → 优先「自动」，没有则普攻+点目标
    4 dialog   对话域         → 优先「自动」，否则点第一个选项
    5 tracker  主线域         → 点追踪条，让游戏自己寻路
    6 monitor  监控域         → HP / MP / 等级（只读，不动手）

为什么这样分：
    · 拆到"每个按钮一个线程"会线程爆炸，同步成本 > 收益（血蓝等级就是一个域）；
    · 混成"一个大循环"又会互相阻塞（主线 OCR 时弹窗没人管）；
    · 按界面域拆，每个域内部顺序判断，域间互不阻塞，点击统一走 Executor。
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
    gap = 2.0

    def __init__(self, cap: Capture, ex: Executor):
        super().__init__(daemon=True, name=self.name_)
        self.cap, self.ex = cap, ex
        self.interval = 1.0 / self.hz
        self.running = True
        self.log: list[str] = []
        self._last = 0.0
        self.cool: dict[str, float] = {}

    def say(self, msg: str) -> None:
        line = f"[{time.strftime('%H:%M:%S')}] {self.name_:8s} {msg}"
        self.log.append(line)
        print(line, flush=True)

    def gray(self) -> np.ndarray | None:
        f, stamp = self.cap.get()
        if f is None or time.time() - stamp > 1.2:
            return None
        f = f[40:580, :] if f.shape[0] > 540 else f
        return cv2.cvtColor(f, cv2.COLOR_BGR2GRAY)

    def bgr(self) -> np.ndarray | None:
        f, stamp = self.cap.get()
        if f is None or time.time() - stamp > 1.2:
            return None
        return f[40:580, :] if f.shape[0] > 540 else f

    def ready(self, key: str, gap: float) -> bool:
        if time.time() - self.cool.get(key, 0) < gap:
            return False
        self.cool[key] = time.time()
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
        self.prompt = _load("dlg_prompt")       # 「请选择要做的事」
        self.avatar = _load("hero_avatar")      # 人物属性面板本体
        self.header = _load("panel_header")     # 任务面板本体
        self.hero_x = _load("hero_close")       # 人物属性 ✕
        self.hero_x2 = _load("hero_close2")
        self.panel_x = _load("panel_close")
        self.panel_x2 = _load("panel_close2")

    def panel_open(self, g) -> bool:
        """面板判定：必须面板本体 + ✕ 同时命中。

        只靠 ✕ 会误判（实测主界面 hero_close 误命中 0.911），
        那会让 tracker 永远以为面板开着而不动作。
        """
        if self.avatar is not None and _find(g, self.avatar, 0.85):
            return _find(g, self.hero_x, 0.88) is not None or _find(g, self.hero_x2, 0.88) is not None
        if self.header is not None and _find(g, self.header, 0.85):
            return _find(g, self.panel_x, 0.88) is not None or _find(g, self.panel_x2, 0.88) is not None
        return False

    def has_hud(self, g) -> bool:
        return _find(g, self.task, 0.85) is not None or _find(g, self.friend, 0.90) is not None

    def in_battle(self, g) -> bool:
        return _find(g, self.atk, 0.82) is not None and _find(g, self.skill, 0.82) is not None

    def in_dialog(self, g) -> bool:
        return _find(g, self.speaker, 0.85) is not None or _find(g, self.prompt, 0.85) is not None


P: Probes | None = None


def probes() -> Probes:
    global P
    if P is None:
        P = Probes()
    return P


# ---------------------------------------------------------------- 1 过场
class SkipWorker(BaseWorker):
    name_, hz, gap = "skip", 6.0, 2.0

    def __init__(self, cap, ex):
        super().__init__(cap, ex)
        # 只认"跳过"类按钮（右上 ▶▶）。**不含 cut_manual** —— 那是右下"手动"，
        # 位置在 (921,490)，点它等于逐句推进，实测会点错地方。
        self.tpls = [t for n in ("cut_ff3", "cut_ff2", "cut_ff") if (t := _load(n)) is not None]
        self.fixed = (920, 27)
        self.nohud_streak = 0

    def step(self) -> None:
        g = self.gray()
        if g is None:
            return
        # 面板开着就别跳过（面板 ✕ 与 ▶▶ 位置接近，误点会点头像）
        if probes().panel_open(g):
            self.nohud_streak = 0
            return
        if probes().has_hud(g):
            self.nohud_streak = 0
            return
        # 战斗/对话界面同样没有 HUD，但它们有自己的域，skip 必须让开
        if probes().in_battle(g) or probes().in_dialog(g):
            self.nohud_streak = 0
            return
        self.nohud_streak += 1
        if self.nohud_streak < 2 or not self.ready("s", 4.0):
            return                                  # 连续两帧无 HUD 才动手
        # 只认模板命中（0.90）。曾经有固定坐标兜底，结果在战斗/加载界面
        # 无 HUD 时盲点 (933,29) = 点头像，导致开面板→关面板无限循环。
        for tpl in self.tpls:
            hit = _find(g, tpl, 0.90)
            if hit:
                self.ex.push(0, hit[0], hit[1], "skip")
                self.say(f"▶▶ ({hit[0]},{hit[1]})")
                return


# ---------------------------------------------------------------- 2 弹窗域
class PopupWorker(BaseWorker):
    name_, hz, gap = "popup", 5.0, 2.0

    def __init__(self, cap, ex):
        super().__init__(cap, ex)
        # 关窗要确认面板本体在（只靠 ✕ 会误关战斗/其它界面的关闭按钮）
        self.avatar = _load("hero_avatar")           # 人物属性面板特征
        self.header = _load("panel_header")          # 任务面板「任务」横幅
        self.hero_closes = [t for n in ("hero_close2", "hero_close") if (t := _load(n)) is not None]
        self.panel_closes = [t for n in ("panel_close", "panel_close2") if (t := _load(n)) is not None]
        self.popup_closes = [t for n in ("popup_close",) if (t := _load(n)) is not None]
        self.uses = [t for n in ("use_btn", "claim_btn", "popup_use") if (t := _load(n)) is not None]

    def step(self) -> None:
        g = self.gray()
        if g is None or not self.ready("p", self.gap):
            return
        # 先点"使用/领取"（有奖励就先拿），没有再关窗
        for tpl in self.uses:
            hit = _find(g, tpl, 0.86)
            if hit:
                self.ex.push(0, hit[0], hit[1], "popup:use")
                self.say(f"使用/领取 ({hit[0]},{hit[1]})")
                return
        if self.avatar is not None and _find(g, self.avatar, 0.85):
            for tpl in self.hero_closes:
                hit = _find(g, tpl, 0.88)
                if hit:
                    self.ex.push(0, hit[0], hit[1], "popup:close-hero")
                    self.say(f"✕ 人物属性 ({hit[0]},{hit[1]})")
                    return
        # 注意：**不要关任务面板** —— 那是 tracker 域的工作面板，
        # 关掉会造成"开面板 ↔ 关面板"死循环（实测每 14 秒一轮）。
        for tpl in self.popup_closes:
            hit = _find(g, tpl, 0.88)
            if hit:
                self.ex.push(0, hit[0], hit[1], "popup:close")
                self.say(f"✕ 弹窗 ({hit[0]},{hit[1]})")
                return


# ---------------------------------------------------------------- 3 战斗域
class BattleWorker(BaseWorker):
    name_, hz, gap = "battle", 2.0, 2.5

    def __init__(self, cap, ex):
        super().__init__(cap, ex)
        self.auto = _load("battle_auto")

    def step(self) -> None:
        g = self.gray()
        if g is None or not probes().in_battle(g) or not self.ready("b", self.gap):
            return
        hit = _find(g, self.auto, 0.85)
        if hit:
            self.ex.push(0, hit[0], hit[1], "battle:auto")
            self.say(f"自动 ({hit[0]},{hit[1]})")
            return
        atk = _find(g, probes().atk, 0.82)
        if atk:
            self.ex.push(5, atk[0], atk[1], "battle:attack")
            time.sleep(0.3)
            self.ex.push(5, 245, 255, "battle:target")
            self.say("普攻 + 点目标")


# ---------------------------------------------------------------- 4 对话域
class DialogWorker(BaseWorker):
    name_, hz, gap = "dialog", 3.0, 3.0

    PROMPT_DY = 48          # 选项按钮相对「请选择要做的事」标题的纵向偏移（实测）

    def __init__(self, cap, ex):
        super().__init__(cap, ex)
        self.auto = _load("dlg_auto")
        self.prompt = _load("dlg_prompt")

    def step(self) -> None:
        g = self.gray()
        if g is None or not probes().in_dialog(g) or not self.ready("d", self.gap):
            return
        # ① 有「自动」按钮 → 点它（对话自动推进）
        hit = _find(g, self.auto, 0.85)
        if hit:
            self.ex.push(0, hit[0], hit[1], "dialog:auto")
            self.say(f"自动 ({hit[0]},{hit[1]})")
            return
        # ② 有「请选择要做的事」标题 → 点标题正下方的选项（不依赖选项文字）
        pr = _find(g, self.prompt, 0.85)
        if pr:
            self.ex.push(5, pr[0], pr[1] + self.PROMPT_DY, "dialog:option")
            self.say(f"选项 ({pr[0]},{pr[1] + self.PROMPT_DY})")


# ---------------------------------------------------------------- 5 主线域
class TrackerWorker(BaseWorker):
    """主线域：只要在主界面就点追踪条的目标行，让游戏自己寻路。

    不再依赖 quest_track 模板 —— 追踪条里是**任务文字**，文字一变模板就失效
    （实测换成"打败老鼠精"后匹配度 0.000）。位置是固定的，直接点。
    """

    name_, hz, gap = "tracker", 0.2, 12.0
    TASK_BTN = (823, 96)             # 「任务」按钮（开面板）
    TELEPORT = (756, 436)            # 面板里的「马上传送」

    def __init__(self, cap, ex):
        super().__init__(cap, ex)
        self.tele_tpl = _load("panel_teleport")

    def step(self) -> None:
        g = self.gray()
        if g is None:
            return
        panel_open = probes().panel_open(g)

        # ① 面板开着：有「马上传送」就点它（主线推进的主力动作）
        if panel_open:
            hit = _find(g, self.tele_tpl, 0.85)
            if hit and self.ready("tele", 6.0):
                self.ex.push(5, hit[0], hit[1], "quest:teleport")
                self.say(f"面板 → 马上传送 ({hit[0]},{hit[1]})")
            return

        # ② 主界面：开任务面板（冷却 12 s，避免反复开关）
        if not probes().has_hud(g):
            return
        if probes().in_battle(g) or probes().in_dialog(g):
            return
        if self.ready("open", self.gap):
            self.ex.push(5, *self.TASK_BTN, "quest:open-task")
            self.say(f"打开任务面板 {self.TASK_BTN}")


# ---------------------------------------------------------------- 6 监控域
class MonitorWorker(BaseWorker):
    """只读：血 / 蓝 / 等级。三件事同域（都是"看自己状态"）。"""

    name_, hz, gap = "monitor", 1.0, 0.0
    HP_ROI = (824, 2, 62, 12)
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
        f = self.bgr()
        if f is None:
            return
        g = cv2.cvtColor(f, cv2.COLOR_BGR2GRAY)
        if not probes().has_hud(g) or probes().panel_open(g):
            return                                   # 面板/过场遮挡时读数不可信
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
            lv = self._ocr_level(f)
            if lv and lv != self.level:
                self.say(f"LV {self.level} -> {lv}")
                self.level = lv

    def _ocr_level(self, f: np.ndarray) -> int | None:
        x, y, w, h = self.LV_ROI
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


# ---------------------------------------------------------------- 编排
WORKER_CLASSES = [SkipWorker, PopupWorker, BattleWorker, DialogWorker, TrackerWorker, MonitorWorker]


@dataclass
class Fleet:
    cap: Capture
    ex: Executor
    workers: list[BaseWorker] = field(default_factory=list)

    @classmethod
    def start(cls, pid: int, fps: float = 8.0) -> "Fleet":
        dpi_aware()
        cap, ex = Capture(pid, fps=fps), Executor()
        probes()
        fleet = cls(cap=cap, ex=ex)
        fleet.workers = [c(cap, ex) for c in WORKER_CLASSES]
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
