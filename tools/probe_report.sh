#!/system/bin/sh
B=/data/data/com.netease.my/files
echo "===== crashhunter_config ====="
ls -la $B/crashhunter_config 2>&1
for f in $B/crashhunter_config/*; do echo "--- $f"; head -c 600 "$f" 2>/dev/null; echo; done
echo
echo "===== ngplugin / uniTrace / 其它 ====="
ls -la $B/ngplugin $B/uniTrace 2>&1 | head -30
echo
echo "===== 77KB 那份 05446735... ====="
head -c 400 $B/05446735E3EA099C1D6215051A1AE955 2>/dev/null | strings -n 6 | head -20
echo
echo "===== logcat 里 CrashHunter / EmulatorDetector 痕迹 ====="
logcat -d -v brief 2>/dev/null | grep -iE 'CEmulatorDetector|EmulatorDetector|CrashHunter|is_emulator|is_rooted' | tail -20
