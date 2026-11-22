"""主线自动驾驶 v1（watchdog + 状态机）。

状态 → 动作表（全部有冷却，避免连点）：
    POPUP     弹窗（新手礼包/活动）     → 点「使用」，没有就点 ✕
    CUTSCENE  剧情过场（黑屏字幕）      → 点「手动」推进一句
    DIALOG    NPC 对话                  → 点「自动」（只点一次，让它自己跑）
    TASK_PANEL 任务面板                 → 若不在主线页：OCR 点「长寿迷踪」→ 点「马上传送」
    MAIN_UI   主界面                    → 只观察；超过 --stuck-sec 无变化才开面板兜底

用法：
    python tools/autopilot.py --seconds 120                  # 只读（不发输入）
    python tools/autopilot.py --seconds 120 --enable-actions  # 真跑
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import cv2  # noqa: E402

from mhxy_console.quest import (Eyes, enable_actions, find_text, read_panel,  # noqa: E402
                                adb_tap)


def log(msg: str) -> None:
    print(f"  [{time.strftime('%H:%M:%S')}] {msg}", flush=True)


class Pilot:
    def __init__(self, act: bool, stuck_sec: float = 30.0):
        self.eyes = Eyes()
        self.act = act
        self.stuck_sec = stuck_sec
        self.cool: dict[str, float] = {}
        self.last_state = ""
        self.last_change = time.time()
        self.stats = {"popup": 0, "cut": 0, "dialog": 0, "panel": 0, "teleport": 0}

    def ready(self, key: str, gap: float) -> bool:
        now = time.time()
        if now - self.cool.get(key, 0) < gap:
            return False
        self.cool[key] = now
        return True

    def tap_hit(self, sense, name: str, tag: str, gap: float = 1.0) -> bool:
        hit = sense.hits.get(name)
        if not hit or not self.ready(tag, gap):
            return False
        cx, cy = hit.center
        if self.act:
            adb_tap(cx, cy)
        log(f"{tag}: tap {name} ({cx},{cy}){'' if self.act else '  [dry]'}")
        return True

    def tick(self) -> str:
        s = self.eyes.tick()
        st = s.state
        if st != self.last_state:
            log(f"state {self.last_state or '-'} -> {st}")
            self.last_state = st
            self.last_change = time.time()

        # ---- POPUP
        if st == "POPUP":
            if self.tap_hit(s, "popup_use", "popup", 1.5):
                self.stats["popup"] += 1
            elif self.tap_hit(s, "popup_close", "popup-close", 2.0):
                self.stats["popup"] += 1
            return st

        # ---- CUTSCENE
        if st == "CUTSCENE":
            if self.tap_hit(s, "cut_manual", "cut", 1.2):
                self.stats["cut"] += 1
            return st

        # ---- DIALOG
        if st == "DIALOG":
            # 自动只点一次；之后靠游戏自己推进
            if "dlg_auto" in s.hits and self.ready("dialog-auto", 8.0):
                cx, cy = s.hits["dlg_auto"].center
                if self.act:
                    adb_tap(cx, cy)
                log(f"dialog: 点自动 ({cx},{cy}){'' if self.act else '  [dry]'}")
                self.stats["dialog"] += 1
            return st

        # ---- TASK_PANEL
        if st == "TASK_PANEL":
            if "panel_teleport" not in s.hits and self.ready("panel-main", 3.0):
                hit = find_text(s, "长寿迷踪")
                if hit:
                    if self.act:
                        adb_tap(hit[0], hit[1])
                    log(f"panel: OCR 点长寿迷踪 ({hit[0]},{hit[1]}){'' if self.act else '  [dry]'}")
                    self.stats["panel"] += 1
                return st
            if "panel_teleport" in s.hits and self.ready("teleport", 5.0):
                info = read_panel(s)
                log(f"panel: {info.get('title')!r} / {info.get('goal')!r}")
                cx, cy = s.hits["panel_teleport"].center
                if self.act:
                    adb_tap(cx, cy)
                log(f"panel: 马上传送 ({cx},{cy}){'' if self.act else '  [dry]'}")
                self.stats["teleport"] += 1
            return st

        # ---- MAIN_UI：只观察，卡住才兜底
        if st == "MAIN_UI":
            idle = time.time() - self.last_change
            if idle > self.stuck_sec and self.ready("open-task", 20.0):
                log(f"main: 卡住 {idle:.0f}s → 打开任务面板")
                if self.tap_hit(s, "task_btn", "open-task", 1.0):
                    pass
            return st

        return st


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seconds", type=float, default=120)
    ap.add_argument("--enable-actions", action="store_true")
    ap.add_argument("--stuck-sec", type=float, default=30)
    args = ap.parse_args(argv)

    if args.enable_actions:
        enable_actions(True)
        log("⚠ 已授权动作")
    p = Pilot(act=args.enable_actions, stuck_sec=args.stuck_sec)
    t_end = time.time() + args.seconds
    while time.time() < t_end:
        try:
            p.tick()
        except Exception as e:
            log(f"tick 异常: {e}")
        time.sleep(0.8)
    log(f"结束 stats={p.stats} 末状态={p.last_state}")
    cv2.imwrite("E:/out/autopilot_end.png", p.eyes.tick().base)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
