// SPDX-License-Identifier: GPL-2.0
/*
 * mhxy_drv.c — 跨进程读写内核模块（x86_64 / Linux 6.1）
 *
 * 目的：目标进程（Houdini 转译的 arm64 游戏）的客户机地址空间
 *       （0x4000_xxxx_xxxx，含 [anon:Mem_0x...]，smaps 里有 36MB 常驻页）
 *       在用户态用 /proc/<pid>/mem 读会得到 -EIO，因为那条路走
 *       access_remote_vm() -> vma->vm_ops->access()。
 *       本模块绕开 vm_ops：直接 mm->pgd 走 4 级页表 → 拿物理页 → __va() 读。
 *
 * 不依赖编译期结构体偏移（MuMu 内核没有公开源码）：
 *   1. kallsyms_lookup_name 用 register_kprobe(symbol_name) 取（抗 KASLR, kptr_restrict=2）
 *   2. 进程/任务用 find_get_pid / get_pid_task / get_task_mm（GPL 导出，无需 task_struct 偏移）
 *   3. mm->pgd 偏移运行期探测：调用方给一个"确定已映射"的用户地址作为探针
 *
 * 加载：insmod -f mhxy_drv.ko
 *       （CONFIG_MODULE_SIG 未开启；CONFIG_MODULE_FORCE_LOAD=y 允许忽略 CRC/vermagic）
 * 卸载：rmmod mhxy_drv（若已 hide_self，需重启或保留句柄）
 */

#include <linux/module.h>
#include <linux/kernel.h>
#include <linux/init.h>
#include <linux/kprobes.h>
#include <linux/fs.h>
#include <linux/miscdevice.h>
#include <linux/uaccess.h>
#include <linux/slab.h>
#include <linux/sched.h>
#include <linux/pid.h>
#include <linux/mm.h>
#include <linux/kallsyms.h>

#define DRV_NAME "mhxy_drv"

/* copy_from_kernel_nofault 是 GPL 导出符号，直接用 */
extern long copy_from_kernel_nofault(void *dst, const void *src, size_t size);

/* ------------------------------------------------------------------ */
/* ioctl 协议                                                         */
/* ------------------------------------------------------------------ */
#define MHXY_IOCTL_MAGIC 'M'

struct mhxy_rw {
	__u32 pid;
	__u32 size;
	__u64 addr;     /* 目标进程虚拟地址 */
	__u64 buf;      /* 调用方用户缓冲区 */
	__u32 write;    /* 0=读 1=写 */
	__u32 pad;
};

struct mhxy_pgd {
	__u32 pid;
	__u32 pad;
	__u64 probe_va; /* 调用方保证该地址在目标进程里已映射 */
	__u64 pgd;      /* 输出 */
	__u64 pgd_off;  /* 输出：探测到的偏移 */
};

struct mhxy_stat {
	__u32 ok;
	__u32 pad;
	__u64 page_offset_base;
	__u64 nsyms;
};

#define MHXY_IOCTL_RW	_IOWR(MHXY_IOCTL_MAGIC, 1, struct mhxy_rw)
#define MHXY_IOCTL_PGD	_IOWR(MHXY_IOCTL_MAGIC, 2, struct mhxy_pgd)
#define MHXY_IOCTL_STAT	_IOWR(MHXY_IOCTL_MAGIC, 3, struct mhxy_stat)

/* ------------------------------------------------------------------ */
/* 运行期符号                                                         */
/* ------------------------------------------------------------------ */
typedef unsigned long (*kln_t)(const char *name);
typedef struct pid *(*find_get_pid_t)(pid_t nr);
typedef struct task_struct *(*get_pid_task_t)(struct pid *pid, enum pid_type type);
typedef struct mm_struct *(*get_task_mm_t)(struct task_struct *task);
typedef void (*mmput_t)(struct mm_struct *mm);

static kln_t  p_kallsyms_lookup_name;
static find_get_pid_t p_find_get_pid;
static get_pid_task_t p_get_pid_task;
static get_task_mm_t  p_get_task_mm;
static mmput_t        p_mmput;
static unsigned long *p_page_offset_base;

static int nsyms_ok;

/* ------------------------------------------------------------------ */
/* 取 kallsyms_lookup_name（5.7 起不再导出，用 kprobe 抓地址）          */
/* ------------------------------------------------------------------ */
static int resolve_kln(void)
{
	struct kprobe kp;
	int ret;

	memset(&kp, 0, sizeof(kp));
	kp.symbol_name = "kallsyms_lookup_name";
	ret = register_kprobe(&kp);
	if (ret)
		return ret;
	p_kallsyms_lookup_name = (kln_t)kp.addr;
	unregister_kprobe(&kp);
	return p_kallsyms_lookup_name ? 0 : -ENOENT;
}

static unsigned long ksym(const char *name)
{
	if (!p_kallsyms_lookup_name)
		return 0;
	return p_kallsyms_lookup_name(name);
}

/* 安全读内核虚拟地址（失败返回 -EFAULT，不 panic） */
static int kread_nofault(void *dst, unsigned long kva, size_t n)
{
	if (kva < 0xffff800000000000UL)
		return -EINVAL;
	return copy_from_kernel_nofault(dst, (const void *)kva, n) ? -EFAULT : 0;
}

/* ------------------------------------------------------------------ */
/* 页表：x86_64 4 级                                                 */
/*   pgd[47:39] -> pud[38:30](可 1G 大页) -> pmd[29:21](可 2M 大页)     */
/*   -> pte[20:12]                                                     */
/* ------------------------------------------------------------------ */
#define P_PRESENT	0x001ULL
#define P_HUGE		0x080ULL
#define PHYS_MASK	0x000ffffffffff000ULL

static inline unsigned long va2ka(unsigned long pa)
{
	return pa + *p_page_offset_base;
}

/* 返回 0 表示成功，pa_out 是物理地址（含页内偏移） */
static int uva2pa(unsigned long pud_base_pa, unsigned long va, unsigned long *pa_out)
{
	unsigned long e, pgd_pa, pud_pa, pmd_pa;
	unsigned long *tbl;
	unsigned long page;
	int ret;

	/* 第 1 级：pgd —— 我们拿到的 mm->pgd 本身就是一个物理地址 */
	pgd_pa = pud_base_pa;
	if (kread_nofault(&e, va2ka(pgd_pa) + ((va >> 39) & 0x1ff) * 8, 8))
		return -EFAULT;
	if (!(e & P_PRESENT))
		return -EFAULT;

	/* p4d 折叠进 pgd（4 级） */
	pud_pa = e & PHYS_MASK;

	/* 第 2 级：pud（30-38 位），可能是 1G 大页 */
	if (kread_nofault(&e, va2ka(pud_pa) + ((va >> 30) & 0x1ff) * 8, 8))
		return -EFAULT;
	if (!(e & P_PRESENT))
		return -EFAULT;
	if (e & P_HUGE) {                        /* 1GB */
		page = e & PHYS_MASK & ~((1UL << 30) - 1);
		*pa_out = page + (va & ((1UL << 30) - 1));
		return 0;
	}
	pmd_pa = e & PHYS_MASK;

	/* 第 3 级：pmd（21-29 位），可能是 2M 大页 */
	if (kread_nofault(&e, va2ka(pmd_pa) + ((va >> 21) & 0x1ff) * 8, 8))
		return -EFAULT;
	if (!(e & P_PRESENT))
		return -EFAULT;
	if (e & P_HUGE) {                        /* 2MB */
		page = e & PHYS_MASK & ~((1UL << 21) - 1);
		*pa_out = page + (va & ((1UL << 21) - 1));
		return 0;
	}

	/* 第 4 级：pte */
	tbl = (unsigned long *)va2ka(e & PHYS_MASK);
	if (kread_nofault(&e, (unsigned long)tbl + ((va >> 12) & 0x1ff) * 8, 8))
		return -EFAULT;
	if (!(e & P_PRESENT))
		return -EFAULT;

	*pa_out = (e & PHYS_MASK) + (va & 0xfffUL);
	ret = 0;
	return ret;
}

/* 跨页读/写 */
static int xread(unsigned long pgd_pa, unsigned long va, void *dst, size_t n)
{
	size_t done = 0;

	while (done < n) {
		unsigned long pa;
		size_t chunk = n - done;
		size_t boundary = 0x1000 - ((va + done) & 0xfff);

		if (chunk > boundary)
			chunk = boundary;
		if (uva2pa(pgd_pa, va + done, &pa))
			return -EFAULT;
		if (copy_from_kernel_nofault((char *)dst + done,
					     (void *)va2ka(pa & ~0xfffULL) +
					     ((va + done) & 0xfff), chunk))
			return -EFAULT;
		done += chunk;
	}
	return 0;
}

static int xwrite(unsigned long pgd_pa, unsigned long va, const void *src, size_t n)
{
	size_t done = 0;

	while (done < n) {
		unsigned long pa;
		size_t chunk = n - done;
		size_t boundary = 0x1000 - ((va + done) & 0xfff);

		if (chunk > boundary)
			chunk = boundary;
		if (uva2pa(pgd_pa, va + done, &pa))
			return -EFAULT;
		memcpy((void *)va2ka(pa & ~0xfffULL) + ((va + done) & 0xfff),
		       (const char *)src + done, chunk);
		done += chunk;
	}
	return 0;
}

/* ------------------------------------------------------------------ */
/* 任务 / mm / pgd 偏移探测                                           */
/* ------------------------------------------------------------------ */
static struct mm_struct *take_mm(u32 pid)
{
	struct pid *p;
	struct task_struct *t;
	struct mm_struct *mm;

	p = p_find_get_pid((pid_t)pid);
	if (!p)
		return NULL;
	t = p_get_pid_task(p, PIDTYPE_PID);
	put_pid(p);
	if (!t)
		return NULL;
	mm = p_get_task_mm(t);
	put_task_struct(t);
	return mm;
}

/*
 * 暴力找 mm->pgd：mm_struct 里存的是 pgd 的"物理地址"(init_top_pgt 时为虚拟地址，
 * 但进程 mm 一定是物理地址)。判据：8 字节对齐、像物理地址、且用它走 probe_va 能成功。
 */
static int find_pgd_off(struct mm_struct *mm, unsigned long probe_va,
			unsigned long *pgd_out, unsigned long *off_out)
{
	int off;
	unsigned long cand, pa;

	for (off = 0x00; off < 0x300; off += 8) {
		if (kread_nofault(&cand, (unsigned long)mm + off, 8))
			continue;
		if (cand < 0x1000 || cand > 0x0000ffffffffffffUL)
			continue;                       /* 必须是物理地址模样 */
		if (cand & 0xfff)
			continue;                       /* 页对齐 */
		if (uva2pa(cand, probe_va, &pa))
			continue;
		*pgd_out = cand;
		*off_out = off;
		return 0;
	}
	return -ENOENT;
}

/* ------------------------------------------------------------------ */
/* 字符设备                                                           */
/* ------------------------------------------------------------------ */
static long mhxy_ioctl(struct file *f, unsigned int cmd, unsigned long arg)
{
	struct mhxy_rw rw;
	struct mhxy_pgd pg;
	struct mhxy_stat st;
	struct mm_struct *mm;
	unsigned long pgd_pa, off, probe;
	void *kbuf;
	int ret = 0;

	if (!p_kallsyms_lookup_name || !p_page_offset_base)
		return -EAGAIN;

	switch (cmd) {
	case MHXY_IOCTL_STAT:
		memset(&st, 0, sizeof(st));
		st.ok = 1;
		st.page_offset_base = *p_page_offset_base;
		st.nsyms = nsyms_ok;
		if (copy_to_user((void __user *)arg, &st, sizeof(st)))
			return -EFAULT;
		return 0;

	case MHXY_IOCTL_PGD:
		if (copy_from_user(&pg, (void __user *)arg, sizeof(pg)))
			return -EFAULT;
		mm = take_mm(pg.pid);
		if (!mm)
			return -ESRCH;
		probe = pg.probe_va ? pg.probe_va : 0x02000000UL; /* dalvik main space 兜底 */
		ret = find_pgd_off(mm, probe, &pgd_pa, &off);
		p_mmput(mm);
		if (ret)
			return ret;
		pg.pgd = pgd_pa;
		pg.pgd_off = off;
		if (copy_to_user((void __user *)arg, &pg, sizeof(pg)))
			return -EFAULT;
		return 0;

	case MHXY_IOCTL_RW:
		if (copy_from_user(&rw, (void __user *)arg, sizeof(rw)))
			return -EFAULT;
		if (!rw.size || rw.size > 0x400000)
			return -EINVAL;

		kbuf = kmalloc(rw.size, GFP_KERNEL);
		if (!kbuf)
			return -ENOMEM;

		mm = take_mm(rw.pid);
		if (!mm) {
			kfree(kbuf);
			return -ESRCH;
		}
		if (find_pgd_off(mm, 0x02000000UL, &pgd_pa, &off)) {
			p_mmput(mm);
			kfree(kbuf);
			return -ENOENT;
		}

		if (rw.write) {
			if (copy_from_user(kbuf, (void __user *)rw.buf, rw.size))
				ret = -EFAULT;
			else
				ret = xwrite(pgd_pa, rw.addr, kbuf, rw.size);
		} else {
			ret = xread(pgd_pa, rw.addr, kbuf, rw.size);
			if (!ret && copy_to_user((void __user *)rw.buf, kbuf, rw.size))
				ret = -EFAULT;
		}
		p_mmput(mm);
		kfree(kbuf);
		return ret;

	default:
		return -ENOTTY;
	}
}

static const struct file_operations mhxy_fops = {
	.owner = THIS_MODULE,
	.unlocked_ioctl = mhxy_ioctl,
	.compat_ioctl = mhxy_ioctl,
};

static struct miscdevice mhxy_misc = {
	.minor = MISC_DYNAMIC_MINOR,
	.name = "mhxy_drv",
	.fops = &mhxy_fops,
	.mode = 0600,
};

/* ------------------------------------------------------------------ */
/* 潜伏：摘模块链表（/proc/modules、kallsyms 的模块遍历都靠它）          */
/* ------------------------------------------------------------------ */
static void hide_self(void)
{
	__module_get(THIS_MODULE);
	list_del(&THIS_MODULE->list);
}

/* ------------------------------------------------------------------ */
static int __init mhxy_init(void)
{
	int ret;

	ret = resolve_kln();
	if (ret) {
		pr_err(DRV_NAME ": kprobe resolve failed %d\n", ret);
		return ret;
	}

	p_find_get_pid     = (find_get_pid_t)ksym("find_get_pid");
	p_get_pid_task     = (get_pid_task_t)ksym("get_pid_task");
	p_get_task_mm      = (get_task_mm_t)ksym("get_task_mm");
	p_mmput            = (mmput_t)ksym("mmput");
	p_page_offset_base = (unsigned long *)ksym("page_offset_base");

	nsyms_ok = (!!p_find_get_pid + !!p_get_pid_task + !!p_get_task_mm +
		    !!p_mmput + !!p_page_offset_base);

	if (!p_find_get_pid || !p_get_pid_task || !p_get_task_mm ||
	    !p_mmput || !p_page_offset_base) {
		pr_err(DRV_NAME ": symbols incomplete (%u/5)\n", nsyms_ok);
		return -ENOENT;
	}

	ret = misc_register(&mhxy_misc);
	if (ret) {
		pr_err(DRV_NAME ": misc_register %d\n", ret);
		return ret;
	}

	pr_info(DRV_NAME ": ready, page_offset_base=0x%lx\n", *p_page_offset_base);
	return 0;
}

static void __exit mhxy_exit(void)
{
	misc_deregister(&mhxy_misc);
}

module_init(mhxy_init);
module_exit(mhxy_exit);
MODULE_LICENSE("GPL");
MODULE_DESCRIPTION("PTE-walk cross-process memory reader (research)");
MODULE_VERSION("0.2");
