# x86_64 内核模块（MuMu 的 Android 内核是 x86_64；uname 伪造成 aarch64，别被骗）
obj-m += mhxy_drv.o

# 目标内核源码树（用 6.1.90 或 android13-6.1，二者对这个模块足够）
KDIR ?= $(HOME)/linux-6.1.90
ARCH ?= x86_64
CROSS_COMPILE ?=

# 这个模块只用导出符号 + 页表常量，不需要 MuMu 的私有头文件
# -Wno-error：6.1 的 -Werror=unused-function 之类会把小警告变硬错误，这里兜底
ccflags-y += -Wno-unused-variable -Wno-error

all:
	$(MAKE) -C $(KDIR) M=$(PWD) ARCH=$(ARCH) CROSS_COMPILE=$(CROSS_COMPILE) modules

clean:
	$(MAKE) -C $(KDIR) M=$(PWD) ARCH=$(ARCH) clean

# 一键：编译 → 推送 → 加载
deploy: all
	adb push mhxy_drv.ko /data/local/tmp/
	adb shell 'insmod -f /data/local/tmp/mhxy_drv.ko && dmesg | tail -5'

.PHONY: all clean deploy
