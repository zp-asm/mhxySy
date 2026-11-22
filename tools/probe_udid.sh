#!/system/bin/sh
B=/data/data/com.netease.my
echo "===== shared_prefs 列表 ====="
ls -la $B/shared_prefs 2>/dev/null | head -20
echo
echo "===== 谁存了 udid / device_id ====="
grep -rl -iE 'udid|device_id|unisdk_device' $B/shared_prefs 2>/dev/null | head -10
echo
echo "===== 命中文件内容（截断） ====="
for f in $(grep -rl -iE 'udid|device_id' $B/shared_prefs 2>/dev/null | head -4); do
  echo "### $f"
  grep -oiE '<string name="[^"]*(udid|device|uid)[^"]*">[^<]{0,64}' "$f" | head -8
done
echo
echo "===== crashhunter.param（可能是 device_id 载体） ====="
head -c 400 /data/local/tmp/crashhunter.param 2>/dev/null; echo
