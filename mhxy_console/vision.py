"""视觉层：模板匹配 + 可选 OCR。

用法：
    v = Vision()
    v.add("btn_task", "templates/task.png")
    hit = v.find(frame_bgr, "btn_task")     # -> Match(x, y, score) | None
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np


@dataclass
class Match:
    x: int
    y: int
    score: float
    w: int = 0
    h: int = 0

    @property
    def center(self) -> tuple[int, int]:
        return self.x + self.w // 2, self.y + self.h // 2


class Vision:
    def __init__(self, templates_dir: str | Path = "templates", threshold: float = 0.86):
        self.dir = Path(templates_dir)
        self.threshold = threshold
        self._cache: dict[str, np.ndarray] = {}

    # ---------- 模板 ----------
    def add(self, name: str, path: str | Path | None = None, scale: float = 1.0) -> None:
        p = Path(path) if path else self.dir / f"{name}.png"
        img = cv2.imread(str(p), cv2.IMREAD_COLOR)
        if img is None:
            raise FileNotFoundError(p)
        if scale != 1.0:
            img = cv2.resize(img, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
        self._cache[name] = img

    def add_from_frame(self, name: str, frame_bgr: np.ndarray,
                       x: int, y: int, w: int, h: int) -> Path:
        """从当前帧裁剪即可得到模板（换分辨率后要重裁）。"""
        self.dir.mkdir(parents=True, exist_ok=True)
        crop = frame_bgr[y:y + h, x:x + w]
        p = self.dir / f"{name}.png"
        cv2.imwrite(str(p), crop)
        self._cache[name] = crop
        return p

    # ---------- 匹配 ----------
    def find(self, frame_bgr: np.ndarray, name: str,
             threshold: float | None = None, region: tuple[int, int, int, int] | None = None
             ) -> Match | None:
        tpl = self._cache.get(name)
        if tpl is None:
            self.add(name)
            tpl = self._cache[name]
        th = self.threshold if threshold is None else threshold

        ox = oy = 0
        roi = frame_bgr
        if region:
            x, y, w, h = region
            roi = frame_bgr[y:y + h, x:x + w]
            ox, oy = x, y

        res = cv2.matchTemplate(roi, tpl, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, max_loc = cv2.minMaxLoc(res)
        if max_val < th:
            return None
        th_, tw_ = tpl.shape[:2]
        return Match(max_loc[0] + ox, max_loc[1] + oy, float(max_val), tw_, th_)

    def find_all(self, frame_bgr: np.ndarray, name: str, threshold: float | None = None,
                 max_hits: int = 20) -> list[Match]:
        tpl = self._cache.get(name)
        if tpl is None:
            self.add(name)
            tpl = self._cache[name]
        th = self.threshold if threshold is None else threshold
        res = cv2.matchTemplate(frame_bgr, tpl, cv2.TM_CCOEFF_NORMED)
        ys, xs = np.where(res >= th)
        th_, tw_ = tpl.shape[:2]
        hits: list[Match] = []
        for x, y in zip(xs, ys):
            if all(abs(int(x) - h.x) > tw_ // 2 or abs(int(y) - h.y) > th_ // 2 for h in hits):
                hits.append(Match(int(x), int(y), float(res[y, x]), tw_, th_))
            if len(hits) >= max_hits:
                break
        return hits

    # ---------- OCR（可选，装了 rapidocr-onnxruntime 才启用） ----------
    def ocr(self, frame_bgr: np.ndarray, region: tuple[int, int, int, int] | None = None
            ) -> list[tuple[str, float, tuple[int, int, int, int]]]:
        try:
            from rapidocr_onnxruntime import RapidOCR  # noqa: WPS433
        except ImportError:
            return []
        global _OCR_SINGLETON
        try:
            engine = _OCR_SINGLETON
        except NameError:
            engine = _OCR_SINGLETON = RapidOCR()

        img = frame_bgr
        ox = oy = 0
        if region:
            x, y, w, h = region
            img = frame_bgr[y:y + h, x:x + w]
            ox, oy = x, y
        out: list[tuple[str, float, tuple[int, int, int, int]]] = []
        for box, text, score in (engine(img)[0] or []):
            xs = [p[0] for p in box]
            ys = [p[1] for p in box]
            out.append((text, float(score),
                        (int(min(xs)) + ox, int(min(ys)) + oy,
                         int(max(xs) - min(xs)), int(max(ys) - min(ys)))))
        return out
