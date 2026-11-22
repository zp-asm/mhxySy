"""从内存 dump 里提取 Lua 5.1 字节码块（.luac）。

原理：Lua 5.1 的二进制 chunk 以 "\\x1bLua\\x51" 开头，结构为：
    header(12B) | sizeupvalues(1B) | Function
    Function = source(string) | linedefined(i32) | lastlinedefined(i32)
               | nups(1) numparams(1) is_vararg(1) maxstacksize(1)
               | code(i32 n + n*4) | constants(i32 n + entries)
               | protos(i32 n + each) | debug(...)
本工具按格式走一遍算出总长，然后落盘。

用法：
    python tools/extract_luac.py --out E:\\out\\lua
"""
from __future__ import annotations

import os
import struct
import sys
import glob
import hashlib

SIG = b"\x1bLua"
# Lua 5.1 标准头：sig + 51 00 01 04 04 04 08 00
HDR = bytes([0x1B,0x4C,0x75,0x61,0x51,0x00,0x01,0x04,0x04,0x04,0x08,0x00])


class Reader:
    def __init__(self, buf: bytes, pos: int):
        self.b = buf
        self.p = pos

    def u8(self) -> int:
        v = self.b[self.p]; self.p += 1; return v

    def u32(self) -> int:
        v = struct.unpack_from("<I", self.b, self.p)[0]; self.p += 4; return v

    def i32(self) -> int:
        v = struct.unpack_from("<i", self.b, self.p)[0]; self.p += 4; return v

    def string(self) -> bytes | None:
        n = self.u32()
        if n == 0:
            return None
        n -= 1
        s = self.b[self.p:self.p + n]; self.p += n
        return s

    def function(self, endian_ok=True):
        self.string()                    # source
        self.i32(); self.i32()           # linedefined / lastdefined
        self.u8(); self.u8(); self.u8(); self.u8()   # nups, numparams, is_vararg, maxstack
        n = self.u32()                   # code
        self.p += n * 4
        n = self.u32()                   # constants
        for _ in range(n):
            t = self.u8()
            if t == 0:
                pass                      # nil
            elif t == 1:
                self.u8()                 # boolean
            elif t == 3:
                self.p += 8               # number (double)
            elif t == 4:
                self.string()             # string
            else:
                raise ValueError("bad const type %d" % t)
        n = self.u32()                   # nested protos
        for _ in range(n):
            self.function()
        # debug
        n = self.u32(); self.p += n * 8   # lineinfo
        n = self.u32(); self.p += n * 8   # locvars (string + 2 ints)
        n = self.u32(); self.p += n * 8   # upvalue names
        return


def chunk_len(buf: bytes, pos: int) -> int | None:
    """返回该 chunk 的总字节数，失败返回 None。Lua5.1 头固定 12 字节。"""
    try:
        if buf[pos:pos + 12] != HDR:
            return None
        r = Reader(buf, pos + 12)
        r.function()
        return r.p - pos
    except Exception:
        return None


def main(argv: list[str]) -> int:
    out_dir = r"E:\out\lua"
    if "--out" in argv:
        out_dir = argv[argv.index("--out") + 1]
    os.makedirs(out_dir, exist_ok=True)

    files = sorted(glob.glob(r"E:\out\*.bin")) + sorted(glob.glob(r"E:\out\memdump\*.bin")) \
        + sorted(glob.glob(r"E:\out\libs\*.bin"))
    files = [f for f in files if os.path.getsize(f) > 1_000_000]

    total = 0
    ok = 0
    for p in files:
        d = open(p, "rb").read()
        i = 0
        while True:
            i = d.find(SIG, i)
            if i < 0:
                break
            ln = chunk_len(d, i)
            if ln and 16 < ln < 4_000_000:
                blob = d[i:i + ln]
                h = hashlib.md5(blob).hexdigest()[:8]
                name = os.path.join(out_dir, f"{os.path.basename(p)[:-4]}_{i:x}_{h}.luac")
                open(name, "wb").write(blob)
                total += ln
                ok += 1
            i += 4
    print(f"提取 {ok} 个 chunk，合计 {total/1048576:.1f} MB -> {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
