/* Native driver for giten/exe/hook.c.
 *
 *   hook_harness <image.bin> <fid> <handle> <start_pc> <stop_pc>
 *
 * Loads a runtime image (index + records, as overlay.image_bytes builds it)
 * as buffer <handle>, sets the current file id, and walks from start_pc until
 * the PC equals stop_pc, calling the hook for every byte exactly as the
 * engine's next_char would.  Prints the bytes seen as hex on one line, then
 * "pc=<final>".  overlay.dat is read from the current directory by the hook
 * itself, through the real Win32 imports.
 */
#include <stdio.h>
#include <stdlib.h>
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

int main(int argc, char **argv)
{
    FILE *f;
    long n;
    u32 fid, handle, pc, stop, steps = 0;
    if (argc != 6) {
        fprintf(stderr, "usage: hook_harness image fid handle start stop\n");
        return 2;
    }
    f = fopen(argv[1], "rb");
    if (!f) {
        perror(argv[1]);
        return 2;
    }
    fseek(f, 0, SEEK_END);
    n = ftell(f);
    fseek(f, 0, SEEK_SET);
    fid = strtoul(argv[2], 0, 0);
    handle = strtoul(argv[3], 0, 0);
    pc = strtoul(argv[4], 0, 0);
    stop = strtoul(argv[5], 0, 0);
    g_bases[handle] = (u8 *)malloc(n + 0x10000);
    if (fread(g_bases[handle], 1, n, f) != (size_t)n)
        return 2;
    fclose(f);
    g_fileid = (u16)fid;
    while (pc != stop && steps < (1u << 20)) {
        u16 p = (u16)pc;
        u8 b = hook(handle, &p);
        printf("%02x", b);
        pc = p;
        steps++;
    }
    printf("\npc=%u\n", pc);
    return 0;
}
