# 安装清单（不写 C 盘、不写 F 盘）

**当前磁盘**：`C: 4.9 GB 可用`｜`D: 151.5 GB`｜`E: 206.4 GB`｜`F: 84 GB（MuMu 专用，不动）`

目录与环境变量已经建好并生效（`tools/setup_dirs.ps1` 已执行）：

```
D:\develop\tools\7zip          7-Zip
D:\develop\tools\qemu          QEMU（无需 VT-x 的本地 Linux 编译环境）
D:\develop\tools\ghidra        Ghidra（可选）
D:\develop\tools\android\ndk   NDK r27c（可选）
E:\iso                         Ubuntu 安装镜像
E:\kernel-src\linux-6.1.90     内核源码（编 .ko 用）
E:\vms\ubuntu-kbuild           QEMU 虚拟机磁盘
E:\cache\pip   E:\cache\tmp    pip 缓存 / TEMP（已从 C 盘挪走）
E:\out                         .ko 等产物
```

## 0. 一条红线：不要装 WSL2

```
HypervisorPresent = False
Microsoft-Hyper-V-All       Disabled
VirtualMachinePlatform      Disabled
Microsoft-Windows-Subsystem-Linux  Disabled
MuMuManager: hyperv_enabled = false   ← MuMu 独占 VT-x
```

`wsl --install` 会做两件坏事：① 发行版装进 `C:\Users\...\AppData\Local\Packages`（C 盘只剩 4.9 GB）；② 启用 `VirtualMachinePlatform`，和 MuMu 抢 VT-x，MuMu 得起 Hyper-V 模式（等于换了一套运行环境，反作弊观测面也变了）。**所以本地 Linux 用 QEMU + TCG，不吃 VT-x。**

## 1. 必装（驱动路线）

| # | 名称 | 下载地址 | 大小 | 装到哪 |
|---|---|---|---|---|
| 1 | **7-Zip 24.08 x64** | https://www.7-zip.org/a/7z2408-x64.exe | 1.6 MB | `D:\develop\tools\7zip`（安装器里改目录） |
| 2 | **QEMU for Windows** | https://qemu.weilnetz.de/w64/ （取最新 `qemu-w64-setup-*.exe`） | ~200 MB | `D:\develop\tools\qemu` |
| 3 | **Ubuntu Server 24.04 ISO** | https://releases.ubuntu.com/24.04/ | 2.6 GB | `E:\iso\` |
| 4 | **linux-6.1.90 源码** | https://cdn.kernel.org/pub/linux/kernel/v6.x/linux-6.1.90.tar.xz | 139 MB | `E:\kernel-src\` |
| 5 | **Android common 6.1（备选内核源）** | https://android.googlesource.com/kernel/common/+/refs/heads/android13-6.1 | — | 只在 `insmod -f` 因结构体布局失败时才用 |

一条命令下完（PowerShell，全部落 D/E）：

```powershell
iwr https://www.7-zip.org/a/7z2408-x64.exe -OutFile D:\develop\tools\7zip\7z-setup.exe
iwr https://qemu.weilnetz.de/w64/qemu-w64-setup-20240423.exe -OutFile D:\develop\tools\qemu\qemu-setup.exe
iwr https://releases.ubuntu.com/24.04/ubuntu-24.04.1-live-server-amd64.iso -OutFile E:\iso\ubuntu-server.iso
iwr https://cdn.kernel.org/pub/linux/kernel/v6.x/linux-6.1.90.tar.xz -OutFile E:\kernel-src\linux-6.1.90.tar.xz
```

## 2. 可选（想省事 / 想更深）

| 名称 | 地址 | 装到哪 | 什么时候需要 |
|---|---|---|---|
| **Ghidra 11.x** | https://github.com/NationalSecurityAgency/ghidra/releases | `D:\develop\tools\ghidra` | 逆 `libunisec_x86_64.so`、`vaddress` 模块；需 JDK21（已有 `D:\develop\jdk-21`） |
| **Android NDK r27c** | https://developer.android.com/ndk/downloads | `D:\develop\tools\android\ndk` | 编 Android 用户态小工具（注入器/probe） |
| **frida-server 17.26.3 android-x86_64** | https://github.com/frida/frida/releases | **推进 VM** `/data/local/tmp/`，不装 Windows | 一次性验证"进程内能否解引用客户机内存" |
| **LIEF / androguard** | `pip install lief androguard` | `D:\develop\py312\Lib\site-packages` | so 改写、dex 交叉引用 |

## 3. Python 包（中控 + 分析）

缓存已在 `E:\cache\pip`，site-packages 在 D 盘，**不会写 C**：

```powershell
pip install dxcam pywin32 adbutils rapidocr-onnxruntime lief androguard
```

| 包 | 用途 | 体积 |
|---|---|---|
| `dxcam` | 宿主 DXGI 抓帧（替代 392 ms 的 `screencap`） | 小 |
| `pywin32` | 向 MuMu 窗口注入鼠标（走 `nemuinput` → 真实 uinput 触摸） | 10 MB |
| `adbutils` | 多实例 adb 并发/重连 | 小 |
| `rapidocr-onnxruntime` | 游戏内文字识别（NPC 名、任务、血量） | ~250 MB（含 onnxruntime） |
| `lief` / `androguard` | so/dex 处理 | 各几十 MB |

## 4. 三条编译路线（`.ko` 怎么得到）

### 路线 A — 云端编，本地零安装（推荐）

仓库里已经有 `.github/workflows/build-ko.yml`：GitHub 的 Ubuntu runner 下载 6.1.90 源码、`modules_prepare`、编出 `mhxy_drv.ko` 并作为 artifact 提供下载。

```powershell
cd E:\gamework\mhxyMobile
git init; git add -A; git commit -m "drv: pte-walk reader"
# 推到你的 GitHub 仓库后，Actions → build-ko → Run workflow → 下载 artifact
```

优点：不装 Linux、不碰 VT-x、不同关 MuMu。缺点：需要 GitHub 账号。

### 路线 B — 本地 QEMU + TCG（不吃 VT-x，可与 MuMu 同时跑）

```powershell
# 1) 建虚拟盘（20 GB 动态）
D:\develop\tools\qemu\qemu-img.exe create -f qcow2 E:\vms\ubuntu-kbuild\disk.qcow2 20G

# 2) 起虚拟机装 Ubuntu（-accel tcg = 纯软件模拟，不需要 VT-x）
D:\develop\tools\qemu\qemu-system-x86_64.exe `
  -accel tcg,thread=multi -m 4096 -smp 4 `
  -drive file=E:\vms\ubuntu-kbuild\disk.qcow2,if=virtio `
  -cdrom E:\iso\ubuntu-server.iso `
  -netdev user,id=n0 -device virtio-net,netdev=n0 `
  -display sdl

# 3) 装完进系统，共享目录拿源码（QEMU 里把 E: 映射进去，或直接 wget 内核源码）
```

优点：完全本地、不冲突、不关机。缺点：TCG 比真机慢 5–15 倍，编一个模块约 1–3 分钟。

### 路线 C — 一台便宜 Linux VPS

`apt install build-essential libelf-dev bc flex bison` 后 `make -C <kernel> M=drv modules`，10 元/月级别。最省心，但要联网。

## 5. 空间预算

| 项 | 占用 |
|---|---|
| 7-Zip + QEMU | ~0.3 GB（D） |
| Ubuntu ISO（装完可删） | 2.6 GB（E） |
| 虚拟机磁盘 | 8–20 GB（E，动态增长） |
| 内核源码（解压后） | 1.5 GB（E） |
| NDK r27c（可选） | 3 GB（D） |
| Python 包（含 onnxruntime） | ~0.5 GB（D） |
| Ghidra（可选） | 0.5 GB（D） |
| **合计** | **约 15–28 GB**，D/E 都放得下 |

## 6. 装的时候注意（这几条最容易偷偷写 C 盘）

1. 每个 `.exe` 安装器都选自定义目录，别一路 Next。
2. 不要装：WSL2、Docker Desktop、Visual Studio 完整版、Steam、Chrome 安装版（都会写 C）。
3. `pip` / `npm` / `nuget` 缓存：已用 `PIP_CACHE_DIR=E:\cache\pip`、`TEMP=E:\cache\tmp` 指走；`npm` 另设 `npm config set cache D:\develop\npm-cache`。
4. 打印/字体/驱动这类系统组件别碰。
5. MuMu 本身在 F 盘不动它——它只是"待分析目标"，不是开发环境。
