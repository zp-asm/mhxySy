#!/system/bin/sh
PID=$(cat /data/local/tmp/pid.txt)
echo "=== 按 RSS 排序的 Top 15 映射（找真正的游戏数据在哪） ==="
awk '
/^[0-9a-f]+-[0-9a-f]+ / { range=$1; perms=$2; name=""; for(i=6;i<=NF;i++) name=name" "$i; rss=0 }
/^Rss:/ { rss=$2; if (rss>0) printf "%8d kB  %s %s%s\n", rss, range, perms, name }
' /proc/$PID/smaps | sort -rn | head -15

echo
echo "=== 每个 Top 段的 64KB 可读性抽测 ==="
awk '
/^[0-9a-f]+-[0-9a-f]+ / { range=$1; perms=$2; name=""; for(i=6;i<=NF;i++) name=name" "$i; rss=0 }
/^Rss:/ { rss=$2; if (rss>8000) printf "%s %s%s\n", range, perms, name }
' /proc/$PID/smaps | head -12 | while read range perms name; do
  start=${range%-*}
  printf "%-26s %-5s %-28s -> " "$range" "$perms" "${name:0:28}"
  dd if=/proc/$PID/mem bs=1024 skip=$((0x$start / 1024)) count=64 2>/dev/null > /data/local/tmp/t.bin
  SZ=$(wc -c < /data/local/tmp/t.bin)
  if [ "$SZ" -lt 1024 ]; then echo "不可读"; else
    NZ=$(tr -d '\0' < /data/local/tmp/t.bin | wc -c)
    S=$(strings -n 8 /data/local/tmp/t.bin 2>/dev/null | head -1)
    echo "可读 非零=$NZ 串=[${S:0:40}]"
  fi
done
rm -f /data/local/tmp/t.bin
