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
    "panel_close":    (0.90, 20),
    "panel_teleport": (0.90, 24),
    "panel_tab_main": (0.88, 20),
    "panel_title":    (0.85, 12),
    "panel_goal":     (0.80, 12),
    "panel_desc":     (0.75, 12),
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
        # 面板优先：面板打开时右侧按钮全被遮住，主界面锚点不可信
        if self.has("panel_teleport") and self.has("panel_close"):
            return "TASK_PANEL"
        if self.has("task_btn") and self.has("quest_track"):
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
