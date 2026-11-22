#!/usr/bin/env python3
"""Disassemble the libunisec lea site and pull a few manifest integers."""
import struct
import zipfile
from pathlib import Path
from capstone import CS_ARCH_X86, CS_MODE_64, Cs

SO = Path(r"E:\gamework\mhxyMobile\artifacts\lib\libunisec_x86_64.so")
OUT = Path(r"E:\gamework\mhxyMobile\analysis\gap_fill3.txt")
data = SO.read_bytes()
md = Cs(CS_ARCH_X86, CS_MODE_64)
md.detail = True
# dump 0x120 bytes before and 0x180 after the lea, then note calls
start = 0x7339f - 0x80
blob = data[start:start + 0x280]
lines = []
for insn in md.disasm(blob, start):
    mark = ""
    if insn.address == 0x7339f:
        mark = "   <== lea /proc/net/tcp"
    if insn.mnemonic.startswith("call") or insn.mnemonic.startswith("j"):
        mark += ""
    lines.append(f"{insn.address:#x}: {insn.mnemonic} {insn.op_str}{mark}")

# also list call targets in a wider window 0x73000-0x74000
lines.append("\n--- calls in 0x73000-0x73c00 ---")
blob2 = data[0x73000:0x73c00]
for insn in md.disasm(blob2, 0x73000):
    if insn.mnemonic == "call":
        lines.append(f"{insn.address:#x}: call {insn.op_str}")

OUT.write_text("\n".join(lines), encoding="utf-8")
print("insns", len(lines))
