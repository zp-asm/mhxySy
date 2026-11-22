"""实验：recv 之后延迟重读同一缓冲区，判断是否"就地解密"。

如果游戏在 recv 拿到的缓冲区里原地解密，那么：
    t0   : 密文
    t0+Δ : 明文（或明文已被消费/覆盖）
抓到"前后不同"就等于拿到明文，无需破密码学。

用法：
    python tools/probe_inplace_decrypt.py [pid] [秒数]
"""
from __future__ import annotations

import subprocess
import sys
import time

import frida

SERIAL = "127.0.0.1:16384"
REMOTE = "127.0.0.1:27042"

JS = r"""
function modOf(a){ var m = Process.findModuleByAddress(a); return m ? m.name + '+0x' + a.sub(m.base).toString(16) : a.toString(); }
var recvAddr = Module.findGlobalExportByName('recv');
var seen = 0;
Interceptor.attach(recvAddr, {
  onEnter: function (args) { this.buf = args[1]; this.len = args[2].toInt32(); this.ra = this.returnAddress; },
  onLeave: function (ret) {
    var n = ret.toInt32();
    if (n < 60 || seen >= 60) return;
    seen++;
    var p = ptr(this.buf), sz = Math.min(n, 64);
    var t0hex = '';
    try { t0hex = hexdump(p.readByteArray(sz), {length: sz, header: false}); } catch(e) {}
    var caller = modOf(this.ra), id = seen;
    [15, 60].forEach(function (delay) {
      setTimeout(function () {
        var h = '';
        try { h = hexdump(p.readByteArray(sz), {length: sz, header: false}); } catch (e) { h = 'ERR'; }
        send({t: 'reread', id: id, delay: delay, len: n, caller: caller, t0: t0hex, later: h});
      }, delay);
    });
  }
});
rpc.exports = { seen: function () { return seen; } };
"""


def main(argv: list[str]) -> int:
    pid = int(argv[1]) if len(argv) > 1 else 1962
    secs = int(argv[2]) if len(argv) > 2 else 25
    dev = frida.get_device_manager().add_remote_device(REMOTE)
    sess = dev.attach(pid)
    sc = sess.create_script(JS)

    rows = []

    def on_msg(m, _d):
        if m["type"] == "send" and m["payload"].get("t") == "reread":
            rows.append(m["payload"])

    sc.on("message", on_msg)
    sc.load()
    print("采集 %ds（自动制造点击流量）..." % secs)
    for _ in range(max(1, secs // 5)):
        subprocess.run(["adb", "-s", SERIAL, "shell", "input", "tap", "825", "95"],
                       capture_output=True)
        time.sleep(5)

    print("recv 采样 %d 次，重读记录 %d 条" % (sc.exports_sync.seen(), len(rows)))
    changed = 0
    for r in rows:
        same = r["t0"][:40] == r["later"][:40]
        if not same:
            changed += 1
            if changed <= 8:
                print("\n  #%d +%dms from %s len=%d" % (r["id"], r["delay"], r["caller"], r["len"]))
                print("    t0   :", r["t0"][:70].replace("\n", " "))
                print("    later:", r["later"][:70].replace("\n", " "))
    print("\n内容发生变化的样本: %d / %d" % (changed, len(rows)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
