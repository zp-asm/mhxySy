"""把游戏进程的可写内存"分类全量"dump 下来，并建立可检索索引。

为什么不全 dump：
    进程 rw 共 6.1 GB，其中 dalvik LinearAlloc / main space / JIT cache 占 3.3 GB，
    对逆向没用。真正有价值的是：
        · [anon:scudo:primary / secondary]  游戏 native 堆（Lua 状态、玩家对象、任务字符串）
        · [anon]                            其他匿名区（可能含解密后的代码/资源）
        · 已解密的 libGame 代码段（另有工具处理）

用法：
    python tools/dump_memory.py [--out E:\\out\\memdump] [--max-mb 3000]
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
import time

SERIAL = "127.0.0.1:16384"
DEV_DIR = "/data/local/tmp/memdump"
SKIP_PAT = re.compile(r"(dalvik|jit-cache|memfd|vdex|\.bss|stack|vectors|linker)", re.I)
KEEP_PAT = re.compile(r"(scudo|\[anon\])", re.I)


def sh(cmd: str, timeout: int = 120) -> str:
    r = subprocess.run(["adb", "-s", SERIAL, "shell", cmd], capture_output=True,
                       text=True, encoding="utf-8", errors="replace", timeout=timeout)
    return r.stdout


def parse_maps(pid: str):
    raw = subprocess.run(["adb", "-s", SERIAL, "shell", f"cat /proc/{pid}/maps"],
                         capture_output=True).stdout
    txt = raw.decode("utf-16", "replace") if raw[:2] in (b"\xff\xfe", b"\xfe\xff") \
        else raw.decode("utf-8", "replace")
    rows = []
    for line in txt.splitlines():
        m = re.match(r"([0-9a-f]+)-([0-9a-f]+)\s+(\S+)\s+\S+\s+\S+\s+\S+\s*(.*)", line)
        if not m:
            continue
        s, e = int(m.group(1), 16), int(m.group(2), 16)
        perm, name = m.group(3), m.group(4).strip()
        if "rw" not in perm:
            continue
        if SKIP_PAT.search(name) or not KEEP_PAT.search(name):
            continue
        rows.append((s, e, name))
    return rows


def merge(rows, gap: int = 0x100000):
    """合并相邻区间，减少 dd 次数。"""
    rows.sort()
    out = []
    for s, e, name in rows:
        if out and s - out[-1][1] <= gap:
            out[-1][1] = max(out[-1][1], e)
            out[-1][2] = out[-1][2] + " + " + name[:24]
        else:
            out.append([s, e, name])
    return out


def main(argv: list[str]) -> int:
    out_dir = r"E:\out\memdump"
    if "--out" in argv:
        out_dir = argv[argv.index("--out") + 1]
    max_mb = 3000
    if "--max-mb" in argv:
        max_mb = int(argv[argv.index("--max-mb") + 1])
    os.makedirs(out_dir, exist_ok=True)

    pid = sh("pidof com.netease.my").strip()
    rows = parse_maps(pid)
    rows = merge(rows)
    total = sum(e - s for s, e, _ in rows)
    print(f"候选区间 {len(rows)} 个，合计 {total/1048576:.0f} MB（上限 {max_mb} MB）")

    sh(f"mkdir -p {DEV_DIR}")
    index = []
    done = 0
    t0 = time.time()
    for i, (s, e, name) in enumerate(rows):
        size = e - s
        if done + size > max_mb * 1048576:
            print("达到上限，停止")
            break
        skip = s // 4096
        cnt = size // 4096
        if cnt == 0:
            continue
        dev_file = f"{DEV_DIR}/r{i:03d}.bin"
        sh(f"dd if=/proc/{pid}/mem of={dev_file} bs=4096 skip={skip} count={cnt} 2>/dev/null")
        local = os.path.join(out_dir, f"r{i:03d}.bin")
        subprocess.run(["adb", "-s", SERIAL, "pull", dev_file, local], capture_output=True)
        sh(f"rm -f {dev_file}")
        if os.path.exists(local):
            got = os.path.getsize(local)
            index.append((s, size, got, name))
            done += size
            print(f"  [{i:03d}] 0x{s:x} {size/1048576:6.1f}MB -> {got/1048576:6.1f}MB  {name[:50]}")
    with open(os.path.join(out_dir, "index.txt"), "w", encoding="utf-8") as f:
        for s, size, got, name in index:
            f.write(f"0x{s:x}\t{size}\t{got}\t{name}\n")
    print(f"\n完成：{len(index)} 个文件，{done/1048576:.0f} MB，用时 {time.time()-t0:.0f}s")
    print("索引：", os.path.join(out_dir, "index.txt"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
