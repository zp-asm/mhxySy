"""主线任务状态机 v0（我们自己的实现）。

数据流：
    抓帧(4~8ms) → 贴底视口(960x540) → 锚点匹配(ROI, 每锚点<1ms) → 状态判定
                                                     ↓
                                         动作：tap(adb) / key(PostMessage)

坐标系约定（重要）：
    所有模板、ROI、点击坐标都在 **基准视口坐标 960x540** 里，和 adb 的设备坐标 1:1 重合，
    所以点击不需要任何换算；换机器只要视口标定对，坐标就跟着对。

状态（v0 只做主线需要的四个）：
    MAIN_UI    主界面（任务按钮 + 任务追踪条都在）
    TASK_PANEL 任务面板打开（任务追踪条消失 + 面板特征）
    BATTLE     战斗中（技能盘放大）—— 待补模板
    UNKNOWN    兜底
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np

from .win import FrameSource, dpi_aware
from . import viewport as V

TPL_DIR = Path("templates")
ADB, SERIAL = "adb", "127.0.0.1:16384"

# 安全闸门：默认只读。任何输入动作都必须显式打开（--enable-actions 或 enable_actions()）
ACTIONS_ENABLED = False


class ActionsDisabled(RuntimeError):
    pass


def enable_actions(flag: bool = True) -> None:
    global ACTIONS_ENABLED
    ACTIONS_ENABLED = flag

# 锚点清单：名字 -> (默认阈值, 默认 ROI 外扩)
# 任务面板锚点（面板打开时才用；优先级高于主界面锚点）
PANEL_ANCHORS: dict[str, tuple[float, int]] = {
    "top_map":     (0.85, 30),
    "mall_btn":    (0.88, 30),
    "event_btn":   (0.88, 30),
    "task_btn":    (0.90, 40),
    "team_btn":    (0.90, 40),
    "quest_track": (0.88, 16),
    "bag_btn":     (0.90, 36),
    "friend_btn":  (0.88, 36),
}

# 剧情过场（黑屏 + 字幕 + 手动/快进）
CUTSCENE_ANCHORS: dict[str, tuple[float, int]] = {
    "cut_manual":   (0.85, 20),
    "cut_ff":       (0.85, 16),
    "cut_skip":     (0.85, 16),
    "cut_subtitle": (0.72, 8),
    "cut_ff2":      (0.85, 16),
}

# NPC 对话（右下「自动」+ 右上 ▶▶ + 说话人铭牌 + 正文）
DIALOG_ANCHORS: dict[str, tuple[float, int]] = {
    "dlg_auto":    (0.88, 20),
    "dlg_ff":      (0.85, 16),
    "dlg_speaker": (0.85, 16),
    "dlg_text":    (0.70, 8),
}

# 弹窗（新手礼包等）：出现就点「使用」，没使用就点 ✕
POPUP_ANCHORS: dict[str, tuple[float, int]] = {
    "popup_use":   (0.85, 20),
    "popup_close": (0.86, 20),
    "popup_title": (0.82, 16),
}

# 人物属性面板（✕ + 头像）
HERO_ANCHORS: dict[str, tuple[float, int]] = {
    "hero_close":  (0.88, 20),
    "hero_avatar": (0.85, 30),
    "hero_close2": (0.88, 18),
}

# 这 4 个是在"面板打开"的帧里采的，纹理其实是面板边缘 → 面板关闭后必须重采
STALE_ANCHORS = {"task_btn", "team_btn", "quest_track", "bag_btn",
                 "mall_btn", "event_btn", "top_map", "coord_text"}

ANCHORS: dict[str, tuple[float, int]] = {
    "task_btn":    (0.90, 70),
    "team_btn":    (0.90, 70),
    "quest_track": (0.88, 24),
    "bag_btn":     (0.90, 60),
    "friend_btn":  (0.88, 60),
    "skill_btn":   (0.86, 60),
    "top_map":     (0.85, 40),
    "coord_text":  (0.85, 40),
    "chat_area":   (0.80, 20),
    "mall_btn":    (0.88, 50),
    "event_btn":   (0.88, 50),
}


@dataclass
class Hit:
    name: str
    score: float
    box: tuple[int, int, int, int]      # 命中框（视口坐标）

    @property
    def center(self) -> tuple[int, int]:
        x, y, w, h = self.box
        return x + w // 2, y + h // 2


@dataclass
class Sense:
    base: np.ndarray
    viewport: V.Viewport
    hits: dict[str, Hit] = field(default_factory=dict)
    capture_ms: float = 0.0
    match_ms: float = 0.0

    # ---------- 便捷查询 ----------
    def has(self, name: str) -> bool:
        return name in self.hits

    def score(self, name: str) -> float:
        return self.hits[name].score if name in self.hits else 0.0

    @property
    def state(self) -> str:
        # 过场优先：黑屏字幕的状态下别的锚点都会失效
        if self.has("popup_use") or self.has("popup_close"):
            return "POPUP"
        if self.has("hero_close") or self.has("hero_close2"):
            return "HERO_PANEL"
        if self.has("cut_ff") or self.has("cut_ff2"):
            return "CUTSCENE"
        if self.has("dlg_auto") or (self.has("dlg_speaker") and self.has("dlg_ff")):
            return "DIALOG"
        # 面板优先：面板打开时右侧按钮全被遮住，主界面锚点不可信
        if any(k in self.hits for k in ("panel_close", "panel_close2", "panel_header")):
            return "TASK_PANEL"
        if self.has("task_btn"):
            return "MAIN_UI"
        return "UNKNOWN"

    @property
    def panel_title_roi(self) -> tuple[int, int, int, int]:
        return (388, 88, 412, 110)      # 标题 + 目标（大字号，OCR 最稳）

    def summary(self) -> str:
        parts = [f"{n}={h.score:.3f}" for n, h in sorted(self.hits.items())]
        return f"state={self.state}  cap={self.capture_ms:.1f}ms match={self.match_ms:.1f}ms\n  " + \
               "  ".join(parts)


class Locator:
    """锚点模板 + ROI 缓存。首次加载时读 templates/*.png 与同名 .json。"""

    def __init__(self, tpl_dir: Path = TPL_DIR):
        self.dir = tpl_dir
        self.items: dict[str, tuple[np.ndarray, tuple[int, int, int, int], float, int]] = {}
        merged = dict(ANCHORS)
        merged.update(PANEL_ANCHORS)
        merged.update(CUTSCENE_ANCHORS)
        merged.update(DIALOG_ANCHORS)
        merged.update(POPUP_ANCHORS)
        merged.update(HERO_ANCHORS)
        for name, (thresh, pad) in merged.items():
            png = self.dir / f"{name}.png"
            if not png.exists():
                continue
            img = cv2.imread(str(png), cv2.IMREAD_COLOR)
            if img is None:
                continue
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            cfg_p = self.dir / f"{name}.json"
            box = (0, 0, 1, 1)
            if cfg_p.exists():
                cfg = json.loads(cfg_p.read_text(encoding="utf-8"))
                box = tuple(cfg.get("box", box))          # type: ignore[assignment]
                pad = int(cfg.get("roi_pad", pad))
                thresh = float(cfg.get("thresh", thresh))
            self.items[name] = (gray, box, thresh, pad)

    def find_all(self, base: np.ndarray) -> tuple[dict[str, Hit], float]:
        t0 = time.perf_counter()
        g = cv2.cvtColor(base, cv2.COLOR_BGR2GRAY)
        H, W = g.shape[:2]
        hits: dict[str, Hit] = {}
        for name, (tpl, box, thresh, pad) in self.items.items():
            bx, by, bw, bh = box
            x0 = max(0, bx - pad)
            y0 = max(0, by - pad)
            x1 = min(W, bx + bw + pad)
            y1 = min(H, by + bh + pad)
            roi = g[y0:y1, x0:x1]
            if roi.shape[0] < tpl.shape[0] or roi.shape[1] < tpl.shape[1]:
                continue
            res = cv2.matchTemplate(roi, tpl, cv2.TM_CCOEFF_NORMED)
            _, mx, _, loc = cv2.minMaxLoc(res)
            if mx >= thresh:
                hits[name] = Hit(name, float(mx), (x0 + loc[0], y0 + loc[1],
                                                  tpl.shape[1], tpl.shape[0]))
        return hits, (time.perf_counter() - t0) * 1000


class Eyes:
    """抓帧 + 归一化 + 定位，一次 tick 给出 Sense。"""

    def __init__(self, pid: int | None = None, locator: Locator | None = None):
        dpi_aware()
        self.pid = pid or mumu_pid()
        self.src = FrameSource(self.pid)
        self.loc = locator or Locator()

    def tick(self) -> Sense:
        f = self.src.grab()
        vp = V.detect(f.image, templates=None)          # 贴底几何定位
        base = V.crop_normalize(f.image, vp)
        hits, match_ms = self.loc.find_all(base)
        return Sense(base=base, viewport=vp, hits=hits,
                     capture_ms=f.cost_ms, match_ms=match_ms)


# ------------------------------------------------------------------ 动作
def mumu_pid() -> int:
    out = subprocess.run(
        ["powershell", "-NoProfile", "-Command",
         "(Get-Process MuMuNxDevice | Select-Object -First 1).Id"],
        capture_output=True, text=True, encoding="utf-8", errors="replace").stdout.strip()
    return int(out)


def adb_tap(x: int, y: int) -> float:
    """视口坐标 → 设备坐标 1:1，直接点。返回耗时 ms。默认禁止。"""
    if not ACTIONS_ENABLED:
        raise ActionsDisabled(f"adb_tap({x},{y}) 被拦截：未授权动作（加 --enable-actions）")
    t0 = time.perf_counter()
    subprocess.run([ADB, "-s", SERIAL, "shell", "input", "tap", str(int(x)), str(int(y))],
                   capture_output=True, timeout=20)
    return (time.perf_counter() - t0) * 1000


def post_key(vk: int, hwnd: int | None = None) -> None:
    """后台按键（实测有效，不抢前台）。默认禁止。"""
    if not ACTIONS_ENABLED:
        raise ActionsDisabled(f"post_key(0x{vk:x}) 被拦截：未授权动作（加 --enable-actions）")
    import ctypes
    from ctypes import wintypes as wt
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.PostMessageW.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM]
    if hwnd is None:
        hwnd = FrameSource(mumu_pid()).refresh_target().hwnd
    user32.PostMessageW(hwnd, 0x0100, vk, 0x000E0001)
    time.sleep(0.05)
    user32.PostMessageW(hwnd, 0x0101, vk, 0xC00E0001)


def read_tracker(sense: Sense, engine: str = "rapid") -> list[str]:
    """读右侧主线追踪条（按需调用，RapidOCR 单次约 1.3s）。"""
    x, y, w, h = ANCHORS["quest_track"][1], 0, 0, 0   # 占位，下面用命中框
    hit = sense.hits.get("quest_track")
    crop = sense.base[132:180, 760:958] if not hit else \
        sense.base[hit.box[1]:hit.box[1] + hit.box[3], hit.box[0]:hit.box[0] + hit.box[2]]
    if engine == "rapid":
        try:
            from rapidocr_onnxruntime import RapidOCR
            out = RapidOCR()(crop)
            return [t[1] for t in (out[0] or [])]
        except ImportError:
            return []
    return []


def read_panel(sense: Sense) -> dict[str, str]:
    """读任务面板：标题 / 目标。大字号，RapidOCR 稳定（实测 0.97~0.99）。"""
    x, y, w, h = sense.panel_title_roi
    crop = sense.base[y:y + h, x:x + w]
    out: dict[str, str] = {}
    try:
        from rapidocr_onnxruntime import RapidOCR
        big = cv2.resize(crop, None, fx=1.6, fy=1.6, interpolation=cv2.INTER_CUBIC)
        res = RapidOCR()(big)
        lines = [t[1] for t in (res[0] or [])] if res else []
    except ImportError:
        lines = []
    for ln in lines:
        if "主线-" in ln or ("主线" in ln and "剧情" not in ln):
            out.setdefault("title", ln)
        elif out.get("title") and "goal" not in out and "目标" not in ln:
            out.setdefault("goal", ln)
        elif "目标" in ln:
            out["goal_marker"] = ln
    out["lines"] = " | ".join(lines)
    return out


def popup_use(sense: Sense) -> float:
    """点弹窗的「使用」（新手礼包等）。"""
    hit = sense.hits.get("popup_use") or sense.hits.get("popup_close")
    if not hit:
        raise RuntimeError("没有弹窗")
    cx, cy = hit.center
    return adb_tap(cx, cy)


def dialog_auto(sense: Sense) -> float:
    """点右下「自动」，让 NPC 对白自动推进（挂机首选）。"""
    hit = sense.hits.get("dlg_auto")
    if not hit:
        raise RuntimeError("不在对话界面")
    cx, cy = hit.center
    return adb_tap(cx, cy)


def dialog_advance(sense: Sense) -> float:
    """点右上 ▶▶ 快进/推进对白。"""
    hit = sense.hits.get("dlg_ff")
    if not hit:
        raise RuntimeError("找不到快进按钮")
    cx, cy = hit.center
    return adb_tap(cx, cy)


def cutscene_next(sense: Sense, use_ff: bool = True) -> float:
    """推进剧情：优先点右上快进 ▶▶，没有就点右下「手动」。"""
    key = "cut_ff" if use_ff and "cut_ff" in sense.hits else "cut_manual"
    hit = sense.hits.get(key)
    if not hit:
        raise RuntimeError("不在剧情过场里")
    cx, cy = hit.center
    return adb_tap(cx, cy)


def find_text(sense: Sense, needle: str, region: tuple[int, int, int, int] | None = None,
              scale: float = 2.0) -> tuple[int, int, tuple[int, int, int, int]] | None:
    """在画面里 OCR 找一段文字，返回 (中心x, 中心y, bbox)。用于面板这种"位置随页签漂移"的 UI。"""
    x0, y0, x1, y1 = region or (60, 20, 900, 500)
    crop = sense.base[y0:y1, x0:x1]
    try:
        from rapidocr_onnxruntime import RapidOCR
        big = cv2.resize(crop, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
        out = RapidOCR()(big)
    except Exception:
        return None
    if not out or not out[0]:
        return None
    for box, txt, score in out[0]:
        if needle in txt:
            xs = [p[0] / scale + x0 for p in box]
            ys = [p[1] / scale + y0 for p in box]
            bx, by = int(min(xs)), int(min(ys))
            bw, bh = int(max(xs) - min(xs)), int(max(ys) - min(ys))
            return (bx + bw // 2, by + bh // 2, (bx, by, bw, bh))
    return None


def click_text(sense: Sense, needle: str, region=None) -> tuple[float, tuple[int, int]]:
    hit = find_text(sense, needle, region)
    if not hit:
        raise RuntimeError(f"画面里找不到文字: {needle}")
    cx, cy, _ = hit
    return adb_tap(cx, cy), (cx, cy)


def panel_goto_main(sense: Sense) -> float:
    """点「主线剧情(1)」页签 —— 面板可能停在 导引/日常 等其它页。"""
    hit = sense.hits.get("panel_tab_main")
    if not hit:
        raise RuntimeError("找不到「主线剧情」页签")
    cx, cy = hit.center
    return adb_tap(cx, cy)


def panel_teleport(sense: Sense) -> float:
    """点任务面板的「马上传送」（主线推进的主力动作）。"""
    hit = sense.hits.get("panel_teleport")
    if not hit:
        raise RuntimeError("面板未打开，找不到 马上传送")
    cx, cy = hit.center
    return adb_tap(cx, cy)


def panel_close(sense: Sense) -> float:
    hit = sense.hits.get("panel_close")
    if not hit:
        raise RuntimeError("面板未打开，找不到 关闭")
    cx, cy = hit.center
    return adb_tap(cx, cy)


# ------------------------------------------------------------------ CLI
def main(argv: list[str]) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    cmd = argv[1] if len(argv) > 1 else "sense"
    if "--enable-actions" in argv:
        enable_actions(True)
        print("⚠ 已授权输入动作（--enable-actions）")
    eyes = Eyes()

    if cmd == "sense":
        s = eyes.tick()
        print(s.summary())
        if "--ocr" in argv:
            t0 = time.perf_counter()
            lines = read_tracker(s)
            print(f"  追踪条 OCR({(time.perf_counter()-t0)*1000:.0f} ms): {lines}")
        cv2.imwrite("E:/out/sense_base.png", s.base)
        return 0

    if cmd == "open-task":
        s = eyes.tick()
        print("before:", s.state)
        if not s.has("task_btn"):
            print("  没找到任务按钮，放弃")
            return 2
        cx, cy = s.hits["task_btn"].center
        cost = adb_tap(cx, cy)
        print(f"  tap({cx},{cy})  {cost:.0f} ms")
        time.sleep(0.8)
        s2 = eyes.tick()
        print("after :", s2.state)
        print("  ", s2.summary())
        cv2.imwrite("E:/out/after_open_task.png", s2.base)
        return 0

    if cmd == "next":
        s = eyes.tick()
        if s.state != "CUTSCENE":
            print(f"  当前状态 {s.state}，不是剧情过场")
            return 2
        cx, cy = (s.hits["cut_ff"] if "cut_ff" in s.hits else s.hits["cut_manual"]).center
        cost = cutscene_next(s)
        print(f"  tap({cx},{cy})  推进剧情  {cost:.0f} ms")
        return 0

    if cmd == "teleport":
        s = eyes.tick()
        if s.state != "TASK_PANEL":
            print(f"  当前状态 {s.state}，不是任务面板，放弃")
            return 2
        cx, cy = s.hits["panel_teleport"].center
        cost = panel_teleport(s)
        print(f"  tap({cx},{cy})  马上传送  {cost:.0f} ms")
        return 0

    if cmd == "close-panel":
        s = eyes.tick()
        if s.state != "TASK_PANEL":
            print(f"  当前状态 {s.state}，不需要关")
            return 0
        cx, cy = s.hits["panel_close"].center
        cost = panel_close(s)
        print(f"  tap({cx},{cy})  关闭面板  {cost:.0f} ms")
        return 0

    if cmd == "close":
        post_key(0x1B)          # ESC
        time.sleep(0.5)
        s = eyes.tick()
        print("after ESC:", s.state)
        return 0

    print("usage: python -m mhxy_console.quest [sense [--ocr] | open-task | close]")
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
