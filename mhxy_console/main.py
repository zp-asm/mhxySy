"""中控台入口。

    python -m mhxy_console.main list                          # 列出 MuMu 实例
    python -m mhxy_console.main shot --index 0                # 抓一帧存盘
    python -m mhxy_console.main crop --index 0 --box 860,120,80,40 --name task
    python -m mhxy_console.main match --index 0 --template task
    python -m mhxy_console.main run --indexes 0,1 --loops 5   # 多实例并跑
    python -m mhxy_console.main isolate --indexes 0,1         # 每实例差异化指纹
"""
from __future__ import annotations

import argparse
import asyncio
import json
import random
import string
import sys
from pathlib import Path

import cv2

from .adb import AdbDevice
from .mumu import MuMuManager
from .vision import Vision
from .worker import InstanceWorker, make_click_step, step_recover

ROOT = Path(__file__).resolve().parent
FRAMES = ROOT.parent / "frames"
TEMPLATES = ROOT.parent / "templates"
PACKAGE = "com.netease.my"


def cmd_list(_args) -> int:
    m = MuMuManager()
    insts = m.instances()
    if not insts:
        print("没有实例")
        return 1
    for i in insts:
        print(f"[{i.index}] {i.name}\tserial={i.serial}\tandroid={i.android_version}\t"
              f"started={i.started}\tpid={i.pid}\twnd={i.render_wnd}")
    return 0


def _serial(args) -> str:
    m = MuMuManager()
    insts = {i.index: i for i in m.instances()}
    if args.index not in insts:
        raise SystemExit(f"实例 {args.index} 不存在，先跑 list")
    return insts[args.index].serial


def cmd_shot(args) -> int:
    serial = _serial(args)
    dev = AdbDevice(serial)
    dev.connect()
    FRAMES.mkdir(parents=True, exist_ok=True)
    p = FRAMES / (args.out or f"frame_{args.index}.png")
    dev.screencap_png(p)
    print(f"saved {p} ({p.stat().st_size} bytes)")
    return 0


def cmd_crop(args) -> int:
    frames = sorted(FRAMES.glob("*.png"))
    if not frames:
        raise SystemExit("没有帧，先跑 shot")
    img = cv2.imread(str(frames[-1]), cv2.IMREAD_COLOR)
    x, y, w, h = (int(v) for v in args.box.split(","))
    v = Vision(TEMPLATES)
    p = v.add_from_frame(args.name, img, x, y, w, h)
    print(f"template saved {p}  ({w}x{h}) from {frames[-1].name}")
    return 0


def cmd_match(args) -> int:
    frames = sorted(FRAMES.glob("*.png"))
    if not frames:
        raise SystemExit("没有帧，先跑 shot")
    img = cv2.imread(str(frames[-1]), cv2.IMREAD_COLOR)
    v = Vision(TEMPLATES)
    hit = v.find(img, args.template, args.threshold)
    print(json.dumps(hit.__dict__ if hit else None, ensure_ascii=False))
    return 0 if hit else 2


async def _run_many(args) -> int:
    m = MuMuManager()
    insts = {i.index: i for i in m.instances()}
    indexes = [int(x) for x in args.indexes.split(",")]
    v = Vision(TEMPLATES)
    steps = [make_click_step(t) for t in (args.click or [])] + [
        __import__("mhxy_console.worker", fromlist=["Step"]).Step(
            name="recover", run=step_recover, cooldown=2.0)
    ]

    async def one(idx: int):
        inst = insts.get(idx)
        if not inst:
            print(f"[{idx}] 跳过：实例不存在")
            return
        w = InstanceWorker(inst.serial, name=inst.name, vision=v)
        try:
            await w.run(steps, loops=args.loops)
        except Exception as e:  # noqa: BLE001
            print(f"[{idx}] 停止: {e}")
        finally:
            s = w.stats
            print(f"[{idx}] frames={s.frames} taps={s.taps} errors={s.errors} "
                  f"elapsed={s.started_at and round(__import__('time').time() - s.started_at, 1)}")

    await asyncio.gather(*(one(i) for i in indexes))
    return 0


def cmd_isolate(args) -> int:
    """每实例给不同的设备身份（规避服务端指纹聚类）。"""
    m = MuMuManager()
    indexes = [int(x) for x in args.indexes.split(",")]
    for idx in indexes:
        aid = "".join(random.choices("0123456789abcdef", k=16))
        mac = "02:00:%02x:%02x:%02x:%02x" % tuple(random.randint(0, 255) for _ in range(4))
        imei = "86" + "".join(random.choices(string.digits, k=13))
        rent = [
            m.set_simulation(idx, "android_id", aid),
            m.set_simulation(idx, "mac_address", mac),
            m.set_simulation(idx, "imei", imei),
        ]
        print(f"[{idx}] android_id={aid} mac={mac} imei={imei} -> "
              f"{[r.get('errcode') for r in rent]}")
    return 0


def cmd_app(args) -> int:
    m = MuMuManager()
    for idx in [int(x) for x in args.indexes.split(",")]:
        if args.action == "launch":
            print(idx, m.app_launch(idx, PACKAGE))
        else:
            print(idx, m.app_close(idx, PACKAGE))
    return 0


def main(argv: list[str] | None = None) -> int:
    try:  # Windows 控制台 UTF-8
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass
    ap = argparse.ArgumentParser(prog="mhxy-console")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("list").set_defaults(func=cmd_list)

    p = sub.add_parser("shot")
    p.add_argument("--index", type=int, default=0)
    p.add_argument("--out")
    p.set_defaults(func=cmd_shot)

    p = sub.add_parser("crop")
    p.add_argument("--box", required=True, help="x,y,w,h")
    p.add_argument("--name", required=True)
    p.set_defaults(func=cmd_crop)

    p = sub.add_parser("match")
    p.add_argument("--index", type=int, default=0)
    p.add_argument("--template", required=True)
    p.add_argument("--threshold", type=float, default=0.86)
    p.set_defaults(func=cmd_match)

    p = sub.add_parser("run")
    p.add_argument("--indexes", default="0")
    p.add_argument("--loops", type=int, default=None)
    p.add_argument("--click", action="append", help="模板名，可多次")
    p.set_defaults(func=lambda a: asyncio.run(_run_many(a)))

    p = sub.add_parser("isolate")
    p.add_argument("--indexes", default="0")
    p.set_defaults(func=cmd_isolate)

    p = sub.add_parser("app")
    p.add_argument("--indexes", default="0")
    p.add_argument("--action", choices=["launch", "close"], default="launch")
    p.set_defaults(func=cmd_app)

    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
