#!/system/bin/sh
echo "===== 输入设备列表 ====="
dumpsys input 2>/dev/null | sed -n '/Input Devices:/,/^ *[0-9]*: /p' | grep -E '^ *[0-9]+: |Classes|KeyLayout|Sources|Touch' | head -30
echo
echo "===== 触摸相关设备 ====="
dumpsys input 2>/dev/null | grep -iE 'touch|touchscreen' | head -12
echo
echo "===== MuMu 注入通道（是否有 nemu/acc 输入服务） ====="
getprop | grep -iE 'nemu|mumu|acc' | head -12
echo
echo "===== 屏幕/显示信息（多实例抓帧用） ====="
wm size; wm density
