"""图色鲁棒性压测：量化"抓出来有偏差"到底差多少、哪种匹配能扛。

对同一模板施加：JPEG 压缩、亮度/对比度漂移、高斯噪声、缩放、平移、模糊，
比较三种匹配方式：
  A. 灰度 TM_CCOEFF_NORMED（默认做法）
  B. 边缘图（Canny）TM_CCOEFF_NORMED（抗颜色漂移）
  C. 多尺度 A（0.94~1.06 步进 0.02）取最大分（抗缩放）
"""
from __future__ import annotations

import cv2
import numpy as np

FRAME = "frames/frame0.png"
TPL = "templates/task.png"


def load():
    frame = cv2.imread(FRAME, cv2.IMREAD_COLOR)
    tpl = cv2.imread(TPL, cv2.IMREAD_COLOR)
    return frame, tpl


def score_gray(frame, tpl, thr=0.8):
    g = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    t = cv2.cvtColor(tpl, cv2.COLOR_BGR2GRAY)
    r = cv2.matchTemplate(g, t, cv2.TM_CCOEFF_NORMED)
    return float(r.max())


def score_edge(frame, tpl, thr=0.8):
    g = cv2.Canny(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), 60, 160)
    t = cv2.Canny(cv2.cvtColor(tpl, cv2.COLOR_BGR2GRAY), 60, 160)
    r = cv2.matchTemplate(g, t, cv2.TM_CCOEFF_NORMED)
    return float(r.max())


def score_multiscale(frame, tpl, scales=np.arange(0.94, 1.061, 0.02)):
    g = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    best = 0.0
    for s in scales:
        t = cv2.resize(tpl, None, fx=float(s), fy=float(s), interpolation=cv2.INTER_AREA)
        t = cv2.cvtColor(t, cv2.COLOR_BGR2GRAY)
        if t.shape[0] >= g.shape[0] or t.shape[1] >= g.shape[1]:
            continue
        r = cv2.matchTemplate(g, t, cv2.TM_CCOEFF_NORMED)
        best = max(best, float(r.max()))
    return best


def degrade(frame, kind, level):
    out = frame.copy()
    if kind == "jpeg":
        ok, buf = cv2.imencode(".jpg", out, [int(cv2.IMWRITE_JPEG_QUALITY), level])
        out = cv2.imdecode(buf, cv2.IMREAD_COLOR)
    elif kind == "bright":
        out = np.clip(out.astype(np.int16) * level, 0, 255).astype(np.uint8)
    elif kind == "noise":
        n = np.random.normal(0, level, out.shape).astype(np.int16)
        out = np.clip(out.astype(np.int16) + n, 0, 255).astype(np.uint8)
    elif kind == "blur":
        out = cv2.GaussianBlur(out, (level | 1, level | 1), 0)
    elif kind == "scale":
        h, w = out.shape[:2]
        out = cv2.resize(out, (int(w * level), int(h * level)), interpolation=cv2.INTER_AREA)
        out = cv2.resize(out, (w, h), interpolation=cv2.INTER_LINEAR)
    elif kind == "shift":
        m = np.float32([[1, 0, level], [0, 1, level]])
        out = cv2.warpAffine(out, m, (out.shape[1], out.shape[0]))
    return out


def main() -> None:
    frame, tpl = load()
    cases = [
        ("原帧", frame),
        ("JPEG q85", degrade(frame, "jpeg", 85)),
        ("JPEG q60", degrade(frame, "jpeg", 60)),
        ("亮度 x0.90", degrade(frame, "bright", 0.90)),
        ("亮度 x1.12", degrade(frame, "bright", 1.12)),
        ("高斯噪声 σ=4", degrade(frame, "noise", 4)),
        ("模糊 3x3", degrade(frame, "blur", 3)),
        ("整体缩 x0.96", degrade(frame, "scale", 0.96)),
        ("偏移 2px", degrade(frame, "shift", 2)),
        ("偏移 4px", degrade(frame, "shift", 4)),
    ]
    print(f"{'场景':14s} {'灰度':>8s} {'边缘':>8s} {'多尺度':>8s}   判定(阈值0.80)")
    print("-" * 62)
    for name, img in cases:
        a, b, c = score_gray(img, tpl), score_edge(img, tpl), score_multiscale(img, tpl)
        flags = "".join("✓" if v >= 0.8 else "✗" for v in (a, b, c))
        print(f"{name:14s} {a:8.3f} {b:8.3f} {c:8.3f}   {flags}")


if __name__ == "__main__":
    main()
