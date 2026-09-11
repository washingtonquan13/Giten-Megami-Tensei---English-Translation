/* Native driver for giten/exe/hook.c -- freestanding Win32, no C runtime
 * (the mingw driver cannot link its CRT from a path with spaces).
 *
 * Three modes:
 *
 *   hook_harness <image.bin> <fid> <handle> <start_pc> <stop_pc>
 *       One walk.  `fid` is ignored -- overlay v6 identifies no file -- but the
 *       argument is still accepted so the existing tests keep working.
 *
 *   hook_harness pace <granularity_ms> <total_ms> <stall_at_ms> <stall_ms>
 *       Drives pace() against a simulated clock.
 *
 *   hook_harness script <file>
 *       One command per line, so ONE PROCESS can do what one play session
 *       does -- which is the only way to test that a buffer swapped under a
 *       live handle stops serving the old script's English:
 *
 *           load <handle> <image.bin>     map the image as this handle's buffer
 *           reload <handle> <image.bin>   overwrite that buffer IN PLACE
 *                                         (same base pointer, so only the
 *                                         content changes -- exactly what the
 *                                         engine does when it loads the next
 *                                         shop into the same slot)
 *           walk <handle> <start> <stop>  walk, printing "bytes=<hex>" and
 *                                         "pc=<final>"
 *           fid <n>                       accepted and ignored (see above)
 *           #...                          a comment
 *
 * Loads a runtime image (index + records, as overlay.image_bytes builds it),
 * and walks from start_pc until the PC equals stop_pc, calling the hook for
 * every byte exactly as the engine's next_char would.  overlay.dat is read from
 * the current directory by the hook itself, through the real Win32 imports.
 * Numbers are decimal or 0x-hex.
 */
#include "hook_harness.h"

u8 *g_bases[16];

u8 hook(u32 handle, u16 *pcp);
int pace(void);
static u32 number(const char *s);

u8 orig_fetch(u32 handle, u16 *pcp)
{
    u8 *base = g_bases[handle];
    u16 pc = *pcp;
    *pcp = (u16)(pc + 1);
    return base ? base[pc] : 0;
}

/* the simulated clock behind pace(): true time in ms, reported in steps of
 * g_granularity (1 = a fine timer, 16 = Windows' coarse 15.6 ms default) */
static u32 g_true_ms, g_granularity = 1;

u32 fake_time(void)
{
    return g_true_ms - g_true_ms % g_granularity;
}

static void out(const char *s, u32 n)
{
    DWORD w;
    WriteFile(GetStdHandle(STD_OUTPUT_HANDLE), s, n, &w, 0);
}

static u32 put_num(char *p, u32 v)
{
    char tmp[12];
    u32 k = 0, n = 0;
    do { tmp[k++] = '0' + v % 10; v /= 10; } while (v);
    while (k) p[n++] = tmp[--k];
    return n;
}

static u32 put_str(char *p, const char *s)
{
    u32 n = 0;
    while (*s) p[n++] = *s++;
    return n;
}

/* hook_harness pace <granularity_ms> <total_ms> <stall_at_ms> <stall_ms>
 *
 * Drives pace() the way the main loop does -- polled continuously (8 polls a
 * simulated millisecond) -- over total_ms of true time, with the clock
 * reported at the given granularity.  At stall_at the loop stops polling for
 * stall_ms (a window drag).  Prints "ticks=<total> after_stall=<ticks in the
 * 40 ms after the stall>". */
static void pace_mode(char **argv)
{
    u32 total = number(argv[2]), stall_at = number(argv[3]), stall = number(argv[4]);
    u32 ticks = 0, after = 0, poll;
    char line[64];
    u32 n = 0;
    g_granularity = number(argv[1]);
    if (!g_granularity) g_granularity = 1;
    for (g_true_ms = 0; g_true_ms < total; g_true_ms++) {
        if (stall && g_true_ms == stall_at) {
            g_true_ms += stall;
            if (g_true_ms >= total) break;
        }
        for (poll = 0; poll < 8; poll++)
            if (pace()) {
                ticks++;
                if (stall && g_true_ms >= stall_at + stall && g_true_ms < stall_at + stall + 40)
                    after++;
            }
    }
    n += put_str(line + n, "ticks=");
    n += put_num(line + n, ticks);
    n += put_str(line + n, " after_stall=");
    n += put_num(line + n, after);
    line[n++] = '\n';
    out(line, n);
    ExitProcess(0);
}

static u32 number(const char *s)
{
    u32 v = 0, base = 10;
    if (s[0] == '0' && (s[1] == 'x' || s[1] == 'X')) {
        base = 16;
        s += 2;
    }
    for (; *s; s++) {
        u32 d;
        if (*s >= '0' && *s <= '9') d = *s - '0';
        else if (*s >= 'a' && *s <= 'f') d = *s - 'a' + 10;
        else if (*s >= 'A' && *s <= 'F') d = *s - 'A' + 10;
        else break;
        v = v * base + d;
    }
    return v;
}

/* split the command line on spaces; a quoted first token (the exe) is skipped */
static int split(char *cl, char **argv, int max)
{
    int n = 0;
    while (*cl && n < max) {
        while (*cl == ' ') cl++;
        if (!*cl) break;
        if (*cl == '"') {
            argv[n++] = ++cl;
            while (*cl && *cl != '"') cl++;
        } else {
            argv[n++] = cl;
            while (*cl && *cl != ' ') cl++;
        }
        if (*cl) *cl++ = 0;
    }
    return n;
}

static int same(const char *a, const char *b)
{
    while (*a && *a == *b) { a++; b++; }
    return *a == 0 && *b == 0;
}

/* Every handle's buffer is one fixed allocation, made on its first `load`.
 * `reload` writes into the SAME allocation, so the base pointer the hook sees
 * does not change -- which is the whole point: the memo must be invalidated by
 * the buffer's own index entry, not by the address moving. */
#define BUFSZ 0x40000

static u32 read_into(const char *path, u8 *dst, u32 cap)
{
    HANDLE f = CreateFileA(path, GENERIC_READ, FILE_SHARE_READ, 0, OPEN_EXISTING, 0, 0);
    DWORD size, got;
    if (f == INVALID_HANDLE_VALUE)
        ExitProcess(2);
    size = GetFileSize(f, 0);
    if (size > cap)
        ExitProcess(2);
    if (!ReadFile(f, dst, size, &got, 0) || got != size)
        ExitProcess(2);
    CloseHandle(f);
    return size;
}

static void map_image(u32 handle, const char *path)
{
    u32 i;
    handle &= 15;
    if (!g_bases[handle])
        g_bases[handle] = (u8 *)VirtualAlloc(0, BUFSZ, MEM_COMMIT | MEM_RESERVE,
                                             PAGE_READWRITE);
    if (!g_bases[handle])
        ExitProcess(2);
    for (i = 0; i < BUFSZ; i++)
        g_bases[handle][i] = 0;
    read_into(path, g_bases[handle], BUFSZ);
}

static char g_out[1 << 20];
static u32 g_n;

static void flush(void)
{
    if (g_n)
        out(g_out, g_n);
    g_n = 0;
}

static void walk(u32 handle, u32 pc, u32 stop)
{
    u32 steps = 0;
    handle &= 15;
    g_n += put_str(g_out + g_n, "bytes=");
    while (pc != stop && steps < (1u << 16) && g_n + 32 < sizeof g_out) {
        u16 p = (u16)pc;
        u8 b = hook(handle, &p);
        g_out[g_n++] = "0123456789abcdef"[b >> 4];
        g_out[g_n++] = "0123456789abcdef"[b & 15];
        pc = p;
        steps++;
    }
    g_out[g_n++] = '\n';
    g_n += put_str(g_out + g_n, "pc=");
    g_n += put_num(g_out + g_n, pc);
    g_out[g_n++] = '\n';
    if (g_n + 64 > sizeof g_out)
        flush();
}

/* one command per line; see the banner */
static void script_mode(const char *path)
{
    static u8 buf[1 << 16];
    u32 size = read_into(path, buf, sizeof buf - 1);
    u32 i = 0;
    buf[size] = 0;
    while (i < size) {
        char *line = (char *)buf + i;
        char *argv[8];
        int argc;
        while (i < size && buf[i] != '\n') i++;
        if (i < size) buf[i++] = 0;
        {
            char *p = line;
            while (*p) { if (*p == '\r') *p = 0; p++; }
        }
        if (line[0] == '#' || line[0] == 0)
            continue;
        argc = split(line, argv, 8);
        if (argc == 0)
            continue;
        if (same(argv[0], "load") && argc == 3)
            map_image(number(argv[1]), argv[2]);
        else if (same(argv[0], "reload") && argc == 3)
            map_image(number(argv[1]), argv[2]);
        else if (same(argv[0], "walk") && argc == 4)
            walk(number(argv[1]), number(argv[2]), number(argv[3]));
        else if (same(argv[0], "fid"))
            ;                   /* v6 reads no file id; accepted, ignored */
        else
            ExitProcess(3);
    }
    flush();
    ExitProcess(0);
}

void _start(void)
{
    char *argv[8];
    int argc = split(GetCommandLineA(), argv, 8);
    u32 handle, pc, stop;
    if (argc == 6 && same(argv[1], "pace"))
        pace_mode(argv + 1);
    if (argc == 3 && same(argv[1], "script"))
        script_mode(argv[2]);
    if (argc != 6) {
        out("usage: hook_harness image fid handle start stop\n", 48);
        ExitProcess(2);
    }
    handle = number(argv[3]) & 15;
    pc = number(argv[4]);
    stop = number(argv[5]);
    map_image(handle, argv[1]);
    walk(handle, pc, stop);
    flush();
    ExitProcess(0);
}
