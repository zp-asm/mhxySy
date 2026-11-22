"""把 MuMu 实例的"影响图色稳定性"的设置统一写死（多实例必须一致）。

原则：只锁与**画面像素/帧率**相关的键；机型/品牌这类影响游戏检测的键不动。
      视觉计算在宿主进程里做（GDI 抓帧 4ms），不占 VM 的 CPU，所以性能档可以低。

用法：
    python tools/lock_mumu.py                 # 只读，打印每个实例的现状与差异（dry-run）
    python tools/lock_mumu.py --apply         # 真正写入（需要实例重启生效）
    python tools/lock_mumu.py --apply --index 0,1
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

MUMU = r"F:\mumu\MuMuPlayer\nx_main\MuMuManager.exe"

# key -> (期望值, 说明)。值为 None 表示"只报告不改"。
CANON: dict[str, tuple[str | None, str]] = {
    # 画面几何（模板坐标的唯一基准）
    "resolution_width.custom":  ("960.000000", "视口宽 = 基准"),
    "resolution_height.custom": ("540.000000", "视口高 = 基准"),
    "resolution_dpi.custom":    ("220.000000", "DPI：UI 尺寸随它变"),
    # 帧率（动态帧率会让动画相位漂移）
    "max_frame_rate":           ("60", "固定 60"),
    "dynamic_adjust_frame_rate": ("false", "关动态帧率"),
    # 渲染后端（vk/dx 抗锯齿不同，实例间必须一致）
    "renderer_mode":            ("vk", "渲染后端固定"),
    "renderer_strategy":        (None, "显卡选择：auto 可能把不同实例分到不同 GPU（建议改固定）"),
    "gpu_mode":                 ("middle", "GPU 档位固定"),
    "gpu_model.custom":         (None, "对外报的 GPU 名（影响游戏检测，不动）"),
    # 性能（不影响像素，只影响流畅度）
    "performance_mode":         (None, "多开时统一下调为 low 更省资源"),
    # 机型（影响游戏检测，不动）
    "phone_brand":              (None, "不动"),
    "phone_model":              (None, "不动"),
}


def run(*args: str) -> str:
    r = subprocess.run([MUMU, *args], capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=60)
    return r.stdout or ""


def instances() -> dict[str, dict]:
    raw = run("info", "-v", "all").strip()
    try:
        d = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    if isinstance(d, dict) and all(k.isdigit() for k in d):
        return d
    return {}


def settings(index: str) -> dict:
    raw = run("setting", "--vmindex", index, "--all_writable").strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {}


def apply_setting(index: str, key: str, value: str) -> bool:
    out = run("setting", "--vmindex", index, "--key", key, "--value", value)
    try:
        return json.loads(out).get("errcode", -1) == 0
    except json.JSONDecodeError:
        return False


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="真正写入（默认只读）")
    ap.add_argument("--index", default="", help="逗号分隔，默认全部")
    args = ap.parse_args(argv)

    insts = instances()
    if not insts:
        print("读不到实例列表（MuMuManager info 失败）")
        return 1
    targets = [i for i in insts if (not args.index or i in args.index.split(","))]
    print(f"实例: {targets}   模式: {'APPLY' if args.apply else 'DRY-RUN'}\n")

    diffs = 0
    for idx in targets:
        cur = settings(idx)
        name = insts[idx].get("name", "?")
        print(f"--- 实例 {idx}  {name}  client={insts[idx].get('adb_host_ip')}:"
              f"{insts[idx].get('adb_port')}")
        for key, (want, why) in CANON.items():
            if key not in cur:
                continue
            now = cur[key]
            if want is None:
                print(f"    {key:26s} = {str(now):14s}    [{why}]")
                continue
            ok = str(now) == want
            mark = "OK " if ok else "DIFF"
            print(f"    {mark} {key:26s} = {str(now):14s} 期望 {want:14s} [{why}]")
            if not ok:
                diffs += 1
                if args.apply:
                    ok2 = apply_setting(idx, key, want)
                    print(f"         -> 写入 {'成功' if ok2 else '失败'}"
                          f"{'（重启实例生效）' if ok2 else ''}")
        print()

    if not args.apply:
        print(f"差异 {diffs} 处。加 --apply 写入；写入后需重启实例生效。")
    else:
        print("写入完成。重启实例：MuMuManager control --vmindex all restart")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
