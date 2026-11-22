#!/system/bin/sh
PID=$(cat /data/local/tmp/pid.txt)
echo "=== 候选大区（rw-p, 大小>8MB） ==="
while read line; do
  set -- $line
  range=$1; perms=$2; path=$6
  [ "$perms" = "rw-p" ] || continue
  start=${range%-*}; end=${range#*-}
  sz=$(( (0x$end - 0x$start) / 1048576 ))
  [ $sz -gt 8 ] && echo "$range ${sz}MB $path"
done < /proc/$PID/maps | head -12

echo
echo "=== 抽样：每区读 1MB，打印前几条字符串 ==="
n=0
while read line; do
  set -- $line
  range=$1; perms=$2; path=$6
  [ "$perms" = "rw-p" ] || continue
  start=${range%-*}; end=${range#*-}
  sz=$(( (0x$end - 0x$start) / 1048576 ))
  [ $sz -gt 8 ] || continue
  n=$((n+1)); [ $n -gt 6 ] && break
  echo "--- $range ${sz}MB $path"
  dd if=/proc/$PID/mem bs=1024 skip=$((0x$start / 1024)) count=1024 2>/dev/null | strings -n 6 | head -5
done < /proc/$PID/maps
