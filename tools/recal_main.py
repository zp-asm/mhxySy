"""等主界面出现后自动重采主界面锚点（不需要人工通知，也不需要动游戏）。

逻辑：
  1. 每 400 ms sense 一次
  2. 连续 3 次判定为 MAIN_UI（面板已关）→ 触发 bootstrap --require-state main --write
  3. 超时（默认 180 s）则退出并提示

用法：
    python tools/recal_main.py                # 等到主界面就采
    python tools/recal_main.py --timeout 600
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mhxy_console.quest import Eyes  # noqa: E402


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--timeout", type=int, default=180)
    ap.add_argument("--need", type=int, default=3, help="连续多少帧判定为主界面")
    ap.add_argument("--spec", default="anchors.main.spec.json")
    args = ap.parse_args(argv)

    eyes = Eyes()
    deadline = time.time() + args.timeout
    streak = 0
    last = ""
    print(f"等待主界面（面板关闭）… 超时 {args.timeout}s")
    while time.time() < deadline:
        try:
            s = eyes.tick()
        except Exception as e:                      # 抓帧失败（窗口最小化等）
            print(f"  抓帧失败: {e}")
            time.sleep(1.0)
            continue
        if s.state != last:
            print(f"  state={s.state}  ({s.match_ms:.0f} ms)")
            last = s.state
        if s.state == "MAIN_UI":
            streak += 1
            if streak >= args.need:
                print(f"\n检测到主界面稳定 {streak} 帧，开始采锚点…")
                rc = subprocess.run(
                    [sys.executable, "tools/bootstrap_anchors.py",
                     "--spec", args.spec, "--require-state", "main", "--write"],
                    cwd=Path(__file__).resolve().parents[1])
                return rc.returncode
        else:
            streak = 0
        time.sleep(0.4)
    print("超时：一直没等到主界面（面板仍开着？）")
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
