"""从 ELF 动态符号表里按名字取函数地址（用于被剥 section 头、且代码加密的 .so）。

思路：
    · 用磁盘文件的 program headers 找到 PT_DYNAMIC（文件头还在）
    · 用 DT_SYMTAB / DT_STRTAB / DT_STRSZ 拿到符号表与字符串表
    · 符号表/字符串表在文件里通常是明文；代码段要看内存 dump
    · 输出 st_value（虚拟地址），配合 dump 的 image_base 就能反汇编

用法：
    python tools/elf_dynsym.py <file.so> <name> [<name2> ...]
"""
from __future__ import annotations

import struct
import sys


def parse(path: str):
    d = open(path, "rb").read()
    e_phoff = struct.unpack("<Q", d[0x20:0x28])[0]
    e_phentsize = struct.unpack("<H", d[0x36:0x38])[0]
    e_phnum = struct.unpack("<H", d[0x38:0x3A])[0]
    dyn = None
    for i in range(e_phnum):
        o = e_phoff + i * e_phentsize
        p_type = struct.unpack("<I", d[o:o + 4])[0]
        if p_type == 2:  # PT_DYNAMIC
            p_offset, p_vaddr = struct.unpack("<QQ", d[o + 8:o + 24])
            p_filesz = struct.unpack("<Q", d[o + 32:o + 40])[0]
            dyn = (p_offset, p_vaddr, p_filesz)
    if not dyn:
        raise SystemExit("no PT_DYNAMIC")
    off, vaddr, size = dyn
    tags = {}
    for i in range(0, size, 16):
        tag, val = struct.unpack("<QQ", d[off + i:off + i + 16])
        if tag == 0:
            break
        tags[tag] = val
    return d, tags


def va_to_off(d: bytes, tags: dict, va: int) -> int | None:
    """把虚拟地址映射到文件偏移（用 PT_LOAD 反查）。"""
    e_phoff = struct.unpack("<Q", d[0x20:0x28])[0]
    e_phentsize = struct.unpack("<H", d[0x36:0x38])[0]
    e_phnum = struct.unpack("<H", d[0x38:0x3A])[0]
    for i in range(e_phnum):
        o = e_phoff + i * e_phentsize
        p_type = struct.unpack("<I", d[o:o + 4])[0]
        if p_type != 1:
            continue
        p_offset, p_vaddr = struct.unpack("<QQ", d[o + 8:o + 24])
        p_filesz = struct.unpack("<Q", d[o + 32:o + 40])[0]
        if p_vaddr <= va < p_vaddr + p_filesz:
            return p_offset + (va - p_vaddr)
    return None


def main(argv: list[str]) -> int:
    if len(argv) < 3:
        print(__doc__)
        return 1
    path, names = argv[1], argv[2:]
    d, tags = parse(path)
    symtab, strtab, strsz = tags.get(6), tags.get(5), tags.get(10, 0)
    if not symtab or not strtab:
        raise SystemExit("missing DT_SYMTAB/DT_STRTAB")
    sym_off = va_to_off(d, tags, symtab)
    str_off = va_to_off(d, tags, strtab)
    print("DT_SYMTAB=0x%x(off 0x%x)  DT_STRTAB=0x%x(off 0x%x)  STRSZ=0x%x"
          % (symtab, sym_off or 0, strtab, str_off or 0, strsz))

    want = {n.encode() for n in names}
    found = 0
    limit = strsz or (1 << 20)
    for i in range(0, 300000):
        o = sym_off + i * 24
        if o + 24 > len(d):
            break
        st_name, st_info, st_other, st_shndx, st_value, st_size = struct.unpack(
            "<IBBHQQ", d[o:o + 24])
        if st_name >= limit:
            continue
        p = str_off + st_name
        e = d.find(b"\0", p)
        if e < 0 or e - p > 200:
            continue
        nm = d[p:e]
        if nm in want:
            print("  0x%08x  %-60s  size=%d  (idx %d)" % (st_value, nm.decode(), st_size, i))
            found += 1
            if found == len(want):
                break
    if not found:
        print("未找到；符号可能被剥离")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
