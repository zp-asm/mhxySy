#!/usr/bin/env python3
import subprocess
from pathlib import Path

script = r"""
echo ABI_PROP
getprop ro.product.cpu.abi
getprop ro.product.cpu.abi2
getprop ro.product.cpu.abilist
getprop ro.build.id
getprop ro.build.display.id
getprop ro.build.version.incremental
echo SU_PATHS
for p in /system/bin/su /system/xbin/su /system/sbin/su /vendor/bin/su /sbin/su; do
  if [ -e "$p" ]; then ls -l "$p"; else echo MISSING "$p"; fi
done
echo EMU_FILES
for p in /dev/socket/genyd /dev/socket/baseband_genyd /dev/socket/qemud /dev/qemu_pipe /system/bin/nox-prop /sys/kernel/debug/x86 /system/app/EmuCoreService/EmuCoreService.apk /system/lib64/libhoudini.so /system/lib64/arm64/libc++.so /fstab.nox /init.nox.rc /ueventd.android_x86.rc /x86.prop; do
  if [ -e "$p" ]; then echo EXISTS "$p"; else echo MISSING "$p"; fi
done
echo PACKAGES
for pkg in com.vphone.helper com.vphone.launcher com.android.flysilkworm com.android.coreservice com.cyanogenmod.filemanager com.netease.mumu.cloner; do
  pm path "$pkg" || echo NOPKG "$pkg"
done
echo WHICH_SU
command -v su || echo NO_SU_IN_PATH
echo ID
id
"""
adb = r"D:\develop\tools\android\platform-tools\adb.exe"
p = subprocess.run([adb, "-s", "127.0.0.1:16384", "shell", script], capture_output=True)
text = p.stdout.decode("utf-8", "replace") + "\n" + p.stderr.decode("utf-8", "replace")
Path(r"E:\gamework\mhxyMobile\analysis\gap_device.txt").write_text(text, encoding="utf-8")
print(text)
print("rc", p.returncode)
