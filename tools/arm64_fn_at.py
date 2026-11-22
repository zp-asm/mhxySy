"""在 ARM64 内存镜像里，从某个地址往上找函数起点并反汇编。

用法：
    python tools/arm64_fn_at.py <image.bin> <image_base> <target_va> [指令数]
"""
from __future__ import annotations

import sys

from capstone import CS_ARCH_ARM64, CS_MODE_ARM, Cs

PROLOGUES = (
    0xA9B00000,   # stp x29, x30, [sp, #-imm]!
    0xA9A00000,
    0xD1000000,   # sub sp, sp, #imm
    0xD1010000,
)


def is_prologue(w: int) -> bool:
    if (w & 0xFFC00000) == 0xA9800000:      # stp ...!, [sp, #-x]
        return True
    if (w & 0xFF800000) == 0xD1000000:      # sub sp, sp, #imm
        return True
    return False


def main(argv: list[str]) -> int:
    if len(argv) < 4:
        print(__doc__)
        return 1
    path, base, target = argv[1], int(argv[2], 0), int(argv[3], 0)
    n = int(argv[4]) if len(argv) > 4 else 120
    data = open(path, "rb").read()
    off = target - base
    if off < 0 or off >= len(data):
        print("target 不在镜像里")
        return 1

    # 往上找函数起点（最多 0x2000）
    start = off
    for back in range(0, 0x2000, 4):
        p = off - back
        if p < 0:
            break
        w = int.from_bytes(data[p:p + 4], "little")
        if is_prologue(w):
            start = p
            break
    fn_va = base + start
    print("函数起点: VA 0x%x (距 target -0x%x)" % (fn_va, off - start))

    md = Cs(CS_ARCH_ARM64, CS_MODE_ARM)
    code = data[start:start + n * 4]
    for i, ins in enumerate(md.disasm(code, fn_va)):
        mark = "   <== target" if ins.address == target else ""
        print("  0x%x: %-10s %s%s" % (ins.address, ins.mnemonic, ins.op_str, mark))
        if i >= n:
            break
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
