#!/system/bin/sh
PID=$(cat /data/local/tmp/pid.txt)
echo "=== rwx 的 Mem_ 段（Houdini 的客户机内存后端候选） ==="
grep 'Mem_0x' /proc/$PID/maps
echo
for r in $(grep 'Mem_0x' /proc/$PID/maps | awk '{print $1}'); do
  start=${r%-*}
  echo "--- $r"
  # 头 1MB
  dd if=/proc/$PID/mem bs=1024 skip=$((0x$start / 1024)) count=1024 2>/dev/null > /data/local/tmp/mem1.bin
  echo "  size=$(wc -c < /data/local/tmp/mem1.bin)  非零字节=$(tr -d '\0' < /data/local/tmp/mem1.bin | wc -c)"
  echo "  可打印串样本:"
  strings -n 6 /data/local/tmp/mem1.bin 2>/dev/null | head -6 | sed 's/^/    /'
  echo "  中文(UTF-8)命中数: $(grep -c -a -P '[\xe4-\xe9][\x80-\xbf]{2}' /data/local/tmp/mem1.bin 2>/dev/null || echo n/a)"
  # 中部 1MB
  mid=$((0x$start / 1024 + 20480))
  dd if=/proc/$PID/mem bs=1024 skip=$mid count=1024 2>/dev/null > /data/local/tmp/mem2.bin
  echo "  中部 size=$(wc -c < /data/local/tmp/mem2.bin) 非零=$(tr -d '\0' < /data/local/tmp/mem2.bin | wc -c)"
  strings -n 6 /data/local/tmp/mem2.bin 2>/dev/null | head -4 | sed 's/^/    中:/'
done
rm -f /data/local/tmp/mem1.bin /data/local/tmp/mem2.bin
