"""在内存 dump 里定位 Cocos2d-x 节点对象（通过 std::string SSO 特征）。

原理：
    cocos2d::Node 里有 std::string _name。libstdc++ 的 SSO 布局是
        struct string { char* ptr; size_t len; char buf[16]; }
    短名字（<=15 字节）时 ptr 指向自身 buf（即 ptr == &obj + 16），len = 名字长度。

    所以内存里会出现这样的 32+ 字节模式：
        [8B ptr = 本结构地址+16][8B len][name 字符...]

    找到它就能反推 std::string 的地址；节点对象基址 = 该地址 - offsetof(_name)。
    节点里还有 _position(x,y float)、_contentSize(w,h float)、_scaleX/_scaleY、_visible 等。

用法：
    python tools/cocos_find_node.py <dump.bin> <base> <名字>
"""
from __future__ import annotations

import struct
import sys


def find_sso_strings(data: bytes, base: int, name: bytes):
    """返回 [(string_obj_va, chars_va)]"""
    hits = []
    ln = len(name)
    start = 0
    while True:
        i = data.find(name, start)
        if i < 0:
            break
        start = i + 1
        if i < 16:
            continue
        ptr = struct.unpack_from("<Q", data, i - 16)[0]
        sz = struct.unpack_from("<Q", data, i - 8)[0]
        chars_va = base + i
        if ptr == chars_va and sz == ln:
            hits.append((chars_va - 16, chars_va))
    return hits


def dump_node(data: bytes, base: int, str_obj_va: int, window: int = 0x300):
    """把 std::string 之前的一段按 4/8 字节打印，找 position/contentSize。"""
    off = str_obj_va - base
    lo = max(0, off - window)
    print("=== 候选节点附近（字符串对象 VA 0x%x）===" % str_obj_va)
    print("%-14s %-22s %s" % ("addr", "u64", "float×2"))
    for p in range(lo, off, 8):
        if p + 8 > len(data):
            break
        u = struct.unpack_from("<Q", data, p)[0]
        f2 = struct.unpack_from("<ff", data, p)
        if u == 0:
            continue
        mark = ""
        if 0.0 <= f2[0] <= 2000 and 0.0 <= f2[1] <= 2000 and (f2[0] or f2[1]):
            mark = "   <= 可能是 position/size"
        print("0x%012x  %-22s %10.3f, %-10.3f%s" % (base + p, hex(u), f2[0], f2[1], mark))


def main(argv: list[str]) -> int:
    if len(argv) < 4:
        print(__doc__)
        return 1
    path, base, name = argv[1], int(argv[2], 0), argv[3].encode()
    data = open(path, "rb").read()
    hits = find_sso_strings(data, base, name)
    print('名字 "%s" 的 SSO 命中: %d 处' % (name.decode(), len(hits)))
    for s_va, c_va in hits[:5]:
        print("   std::string @0x%x  chars @0x%x" % (s_va, c_va))
    if hits:
        dump_node(data, base, hits[0][0])
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
