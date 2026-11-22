#!/system/bin/sh
PID=$(cat /data/local/tmp/pid.txt)
echo "=== nemu 内核/设备接口 ==="
for p in /proc/nemu /dev/nemu /sys/kernel/nemu /dev/nemuinput /dev/nemuguest; do
  [ -e "$p" ] && echo "EXIST $p" || echo "none  $p"
done
echo
echo "=== 客户机地址空间的 map_files 是否可打开（等价于能不能拿到后端文件） ==="
ls -l /proc/$PID/map_files/ 2>/dev/null | grep -E '40002|40000' | head -6
echo
echo "=== 关键：客户机大区在 smaps 里的 VmFlags（有无 uffd / io / 特殊标志） ==="
grep -A 24 '^400000000000' /proc/$PID/smaps 2>/dev/null | grep -E 'Size|Rss|VmFlags|VmFlags|KernelPageSize'
echo
echo "=== 该进程所有 >64MB 的映射（找客户机堆上限） ==="
while read line; do
  set -- $line
  range=$1; perms=$2; path=$6
  start=${range%-*}; end=${range#*-}
  sz=$(( (0x$end - 0x$start) / 1048576 ))
  [ $sz -gt 64 ] && echo "  $range ${sz}MB $perms $path"
done < /proc/$PID/maps
