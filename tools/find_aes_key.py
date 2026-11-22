"""在进程内存里搜 AES key schedule，反推密钥。

原理：AES 的轮密钥扩展是确定性的。若内存里存在 176B(AES-128) / 208B(AES-192) /
240B(AES-256) 的轮密钥数组，就能用标准扩展算法验证：
    w[i] = w[i-Nk] ^ (SubWord(RotWord(w[i-1])) ^ Rcon[i/Nk])
命中即说明找到了真正的 AES 密钥（前 16/24/32 字节就是 key）。

用法：
    python tools/find_aes_key.py <mem_dump.bin> [--base 0x400000000000] [--align 4]
"""
from __future__ import annotations

import sys

SBOX = bytes.fromhex(
    "637c777bf26b6fc53001672bfed7ab76ca82c97dfa5947f0add4a2af9ca472c0"
    "b7fd9326363ff7cc34a5e5f171d8311504c723c31896059a071280e2eb27b275"
    "09832c1a1b6e5aa0523bd6b329e32f8453d100ed20fcb15b6acbbe394a4c58cf"
    "d0efaafb434d338545f9027f503c9fa851a3408f929d38f5bcb6da2110fff3d2"
    "cd0c13ec5f974417c4a77e3d645d197360814fdc222a908846eeb814de5e0bdb"
    "e0323a0a4906245cc2d3ac629195e479e7c8376d8dd54ea96c56f4ea657aae08"
    "ba78252e1ca6b4c6e8dd741f4bbd8b8a703eb5664803f60e613557b986c11d9e"
    "e1f8981169d98e949b1e87e9ce5528df8ca1890dbfe6426841992d0fb054bb16"
)
RCON = [0x01, 0x02, 0x04, 0x08, 0x10, 0x20, 0x40, 0x80, 0x1B, 0x36]


def expand(key: bytes) -> bytes:
    nk = len(key) // 4
    total = 4 * (nk + 7)
    w = [list(key[4 * i:4 * i + 4]) for i in range(nk)]
    for i in range(nk, total):
        t = list(w[i - 1])
        if i % nk == 0:
            t = t[1:] + t[:1]
            t = [SBOX[b] for b in t]
            t[0] ^= RCON[i // nk - 1]
        elif nk > 6 and i % nk == 4:
            t = [SBOX[b] for b in t]
        w.append([w[i - nk][j] ^ t[j] for j in range(4)])
    return bytes(b for word in w for b in word)


def scan(buf: bytes, base: int = 0, align: int = 4, limit: int = 0):
    n = len(buf) if not limit else min(len(buf), limit)
    found = []
    for keylen, schedlen in ((32, 240), (16, 176), (24, 208)):
        step = keylen
        for off in range(0, n - schedlen, align):
            key = buf[off:off + keylen]
            if key.count(0) == keylen:        # 全零跳过
                continue
            if expand(key) == buf[off:off + schedlen]:
                found.append((base + off, keylen, key.hex()))
    return found


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 1
    path = argv[1]
    base = 0
    align = 4
    if "--base" in argv:
        base = int(argv[argv.index("--base") + 1], 0)
    if "--align" in argv:
        align = int(argv[argv.index("--align") + 1], 0)
    data = open(path, "rb").read()
    print("扫描 %s  %.1f MB  align=%d" % (path, len(data) / 1048576, align))
    hits = scan(data, base, align)
    print("命中 %d 个 key schedule" % len(hits))
    for addr, kl, key in hits[:40]:
        print("  0x%x  AES-%d  key=%s" % (addr, kl * 8, key))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
