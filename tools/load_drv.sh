#!/system/bin/sh
# reload module + create node + stat   (ASCII only)
K=/data/local/tmp
rmmod mhxy_drv 2>/dev/null
rm -f /dev/mhxy_drv

echo "===== load ====="
$K/kread load $K/mhxy_drv.ko

echo
echo "===== /proc/modules ====="
grep mhxy /proc/modules || echo "(not listed)"

echo
echo "===== /proc/misc ====="
grep mhxy /proc/misc || echo "(no misc entry yet)"

echo
echo "===== dmesg (mhxy) ====="
dmesg | grep -i mhxy | tail -8

MINOR=$(grep mhxy /proc/misc | awk '{print $1}')
if [ -n "$MINOR" ]; then
  mknod /dev/mhxy_drv c 10 "$MINOR"
  chmod 600 /dev/mhxy_drv
  echo
  echo "===== node ====="
  ls -l /dev/mhxy_drv
  echo
  echo "===== stat ====="
  $K/kread stat
else
  echo
  echo "!! no misc minor -> init did not run"
fi
