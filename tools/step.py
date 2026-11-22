"""单步执行器 —— 每次只做一个动作，绝不自己连跑。

用法：
    python tools/step.py sense            # 只报状态，不动
    python tools/step.py next             # 按当前状态执行**一个**动作，然后报告
    python tools/step.py next --enable-actions
    python tools/step.py click X Y --enable-actions
    python tools/step.py ocr 文字          # 在画面里找这段文字，只报坐标不点
    python tools/step.py ocr 文字 --click --enable-actions

状态 → 单步动作：
    POPUP      点「使用」（没有则点 ✕）
    CUTSCENE   点右上 ▶▶ 跳过（没有则点「手动」推一句）
    DIALOG     点「自动」
    HERO_PANEL 点 ✕ 关掉
    TASK_PANEL 不在主线页→点「长寿迷踪」；有「马上传送」→点它
    MAIN_UI    点追踪条目标行（触发寻路）；不做其它事
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import cv2  # noqa: E402

from mhxy_console.quest import (Eyes, enable_actions, adb_tap, find_text,  # noqa: E402
                                read_panel)


def sense_line(s) -> str:
    return (f"state={s.state:10s} mean={float(s.base.mean()):6.1f} "
            f"hits={sorted(s.hits)[:6]}")


def do_next(eyes: Eyes, act: bool) -> str:
    s = eyes.tick()
    print("  现在:", sense_line(s))

    def tap(name: str, label: str, gap_box=None) -> str:
        hit = s.hits.get(name)
        if not hit:
            return ""
        cx, cy = hit.center if gap_box is None else gap_box
        if act:
            adb_tap(cx, cy)
        return f"{label} ({cx},{cy}){'' if act else '  [dry]'}"

    if s.state == "POPUP":
        for k, lb in (("popup_use", "弹窗-使用"), ("popup_close", "弹窗-关闭")):
            r = tap(k, lb)
            if r:
                return r

    if s.state == "CUTSCENE":
        for k, lb in (("cut_ff2", "跳过剧情(▶▶)"), ("cut_ff", "跳过剧情(▶▶)"),
                      ("cut_manual", "剧情-手动")):
            r = tap(k, lb)
            if r:
                return r
        # 模板追不完各版本的 ▶▶ 图标 → 右上角固定坐标兜底
        if act:
            adb_tap(920, 27)
        return f"跳过剧情(▶▶ 固定坐标 920,27){'' if act else '  [dry]'}"

    if s.state == "DIALOG":
        r = tap("dlg_auto", "对话-自动")
        if r:
            return r
        r = tap("dlg_ff", "对话-快进")
        if r:
            return r

    if s.state == "HERO_PANEL":
        for k, lb in (("hero_close2", "关人物属性"), ("hero_close", "关人物属性")):
            r = tap(k, lb)
            if r:
                return r

    if s.state == "TASK_PANEL":
        if "panel_teleport" in s.hits:
            info = read_panel(s)
            cx, cy = s.hits["panel_teleport"].center
            if act:
                adb_tap(cx, cy)
            return (f"马上传送 ({cx},{cy})  [{info.get('title')} / {info.get('goal')}]"
                    f"{'' if act else '  [dry]'}")
        t = find_text(s, "长寿迷踪")
        if t:
            if act:
                adb_tap(t[0], t[1])
            return f"点长寿迷踪 ({t[0]},{t[1]}){'' if act else '  [dry]'}"
        return "面板里没找到主线页（需要滚动/换页）"

    if s.state == "MAIN_UI":
        box = s.hits["quest_track"].box if "quest_track" in s.hits else (760, 134, 190, 64)
        tx, ty = box[0] + box[2] // 2, box[1] + int(box[3] * 0.72)
        if act:
            adb_tap(tx, ty)
        return f"点追踪条目标行 ({tx},{ty}){'' if act else '  [dry]'}"

    return "没有可执行的单步动作（未知界面）"


def main(argv: list[str]) -> int:
    act = "--enable-actions" in argv
    if act:
        enable_actions(True)
        print("⚠ 已授权动作")
    eyes = Eyes()
    cmd = argv[1] if len(argv) > 1 else "sense"

    if cmd == "sense":
        print(sense_line(eyes.tick()))
        return 0
    if cmd == "next":
        print("  动作:", do_next(eyes, act))
        time.sleep(1.2)
        print("  之后:", sense_line(eyes.tick()))
        return 0
    if cmd == "click" and len(argv) >= 4:
        x, y = int(argv[2]), int(argv[3])
        if act:
            adb_tap(x, y)
        print(f"  click ({x},{y}){'' if act else '  [dry]'}")
        time.sleep(1.0)
        print("  之后:", sense_line(eyes.tick()))
        return 0
    if cmd == "ocr" and len(argv) >= 3:
        s = eyes.tick()
        t = find_text(s, argv[2])
        print(f"  「{argv[2]}」-> {t}")
        if t and "--click" in argv:
            if act:
                adb_tap(t[0], t[1])
            print(f"  click ({t[0]},{t[1]}){'' if act else '  [dry]'}")
        cv2.imwrite("E:/out/step.png", s.base)
        return 0
    print(__doc__)
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
