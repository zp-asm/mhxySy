#!/usr/bin/env python3
import subprocess
from pathlib import Path

adb = r"D:\develop\tools\android\platform-tools\adb.exe"
script = r"""
echo CLONER
dumpsys package com.netease.mumu.cloner | grep -E 'userId=|pkgFlags|versionName|codePath' | head -n 20
echo GAME
dumpsys package com.netease.my | grep -E 'userId=|versionName|versionCode|flags=' | head -n 20
echo LOG
logcat -d -t 400 | grep -E 'wnydebug|CEmulatorDetector|UniSDK EmulatorDetector|is_emulator|EmulatorDetect|Sdkybuaxwny' | tail -n 40
"""
p = subprocess.run([adb, "-s", "127.0.0.1:16384", "shell", script], capture_output=True)
text = p.stdout.decode("utf-8", "replace")
Path(r"E:\gamework\mhxyMobile\analysis\gap_pkg.txt").write_text(text, encoding="utf-8")
print(text)
