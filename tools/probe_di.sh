#!/system/bin/sh
B=/data/data/com.netease.my/files
echo "===== crashhunter_config.txt 全文 ====="
cat $B/crashhunter_config/crashhunter_config.txt; echo; echo
echo "===== uniTrace/crashhunter 树 ====="
find $B/uniTrace -type f 2>/dev/null | head -40
echo
echo "===== 在其中搜 is_emulator / is_rooted / package_fingerprint ====="
grep -rl -iE 'is_emulator|is_rooted|package_fingerprint' $B/uniTrace 2>/dev/null | head -10
echo "--- 命中文件的片段 ---"
for f in $(grep -rl -iE 'is_emulator|is_rooted' $B/uniTrace 2>/dev/null | head -3); do
  echo "### $f"
  head -c 1200 "$f" | strings -n 4 | head -40
done
echo
echo "===== di_refresh_interval=1800 → 设备信息上报节奏；看是否有 di 缓存 ====="
find $B -maxdepth 3 -iname '*di*' -o -maxdepth 3 -iname '*device*' 2>/dev/null | head -10
