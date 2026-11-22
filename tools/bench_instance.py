"""中控单实例 CPU 预算实测：抓帧 + 多锚点匹配 + （可选）OCR 的单轮成本。

回答一个问题：纯 CPU 的 Python 能不能扛 N 开？
"""
from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import cv2
import numpy as np

from mhxy_console.win import FrameSource, dpi_aware
from mhxy_console import viewport as V


def main() -> int:
    dpi_aware()
    pid = int(subprocess.run(
        ["powershell", "-NoProfile", "-Command",
         "(Get-Process MuMuNxDevice | Select-Object -First 1).Id"],
        capture_output=True, text=True, encoding="utf-8", errors="replace").stdout.strip())
    src = FrameSource(pid)
    src.refresh_target()

    # 取一帧，标定视口，再用当前画面裁 12 个"伪锚点"（模拟 12 个 UI 元素）
    f = src.grab()
    vp = V.detect(f.image)
    base = V.crop_normalize(f.image, vp)
    h, w = base.shape[:2]
    print(f"viewport={vp}  base={w}x{h}")

    rng = np.random.default_rng(0)
    tpls = []      # (name, gray_template, roi_box)
    for i in range(12):
        x = int(rng.integers(70, w - 140))
        y = int(rng.integers(70, h - 100))
        crop = base[y:y + 28, x:x + 64]
        rx, ry = max(0, x - 60), max(0, y - 60)
        rw = min(w - rx, 64 + 120)
        rh = min(h - ry, 28 + 120)
        tpls.append((f"a{i}", cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY), (rx, ry, rw, rh)))
    # 每个锚点配一个 ROI（模板位置外扩 60px），模拟真实用法
    print(f"templates={len(tpls)}")

    N = 60
    # ---- 阶段 1：抓帧 only
    t0, c0 = time.perf_counter(), time.process_time()
    for _ in range(N):
        src.grab()
    wall1, cpu1 = time.perf_counter() - t0, time.process_time() - c0

    # ---- 阶段 2：抓帧 + 12 锚点匹配（每锚点限定 ROI）
    t0, c0 = time.perf_counter(), time.process_time()
    for _ in range(N):
        fr = src.grab()
        g = cv2.cvtColor(V.crop_normalize(fr.image, vp), cv2.COLOR_BGR2GRAY)
        hits = 0
        for name, t, (rx, ry, rw, rh) in tpls:
            roi = g[ry:ry + rh, rx:rx + rw]
            if roi.shape[0] < t.shape[0] or roi.shape[1] < t.shape[1]:
                continue
            res = cv2.matchTemplate(roi, t, cv2.TM_CCOEFF_NORMED)
            if float(res.max()) > 0.9:
                hits += 1
    wall2, cpu2 = time.perf_counter() - t0, time.process_time() - c0

    # ---- 阶段 3：OCR（装了才测）
    ocr_ms = None
    try:
        from rapidocr_onnxruntime import RapidOCR
        eng = RapidOCR()
        eng(base[80:200, 0:480])          # warmup（首次含模型加载）
        t0 = time.perf_counter()
        for _ in range(3):
            eng(base[80:200, 0:480])
        ocr_ms = (time.perf_counter() - t0) / 3 * 1000
    except ImportError:
        pass

    print("\n--- 结果（每轮）---")
    print(f"抓帧              {wall1/N*1000:7.2f} ms   CPU {cpu1/N*1000:6.2f} ms")
    print(f"抓帧+12锚点       {wall2/N*1000:7.2f} ms   CPU {cpu2/N*1000:6.2f} ms")
    if ocr_ms:
        print(f"OCR(480x120 区域) {ocr_ms:7.2f} ms")
    else:
        print("OCR              未安装（pip install rapidocr-onnxruntime）")

    # 按 20 Hz 轮询估算单实例 CPU 占用
    per_tick_cpu = cpu2 / N
    cores_per_instance = per_tick_cpu * 20
    print("\n--- 20 Hz 轮询下的单实例估算 ---")
    print(f"CPU 时间/轮 = {per_tick_cpu*1000:.2f} ms → 单实例 ≈ {cores_per_instance:.2f} 核")
    for n in (1, 4, 10):
        print(f"  {n:2d} 开 ≈ {cores_per_instance*n:.2f} 核")
    print("\n参考：本机 i5-10400 = 6 核 12 线程")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
