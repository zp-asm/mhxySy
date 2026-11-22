"""感知管线性能基准：给"注不注入"这个问题一个数字答案。"""
from __future__ import annotations

import time

import cv2
import numpy as np

from mhxy_console.adb import AdbDevice
from mhxy_console.vision import Vision

SERIAL = "127.0.0.1:16384"


def bench(label: str, fn, n: int = 30) -> float:
    fn()  # warmup
    t0 = time.perf_counter()
    for _ in range(n):
        fn()
    dt = (time.perf_counter() - t0) / n * 1000
    print(f"{label:34s} {dt:8.2f} ms")
    return dt


def main() -> None:
    dev = AdbDevice(SERIAL)
    dev.connect()

    # 1) 通道：adb screencap
    dev.screencap_png()
    t_cap = bench("adb screencap 全帧(960x540)", lambda: dev.screencap_png(), 5)

    # 2) 通道：宿主窗口 DXGI（dxcam 未装则跳过）
    try:
        import dxcam  # noqa: F401
        cam = dxcam.create(output_color="BGR")
        t_cap_host = bench("dxcam 宿主抓帧", lambda: cam.grab(), 60)
    except Exception as e:  # noqa: BLE001
        print(f"{'dxcam 宿主抓帧':34s} 未安装 ({type(e).__name__})")
        t_cap_host = None

    # 3) 视觉：模板匹配
    png = dev.screencap_png()
    frame = cv2.imdecode(np.frombuffer(png, np.uint8), cv2.IMREAD_COLOR)
    v = Vision("templates")
    v.add("task")
    t1 = bench("单模板 matchTemplate 全帧", lambda: v.find(frame, "task", 0.8), 200)

    # 4) 视觉：10 个模板（模拟一屏 UI 状态判定）
    for i in range(9):
        v._cache[f"synthetic{i}"] = v._cache["task"][:, : max(8, 30 - i)]
    names = ["task"] + [f"synthetic{i}" for i in range(9)]
    t10 = bench("10 模板全帧扫描", lambda: [v.find(frame, n, 0.8) for n in names], 50)

    # 5) ROI 优化：只在右上半屏找
    roi = (600, 40, 360, 200)
    t_roi = bench("单模板 ROI(360x200)", lambda: v.find(frame, "task", 0.8, roi), 200)

    # 6) 缩放到 480x270 再匹配（多开省 CPU 的做法）
    small = cv2.resize(frame, (480, 270), interpolation=cv2.INTER_AREA)
    vs = Vision("templates")
    vs._cache["task_s"] = cv2.resize(v._cache["task"], None, fx=0.5, fy=0.5,
                                     interpolation=cv2.INTER_AREA)
    t_small = bench("单模板 480x270 缩图匹配", lambda: vs.find(small, "task_s", 0.8), 200)

    print("\n--- 单轮「感知 -> 决策」成本估算 ---")
    if t_cap_host:
        print(f"宿主抓帧 + 10 模板 + ROI 复检 ≈ {t_cap_host + t10 + t_roi:.0f} ms")
    print(f"adb 抓帧 + 10 模板            ≈ {t_cap + t10:.0f} ms  ← 现状，太慢")
    print(f"缩图 + 单模板                  ≈ {t_small:.1f} ms")

    # 7) 输入延迟
    t0 = time.perf_counter()
    dev.tap(480, 300)
    print(f"{'adb input tap':34s} {(time.perf_counter() - t0) * 1000:8.2f} ms")


if __name__ == "__main__":
    main()
