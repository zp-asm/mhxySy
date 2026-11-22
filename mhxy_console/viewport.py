"""视口标定：从整窗抓图里切出真正的游戏画面，并归一到基准坐标。

为什么要它：
    实例窗口客户区是 960×580，上方 40 px 是 MuMu 自绘标题栏，下面 960×540 才是游戏。
    不同机器上标题栏高度/窗口尺寸/DPI 都可能不同，模板一旦按"整窗坐标"裁，就绑死当前环境。
    所以统一流程：抓整窗 → 定位游戏区(视口) → 裁出来 → 缩放到基准 960×540 → 之后所有
    坐标都只谈"基准视口坐标"，跨机器只差一个自动标定的仿射参数。

标定方法（不依赖任何外部假设）：在候选 y 偏移里滑动一个 16:9 窗口，取"边缘密度最高"的那个。
    游戏画面有大量细节，标题栏是平坦渐变 → 区分度很高（实测 std 77.6 vs 10 量级）。
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

BASE_W, BASE_H = 960, 540          # 基准视口（本作在 960x540 下 UI 布局与实测数据一致）


@dataclass
class Viewport:
    x: int = 0
    y: int = 40
    w: int = 960
    h: int = 540
    src_w: int = 960
    src_h: int = 580

    def to_dict(self) -> dict:
        return {"x": self.x, "y": self.y, "w": self.w, "h": self.h,
                "src_w": self.src_w, "src_h": self.src_h,
                "base": [BASE_W, BASE_H]}


def _sharpness(region: np.ndarray) -> float:
    if region.size == 0:
        return -1.0
    g = cv2.cvtColor(region, cv2.COLOR_BGR2GRAY)
    return float(cv2.Laplacian(g, cv2.CV_32F).var())


def detect(frame: np.ndarray, base_aspect: float = 16 / 9,
           templates: list[str] | None = None) -> Viewport:
    """在整窗帧里找游戏视口。

    两段式：
      1) 形状先验：游戏区是 16:9，MuMu 把自绘标题栏放在**顶部**，所以候选只有
         y ∈ [0, src_h - ph] 里的一小段；纯"边缘密度"会被标题栏图标骗（实测选到 y=0）。
      2) 模板自证：若给了已知模板，用"在候选视口里能否命中"来打分，取最高分偏移。
         这比任何启发式都可靠 —— 复用我们已有的 task 模板即可锁定 y=40。
    """
    h, w = frame.shape[:2]
    ph = int(round(w / base_aspect))
    if ph > h:
        ph = h
    pw = w
    max_off = max(0, h - ph)
    cands = list(range(0, max_off + 1, 2))
    if max_off not in cands:
        cands.append(max_off)

    if templates:
        loaded = []
        for p in templates:
            img = cv2.imread(p, cv2.IMREAD_COLOR)
            if img is not None:
                loaded.append(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY))
        if loaded:
            best = (None, -1.0)
            for y in cands:
                roi = frame[y:y + ph, 0:pw]
                if roi.size == 0:
                    continue
                g = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
                total = 0.0
                for t in loaded:
                    s = t
                    if (t.shape[1] > g.shape[1]) or (t.shape[0] > g.shape[0]):
                        continue
                    res = cv2.matchTemplate(g, s, cv2.TM_CCOEFF_NORMED)
                    total += float(res.max())
                if total > best[1]:
                    best = ((0, y, pw, ph), total)
            x, y, pw_, ph_ = best[0]
            return Viewport(x=x, y=y, w=pw_, h=ph_, src_w=w, src_h=h)

    # 无模板时的先验：标题栏在顶部 → 游戏区贴底
    y = max_off
    return Viewport(x=0, y=y, w=pw, h=ph, src_w=w, src_h=h)


def crop_normalize(frame: np.ndarray, vp: Viewport) -> np.ndarray:
    """裁视口并归一到基准尺寸。缩放用 AREA（缩小）保持边缘干净。"""
    roi = frame[vp.y:vp.y + vp.h, vp.x:vp.x + vp.w]
    if roi.size == 0:
        raise ValueError(f"视口越界: {vp}")
    if (vp.w, vp.h) == (BASE_W, BASE_H):
        return roi
    interp = cv2.INTER_AREA if vp.w >= BASE_W else cv2.INTER_LINEAR
    return cv2.resize(roi, (BASE_W, BASE_H), interpolation=interp)


def to_base_xy(x_win: int, y_win: int, vp: Viewport) -> tuple[int, int]:
    """整窗坐标 → 基准视口坐标。"""
    return (int((x_win - vp.x) * BASE_W / vp.w), int((y_win - vp.y) * BASE_H / vp.h))


def to_win_xy(x_base: int, y_base: int, vp: Viewport) -> tuple[int, int]:
    """基准视口坐标 → 整窗坐标（点击时用）。"""
    return (int(x_base * vp.w / BASE_W + vp.x), int(y_base * vp.h / BASE_H + vp.y))


def load(path: str | Path) -> Viewport | None:
    p = Path(path)
    if not p.exists():
        return None
    d = json.loads(p.read_text(encoding="utf-8"))
    return Viewport(**{k: d[k] for k in ("x", "y", "w", "h", "src_w", "src_h")})


def save(vp: Viewport, path: str | Path) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(vp.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    import sys
    img = cv2.imread(sys.argv[1] if len(sys.argv) > 1 else "E:\\out\\win_frame.png")
    if img is None:
        print("读不到图片")
        raise SystemExit(2)
    vp = detect(img)
    print("detected viewport:", vp)
    out = crop_normalize(img, vp)
    cv2.imwrite("E:\\out\\viewport.png", out)
    print("normalized ->", out.shape, "saved E:\\out\\viewport.png")


def align_by_anchors(frame: np.ndarray, locator, base_h: int = BASE_H,
                     base_w: int = BASE_W, search: int = 24,
                     tol: int = 6) -> tuple[Viewport, float, list[tuple[int, int, float]]]:
    """多锚点联合对齐（我们自己的标定核心）。

    为什么不能靠几何假设：
        实例窗口 chrome 高度会变（实测一次是 40px，重开窗口后变 30px），
        按"贴底"裁就会整体错位 10px，所有 UI 模板集体失配。
    做法：
        在 ±search 范围内枚举裁剪偏移 (dx,dy)，对每个锚点在**它自己的期望位置**附近
        （±tol）取匹配分，求和；总分最高的偏移即为真实视口。
    为什么不是退化的：
        单个模板自由搜索时，滑动裁剪窗只是让命中坐标跟着平移、分数不变；
        但这里每个锚点被约束在各自的期望坐标上，裁剪一错位，内容就落到别处，分数必掉。
    """
    h, w = frame.shape[:2]
    best = ((0, max(0, h - base_h)), -1.0)
    scores: list[tuple[int, int, float]] = []
    for dy in range(-search, search + 1, 2):
        for dx in range(-search, search + 1, 4):
            y0 = h - base_h + dy
            x0 = dx
            if y0 < 0 or x0 < 0 or y0 + base_h > h or x0 + base_w > w:
                continue
            roi = frame[y0:y0 + base_h, x0:x0 + base_w]
            g = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
            total, cnt = 0.0, 0
            for name, (tpl, box, thresh, pad) in locator.items.items():
                bx, by, bw, bh = box
                rx0 = max(0, bx - tol); ry0 = max(0, by - tol)
                rx1 = min(base_w, bx + bw + tol); ry1 = min(base_h, by + bh + tol)
                sub = g[ry0:ry1, rx0:rx1]
                if sub.shape[0] < tpl.shape[0] or sub.shape[1] < tpl.shape[1]:
                    continue
                res = cv2.matchTemplate(sub, tpl, cv2.TM_CCOEFF_NORMED)
                total += float(res.max()); cnt += 1
            if cnt:
                avg = total / cnt
                scores.append((dx, y0, avg))
                if avg > best[1]:
                    best = ((x0, y0), avg)
    (x0, y0), score = best
    scores.sort(key=lambda t: -t[2])
    return Viewport(x=x0, y=y0, w=base_w, h=base_h, src_w=w, src_h=h), score, scores[:5]
