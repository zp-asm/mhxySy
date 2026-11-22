#!/system/bin/sh
# 检测面取证脚本（只读）
echo "===== 1. 模拟器指纹 props ====="
for p in ro.product.brand ro.product.model ro.product.device ro.product.name \
         ro.product.manufacturer ro.product.board ro.hardware ro.board.platform \
         ro.build.fingerprint ro.build.flavor ro.build.tags ro.build.type \
         ro.debuggable ro.secure ro.kernel.qemu ro.boot.qemu ro.boot.hardware \
         ro.serialno ro.product.cpu.abilist ro.dalvik.vm.isa.arm64; do
  printf "%-28s = %s\n" "$p" "$(getprop $p)"
done

echo
echo "===== 2. proc/cpuinfo 硬指纹 ====="
head -30 /proc/cpuinfo | grep -Ei 'model name|Hardware|processor|flags|vendor_id' | head -10

echo
echo "===== 3. 传感器（模拟器常见缺失/伪造点） ====="
dumpsys sensorservice 2>/dev/null | sed -n '1,40p'

echo
echo "===== 4. 反作弊/易盾日志 ====="
logcat -d -v time 2>/dev/null | grep -iE 'wnydebug|ybuax|EmulatorDetect|Wnyklrie|unisec|secsdk|SecLib|ntunisdk|Checker' | tail -60

echo
echo "===== 5. 游戏进程关键状态 ====="
PID=$(pidof com.netease.my | tr ' ' '\n' | head -1)
echo "pid=$PID"
grep -E 'TracerPid|Seccomp|CapEff|NoNewPrivs|Dumpable' /proc/$PID/status 2>/dev/null
if [ -r /proc/$PID/status ]; then echo "proc readable: yes"; fi

echo
echo "===== 6. 游戏进程内可疑线程（反外挂线程名） ====="
ls /proc/$PID/task 2>/dev/null | while read t; do cat /proc/$PID/task/$t/comm 2>/dev/null; done | sort | uniq -c | sort -rn | head -30

echo
echo "===== 7. 游戏加载的 so（关键模块基址） ====="
grep -E '\.so$' /proc/$PID/maps 2>/dev/null | awk '{print $1, $6}' | grep -E 'libGame|libybuaxz|libunisec|libsecsdk|libsec-lib|libntunisdk|libnesdk|libnep|libc\+\+|libart' | head -20

echo
echo "===== 8. 是否存在 hook/调试器痕迹（maps 中的匿名可执行段/异常路径） ====="
grep -cE 'r-xp' /proc/$PID/maps 2>/dev/null
grep -E 'frida|xposed|substrate|magisk|zygisk|lsposed|gadget' /proc/$PID/maps 2>/dev/null | head
echo "--- /data/local/tmp 下的工具 ---"
ls -la /data/local/tmp 2>/dev/null | head -20

echo
echo "===== 9. 多开/分身检测面 ====="
pm list packages -3
ls -d /data/data/* 2>/dev/null | wc -l
echo "cloner installed:"
pm list packages | grep -i mumu

echo
echo "===== 10. seccomp / ptrace 能力自检 ====="
cat /proc/sys/kernel/yama/ptrace_scope 2>/dev/null
echo "self ptrace test skip (read-only pass)"
