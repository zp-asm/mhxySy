"""按 socket inode 精准抓"就地解密后的明文"。

原理：
    1. 先确定游戏服的 socket inode（/proc/pid/net/tcp 里本端端口 37080 → 42.186.128.28:10002）
    2. hook recv/recvfrom/read，只处理 fd 解析出的 socket:[<inode>] 匹配的那些
    3. recv 返回后延迟 10/30/80ms 重读同一缓冲区 —— 若内容变化，变化后的就是明文

用法：
    python tools/probe_game_plaintext.py <inode> [秒数]
"""
from __future__ import annotations

import subprocess
import sys
import time

import frida

SERIAL = "127.0.0.1:16384"
REMOTE = "127.0.0.1:27042"

JS = r"""
var TARGET_INODE = "%INODE%";
var _readlink = null;
function readlinkFn() {
  if (_readlink) return _readlink;
  var p = Module.findGlobalExportByName('readlink');
  _readlink = new NativeFunction(p, 'long', ['pointer', 'pointer', 'ulong']);
  return _readlink;
}
function fdInode(fd) {
  try {
    var path = Memory.allocUtf8String('/proc/self/fd/' + fd);
    var buf = Memory.alloc(128);
    var n = readlinkFn()(path, buf, 127);
    if (n <= 0) return null;
    var s = buf.readUtf8String(n);
    var m = s.match(/socket:\[(\d+)\]/);
    return m ? m[1] : null;
  } catch (e) { return null; }
}
rpc.exports = { hits: function () { return hits; } };
var hits = 0;

var hits = 0;
['recv', 'recvfrom', 'read'].forEach(function (name) {
  var a = null;
  try { a = Module.findGlobalExportByName(name); } catch (e) { }
  if (!a) return;
  Interceptor.attach(a, {
    onEnter: function (args) {
      this.fd = args[0].toInt32();
      this.buf = args[1];
      this.len = args[2].toInt32();
      this.name = name;
      this.match = (fdInode(this.fd) === TARGET_INODE);
    },
    onLeave: function (ret) {
      if (!this.match) return;
      var n = ret.toInt32();
      if (n < 40) return;
      hits++;
      var p = ptr(this.buf), sz = Math.min(n, 200);
      var t0 = '';
      try { t0 = hexdump(p.readByteArray(sz), { length: sz, header: false }); } catch (e) { t0 = 'ERR'; }
      var who = this.name, id = hits;
      [10, 30, 80].forEach(function (d) {
        setTimeout(function () {
          var h = '';
          try { h = hexdump(p.readByteArray(sz), { length: sz, header: false }); } catch (e) { h = 'ERR'; }
          send({ t: 'rr', id: id, delay: d, len: n, fn: who, t0: t0, later: h });
        }, d);
      });
    }
  });
});
"""


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 1
    inode = argv[1]
    secs = int(argv[2]) if len(argv) > 2 else 30
    dev = frida.get_device_manager().add_remote_device(REMOTE)
    pid = int(subprocess.run(["adb", "-s", SERIAL, "shell", "pidof", "com.netease.my"],
                             capture_output=True, text=True).stdout.strip())
    sess = dev.attach(pid)
    sc = sess.create_script(JS.replace("%INODE%", inode))

    rows = []

    def on_msg(m, _d):
        if m["type"] == "send" and m["payload"].get("t") == "rr":
            rows.append(m["payload"])

    sc.on("message", on_msg)
    sc.load()
    print("目标 inode=%s，采集 %ds ..." % (inode, secs))
    for _ in range(max(1, secs // 4)):
        # 只点场景中央（不碰任何按钮），制造移动/寻路流量
        subprocess.run(["adb", "-s", SERIAL, "shell", "input", "tap", "480", "330"],
                       capture_output=True)
        time.sleep(3)
        subprocess.run(["adb", "-s", SERIAL, "shell", "input", "tap", "500", "380"],
                       capture_output=True)
        time.sleep(3)

    print("命中 %d 次游戏 recv，重读 %d 条" % (sc.exports_sync.hits(), len(rows)))
    for r in rows[:10]:
        if r["later"][:32] == r["t0"][:32]:
            continue
        print("\n  #%d +%dms %s len=%d" % (r["id"], r["delay"], r["fn"], r["len"]))
        print("    t0   :", r["t0"][:90].replace("\n", " "))
        print("    later:", r["later"][:90].replace("\n", " "))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
