"""福利 / 刮刮乐 / 升级礼包 自动化（登录例行）。

设计原则（针对我们踩过的坑）：
  · 不用固定坐标 —— 面板布局随页签/分辨率漂移，改成 **OCR 找文字再点**。
  · 红点用**颜色检测**（不是模板）：小红点是大红+低绿低蓝的实心圆，模板很容易被背景骗。
  · 升级礼包用**等级判断**（1/10/20…120，每 10 级一档），只领 ≤ 当前等级的档位。
  · 全部动作走 quest.adb_tap（同一个动作闸门），默认干跑。

对外 API：
    open_welfare(eyes)                    打开福利面板
    read_level(eyes)                      读角色等级（OCR）
    do_daily(eyes)                        每日福利 → 打开刮刮乐 → 刮奖
    do_levelup(eyes, level)               升级礼包 → 领可领档位
    login_routine(eyes, act=False)        登录例行：上面三件的组合
"""
from __future__ import annotations

import time

import cv2
import numpy as np

from .quest import Eyes, Sense, adb_tap, find_text

# ---------------------------------------------------------------- 红点检测
RED_LO1 = np.array([0, 120, 120])       # HSV 下界（红在 0 和 180 两端）
RED_HI1 = np.array([8, 255, 255])
RED_LO2 = np.array([172, 120, 120])
RED_HI2 = np.array([180, 255, 255])


def red_dot_ratio(img: np.ndarray, box: tuple[int, int, int, int]) -> float:
    """框内"红点像素"占比。红点一般 8~14px 圆，占比 5%~40% 之间。"""
    x, y, w, h = box
    roi = img[max(0, y):y + h, max(0, x):x + w]
    if roi.size == 0:
        return 0.0
    hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
    m = cv2.inRange(hsv, RED_LO1, RED_HI1) | cv2.inRange(hsv, RED_LO2, RED_HI2)
    m = cv2.morphologyEx(m, cv2.MORPH_OPEN, np.ones((2, 2), np.uint8))
    return float((m > 0).mean())


def has_red_dot(img: np.ndarray, text_box: tuple[int, int, int, int]) -> bool:
    """文字框右上角找红点。"""
    x, y, w, h = text_box
    probe = (x + w - 6, max(0, y - 16), 26, 26)
    r = red_dot_ratio(img, probe)
    return 0.04 < r < 0.75


# ---------------------------------------------------------------- 面板操作
WELFARE_TEXTS = ("每日福利", "升级礼包", "打开刮刮乐", "领取", "使用", "刮刮乐")


def open_welfare(eyes: Eyes, act: bool) -> bool:
    """主界面点「福利」。优先锚点，失败则 OCR 找「福利」两字。"""
    s = eyes.tick()
    hit = None
    if "welfare_btn" in s.hits:
        hit = (s.hits["welfare_btn"].center, s.hits["welfare_btn"].box)
    else:
        t = find_text(s, "福利", region=(0, 40, 200, 220))
        if t:
            hit = ((t[0], t[1]), t[2])
    if not hit:
        print("  找不到「福利」入口")
        return False
    (cx, cy), _ = hit
    if act:
        adb_tap(cx, cy)
    print(f"  点福利 ({cx},{cy}){'' if act else '  [dry]'}")
    time.sleep(1.4)
    return True


LEVEL_ROI = (246, 56, 120, 40)      # 人物属性面板上「3级」的位置（960x540 基准）


def read_level(eyes: Eyes, act: bool) -> int | None:
    """读等级：OCR「N级」。当前界面若没有，就先点头像开人物属性。"""
    s = eyes.tick()
    t = find_text(s, "级", region=LEVEL_ROI)
    if not t:
        t = find_text(s, "级", region=(80, 40, 620, 220))   # 放宽兜底
    if not t:
        if not act:
            return None
        if "hero_avatar" in s.hits:
            cx, cy = s.hits["hero_avatar"].center
        else:
            cx, cy = (150, 96)                            # 头像常驻位置兜底
        adb_tap(cx, cy)
        time.sleep(1.2)
        s = eyes.tick()
        t = find_text(s, "级", region=(80, 40, 520, 200))
    if not t:
        return None
    text = t[2]
    s2 = s.base[t[2][1]:t[2][1] + t[2][3], t[2][0]:t[2][0] + t[2][2]]
    # 用 OCR 文本里的数字兜底
    from rapidocr_onnxruntime import RapidOCR
    big = cv2.resize(s2, None, fx=2.0, fy=2.0, interpolation=cv2.INTER_CUBIC)
    out = RapidOCR()(big)
    if out and out[0]:
        for _, txt, _sc in out[0]:
            digits = "".join(ch for ch in txt if ch.isdigit())
            if digits:
                return int(digits)
    return None


def click_text(eyes: Eyes, sense: Sense, needle: str, act: bool,
               region=(0, 0, 960, 540)) -> bool:
    t = find_text(sense, needle, region=region)
    if not t:
        return False
    if act:
        adb_tap(t[0], t[1])
    print(f"  点「{needle}」({t[0]},{t[1]}){'' if act else '  [dry]'}")
    time.sleep(1.2)
    return True


def do_daily(eyes: Eyes, act: bool) -> bool:
    """每日福利 → 打开刮刮乐 → 刮奖。返回是否做了刮奖。"""
    s = eyes.tick()
    t = find_text(s, "每日福利")
    if not t:
        print("  没找到「每日福利」")
        return False
    dotted = has_red_dot(s.base, t[2])
    print(f"  每日福利 红点={dotted}")
    if not dotted:
        print("  每日福利无红点 → 今天不用刮")
        return False
    if act:
        adb_tap(t[0], t[1])
    time.sleep(1.3)

    s = eyes.tick()
    if not click_text(eyes, s, "打开刮刮乐", act):
        print("  没找到「打开刮刮乐」（可能今天已抽完）")
        return False

    s = eyes.tick()
    return scratch(eyes, s, act)


def scratch(eyes: Eyes, sense: Sense, act: bool, passes: int = 8) -> bool:
    """在刮刮乐卡片上做之字形滑动。卡片区域用「刮刮乐」标题下方估算。"""
    t = find_text(sense, "刮刮乐")
    if not t:
        return False
    cx, cy = t[0], t[1]
    x0, y0, x1, y1 = cx - 200, cy + 60, cx + 200, cy + 300
    print(f"  刮奖区域 ({x0},{y0})-({x1},{y1})")
    for i in range(passes):
        yy = y0 + (y1 - y0) * (i + 1) / (passes + 1)
        xs, xe = (x0, x1) if i % 2 == 0 else (x1, x0)
        if act:
            import subprocess
            subprocess.run(["adb", "-s", "127.0.0.1:16384", "shell", "input", "swipe",
                            str(int(xs)), str(int(yy)), str(int(xe)), str(int(yy)), "260"],
                           capture_output=True, timeout=20)
        print(f"    swipe y={yy:.0f} {'→' if i % 2 == 0 else '←'}{'' if act else '  [dry]'}")
        time.sleep(0.35)
    return True


def do_levelup(eyes: Eyes, level: int, act: bool) -> int:
    """升级礼包：把 ≤ level 的档位都领一遍。返回领取次数。

    重要规则（实测确认）：**已领取的档位会从列表里消失**，所以
      · 找不到某档位 = 已领取（或未达等级），不是失败
      · 档位在但按钮是「N级领取」灰字 = 等级不够
      · 档位在且按钮是「领取」金字 = 可领
    """
    s = eyes.tick()
    if not click_text(eyes, s, "升级礼包", act):
        print("  没找到「升级礼包」")
        return 0

    claimed = 0
    missing = []
    for lv in range(1, 121, 10):
        if lv > level:
            break
        s = eyes.tick()
        label = f"{lv}级礼包"
        t = find_text(s, label, region=(60, 80, 820, 470))
        if not t:
            missing.append(lv)          # 已领取 or 未滚动到
            continue
        # 领取按钮通常在同一条目的右侧
        s2 = eyes.tick()
        tb = t[2]
        region = (tb[0], tb[1] - 20, tb[2] + 420, 90)
        if click_text(eyes, s2, "领取", act, region=region):
            claimed += 1
    if missing:
        print(f"  未在列表中出现的档位（= 已领取或未滚动到）: {missing}")
    print(f"  升级礼包：领取 {claimed} 次（等级 {level}）")
    return claimed


def login_routine(eyes: Eyes, act: bool = False, level: int | None = None) -> None:
    """登录例行：福利 → 每日福利(红点) → 刮刮乐 → 升级礼包。"""
    print("== 登录例行 ==")
    # 先在主界面读等级（头像 → 人物属性），再关掉，避免被福利面板挡住
    lv = level
    if lv is None:
        s0 = eyes.tick()
        if "hero_close" in s0.hits:              # 面板已开着，直接读
            lv = read_level(eyes, act)
        else:
            if act and "hero_avatar" in s0.hits:
                cx, cy = s0.hits["hero_avatar"].center
            else:
                cx, cy = (150, 96)
            if act:
                adb_tap(cx, cy)
                time.sleep(1.2)
            lv = read_level(eyes, act)
        # 读完关掉人物属性
        s1 = eyes.tick()
        if act and "hero_close" in s1.hits:
            cx, cy = s1.hits["hero_close"].center
            adb_tap(cx, cy)
            time.sleep(1.0)
    lv = lv or 1
    print(f"  角色等级 = {lv}")

    if not open_welfare(eyes, act):
        return
    do_daily(eyes, act)
    do_levelup(eyes, lv, act)


if __name__ == "__main__":
    import sys
    from .quest import enable_actions
    act = "--enable-actions" in sys.argv
    if act:
        enable_actions(True)
        print("⚠ 已授权动作")
    e = Eyes()
    login_routine(e, act=act)
