"""在 libGame.so 的真实代码页里扫 ARM64 AES 指令，定位加解密实现。

背景：libGame.so 无 section 头、且包含大块加密/压缩数据，
直接全文件扫 AES 会命中大量假阳性。所以先用 capstone 判定"代码页"，再扫。
"""
from __future__ import annotations

import struct
import sys
from collections import Counter

from capstone import CS_ARCH_ARM64, CS_MODE_ARM, Cs

PATH = sys.argv[1] if len(sys.argv) > 1 else r"E:\out\libs\libGame.so"
PAGE = 0x1000
LIMIT = 0x432D9E0          # 第一个 PT_LOAD 的 filesz（R+X）

AES_OPS = {
    0x4E284800: "AESE",
    0x4E285800: "AESD",
    0x4E286800: "AESMC",
    0x4E287800: "AESIMC",
}


def main() -> int:
    data = open(PATH, "rb").read()
    md = Cs(CS_ARCH_ARM64, CS_MODE_ARM)
    limit = min(len(data), LIMIT)
    pages = limit // PAGE

    code_pages = []
    for p in range(pages):
        off = p * PAGE
        ins = list(md.disasm(data[off:off + 64], off))
        good = sum(1 for i in ins if i.mnemonic != "udf")
        if good >= 6:
            code_pages.append(off)

    print("扫描 %d 页 -> 代码页 %d 页 (%d KB)" % (pages, len(code_pages), len(code_pages) * 4))

    hits = []
    for off in code_pages:
        seg = data[off:off + PAGE]
        for i in range(0, PAGE - 4, 4):
            w = struct.unpack("<I", seg[i:i + 4])[0]
            for op, name in AES_OPS.items():
                if (w & 0xFFFFFC00) == op:
                    hits.append((off + i, name))

    print("代码页内 AES 指令:", len(hits), dict(Counter(n for _, n in hits)))

    clusters = []
    for off, name in hits:
        if clusters and off - clusters[-1][-1][0] < 2048:
            clusters[-1].append((off, name))
        else:
            clusters.append([(off, name)])
    clusters.sort(key=lambda c: -len(c))

    print("聚簇 %d 个，最大的 10 个：" % len(clusters))
    for c in clusters[:10]:
        kinds = dict(Counter(n for _, n in c))
        print("  va=0x%x  条数=%d  %s" % (c[0][0], len(c), kinds))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
