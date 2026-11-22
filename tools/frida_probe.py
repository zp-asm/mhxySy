"""协议层探测工具（Frida）—— 只读，不改游戏、不发上行包。

前置（一次性）：
    adb -s 127.0.0.1:16384 root
    adb -s 127.0.0.1:16384 push frida-server /data/local/tmp/ && chmod 755
    adb -s 127.0.0.1:16384 shell "setsid /data/local/tmp/frida-server -l 0.0.0.0:27042 </dev/null >/dev/null 2>&1 &"
    adb -s 127.0.0.1:16384 forward tcp:27042 tcp:27042
    pip install frida

用法：
    python tools/frida_probe.py pid             # 列进程
    python tools/frida_probe.py modules PID     # 列加密/网络模块
    python tools/frida_probe.py crypto PID      # hook EVP_Encrypt/DecryptUpdate
    python tools/frida_probe.py recv PID        # hook recv/read（拿密文 + 调用者）

已确认的结论（2026-11-22 实测）：
    · 游戏服务 42.186.128.28:10002，载荷全密文（无明文头），上行极小、下行大
    · SDK 登录 117.147.201.71:443（标准 TLS 1.2）
    · 协议不走 OpenSSL EVP（hook 20 s 内 0 次调用）→ 自己实现
    · socket 收包全在 libtcb.so（ARM，Houdini 转译，导出只有 2 个符号，已剥符号）
    · 进程里 libprotobuf-cpp-lite/full 都在 → payload 是 protobuf
    · libclienc.so 是内存模块（文件已删，anon 映射，仅 8KB 代码）—— 反 dump
"""
from __future__ import annotations

import subprocess
import sys
import time

import frida

SERIAL = "127.0.0.1:16384"
REMOTE = "127.0.0.1:27042"


def device():
    return frida.get_device_manager().add_remote_device(REMOTE)


def attach(pid: int):
    sess = device().attach(pid)
    return sess


MODULES_JS = r"""
rpc.exports = {
  info: function () {
    return Process.enumerateModules()
      .filter(function (m) { return /crypto|ssl|tcb|proto|clienc|unisec|secsdk|houdini/i.test(m.name); })
      .map(function (m) { return m.name + ' @ ' + m.base + ' ' + Math.round(m.size / 1024) + 'KB'; });
  }
};
"""

CRYPTO_JS = r"""
var hits = 0;
function hook(name, isDec) {
  var a = null; try { a = Module.findGlobalExportByName(name); } catch (e) {}
  if (!a) { send({ t: 'miss', name: name }); return; }
  send({ t: 'hook', name: name, addr: a.toString() });
  Interceptor.attach(a, {
    onEnter: function (args) {
      this.out = args[1]; this.outl = args[2]; this.inp = args[3]; this.inl = args[4].toInt32();
      if (hits < 40 && this.inl > 0 && this.inl < 4096) {
        hits++;
        var n = Math.min(this.inl, 48);
        send({ t: 'io', dir: isDec ? 'dec' : 'enc', len: this.inl,
               inhex: hexdump(ptr(this.inp).readByteArray(n), { length: n, header: false }) });
      }
    }
  });
}
hook('EVP_DecryptUpdate', true);
hook('EVP_EncryptUpdate', false);
rpc.exports = { hits: function () { return hits; } };
"""

RECV_JS = r"""
function modOf(a) { var m = Process.findModuleByAddress(a); return m ? m.name + '+' + a.sub(m.base) : a.toString(); }
var hits = 0;
['recv', 'read'].forEach(function (fn) {
  var a = null; try { a = Module.findGlobalExportByName(fn); } catch (e) {}
  if (!a) return;
  send({ t: 'hook', name: fn });
  Interceptor.attach(a, {
    onEnter: function (args) { this.buf = args[1]; this.len = args[2].toInt32(); this.fn = fn; this.caller = this.returnAddress; },
    onLeave: function (ret) {
      var n = ret.toInt32();
      if (n > 40 && hits < 25) {
        hits++;
        send({ t: 'rx', fn: this.fn, len: n, caller: modOf(this.caller),
               bt: Thread.backtrace(this.context, Backtracer.ACCURATE).slice(0, 4).map(modOf),
               hex: hexdump(ptr(this.buf).readByteArray(Math.min(n, 40)), { length: Math.min(n, 40), header: false }) });
      }
    }
  });
});
rpc.exports = { hits: function () { return hits; } };
"""


def on_msg(m, _d):
    if m["type"] == "send":
        p = m["payload"]
        if p["t"] == "hook":
            print("  hook", p["name"], p.get("addr", ""))
        elif p["t"] == "miss":
            print("  miss", p["name"])
        elif p["t"] == "io":
            print(f"  [{p['dir']}] len={p['len']} in={p['inhex'][:80]}")
        elif p["t"] == "rx":
            print(f"  rx {p['fn']} {p['len']}B caller={p['caller']}\n     {p['hex'][:80]}")
    else:
        print("  err", m)


def main(argv: list[str]) -> int:
    if len(argv) < 2 or argv[1] == "pid":
        for p in device().enumerate_processes():
            if "netease" in p.name.lower() or "梦幻" in p.name:
                print(p.pid, p.name)
        return 0

    cmd = argv[1]
    if cmd == "modules" and len(argv) > 2:
        sc = attach(int(argv[2])).create_script(MODULES_JS)
        sc.load()
        for x in sc.exports_sync.info():
            print(" ", x)
        return 0

    js = {"crypto": CRYPTO_JS, "recv": RECV_JS}.get(cmd)
    if not js or len(argv) < 3:
        print(__doc__)
        return 1
    sc = attach(int(argv[2])).create_script(js)
    sc.on("message", on_msg)
    sc.load()
    secs = int(argv[3]) if len(argv) > 3 else 20
    print(f"采集中 {secs}s ...")
    for _ in range(secs // 5):
        time.sleep(5)
        subprocess.run(["adb", "-s", SERIAL, "shell", "input", "tap", "825", "95"],
                       capture_output=True)          # 制造一点流量
    print("hits =", sc.exports_sync.hits())
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
