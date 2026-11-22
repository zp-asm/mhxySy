#!/system/bin/sh
PID=$(cat /data/local/tmp/pid.txt)
R=$(grep 'Mem_0x20000000' /proc/$PID/maps | head -1)
echo "arena = $R"
START=$(echo "$R" | cut -d- -f1)
echo "start = 0x$START"
echo
echo "=== 头 2MB 内容 ==="
dd if=/proc/$PID/mem bs=1024 skip=$((0x$START / 1024)) count=2048 2>/dev/null > /data/local/tmp/ar.bin
echo "read = $(wc -c < /data/local/tmp/ar.bin) 字节, 非零 = $(tr -d '\0' < /data/local/tmp/ar.bin | wc -c)"
echo "--- ASCII 串（前 10） ---"
strings -n 8 /data/local/tmp/ar.bin 2>/dev/null | head -10
echo "--- 中文命中 ---"
grep -a -o -E '[\xe4-\xe9][\x80-\xbf]{2}([\xe4-\xe9][\x80-\xbf]{2})+' /data/local/tmp/ar.bin 2>/dev/null | head -5
echo
echo "=== 中后段 2MB（偏移 60MB 处） ==="
dd if=/proc/$PID/mem bs=1024 skip=$((0x$START / 1024 + 61440)) count=2048 2>/dev/null > /data/local/tmp/ar2.bin
echo "read = $(wc -c < /data/local/tmp/ar2.bin) 字节, 非零 = $(tr -d '\0' < /data/local/tmp/ar2.bin | wc -c)"
strings -n 8 /data/local/tmp/ar2.bin 2>/dev/null | head -8
echo "--- 关键串搜索（libGame / lua / 长寿村） ---"
for p in libGame lua 长寿村; do printf "  %-10s " "$p"; grep -c -a "$p" /data/local/tmp/ar2.bin 2>/dev/null; done
rm -f /data/local/tmp/ar.bin /data/local/tmp/ar2.bin
