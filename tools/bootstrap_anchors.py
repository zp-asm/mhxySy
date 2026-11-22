"""锚点引导：从当前画面裁出一套模板，并立刻做正/负样本验收。

为什么需要"引导"而不是手写坐标：
  · MuMu 窗口客户区 = 游戏画面 + chrome（实测 960x580 = 40px 标题栏 + 960x540 游戏）
  · 不同机器 chrome 高度可能不同 → 视口用"贴底"几何约束定位，再靠锚点自证
  · 锚点必须在**当前这台机器、当前画质档**下裁，才能保证模板与像素一致

用法：
    python tools/bootstrap_anchors.py --spec anchors.spec.json           # 只验收，不写盘
    python tools/bootstrap_anchors.py --spec anchors.spec.json --write    # 写 templates/
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import cv2
import numpy as np

from mhxy_console.win import FrameSource, dpi_aware
from mhxy_console import viewport as V


def mumu_pid() -> int:
    out = subprocess.run(
        ["powershell", "-NoProfile", "-Command",
         "(Get-Process MuMuNxDevice | Select-Object -First 1).Id"],
        capture_output=True, text=True, encoding="utf-8", errors="replace").stdout.strip()
    return int(out)


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--spec", default="anchors.spec.json")
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--out", default="templates")
    ap.add_argument("--require-state", choices=["main", "panel", "any"], default="any",
                    help="采集前校验当前界面状态，防止在错误状态下采锚点")
    args = ap.parse_args(argv)

    spec = json.loads(Path(args.spec).read_text(encoding="utf-8"))
    dpi_aware()
    src = FrameSource(mumu_pid())
    tgt = src.refresh_target()
    # 采 3 帧：第 1 帧裁模板，第 2/3 帧做**跨帧验证**（关键：自证等于没验）
    frames = []
    for i in range(3):
        fr = src.grab()
        frames.append(fr.image)
        if i < 2:
            time.sleep(0.35)
    f = src  # 占位，后面不再用
    print(f"window={tgt}  frame={frames[0].shape[1]}x{frames[0].shape[0]}  采集 3 帧做跨帧验证")
    import time as _t

    vp = V.detect(frames[0], templates=None)        # 贴底几何定位
    print(f"viewport(贴底): {vp}")
    base = V.crop_normalize(frames[0], vp)
    others = [V.crop_normalize(fr, vp) for fr in frames[1:]]
    cv2.imwrite("E:/out/base_current.png", base)

    # ---- 状态闸门：用已有模板判定当前是主界面还是任务面板 ----
    if args.require_state != "any":
        import json as _json
        probe = {}
        for nm in ("panel_teleport", "panel_close", "quest_track", "task_btn"):
            f2 = Path(args.out) / f"{nm}.png"
            if not f2.exists():
                continue
            img = cv2.imread(str(f2))
            if img is None:
                continue
            gt = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            g2 = cv2.cvtColor(base, cv2.COLOR_BGR2GRAY)
            r = cv2.matchTemplate(g2, gt, cv2.TM_CCOEFF_NORMED)
            probe[nm] = float(r.max())
        panel_open = probe.get("panel_teleport", 0) > 0.90 and probe.get("panel_close", 0) > 0.90
        print(f"  状态探测: {[(k, round(v,3)) for k,v in probe.items()]} -> panel_open={panel_open}")
        if args.require_state == "main" and panel_open:
            print("  ✗ 当前是【任务面板】状态，拒绝采主界面锚点（请先关掉面板）")
            return 3
        if args.require_state == "panel" and not panel_open:
            print("  ✗ 当前不是【任务面板】状态，拒绝采面板锚点")
            return 3

    ok_all = True
    for name, box in spec.items():
        x, y, w, h = box
        if x < 0 or y < 0 or x + w > base.shape[1] or y + h > base.shape[0]:
            print(f"  {name:14s} 越界 {box}")
            ok_all = False
            continue
        crop = base[y:y + h, x:x + w]
        gt = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
        # 跨帧验证：在另外两帧的**同一位置**做局部匹配（±6px 容差）
        xf: list[float] = []
        for other in others:
            og = cv2.cvtColor(other, cv2.COLOR_BGR2GRAY)
            rx0, ry0 = max(0, x - 6), max(0, y - 6)
            rx1 = min(og.shape[1], x + w + 6)
            ry1 = min(og.shape[0], y + h + 6)
            sub = og[ry0:ry1, rx0:rx1]
            if sub.shape[0] < gt.shape[0] or sub.shape[1] < gt.shape[1]:
                xf.append(0.0); continue
            r = cv2.matchTemplate(sub, gt, cv2.TM_CCOEFF_NORMED)
            xf.append(float(r.max()))
        score = min(xf) if xf else 0.0
        neg = 0.0
        loc = (x, y)
        uniq = float(crop.std())                     # 模板是否有足够结构（纯色块没用）
        verdict = "OK" if (score > 0.92 and uniq > 8) else "WEAK"
        if verdict != "OK":
            ok_all = False
        print(f"  {name:14s} box={box} 跨帧={score:.4f} (另两帧 {[round(v,3) for v in xf]}) "
              f"std={uniq:5.1f}  {verdict}")
        if args.write:
            out = Path(args.out)
            out.mkdir(parents=True, exist_ok=True)
            cv2.imwrite(str(out / f"{name}.png"), crop)
            (out / f"{name}.json").write_text(
                json.dumps({"box": box, "thresh": 0.90, "roi_pad": 60},
                           ensure_ascii=False, indent=2), encoding="utf-8")

    if args.write:
        print(f"\n已写入 {args.out}/（{len(spec)} 个锚点）")
    print("结论:", "全部可用" if ok_all else "有 WEAK 项，需要重新定框或换画质档")
    return 0 if ok_all else 4


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
