#!/system/bin/sh
echo "===== app_ntp0 目录树 ====="
ls -la /data/data/com.netease.my/app_ntp0/ 2>&1
echo
echo "===== 版本目录内容 ====="
for d in /data/data/com.netease.my/app_ntp0/*/; do echo "--- $d"; ls -la "$d" 2>&1 | head -40; done
echo
echo "===== files 目录里的插件/配置 ====="
ls -la /data/data/com.netease.my/files 2>&1 | head -30
echo
echo "===== 当前加载的 libunisec 段信息 ====="
PID=$(pidof com.netease.my | tr ' ' '\n' | head -1)
grep -E 'libunisec|app_ntp0' /proc/$PID/maps 2>/dev/null
echo
echo "===== 反作弊线程完整列表（含 native 线程） ====="
for t in /proc/$PID/task/*; do printf "%s %s\n" "$(basename $t)" "$(cat $t/comm 2>/dev/null)"; done | sort -k2 | head -60
