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

u8 orig_fetch(u32 handle, u16 *pcp)
{
    u8 *base = g_bases[handle];
    u16 pc = *pcp;
    *pcp = (u16)(pc + 1);
    return base ? base[pc] : 0;
}

static void out(const char *s, u32 n)
{
    DWORD w;
    WriteFile(GetStdHandle(STD_OUTPUT_HANDLE), s, n, &w, 0);
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
