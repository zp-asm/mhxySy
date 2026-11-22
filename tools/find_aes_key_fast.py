"""快速搜 AES key schedule（numpy 向量化预筛 + 完整校验）。

为什么这么写：6 GB 内存里逐个候选做完整 key expansion 太慢。
先用一次轮密钥扩展（SubWord(RotWord(w[-1])) ^ Rcon ^ w[0]）做向量化比对，
幸存者再走完整扩展验证 —— 命中率足够且可跑。

用法：
    python tools/find_aes_key_fast.py <dump.bin> [--base 0xADDR] [--align 4]
"""
from __future__ import annotations

import sys

import numpy as np

SBOX = np.frombuffer(bytes.fromhex(
    "637c777bf26b6fc53001672bfed7ab76ca82c97dfa5947f0add4a2af9ca472c0"
    "b7fd9326363ff7cc34a5e5f171d8311504c723c31896059a071280e2eb27b275"
    "09832c1a1b6e5aa0523bd6b329e32f8453d100ed20fcb15b6acbbe394a4c58cf"
    "d0efaafb434d338545f9027f503c9fa851a3408f929d38f5bcb6da2110fff3d2"
    "cd0c13ec5f974417c4a77e3d645d197360814fdc222a908846eeb814de5e0dbd"
    "e0323a0a4906245cc2d3ac629195e479e7c8376d8dd54ea96c56f4ea657aae08"
    "ba78252e1ca6b4c6e8dd741f4bbd8b8a703eb5664803f60e613557b986c11d9e"
    "e1f8981169d98e949b1e87e9ce5528df8ca1890dbfe6426841992d0fb054bb16"
), dtype=np.uint8)

RCON = [0x01, 0x02, 0x04, 0x08, 0x10, 0x20, 0x40, 0x80, 0x1B, 0x36]


def expand_bytes(key: bytes) -> bytes:
    nk = len(key) // 4
    total = 4 * (nk + 7)
    w = [list(key[4 * i:4 * i + 4]) for i in range(nk)]
    for i in range(nk, total):
        t = list(w[i - 1])
        if i % nk == 0:
            t = t[1:] + t[:1]
            t = [int(SBOX[b]) for b in t]
            t[0] ^= RCON[i // nk - 1]
        elif nk > 6 and i % nk == 4:
            t = [int(SBOX[b]) for b in t]
        w.append([w[i - nk][j] ^ t[j] for j in range(4)])
    return bytes(b for word in w for b in word)


def prescreen(buf: np.ndarray, keylen: int, align: int) -> np.ndarray:
    """只验证第一轮扩展（w[nk] 与内存里第 nk 个 word 是否一致）。"""
    n = len(buf) - (keylen + 256)
    pos = np.arange(0, max(n, 0), align)
    if pos.size == 0:
        return pos
    last = keylen - 4                       # w[nk-1] 的起始
    t = buf[pos + last + 1]                 # RotWord: b1,b2,b3,b0
    t2 = buf[pos + last + 2]
    t3 = buf[pos + last + 3]
    t0 = buf[pos + last + 0]
    r = np.empty((pos.size, 4), dtype=np.uint8)
    r[:, 0] = SBOX[t] ^ RCON[0] ^ buf[pos + 0]
    r[:, 1] = SBOX[t2] ^ buf[pos + 1]
    r[:, 2] = SBOX[t3] ^ buf[pos + 2]
    r[:, 3] = SBOX[t0] ^ buf[pos + 3]
    ok = ((r[:, 0] == buf[pos + keylen]) & (r[:, 1] == buf[pos + keylen + 1]) &
          (r[:, 2] == buf[pos + keylen + 2]) & (r[:, 3] == buf[pos + keylen + 3]))
    return pos[ok]


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 1
    path = argv[1]
    base = int(argv[argv.index("--base") + 1], 0) if "--base" in argv else 0
    align = int(argv[argv.index("--align") + 1], 0) if "--align" in argv else 4
    data = open(path, "rb").read()
    buf = np.frombuffer(data, dtype=np.uint8)
    print("扫描 %s  %.1f MB align=%d" % (path, len(data) / 1048576, align))

    total = 0
    for keylen in (32, 16, 24):
        pos = prescreen(buf, keylen, align)
        print("  AES-%d 预筛候选 %d" % (keylen * 8, len(pos)))
        sched = keylen + 7 * 4 * 4 if False else {16: 176, 24: 208, 32: 240}[keylen]
        for p in pos[:2000]:
            key = data[int(p):int(p) + keylen]
            if expand_bytes(key) == data[int(p):int(p) + sched]:
                total += 1
                print("   ★ 0x%x  AES-%d  key=%s" % (base + int(p), keylen * 8, key.hex()))
    print("命中 %d 个" % total)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
