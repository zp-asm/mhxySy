"""在 ARM64 解密镜像里找某个字符串的引用（ADRP+ADD 相对寻址）。

ARM64 取字符串地址的典型序列：
    adrp xN, page(str)      ; 0x90000000 族
    add  xN, xN, #(str&0xFFF) ; 0x91000000 族
本工具扫描整段代码，找出所有指向目标 VA 的 (adrp, add) 组合，
再反汇编附近 12 条指令，用于定位分发器/解包函数。

用法：
    python tools/find_str_xrefs_arm64.py <image.bin> <image_base> <target_va>
"""
from __future__ import annotations

import sys

from capstone import CS_ARCH_ARM64, CS_MODE_ARM, Cs


def decode_adrp(w: int, pc: int) -> tuple[int, int] | None:
    if (w & 0x9F000000) != 0x90000000:
        return None
    rd = w & 0x1F
    immlo = (w >> 29) & 0x3
    immhi = (w >> 5) & 0x7FFFF
    imm = ((immhi << 2) | immlo) << 12
    if imm & (1 << 32):          # 符号扩展（33 位）
        imm -= 1 << 33
    return rd, (pc & ~0xFFF) + imm


def decode_add_imm(w: int) -> tuple[int, int, int] | None:
    if (w & 0x7F800000) != 0x11000000:
        return None
    rd = w & 0x1F
    rn = (w >> 5) & 0x1F
    imm = (w >> 10) & 0xFFF
    if (w >> 22) & 0x1:
        imm <<= 12
    return rd, rn, imm


def main(argv: list[str]) -> int:
    if len(argv) < 4:
        print(__doc__)
        return 1
    path, base, target = argv[1], int(argv[2], 0), int(argv[3], 0)
    data = open(path, "rb").read()
    md = Cs(CS_ARCH_ARM64, CS_MODE_ARM)

    tpage, toff = target & ~0xFFF, target & 0xFFF
    hits = []
    for off in range(0, len(data) - 8, 4):
        w = int.from_bytes(data[off:off + 4], "little")
        a = decode_adrp(w, base + off)
        if not a or a[1] != tpage:
            continue
        rd = a[0]
        # 往后 4 条指令内找 add xRD, xRD, #toff
        for k in range(1, 5):
            w2 = int.from_bytes(data[off + 4 * k: off + 4 * k + 4], "little")
            ai = decode_add_imm(w2)
            if ai and ai[0] == rd and ai[1] == rd and ai[2] == toff:
                hits.append(off)
                break

    print("命中 %d 处引用 0x%x" % (len(hits), target))
    for h in hits[:10]:
        print("\n=== 引用 @ 文件偏移 0x%x (VA 0x%x) ===" % (h, base + h))
        code = data[max(0, h - 40): h + 60]
        for ins in md.disasm(code, base + max(0, h - 40)):
            mark = "   <== 引用点" if ins.address == base + h else ""
            print("  0x%x: %-8s %s%s" % (ins.address, ins.mnemonic, ins.op_str, mark))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
