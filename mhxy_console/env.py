"""环境体检（Windows 侧 + MuMu 侧）—— 输出"必须改 / 建议改 / 脚本自动吸收"三类。

判据来自我们自己的实测：
  · 抓帧走 GDI 窗口位图 → 系统 DPI / 显示器缩放 / HDR 对像素影响有限，但高对比度主题、
    色彩增强类设置会整体改配色，模板会失配，必须关。
  · 窗口不能最小化（实测黑帧），可以重叠。
  · MuMu 的分辨率/DPI/帧率/渲染后端必须固定，否则同一模板在不同实例上分数漂移。

用法：
  python -m mhxy_console.env                 # 体检
  python -m mhxy_console.env --save-profile  # 存成 profile（跨机器比对用）
"""
from __future__ import annotations

import ctypes
import json
import subprocess
import sys
from ctypes import wintypes as wt
from pathlib import Path

user32 = ctypes.WinDLL("user32", use_last_error=True)
user32.SystemParametersInfoW.argtypes = [wt.UINT, wt.UINT, ctypes.c_void_p, wt.UINT]
user32.SystemParametersInfoW.restype = wt.BOOL
user32.GetSystemMetrics.argtypes = [ctypes.c_int]
user32.GetSystemMetrics.restype = ctypes.c_int

SPI_GETMOUSE = 0x0003
SPI_GETSCREENSAVEACTIVE = 0x0010
SPI_GETHIGHCONTRAST = 0x0042
HCF_HIGHCONTRASTON = 0x1
MUMU_MANAGER = r"F:\mumu\MuMuPlayer\nx_main\MuMuManager.exe"


class HIGHCONTRASTW(ctypes.Structure):
    _fields_ = [("cbSize", wt.DWORD), ("dwFlags", wt.DWORD), ("lpszDefaultScheme", wt.LPWSTR)]


# ------------------------------------------------------------------ 采集
def dpi() -> tuple[float, bool]:
    scale, aware = 1.0, False
    try:
        a = ctypes.c_int(-1)
        ctypes.WinDLL("shcore").GetProcessDpiAwareness(None, ctypes.byref(a))
        aware = a.value in (1, 2)
    except Exception:
        pass
    try:
        gdi32 = ctypes.WinDLL("gdi32")
        gdi32.GetDeviceCaps.argtypes = [wt.HDC, ctypes.c_int]
        gdi32.GetDeviceCaps.restype = ctypes.c_int
        dc = user32.GetDC(0)
        scale = round(gdi32.GetDeviceCaps(dc, 88) / 96.0, 3)
        user32.ReleaseDC(0, dc)
    except Exception:
        pass
    return scale, aware


def gpus() -> list[tuple[str, str]]:
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-Command",
                            "Get-CimInstance Win32_VideoController | "
                            "ForEach-Object { \"$($_.Name)|$($_.Status)\" }"],
                           capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=20)
        out = []
        for ln in r.stdout.splitlines():
            ln = ln.strip()
            if "|" in ln:
                name, _, st = ln.rpartition("|")
                out.append((name.strip(), st.strip()))
        return out
    except Exception:
        return []


def reg(hive, path: str, name: str):
    try:
        import winreg
        with winreg.OpenKey(hive, path) as k:
            return winreg.QueryValueEx(k, name)[0]
    except Exception:
        return None


def night_light_on() -> bool | None:
    v = reg(__import__("winreg").HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\CloudStore\Store\DefaultAccount"
            r"\default$windows.data.bluelightreduction.bluelightreductionstate"
            r"\windows.data.bluelightreduction.bluelightreductionstate", "Data")
    return None if v is None else True


def hdr_flag():
    return reg(__import__("winreg").HKEY_LOCAL_MACHINE,
               r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\VideoSettings",
               "EnableHDRForPlayback")


def mouse_accel() -> tuple[bool, tuple[int, int, int]]:
    arr = (ctypes.c_int * 3)()
    if not user32.SystemParametersInfoW(SPI_GETMOUSE, 0, ctypes.byref(arr), 0):
        return False, (0, 0, 0)
    return arr[2] != 0, (arr[0], arr[1], arr[2])


def high_contrast() -> bool | None:
    hc = HIGHCONTRASTW()
    hc.cbSize = ctypes.sizeof(HIGHCONTRASTW)
    if not user32.SystemParametersInfoW(SPI_GETHIGHCONTRAST, hc.cbSize, ctypes.byref(hc), 0):
        return None
    return bool(hc.dwFlags & HCF_HIGHCONTRASTON)


def screensaver() -> bool | None:
    v = ctypes.c_int()
    if not user32.SystemParametersInfoW(SPI_GETSCREENSAVEACTIVE, 0, ctypes.byref(v), 0):
        return None
    return bool(v.value)


def power_timeout(sub: str, setting: str) -> int | None:
    try:
        r = subprocess.run(["powercfg", "/q", "SCHEME_CURRENT", sub, setting],
                           capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=15)
        for tok in r.stdout.split():
            if tok.lower().startswith("0x00"):
                return int(tok, 16)
    except Exception:
        pass
    return None


def ime_layout() -> str:
    v = reg(__import__("winreg").HKEY_CURRENT_USER, r"Keyboard Layout\Preload", "1")
    return str(v) if v else "?"


# ------------------------------------------------------------------ MuMu
def mumu_info() -> dict:
    try:
        r = subprocess.run([MUMU_MANAGER, "info", "-v", "all"],
                           capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30)
        return json.loads(r.stdout)
    except Exception as e:
        return {"error": str(e)}


def mumu_settings(index: str = "0") -> dict:
    try:
        r = subprocess.run([MUMU_MANAGER, "setting", "--vmindex", index, "--all_writable"],
                           capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30)
        return json.loads(r.stdout)
    except Exception as e:
        return {"error": str(e)}


# ------------------------------------------------------------------ 判定
STABILITY_KEYS = [
    # (key, 期望值, 说明)
    ("resolution_mode", None, "分辨率模式固定即可"),
    ("resolution_width.custom", "960.000000", "视口宽度（基准 960）"),
    ("resolution_height.custom", "540.000000", "视口高度（基准 540）"),
    ("resolution_dpi.custom", "220.000000", "DPI（UI 尺寸随它变）"),
    ("max_frame_rate", "60", "固定帧率，关掉动态帧率"),
    ("dynamic_adjust_frame_rate", "false", "动态帧率会让画面细节漂移"),
    ("renderer_mode", None, "渲染后端必须固定（vk/dx 不要 auto）"),
    ("gpu_mode", None, "GPU 档位固定"),
    ("system_disk_readonly", None, "只读系统盘（防误改）"),
]


def main(argv: list[str]) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    scale, aware = dpi()
    must: list[str] = []
    rec: list[str] = []
    absorbed: list[str] = []

    if high_contrast():
        must.append("高对比度主题开着 → 设置→辅助功能→对比度主题→无（整体改配色，模板必废）")
    accel, raw = mouse_accel()
    if accel:
        must.append(f"鼠标加速开着 {raw} → 设置→鼠标→其他鼠标选项→指针选项→取消『提高指针精确度』")
    if screensaver():
        must.append("屏保已启用 → 设置→个性化→锁屏界面→屏幕保护程序→无")
    st = power_timeout("SUB_SLEEP", "STANDBYIDLE")
    if st:
        must.append(f"睡眠超时 {st}s → 设为『从不』")
    mo = power_timeout("SUB_VIDEO", "VIDEOIDLE")
    if mo:
        must.append(f"关闭显示器超时 {mo}s → 设为『从不』（关屏后抓帧会黑）")
    layout = ime_layout()
    if layout.startswith(("00000804", "e0200804")):
        must.append(f"默认输入法是中文拼音({layout}) → 加装美式键盘并设为默认（否则 input text 会串）")

    if hdr_flag():
        rec.append("HDR 播放标记开着 → 建议关（灰度匹配能扛，但会让 UI 亮度整体漂移）")
    if night_light_on():
        rec.append("夜间模式(护眼)可能开着 → 建议关（整体偏黄，长时间挂机还可能自动开启）")
    for name, status in gpus():
        low = name.lower()
        if any(k in low for k in ("virtual", "mumu", "basic display", "remote")):
            must.append(f"『{name}』({status}) 是虚拟显示适配器：**先别动**。"
                        "它是 MuMu 的渲染出口，禁用会导致模拟器黑屏；"
                        "只在确认真实显示器也能正常出画面后再考虑禁")
        elif any(k in low for k in ("nvidia", "amd", "radeon", "intel")):
            absorbed.append(f"显卡『{name}』：色彩增强/锐化/数字振动一律不用动（我们用灰度+掩码匹配）")
    if abs(scale - 1.0) > 0.01:
        absorbed.append(f"系统缩放 {scale:.0%}：不用改（抓的是窗口位图，坐标按视口归一化）")
    absorbed.append("系统版本/驱动版本：不用改（差异由视口标定 + 多尺度吸收）")

    print("=" * 78)
    print(f"Windows: {sys.getwindowsversion().major}.{sys.getwindowsversion().minor}"
          f".{sys.getwindowsversion().build}   DPI={scale:.0%}  进程DPI感知={aware}")
    print("=" * 78)

    print("\n【必须改】不改会直接影响抓帧/点击")
    for i, m in enumerate(must, 1):
        print(f"  {i}. {m}")
    if not must:
        print("  ✅ 无")

    print("\n【建议改】影响稳定性/寿命，不改也能跑")
    for i, m in enumerate(rec, 1):
        print(f"  {i}. {m}")
    if not rec:
        print("  ✅ 无")

    print("\n【不需要改】脚本自动吸收")
    for m in absorbed:
        print("  ·", m)

    print("\n" + "=" * 78)
    print("MuMu 实例设置（决定模板是否跨机器通用）")
    print("=" * 78)
    info = mumu_info()
    sett = mumu_settings("0")
    if "error" in sett:
        print("  读不到 MuMu 设置:", sett["error"])
    else:
        for k, want, why in STABILITY_KEYS:
            cur = sett.get(k)
            if cur is None:
                continue
            flag = ""
            if want is not None and str(cur) != str(want):
                flag = f"  ← 期望 {want}"
            print(f"  {k:28s} = {str(cur):14s}{flag}   {why}")
        for k in ("phone_brand", "phone_model", "gpu_model.custom",
                  "performance_mode", "performance_cpu.custom", "performance_mem.custom"):
            if k in sett:
                print(f"  {k:28s} = {sett[k]}")

    prof = {
        "dpi_scale": scale, "dpi_aware": aware,
        "gpus": gpus(), "hdr": hdr_flag(), "mouse_accel": mouse_accel(),
        "high_contrast": high_contrast(), "screensaver": screensaver(),
        "sleep_timeout": st, "monitor_timeout": mo, "ime": layout,
        "mumu_settings": sett, "mumu_info": info,
    }
    if "--save-profile" in argv:
        p = Path("profile.json")
        p.write_text(json.dumps(prof, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\nprofile 已保存: {p.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
