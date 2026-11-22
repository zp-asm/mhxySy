#!/system/bin/sh
echo "===== 1) 内核版本与构建 ====="
uname -a
cat /proc/version
echo
echo "===== 2) 模块支持 ====="
if [ -e /proc/config.gz ]; then
  zcat /proc/config.gz 2>/dev/null | grep -E 'CONFIG_MODULES=|CONFIG_MODULE_SIG|CONFIG_MODULE_SIG_FORCE|CONFIG_STRICT_KERNEL_RWX|CONFIG_KALLSYMS|CONFIG_DEVKMEM|CONFIG_STRICT_DEVMEM|CONFIG_DEBUG_INFO' | head -20
else
  echo "no /proc/config.gz"
  for f in /boot/config-$(uname -r); do [ -e "$f" ] && grep -E 'CONFIG_MODULES=|CONFIG_MODULE_SIG' "$f"; done
fi
echo "--- 已加载模块数 ---"
wc -l /proc/modules 2>/dev/null
head -8 /proc/modules 2>/dev/null
echo "--- /lib/modules ---"
ls -l /lib/modules 2>/dev/null | head
echo
echo "===== 3) 关键节点/接口 ====="
for f in /dev/kmem /dev/mem /proc/kcore /sys/kernel/debug /proc/kallsyms; do
  if [ -e "$f" ]; then printf "EXIST %-18s perms=%s size=%s\n" "$f" "$(ls -ld $f | awk '{print $1}')" "$(ls -l $f | awk '{print $5}')"; else echo "none  $f"; fi
done
echo "--- kptr_restrict / dmesg_restrict ---"
cat /proc/sys/kernel/kptr_restrict 2>/dev/null; cat /proc/sys/kernel/dmesg_restrict 2>/dev/null
echo "--- kallsyms 抽样（能否读到符号地址） ---"
head -3 /proc/kallsyms 2>/dev/null
grep -c ' T ' /proc/kallsyms 2>/dev/null
echo
echo "===== 4) 工具链 ====="
for t in insmod rmmod modprobe lsmod dmesg; do printf "%-8s " $t; command -v $t || echo missing; done
echo
echo "===== 5) 是否 GKI / vendor 分支 ====="
getprop ro.board.platform; getprop ro.kernel.version 2>/dev/null; getprop ro.product.kernel 2>/dev/null
cat /proc/cmdline 2>/dev/null | head -c 400
