#!/system/bin/sh
PID=$(cat /data/local/tmp/pid.txt)
echo "=== 能读的区域里到底有没有游戏状态？(dalvik main space 前 64MB) ==="
echo "--- UTF-16LE 形式的 '长寿村' / '背包' / 'lua' ---"
dd if=/proc/$PID/mem bs=1048576 skip=32 count=64 2>/dev/null > /data/local/tmp/dv.bin
ls -l /data/local/tmp/dv.bin
for pat in '长寿村' '背包' '任务' 'lua' 'Lua' 'Messiah'; do
  n8=$(grep -c -a "$pat" /data/local/tmp/dv.bin 2>/dev/null)
  n16=$(grep -c -a -P "$(echo -n $pat | sed 's/./&\x00/g')" /data/local/tmp/dv.bin 2>/dev/null)
  echo "  $pat : utf8=$n8 utf16=$n16"
done
echo
echo "=== 对照组：Houdini 客户机大区（rw-p 且 >8MB）可读性 ==="
while read line; do
  set -- $line
  range=$1; perms=$2
  case "$range" in 4000*) ;; *) continue;; esac
  [ "$perms" = "rw-p" ] || continue
  start=${range%-*}; end=${range#*-}
  sz=$(( (0x$end - 0x$start) / 1048576 ))
  [ $sz -lt 8 ] && continue
  printf "%s %sMB -> " "$range" "$sz"
  dd if=/proc/$PID/mem bs=4096 skip=$((0x$start / 4096)) count=4 2>&1 >/dev/null | head -1
  break
done < /proc/$PID/maps
rm -f /data/local/tmp/dv.bin
