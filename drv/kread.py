"""宿主/VM 侧客户端：通过 mhxy_drv 读目标进程内存。

用法（在 VM 内跑，需要 root）：
    python3 kread.py verify            # 阶梯验证：STAT → PGD → 读 dalvik → 读 arena
    python3 kread.py read 0x400060174000 256
    python3 kread.py scan 0x400060174000 0x7e8c000 'lua|Lua|Messiah'

当前版本用 ctypes 直接打 ioctl，不依赖 adb；也可以被宿主侧通过 adb shell 调起来。
"""
from __future__ import annotations

import ctypes
import os
import struct
import sys

DEV = "/dev/mhxy_drv"
MAGIC = ord("M")


def _iowr(nr: int, size: int) -> int:
    # _IOWR('M', nr, struct): dir=3(write|read)<<30 | size<<16 | 'M'<<8 | nr
    return (3 << 30) | (size << 16) | (MAGIC << 8) | nr


class Stat(ctypes.Structure):
    _fields_ = [("ok", ctypes.c_uint32), ("pad", ctypes.c_uint32),
                ("page_offset_base", ctypes.c_uint64), ("nsyms", ctypes.c_uint64)]


class Pgd(ctypes.Structure):
    _fields_ = [("pid", ctypes.c_uint32), ("pad", ctypes.c_uint32),
                ("probe_va", ctypes.c_uint64), ("pgd", ctypes.c_uint64),
                ("pgd_off", ctypes.c_uint64)]


class Rw(ctypes.Structure):
    _fields_ = [("pid", ctypes.c_uint32), ("size", ctypes.c_uint32),
                ("addr", ctypes.c_uint64), ("buf", ctypes.c_uint64),
                ("write", ctypes.c_uint32), ("pad", ctypes.c_uint32)]


class Drv:
    def __init__(self, path: str = DEV):
        self.fd = os.open(path, os.O_RDWR)

    def _ioctl(self, nr: int, obj) -> int:
        return ctypes.cdll.LoadLibrary(None).ioctl(
            self.fd, _iowr(nr, ctypes.sizeof(obj)), ctypes.byref(obj))

    # ---- API ----
    def stat(self) -> Stat:
        s = Stat()
        if self._ioctl(3, s) < 0:
            raise OSError(ctypes.get_errno(), "STAT failed")
        return s

    def pgd(self, pid: int, probe_va: int = 0x02000000) -> Pgd:
        p = Pgd(pid=pid, probe_va=probe_va)
        if self._ioctl(2, p) < 0:
            raise OSError(ctypes.get_errno(), "PGD failed")
        return p

    def read(self, pid: int, addr: int, size: int) -> bytes:
        buf = ctypes.create_string_buffer(size)
        r = Rw(pid=pid, size=size, addr=addr,
               buf=ctypes.addressof(buf), write=0)
        if self._ioctl(1, r) < 0:
            raise OSError(ctypes.get_errno(), f"READ 0x{addr:x}+{size} failed")
        return buf.raw[:size]

    def write(self, pid: int, addr: int, data: bytes) -> None:
        buf = ctypes.create_string_buffer(data, len(data))
        r = Rw(pid=pid, size=len(data), addr=addr,
               buf=ctypes.addressof(buf), write=1)
        if self._ioctl(1, r) < 0:
            raise OSError(ctypes.get_errno(), f"WRITE 0x{addr:x} failed")


def find_pid(name: str = "com.netease.my") -> int:
    for d in os.listdir("/proc"):
        if not d.isdigit():
            continue
        try:
            with open(f"/proc/{d}/cmdline", "rb") as f:
                if f.read().split(b"\0")[0].decode(errors="ignore") == name:
                    return int(d)
        except OSError:
            continue
    raise SystemExit(f"进程未找到: {name}")


def hexdump(b: bytes, base: int = 0, width: int = 16, limit: int = 8) -> str:
    out = []
    for i in range(0, min(len(b), width * limit), width):
        chunk = b[i:i + width]
        hexs = " ".join(f"{x:02x}" for x in chunk)
        text = "".join(chr(x) if 32 <= x < 127 else "." for x in chunk)
        out.append(f"{base + i:016x}  {hexs:<{width * 3}}  |{text}|")
    return "\n".join(out)


def cmd_verify(drv: Drv) -> int:
    pid = find_pid()
    print(f"pid = {pid}")
    st = drv.stat()
    print(f"STAT: page_offset_base=0x{st.page_offset_base:x} symbols={st.nsyms}/5")

    pg = drv.pgd(pid)
    print(f"PGD : 0x{pg.pgd:x}  (mm->pgd offset = 0x{pg.pgd_off:x})")

    print("\n[1] 对照：dalvik main space（用户态本来就可读）")
    d = drv.read(pid, 0x02000000, 64)
    print(hexdump(d, 0x02000000, limit=2))

    print("\n[2] 关键：Houdini 客户机 arena（用户态读会 EIO）")
    try:
        d = drv.read(pid, 0x400060174000, 256)
        nz = sum(1 for x in d if x)
        print(f"读到 {len(d)} 字节，非零 {nz} 字节")
        print(hexdump(d, 0x400060174000, limit=6))
        if nz:
            print("\n>>> 成功：绕过 vm_ops 拿到客户机内存")
            return 0
        print("\n>>> 返回全 0：该页 PTE 不存在（换别的 arena 段再试）")
        return 2
    except OSError as e:
        print(f">>> 失败: {e}")
        return 3


def cmd_read(drv: Drv, addr: int, size: int) -> int:
    pid = find_pid()
    print(hexdump(drv.read(pid, addr, size), addr))
    return 0


def cmd_scan(drv: Drv, start: int, length: int, pattern: str) -> int:
    pid = find_pid()
    import re
    rx = re.compile(pattern.encode())
    CH = 1 << 20
    hits = 0
    for off in range(0, length, CH):
        try:
            d = drv.read(pid, start + off, min(CH, length - off))
        except OSError:
            continue
        for m in rx.finditer(d):
            print(f"hit @ 0x{start + off + m.start():x}  {d[max(0, m.start()-16):m.start()+48]!r}")
            hits += 1
            if hits > 50:
                return 0
    print(f"共 {hits} 处")
    return 0


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 1
    drv = Drv()
    cmd = argv[1]
    if cmd == "verify":
        return cmd_verify(drv)
    if cmd == "read":
        return cmd_read(drv, int(argv[2], 0), int(argv[3], 0))
    if cmd == "scan":
        return cmd_scan(drv, int(argv[2], 0), int(argv[3], 0), argv[4])
    print("未知命令")
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
