import json, sys
p = sys.argv[1] if len(sys.argv) > 1 else r"E:\gamework\mhxyMobile\analysis\elf_triage.json"
d = json.load(open(p, encoding="utf-8"))
for e in d:
    if "error" in e:
        print(e["file"], "ERR", e["error"]); continue
    cap = e["capabilities"]
    print(f"{e['file']:24s} {e['arch']:6s} imports={e['n_imports']:4d} exports={e['n_exports']:4d} init_array={e['init_array']}")
    for k in cap:
        print(f"      {k:34s} {', '.join(cap[k])}")
    ie = e.get("interesting_exports") or []
    if ie:
        print("      exports:", ", ".join(ie[:18]))
