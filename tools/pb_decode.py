"""最小 protobuf wire-format 解码器（无 schema，纯裸解）。

用途：内存里扫到 protobuf 消息后，直接把字段/值打印出来，
用于确认"玩家状态是不是 protobuf"以及找出字段含义。

用法：
    python tools/pb_decode.py <文件> <起始偏移> [长度]
    python tools/pb_decode.py E:\\out\\scudo46.bin 0x1C0D8 128
"""
from __future__ import annotations

import sys

WIRE = {0: "varint", 1: "64bit", 2: "len", 5: "32bit"}


def read_varint(buf: bytes, i: int) -> tuple[int, int] | None:
    shift = 0
    val = 0
    start = i
    while i < len(buf) and shift < 64:
        b = buf[i]
        val |= (b & 0x7F) << shift
        i += 1
        if not b & 0x80:
            return val, i
        shift += 7
    return None


def try_parse(buf: bytes, depth: int = 0, limit: int = 40) -> list[str] | None:
    out: list[str] = []
    i = 0
    count = 0
    while i < len(buf) and count < limit:
        r = read_varint(buf, i)
        if not r:
            return None
        tag, i = r
        field, wire = tag >> 3, tag & 7
        if field == 0 or wire not in WIRE:
            return None
        if wire == 0:
            r = read_varint(buf, i)
            if not r:
                return None
            val, i = r
            out.append("  " * depth + f"#{field} varint = {val}")
        elif wire == 1:
            if i + 8 > len(buf):
                return None
            out.append("  " * depth + f"#{field} 64bit = {buf[i:i+8].hex()}")
            i += 8
        elif wire == 5:
            if i + 4 > len(buf):
                return None
            out.append("  " * depth + f"#{field} 32bit = {buf[i:i+4].hex()}")
            i += 4
        else:  # LEN
            r = read_varint(buf, i)
            if not r:
                return None
            ln, i = r
            if ln > len(buf) - i:
                return None
            data = buf[i:i + ln]
            i += ln
            try:
                txt = data.decode("utf-8")
                printable = all(32 <= ord(c) < 0x30000 for c in txt)
            except Exception:
                txt, printable = "", False
            if printable and txt:
                out.append("  " * depth + f"#{field} str[{ln}] = {txt!r}")
            else:
                # 试着当嵌套消息
                sub = try_parse(data, depth + 1, limit) if ln > 1 else None
                if sub:
                    out.append("  " * depth + f"#{field} msg[{ln}] {{")
                    out.extend(sub)
                    out.append("  " * depth + "}")
                else:
                    out.append("  " * depth + f"#{field} bytes[{ln}] = {data[:32].hex()}")
        count += 1
    return out if out else None


def main(argv: list[str]) -> int:
    if len(argv) < 3:
        print(__doc__)
        return 1
    path = argv[1]
    off = int(argv[2], 0)
    ln = int(argv[3], 0) if len(argv) > 3 else 128
    data = open(path, "rb").read()
    chunk = data[off:off + ln]
    print(f"=== {path} @0x{off:x} ({ln} 字节) ===")
    print("hex:", chunk.hex())
    res = try_parse(chunk)
    if res:
        print("--- protobuf 解码 ---")
        for line in res:
            print(line)
    else:
        print("不是合法的 protobuf")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
