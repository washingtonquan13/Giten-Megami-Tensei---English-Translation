/* Native driver for giten/exe/hook.c -- freestanding Win32, no C runtime
 * (the mingw driver cannot link its CRT from a path with spaces).
 *
 *   hook_harness <image.bin> <fid> <handle> <start_pc> <stop_pc>
 *
 * Loads a runtime image (index + records, as overlay.image_bytes builds it)
 * as buffer <handle>, sets the current file id, and walks from start_pc until
 * the PC equals stop_pc, calling the hook for every byte exactly as the
 * engine's next_char would.  Prints the bytes seen as hex on one line, then
 * "pc=<final>".  overlay.dat is read from the current directory by the hook
 * itself, through the real Win32 imports.  Numbers are decimal or 0x-hex.
 */
#include "hook_harness.h"

u16 g_fileid;
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
    line[n++] = 't'; line[n++] = 'i'; line[n++] = 'c'; line[n++] = 'k'; line[n++] = 's'; line[n++] = '=';
    n += put_num(line + n, ticks);
    line[n++] = ' ';
    line[n++] = 'a'; line[n++] = 'f'; line[n++] = 't'; line[n++] = 'e'; line[n++] = 'r'; line[n++] = '_';
    line[n++] = 's'; line[n++] = 't'; line[n++] = 'a'; line[n++] = 'l'; line[n++] = 'l'; line[n++] = '=';
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

void _start(void)
{
    char *argv[8];
    int argc = split(GetCommandLineA(), argv, 8);
    HANDLE f;
    DWORD size, got;
    u32 fid, handle, pc, stop, steps = 0;
    static char line[1 << 18];
    u32 n = 0;
    if (argc == 6 && argv[1][0] == 'p' && argv[1][1] == 'a' && argv[1][2] == 'c' && argv[1][3] == 'e' && !argv[1][4])
        pace_mode(argv + 1);
    if (argc != 6) {
        out("usage: hook_harness image fid handle start stop\n", 48);
        ExitProcess(2);
    }
    f = CreateFileA(argv[1], GENERIC_READ, FILE_SHARE_READ, 0, OPEN_EXISTING, 0, 0);
    if (f == INVALID_HANDLE_VALUE)
        ExitProcess(2);
    size = GetFileSize(f, 0);
    fid = number(argv[2]);
    handle = number(argv[3]) & 15;
    pc = number(argv[4]);
    stop = number(argv[5]);
    g_bases[handle] = (u8 *)VirtualAlloc(0, size + 0x10000, MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE);
    if (!ReadFile(f, g_bases[handle], size, &got, 0) || got != size)
        ExitProcess(2);
    CloseHandle(f);
    g_fileid = (u16)fid;
    while (pc != stop && steps < (1u << 16) && n + 16 < sizeof line) {
        u16 p = (u16)pc;
        u8 b = hook(handle, &p);
        line[n++] = "0123456789abcdef"[b >> 4];
        line[n++] = "0123456789abcdef"[b & 15];
        pc = p;
        steps++;
    }
    line[n++] = '\n';
    line[n++] = 'p'; line[n++] = 'c'; line[n++] = '=';
    {
        char tmp[12];
        int k = 0;
        u32 v = pc;
        do { tmp[k++] = '0' + v % 10; v /= 10; } while (v);
        while (k) line[n++] = tmp[--k];
    }
    line[n++] = '\n';
    out(line, n);
    ExitProcess(0);
}
