# 后台能力实测（MuMu NX 15 / 实例 0 / 960x580 窗口）

> 三个问题：能不能后台截图、能不能后台按键、能不能后台点击。
> 全部结论来自本机实测，命令可复现。

---

## 1. 后台截图 —— ✅ 能（唯一限制：不能最小化）

窗口：`MuMuNxDevice.exe` 下的实例窗口 `MuMu安卓设备`，客户区 **960×580**（上方 40 px 是 MuMu 自绘标题栏，下面 960×540 才是游戏画面）。

| 窗口状态 | BitBlt | PrintWindow(PW_RENDERFULLCONTENT) |
|---|---|---|
| 正常可见 | ✅ nonblack 100% / std 77.6 | ✅ 同左 |
| **被另一个 topmost 窗口完全遮住** | ✅ **nonblack 100% / std 77.6** | ✅ 同左 |
| 最小化 (SW_MINIMIZE) | ❌ nonblack 0.8% | ❌ nonblack 0.7% |
| 恢复后 | ✅ | ✅ |

**耗时**：BitBlt **4.1 ms**，PrintWindow **18.7 ms**（对比 `adb exec-out screencap` 392 ms，快 95 倍）。

复现：

```powershell
python tools\probe_bg_capture.py        # 三态矩阵
python -m mhxy_console.win <MuMuNxDevice_pid>   # 10 帧耗时
```

**工程结论**
- 多开时窗口**可以互相重叠**，不需要摆开、不需要置顶 → 这是多开能跑的前提。
- **不能最小化**（渲染停止）。要"隐藏"就用 `MuMuManager control -v N hide_window`（隐藏 ≠ 最小化，需单独验证）或把窗口移到屏幕外的负坐标。
- 窗口选择必须**按内容验证**，不能按面积：同一 pid 下 1424×720 的宿主窗口是全黑的，960×580 的实例窗口才有画面。

---

## 2. 后台键盘 —— ✅ 能（PostMessage 直接进 guest）

方法：`PostMessageW(hwnd, WM_KEYDOWN/WM_KEYUP, vk, lParam)`，同时在 guest 内 `getevent -lt` 抓 evdev。

实测（1323 行日志里筛 EV_ 行，按相位计数）：

```
p0_idle        0
p1_postmsg     4     ← KEY_A DOWN / SYN / KEY_A UP / SYN   （/dev/input/event5 Xiaomi Keyboard）
p2_adb         0     ← adb input keyevent 不进 evdev（走 InputManager，见下）
p3_postmsg2   10     ← KEY_ENTER / KEY_ESC 同样到达
```

**结论**：`PostMessage` 的 `WM_KEYDOWN/WM_KEYUP` 会被 MuMu 送进 Android 的键盘设备 `/dev/input/event5`，**不需要窗口有焦点、不需要抢前台**。延迟在毫秒级。

注意：`adb shell input` 系列**不会**出现在 evdev 里（它注入在 InputManager 之上），所以不能拿 getevent 判断 adb 是否生效——这是本次测量踩到的坑。

---

## 3. 后台鼠标/触摸 —— ❌ PostMessage 不行

同一相位里 PostMessage 发了 `WM_MOUSEMOVE ×6 + WM_LBUTTONDOWN/UP`，guest 侧 **0 个**鼠标/触摸事件（event4 Xiaomi Touchscreen、event6 Xiaomi Mouse 都没动静），只有同批次的键盘事件到达。

原因：MuMu 的鼠标走**真实光标位置/原始输入**，合成消息改不了它。

**可用的替代通道**（都与会话焦点无关）：

| 通道 | 实测耗时 | 说明 |
|---|---|---|
| `adb shell input tap x y` | **74 ms**（PowerShell 里连进程开销是 195 ms） | 直接注入 InputManager，与焦点无关，最稳 |
| scrcpy 控制通道 | 待测（预期 <10 ms） | 走 H.264 流 + 控制 socket，需起 scrcpy |
| `MuMuManager` 无输入接口 | — | `control/setting/simulation` 里没有点击能力 |

---

## 4. 对中控架构的直接影响

| 动作 | 通道 | 单次成本 | 是否需要前台 |
|---|---|---|---|
| 看画面 | GDI BitBlt（被遮挡可用） | 4.1 ms | ❌ |
| 按技能/快捷键 | `PostMessage WM_KEYDOWN/UP` | <1 ms | ❌ |
| 点地面/点 NPC/拖动 | `adb shell input tap/swipe` | 74 ms | ❌ |
| 输入文字 | `adb shell input text` | ~80 ms | ❌ |

单实例一轮「看→判→按键」≈ 5–10 ms；只有需要点击时才付 74 ms。10 实例并发时，点击走线程池排队即可（每实例每秒最多几次点击）。

---

## 5. 尚未验证（别当结论）

1. `MuMuManager control hide_window` 隐藏后是否仍能 BitBlt（隐藏≠最小化，可能同样停渲染）。
2. 窗口移到屏幕外（负坐标）时 DWM 是否仍保留表面。
3. scrcpy 控制通道在 MuMu 上的实际延迟（预期最低）。
4. 键盘事件到达的是 Android 输入层；**游戏是否接受**（例如 'A' 在梦幻里有无绑定）未逐键验证。
