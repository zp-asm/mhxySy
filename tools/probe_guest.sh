#!/system/bin/sh
PID=$(cat /data/local/tmp/pid.txt)
echo "=== A) 读 Houdini 客户机地址空间（显示错误） ==="
for a in 400020c00000 40002591f000 400027c06000 4000691de000 400000000000; do
  printf "%s -> " $a
  dd if=/proc/$PID/mem bs=1 skip=$((0x$a)) count=16 2>&1 | tr -d '\0' | head -2
  echo
done

echo "=== B) 同一进程 dalvik 堆对照（应可读） ==="
printf "02000000 -> "; dd if=/proc/$PID/mem bs=1 skip=$((0x02000000)) count=16 2>&1 | xxd | head -1

echo
echo "=== C) map_files 里 4000 段指向什么 ==="
ls -l /proc/$PID/map_files 2>/dev/null | grep -E '4000(2|0)' | head -8

echo
echo "=== D) smaps 中该段的 VmFlags ==="
grep -A 22 '^40002591f000' /proc/$PID/smaps 2>/dev/null | grep -E 'Size|Rss|VmFlags|VmFlags|AnonHugePages|KernelPageSize|MMUPageSize' | head -8

echo
echo "=== E) 是否存在 houdini 专用内存文件 ==="
ls -l /proc/$PID/fd 2>/dev/null | grep -iE 'houdini|arm|nb|memfd|deleted' | head -10
