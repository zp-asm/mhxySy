"""MuMuManager CLI 封装：多实例生命周期 + 差异化配置。

实测版本：MuMu Player NX 15.0（MuMuManager.exe 支持 info/control/simulation/setting/clone）
"""
from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

DEFAULT_MANAGER = Path(r"F:\mumu\MuMuPlayer\nx_main\MuMuManager.exe")


@dataclass
class Instance:
    index: int
    name: str
    adb_host: str
    adb_port: int
    android_version: str
    started: bool
    pid: int
    render_wnd: str | None

    @property
    def serial(self) -> str:
        return f"{self.adb_host}:{self.adb_port}"


class MuMuManager:
    def __init__(self, exe: str | Path | None = None, timeout: float = 60.0):
        exe = exe or DEFAULT_MANAGER
        # 允许 "MuMuManager" 在 PATH 里
        self.exe = str(exe)
        if not Path(self.exe).exists():
            found = shutil.which("MuMuManager")
            if not found:
                raise FileNotFoundError(f"MuMuManager 未找到: {exe}")
            self.exe = found
        self.timeout = timeout

    # ---------- 基础 ----------
    def _run(self, *args: str) -> subprocess.CompletedProcess:
        cmd = [self.exe, *args]
        return subprocess.run(
            cmd, capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=self.timeout,
        )

    def _json(self, *args: str) -> dict:
        cp = self._run(*args)
        out = (cp.stdout or "").strip()
        if not out:
            return {"errcode": cp.returncode, "errmsg": (cp.stderr or "").strip()}
        try:
            return json.loads(out)
        except json.JSONDecodeError:
            return {"errcode": -1, "errmsg": out}

    # ---------- 查询 ----------
    def version(self) -> dict:
        return self._json("version")

    def instances(self) -> list[Instance]:
        raw = self._json("info", "-v", "all")
        items: Iterable[dict]
        if isinstance(raw, dict) and all(k.isdigit() for k in raw.keys()):
            items = raw.values()
        elif isinstance(raw, dict):
            items = [raw]
        else:
            items = []
        out = []
        for it in items:
            try:
                out.append(Instance(
                    index=int(it.get("index", -1)),
                    name=it.get("name", ""),
                    adb_host=it.get("adb_host_ip", "127.0.0.1"),
                    adb_port=int(it.get("adb_port", 0)),
                    android_version=str(it.get("android_version", "")),
                    started=bool(it.get("is_android_started")),
                    pid=int(it.get("pid", 0)),
                    render_wnd=it.get("render_wnd"),
                ))
            except (TypeError, ValueError):
                continue
        return sorted(out, key=lambda i: i.index)

    def ensure_started(self, index: int) -> dict:
        return self._json("control", "--vmindex", str(index), "launch")

    def shutdown(self, index: int) -> dict:
        return self._json("control", "--vmindex", str(index), "shutdown")

    def restart(self, index: int) -> dict:
        return self._json("control", "--vmindex", str(index), "restart")

    def show_window(self, index: int) -> dict:
        return self._json("control", "--vmindex", str(index), "show_window")

    def hide_window(self, index: int) -> dict:
        return self._json("control", "--vmindex", str(index), "hide_window")

    # ---------- 应用 ----------
    def app_launch(self, index: int, package: str) -> dict:
        return self._json("control", "--vmindex", str(index), "app", "launch",
                          "--package", package)

    def app_close(self, index: int, package: str) -> dict:
        return self._json("control", "--vmindex", str(index), "app", "close",
                          "--package", package)

    # ---------- 差异化 / 反检测 ----------
    def set_simulation(self, index: int, key: str, value: str) -> dict:
        """key: android_id | mac_address | imei"""
        return self._json("simulation", "--vmindex", str(index),
                          "--simu_key", key, "--simu_value", value)

    def set_setting(self, index: int, **kv: str) -> dict:
        args = ["setting", "--vmindex", str(index)]
        for k, v in kv.items():
            args += ["--key", k, "--value", str(v)]
        return self._json(*args)

    def writable_settings(self, index: int = 0) -> dict:
        return self._json("setting", "--vmindex", str(index), "--all_writable")

    def clone(self, index: int, number: int = 1) -> dict:
        return self._json("clone", "--vmindex", str(index), "--number", str(number))

    # ---------- adb 快捷 ----------
    def adb(self, index: int, cmd: str) -> subprocess.CompletedProcess:
        cp = self._run("adb", "--vmindex", str(index), "--cmd", cmd)
        return cp


if __name__ == "__main__":
    m = MuMuManager()
    print("version:", m.version())
    for i in m.instances():
        print(f"[{i.index}] {i.name} serial={i.serial} android={i.android_version} "
              f"started={i.started} pid={i.pid} wnd={i.render_wnd}")
