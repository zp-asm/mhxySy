// kread.c — mhxy_drv 的用户态客户端（静态链接，Android x86_64，无需 python/root 以外的依赖）
//
// 用法：
//   kread stat                      读驱动状态（page_offset_base / 符号数）
//   kread pgd  <pid> [probe_va]     取 mm->pgd 并探测偏移
//   kread read <pid> <addr> <len>   十六进制打印
//   kread arena <pid>               读 Houdini 客户机 arena 头 256 字节（决定性测试）
//
// 编译（CI 里用 NDK）：
//   x86_64-linux-android24-clang -static -O2 -o kread kread.c

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include <fcntl.h>
#include <unistd.h>
#include <errno.h>
#include <dirent.h>
#include <sys/ioctl.h>

#define DEV "/dev/mhxy_drv"
#define MHXY_MAGIC 'M'

struct mhxy_rw {
	uint32_t pid;
	uint32_t size;
	uint64_t addr;
	uint64_t buf;
	uint32_t write;
	uint32_t pad;
};

struct mhxy_pgd {
	uint32_t pid;
	uint32_t pad;
	uint64_t probe_va;
	uint64_t pgd;
	uint64_t pgd_off;
};

struct mhxy_stat {
	uint32_t ok;
	uint32_t pad;
	uint64_t page_offset_base;
	uint64_t nsyms;
};

#define MHXY_IOCTL_RW   _IOWR(MHXY_MAGIC, 1, struct mhxy_rw)
#define MHXY_IOCTL_PGD  _IOWR(MHXY_MAGIC, 2, struct mhxy_pgd)
#define MHXY_IOCTL_STAT _IOWR(MHXY_MAGIC, 3, struct mhxy_stat)

static int g_fd = -1;

static int find_pid(const char *name)
{
	DIR *d = opendir("/proc");
	struct dirent *e;
	char path[128], buf[256];
	int fd, n, pid = -1;

	if (!d)
		return -1;
	while ((e = readdir(d))) {
		if (e->d_name[0] < '0' || e->d_name[0] > '9')
			continue;
		snprintf(path, sizeof(path), "/proc/%s/cmdline", e->d_name);
		fd = open(path, O_RDONLY);
		if (fd < 0)
			continue;
		n = read(fd, buf, sizeof(buf) - 1);
		close(fd);
		if (n <= 0)
			continue;
		buf[n] = 0;
		if (!strcmp(buf, name)) {
			pid = atoi(e->d_name);
			break;
		}
	}
	closedir(d);
	return pid;
}

static void hexdump(const uint8_t *b, size_t n, uint64_t base, int maxlines)
{
	size_t i, j;
	int line = 0;

	for (i = 0; i < n && line < maxlines; i += 16, line++) {
		printf("%016llx  ", (unsigned long long)(base + i));
		for (j = 0; j < 16; j++) {
			if (i + j < n)
				printf("%02x ", b[i + j]);
			else
				printf("   ");
		}
		printf(" |");
		for (j = 0; j < 16 && i + j < n; j++) {
			uint8_t c = b[i + j];
			putchar(c >= 32 && c < 127 ? c : '.');
		}
		printf("|\n");
	}
}

static int do_stat(void)
{
	struct mhxy_stat st;
	memset(&st, 0, sizeof(st));
	if (ioctl(g_fd, MHXY_IOCTL_STAT, &st) < 0)
		return -1;
	printf("STAT ok=%u page_offset_base=0x%llx symbols=%llu/5\n",
	       st.ok, (unsigned long long)st.page_offset_base,
	       (unsigned long long)st.nsyms);
	return 0;
}

static int do_pgd(int pid, uint64_t probe)
{
	struct mhxy_pgd pg;
	memset(&pg, 0, sizeof(pg));
	pg.pid = (uint32_t)pid;
	pg.probe_va = probe;
	if (ioctl(g_fd, MHXY_IOCTL_PGD, &pg) < 0)
		return -1;
	printf("PGD pid=%d pgd=0x%llx mm->pgd_off=0x%llx\n",
	       pid, (unsigned long long)pg.pgd, (unsigned long long)pg.pgd_off);
	return 0;
}

static int do_read(int pid, uint64_t addr, uint32_t len)
{
	struct mhxy_rw rw;
	uint8_t *buf;
	if (len == 0 || len > (16u << 20))
		return -1;
	buf = malloc(len);
	if (!buf)
		return -1;
	memset(&rw, 0, sizeof(rw));
	rw.pid = (uint32_t)pid;
	rw.size = len;
	rw.addr = addr;
	rw.buf = (uint64_t)(uintptr_t)buf;
	rw.write = 0;
	if (ioctl(g_fd, MHXY_IOCTL_RW, &rw) < 0) {
		free(buf);
		return -1;
	}
	hexdump(buf, len, addr, (int)(len / 16 > 32 ? 32 : len / 16 + 1));
	free(buf);
	return 0;
}

int main(int argc, char **argv)
{
	int pid;

	if (argc < 2) {
		fprintf(stderr,
			"usage:\n"
			"  kread stat\n"
			"  kread pgd  <pid|name> [probe_va]\n"
			"  kread read <pid|name> <addr> <len>\n"
			"  kread arena <pid|name>\n");
		return 2;
	}

	g_fd = open(DEV, O_RDWR);
	if (g_fd < 0) {
		fprintf(stderr, "open %s: %s\n", DEV, strerror(errno));
		return 3;
	}

	if (!strcmp(argv[1], "stat")) {
		if (do_stat()) { perror("STAT"); return 4; }
		return 0;
	}

	if (argc < 3) { fprintf(stderr, "missing pid\n"); return 2; }
	pid = atoi(argv[2]);
	if (pid <= 0)
		pid = find_pid(argv[2]);
	if (pid <= 0) { fprintf(stderr, "pid not found\n"); return 5; }

	if (!strcmp(argv[1], "pgd")) {
		uint64_t probe = (argc > 3) ? strtoull(argv[3], NULL, 0) : 0x02000000ULL;
		if (do_stat()) fprintf(stderr, "warn: STAT failed\n");
		if (do_pgd(pid, probe)) { perror("PGD"); return 4; }
		return 0;
	}

	if (!strcmp(argv[1], "read")) {
		uint64_t addr = (argc > 3) ? strtoull(argv[3], NULL, 0) : 0;
		uint32_t len = (argc > 4) ? (uint32_t)strtoul(argv[4], NULL, 0) : 256;
		if (do_read(pid, addr, len)) { perror("READ"); return 4; }
		return 0;
	}

	if (!strcmp(argv[1], "arena")) {
		/* 决定性测试：这段在用户态 /proc/pid/mem 里是 EIO */
		if (do_read(pid, 0x400060174000ULL, 256)) {
			perror("READ arena");
			fprintf(stderr, "该页 PTE 不存在，换地址重试\n");
			return 4;
		}
		return 0;
	}

	fprintf(stderr, "unknown cmd\n");
	return 2;
}
