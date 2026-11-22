# 协议层侦查报告（2026-11-22 实测）

> 目标：判断"用协议当传感器"（读任务/角色状态，替代 OCR）是否可行、成本多少。
> 结论先说：**可行，但要把 `libtcb.so` 这层逆向下来（1–2 天起步），不是当天能出活的路线。**

---

## 1. 抓包结果（guest 内 tcpdump，root）

```bash
adb -s 127.0.0.1:16384 root
adb shell "setsid tcpdump -i any -s 0 -w /data/local/tmp/cap.pcap </dev/null >/dev/null 2>&1 &"
adb pull /data/local/tmp/cap.pcap
```

pcap：**1.9 MB / 2071 包 / 10 条流**，linktype=276（Linux SLL2，注意解析偏移 20 字节）。

| 流 | 包数 | 载荷 | 判断 |
|---|---|---|---|
| `42.186.128.28:10002` ↔ `:37080` | 106 / 12 | 下行 14,203 B，上行 135 B | **游戏本体**，全密文 |
| `117.147.201.71:443` | 10 / 10 | 3 KB | SDK 登录，标准 **TLS 1.2** |
| `42.186.76.79:10609` | 35 / 35 | 342 / 162 B | 另一服务（网关/心跳） |

游戏流重组后**首字节即密文**（无明文长度头、无明文 opcode）：

```
7caf206e25dec1dc99bf4e317edef55c309014f7332f4b04b69093254202fd73…
```

上行只有 135 B / 106 包 → 客户端**极少发指令**（挂机场景天然如此），主要吃下行推送。

---

## 2. 静态侧：库清单

`/data/app/.../lib/arm64/`（APK 内，63 个）：`libGame.so`(78 MB)、`libnep.so`、`libsecsdk.so`、`libunisec.so`、`libybuaxz.so`、`libpharos.so`、`libcsimpletcp.so`…

进程运行时额外加载：
- `/data/user/0/com.netease.my/app_ntp0/1.567.0_15670/libclienc.so`
  → **内存模块**：文件已删，只有 `[anon:…]` 映射，**仅 8 KB r-xp**（反 dump）
- `/data/data/com.netease.my/app_ntp0/1.567.0_15670/libunisec_x86_64.so`（热更新下发）
- `/system/lib64/libtcb.so`（**ARM，Houdini 转译**，1379 KB，**导出仅 2 个符号、0 条可读字符串**）
- `/system/lib64/libprotobuf-cpp-lite.so` / `-full.so`

---

## 3. 动态侧：Frida 做了什么

环境：宿主 `frida 17.27.4` + 设备 `frida-server`（android-x86_64），`adb root` 后 attach 主进程（Frida 里显示为"梦幻西游"，pid 可通过 `pidof com.netease.my` 取）。

| Hook | 结果 |
|---|---|
| `EVP_DecryptUpdate` / `EVP_EncryptUpdate`（libcrypto） | **20 s 内 0 次调用** → 协议加密**不走 OpenSSL** |
| `recv` / `read`（libc） | 收包调用者全是 **`libtcb.so+0xa24f0`**；能看到 `02 00 00 6c 03 03 …`（长度前缀 + TLS 记录）与 `PING 42.186.128.28` 心跳 |
| `MessageLite::ParseFromArray`（libprotobuf-cpp-lite） | **30 s 内 0 次调用** → 网络热路径**不是** protobuf 解析（protobuf 用于配置/资源） |

工具已入库：`tools/frida_probe.py`（pid / modules / crypto / recv 四个子命令）。

---

## 4. 为什么必须啃 `libtcb.so`

- 收包全在它里面（`recv` 的唯一调用者）
- 它同时管 TLS（SDK）和游戏自定义帧（10002）
- 已剥符号、无字符串、ARM 代码（Houdini 转译）→ 只能 IDA 动态+静态结合

### 下一步（可执行）

1. `IDA` 打开 `libtcb.so`（ARM64），从 `recv` 的调用点 `+0xa24f0` 往上找帧解析函数
2. 找 `AES` 特征：S-box（`0x63,0x7c,0x77,0x7b…`）或 T-table（1024 B ×4），定位 cipher 初始化
3. 在初始化处 dump **key/iv**（session 级），然后离线解 10002 的密文验证
4. 解出来后做 **字段映射**（opcode → 任务/角色/坐标），再接进 `workers.MonitorWorker`

### 成本

| 步骤 | 估时 |
|---|---|
| 定位解密入口 + dump key | 1–2 天 |
| 离线解密验证 pcap | 0.5 天 |
| 帧格式 / 字段映射 | 2–3 天 |
| 版本更新维护 | 每次大版本 0.5 天 |

---

## 5. 建议

- **短期**：图色继续跑（今天实测 3 级 → 14 级，主线推进正常），不阻塞收益
- **中期**：协议作为并行研究，只做**只读传感器**（不改上行、不发包），目标是把 `MonitorWorker` 的 HP/MP/等级和任务状态从"看图"换成"读包"
- **不要做**：完整协议驱动（自己构造上行指令）——握手/序列号/反重放 + `libsecsdk` 监控，风险与成本都不划算
