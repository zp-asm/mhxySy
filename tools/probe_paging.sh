#!/system/bin/sh
zcat /proc/config.gz 2>/dev/null > /data/local/tmp/k.txt
echo "=== 5 级页表相关（影响页表走查层数） ==="
for k in CONFIG_X86_5LEVEL CONFIG_X86_64 CONFIG_PGTABLE_LEVELS CONFIG_DYNAMIC_MEMORY_LAYOUT CONFIG_RANDOMIZE_MEMORY CONFIG_X86_PAE; do
  v=$(grep -E "^$k=|^# $k is not set" /data/local/tmp/k.txt | head -1)
  printf "%-32s %s\n" "$k" "${v:-<absent>}"
done
echo
echo "=== CPU 是否支持/启用 la57 ==="
grep -o -m1 'la57' /proc/cpuinfo && echo "CPU 支持 la57" || echo "CPU 无 la57"
echo "--- vabits / 用户地址上限 ---"
grep -m1 'address sizes' /proc/cpuinfo
echo
echo "=== 页表相关符号是否在 kallsyms（kptr_restrict=2，只看是否存在名字） ==="
grep -c 'page_offset_base' /proc/kallsyms
grep -c 'init_top_pgt' /proc/kallsyms
grep -c 'copy_from_kernel_nofault' /proc/kallsyms
grep -c 'kallsyms_lookup_name' /proc/kallsyms
rm -f /data/local/tmp/k.txt
