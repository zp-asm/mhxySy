"""在 Cocos 对象里定位 _parent / _children 偏移。

方法：
    · 已知一批 vptr（Node/Sprite/Layer 家族）
    · 对每个对象，扫描 0..0x300 内的 qword
    · 若某个 qword 指向同一 dump 区内，且目标首字段属于 vptr 集合 → 它指向另一个节点
    · 统计这些指针出现最多的偏移 → 就是 _parent 或 _children 的槽位

用法：
    python tools/cocos_find_links.py <dump.bin> <base>
"""
from __future__ import annotations

import collections
import struct
import sys

VPTRS = {
    0x400024fa72e8, 0x400024fa79c0, 0x400024fa8088, 0x400024fa88f0,
    0x400024fa8fc8, 0x400024fab068, 0x400024facc68, 0x400024faecc8,
    0x400024fac3d0, 0x400024fbcc78, 0x400024fbd488, 0x400024fbd4b0,
    0x400024fd06d0, 0x400024fd8e48, 0x400024fdefd0, 0x400025442ab8,
    0x400024facca0, 0x400024fad440, 0x400024faece8, 0x400024faed30,
    0x400024faf870, 0x400024feeae0, 0x400024fefde0, 0x40002507b2c0,
}
PRIMARY = 0x400024fbd4b0          # 最常见的 Sprite vptr


def is_node_ptr(data: bytes, base: int, v: int) -> bool:
    off = v - base
    if off < 0 or off + 8 > len(data) or off % 8:
        return False
    head = struct.unpack_from("<Q", data, off)[0]
    return head in VPTRS


def main(argv: list[str]) -> int:
    if len(argv) < 3:
        print(__doc__)
        return 1
    path, base = argv[1], int(argv[2], 0)
    d = open(path, "rb").read()
    pat = struct.pack("<Q", PRIMARY)

    objs = []
    i = 0
    while True:
        i = d.find(pat, i)
        if i < 0 or len(objs) >= 4000:
            break
        if i % 8 == 0 and i + 0x300 < len(d):
            objs.append(i)
        i += 1
    print("对象 %d 个" % len(objs))
    if not objs:
        return 1

    link_off = collections.Counter()
    head_off = collections.Counter()   # 首字段指向节点（= _children 数组首元素? / _parent）
    for o in objs:
        for off in range(8, 0x300, 8):
            v = struct.unpack_from("<Q", d, o + off)[0]
            if v and is_node_ptr(d, base, v):
                link_off[off] += 1

    n = len(objs)
    print("\n指向其它节点的指针，出现最多的偏移：")
    for off, c in link_off.most_common(12):
        print("   +0x%03x  命中 %4d/%d (%.1f%%)" % (off, c, n, 100.0 * c / n))

    # 取最热偏移，看它指向的数组结构（begin/end/cap）
    if link_off:
        hot = link_off.most_common(1)[0][0]
        print("\n最热偏移 +0x%x 的前 3 个对象详情：" % hot)
        shown = 0
        for o in objs:
            v = struct.unpack_from("<Q", d, o + hot)[0]
            if not v or not is_node_ptr(d, base, v):
                continue
            # 看后续两个 qword 是否构成 begin/end/cap
            nb, ne, nc = struct.unpack_from("<QQQ", d, o + hot)
            print("   obj@0x%x: begin=0x%x end=0x%x cap=0x%x  (size=%d)"
                  % (base + o, nb, ne, nc, (ne - nb) // 8 if ne >= nb else -1))
            shown += 1
            if shown >= 3:
                break
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
