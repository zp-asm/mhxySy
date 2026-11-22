# 工具矩阵 / 缺口清单（含官方下载地址）

本机实测环境：Windows + MuMu Player NX 15.0（`MuMuManager 6.8.8.0`）+ KernelSU（VM 内已 root）
工作目录：`E:\gamework\mhxyMobile`

---

## 1. 已装、且本次实际用上的

| 工具 | 版本 / 路径 | 本次用途 | 结论 |
|---|---|---|---|
| **IDA Pro + MCP** | `D:\develop\idapro93\ida.exe`，MCP server `ida`（`mcp__ida__*`） | 打开 `libntunisdk.so` / `libybuaxz.so`，做导出表与导入面取证 | ✅ 主用。`libybuaxz.so` 是加壳/导出表混淆，深逆需配合动态 |
| **jadx** | 1.5.6，`D:\develop\tools\jadx\bin\jadx.bat` | 反编译 9 个 dex（10879 类，113 处失败）到 `analysis\jadx` | ✅ 够用，`Sdkybuaxwny` / `Flagclass` 就是它出的 |
| **apktool** | `D:\develop\tools\apktool\apktool.bat` | 尚未用（manifest 还没解，见 §3 待办） | ⏸ 备用 |
| **adb** | `D:\develop\tools\android\platform-tools\adb.exe` | 设备枚举、抓帧、root shell 取证、mem 读测试 | ✅ 主用 |
| **frida CLI** | 17.26.3，`D:\develop\tools\pyenv\Scripts\frida.exe`；frida-python 同版本 | 尚未连设备（无可用的 frida-server） | ⏸ 待装 server |
| **scrcpy** | 5.0.1，`D:\develop\tools\scrcpy\scrcpy.exe` | 已验证可执行；中控台主视频通道 | ✅ 主用 |
| **Python** | 3.12，`D:\develop\py312\python.exe`（numpy 2.5.3 / opencv 5.1.0 / pyelftools 已装） | 所有脚本、ELF triage、视觉 | ✅ 主用 |
| **JDK** | 1.8 + 21（`D:\develop\jdk-21`） | jadx / ghidra 运行时 | ✅ |
| **Node / git** | 已装 | 备用 | ⏸ |
| **MuMuManager** | `F:\mumu\MuMuPlayer\nx_main\MuMuManager.exe` | 多实例生命周期、差异化指纹、adb/sh 封装 | ✅ **中控台核心 API** |
| **KernelSU** | VM 内已装，`adb shell` 直接 `uid=0 context=u:r:su:s0` | 只读取证 | ✅ |

---

## 2. 缺的（按优先级）

### P0 — 不装就推进不了

| 工具 | 用途 | 下载地址 | 备注 |
|---|---|---|---|
| **dxcam**（或 mss） | 宿主窗口抓帧（比 `adb screencap` 快 10–30×） | `pip install dxcam` / `pip install mss`（https://github.com/ra1nty/DXcam） | 实测 `screencap` **470–800 ms/帧**，多开跑不动；dxcam 抓 `render_wnd` 可到 60 fps |
| **pywin32** | 向 MuMu 窗口 (`render_wnd`) 注入鼠标事件，走 `nemuinput` → 真实 uinput 触摸（游戏侧看到的是 `Xiaomi Touchscreen` deviceId=3，和真人一致） | `pip install pywin32`（https://github.com/mhammond/pywin32） | 比 `adb shell input tap` 干净：后者是 InputManager 注入，`deviceId/source` 可被判 |
| **adbutils** | 稳定的 adb 封装（多实例并发、端口重连） | `pip install adbutils`（https://github.com/openatx/adbutils） | 现在的 `subprocess` 版每帧多 ~300 ms 进程开销 |
| **RapidOCR** | 识别游戏内文字（任务文本、血量、聊天、NPC 名） | `pip install rapidocr-onnxruntime`（https://github.com/RapidAI/RapidOCR） | 比 tesseract 准，纯 onnx 无需 GPU |

### P1 — 动态分析 / 验证检测结论

| 工具 | 用途 | 下载地址 | 备注 |
|---|---|---|---|
| **frida-server (android-x86_64)** | 在 VM 内 hook `Java_com_netease_ybuax_Flagclass_Startybuax` 读判定结果；hook `libunisec_x86_64.so` 找检测点 | https://github.com/frida/frida/releases → `frida-server-17.26.3-android-x86_64.xz`（必须与客户端 17.26.3 对齐） | ⚠️ 高检测面：`libsecsdk`/`libunisec` 有 `dl_iterate_phdr` 模块枚举，`libsec-lib` 有 `frida` 家族扫描位。只在离号镜像上做，做完回滚快照 |
| **objection** | frida 的免脚本封装（`android root disable`、SSL unpinning、`memory search`） | `pip install objection`（https://github.com/sensepost/objection） | 快速验证用 |
| **Android NDK r27** | 编 20 行 `process_vm_readv` 探针，把"客户机段不可读"钉死；也可编注入 loader | https://developer.android.com/ndk/downloads | 仅验证用，别用来写外挂 |
| **Ghidra 11.x** | 你提到有，实际**本机没装**（`D:\develop` 下无 ghidra，`ghidraRun` 不在 PATH）。要装需 JDK21（已有） | https://github.com/NationalSecurityAgency/ghidra/releases | IDA 9.3 已覆盖大部分需求；Ghidra 的优势是 `libunisec` 这种混淆体用脚本批量去花指令更顺手 |
| **LIEF** | so 结构改写 / 段分析（比 pyelftools 强） | `pip install lief`（https://github.com/lief-project/LIEF） | |
| **Androguard** | dex 级交叉引用（jadx 反编译失败的那 113 个类可用它兜） | `pip install androguard`（https://github.com/androguard/androguard） | |

### P2 — 只在特定路线才需要

| 工具 | 用途 | 下载地址 |
|---|---|---|
| **mitmproxy** | 协议层时序/包长分析（`libnep`/`libclienc` 加密，只能看元数据） | https://mitmproxy.org/downloads/ |
| **unluac / luadec** | 若后续能 dump 出 Lua 字节码，反编译脚本逻辑 | https://sourceforge.net/projects/unluac/ ；https://github.com/viruscamp/luadec |
| **minicap / minitouch** | 老方案（Android 5–10 时代），Android 15 上兼容差 | https://github.com/openstf/minicap |
| **uiautomator2** | 走 Accessibility 树做控件级定位 | `pip install uiautomator2`（https://github.com/openatx/uiautomator2）|

### 明确"不需要"的（避免浪费时间）

- **Cheat Engine / GG修改器 / 任何 `/proc/pid/mem` 扫描器** → Houdini 客户机段读 `EIO`（见 REPORT §3.1），对本作无效
- **Il2CppDumper / Frida-il2cpp-bridge** → 不是 Unity，是 Messiah + Lua
- **LSPosed / Zygisk / 双开插件** → `libsec-lib` 的 `ProcMapsHasXposed`、`SameUidPackage`、分身包黑名单直接命中
- **改包/重签 / 内购破解** → `uploadapk` 会把 APK 摘要送服务端比对

---

## 3. 装完后的验证顺序（按这个顺序做，别跳）

1. `pip install dxcam pywin32 adbutils rapidocr-onnxruntime` → 跑 `mhxy_console` 的 `shot`/`match`，确认命中率与帧率
2. `python -m mhxy_console.main isolate --indexes 0` → 验证 MuMuManager `simulation` 生效（改完重启实例，`getprop`/`settings get secure android_id` 应变化）
3. `python -m mhxy_console.main list` → `control launch` 建 2–4 实例，测单机承载（i5-10400，建议 ≤4）
4. 需要动态验证时再上 `frida-server`（**先给实例做快照**）

---

## 4. 本次会话产出的文件

```
E:\gamework\mhxyMobile\
├─ REPORT.md                     # 检测面分析报告（含证据偏移）
├─ TOOLS.md                      # 本文件
├─ artifacts\                    # 取证副本
│  ├─ base.apk (1.95 GB)         # 游戏包
│  ├─ dex\classes*.dex (9 个)     # Java 侧
│  ├─ dex\ntp_classes.dex        # 热更新插件 dex (8.7 MB)
│  ├─ lib\arm64-v8a\*.so         # 12 个关键 so + libGame.so (78 MB)
│  ├─ lib\libunisec_x86_64.so    # 运行时下载的模拟器专用反外挂模块
│  ├─ ntunisdk_so_uuids          # 全模块 MD5 表（完整性校验证据）
│  └─ wnyklrieFile               # 5790 字节，一行 base64 字母表文本；解码后的结构未分析
├─ analysis\
│  ├─ strings\*.strings.txt      # 每个 so 的字符串全量（含偏移）
│  ├─ strings_dex\*.txt          # 每个 dex 的字符串
│  ├─ jadx\sources\...           # 反编译 Java 源码
│  ├─ elf_triage.json            # 12 个 so 的导入/能力矩阵
│  ├─ device_probe.txt           # 设备指纹/传感器/日志取证
│  └─ ntp0_probe.txt             # 下载模块目录取证
├─ frames\                       # 抓帧样本 + e2e 验证帧
├─ templates\task.png            # 已验证的模板（命中 0.99）
├─ mhxy_console\                 # 中控台骨架（可用）
│  ├─ mumu.py                    # MuMuManager 封装：实例/启停/差异化指纹
│  ├─ adb.py                     # 输入注入 + 抓帧 + 只读内存
│  ├─ vision.py                  # 模板匹配 + OCR 挂载点
│  ├─ worker.py                  # 单实例循环 + 人类化节流
│  └─ main.py                    # CLI: list/shot/crop/match/run/isolate/app
└─ tools\                        # 取证脚本
   ├─ extract_strings.py
   ├─ elf_triage.py
   ├─ show_triage.py
   ├─ probe_device.sh / probe_ntp0.sh / probe_mem.sh / probe_guest.sh / probe_input.sh
   └─ e2e_check.py               # 端到端：抓帧→匹配→点击→回验
```
