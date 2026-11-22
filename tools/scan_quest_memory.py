"""从游戏内存里读主线任务（不依赖图色）。

原理（实测）：
    · 主线标题是 Lua 字符串，形如 "主线-长寿迷踪"（UTF-8，前面有 le32 长度）
    · 目标是**富文本**，形如 "#W击败#Y李靖·心魔#l"（#X 是颜色，结尾 #l）
    · 这些字符串在堆里每次启动地址不同 → 每次重新扫描（不需要指针链）
    · 扫描 79 MB：Python ~1s，C/Go ~30-50ms（可 1 Hz 轮询）

用法：
    python tools/scan_quest_memory.py <dump.bin> [--base 0xADDR]
    python tools/scan_quest_memory.py --live            # 直接从设备 dump 后扫描
"""
from __future__ import annotations

import re
import struct
import subprocess
import sys

SERIAL = "127.0.0.1:16384"
HEAP_BASE = 0x73741AD2A000      # 实测：主线字符串集中在这一段
HEAP_SIZE = 0x4F00000           # 79 MB

TAG = re.compile(r"#[A-Za-z]")


def strip_tags(s: str) -> str:
    return TAG.sub("", s).replace("#l", "").strip()


def scan(buf: bytes, base: int) -> dict:
    """返回 {'titles': [(va, text)], 'goals': [(va, text)]}"""
    txt = buf.decode("utf-8", "ignore")
    titles, goals = [], []
    seen = set()

    # 主线标题："主线-xxx"
    for m in re.finditer(r"主线[-－][\u4e00-\u9fff·]{2,20}", txt):
        s = m.group(0)
        if s not in seen:
            seen.add(s)
            titles.append((base + len(txt[:m.start()].encode("utf-8", "ignore")), s))

    # 目标：富文本可能由多段颜色拼接（如 #W击败#Y李靖·心魔#l）→ 逐段取到 #l 为止再拼接
    act = re.compile(r"((?:#[A-Za-z][^#\x00]{1,40}?)+)#l")
    for m in act.finditer(txt):
        s = strip_tags(m.group(1))
        if not s or "%" in s:
            continue
        if any(k in s for k in ("击败", "前往", "寻找", "交付", "回禀", "对话", "采集", "护送")):
            if s not in seen:
                seen.add(s)
                goals.append((base + len(txt[:m.start()].encode("utf-8", "ignore")), s))
    return {"titles": titles, "goals": goals}


def live_dump() -> bytes:
    pid = subprocess.run(["adb", "-s", SERIAL, "shell", "pidof", "com.netease.my"],
                         capture_output=True, text=True).stdout.strip()
    skip = HEAP_BASE // 4096
    cnt = HEAP_SIZE // 4096
    subprocess.run(["adb", "-s", SERIAL, "shell",
                    f"dd if=/proc/{pid}/mem of=/data/local/tmp/q.bin bs=4096 skip={skip} count={cnt}"],
                   capture_output=True)
    subprocess.run(["adb", "-s", SERIAL, "pull", "/data/local/tmp/q.bin", r"E:\out\q.bin"],
                   capture_output=True)
    return open(r"E:\out\q.bin", "rb").read()


def main(argv: list[str]) -> int:
    if "--live" in argv:
        print("从设备 dump 中（79 MB）...")
        data = live_dump()
        base = HEAP_BASE
    elif len(argv) > 1:
        data = open(argv[1], "rb").read()
        base = int(argv[argv.index("--base") + 1], 0) if "--base" in argv else 0
    else:
        print(__doc__)
        return 1

    res = scan(data, base)
    print("=== 主线标题 ===")
    for va, s in res["titles"][:8]:
        print("  0x%x  %s" % (va, s))
    print("=== 当前目标（富文本已去标签）===")
    for va, s in res["goals"][:12]:
        print("  0x%x  %s" % (va, s))
    if not res["titles"] and not res["goals"]:
        print("未命中（可能不在该区域，或界面未打开）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
