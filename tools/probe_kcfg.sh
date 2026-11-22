#!/system/bin/sh
zcat /proc/config.gz 2>/dev/null > /data/local/tmp/kcfg.txt
for k in CONFIG_MODVERSIONS CONFIG_MODULE_UNLOAD CONFIG_STRICT_MODULE_RWX CONFIG_MODULE_FORCE_LOAD CONFIG_RANDOMIZE_BASE CONFIG_PAGE_TABLE_ISOLATION CONFIG_X86_64 CONFIG_ARM64 CONFIG_KPROBES CONFIG_BPF_SYSCALL CONFIG_DEBUG_FS CONFIG_HAVE_ARCH_TRACEHOOK CONFIG_PROC_KCORE CONFIG_DEVKMEM; do
  v=$(grep -E "^$k=|^# $k is not set" /data/local/tmp/kcfg.txt | head -1)
  printf "%-34s %s\n" "$k" "${v:-<absent>}"
done
echo "--- 内核架构真身（ELF header） ---"
head -c 20 /dev/zero > /dev/null
python3 - 2>/dev/null <<'EOF' || true
EOF
ls /sys/kernel/ | head -20
rm -f /data/local/tmp/kcfg.txt
