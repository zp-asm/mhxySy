#!/system/bin/sh
PID=$(cat /data/local/tmp/pid.txt)
echo "=== 逐个试探客户机空间各段可读性（每段 64KB，找有没有数据） ==="
N=0
while read line; do
  set -- $line
  range=$1; perms=$2; path=$3
  start=${range%-*}
  case "$start" in 4000*) ;; *) continue;; esac
  N=$((N+1)); [ $N -gt 24 ] && break
  # 跳过 PROT_NONE
  [ "$perms" = "---p" ] && continue
  printf "%-32s %-5s -> " "$range" "$perms"
  if dd if=/proc/$PID/mem bs=1024 skip=$((0x$start / 1024)) count=64 2>/dev/null > /data/local/tmp/chunk.bin; then
    SZ=$(wc -c < /data/local/tmp/chunk.bin)
    if [ "$SZ" -lt 1024 ]; then
      echo "空/短读 ($SZ 字节)"
      continue
    fi
    H=$(md5sum /data/local/tmp/chunk.bin | cut -c1-8)
    Z=$(tr -d '\0' < /data/local/tmp/chunk.bin | wc -c)
    S=$(strings -n 6 /data/local/tmp/chunk.bin 2>/dev/null | head -2 | tr '\n' '|')
    echo "OK md5=$H 非零=$Z 串=[${S:0:70}]"
  else
    echo "读取失败"
  fi
done < /proc/$PID/maps
echo
echo "=== 特别关注：rwx 的 Mem_ 段 与 libGame 数据段 ==="
for r in $(grep -E 'Mem_0x|libGame' /proc/$PID/maps | awk '{print $1}' | head -4); do
  start=${r%-*}
  printf "%-32s -> " "$r"
  dd if=/proc/$PID/mem bs=1024 skip=$((0x$start / 1024)) count=32 2>/dev/null | md5sum | cut -c1-16
done
rm -f /data/local/tmp/chunk.bin
