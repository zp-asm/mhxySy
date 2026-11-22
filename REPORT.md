# 梦幻西游手游（MuMu NX 15）反作弊 / 模拟器检测 / 内存检测 分析报告

> 目标环境：MuMu Player NX（Android 15，`ro.build.version.sdk=35`），实例 0，adb `127.0.0.1:16384`
> 目标进程：`com.netease.my`（PID 3509），Activity `com.netease.game.MessiahNativeActivity`（Messiah 引擎）
> APK：`/data/app/~~38WEFV0rt0UUK5U3KXSWuA==/com.netease.my-z14AcJ0sX5ab2tIo-LhLkg==/base.apk`（1.95 GB）。进程 maps 里加载的是 `lib/arm64`；`files/ntunisdk_so_uuids` 同时列了 `arm64-v8a` 和 `armeabi-v7a`
> 采集时间：本次会话，全部为只读取证。第 8 节是对照 jadx 与探针后的勘误，和前面冲突时以第 8 节为准

---

## 0. 结论摘要（先看这 6 条）

1. **游戏本体跑在 Houdini ARM 转译上**：所有游戏 so 都是 `arm64`，映射在 `0x4000_xxxx_xxxx` 客户机空间，`/system/lib64/libhoudini.so` 已加载。
2. **宿主/root shell 直接读游戏逻辑内存不行**：`/proc/<pid>/mem` 对 Houdini 客户机段返回 `I/O error`（anon）或全 0（file-backed），dalvik/x86 段可读（~200 MB/s）。→ **"读内存"这条路线在 MuMu NX15 上被转译层天然掐死**。
3. **模拟器检测是"游戏主动点名触发"的**：游戏通过 ntunisdk 发 `{"methodId":"startEmulatorDetect", ...}`，由 `libybuaxz.so` 执行、结果写回 `EmulatorDetectResult`。检测结果另存密文 `files/wnyklrieFile`（5.8 KB）上报。
4. **这台机器上 Java 检测已经为真，brand/model 伪装清不掉。** fingerprint 中的 `Build.ID` 是 `V417IR`。`CEmulatorDetector.checkBasic()`、unifix 的 `EmulatorDetector`、下载器 `UniBaseUtil.is_mumu` 都把 `V417IR` 写成 MuMu 固定值。同一条 `detectLocal()` 还会读 `/proc/cpuinfo`，出现 `intel` 或 `amd` 就返回真；本机是 `GenuineIntel`。另外仍在的结构性指纹：cpuinfo 的 `hypervisor`、`abilist` 首位 `x86_64`、`ro.hardware=Redmi` 与 `ro.boot.hardware=kona` 不一致、8 个硬件传感器带 `data-injection`、`libhoudini.so` 已加载。brand/model 已写成 Redmi K70 Pro（`manet` / `23117RK66C`），这几项不看 brand。
5. **反调试/反 hook 是"发命令 + 扫模块 + 校验摘要"三件套**：`ptrace + TracerPid` 读取、`cat /proc/net/tcp | grep :5D8A`（IDA 23946）、`android_server` 进程名、`dl_iterate_phdr` 模块枚举、`ntunisdk_so_uuids` 全模块 MD5 表。
6. **多开检测只在同一 Android 系统内有效**：`SameUidPackage` / `SamePackageCount` / 分身包黑名单（`com.lody.virtual`、`com.excelliance.dualaid`、`com.lbe.parallel`、`com.bly.dkplat`、`com.by.chaos`、`com.qihoo.magic`）。**用 MuMuManager 多实例（每实例独立 Android）= 天然规避；用 MuMu 分身/cloner = 主动送检**。

---

## 1. 反作弊组件清单（静态证据）

| 组件 | 位置 | 关键导入/能力 | 判定 |
|---|---|---|---|
| `libsec-lib.so` (284 KB) | `lib/arm64-v8a` | `ptrace`、`popen`、`getppid`、`__system_property_get`、`dl_iterate_phdr` | 设备风险评级（`rating`/`optionMark`/`type`/`flag`/`info`），易盾系 |
| `libsecsdk.so` (349 KB) | 同上 | `dlopen/dlsym/dl_iterate_phdr/access/stat/mmap` | hook 扫描 / 模块枚举 |
| `libntunisdk.so` (133 KB) | 同上 | `popen`、`fgets`、`atoi`、`__system_property_get`、`dl_iterate_phdr` | `Java_..._Checker_*` JNI + 跑 shell 命令 |
| `libnesdk.so` (1.6 MB) | 同上 | `opendir/readdir`、`fopen`、`dlopen/dlsym`、`pthread_create` | 目录扫描（/proc、/data 面） |
| `libybuaxz.so` (2.4 MB) | 同上 | `fork`、`popen`、`mprotect`、`dl_iterate_phdr`、`__system_property_get` | **模拟器检测执行体**：`Flagclass_Startybuax` / `GetWnyklrieResult(JSON)` / `SensorUtils_onSensorChanged` / `UniNetProxyJni_getResult` |
| `libunisec.so` (1.5 MB) | apk 内 | 极端混淆，字符串加密，仅残留 `RISK` | 核心反外挂（arm64） |
| `libunisec_x86_64.so` (1.2 MB) | **运行时下载**至 `/data/data/com.netease.my/app_ntp0/1.567.0_15670/` | x86_64 原生，含 `/proc/net/tcp`，`.text` 映射 `r-xp` 在正常 x86 地址空间 | **专门给模拟器/x86 环境下发的反外挂模块** |
| `libclienc.so` (匿名映射) | `app_ntp0/...`，`[anon:...]` | 加密通道 | 协议/完整性 |
| `libnep.so` (1.57 MB) | apk | `/proc/self/maps`、`dl_iterate_phdr` | 支付/协议安全 |
| `libpharos.so` (5 MB) | apk | socket/fork/execl/popen/opendir | 网易 UU 网络加速（**非反作弊**，别误判） |
| `ntunisdk_so_uuids` | `files/ntunisdk_so_uuids`（9.7 KB） | 每模块 `路径 + abi + MD5` | **so 篡改/替换检测表** |
| `wnyklrieFile` | `files/wnyklrieFile`（5.8 KB） | 密文 | 模拟器检测结果上报包 |

### 1.1 模拟器检测的触发契约（Java 侧实证）

`com.netease.ntunisdk.Sdkybuaxwny`（`classes.dex`，含 `System.loadLibrary("ybuaxz")`）：

```java
// methodId == "startEmulatorDetect"
Flagclass.EB          = SdkMgr.getPropInt("EB", 0);
UniNetProxyJni.useUniNetProxy = json.optBoolean("enableNetProxy", false);
wnydet.uploadapk      = json.optBoolean("uploadapk", false);   // ← 可上传 APK 做重打包校验
wnydet.jfGameId       = SdkMgr.getPropStr("JF_GAMEID", "");
wnydet.Uid            = json.optString("nonce", SdkMgr.getUdid());
wnydet.Startybuax();                                           // → libybuaxz.so
wnydet.Detectfinish.tryAcquire(json.optInt("waittime", 40), SECONDS);
extendFuncCall(wnydet.GetWnyklrieResultJSON());                // 结果回给游戏
SdkMgr.setPropInt("EmulatorDetectResult", wnydet.WnyklrieResult);
```

另一条：`{"methodId":"GetEmulatorResult"}` 可随时再取一次结果。

**含义**：`Sdkybuaxwny.init()` 不调用检测。`extendFunc` 只在 JSON 的 `methodId` 为 `startEmulatorDetect` 时执行 `Startybuax()`。这份 jadx 工程里，该字符串只出现在这个方法中，调用方还没定位到。`uploadapk` 被写入 `Flagclass.uploadapk`；`onlysetuid` 读出后没有使用。Java 里看不到 APK 上传，也看不到服务端处置。

### 1.2 `libsec-lib.so` 里的检测字符串（原文，偏移即证据）

```
0x00037122 simulator        0x00037311 XposedBridge.jar      0x00037066 TracerPid:
0x0003716f MuMu             0x00037322 com.saurik.substrate  0x0003707b hasIdaServerPort
0x00037197 Genymotion       0x00037345 ProcMapsHasXposed     0x000370a0 cat /proc/net/tcp | grep :5D8A
0x000371d6 goldfish         0x00037357 ProcMapsHasSubstrate  0x000370bf android_server
0x00037208 Emulator         0x00037417 StacktraceHasXposed   0x000370d3 /system/bin/su
0x00037150 google_sdk       0x00037487 XposedHelpers         0x00037119 ls -l %s
0x0003715b Droid4X          0x00037143 ttVM_Hdragon          0x000371f6 ro.product.device
0x000371a6 TiantianVM       0x00037222 vbox86                0x000372ab ro.build.fingerprint
0x0003766c SamePackageCount 0x000376dc com.qihoo.magic       0x000376f1 u0_a%d
0x00037732 SameUidPackage   0x000376cb com.lody.virtual      0x0003771c miui_ps
0x00037695 com.by.chaos     0x000376a2 com.lbe.parallel      0x00037686 com.bly.dkplat
```

`rating` / `optionMark` / `type` / `flag` / `info` 是相邻字符串。打分循环没反编译，不能把它们当成已经还原的模型。

---

## 2. 模拟器侧：当前 MuMu 的伪装 vs 实际破口

MuMuManager 实配（`MuMuManager setting --vmindex 0 --all_writable`）：

```
phone_brand   = Redmi          gpu_model.custom = Adreno (TM) 640
phone_model   = K70 Pro        resolution       = 960x540 / dpi 220
phone_miit    = 23117RK66C     root_permission  = true
phone_imei    = 863515041681530 renderer_mode   = vk
```

系统 props（已伪装）：`brand=Redmi`、`model=23117RK66C`、`device/name=manet`、`fingerprint=Redmi/manet/manet:15/V417IR/1171:user/release-keys`、`ro.debuggable=0`、`ro.kernel.qemu=`（空）。

### 破口（按被检出概率排序）

| # | 检测点 | 实际值 | 说明 |
|---|---|---|---|
| 0 | `Build.ID` | fingerprint = `Redmi/manet/manet:15/V417IR/1171:user/release-keys`，即 `Build.ID=V417IR` | Java 写死的 MuMu 代号。`CEmulatorDetector.checkBasic()` 因此为真，后面的文件/QEMU 属性计数不会再跑 |
| 1 | `/proc/cpuinfo` | `vendor_id: GenuineIntel`、`model name: Intel(R) Core(TM) i5-10400`、flags 含 `hypervisor` | `isEmulatorFromCpu()` 见到 `intel`/`amd` 即真。arm 真机这里是 `CPU implementer: 0x41` |
| 2 | `ro.product.cpu.abilist` / `ro.dalvik.vm.isa.arm64` | `x86_64,arm64-v8a,x86` / `x86_64` | 真机首位是 `arm64-v8a` |
| 3 | `ro.hardware` vs `ro.boot.hardware` | `Redmi` vs `kona` | 互相矛盾（kona 是骁龙 865 平台名，不该出现在"Redmi"品牌位） |
| 4 | `ro.board.platform` | `Redmi` | 真机是 `kona`/`sm8550` 之类 |
| 5 | 传感器 | 8 个硬件传感器 `flags: 0x00000010`（`data-injection`），速率都是 `minRate=2.00Hz/maxRate=100Hz`，含 `Ambient Temperature`。handle `0x5f*` 的融合传感器（重力、旋转矢量、线性加速度）`flags=0`，没有该标志 | `SensorUtils.onSensorChanged` 只有 native 声明。Java 看不到它读 flag、读数值，还是只采样 |
| 6 | `libhoudini.so` 存在 / `libc++` 在 `/system/lib64/arm64/` | 存在 | 转译层指纹 |
| 7 | 图形 | `Adreno (TM) 640` + GL 版本组合 | 与 `manet`(K70 Pro / Adreno 750) 不匹配 |

> 结论：这台实例上，CrashHunter 写入 `DiInfo` 的 `is_emulator` 为 true。依据是 `Build.ID=V417IR` 和 cpuinfo 里的 Intel，两条都在已反编译的 Java 里。Redmi 的 brand/model 不参与这两条。cpuinfo、ABI、houdini 也不在 props 伪装覆盖的键上。服务端拿到标记后如何处置，这次没有登录结果，也没有封禁记录。

---

## 3. 内存侧：读游戏内存会被怎么发现 / 能不能读

### 3.1 实测可读性（root shell，KernelSU 已授权 `uid=0 context=u:r:su:s0`）

```
进程状态:  TracerPid: 0    Seccomp: 0    CapEff: 0000000000000000
dalvik/x86 段 (0x02000000 等)   → 可读，16 MB / 80 ms ≈ 200 MB/s
Houdini 客户机 file-backed 段   → 读回全 0（0x400020c00000 = libGame.so 首段）
Houdini 客户机 anon 段          → dd: /proc/3509/mem: read error: I/O error
```

`maps` 实证（注意**没有任何 r-xp**）：

```
400020c00000-400021f9e000 r--p 00000000 .../lib/arm64/libGame.so
400025450000-40002591f000 rw-p 0484e000 .../lib/arm64/libGame.so
77d3fb412000-77d3fb531000 r-xp 00000000 .../app_ntp0/1.567.0_15670/libunisec_x86_64.so   ← 只有 x86 模块是真 r-xp
77d3fdc960000-...         r-xp .../system/lib64/libhoudini.so
```

**判定**：arm64 游戏逻辑（`libGame.so` 82 MB，Messiah 引擎 + Lua VM）全部在 Houdini 客户机空间，**宿主 root 用 `/proc/<pid>/mem` 读不到**。这不是反作弊写的限制，是转译层映射方式（读时缺页无法在读取上下文完成 → EIO）。所以：

- ❌ `Cheat Engine / GG修改器 / 自写 /proc/mem 扫描器` → 在 MuMu NX15 上对**游戏本体**无效
- `process_vm_readv` 这次没测。它和 `/proc/<pid>/mem` 走同一套页表，所以多半也是 EIO；这是推断，不是实测
- ⭕ 进程内注入 x86_64 SO 后**用 houdini 的客户机 API**读 → 技术上可行，但那是把整条反作弊检测面全引过来（见 3.2），且 `libGame.so` 字符串全加密（抽 23 万条 strings，无一可读业务串），偏移还得纯靠动态定位

### 3.2 真要被发现，是这 6 条

| 检测 | 机制 | 证据 |
|---|---|---|
| ptrace attach | 读 `/proc/<pid>/status` 的 `TracerPid:` | `libsec-lib.so:0x37066 TracerPid:` |
| IDA 调试 | `popen("cat /proc/net/tcp \| grep :5D8A")`（23946=IDA） + 扫 `android_server` 进程名 | `0x370a0` / `0x370bf` |
| Java 调试 | `Debug.isDebuggerConnected()` / `waitingForDebugger()` | `0x3703b` / `0x37053` |
| Hook 框架 | `dl_iterate_phdr` 遍历模块名 + `/proc/<pid>/maps` 匹配 `XposedBridge.jar`/`substrate` + 调用栈扫描 | `libsecsdk/libunisec/libnesdk` 全带 `dl_iterate_phdr`；`0x37345/0x37357/0x37417` |
| 模块被替换 | `ntunisdk_so_uuids` 里每个 so 的 MD5 对表 | `files/ntunisdk_so_uuids` |
| 代码被改 | `libunisec`（混淆）内部完整性校验；`libsecsdk` `mprotect` | 静态导入面 |

**唯一相对干净的路子**：只读、短时、不落文件、不经 ptrace——即"紧邻宿主进程但用非 ptrace 通道"。但这条在 3.1 已经被转译层堵死（读不到），所以**中控台不要押内存路线**。

---

## 4. 多开侧

同一 Android 系统内可被查的：`SameUidPackage`、`SamePackageCount`、`/data/data/*` 计数、分身包黑名单、`u0_a%d` uid 解析、`miui_ps` 兼容解析。

- ✅ **MuMuManager 多实例**：每实例是**独立 Android 虚拟机**（`F:\mumu\MuMuPlayer\vms\MuMuPlayer-15.0-0`），互相不可见 → 上述检测全部拿不到
- ❌ **MuMu 分身 / `com.netease.mumu.cloner`**：同系统多开 → uid/包名/路径直接对上，**等于自己上交**
- ❌ 用户态双开插件（`com.lody.virtual` / `dualaid` / `lbe.parallel` / `dkplat` / `chaos` / `qihoo.magic`）→ 全在黑名单里

---

## 5. 服务端处置：这次没有证据

上面各条能确定的是客户端标记。仓库里没有封禁记录，也没有协议样本。下面是尚未取证的假设，不能当成已观察到的封号原因：

- 在线曲线（24h 不间断、单号 18h+）
- 操作熵（点击/滑动的时序、坐标抖动、无操作空白段）
- 收益路径（同一产出点、固定 NPC 循环、拍卖/摆摊价格特征）
- 账号关联（同 IP / 同设备指纹簇 / 同注册批次 / 资金闭环）

这四条都还没有样本。不能从它们推出“静态检测过了就一定封”或“过了就一定不封”。

---

## 6. 中控台设计（可落地）

### 6.1 通道选型（实测数据）

| 通道 | 实测 | 结论 |
|---|---|---|
| `adb exec-out screencap -p` | **471–800 ms/帧**（960x540，1.0–2.1 MB PNG） | 只能做低频巡检 |
| **scrcpy 5.0.1 H.264 视频流** | 30–60 fps | ✅ 主通道（`--no-audio --video-codec=h264`） |
| MuMu 窗口抓取（`render_wnd` HWND + DXGI/dxcam） | 宿主原生，最省 | ✅ 多开时首选（`MuMuManager info` 给 `render_wnd`） |
| `adb shell input tap/swipe` | 40–120 ms/次 | 兜底。VM 里触摸设备只有 `Xiaomi Touchscreen`；游戏有没有读 `InputDevice` 来源，这次没在代码里找到 |
| **宿主窗口 + pywin32 注入** | 宿主原生 | ✅✅ 生产首选：经 `nemuinput` → 真实 uinput 触摸 |

**输入侧实证**：VM 内只有一个触摸设备 `Xiaomi Touchscreen`（deviceId=3，`Sources: TOUCHSCREEN`，`nemuinput` 服务 pid 777 产生）。
`adb shell input tap` 是 InputManager 注入（来源可判）；宿主窗口注入鼠标 → MuMu 转换 → 落在同一个 uinput 设备 → 游戏侧与真人一致。

**端到端已跑通**（`tools/e2e_check.py`）：
```
模板 task 命中 0.9956 @ (796,80)  →  tap(824,97)  →  画面变化 90.7%（面板打开）
                                →  BACK(4)       →  与初始帧差 4.7%
```
结论：`screencap` 尺寸 960x540 与 `input` 坐标一致（`wm size` 报 540x960 是自然竖屏，别用它算坐标）。

### 6.2 分层

```
┌──────────────────────────────────────────────┐
│ 调度层 (asyncio)：实例池 / 任务队列 / 节流 / 日志 │
├──────────────────────────────────────────────┤
│ 实例通道层：MuMuManager(生命周期) + scrcpy(视频/控制) │
├──────────────────────────────────────────────┤
│ 感知层：模板匹配(cv2) + OCR(RapidOCR) + 状态机    │
├──────────────────────────────────────────────┤
│ 执行层：点击/滑动/按键，带人类化抖动与停顿        │
└──────────────────────────────────────────────┘
```

### 6.3 反检测工程约束（照做）

1. 中控**全部跑在宿主机**，VM 内不装 frida-server、不落脚本、不留 so
2. 不碰 `libGame.so`、不 patch、不改 APK（`uploadapk` 会校验）
3. 每实例差异化：`MuMuManager simulation -sk android_id/mac_address/imei` + `setting phone_brand/phone_model/phone_miit/resolution_*/gpu_model.custom`
4. 实例间错峰启停（`launch_time` 会进 `MuMuManager info`，但游戏看不到宿主信息）
5. 输入人类化：随机 60–180 ms 停顿、坐标 ±3 px、滑动分 3–6 段、20% 概率"发呆"2–8 s
6. 单号在线时长 < 10 h/日，强制下线窗口随机
7. 单机实例数受 CPU 约束（本机 i5-10400 / 4 核分给实例 0）：**实测建议 ≤ 4 实例/台**，`performance_cpu=4, performance_mem=4` 时每实例约 0.9 GB RSS

---

## 7. 下一步（要真机验证的三件事）

1. `libunisec_x86_64.so` 的检测点定位：它是唯一真 `r-xp` 的原生模块，`/proc/net/tcp` 已确认 → IDA 里找引用它的函数，能拿到"它到底查什么端口/进程"
2. `Flagclass.WnyklrieResult` 的取值域：hook `Java_com_netease_ybuax_Flagclass_Startybuax` 的返回值，直接读**本机被判定的结论**（0/1/2/…），这决定"这台机器在服务端的标签"
3. 行为层抓包：`libnep`/`libclienc` 加密，但可看**频率/时序/包长分布**，用来对齐中控的节流参数

> 这三件事都需要在 VM 内做（frida-server x86_64 + hook），属于**高检测面操作**，建议只在离号/小号上做，且做完立刻恢复镜像。

---

## 8. 勘误与补遗（对照 jadx + 探针）

第 0–7 节把「字符串出现」写成了「这条检测会生效」，又把 ybuax 一条链路当成了全部模拟器检测。下面按证据强度重写缺口。

### 8.1 模拟器检测至少四条，结果互不相通

| 通道 | 代码 | 本机结果 | 结果去向 |
|---|---|---|---|
| ybuax | `Sdkybuaxwny` → `libybuaxz.so` 的 `Startybuax` | 未知。`Flagclass.WnyklrieResult` 初值是 `-1`，取值域没看到 | `EmulatorDetectResult` 整型属性，另有 `GetWnyklrieResultJSON()` |
| CrashHunter | `CEmulatorDetector.detectLocal` | **true**。`checkBasic()` 因 `Build.ID=V417IR` 为真；`isEmulatorFromCpu()` 因 cpuinfo 含 `intel` 也为真 | `DiInfo` JSON 字段 `is_emulator`，同包还有 `is_rooted`、`package_fingerprint`（证书 SHA1，native） |
| unifix | `com.netease.ntunisdk.unifix.util.j`，日志标签 `UniSDK EmulatorDetector` | 基础判断同样命中 `V417IR`。还查 Windows Subsystem for Android、雷电路径 `/system/app/EmuCoreService/EmuCoreService.apk`、包名 `com.vphone.helper` / `com.android.flysilkworm` / `com.android.coreservice` | 热修模块自己的布尔值，和 ybuax 的整型不是同一个字段 |
| 分散调用 | `UniSdkUtils.isEmulator` / `isMuMu` 被 webview、相册、一键登录引用 | `UniSdkUtils` 本体不在这份 jadx 树里。支付库反射失败时退回 `Build.ID` ∈ {`V417IR`,`W528JS`,`X639KT`}。下载器 `UniBaseUtil` 把 `is_mumu` 设成 `Build.ID==V417IR` | 各 SDK 自己的上报字段 |

URS 登录库 `Devices.isEmulator()` **没有** `V417IR` 这一项。按它列出的 generic / goldfish / nox 条件，当前 Redmi 伪装对不上，这个布尔值可以是 false。同一台机器上，CrashHunter 为 true、URS 这条可以为 false。

`CUtil.getCPUType()` 读 `ro.product.cpu.abi`。本机这个值是 `x86_64`，函数返回 `"x86"`，`"x86".contains("x86")` 为真。`detectLocal()` 在 `checkBasic()` 已经为真之后，仍会执行 `isEmulatorFromCpu()`；cpuinfo 含 `GenuineIntel`，这里直接返回 true。

QEMU 属性要凑满 5 条才算命中（`ro.kernel.qemu=1`、`ro.hardware=goldfish` 等）。本机这些键是空或 Redmi，计数到不了 5。因为 `checkBasic()` 已经为真，文件探测和这组属性计数不会执行。

进程入口是 `UFProxyApplication`（unifix 热修），logcat 里有 `App instance already created`。组件表原先没写这个 Application。

### 8.2 原先说过头的几句

- **`uploadapk` 会送 APK 并因此封号。** Java 只把布尔值存进 `Flagclass`。`onlysetuid` 读出后丢弃。
- **检测由 Lua 点名、SDK 不自启。** `init()` 确实不调用 `Startybuax()`。`startEmulatorDetect` 在已反编译的 Java 里没有第二个引用，调用方仍可能在 native 或脚本里。
- **`libybuaxz` 用传感器 flag 判模拟器。** 只有 `SensorUtils.onSensorChanged(SensorEvent)` 的 native 声明。8 个硬件传感器带 `data-injection`；融合传感器没有。判定式没看到。
- **`ntunisdk_so_uuids` 就是运行时 MD5 对照表。** 文件是明文：`路径 + abi + 32 位十六进制 + 末尾一个 0`，arm64 与 armeabi-v7a 都有，含 `libGame.so`。CrashHunter 有 native `CUtil.getFileMD5`。对照循环没定位到，文件存在不等于每次启动都比对。
- **`wnyklrieFile` 是二进制密文。** 解开 base64 后是 4340 字节，头不是 JSON。不能当成 `EmulatorDetectResult` 的明文。见第 9.2 节。
- **`libclienc.so` 是加密通道。** maps 里是三段匿名映射，可执行段约 8 KB，路径挂在 `app_ntp0/1.567.0_15670/` 下。没有导入表或字符串证明它负责协议加密。
- **`libnep` / `libGame` 的能力来自导入表。** `elf_triage` 对这两个文件的导入、导出计数都是 0。`libnep` 的 `/proc/self/maps` 来自字符串文件，不是 `.dynsym`。`libGame.so` 的字符串里至少有一条 Messiah 的 C++ 修饰名（`_ZTHN7Messiah30GExternalProfilerThreadContextE`），`luaL_` / `luaopen_` 没有命中。旧报告写的「23 万条字符串全无业务串」没有逐条复查。
- **`libunisec` 只残留 `RISK`。** arm64 那份的明文字符串这次没重抽。x86_64 那份的 `/proc/net/tcp` 引用已经定位到 `0x73370`，见第 9.4 节。
- **`process_vm_readv` 同样 EIO。** 只测了 `/proc/<pid>/mem`。同一页表是推断，NDK 探针没跑。
- **`adb shell input` 会被游戏认出。** 实测只有：VM 内一个触摸设备 `Xiaomi Touchscreen`（deviceId=3），`nemuinput` 在写它。游戏侧读取 `InputDevice` 来源的代码没找到。
- **device_probe 第 4 节是易盾日志。** 内容是 Watchdog 和 WindowManager。没有 `wnydebug`、`CEmulatorDetector`、`UniSDK EmulatorDetector` 的行。
- **本作长期允许模拟器登录。** 没有登录结果或处罚记录。

`libsec-lib.so` 字符串表里，`0x37143` 只对应 `ttVM_Hdragon`，`TiantianVM` 在 `0x371a6`。同一段还有旧表没列的：`intel`、`Xiaomi`、`Netease`、`Andy`、`TTVM`、`i686`、`os.arch`、`hasIdaServerProcess`、`hook`，以及 `/system/xbin/su`、`/system/sbin/su`、`/vendor/bin/su`。`rating` / `optionMark` / `type` / `flag` / `info` 是相邻字符串，打分循环没反编译，不能当成已经还原的模型。

### 8.3 ybuax 的 HTTP 客户端（调用点未接上）

`com.netease.ybuax.HttpTools` 和检测类在同一个包。允许的主机名只有 `xyq-service.netease.com` 和 `xyq-service-gcp.easebar.com`。Cookie 名 `unisec_sessionId`。证书校验是空实现，主机名仍必须落在这两个名字上。POST 体类型是 `application/json`。Java 里没有 `HttpRequest` 的调用者，native 是否使用它还不知道。`Flagclass.EB` 来自属性 `EB`，代码默认 0。`assets/ntunisdk_config` 是 `{}`，包内没有 `ntunisdk.cfg`，`CUtil.getEB()` 读不到 `EB` 字段。`getSuitableUrl()` 只有在这个值等于 `"1"` 时才把主机从 `netease` 换成 `easebar`。

### 8.4 热更目录里实际有两份模块

`app_ntp0` 同时留着：

| 目录 | `libunisec_x86_64.so` | 备注 |
|---|---|---|
| `1.540.1_15401` | 501088 字节 | 未映射 |
| `1.567.0_15670` | 1239152 字节 | 当前 `r-xp` 映射的是这一份 |

`1.567.0_15670/.unzip/classes.dex` 以 `r--p` 映射在 so 前面。`files/` 里还有 `ngplugin/`、`uniTrace/`、`05446735E3EA099C1D6215051A1AE955`（77073 字节）、`messiah_app_file_directory`（53 字节）。这些都没打开。`share_compat_config.json` 是微信/QQ/微博的分享 Activity 映射，和检测无关。

本机 `root_permission=true`，取证 shell 是 `uid=0`。游戏进程 `CapEff=0`。四条 `su` 路径在这台镜像上都不存在，见第 9.3 节。

### 8.5 当时还开着的口

下面 1–5 的测量在第 9 节。第 6 条仍然没有样本：服务端有没有因为 `is_emulator=true` 处罚账号。

1. AndroidManifest。
2. `startEmulatorDetect` 的调用方。
3. `WnyklrieResult` 的取值，以及 `wnyklrieFile` 解码后的内容。
4. `libunisec_x86_64.so` 里谁引用 `/proc/net/tcp`。
5. `ro.product.cpu.abi`、四条 `su` 路径、Nox/雷电/vphone 特征文件。
6. 服务端处罚。没有登录结果，也没有协议样本。

---

## 9. 补完的测量，以及中控怎么用这些结果

### 9.1 包体

从 APK 的二进制清单和这台机器的 `dumpsys package com.netease.my` 读到：

| 项 | 值 |
|---|---|
| 包名 | `com.netease.my` |
| versionName / versionCode | `1.567.0` / `15670`，与已映射的 `app_ntp0/1.567.0_15670` 一致 |
| minSdk / targetSdk | 21 / 30 |
| Application | `com.netease.ntunisdk.unifix_hotfix_library.proxyApplication.UFProxyApplication` |
| 热修要换上的类 | meta `UNIFIX_APPLICATION_CLASS_NAME`。清单字符串里还有 `NtSdkApplication` 和 `com.netease.android.protect.StubApp` |
| 游戏 Activity | `com.netease.game.MessiahNativeActivity`，meta `android.app.lib_name` |
| 安装标志 | `LARGE_HEAP`。没有 `DEBUGGABLE` |
| 渠道资产 | `assets/ntunisdk_common_data`：`JF_GAMEID=g18`，`APP_CHANNEL=netease.innerdomin_cps_dev` |

`assets/ntunisdk_config` 的内容是 `{}`。`assets/ntunisdk_data` 是分号分隔的插件表，其中有 `Sdkybuaxwny`。`AppChannel` 会打开这个资产，UniSDK 按这张表加载渠道。

`assets/emulatordetector_data` 不是检测规则。它是一份 base64 的 UniSDK JSON：`DEBUG_MODE=0`、`OVERSEA_CHANNEL=0`、`PROTOCOL_LAUNCHER=1`、`JF_GAMEID=g18`，其余是支付和分享配置。

`res/xml/network_security_config.xml` 的字符串池里有 `cleartextTrafficPermitted`、`base-config`、`trust-anchors`、`certificates`、`system`。属性布尔值还在二进制 XML 的类型字段里，没有拆成 true/false。

权限里和本机检测有关的两条：`READ_PHONE_STATE` 当前 `granted=false`；清单里还有 `HIGH_SAMPLING_RATE_SENSORS`。

### 9.2 `startEmulatorDetect` 没有第二个明文调用点

在 APK 成员和 `libGame.so` 里搜这些字节：

| 字符串 | 出现位置 |
|---|---|
| `startEmulatorDetect` | 只有 `classes.dex`（`Sdkybuaxwny.extendFunc`） |
| `uploadapk` | `classes.dex`、`classes8.dex`（`Flagclass` 的字段） |
| `ybuaxwny` | `classes.dex`，以及 `assets/ntunisdk_data` 的插件名 |
| `libGame.so` | 上面三个都是 0 |

`assets/_ntcfgss.dat`（8.7 MB）里有一处 `EmulatorDetectResult` 和一处 `V417IR`。上下文是按字母排的词表（`EmptyCoroutineContext`、`Emulator`、`Enable`，以及 `V2056A`、`V417IR`、`VAID`）。这是字符串池，不是调用。`startEmulator`、`ybuax`、`uploadapk` 在这个文件里是 0 次。

`Java_com_netease_ybuax_Flagclass_GetWnyklrieResult` 在 `libybuaxz.so` 的地址是 `0x9e5a8`，大小 `0x6f0`。开头是对两个全局字的加减乘，不是 `mov w0, #常量; ret`。取值域静态还原不出来。`Startybuax` 在 `0x9c910`，大小 `0xc98`。

`wnyklrieFile` 按 base64 解出 4340 字节，可打印字符比例 0.38，头 16 字节是 `b0 c8 9f 91 6f 3c 3c df ...`，不是 JSON。

这次 `logcat -d -t 400` 里没有 `wnydebug`、`CEmulatorDetector`、`Sdkybuaxwny`。ybuax 的整数仍然只有 Java 初值 `-1` 这一条已知。

### 9.3 本机又读了一次

| 检查 | 结果 |
|---|---|
| `getprop ro.build.id` | `V417IR` |
| `getprop ro.product.cpu.abi` | `x86_64` |
| `/system/bin/su`、`/system/xbin/su`、`/system/sbin/su`、`/vendor/bin/su`、`/sbin/su` | 都不存在。`command -v su` 也没有 |
| adb shell | `uid=0` `context=u:r:su:s0`。这是 shell，不是游戏进程 |
| `/sys/kernel/debug/x86` | 存在。这是 `CEmulatorDetector` 和 unifix 的 `ext_files` 项 |
| `/dev/socket/genyd`、`qemud`、`qemu_pipe`、nox、雷电 `EmuCoreService.apk` | 不存在 |
| `com.vphone.helper`、`com.android.flysilkworm`、`com.android.coreservice` | 未安装 |
| `com.netease.mumu.cloner` | 系统 priv-app，versionName `1.0.64.20260722.1219` |
| `libhoudini.so` | 存在 |

`checkBasic()` 已经因 `V417IR` 为真，所以 `/sys/kernel/debug/x86` 在当前调用路径上不会被执行。文件本身在。Nox、雷电、vphone 的包和特征文件不在。

已反编译的分身包黑名单里没有 `com.netease.mumu.cloner`。它预装在镜像里。`dumpsys` 这段没有打出它的 `userId`，不能说它和 `com.netease.my` 同 uid。

### 9.4 `libunisec_x86_64.so` 里的 `/proc/net/tcp`

`/proc/` 开头的明文字符串只有 `/proc/net/tcp`，文件偏移 `0xeff70`。引用指令在 `0x7339f`：`lea rsi, [rip + 0x7cbca]`。函数从 `0x73370` 到 `0x734cc`：

- 把一块栈缓冲、这个路径、长度 `0x400` 交给 `0x441e0`
- 再取比较串，按行看缓冲
- 对行内 `+0xf` 的字段用基数 10 做转换
- 用长度 4 和另一段数据比较
- 相等则把栈上的标志字节设为 1，函数返回这个字节

比较用的那几段数据不是明文。端口或进程名没有以 ASCII 放在这个 so 里。`1.540.1` 那份没有拉回本地，当前映射的是 `1.567.0`。

### 9.5 中控按这些结果执行

1. **把「这台是模拟器」当成既定输入。** `ro.build.id`、`ro.product.cpu.abi`、cpuinfo 三条都已经读到，CrashHunter 的 `detectLocal()` 为真。Redmi 的 brand/model 不参与这三条。宿主抓帧和点击也不改它们。MuMuManager 多开的每个实例是同一类镜像，各自仍会得到 `is_emulator=true`。多开避开的是第 4 节的同 uid / 同包计数。
2. **客户机保持现在没有 su 文件的状态。** 四条 `su` 路径和 `PATH` 当前都是空的。调试器、`android_server`、额外 so 放进镜像，会落到 `libsec-lib` 的进程/端口字符串和 9.4 的 tcp 解析上。中控继续只跑在宿主上。
3. **不要用预装的 `com.netease.mumu.cloner` 在同一个 Android 里再开一份游戏。** 多实例用 MuMuManager 的独立虚拟机。这个包预装本身不在已看到的包名黑名单里。
4. **不要读 `EmulatorDetectResult` 或 `wnyklrieFile` 来做分支。** 明文调用点只有处理函数自己。返回值函数是混淆的，文件解开后是二进制，日志里也没有这次运行的结果。Java 侧目前只能确认初值 `-1`。CrashHunter 的 `is_emulator` 不依赖这次调用。
5. **客户端标记和账号处罚分开记。** 标记在这台机器上是 true。处罚没有登录记录、没有协议样本、没有对应 log。第 5 节的在线时长和操作熵仍然是假设，不写进调度器。
6. **包体和 so 保持原样。** `uploadapk` 仍然只是一个存进去的布尔值，但清单、`ntunisdk_so_uuids` 和 `CUtil.getFileMD5` 都在。Houdini 客户机段照旧读不到。这两条不改变第 6 节的宿主通道。

---

## 10. 复核结论（对照 REVIEW.md）

第 8–9 节经独立复核**基本成立**；第 0–7 节已撤回 6 条（`libsec-lib` 未加载、无 su 二进制、`process_vm_readv` 未测、输入来源未被读、`wnyklrieFile` 非明文、封号面无样本）。详见 `REVIEW.md`。

本轮新增的硬证据（两边原文都没有）：

### 10.1 游戏自己落盘的判定：`files/uniTrace/crashhunter/crashhunter.di`

```json
"is_emulator":"true"  "is_rooted":"false"  "hardware":" placeholder"  "cpu":"Redmi"
"cpu_abi":"arm64-v8a" "cpu_abi2":"x86_64"  "rom_name":"MIUI_15_V417IR release-keys"
"local_ip":"10.0.2.15"  "gl_renderer":"Adreno (TM) 640"
"battery_level_info":{"0":"99.00%","1800":"84.00%","3600":"71.00%"}
"unisdk_device_id":"2b8837c8aca36189"
```

- `is_emulator=true` 是**已发生**的事实；`is_rooted=false` 说明"没有 su 文件"就够，adb root 不暴露
- `hardware=" placeholder"`（带前导空格）、`cpu="Redmi"`、`local_ip=10.0.2.15`、`Adreno 640 vs 23117RK66C`、30 分钟掉 15% 电量：五条 MuMu 专属痕迹，**props 改不掉**
- 刷新周期 `di_refresh_interval: 1800`（`crashhunter_config.txt`），启动另写一份 `crashhunter_pre.di` → **这就是反检测的验收 oracle**

### 10.2 设备号的落盘位置（决定多开是否被关联）

```
app_uf_data/device_id.info      = 2b8837c8aca36189      ← unisdk_device_id 本体，明文
app_uf_data/install_id.info     = {"install_id":"8a1b40b306946e70033709f712d1caa7"}
app_uf_data/eb.info             = {"eb":false}          ← Flagclass.EB 来源
crashhunter.param               = {"transid":"2b8837c8aca36189_1795335655583_779183027",
                                   "uid":"359094790","username":"梦中做运动丶"}
```

`transid` 前缀即设备号 → 服务端按设备号关联账号；`MuMuManager clone` 拷整个 data 分区 → 克隆实例**同号**。
落地步骤与风险见 `REVIEW.md` §4.1（需在离号实例上做）。

### 10.3 加载实测（决定哪些"检测"根本不跑）

`/proc/3509/maps` 计数：`libsecsdk` 3 / `libunisec` 3 / `libybuaxz` 3 / `libntunisdk` 3 / `libpharos` 3 / `libclienc` 3 / `libGame` 5，而 **`libsec-lib` 0 / `libnesdk` 0 / `libnep` 0**。
第 1.2 节那张字符串表归属的模块**不在进程内**，其检测能力在本作常规流程中不生效。
