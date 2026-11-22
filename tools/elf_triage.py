#!/usr/bin/env python3
"""ELF triage: imports/exports matrix focused on anti-cheat + anti-debug primitives."""
import sys, pathlib, json
from elftools.elf.elffile import ELFFile
from elftools.elf.dynamic import DynamicSection

SUSPECT = {
    # anti-debug
    "ptrace": "anti-debug/self-attach",
    "process_vm_readv": "cross-process memory read",
    "process_vm_writev": "cross-process memory write",
    "__ptrace": "anti-debug",
    # module / mapping enumeration
    "dl_iterate_phdr": "module enumeration (hook scan)",
    "_r_debug": "linker map walk",
    # file / proc access
    "open": "file access", "openat": "file access", "fopen": "file access",
    "access": "file probe", "stat": "file probe", "lstat": "file probe",
    "readlinkat": "path probe", "readlink": "path probe",
    "opendir": "dir scan", "readdir": "dir scan",
    "inotify_add_watch": "fs watch",
    # process control
    "fork": "process spawn", "vfork": "process spawn", "clone": "thread/process spawn",
    "execl": "exec", "execlp": "exec", "execvp": "exec", "system": "shell out",
    "popen": "shell out", "getppid": "parent probe",
    "kill": "signal", "prctl": "prctl (dumpable/ptracer)", "personality": "personality",
    # net
    "socket": "net", "connect": "net", "sendto": "net",
    # props / env
    "__system_property_get": "prop read", "getenv": "env read",
    "sysconf": "sysconf", "uname": "uname",
    # misc
    "dlopen": "dlopen", "dlsym": "dlsym", "memfd_create": "memfd",
    "syscall": "raw syscall",
    "pthread_create": "thread", "setpriority": "sched",
    "sigaction": "signal handler", "mmap": "mmap", "mprotect": "mprotect",
    "clock_gettime": "timing", "gettimeofday": "timing",
}

def triage(path: pathlib.Path):
    with open(path, "rb") as f:
        elf = ELFFile(f)
        imports, exports = [], []
        for sec in elf.iter_sections():
            if sec.name in (".dynsym", ".symtab"):
                for sym in sec.iter_symbols():
                    name = sym.name
                    if not name:
                        continue
                    if sec.name == ".dynsym":
                        if sym["st_shndx"] == "SHN_UNDEF" and sym["st_info"]["type"] in ("STT_FUNC", "STT_NOTYPE", "STT_GNU_IFUNC"):
                            imports.append(name)
                        elif sym["st_shndx"] != "SHN_UNDEF" and sym["st_info"]["type"] in ("STT_FUNC", "STT_GNU_IFUNC"):
                            exports.append(name)
        hits = {}
        for n in imports:
            key = n.split("@")[0]
            if key in SUSPECT:
                hits.setdefault(SUSPECT[key], []).append(key)
        has_init_array = any(s.name == ".init_array" for s in elf.iter_sections())
        notes = []
        for sec in elf.iter_sections():
            if sec.name in (".note.android.ident",):
                notes.append(sec.name)
        return {
            "file": path.name,
            "arch": elf.get_machine_arch(),
            "elf_type": elf.header["e_type"],
            "n_imports": len(imports),
            "n_exports": len(exports),
            "init_array": has_init_array,
            "capabilities": {k: sorted(set(v)) for k, v in sorted(hits.items())},
            "interesting_exports": sorted([e for e in exports if any(
                t in e.lower() for t in ("java_", "jni", "init", "check", "detect", "sec", "protect", "flag", "risk", "report", "sensor", "encrypt", "decrypt"))])[:40],
        }

def main():
    root = pathlib.Path(sys.argv[1])
    out = []
    for p in sorted(root.rglob("*.so")):
        try:
            out.append(triage(p))
        except Exception as e:
            out.append({"file": p.name, "error": str(e)})
    print(json.dumps(out, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()
