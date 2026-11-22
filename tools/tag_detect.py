"""人群场景下的目标定位演示：不点"人"，点"名字条"。

思路：MMO 里每个玩家/NPC 头顶都有名字条（彩色字 + 深色描边/半透明底）。
按颜色+形态把名字条抠出来 → 拿到 bbox → 点 bbox 中心。
人群再密，名字条依然是一条条独立的，不受模型像素遮挡影响（只能被别的名字条压住）。
"""
from __future__ import annotations

import cv2
import numpy as np

FRAME = "frames/frame0.png"


def find_name_tags(img: np.ndarray):
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    h, s, v = cv2.split(hsv)

    # 名字条常见配色：亮色文字 + 深描边。先抓"高亮 + 高饱和"的像素
    mask = ((v > 170) & (s > 60)).astype(np.uint8) * 255
    # 去掉画面上下 UI 区（这里只演示场景区）
    mask[:60, :] = 0
    mask[-110:, :] = 0
    mask[:, :30] = 0
    mask[:, -160:] = 0

    # 横向膨胀把同一个名字的字连成一条，纵向几乎不膨胀
    k = cv2.getStructuringElement(cv2.MORPH_RECT, (9, 2))
    mask = cv2.dilate(mask, k, iterations=1)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, k)

    n, labels, stats, cents = cv2.connectedComponentsWithStats(mask, 8)
    out = []
    for i in range(1, n):
        x, y, w, hh, area = stats[i]
        if not (26 <= w <= 170 and 7 <= hh <= 24):
            continue
        if area < 80 or w / max(hh, 1) < 2.0:
            continue
        fill = area / float(w * hh)
        if fill < 0.25:
            continue
        out.append((int(x), int(y), int(w), int(hh), round(float(fill), 2)))
    out.sort(key=lambda t: -t[2])
    return out


def main() -> None:
    img = cv2.imread(FRAME, cv2.IMREAD_COLOR)
    tags = find_name_tags(img)
    print(f"检出候选名字条 {len(tags)} 条（按宽度排序）")
    for x, y, w, hh, fill in tags[:15]:
        cx, cy = x + w // 2, y + hh // 2
        print(f"  bbox=({x:4d},{y:4d},{w:3d},{hh:2d}) fill={fill:<5} → 点击点 ({cx},{cy})")
        cv2.rectangle(img, (x, y), (x + w, y + hh), (0, 0, 255), 1)
        cv2.circle(img, (cx, cy), 2, (0, 255, 255), -1)
    cv2.imwrite("frames/nametags.png", img)
    print("标注图 → frames/nametags.png")


if __name__ == "__main__":
    main()
