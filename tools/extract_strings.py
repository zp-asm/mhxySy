#!/usr/bin/env python3
"""Extract printable strings (and UTF-16) from binaries into per-file .txt for grepping."""
import sys, os, re, pathlib

PRINT = re.compile(rb"[\x20-\x7e]{4,}")
WIDE = re.compile(rb"(?:[\x20-\x7e]\x00){4,}")

def strings(path, minlen=4):
    data = pathlib.Path(path).read_bytes()
    out = []
    for m in PRINT.finditer(data):
        if len(m.group()) >= minlen:
            out.append((m.start(), m.group().decode("ascii", "replace")))
    for m in WIDE.finditer(data):
        s = m.group().decode("utf-16-le", "replace")
        if len(s) >= minlen:
            out.append((m.start(), "[w]" + s))
    out.sort(key=lambda t: t[0])
    return out

def main():
    src = pathlib.Path(sys.argv[1])
    dst = pathlib.Path(sys.argv[2])
    dst.mkdir(parents=True, exist_ok=True)
    files = [src] if src.is_file() else sorted(
        p for p in src.rglob("*") if p.is_file()
    )
    for p in files:
        try:
            items = strings(str(p))
        except Exception as e:
            print("skip", p, e); continue
        outp = dst / (p.name + ".strings.txt")
        with outp.open("w", encoding="utf-8") as f:
            for off, s in items:
                f.write(f"{off:08x} {s}\n")
        print(f"{p.name:34s} strings={len(items):7d} -> {outp.name}")

if __name__ == "__main__":
    main()
