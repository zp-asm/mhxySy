#!/usr/bin/env python3
"""Second pass: config decode, cfg blob context, unisec pointer xrefs, manifest attrs."""
import base64
import json
import struct
import zipfile
from pathlib import Path

APK = Path(r"E:\gamework\mhxyMobile\artifacts\base.apk")
SO = Path(r"E:\gamework\mhxyMobile\artifacts\lib\libunisec_x86_64.so")
WNY = Path(r"E:\gamework\mhxyMobile\artifacts\wnyklrieFile")
OUT = Path(r"E:\gamework\mhxyMobile\analysis\gap_fill2.txt")
lines = []


def add(s=""):
    lines.append(s)


# --- emulatordetector_data ---
with zipfile.ZipFile(APK) as zf:
    raw = zf.read("assets/emulatordetector_data")
    try:
        obj = json.loads(base64.b64decode(raw))
    except Exception as e:
        obj = None
        add("EMU_DATA_DECODE_ERR " + repr(e))
    if isinstance(obj, dict):
        add("EMU_DATA_KEYS " + str(len(obj)))
        for k in sorted(obj):
            v = obj[k]
            sv = str(v)
            # keep short non-secret values; redact long tokens
            if any(x in k.upper() for x in ("KEY", "SECRET", "TOKEN", "PASS", "APPID", "APP_ID")):
                add(f"  {k} = <redacted len={len(sv)}>")
            else:
                add(f"  {k} = {sv[:180]}")

    blob = zf.read("assets/_ntcfgss.dat")
    add(f"\nNTCFG magic {blob[:16]!r} size={len(blob)}")
    for needle in (b"EmulatorDetectResult", b"V417IR", b"startEmulator", b"ybuax", b"methodId", b"uploadapk"):
        idxs = []
        start = 0
        while len(idxs) < 6:
            i = blob.find(needle, start)
            if i < 0:
                break
            idxs.append(i)
            start = i + 1
        add(f"NTCFG {needle.decode()} hits={blob.count(needle)} first={idxs}")
        for i in idxs[:3]:
            frag = blob[max(0, i - 60):i + 80]
            # printable
            shown = "".join(chr(b) if 32 <= b < 127 else "." for b in frag)
            add(f"  @{i}: {shown}")

# --- wnyklrie ---
w = WNY.read_bytes().strip()
add(f"\nWNY len={len(w)} alphabet_ok={all(c in b'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/=' for c in w)}")
try:
    dec = base64.b64decode(w, validate=False)
    add(f"WNY decoded_len={len(dec)} head={dec[:32]!r}")
    printable = sum(32 <= b < 127 or b in (9, 10, 13) for b in dec) / max(1, len(dec))
    add(f"WNY decoded_printable_ratio={printable:.3f}")
except Exception as e:
    add("WNY_B64_ERR " + repr(e))

# --- unisec ELF + pointer search ---
data = SO.read_bytes()
assert data[:4] == b"\x7fELF"
e_phoff, e_shoff = struct.unpack_from("<QQ", data, 32)
e_phentsize, e_phnum, e_shentsize, e_shnum, e_shstrndx = struct.unpack_from("<HHHHH", data, 54)
add(f"\nUNISEC phoff={e_phoff:#x} phnum={e_phnum} shoff={e_shoff:#x} shnum={e_shnum} machine={struct.unpack_from('<H', data, 18)[0]}")
loads = []
for i in range(e_phnum):
    off = e_phoff + i * e_phentsize
    p_type, p_flags, p_offset, p_vaddr, p_paddr, p_filesz, p_memsz, p_align = struct.unpack_from("<IIQQQQQQ", data, off)
    add(f"  PH type={p_type} flags={p_flags:#x} off={p_offset:#x} va={p_vaddr:#x} filesz={p_filesz:#x}")
    if p_type == 1:
        loads.append((p_offset, p_vaddr, p_filesz, p_flags))

needle = b"/proc/net/tcp\x00"
soff = data.find(needle)
sva = None
for o, v, sz, fl in loads:
    if o <= soff < o + sz:
        sva = v + (soff - o)
        break
add(f"string fileoff={soff:#x} va={sva}")
if sva is not None:
    pat = struct.pack("<Q", sva)
    pat4 = struct.pack("<I", sva & 0xFFFFFFFF)
    c8 = data.count(pat)
    c4 = data.count(pat4)
    add(f"qword hits={c8} dword hits={c4}")
    start = 0
    shown = 0
    while shown < 8:
        i = data.find(pat, start)
        if i < 0:
            i = data.find(pat4, start) if c8 == 0 else -1
        if i < 0:
            break
        add(f"  ptr at fileoff={i:#x}")
        start = i + 1
        shown += 1
    # also search 32-bit relative: target = insn_end + disp, look in exec for disp
    # simpler: scan executable for imm32 equal to (sva - (va+len)) is hard.
    # Search lea encoding: 48 8d 0d/05/15/1d/2d/35/3d disp32
    execs = [(o, v, sz) for o, v, sz, fl in loads if fl & 1]
    lea_hits = []
    for o, v, sz in execs:
        blob = data[o:o + sz]
        for i in range(len(blob) - 7):
            if blob[i] in (0x48, 0x4C) and blob[i + 1] == 0x8D and (blob[i + 2] & 0xC7) == 0x05:
                disp = struct.unpack_from("<i", blob, i + 3)[0]
                insn_va = v + i
                target = insn_va + 7 + disp
                if target == sva:
                    lea_hits.append(insn_va)
                    if len(lea_hits) >= 12:
                        break
        if len(lea_hits) >= 12:
            break
    add("lea_hits " + ", ".join(hex(x) for x in lea_hits))

# nearby cstrings in .rodata around the string, wider
i = soff
region = data[max(0, i - 256):i + 512]
cur = []
strs = []
for b in region:
    if 32 <= b < 127:
        cur.append(chr(b))
    else:
        if len(cur) >= 6:
            strs.append("".join(cur))
        cur = []
add("WIDE_NEAR " + " | ".join(strs[:40]))

# other proc strings
add("\nUNISEC proc-like strings:")
start = 0
n = 0
while n < 40:
    j = data.find(b"/proc/", start)
    if j < 0:
        break
    end = data.find(b"\x00", j)
    s = data[j:end if end != -1 else j + 80]
    if all(32 <= c < 127 for c in s) and len(s) < 120:
        add("  " + s.decode())
        n += 1
    start = j + 6

OUT.write_text("\n".join(lines), encoding="utf-8")
print("wrote", OUT, "lines", len(lines))
