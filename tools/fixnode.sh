#!/system/bin/sh
echo "===== 1) 模块是否在 /proc/modules ====="
grep mhxy /proc/modules || echo "(not listed)"
echo
echo "===== 2) misc 设备号 ====="
grep mhxy /proc/misc || echo "(not in /proc/misc)"
echo
echo "===== 3) 我们的 dmesg ====="
dmesg | grep -i mhxy | tail -10
echo
echo "===== 4) 手动建节点（misc major=10） ====="
MINOR=$(grep mhxy /proc/misc | awk '{print $1}')
echo "minor = ${MINOR:-<none>}"
if [ -n "$MINOR" ]; then
  rm -f /dev/mhxy_drv
  mknod /dev/mhxy_drv c 10 "$MINOR"
  chmod 600 /dev/mhxy_drv
  ls -l /dev/mhxy_drv
fi
echo
echo "===== 5) 取状态 ====="
/data/local/tmp/kread stat 2>&1
