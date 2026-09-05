/* Runtime text overlay for dds.exe -- the byte-fetch hook.
 *
 * The interpreter reads every script byte through one routine,
 * FETCH(handle, &pc) at 0x438E50 (cdecl, returns the byte in al).  Its five
 * call sites are redirected here.  See giten/overlay.py for the rules and the
 * overlay.dat layout; this file and overlay.Model must agree byte for byte
 * (tests/test_overlay.py runs both).
 *
 * Built two ways:
 *   -DGAME     absolute engine addresses; linked at the cave's VA (hook.ld),
 *              no CRT, no relocations, first function = the hook.
 *   (harness)  tests/hook_harness.c supplies the engine's globals and the
 *              original fetch; the same logic runs as a native 32-bit exe.
 */
typedef unsigned char u8;
typedef unsigned short u16;
typedef unsigned int u32;

#ifdef GAME
typedef u8 (*fetch_fn)(u32 handle, u16 *pcp);
#define ORIG_FETCH ((fetch_fn)0x438E50)
#define FILEID (*(volatile u16 *)0x4911B0)
#define HANDLE_BASE(h) (*(u8 **)(0x47605C + (h) * 8))
typedef void *HANDLE;
typedef u32 dword;
typedef HANDLE(__attribute__((stdcall)) * CreateFileA_t)(const char *, u32, u32, void *, u32, u32, HANDLE);
typedef dword(__attribute__((stdcall)) * GetFileSize_t)(HANDLE, dword *);
typedef int(__attribute__((stdcall)) * ReadFile_t)(HANDLE, void *, dword, dword *, void *);
typedef void *(__attribute__((stdcall)) * VirtualAlloc_t)(void *, u32, u32, u32);
typedef int(__attribute__((stdcall)) * CloseHandle_t)(HANDLE);
typedef dword(__attribute__((stdcall)) * timeGetTime_t)(void);
typedef HANDLE(__attribute__((stdcall)) * GetModuleHandleA_t)(const char *);
typedef void *(__attribute__((stdcall)) * GetProcAddress_t)(HANDLE, const char *);
#define pCreateFileA (*(CreateFileA_t *)0x464074)
#define pGetFileSize (*(GetFileSize_t *)0x464078)
#define pReadFile (*(ReadFile_t *)0x464070)
#define pVirtualAlloc (*(VirtualAlloc_t *)0x4640A8)
#define pCloseHandle (*(CloseHandle_t *)0x464080)
#define pTimeGetTime (*(timeGetTime_t *)0x4641D8)
#define pGetModuleHandleA (*(GetModuleHandleA_t *)0x46411C)
#define pGetProcAddress (*(GetProcAddress_t *)0x46405C)
#define ENTRY __attribute__((section(".text.entry"), used))
#define EXPORT __attribute__((used))
#else
#include "hook_harness.h"
#define ENTRY
#define EXPORT
#endif

#define OVERLAY_NAME "overlay.dat"
#define FP_BYTES 0x400          /* the whole record index */

struct hdr { u32 magic, version, nfiles, reserved; };
struct dir { u16 fid, pad; u32 fp; u16 image_end, nspans; u32 spans_off; u16 ntails, pad2; u32 tails_off; };
struct span { u16 start, end, virt, len; u32 data_off; };

static u8 *ovl;                 /* the whole overlay.dat in memory */
static int state;               /* 0 not loaded, 1 loaded, -1 unavailable */
static struct dir *dirs;
static u32 ndirs;

/* two-entry cache: (handle, fid) -> directory entry (or 0 = no overlay) */
static u32 c_handle[2];
static u16 c_fid[2];
static struct dir *c_dir[2];
static int c_valid[2];
static int c_next;

static u32 fnv1a(const u8 *p, u32 n)
{
    u32 h = 0x811C9DC5u;
    while (n--)
        h = (h ^ *p++) * 0x01000193u;
    return h;
}

static void load(void)
{
    HANDLE f = pCreateFileA(OVERLAY_NAME, 0x80000000u, 1, 0, 3, 0x80, 0);
    dword size, got;
    struct hdr *h;
    state = -1;
    if (f == (HANDLE)-1)
        return;
    size = pGetFileSize(f, 0);
    if (size < sizeof(struct hdr) || size == 0xFFFFFFFFu) {
        pCloseHandle(f);
        return;
    }
    ovl = (u8 *)pVirtualAlloc(0, size, 0x3000, 4);
    if (!ovl) {
        pCloseHandle(f);
        return;
    }
    if (!pReadFile(f, ovl, size, &got, 0) || got != size) {
        pCloseHandle(f);
        return;
    }
    pCloseHandle(f);
    h = (struct hdr *)ovl;
    if (h->magic != 0x564F5447u /* "GTOV" */ || h->version != 3)
        return;
    dirs = (struct dir *)(ovl + sizeof(struct hdr));
    ndirs = h->nfiles;
    state = 1;
}

static struct dir *rebind(u32 handle, u16 fid)
{
    u32 i, fp;
    const u8 *base;
    for (i = 0; i < ndirs; i++)
        if (dirs[i].fid == fid)
            break;
    if (i == ndirs)
        return 0;                       /* no translation for this file id */
    base = HANDLE_BASE(handle);
    if (!base || *(const u16 *)base != 0x0400)
        return 0;                       /* not a script buffer: entry 0 always sits at 0x400 */
    fp = fnv1a(base, FP_BYTES);
    for (; i < ndirs; i++)
        if (dirs[i].fid == fid && dirs[i].fp == fp)
            return &dirs[i];
    return 0;                           /* a container we did not translate */
}

static struct dir *lookup(u32 handle, u16 fid)
{
    int k;
    for (k = 0; k < 2; k++)
        if (c_valid[k] && c_handle[k] == handle && c_fid[k] == fid)
            return c_dir[k];
    k = c_next;
    c_next ^= 1;
    c_handle[k] = handle;
    c_fid[k] = fid;
    c_dir[k] = rebind(handle, fid);
    c_valid[k] = 1;
    return c_dir[k];
}

/* the entry of a sorted, non-overlapping array whose [start, start+len)
 * holds pc, or 0.  For the spans array the served length is the head,
 * min(len, end - start); for the tails array start == virt and len == tail. */
static struct span *in_range(struct span *s, u32 n, u16 pc, int heads)
{
    int lo = 0, hi = (int)n - 1;
    while (lo <= hi) {
        int mid = (lo + hi) >> 1;
        u32 v = s[mid].start;
        u32 l = s[mid].len;
        if (heads && l > (u32)(s[mid].end - s[mid].start))
            l = s[mid].end - s[mid].start;
        if (pc < v)
            hi = mid - 1;
        else if (pc >= v + l)
            lo = mid + 1;
        else
            return &s[mid];
    }
    return 0;
}

ENTRY u8 hook(u32 handle, u16 *pcp)
{
    struct dir *d;
    struct span *s;
    u16 pc;
    u32 k, head;
    if (state == 0)
        load();
    if (state < 0)
        return ORIG_FETCH(handle, pcp);
    d = lookup(handle, FILEID);
    if (!d)
        return ORIG_FETCH(handle, pcp);
    pc = *pcp;
    if (pc >= d->image_end) {
        s = in_range((struct span *)(ovl + d->tails_off), d->ntails, pc, 0);
        if (!s)
            return ORIG_FETCH(handle, pcp);
        k = pc - s->start;
        *pcp = (k + 1 == s->len) ? s->end : (u16)(pc + 1);
        return ovl[s->data_off + k];
    }
    s = in_range((struct span *)(ovl + d->spans_off), d->nspans, pc, 1);
    if (!s)
        return ORIG_FETCH(handle, pcp);
    k = pc - s->start;
    head = s->end - s->start;
    if (head > s->len)
        head = s->len;
    if (k + 1 == s->len)
        *pcp = s->end;                  /* the English is done */
    else if (k + 1 == head)
        *pcp = s->virt;                 /* head done, the tail is virtual */
    else
        *pcp = (u16)(pc + 1);
    return ovl[s->data_off + k];
}

/* Frame pacing -- the game tick at 60 per second.
 *
 * The main loop (0x45104E) runs one update+render whenever timeGetTime has
 * advanced by a millisecond, so on anything faster than 1999 hardware -- or
 * whenever DirectDraw's Flip no longer blocks on the vertical retrace -- it
 * ticks up to 1000 times a second, and everything frame-counted (movement,
 * turning, menus, battle animation) runs that much too fast.  The builder
 * replaces the loop's "call timeGetTime; cmp eax,edi; jbe again" with
 * "call pace; test eax,eax; je again": a tick is due when this returns 1.
 *
 * Deadlines are kept in thirds of a millisecond and advanced by 50 per tick
 * (16 2/3 ms, exactly 60 Hz), so nothing drifts.  timeGetTime can step in
 * 15.6 ms increments on Windows 10/11 unless someone asks for finer
 * resolution, so the first call requests 1 ms via timeBeginPeriod; even
 * without it the accumulating deadline still averages 60 ticks a second.
 * After a stall (a window drag, a disk hitch) the deadline is re-based rather
 * than letting the game burst through the missed ticks. */
#define TICK3 50                /* one tick, in thirds of a millisecond */
#define STALL3 (3 * 250)        /* re-base if we are this far behind */

static u32 deadline3;
static int pace_state;          /* 0 first call, 1 running */

EXPORT int pace(void)
{
    u32 now3;
    int behind;
    if (pace_state == 0) {
        HANDLE m = pGetModuleHandleA("winmm.dll");
        if (m) {
            u32(__attribute__((stdcall)) * begin)(u32) = 0;
            *(void **)&begin = pGetProcAddress(m, "timeBeginPeriod");
            if (begin)
                begin(1);
        }
        deadline3 = pTimeGetTime() * 3;
        pace_state = 1;
    }
    now3 = pTimeGetTime() * 3;
    behind = (int)(now3 - deadline3);
    if (behind < 0)
        return 0;
    if (behind > STALL3)
        deadline3 = now3;
    deadline3 += TICK3;
    return 1;
}
