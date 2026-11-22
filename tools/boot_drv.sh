#!/system/bin/sh
K=/data/local/tmp
chmod 755 $K/kread
rmmod mhxy_drv 2>/dev/null
rm -f /dev/mhxy_drv

echo "===== load ====="
$K/kread load $K/mhxy_drv.ko

echo
echo "===== /proc/modules ====="
grep mhxy /proc/modules || echo "(not listed)"

echo
echo "===== params dir ====="
ls /sys/module/mhxy_drv/parameters/ 2>&1

echo
echo "===== trigger param go ====="
echo 1 > /sys/module/mhxy_drv/parameters/go
echo "exit=$?"

echo
echo "===== dmesg ====="
dmesg | grep -i "mhxy" | tail -10

echo
echo "===== /proc/misc ====="
grep mhxy /proc/misc || echo "(none)"

MINOR=$(grep mhxy /proc/misc | awk '{print $1}')
if [ -n "$MINOR" ]; then
  mknod /dev/mhxy_drv c 10 "$MINOR"
  chmod 600 /dev/mhxy_drv
  ls -l /dev/mhxy_drv
  echo "===== stat ====="
  $K/kread stat
fi
