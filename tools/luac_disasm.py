"""Lua 5.1 字节码反汇编器（纯 Python，无外部依赖）。

为什么自己写：unluac 的 jar 下载源全被 SourceForge 拦成 HTML；
而反汇编已足够看清游戏 Lua 的 API 名与调用关系。

用法：
    python tools/luac_disasm.py <a.luac> [--grep 关键词]
"""
from __future__ import annotations

import struct
import sys

OPNAMES = [
    "MOVE", "LOADK", "LOADBOOL", "LOADNIL", "GETUPVAL", "GETGLOBAL", "GETTABLE",
    "SETGLOBAL", "SETUPVAL", "SETTABLE", "NEWTABLE", "SELF", "ADD", "SUB", "MUL",
    "DIV", "MOD", "POW", "UNM", "NOT", "LEN", "CONCAT", "JMP", "EQ", "LT", "LE",
    "TEST", "TESTSET", "CALL", "TAILCALL", "RETURN", "FORLOOP", "FORPREP",
    "TFORLOOP", "SETLIST", "CLOSE", "CLOSURE", "VARARG",
]


class Proto:
    def __init__(self):
        self.source = ""
        self.linedefined = 0
        self.lastlinedefined = 0
        self.nups = 0
        self.numparams = 0
        self.is_vararg = 0
        self.maxstack = 0
        self.code: list[int] = []
        self.consts: list = []
        self.protos: list["Proto"] = []
        self.lines: list[int] = []


class R:
    def __init__(self, b: bytes, p: int = 0):
        self.b, self.p = b, p

    def u8(self):
        v = self.b[self.p]; self.p += 1; return v

    def u32(self):
        v = struct.unpack_from("<I", self.b, self.p)[0]; self.p += 4; return v

    def i32(self):
        v = struct.unpack_from("<i", self.b, self.p)[0]; self.p += 4; return v

    def string(self):
        n = self.u32()
        if n == 0:
            return None
        n -= 1
        s = self.b[self.p:self.p + n]; self.p += n
        return s


def read_proto(r: R) -> Proto:
    p = Proto()
    src = r.string()
    p.source = (src or b"").decode("latin1")
    p.linedefined = r.i32()
    p.lastlinedefined = r.i32()
    p.nups = r.u8(); p.numparams = r.u8(); p.is_vararg = r.u8(); p.maxstack = r.u8()
    n = r.u32()
    p.code = [r.u32() for _ in range(n)]
    n = r.u32()
    for _ in range(n):
        t = r.u8()
        if t == 0:
            p.consts.append(None)
        elif t == 1:
            p.consts.append(bool(r.u8()))
        elif t == 3:
            p.consts.append(struct.unpack_from("<d", r.b, r.p)[0]); r.p += 8
        elif t == 4:
            s = r.string()
            p.consts.append((s or b"").decode("utf-8", "replace"))
        else:
            raise ValueError("const type %d" % t)
    n = r.u32()
    for _ in range(n):
        p.protos.append(read_proto(r))
    n = r.u32()
    p.lines = [r.i32() for _ in range(n)]
    n = r.u32()
    for _ in range(n):
        r.string(); r.i32(); r.i32()
    n = r.u32()
    for _ in range(n):
        r.string()
    return p


def read_chunk(path: str) -> Proto | None:
    b = open(path, "rb").read()
    if b[:4] != b"\x1bLua":
        return None
    r = R(b, 4)
    if r.u8() != 0x51:
        print("不是 Lua 5.1")
        return None
    # 5.1 头：format, endian, sizeof(int), sizeof(size_t), sizeof(Instruction),
    #         sizeof(lua_Number), integral flag  = 7 字节
    for _ in range(7):
        r.u8()
    return read_proto(r)


def kname(p: Proto, k: int) -> str:
    v = p.consts[k] if k < len(p.consts) else None
    if isinstance(v, str):
        return '"%s"' % v
    return repr(v)


def rk(p: Proto, x: int) -> str:
    if x & 0x100:
        return "K" + kname(p, x & 0xFF)
    return "R%d" % x


def disasm(p: Proto, depth: int = 0, out: list[str] | None = None) -> list[str]:
    out = out if out is not None else []
    ind = "  " * depth
    name = p.source or "?"
    out.append("%s-- func @%d..%d  params=%d vararg=%d stack=%d consts=%d protos=%d  (%s)"
               % (ind, p.linedefined, p.lastlinedefined, p.numparams, p.is_vararg,
                  p.maxstack, len(p.consts), len(p.protos), name))
    for pc, ins in enumerate(p.code):
        op = ins & 0x3F
        A = (ins >> 6) & 0xFF
        C = (ins >> 14) & 0x1FF
        B = (ins >> 23) & 0x1FF
        Bx = (ins >> 14) & 0x3FFFF
        sBx = Bx - 131071
        m = OPNAMES[op] if op < len(OPNAMES) else "OP%d" % op
        line = p.lines[pc] if pc < len(p.lines) else 0
        if m in ("GETGLOBAL", "SETGLOBAL"):
            s = "%s%-9s %-8s %s" % (ind, m, "R%d" % A, kname(p, Bx))
        elif m in ("GETTABLE", "SETTABLE"):
            s = "%s%-9s %-8s %s %s" % (ind, m, "R%d" % A, rk(p, B), rk(p, C))
        elif m == "SELF":
            s = "%s%-9s %-8s %s %s" % (ind, m, "R%d" % A, rk(p, B), rk(p, C))
        elif m == "LOADK":
            s = "%s%-9s %-8s %s" % (ind, m, "R%d" % A, kname(p, Bx))
        elif m == "CLOSURE":
            s = "%s%-9s %-8s <proto %d>" % (ind, m, "R%d" % A, Bx)
        elif m in ("CALL", "TAILCALL", "RETURN"):
            s = "%s%-9s A=%d B=%d C=%d" % (ind, m, A, B, C)
        elif m in ("JMP", "FORPREP", "FORLOOP"):
            s = "%s%-9s -> %d" % (ind, m, pc + 1 + sBx)
        elif m in ("ADD", "SUB", "MUL", "DIV", "MOD", "POW", "CONCAT"):
            s = "%s%-9s %-8s %s %s" % (ind, m, "R%d" % A, rk(p, B), rk(p, C))
        elif m == "TEST" or m == "TESTSET":
            s = "%s%-9s A=%d C=%d" % (ind, m, A, C)
        else:
            s = "%s%-9s A=%d B=%d C=%d" % (ind, m, A, B, C)
        out.append("%s; [%3d] L%-4d %s" % (ind, pc, line, s[len(ind):]))
    for i, sp in enumerate(p.protos):
        out.append("%s-- nested %d:" % (ind, i))
        disasm(sp, depth + 1, out)
    return out


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 1
    p = read_chunk(argv[1])
    if not p:
        print("解析失败")
        return 1
    lines = disasm(p)
    if "--grep" in argv:
        kw = argv[argv.index("--grep") + 1]
        sel = [ln for ln in lines if kw in ln]
        print("\n".join(sel[:200]))
        print("\n命中 %d 行" % len(sel))
    else:
        print("\n".join(lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
