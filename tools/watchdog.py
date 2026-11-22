"""主线看守（watchdog）：只在"卡住"时才动手。

设计依据：
    游戏自带自动任务，所以默认**不干预**。只有当
      · 处于主界面（MAIN_UI）
      · 追踪条文本在一段时间内没有变化
      · 也没有过场/面板/战斗在跑
    才判定"卡住"，执行兜底动作：点任务 → 读面板 → 若主线则点「马上传送」。

用法：
    python tools/watchdog.py --dry                 # 只看不动（默认）
    python tools/watchdog.py --enable-actions --seconds 120
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mhxy_console.quest import (Eyes, enable_actions, read_panel, panel_teleport,  # noqa: E402
                               adb_tap)


def tracker_text(sense) -> str:
    """读追踪条（小字号，OCR 不稳）——这里只用它做"有没有变化"的粗判。"""
    try:
        import cv2
        from rapidocr_onnxruntime import RapidOCR
        hit = sense.hits.get("quest_track")
        if not hit:
            return ""
        x, y, w, h = hit.box
        crop = sense.base[y:y + h, x:x + w]
        big = cv2.resize(crop, None, fx=2.0, fy=2.0, interpolation=cv2.INTER_CUBIC)
        out = RapidOCR()(big)
        return " ".join(t[1] for t in (out[0] or [])) if out and out[0] else ""
    except Exception:
        return ""


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seconds", type=float, default=90)
    ap.add_argument("--enable-actions", action="store_true")
    ap.add_argument("--stuck-sec", type=float, default=25, help="多久没动静算卡住")
    args = ap.parse_args(argv)

    if args.enable_actions:
        enable_actions(True)
        print("⚠ 已授权动作")
    eyes = Eyes()
    t_end = time.time() + args.seconds
    last_state = ""
    last_text = ""
    last_change = time.time()
    intervened = 0

    while time.time() < t_end:
        try:
            s = eyes.tick()
        except Exception as e:
            print(f"  抓帧失败: {e}")
            time.sleep(1.0)
            continue

        if s.state != last_state:
            print(f"  [{time.strftime('%H:%M:%S')}] state: {last_state or '-'} -> {s.state}")
            last_state = s.state
            last_change = time.time()

        if s.state == "MAIN_UI":
            # 每 5 秒读一次追踪条文本，判断有没有推进
            if int(time.time()) % 5 == 0:
                txt = tracker_text(s)
                if txt and txt != last_text:
                    print(f"  [{time.strftime('%H:%M:%S')}] 追踪条: {txt}")
                    last_text = txt
                    last_change = time.time()

            idle = time.time() - last_change
            if idle > args.stuck_sec:
                print(f"  [{time.strftime('%H:%M:%S')}] 判定卡住（{idle:.0f}s 无变化）")
                if args.enable_actions and "task_btn" in s.hits:
                    cx, cy = s.hits["task_btn"].center
                    adb_tap(cx, cy)
                    time.sleep(1.0)
                    s2 = eyes.tick()
                    if s2.state == "TASK_PANEL":
                        info = read_panel(s2)
                        print(f"    面板: {info.get('title')} / {info.get('goal')}")
                        if "主线" in (info.get("title") or ""):
                            cost = panel_teleport(s2)
                            print(f"    马上传送 -> {cost:.0f} ms")
                            intervened += 1
                    last_change = time.time()
                else:
                    print("    （dry 模式，不动作）")
                    last_change = time.time()

        time.sleep(1.2)

    print(f"\n结束：干预 {intervened} 次")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
