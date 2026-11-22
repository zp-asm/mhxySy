#!/usr/bin/env python3
"""Fill the open gaps: manifest strings, asset configs, APK string hits, unisec xrefs."""
import struct
import subprocess
import zipfile
from pathlib import Path

APK = Path(r"E:\gamework\mhxyMobile\artifacts\base.apk")
OUT = Path(r"E:\gamework\mhxyMobile\analysis\gap_fill.txt")
SO = Path(r"E:\gamework\mhxyMobile\artifacts\lib\libunisec_x86_64.so")
YBU = Path(r"E:\gamework\mhxyMobile\artifacts\lib\arm64-v8a\libybuaxz.so")
NEEDLES = [
    b"startEmulatorDetect",
    b"GetEmulatorResult",
    b"ybuaxwny",
    b"EmulatorDetectResult",
    b"uploadapk",
    b"ntunisdk_config",
    b"V417IR",
]


def axml_strings(data: bytes):
    if len(data) < 28 or struct.unpack_from("<H", data, 0)[0] != 0x0003:
        # still try to find a string pool
        pass
    # find string pool chunk
    off = 8
    # XML starts with ResXMLTree_header then string pool
    if struct.unpack_from("<H", data, 0)[0] == 0x0003:
        off = struct.unpack_from("<H", data, 2)[0]
    strings = []
    if off + 28 > len(data):
        return strings
    typ, hs, size = struct.unpack_from("<HHI", data, off)
    if typ != 0x0001:
        return strings
    string_count, style_count, flags, strings_start, styles_start = struct.unpack_from("<IIIII", data, off + 8)
    utf8 = bool(flags & (1 << 8))
    offsets = list(struct.unpack_from("<" + "I" * string_count, data, off + 28))
    base = off + strings_start
    for rel in offsets:
        p = base + rel
        if p >= len(data):
            continue
        if utf8:
            # u16 char len, u16 byte len, or u8 if < 0x80
            n = data[p]
            p += 1
            if n & 0x80:
                n = ((n & 0x7F) << 8) | data[p]
                p += 1
            bl = data[p]
            p += 1
            if bl & 0x80:
                bl = ((bl & 0x7F) << 8) | data[p]
                p += 1
            raw = data[p:p + bl]
            try:
                strings.append(raw.decode("utf-8", "replace"))
            except Exception:
                strings.append(repr(raw))
        else:
            n = struct.unpack_from("<H", data, p)[0]
            p += 2
            if n & 0x8000:
                n = ((n & 0x7FFF) << 16) | struct.unpack_from("<H", data, p)[0]
                p += 2
            raw = data[p:p + n * 2]
            strings.append(raw.decode("utf-16-le", "replace"))
    return strings


def interesting_manifest(strings):
    keys = (
        "application", "permission", "activity", "meta-data", "networkSecurityConfig",
        "extractNativeLibs", "debuggable", "UNIFIX", "Messiah", "protect", "uses-sdk",
        "package", "version", "android.permission",
    )
    # return all strings that look like components / permissions / meta
    keep = []
    for s in strings:
        if not s or len(s) > 300:
            continue
        if (
            s.startswith("android.permission")
            or s.startswith("com.netease")
            or s.startswith("android.app")
            or "UNIFIX" in s
            or "network" in s.lower()
            or "debuggable" in s
            or "extractNative" in s
            or s in ("android.permission.INTERNET",)
            or "." in s and any(k in s for k in ("Activity", "Application", "Service", "Provider", "permission"))
        ):
            keep.append(s)
    return keep


def scan_member(zf, info, needle_set):
    hits = []
    if info.file_size > 80_000_000:
        return hits
    data = zf.read(info.filename)
    for n in needle_set:
        start = 0
        c = 0
        while c < 5:
            i = data.find(n, start)
            if i < 0:
                break
            hits.append((info.filename, n.decode(), i, info.file_size))
            start = i + 1
            c += 1
    return hits


def elf_xrefs(path: Path, needle: bytes, max_hits=30):
    from capstone import CS_ARCH_X86, CS_MODE_64, Cs
    data = path.read_bytes()
    # ELF64
    assert data[:4] == b"\x7fELF"
    e_phoff = struct.unpack_from("<Q", data, 32)[0]
    e_phentsize = struct.unpack_from("<H", data, 54)[0]
    e_phnum = struct.unpack_from("<H", data, 56)[0]
    loads = []
    for i in range(e_phnum):
        off = e_phoff + i * e_phentsize
        p_type, p_flags, p_offset, p_vaddr, p_paddr, p_filesz, p_memsz, p_align = struct.unpack_from("<IIQQQQQQ", data, off)
        if p_type == 1:  # PT_LOAD
            loads.append((p_offset, p_vaddr, p_filesz, p_flags))
    def va_to_off(va):
        for o, v, sz, fl in loads:
            if v <= va < v + sz:
                return o + (va - v)
        return None
    def off_to_va(off):
        for o, v, sz, fl in loads:
            if o <= off < o + sz:
                return v + (off - o)
        return None
    str_off = data.find(needle)
    hits = []
    if str_off < 0:
        return {"string_off": None, "xrefs": []}
    str_va = off_to_va(str_off)
    md = Cs(CS_ARCH_X86, CS_MODE_64)
    md.detail = True
    exec_ranges = [(o, v, sz) for o, v, sz, fl in loads if fl & 1]
    for o, v, sz in exec_ranges:
        blob = data[o:o + sz]
        # disasm in 1MB windows
        window = 0x100000
        pos = 0
        while pos < len(blob):
            chunk = blob[pos:pos + window]
            base = v + pos
            for insn in md.disasm(chunk, base):
                text = f"{insn.mnemonic} {insn.op_str}"
                if str_va is not None and (hex(str_va) in text or f"{str_va:#x}" in text):
                    hits.append((insn.address, text))
                # RIP-relative: next_ip + disp == str_va
                if str_va is not None and insn.mnemonic.startswith("lea") or (str_va and "rip" in insn.op_str):
                    # parse disp from op_str like [rip + 0x123]
                    op = insn.op_str
                    if "rip" in op:
                        try:
                            # capstone prints [rip + 0xNN] or [rip - 0xNN]
                            if "+" in op:
                                disp = int(op.split("+")[-1].strip(" ]"), 16)
                                sign = 1
                            elif "-" in op[op.find("rip"):]:
                                disp = int(op.split("-")[-1].strip(" ]"), 16)
                                sign = -1
                            else:
                                disp = 0
                                sign = 1
                            target = insn.address + insn.size + sign * disp
                            if target == str_va:
                                hits.append((insn.address, text + "  -> string"))
                        except Exception:
                            pass
                if len(hits) >= max_hits:
                    return {"string_off": str_off, "string_va": str_va, "xrefs": hits}
            pos += window
    return {"string_off": str_off, "string_va": str_va, "xrefs": hits}


def main():
    lines = []
    with zipfile.ZipFile(APK) as zf:
        manifest = zf.read("AndroidManifest.xml")
        strings = axml_strings(manifest)
        lines.append(f"MANIFEST_STRINGS {len(strings)}")
        for s in interesting_manifest(strings):
            lines.append("M " + s)
        lines.append("--- ALL MANIFEST STRINGS (filtered length) ---")
        for s in strings:
            if s and len(s) < 200:
                lines.append("MS " + s.replace("\n", " "))
        # assets
        for name in (
            "assets/ntunisdk_config",
            "assets/ntunisdk_data",
            "assets/ntunisdk_common_data",
            "assets/emulatordetector_data",
            "res/xml/network_security_config.xml",
            "res/xml/unifix_network_security_config.xml",
        ):
            raw = zf.read(name)
            lines.append(f"\n===== {name} size={len(raw)} =====")
            if name.endswith(".xml"):
                xs = axml_strings(raw)
                for s in xs:
                    lines.append("X " + s)
            else:
                lines.append(raw[:2000].decode("utf-8", "replace"))
        # search needles in non-huge members, skip bulk media
        lines.append("\n===== NEEDLE HITS =====")
        hits = []
        for info in zf.infolist():
            n = info.filename
            if info.file_size == 0 or info.file_size > 30_000_000:
                continue
            if n.startswith("res/") and not n.endswith((".xml", ".json", ".cfg", ".txt")):
                continue
            if any(n.endswith(ext) for ext in (".png", ".jpg", ".ogg", ".mp3", ".webp", ".so")):
                # still scan so and dex and assets and xml
                if not (n.endswith(".so") or n.startswith("assets/") or n.endswith(".dex")):
                    continue
            if n.endswith(".so") and "libGame" in n:
                continue  # scanned separately if needed
            data = zf.read(n)
            for needle in NEEDLES:
                if needle in data:
                    hits.append(f"{needle.decode()} in {n} ({info.file_size})")
        # unique
        for h in sorted(set(hits)):
            lines.append(h)
        # libGame specifically, streaming
        lines.append("\n===== libGame.so needle =====")
        info = zf.getinfo("lib/arm64-v8a/libGame.so")
        with zf.open(info) as f:
            # scan in chunks with overlap
            overlap = 64
            prev = b""
            off = 0
            found = {n: 0 for n in NEEDLES}
            while True:
                chunk = f.read(8 << 20)
                if not chunk:
                    break
                buf = prev + chunk
                for n in NEEDLES:
                    if n in buf:
                        found[n] += buf.count(n)
                prev = buf[-overlap:]
                off += len(chunk)
            for n, c in found.items():
                lines.append(f"libGame {n.decode()} count={c}")

    lines.append("\n===== unisec /proc/net/tcp xrefs =====")
    try:
        xr = elf_xrefs(SO, b"/proc/net/tcp\x00")
        lines.append(str({k: xr[k] for k in xr if k != "xrefs"}))
        for a, t in xr["xrefs"]:
            lines.append(f"  {a:#x}  {t}")
    except Exception as e:
        lines.append("XREF_ERR " + repr(e))

    # also nearby strings in unisec around the hit
    data = SO.read_bytes()
    i = data.find(b"/proc/net/tcp")
    lines.append(f"unisec string fileoff={i:#x}")
    window = data[max(0, i - 80):i + 200]
    strs = []
    cur = []
    for b in window:
        if 32 <= b < 127:
            cur.append(chr(b))
        else:
            if len(cur) >= 4:
                strs.append("".join(cur))
            cur = []
    if len(cur) >= 4:
        strs.append("".join(cur))
    lines.append("NEAR " + " | ".join(strs))

    lines.append("\n===== libybuaxz JNI prologues =====")
    try:
        from capstone import CS_ARCH_ARM64, CS_MODE_ARM, Cs
        ydata = YBU.read_bytes()
        # dynsym
        e_shoff = struct.unpack_from("<Q", ydata, 40)[0]
        e_shentsize = struct.unpack_from("<H", ydata, 58)[0]
        e_shnum = struct.unpack_from("<H", ydata, 60)[0]
        e_shstrndx = struct.unpack_from("<H", ydata, 62)[0]
        shoff = e_shoff
        def shdr(i):
            o = shoff + i * e_shentsize
            return struct.unpack_from("<IIQQQQIIQQ", ydata, o)
        # name, type, flags, addr, offset, size, link, info, addralign, entsize
        shstr = shdr(e_shstrndx)
        strtab_off = shstr[4]
        dynsym = dynstr = None
        for i in range(e_shnum):
            h = shdr(i)
            name = ydata[strtab_off + h[0]:].split(b"\x00", 1)[0].decode()
            if name == ".dynsym":
                dynsym = h
            elif name == ".dynstr":
                dynstr = h
        lines.append(f"dynsym={dynsym is not None} dynstr={dynstr is not None}")
        if dynsym and dynstr:
            md = Cs(CS_ARCH_ARM64, CS_MODE_ARM)
            entsize = dynsym[9] or 24
            count = dynsym[5] // entsize
            for i in range(count):
                o = dynsym[4] + i * entsize
                st_name, st_info, st_other, st_shndx, st_value, st_size = struct.unpack_from("<IBBHQQ", ydata, o)
                name = ydata[dynstr[4] + st_name:].split(b"\x00", 1)[0].decode("utf-8", "replace")
                if "Java_com_netease_ybuax" in name or name in ("JNI_OnLoad",):
                    lines.append(f"SYM {name} va={st_value:#x} size={st_size:#x} shndx={st_shndx}")
                    # file offset via PT_LOAD
                    e_phoff = struct.unpack_from("<Q", ydata, 32)[0]
                    e_phentsize = struct.unpack_from("<H", ydata, 54)[0]
                    e_phnum = struct.unpack_from("<H", ydata, 56)[0]
                    foff = None
                    for pi in range(e_phnum):
                        po = e_phoff + pi * e_phentsize
                        p_type, p_flags, p_offset, p_vaddr, p_paddr, p_filesz, p_memsz, p_align = struct.unpack_from("<IIQQQQQQ", ydata, po)
                        if p_type == 1 and p_vaddr <= st_value < p_vaddr + p_filesz:
                            foff = p_offset + (st_value - p_vaddr)
                            break
                    if foff is None:
                        lines.append("  no file offset")
                        continue
                    blob = ydata[foff:foff + min(st_size or 64, 160)]
                    nins = 0
                    for insn in md.disasm(blob, st_value):
                        lines.append(f"  {insn.address:#x}: {insn.mnemonic} {insn.op_str}")
                        nins += 1
                        if nins >= 25:
                            break
    except Exception as e:
        lines.append("YBU_ERR " + repr(e))

    OUT.write_text("\n".join(lines), encoding="utf-8")
    print("wrote", OUT, "lines", len(lines))


if __name__ == "__main__":
    main()
