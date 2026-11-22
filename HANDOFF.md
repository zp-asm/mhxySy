# 交底书（给接手的人看）

**目标**：MuMu Player NX 15（Android 15，x86_64）+《梦幻西游手游》多开挂机中控台。
**产出要求**：能多实例并行挂机、行为自然化、不触发客户端检测。
**本文件只写已实证的事实与明确结论；未验证的一律标在 §7，请勿当结论引用。**

---

## 0. 一页结论

1. **用户态读游戏内存不可行**。游戏跑在 Houdini（ARM→x86 转译）上，客户机地址空间（`0x4000_xxxx_xxxx`）的页表在外部读取时返回 `EIO`，但页确实在物理内存里（RSS 36 MB）。根因是 `/proc/<pid>/mem` 走 `vma->vm_ops->access()`，被 Houdini 的 VMA 实现挡住。
2. **内核模块这条路当前也走不通**（不是代码问题）。模块能用 `finit_module` + `IGNORE_VERMAGIC/IGNORE_MODVERSIONS` 加载、`module_param` 回调能执行，但 MuMu 的 **定制内核** `struct module` / 节区契约与 vanilla 6.1.90 不一致：`mod->init` 不被调用，静态变量读到垃圾值。拿不到厂商内核源码/头文件，编不出能真正运行的模块。
3. **能走的是两条零风险路线**：①图色 + OCR + 名字条定位（已有实测数据与可运行骨架）；②脚本包离机解密（`_ntcfg_.data` 里有疑似 AES key）。中控台不需要读内存就能挂机。

---

## 1. 环境（复现基线）

| 项 | 值 |
|---|---|
| 宿主 | Windows，i5-10400 / 内存 4 GB 分配给实例 |
| 模拟器 | MuMu Player NX 15.0，实例 0，`MuMuVMMManage 6.1.36_OSE`（VBoxManage fork） |
| adb | `127.0.0.1:16384`，`adb shell` 直接 `uid=0 context=u:r:su:s0`（MuMu `root_permission=true`，**机器上没有 su 二进制**） |
| 游戏 | 包名 **`com.netease.my`**（不是 `com.netease.mhxy`），Activity `com.netease.game.MessiahNativeActivity`（Messiah 引擎），`1.567.0 / 15670` |
| APK | `/data/app/.../base.apk` 1.95 GB，**lib 只有 `arm64-v8a`**（靠 `libhoudini.so` 转译） |
| 仓库 | `https://github.com/zp-asm/mhxySy`（公开，deploy key 可推） |

---

## 2. 已确证的事实（F = fact，附证据与复现）

| # | 结论 | 证据 / 复现 |
|---|---|---|
| F1 | 游戏逻辑跑在 Houdini 转译上 | `/proc/<pid>/maps` 里 `libGame.so` 全是 `r--p/rw-p`，**无 r-xp**；`/system/lib64/libhoudini.so` 已加载；客户机段在 `0x4000_xxxx_xxxx` |
| F2 | 用户态读客户机内存 = EIO | `dd if=/proc/$PID/mem bs=1024 skip=… 2>&1` → `read error: I/O error`；file-backed 段读回全 0 |
| F3 | 那些页确实在物理内存里 | `smaps`：`400060174000-400068000000 rwxp [anon:Mem_0x20000000]` RSS **36 MB** |
| F4 | 能读的区域没有游戏状态 | dalvik main space 前 64 MB：`长寿村`/`背包`/`任务` 命中 **0**；只有 `lua` 9 次、`Messiah` 31 次（都是 Java 类名/日志） |
| F5 | 反作弊主力在 **`libsec-lib.so` 之外** | maps 计数：`libsecsdk`/`libunisec`/`libybuaxz`/`libntunisdk`/`libpharos`/`libclienc` = 3、`libGame` = 5；**`libsec-lib`=0、`libnesdk`=0、`libnep`=0（未加载）** |
| F6 | 模拟器检测有 ≥4 条互不相通的通道 | CrashHunter `CEmulatorDetector.detectLocal`、unifix `UniSDK EmulatorDetector`、URS `Devices.isEmulator()`、分散的 `UniSdkUtils.isEmulator/isMuMu` |
| F7 | 本机 `is_emulator = true`（实测，不是推断） | `files/uniTrace/crashhunter/crashhunter.di`：`"is_emulator":"true"`；成因：`checkBasic()` 里 `"V417IR".equals(Build.ID)` 为真 + `getCPUType()` 读 `ro.product.cpu.abi=x86_64` 返回 `"x86"` + `cpuinfo` 含 `intel` |
| F8 | 本机 `is_rooted = false` | 同上文件；五条 `su` 路径全不存在，adb 是 root 但没 su 二进制 |
| F9 | MuMu 特有痕迹（props 改不掉） | 同上文件：`hardware=" placeholder"`（字面量带前导空格）、`cpu="Redmi"`、`local_ip="10.0.2.15"`、`gl_renderer="Adreno (TM) 640"` 配 `23117RK66C`、电量 30 min 掉 15% |
| F10 | 服务端关联账号靠设备号 | `app_uf_data/device_id.info = 2b8837c8aca36189` = `crashhunter.di` 的 `unisdk_device_id` = `crashhunter.param` 里 `transid` 前缀；**`MuMuManager clone` 会复制该文件 → 克隆实例同号** |
| F11 | 目标内核是 x86_64 但 uname 伪造成 aarch64 | `CONFIG_X86_64=y`、`CONFIG_ARM64` 不存在、`uname -m` 返回 `aarch64` |
| F12 | 内核允许加载**未签名**模块 | `CONFIG_MODULE_SIG` 未设、`CONFIG_MODULES=y`、`CONFIG_MODULE_FORCE_LOAD=y`、`CONFIG_MODVERSIONS=y` |
| F13 | `insmod -f` 不可用，但 `finit_module` 的 IGNORE 标志可用 | `toybox`/`busybox` 的 `insmod` 都不接受 `-f`；`finit_module(fd,"",IGNORE_MODVERSIONS\|IGNORE_VERMAGIC)` 返回 0，模块进 `/proc/modules` |
| F14 | 但模块**跑不起来**（定制内核契约不一致） | `initstate=live`、`initsize=0`、`/proc/misc` 无条目、无 `boot ok` 日志；`module_param` 回调里打印 `booted=-1067715648`（静态变量读到垃圾），`sizeof(struct module)=832 off_init=312` 在目标内核不成立 |
| F15 | 宿主侧 dump 不可用 | `MuMuVMMManage list vms` 为空（VM 未注册）→ `debugvm dumpvmcore` 无目标；guest RAM 在 ring-0 `MuMuNxVMMR0.r0` |
| F16 | HyperDbg 与 MuMu 抢 VT-x | `NestedHWVirt=0`、`HypervisorPresent=False`、`hyperv_enabled=false`；Windows 侧 Hyper-V/VMP/WSL 全 Disabled |

---

## 3. 已排除的方案（别重复踩）

| 方案 | 为什么不行 |
|---|---|
| `/proc/<pid>/mem` 直读、Cheat Engine、GG 修改器 | F2/F3：Houdini 客户机段 EIO |
| 注入 x86_64 SO 后直接解引用客户机地址 | **未验证**（见 §7），但即便可行也会引入 maps/模块枚举等暴露面 |
| 改 props 伪装机型 | F7：`V417IR` / `abi=x86_64` / `cpuinfo=intel` 三条硬命中，与 brand/model 无关 |
| 改 APK / 重签 | 存在 `ntunisdk_so_uuids`（模块 MD5 表）、`package_fingerprint`（证书 SHA1）、`uploadapk` 参数 |
| 同系统内双开（`com.netease.mumu.cloner`、`lody.virtual` 等） | `libsec-lib` 的 `SameUidPackage`/`SamePackageCount`/分身包黑名单（注意：该 so 当前未加载，但属已知检测项） |
| WSL2 / Docker Desktop 做编译 | 写 C 盘（仅剩 4.9 GB）+ 启 VMP 抢 MuMu 的 VT-x |
| `MuMuVMMManage debugvm dumpvmcore` | F15：`list vms` 为空 |
| HyperDbg / EPT 级方案 | F16：VT-x 被 MuMu 独占 |
| 继续魔改 LKM | F14：需要 MuMu 内核源码或头文件，拿不到 |

---

## 4. 仍然可行的路线（按 ROI 排序）

### R1 图色 + OCR + 名字条（零检测面，推荐主线）

实测数据（960×540，i5-10400）：

| 环节 | 实测 |
|---|---|
| `adb screencap` 全帧 | 392–800 ms（只能低频巡检） |
| 单模板全屏 `matchTemplate` | 21 ms |
| **单模板 ROI(360×200)** | **3.8 ms** |
| 缩到 480×270 匹配 | 5.7 ms |
| `adb input tap` | 195 ms（每次起进程，宿主注入约 1 ms） |
| 模板鲁棒性 | JPEG q60 0.985 / 亮度 ±12% 1.000 / 噪声 σ4 0.999 / 模糊 3×3 0.928 / 缩放 0.96 0.955（`TM_CCOEFF_NORMED`，阈值 0.80） |
| 端到端 | 模板命中 0.9956 → 点击 → 画面变化 90.7% → BACK 回落 4.7% |
| 名字条检测（人群） | 单帧检出 6 条候选（含"心月狐之影"），需按颜色分层 + OCR 过滤误检 |

骨架已在 `mhxy_console/`（`mumu.py` 多实例、`adb.py` 注入/抓帧、`vision.py` 模板+OCR 挂载、`worker.py` 人类化节流、`main.py` CLI）。
**待补**：`dxcam` 抓帧（把 392 ms 降到 ~10 ms）、`pywin32` 走 MuMu 窗口注入（落到真实 `nemuinput` → uinput 触摸）、每实例独立模板目录。

### R2 脚本包离机解密（零风险，拿"逻辑层"）

```
assets/_ntcfgss.dat   8,764,560 B   熵 6.33  可打印 0.386（词表形态）
assets/_ntcfg_.data   105 B         内含：
    387924e229e47568b8a64c9c3f8c9743   （32 hex，像 md5）
    g18                                 （JF_GAMEID）
    NsUf4AGAMWAY4ZabxM4ekxXc5J9iTNV4    （32 字符，疑似 AES-256 key）
    libGame.so
```
`_ntcfgss.dat` 里 `EmulatorDetectResult` 出现 1 次、`V417IR` 1 次 → 脚本层很可能就是模拟器检测的调用方（`libGame.so` 里这些串是 0 命中）。
**做法**：拿那把 32 字符 key 试 AES-256-ECB/CBC；先看是否 zlib（头不是 `78 9c`）。

### R3 内核路线（若坚持）

前提条件只有两个：拿到 MuMu 内核源码/头文件，或者暴力对齐 `struct module`（把 `init` 指针铺满多个候选偏移，每轮 CI 6 分钟，错一次可能 panic）。**不建议**，且即使通了还要面对 Houdini 影子地址能否被页表走查拿到（§7）。

---

## 5. 代码与产物位置

```
仓库 zp-asm/mhxySy
├─ REPORT.md        反作弊/模拟器/内存检测分析（含字符串偏移证据）
├─ REVIEW.md        对 REPORT 的交叉复核 + crashhunter.di / device_id.info 证据
├─ DRV_STATUS.md    内核驱动路线：已打通项、卡点、可选路线
├─ TOOLS.md         工具矩阵与下载地址
├─ INSTALL.md       安装清单（禁装 C/F 盘；WSL2 为何不能用）
├─ drv/             mhxy_drv.c（4 级页表走查/kprobe 符号解析/param 入口）
│                   kread.c（finit_module 加载 + stat/pgd/read/arena）
│                   kernel.config（目标机 /proc/config.gz 原样）
├─ mhxy_console/    多实例中控骨架（MuMuManager + adb + 视觉 + 节流）
├─ tools/           抓帧/压测/鲁棒性/名字条/设备探针（probe_*.sh）
└─ .github/workflows/build-ko.yml   云编 .ko + 静态 kread（失败也发日志）
```

Release：`latest`（`mhxy_drv.ko` + `kread`）、`ci-log`（`report.txt` 构建日志）。

本机保留：`E:\out\drv\`（产物）、`E:\gamework\mhxyMobile\artifacts\`（APK/dex/so/crashhunter.di 取证副本，已 gitignore）。

---

## 6. 关键复现命令

```powershell
# 1) 云端编（免费，公开仓库）
git push origin main          # 触发 Actions → Release latest/ci-log

# 2) 装模块（证明 F13/F14）
adb push mhxy_drv.ko kread /data/local/tmp/
adb shell 'chmod 755 /data/local/tmp/kread'
adb shell '/data/local/tmp/kread load /data/local/tmp/mhxy_drv.ko'   # → finit_module OK
adb shell 'echo 1 > /sys/module/mhxy_drv/parameters/go'              # 绕过 mod->init
adb shell 'dmesg | grep mhxy_drv'                                    # → booted=-1067715648
adb shell 'rmmod mhxy_drv'                                           # 清理

# 3) 图色泵
python -m mhxy_console.main list
python -m mhxy_console.main shot --index 0 --out f.png
python -m mhxy_console.main match --template task --threshold 0.8
```

---

## 7. 明确**未验证**的（请勿当结论）

1. `process_vm_readv` 对 Houdini 客户机段是否也 EIO（只测过 `/proc/mem`；需 NDK 探针）。
2. 注入 x86_64 SO 后，**进程内**解引用客户机地址是否成功（页表层面可能同样不可得）。
3. 若页表走查能拿到 PTE，`Mem_0x*` 段里是否含有可用的游戏结构（目前只证明页存在、外部读不到）。
4. `unisdk_device_id` 的派生规则（是否随 `simulation android_id/mac/imei` 变化、删除 `device_id.info` 后是否重生）——**改动会触发"换设备登录"，只能在小号上试**。
5. 服务端是否因 `is_emulator=true` 处罚账号（无登录记录、无协议样本）。
6. `_ntcfgss.dat` 的加密算法与那把 32 字符 key 的作用。
7. 名字条检测的准确率/召回率（只做过单帧 demo，6 条候选中含 2 条 UI 误检）。

---

## 8. 接手后前三小时建议

1. 读 `REPORT.md` §0–§3 + `REVIEW.md`，把 F1–F16 用 §6 的命令抽验 3 条（F2、F7、F14）。
2. 跑 `python -m mhxy_console.main list / shot / match`，确认视觉链路在你机器上可复现。
3. 装 `dxcam + pywin32`，把抓帧从 392 ms 降到 ~10 ms、输入从 195 ms 降到 ~1 ms——这是中控能不能多开的唯一瓶颈。
4. 不要在 LKM 上继续投入，除非能拿到 MuMu 内核源码。
