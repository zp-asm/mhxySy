# 内核驱动路线：进展与结论（2026-11-22）

## 已打通的部分（都验证过）

| 项 | 结果 |
|---|---|
| GitHub Actions 云编 | ✅ `.ko`(17 KB) + 静态 `kread`(441 KB)，Release 匿名可下 |
| 目标内核可加载**未签名**模块 | ✅ `CONFIG_MODULE_SIG` 未开 |
| `MODVERSIONS` / vermagic 不匹配 | ✅ `finit_module(fd, "", IGNORE_MODVERSIONS\|IGNORE_VERMAGIC)` 成功（toybox/busybox 的 `insmod` 都不支持 `-f`） |
| 目标机 config 参与编译 | ✅ 用 `/proc/config.gz`（`drv/kernel.config`，8754 项）而不是 vanilla defconfig |
| `module_param` 回调可执行 | ✅ `echo 1 > /sys/module/mhxy_drv/parameters/go` → `go_set called` 打出来了 |
| 环境可安全回收 | ✅ `rmmod` 干净，游戏进程仍存活（PID 3509） |

## 卡住的部分（内核契约不一致）

```
[10266.932334] mhxy_drv: do_boot enter (booted=-1067715648 sizeof(struct module)=832 off_init=312 off_name=24)
[10266.933202] mhxy_drv: do_boot skip (already booted)
```

三条互相印证的证据：

1. **`static int mhxy_booted` 读到 `-1067715648`** —— 静态变量没被正确清零/映射，`.bss` 落点不对。
2. **`mod->init` 从未被调用**（`/sys/module/mhxy_drv/initstate=live`、`/proc/misc` 无条目、无 `boot ok` 日志）—— 内核按它自己的 `struct module` 偏移读 `init`，读到 NULL。
3. **`initsize=0`、`sections/` 只剩 `__bug_table/__mcount_loc/__param`** —— 内核看待我们节区的方式和我们的 ELF 不一致。

即：**MuMu 的 `6.1.90-perf+` 是可定制内核，`struct module` 布局/节区契约与 vanilla 6.1.90 不同。** 这不是代码 bug，改代码修不了。

## 三条可选路线（成本 / 风险 / 期望）

| 路线 | 需要什么 | 风险 | 现实性 |
|---|---|---|---|
| A. 拿到 MuMu 内核源码/头文件，重编 | 厂商源码（无公开） | — | ❌ 不可能 |
| B. 暴力对齐 `struct module`：自己写 `this_module` 段，把 `init` 指针铺满多个候选偏移 | 每个偏移一轮 CI（~6 min），错一次可能 panic | 高（可能把 VM 搞崩） | ⚠️ 理论上可试，收益不确定 |
| C. 绕开模块：用 tracefs `kprobe_events` + fetchargs 做内核读原语 | 需要构造可控 kprobe 调用点、KASLR 绕过 | 中 | ⚠️ 工程量大 |
| D. **放弃内核层**：图色中控 + 脚本包解密 | 已有一半在做 | 低 | ✅ 推荐 |

## 为什么推荐 D

- 目标只是"中控台多开挂机"，**不需要读内存**：固定 UI 用模板匹配（实测 3.8 ms/ROI）、文字用 OCR、人群用名字条（实测已能检出）。
- 想要"逻辑层"信息，**`_ntcfgss.dat`（8.76 MB）+ `_ntcfg_.data`（105 B，内含疑似 AES key `NsUf4AGAMWAY4ZabxM4ekxXc5J9iTNV4`）** 是离机可解的，零检测风险。
- 内核路线即使成功，也要面对：每版内核更新失效、`/proc/modules` 可见性、taint、以及"读到的仍是 Houdini 影子地址（页表层面是否可得尚未验证）"。

## 复现方式（保留给后来人）

```bash
# 云端编（免费，公开仓库）
push 到 GitHub → Actions 自动跑 → Release: latest (mhxy_drv.ko + kread) / ci-log (report.txt)

# 设备侧
adb push mhxy_drv.ko kread /data/local/tmp/
adb shell 'chmod 755 /data/local/tmp/kread'
adb shell '/data/local/tmp/kread load /data/local/tmp/mhxy_drv.ko'   # finit_module + IGNORE 标志
adb shell 'echo 1 > /sys/module/mhxy_drv/parameters/go'              # 绕过 mod->init
adb shell 'dmesg | grep mhxy_drv'                                    # 这里会看到 booted=-...
```

关键源码位置：
- `drv/mhxy_drv.c`：4 级页表走查（含 1G/2M 大页）、kprobe 解析符号、param 回调入口
- `drv/kread.c`：`load`（finit_module 带 IGNORE 标志）、`stat/pgd/read/arena`
- `.github/workflows/build-ko.yml`：用 `drv/kernel.config` 编、失败也发日志
