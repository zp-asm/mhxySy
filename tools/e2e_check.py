"""端到端验证：抓帧 → 模板定位 → 注入点击 → 再抓帧确认状态变化。

只点"任务"按钮（无害面板），验证完自动 BACK 关闭。
"""
from __future__ import annotations

import time

import cv2
import numpy as np

from mhxy_console.adb import AdbDevice
from mhxy_console.vision import Vision

SERIAL = "127.0.0.1:16384"


def frame(dev: AdbDevice) -> np.ndarray:
    png = dev.screencap_png()
    return cv2.imdecode(np.frombuffer(png, np.uint8), cv2.IMREAD_COLOR)


def diff(a: np.ndarray, b: np.ndarray) -> float:
    if a.shape != b.shape:
        return 1.0
    d = cv2.absdiff(a, b)
    return float((d.mean(axis=2) > 24).mean())


def main() -> int:
    dev = AdbDevice(SERIAL)
    print("connect:", dev.connect(), "root:", dev.ensure_root())
    print("screen:", dev.screen)

    v = Vision("templates")
    v.add("task")

    f0 = frame(dev)
    hit = v.find(f0, "task", 0.80)
    print(f"frame0 {f0.shape}, task match={None if not hit else (hit.x, hit.y, round(hit.score, 4))}")
    if not hit:
        print("模板没命中，先 crop 一个新模板")
        return 2

    cx, cy = hit.center
    print(f"tap 任务按钮 @ ({cx},{cy})")
    dev.tap(cx, cy)
    time.sleep(1.2)
    f1 = frame(dev)
    print(f"点击后帧变化率 = {diff(f0, f1):.3f}（>0.05 说明 UI 有反应）")

    # 关闭面板
    dev.key(4)  # BACK
    time.sleep(0.8)
    f2 = frame(dev)
    print(f"BACK 后与初始帧差异 = {diff(f0, f2):.3f}（应接近 0）")

    cv2.imwrite("frames/e2e_0.png", f0)
    cv2.imwrite("frames/e2e_1_after_tap.png", f1)
    cv2.imwrite("frames/e2e_2_after_back.png", f2)
    print("帧已存 frames/e2e_*.png")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
