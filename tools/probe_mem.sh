#!/system/bin/sh
PID=$(cat /data/local/tmp/pid.txt)
echo "=== 1) 该进程所有 r-xp 段（前 25） ==="
grep -E 'r-xp' /proc/$PID/maps | head -25
echo
echo "=== 2) 匿名可执行段统计 ==="
grep -E 'r-xp.*\[anon' /proc/$PID/maps | wc -l
echo
echo "=== 3) 在 libGame.so 各段中找 ELF magic / 可打印串 ==="
for seg in $(grep libGame.so /proc/$PID/maps | cut -d' ' -f1); do
  START=$(echo $seg | cut -d- -f1)
  dd if=/proc/$PID/mem bs=1 skip=$((0x$START)) count=16 2>/dev/null | xxd | head -1
done
echo
echo "=== 4) rw-p 数据段抽样（找 lua / 字符串特征） ==="
RW=$(grep libGame.so /proc/$PID/maps | grep rw-p | cut -d' ' -f1 | head -1 | cut -d- -f1)
echo "rw-p seg start = $RW"
dd if=/proc/$PID/mem bs=1 skip=$((0x$RW)) count=262144 2>/dev/null | strings -n 8 | head -20
echo
echo "=== 5) 该进程 maps 中的 native bridge / 转译痕迹 ==="
grep -E 'arm64|libnb|houdini|ndk_translation|nativebridge' /proc/$PID/maps | head -10
