# mhxy_drv —— 跨进程 PTE 走查读内存（x86_64 / Linux 6.1）

目标：读目标进程里**用户态读不到**的那部分内存。

## 为什么必须走内核

| 事实 | 数据 |
|---|---|
| `[anon:Mem_0x20000000]` 有常驻页 | `smaps` RSS = **36 MB** |
| 用户态读同样地址 | `dd: /proc/3509/mem: read error: I/O error`（0 字节） |
| 原因 | `/proc/<pid>/mem` → `access_remote_vm()` → `vma->vm_ops->access()`，被 Houdini 的 VMA 实现挡掉 |
| 绕过方式 | 从 `mm->pgd` 手工走 4 级页表拿 PTE → `__va()` 直接读物理页，**完全不走 vm_ops** |

## 现场条件（已实测，决定可行性的 4 条）

```
CONFIG_MODULES=y            CONFIG_MODULE_SIG   not set      ← 不需要签名
CONFIG_MODULE_FORCE_LOAD=y  CONFIG_MODVERSIONS=y             ← insmod -f 可忽略 CRC/vermagic
CONFIG_KPROBES=y            CONFIG_KALLSYMS_ALL=y            ← 可运行期解析符号
CONFIG_PGTABLE_LEVELS=4     无 CONFIG_X86_5LEVEL / 无 la57    ← 页表走 4 级，已验证
CONFIG_RANDOMIZE_BASE=y     kptr_restrict=2                  ← 地址必须运行期取，不能硬编码
CONFIG_PROC_KCORE off       /dev/kmem 不存在                 ← 用户态没有内核内存通道
内核真身 CONFIG_X86_64=y，uname 伪造成 aarch64                ← 必须编 x86_64 的 .ko
```

## 编译（在 Linux 里，Windows 上没有 kbuild）

```bash
# 0) WSL2 + Ubuntu（管理员 PowerShell）
wsl --install -d Ubuntu-22.04

# 1) 内核源码（6.1.90；也可用 android13-6.1）
cd ~ && wget https://cdn.kernel.org/pub/linux/kernel/v6.x/linux-6.1.90.tar.xz
tar xf linux-6.1.90.tar.xz && cd linux-6.1.90
make ARCH=x86_64 defconfig
make ARCH=x86_64 modules_prepare

# 2) 编模块
cd /mnt/e/gamework/mhxyMobile/drv
make KDIR=$HOME/linux-6.1.90            # 产出 mhxy_drv.ko

# 3) 部署（Windows 侧）
make deploy                              # = adb push + insmod -f + dmesg
```

## 验证阶梯（每一步都有明确判据）

```bash
adb shell 'insmod -f /data/local/tmp/mhxy_drv.ko'   # 失败看 dmesg（dmesg_restrict=0）
adb shell 'ls -l /dev/mhxy_drv'
adb shell 'python3 /data/local/tmp/kread.py verify'
```

`kread.py verify` 的输出判据：

| 输出 | 含义 | 下一步 |
|---|---|---|
| `STAT: page_offset_base=0x... symbols=5/5` | kprobe 解析成功（抗 KASLR） | 继续 |
| `PGD : 0x... mm->pgd offset = 0x...` | 偏移探测成功 | 继续 |
| `[1] dalvik` 非零 | 页表走查基本正确 | 继续 |
| `[2] arena` 非零 | **成功**：拿到 Houdini 客户机内存 | 进入"找结构"阶段 |
| `[2]` 报 `EFAULT` | 该页 PTE 不存在 | 换 arena 段/换地址重试 |
| `insmod` 报 `-ENOENT`/`Invalid module format` | 符号或 vermagic 问题 | 看 dmesg 原文，用 `-f` 重试 |
| `STAT` 返回 `EAGAIN` | 符号解析没完成 | `dmesg \| grep mhxy_drv` |

## 已知风险 / 边界

1. **MuMu 内核是定制的**（`6.1.90-perf+ #3 build-user@build-host`，无公开源码）
   → 拿不到 `Module.symvers`，只能靠 `CONFIG_MODULE_FORCE_LOAD + insmod -f` 跳过 CRC。
   若某版本关掉 FORCE_LOAD，这条路断，只能转宿主层（成本高得多）。
2. **`mm->pgd` 偏移未知** → `find_pgd_off()` 运行期暴力探测（给一个确定已映射的地址当探针）。
3. **大页**：`CONFIG_PGTABLE_LEVELS=4`，1 GB（PUD）与 2 MB（PMD）大页都在代码里处理了。
4. **隐藏 vs 可卸载**：`hide_self()` 摘 `THIS_MODULE->list` 后 `/proc/modules` 里看不见，
   但 `rmmod` 也失效（要重启实例清理）。调试阶段先别调用。
5. **taint**：`insmod -f` 会置 `TAINT_FORCED_MODULE / TAINT_OOT_MODULE`，`dmesg` 里可见。
   生产前要清（改 `tainted_mask`），或者接受（游戏读 dmesg 的概率未知）。
6. **写内存有风险**：COW 页写会破坏共享，游戏逻辑页写会崩客户端。先只读。

## 文件

```
drv/
├─ mhxy_drv.c    模块：kprobe 符号解析 + 4 级页表走查 + 大页 + ioctl + 摘链隐藏
├─ Makefile      obj-m，KDIR 可覆盖，make deploy 一键推+加载
└─ kread.py      客户端：verify / read / scan（ctypes 打 ioctl）
```
