# 交叉复核：对第 8–9 节的审计，以及本轮新增的硬证据

对象：`REPORT.md` 第 8 节（勘误与补遗）、第 9 节（补完的测量）
复核方式：能独立验的全部重跑了一遍（dynsym 地址、字节搜索、设备 props、文件格式、Java 源码路径）；不能验的标明"未验证"。
结论：**第 8–9 节基本成立，我的第 0–7 节有 6 处必须撤回。** 另外找到一份双方都没提到的证据，它把"模拟器标记是否真的发生"从推断变成既成事实。

---

## 1. 我撤回的（上一版报告的错误）

| 原说法 | 实际 | 影响 |
|---|---|---|
| 「`libsec-lib.so` 的字符串表 = 当前生效的检测」 | 该 so 在游戏进程里 **maps 计数 = 0，根本没加载** | **整张表降级**。TracerPid / IDA 23946 / `android_server` / Genymotion / MuMu / `su` 路径那一套，在本进程内不运行。它属于支付 SDK（`com/netease/epay/brick/seclib/Reh`），只在支付链路加载 |
| 同样未加载 | `libnesdk.so` = 0、`libnep.so` = 0（只有 `libsecsdk` / `libunisec` / `libybuaxz` / `libntunisdk` / `libpharos` / `libGame` / `libclienc` 有映射） | "目录扫描 / maps 读取 / 协议加密"这些能力描述都失去归属 |
| 「KernelSU 已授权 su」 | 机器上**没有 su 二进制**：`/system/bin`、`/system/xbin`、`/system/sbin`、`/vendor/bin`、`/sbin` 全不存在；`command -v su` 空。`adb shell` 是 uid=0，但那是 MuMu `root_permission=true` 让 adbd 以 root 跑，**不是 su 提权** | 反过来说：`is_rooted=false` 是真的，这是个**干净状态**，别去破坏它 |
| 「process_vm_readv 同样 EIO」 | 只测过 `/proc/<pid>/mem`，`process_vm_readv` **没测** | 内存路线结论保持"未验证"，需 NDK 探针 |
| 「adb input 会被游戏认出」 | 游戏侧读 `InputDevice` 来源的代码**没找到** | 降级为"未知/低风险"；宿主注入的理由改为性能，不再是防检测 |
| 「`wnyklrieFile` 是检测结果明文」 | base64 → 4340 字节，头 `b0c89f916f3c3cdf…`，可打印率 0.374，**不是 JSON** | 不能拿它做分支 |
| 「封号来自在线曲线/操作熵」 | 无样本 | 按第 5 节处理：仅假设，不进调度器 |

---

## 2. 我独立复核成立的（这些可以直接用）

| 对方结论 | 我的复核方式 | 判定 |
|---|---|---|
| `checkBasic()` 里 `"V417IR".equals(Build.ID)` 使本机为真 | 读 `CEmulatorDetector.java` 原文 + `getprop ro.build.id` = `V417IR` | ✅ 成立 |
| `CUtil.getCPUType()` 读 `ro.product.cpu.abi`，`"x86_64".contains("x86")` → 返回 `"x86"`，`detectLocal()` 里 `"x86".contains(...)` 恒真 | 读源码 + `getprop ro.product.cpu.abi` = `x86_64` | ✅ 成立，**且这不依赖任何伪装** |
| `isEmulatorFromCpu()` 读 `/proc/cpuinfo` 含 `intel` → true | 源码 `ShellAdbUtils.execCommand("cat /proc/cpuinfo")` + 本机 cpuinfo = GenuineIntel | ✅ 成立（会起子进程） |
| URS `Devices.isEmulator()` **无** V417IR 分支 → 可为 false | 读 `Devices.java` 全文条件，无 `Build.ID` 项 | ✅ 成立：同机 CrashHunter=true / URS=false |
| `GetWnyklrieResult` @`0x9e5a8` size `0x6f0`；`Startybuax` @`0x9c910` size `0xc98` | 我用 pyelftools 独立读 `.dynsym` | ✅ 数值完全一致 |
| `/proc/net/tcp` 在 `libunisec_x86_64.so` 文件偏移 `0xeff70` | 字节搜索 | ✅ 一致 |
| `startEmulatorDetect` 在 `libGame.so` 里 0 命中 | 我在 `libGame.so`(78 MB) 搜 6 个关键串，全 0 | ✅ 成立 |
| `_ntcfgss.dat` 里有 1 处 `EmulatorDetectResult`、1 处 `V417IR` | 我从 apk 里取该成员搜，命中数一致（8 764 560 字节） | ✅ 成立 |
| su 四路径不存在、`/sys/kernel/debug/x86` 存在 | 设备实测 | ✅ 成立 |
| `ntunisdk_so_uuids` 是明文表 | 我读过：`路径 + abi + 32 hex + \0`，含 `libGame.so` | ✅ 成立 |

唯一要补一句：`_ntcfgss.dat` 那处 `EmulatorDetectResult` 虽然只是词表，但**它是本项目里"脚本层"唯一还活着的线索**（见 §4.2）。

---

## 3. 双方都没提到、但决定性的新证据

### 3.1 游戏自己把判定写进了磁盘：`crashhunter.di`

路径：`/data/data/com.netease.my/files/uniTrace/crashhunter/crashhunter.di`（另有 `crashhunter_pre.di`）
刷新：`crashhunter_config.txt` 里 `di_refresh_interval: 1800`（30 min 一次），文件 1.6 KB / 55 字段

实测值（原文摘录）：

```json
{"time":"2026-11-22 17:20:55 +0800","launch_time":"2026-11-22 16:20:55 +0800",
 "system_version":"15","system_api_level":"35","bundle_version":"1.567.0",
 "crashhunter_version":"3.12.4","unisdk_version":"V5.18.0",
 "model":"23117RK66C","brand":"Redmi","mfr":"Redmi","board":"23117RK66C",
 "cpu_abi":"arm64-v8a","cpu_abi2":"x86_64","arch_type":64,
 "rom_name":"MIUI_15_V417IR release-keys",
 "is_rooted":"false","hardware":" placeholder","cpu":"Redmi","is_emulator":"true",
 "package_fingerprint":"75:5B:8C:35:70:8E:00:84:B6:8D:85:47:41:89:BF:09:F3:A1:7A:96",
 "gl_renderer":"Adreno (TM) 640","gl_vendor":"Qualcomm","gl_version":"OpenGL ES 3.2 v334 R",
 "screen_width":"960","screen_height":"540","ori":"LANDSCAPE",
 "battery_level_info":{"0":"99.00%","1800":"84.00%","3600":"71.00%"},
 "battery_temperature_info":{"0":"36.0","1800":"36.0","3600":"36.0"},
 "unisdk_device_id":"2b8837c8aca36189","imei":"","local_ip":"10.0.2.15",
 "sys_mem":"3932MB","total_size":"1645.568MB","avl_size":"0.0MB"}
```

六个可直接用的结论：

1. **`is_emulator = "true"` 是已发生的事实**，不是"预计会被判"。
2. **`is_rooted = "false"`**：没有 su 文件就够了，adb root 不暴露。这条把我上一版的误判彻底翻过来了。
3. **`hardware = " placeholder"`**（字面量，带前导空格）：全 props 里搜不到 `placeholder`，说明这是 **MuMu 的 spoof 层写死的值**。它比 `/proc/cpuinfo` 更露，而且**改 props 治不了**。
4. **`cpu = "Redmi"`**：该字段应是平台名（`kona`/`sm8550`），MuMu 把品牌塞进去了。第二条 spoof 泄漏。
5. **`local_ip = "10.0.2.15"`**：QEMU/VirtualBox NAT 的默认地址，真机不会是这个。第三条。
6. **`gl_renderer = Adreno (TM) 640` vs `model = 23117RK66C`（K70 Pro 应为 Adreno 750）**：MuMu 的 `gpu_model.custom` 与机型不配套。第四条。
7. **`battery_level_info` 30 min 掉 15%（99→84→71）**、温度恒定 36.0：行为侧也能看出来。

### 3.2 这份文件同时是**反检测的验收通道**

改任何设置 → 重启实例 → 等一次 refresh（或直接看 `crashhunter_pre.di`，启动即写）→ 重读 JSON，就能看到**游戏视角的自己**。不需要 hook、不需要 frida、不进游戏进程。这比第 7 节列的三种"高检测面验证"便宜一个量级。

### 3.3 `_ntcfg_.data`（105 字节）里有一把疑似密钥

```
01 000000 20 000000  "387924e229e47568b8a64c9c3f8c9743"      ← 32 hex，像 md5
                      "O" 000000 03 000000 "g18"              ← JF_GAMEID
                      20 000000 "NsUf4AGAMWAY4ZabxM4ekxXc5J9iTNV4"   ← 32 字符，像 AES-256 key
                      0a 000000 "libGame.so"
```

`_ntcfgss.dat`：8 764 560 字节，整体熵 6.33、可打印率 0.386，头 `3534295b61626400 2c30335427d7b9b2…`。
**假设**：这是 Messiah 的脚本/配置包，用上面那把 32 字符 key 加密或校验；解开就能拿到脚本层，`EmulatorDetectResult` 的读取方大概率在里面。
这是本项目里唯一能"绕过 Houdini 拿逻辑"的正当入口（内存读不通，脚本包可离机解）。

---

## 4. 之后的优先级（按 ROI 排）

### 4.1 `unisdk_device_id` 已定位到本地文件 —— 直接决定多开是否被关联

`unisdk_device_id = 2b8837c8aca36189`，它不是算出来的随机值，而是**落盘的**：

```
/data/data/com.netease.my/app_uf_data/device_id.info      2b8837c8aca36189          ← 就是它
/data/data/com.netease.my/app_uf_data/install_id.info     {"install_id":"8a1b40b306946e70033709f712d1caa7"}
/data/data/com.netease.my/app_uf_data/eb.info             {"eb":false}             ← Flagclass.EB 的来源，false→上报走 netease 域名
/data/data/com.netease.my/app_uf_data/data_id.info        1795334773232（ms 时间戳）
/data/data/com.netease.my/app_uf_data/ralc.info           {"disable_rollback":false}
/data/data/com.netease.my/app_uf/reported                 {"current_device_id":"2b8837c8aca36189", ...}
/data/data/com.netease.my/files/uniTrace/crashhunter/crashhunter.param
        {"transid":"2b8837c8aca36189_1795335655583_779183027","uid":"359094790",
         "username":"梦中做运动丶","server_name":"一区-再…"}
```

三条确定的推论：

1. **`transid` 前缀就是它** → 服务端每一笔带 `transid` 的请求都带这个设备号，**账号关联靠它，不靠在线曲线**。
2. **克隆虚拟机 = 复制 `device_id.info` = 两个实例同号**。`MuMuManager clone` 拷的是整个 data 分区，所以克隆出来的实例在服务端是**同一台设备**。
3. `eb.info = {"eb":false}` 反向验证了第 8.3 节：`Flagclass.EB` 为 false → `getSuitableUrl()` 不切到 `easebar`，上报打 `xyq-service.netease.com`。

**验证/落地步骤（30 min，需你同意，因为改设备号等于"新设备登录"）**

```bash
# 0) 备份（可回滚）
adb -s 127.0.0.1:16384 shell 'cp -r /data/data/com.netease.my/app_uf_data /data/local/tmp/uf_bak'
# 1) 改 android_id / mac / imei（MuMuManager 侧）
MuMuManager simulation -v 0 -sk android_id -sv <新16位hex>
# 2) 删掉持久化设备号，让 SDK 重新生成
adb -s 127.0.0.1:16384 shell 'rm /data/data/com.netease.my/app_uf_data/device_id.info'
# 3) 重启应用，读游戏视角的判定
MuMuManager control -v 0 app close -p com.netease.my
MuMuManager control -v 0 app launch -p com.netease.my
adb -s 127.0.0.1:16384 shell 'cat /data/data/com.netease.my/app_uf_data/device_id.info'
adb -s 127.0.0.1:16384 shell 'cat /data/data/com.netease.my/files/uniTrace/crashhunter/crashhunter_pre.di | head -c 400'
```

- 若 `device_id.info` 被重新生成为新值 → 多开只需在**实例首次启动前**清掉它，即可保证每实例独立设备号
- 若它被服务端下发覆盖回原值（或登录要验证码）→ 说明设备号绑定账号，克隆路线必须放弃，只能"一号一实例、实例不复用"

**风险提示**：设备号变化会被判为"换设备登录"，极可能触发短信/人脸验证，甚至风控观察期。请在**离号/小号实例**上做这个实验，别拿主号。

### 4.2 解 `_ntcfgss.dat`（脚本层唯一入口）

用 3.3 那把 key 试 AES-256-ECB/CBC / 或先看是否 zlib（头不是 `78 9c`，熵 6.33 不像纯压缩）。成功则能拿到 `EmulatorDetectResult` 的读取逻辑与挂机相关的脚本状态机。

### 4.3 NDK 探针（把内存路线钉死，20 行）

`process_vm_readv` 对 Houdini 客户机段是否也 EIO。若同样 EIO，第 3 节结论封口，中控永远走视觉。

### 4.4 `libunisec` 的 tcp 函数（0x73370–0x734cc）

对方已定位 `lea rsi,[rip+0x7cbca]` @`0x7339f`。它比较的 4 字节不是明文；静态到此为止，要动态 hook 读比较值才知道查什么端口/进程。**优先级低于 4.1/4.2**，因为客户端标记已确认跑不出变化。

---

## 5. 中控台的最终修正（相对第 6 节）

| 项 | 第 6 节原说法 | 修正后 |
|---|---|---|
| 模拟器标签 | 想办法绕 | **接受**。`is_emulator` 由 `V417IR` + `abi=x86` + `cpuinfo=intel` 三条独立命中，改 props 无效；`hardware=" placeholder"` 还写着 MuMu 的痕迹 |
| root | 「KernelSU 已授权，注意隐藏」 | **保持无 su 文件**。`is_rooted=false` 已成立，别装 su、别放 `android_server` |
| 输入 | adb input 会被认 → 用宿主注入 | 宿主注入仍首选（**理由：性能/稳定性**）；adb input 仍可作为低频兜底 |
| 内存 | 转译层读不到 → 放弃 | 不变，但补一句：`process_vm_readv` 未测，用 4.3 收尾 |
| 多开 | 独立实例即可 | **加一条硬门槛**：每实例 `unisdk_device_id` 必须不同（4.1 验证） |
| 验收 | 靠 frida hook 读结果 | **改为读 `crashhunter.di`**：零检测面、30 min 自动刷新、启动即写一份 |
| 分支依据 | 想读 `EmulatorDetectResult` | 不读（对方第 9.5 节第 4 条正确）；要看就用 `.di` 的 `is_emulator` / `is_rooted` |

---

## 6. 一句话总结

对方第 8–9 节把"字符串当行为"这个系统性错误挑出来了，是对的；我复核后**撤回 6 条**。
但两边都没有的那份 `crashhunter.di` 才是这轮最值钱的东西：它证明 `is_emulator=true, is_rooted=false`，还暴露 `hardware=" placeholder"`、`local_ip=10.0.2.15`、`Adreno 640 vs 23117RK66C`、30 分钟掉 15% 电量这四条 MuMu 特有痕迹，同时提供了一个零成本验收通道。
下一步只做两件：**4.1 的 device_id 实验**（决定多开是否安全）和 **4.2 的脚本包解密**（决定能不能拿到脚本层）。
