"""对 Cocos2d-x 对象做字段偏移统计，找出 _position / _contentSize。

方法：遍历成千上万个同 vptr 的对象，看哪个偏移上最常出现"像屏幕坐标"的
float 对（x∈[0,960], y∈[0,540]）或"像尺寸"的对（0<w,h<2000）。
出现率最高的偏移就是该字段。

用法：
    python tools/cocos_layout_stats.py <dump.bin> <vptr>
"""
from __future__ import annotations

import collections
import struct
import sys

MAX_SCAN = 0x300


def main(argv: list[str]) -> int:
    if len(argv) < 3:
        print(__doc__)
        return 1
    path = argv[1]
    vt = int(argv[2], 0)
    d = open(path, "rb").read()
    pat = struct.pack("<Q", vt)

    objs = []
    i = 0
    while True:
        i = d.find(pat, i)
        if i < 0 or len(objs) >= 20000:
            break
        if i % 8 == 0 and i + MAX_SCAN < len(d):
            objs.append(i)
        i += 1
    print("对象 %d 个（vptr 0x%x）" % (len(objs), vt))
    if not objs:
        return 1

    pos_hits = collections.Counter()
    size_hits = collections.Counter()
    for o in objs:
        for off in range(8, MAX_SCAN, 4):
            p = o + off
            a, b = struct.unpack_from("<ff", d, p)
            if not (-1e6 < a < 1e6 and -1e6 < b < 1e6):
                continue
            # 排除 0/1 这类常量字段：要求非零且在范围内
            if 1.0 < a < 960.0 and 1.0 < b < 540.0:
                pos_hits[off] += 1
            if 4.0 < a <= 1200.0 and 4.0 < b <= 1200.0:
                size_hits[off] += 1

    n = len(objs)
    print("\n最像 position 的偏移（x∈[0,960], y∈[0,540]）：")
    for off, c in pos_hits.most_common(10):
        print("   +0x%03x  命中 %5d/%d (%.1f%%)" % (off, c, n, 100.0 * c / n))
    print("\n最像 contentSize 的偏移（0<w,h≤2000）：")
    for off, c in size_hits.most_common(10):
        print("   +0x%03x  命中 %5d/%d (%.1f%%)" % (off, c, n, 100.0 * c / n))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
