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

/* The engine hands us the handle; indexing the handle table with it computes an
   address before there is anything to null-check, so the index is bounded
   first.  0x1000 entries keeps 0x47605C + h*8 inside .data (which ends at
   0x492B54); trace.S bounds the same table the same way.  Every absolute engine
   address this file touches is registered in giten/exe/engine_state.py with the
   guard it requires -- a pointer the engine legitimately nulls, dereferenced
   without a guard, is what crashed the tracer at a scene transition.
   Defined outside the GAME block so the test harness compiles it too. */
#define HANDLE_MAX 0x1000

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
#define ORIG_SCRIPT_STEP ((void (*)(void))0x43B5E0)
/* state 24 of the per-tick state machine at 0x00417160: the battle.  Its own
   sub-states each advance themselves by one, so calling it once is one battle
   phase, and calling it 60 times a second is why the party never gets a turn. */
#define ORIG_BATTLE_STEP ((u16 (*)(void))0x42B6A0)
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
struct dir { u16 fid, ci; u32 fp; u16 image_end, nspans; u32 spans_off; u16 ntails, pad2; u32 tails_off; };
/* `served` is how many bytes this entry answers from `start`.  It used to be
   derived as min(len, end - start), which meant the hook answered EVERY address
   inside a span -- including the ones branches jump to.  It is now built into
   overlay.dat, capped at the lowest branch target inside the span, so a jump
   falls through to the original file.  See giten/overlay.py. */
/* `start` and `virt` are where our model of the FILE put this span.  A merged
   buffer puts the record somewhere else, so neither is an address here: `rec`
   and `rec_off` say which record the span is in and where inside it, and the
   real address is the running buffer's own index entry plus `rec_off`.
   `jp_len` is a length rather than an end for the same reason.  `jp_hash` is
   FNV-1a over the Japanese those bytes hold, and a span is only served when the
   buffer still holds exactly that -- which is what makes a merge safe: a record
   another file replaced fails the hash and is dropped, not served at a
   plausible-looking address. */
struct span { u16 start, jp_len, virt, len, served, pad; u32 data_off;
              u16 rec, rec_off; u32 jp_hash; };

/* the largest nspans in the shipped overlay is 1 013 (m/MS0030 c0); an entry
   over this is refused whole rather than half-verified.  tests/test_overlay.py
   pins both numbers. */
#define MAX_SPANS 1024
#define MAX_TAILS 1024

/* How many entries may bind to one merged buffer.  m/MS6000 is only the shell:
   296 spans, the prompts and the approach menus.  The demon files merged onto
   it hold 7,647 spans, which is every line a demon says, and they are reachable
   only by serving one buffer from several entries.  Measured, at most 5 ever
   verify against one buffer. */
#define MAX_MERGE 8

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
/* per cached entry: how far the running buffer's end is from the one we planned
   against (virtual addresses move with it), and one bit per span/tail saying
   the buffer still holds the Japanese that span was built from. */
static int c_delta[2];
static u8 c_ok[2][MAX_SPANS / 8];
static u8 c_tok[2][MAX_TAILS / 8];
/* the merged case: several entries, each contributing the spans that verify */
static struct dir *c_multi[2][MAX_MERGE];
static int c_mdelta[2][MAX_MERGE];
static u32 c_nmulti[2];
/* A merged entry may hold spans the merge displaced, so the serve path has to
   check the one span a PC lands in.  The single-entry path keeps a bit per span
   instead; doing that here would need 2 x MAX_MERGE x MAX_SPANS/8 for spans and
   again for tails, about 4 KB -- and hook.ld puts .bss inside the blob, so it
   would be 4 KB of zeroes appended to the exe.  Consecutive fetches walk
   through the same span, so a one-entry memo costs eight bytes and makes it one
   hash per span rather than one per byte.  Cleared whenever a slot rebinds. */
static const struct span *c_last[2];
static int c_last_ok[2];

static u32 fnv1a(const u8 *p, u32 n)
{
    u32 h = 0x811C9DC5u;
    while (n--)
        h = (h ^ *p++) * 0x01000193u;
    return h;
}

/* the address the running buffer puts this span at */
static u32 span_start(const u16 *idx, const struct span *s)
{
    return (u32)idx[s->rec * 2] + s->rec_off;
}

/* where the engine resumes once the English is done: just past the Japanese,
   in the running buffer's coordinates */
static u16 span_end(const u16 *idx, const struct span *s)
{
    return (u16)(span_start(idx, s) + s->jp_len);
}

/* Does the buffer still hold the Japanese this span replaces?  Three ways it
   might not: the record is shorter here than the span needs, the span would run
   past the end of the image, or some other file supplied the record. */
static int span_holds(const u16 *idx, const u8 *base, u32 end, const struct span *s)
{
    u32 off, ln, lo;
    if (!s->jp_hash || s->rec > 0xFF)
        return 0;
    off = idx[s->rec * 2];
    ln = idx[s->rec * 2 + 1];
    lo = off + s->rec_off;
    if ((u32)s->rec_off + s->jp_len > ln || lo + s->jp_len > end)
        return 0;
    return fnv1a(base + lo, s->jp_len) == s->jp_hash;
}

static void mark(u8 *bits, u32 n, const u16 *idx, const u8 *base, u32 end,
                 struct span *sp, u32 count)
{
    u32 i;
    for (i = 0; i < n; i++)
        bits[i] = 0;
    for (i = 0; i < count; i++)
        if (span_holds(idx, base, end, &sp[i]))
            bits[i >> 3] |= (u8)(1u << (i & 7));
}

static int bit(const u8 *bits, u32 i)
{
    return (bits[i >> 3] >> (i & 7)) & 1;
}

/* span_holds() for the merged path, memoised on the last span asked about. */
static int span_ok(int slot, const u16 *idx, const u8 *base, u32 end,
                   const struct span *s)
{
    if (c_last[slot] != s) {
        c_last[slot] = s;
        c_last_ok[slot] = span_holds(idx, base, end, s);
    }
    return c_last_ok[slot];
}

/* Does this entry have anything to say about the buffer in front of us?
 *
 * ANY span that verifies is enough.  This used to demand that *every* span
 * verify, on the reasoning that a file in the merge cannot fail one -- but
 * 0x0043ABC0 lets a later merged file REPLACE an earlier file's record by id,
 * so a file that is in the merge fails too, and the all-or-nothing rule then
 * discarded the hundred-odd other spans of English that had verified.  Measured
 * against the merges et/ET0007 names, slot 0 alone went from 2 646 spans bound
 * to 3 435, and seven of the twenty-five demon rows from about 3 to about 108.
 *
 * Relaxing it cannot serve a span differently: span_holds() is unchanged and is
 * still consulted before any byte is served (merged_fetch).  It can only add
 * spans whose Japanese is present and hashes to what we translated.
 */
static int entry_fits(struct dir *d, const u16 *idx, const u8 *base, u32 end)
{
    struct span *sp = (struct span *)(ovl + d->spans_off);
    u32 i;
    if (!d->nspans || d->nspans > MAX_SPANS)
        return 0;
    for (i = 0; i < d->nspans; i++)
        if (span_holds(idx, base, end, &sp[i]))
            return 1;
    return 0;
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
    if (h->magic != 0x564F5447u /* "GTOV" */ || h->version != 5)
        return;
    dirs = (struct dir *)(ovl + sizeof(struct hdr));
    ndirs = h->nfiles;
    state = 1;
}

/* The runtime image's own end: the record index is 256 entries of
   {u16 offset, u16 length}, so the last one stops where the buffer stops.
   Four bytes, and it needs no directory entry -- which is the point: it is
   what lets the hook refuse an out-of-bounds read for a file it cannot
   identify. */
static u32 image_end_of(const u8 *base)
{
    const u16 *last = (const u16 *)(base + 255 * 4);
    return (u32)last[0] + last[1];
}

static const u8 *script_buffer(u32 handle)
{
    const u8 *base;
    if (handle >= HANDLE_MAX)
        return 0;                       /* out of the table: not ours to read */
    base = HANDLE_BASE(handle);
    if (!base || *(const u16 *)base != 0x0400)
        return 0;                       /* not a script buffer: entry 0 always sits at 0x400 */
    return base;
}

/* Which directory entry describes the buffer behind `handle`?
 *
 * `fid` is the engine's current-file global (0x4911B0), and it is written when
 * a script is LOADED, not on every context switch.  Several scripts are
 * resident at once and the interpreter runs whichever its context points at,
 * so while it runs an earlier one the global still names the file loaded most
 * recently.  Requiring both to agree is what made this return 0 -- and a 0
 * here means the hook hands the address to ORIG_FETCH, which for a virtual PC
 * reads past the end of the buffer.  Measured, from the 2026-09-07 crash dump:
 * FILEID said 0x00DD (the battle script) while the program counter was 0x58EB,
 * an address this overlay invented for m/MS001F, whose image ends at 0x4BA7.
 *
 * So the fingerprint is tried on its own when the pair fails.  It identifies
 * the buffer by its own contents and cannot go stale.  It is only accepted
 * when exactly one entry matches: ten fingerprints in the corpus are shared,
 * and six of those groups have genuinely different images (identical record
 * layouts, different content), so a lone fingerprint is not always an answer.
 * Those keep the old behaviour, and the guard in hook() keeps them safe.
 */
static struct dir *rebind(u32 handle, u16 fid)
{
    u32 i, fp;
    const u8 *base = script_buffer(handle);
    struct dir *only = 0;
    if (!base)
        return 0;
    fp = fnv1a(base, FP_BYTES);
    for (i = 0; i < ndirs; i++)
        if (dirs[i].fid == fid && dirs[i].fp == fp)
            return &dirs[i];            /* both agree: no ambiguity possible */
    for (i = 0; i < ndirs; i++)
        if (dirs[i].fp == fp) {
            if (only)
                return 0;               /* two files hash alike: no answer */
            only = &dirs[i];
        }
    if (only)
        return only;
    /* A demon-conversation buffer.  The engine builds it by merging m/MS6000
       with up to four more files (0x0040EB70) and reports it as 0xE0 + slot,
       which no filename maps to and whose index hashes to nothing we hold.
       m/MS6000 is always the base and slot == container, so that is the entry;
       which of its spans the merge actually left in place is decided per span
       by span_holds, not here. */
    if (fid >= 0xE0 && fid <= 0xEF)
        for (i = 0; i < ndirs; i++)
            if (dirs[i].fid == 0x6000 && dirs[i].ci == (u16)(fid - 0xE0))
                return &dirs[i];
    return 0;
}

/* Returns the cache slot, not the entry: the caller needs the slot's delta and
   its verification bits, and recomputing them per fetch would mean hashing
   every span on every byte. */
static int lookup(u32 handle, u16 fid)
{
    const u8 *base;
    const u16 *idx;
    u32 end;
    struct dir *d;
    int k;
    for (k = 0; k < 2; k++)
        if (c_valid[k] && c_handle[k] == handle && c_fid[k] == fid)
            return k;
    k = c_next;
    c_next ^= 1;
    c_handle[k] = handle;
    c_fid[k] = fid;
    c_valid[k] = 1;
    c_dir[k] = 0;
    c_delta[k] = 0;
    c_nmulti[k] = 0;
    c_last[k] = 0;              /* the memo belongs to the buffer, not the slot */
    c_last_ok[k] = 0;
    base = script_buffer(handle);
    if (fid >= 0xE0 && fid <= 0xEF) {
        /* A demon-conversation buffer.  dirs are in file-id order, and the
           first entry to claim an address keeps it -- two addresses in the
           corpus are claimed twice, by two correct translations of the same
           Japanese, so this only has to be repeatable. */
        u32 i, cursor;
        if (!base)
            return k;
        idx = (const u16 *)base;
        end = image_end_of(base);
        /* Each bound entry needs its OWN virtual window.  They all planned
           their tails from their own image end, so handing them the same base
           makes several entries answer the same virtual address and a fetch
           there is ambiguous -- the C conformance test caught exactly that.
           Stacking the windows keeps them disjoint. */
        cursor = end;
        for (i = 0; i < ndirs && c_nmulti[k] < MAX_MERGE; i++) {
            struct span *tl;
            u32 used = 0, j;
            if (dirs[i].ci != (u16)(fid - 0xE0))
                continue;
            if (!entry_fits(&dirs[i], idx, base, end))
                continue;
            /* Reserve only what this entry can actually use.  Tails are sorted
               by virtual address, so the last one that verifies is the highest;
               sizing from the last tail regardless (which is what this did when
               every span was known to verify) over-reserves, and with more
               entries binding that reaches the PC limit sooner and stops the
               loop early.  overlay.bind() sizes the window the same way. */
            tl = (struct span *)(ovl + dirs[i].tails_off);
            for (j = dirs[i].ntails; j-- > 0; )
                if (span_holds(idx, base, end, &tl[j])) {
                    used = (u32)tl[j].start + tl[j].served - dirs[i].image_end;
                    break;
                }
            if (cursor + used > 0x10000u)
                break;                      /* no room left below the PC limit */
            c_mdelta[k][c_nmulti[k]] = (int)cursor - (int)dirs[i].image_end;
            c_multi[k][c_nmulti[k]] = &dirs[i];
            c_nmulti[k]++;
            cursor += used;
        }
        return k;
    }
    d = rebind(handle, fid);
    if (!d)
        return k;
    if (d->nspans > MAX_SPANS || d->ntails > MAX_TAILS)
        return k;                       /* too big to verify: serve nothing */
    if (!base)
        return k;
    idx = (const u16 *)base;
    end = image_end_of(base);
    c_delta[k] = (int)end - (int)d->image_end;
    mark(c_ok[k], sizeof c_ok[k], idx, base, end,
         (struct span *)(ovl + d->spans_off), d->nspans);
    mark(c_tok[k], sizeof c_tok[k], idx, base, end,
         (struct span *)(ovl + d->tails_off), d->ntails);
    c_dir[k] = d;
    return k;
}

/* the entry of a sorted, non-overlapping array whose [start, start+served)
 * holds pc, or 0.  Both arrays carry `served`, so this needs to know nothing
 * about which one it is walking -- the head/tail distinction used to live here
 * as a flag and a min(), and getting that min() wrong is what made the hook
 * answer branch targets. */
static struct span *in_range(const u16 *idx, struct span *s, u32 n, u16 pc)
{
    int lo = 0, hi = (int)n - 1;
    while (lo <= hi) {
        int mid = (lo + hi) >> 1;
        u32 v = span_start(idx, &s[mid]);
        if (pc < v)
            hi = mid - 1;
        else if (pc >= v + (u32)s[mid].served)
            lo = mid + 1;
        else
            return &s[mid];
    }
    return 0;
}

/* the same search over the virtual side.  Tails sit above the image end, and
   the image end moves when a merge makes the buffer longer, so every virtual
   address shifts by the same `delta` -- which is what keeps them from landing
   on real records that only exist in the merged buffer. */
static struct span *in_tail(struct span *s, u32 n, int delta, u16 pc)
{
    int lo = 0, hi = (int)n - 1;
    while (lo <= hi) {
        int mid = (lo + hi) >> 1;
        u32 v = (u32)((int)s[mid].start + delta);
        if (pc < v)
            hi = mid - 1;
        else if (pc >= v + (u32)s[mid].served)
            lo = mid + 1;
        else
            return &s[mid];
    }
    return 0;
}

/* ORIG_FETCH, unless that would read past the end of the buffer.
 *
 * A program counter at or above the image end exists for exactly one reason:
 * this overlay put it there, because some line's English did not fit where its
 * Japanese was.  The original fetch knows nothing about that -- it indexes the
 * script buffer and reads -- so handing it such an address reads memory the
 * buffer does not own.  On 2026-09-07 that was an access violation at
 * 0x00438E75 (pc 0x58EB against m/MS001F, whose image ends at 0x4BA7); on the
 * run before it, the same fall-through landed on mapped bytes instead and the
 * interpreter looped on `01 01` pool calls until the player gave up.  Same
 * bug, and which symptom you get depends on what happens to be mapped.
 *
 * So: refuse.  0xFF is returned because it is unassigned in cp932 and so is
 * never text -- the same reason overlay.py will not serve a span containing
 * one -- and it is what the engine's own list structures terminate on.  This
 * is a chosen degradation, not a known-correct value: by the time we are here
 * the run is already wrong, and the only thing being promised is that we do
 * not read memory we do not own.  The PC still advances, so nothing spins.
 */
static u8 passthrough(u32 handle, u16 *pcp)
{
    const u8 *base = script_buffer(handle);
    if (base && *pcp >= image_end_of(base)) {
        *pcp = (u16)(*pcp + 1);
        return 0xFF;
    }
    return ORIG_FETCH(handle, pcp);
}

/* One fetch out of a merged buffer.  Returns 1 and sets *out when one of the
   bound entries answers this address, 0 when none does. */
static int merged_fetch(int slot, const u8 *base, u16 *pcp, u8 *out)
{
    const u16 *idx = (const u16 *)base;
    u32 end = image_end_of(base);
    u16 pc = *pcp;
    u32 i, k;
    for (i = 0; i < c_nmulti[slot]; i++) {
        struct dir *d = c_multi[slot][i];
        int delta = c_mdelta[slot][i];
        struct span *s, *sp;
        if (pc >= end) {
            sp = (struct span *)(ovl + d->tails_off);
            s = in_tail(sp, d->ntails, delta, pc);
            /* A tail is packed with its span's rec, rec_off and jp_hash, so the
               same test decides both -- an English tail must not be served when
               the Japanese it belongs to is not the Japanese in the buffer. */
            if (!s || !span_ok(slot, idx, base, end, s))
                continue;
            k = pc - (u32)((int)s->start + delta);
            *pcp = (k + 1 == s->len) ? span_end(idx, s) : (u16)(pc + 1);
            *out = ovl[s->data_off + k];
            return 1;
        }
        sp = (struct span *)(ovl + d->spans_off);
        s = in_range(idx, sp, d->nspans, pc);
        if (!s || !span_ok(slot, idx, base, end, s))
            continue;
        k = pc - span_start(idx, s);
        if (k + 1 == s->len)
            *pcp = span_end(idx, s);
        else if (k + 1 == s->served)
            *pcp = (u16)((int)s->virt + delta);
        else
            *pcp = (u16)(pc + 1);
        *out = ovl[s->data_off + k];
        return 1;
    }
    return 0;
}

ENTRY u8 hook(u32 handle, u16 *pcp)
{
    struct dir *d;
    struct span *s, *sp;
    const u8 *base;
    const u16 *idx;
    u16 pc;
    u32 k, end;
    int slot;
    if (state == 0)
        load();
    if (state < 0)
        return ORIG_FETCH(handle, pcp);
    slot = lookup(handle, FILEID);
    base = script_buffer(handle);
    if (!base)
        return ORIG_FETCH(handle, pcp);
    if (c_nmulti[slot]) {
        u8 b;
        if (merged_fetch(slot, base, pcp, &b))
            return b;
        pc = *pcp;
        return (pc >= image_end_of(base)) ? passthrough(handle, pcp)
                                          : ORIG_FETCH(handle, pcp);
    }
    d = c_dir[slot];
    if (!d)
        return passthrough(handle, pcp);
    idx = (const u16 *)base;
    end = image_end_of(base);
    pc = *pcp;
    if (pc >= end) {
        sp = (struct span *)(ovl + d->tails_off);
        s = in_tail(sp, d->ntails, c_delta[slot], pc);
        if (!s || !bit(c_tok[slot], (u32)(s - sp)))
            return passthrough(handle, pcp);   /* a virtual PC in no tail of ours */
        k = pc - (u32)((int)s->start + c_delta[slot]);
        *pcp = (k + 1 == s->len) ? span_end(idx, s) : (u16)(pc + 1);
        return ovl[s->data_off + k];
    }
    sp = (struct span *)(ovl + d->spans_off);
    s = in_range(idx, sp, d->nspans, pc);
    if (!s || !bit(c_ok[slot], (u32)(s - sp)))
        return ORIG_FETCH(handle, pcp);
    k = pc - span_start(idx, s);
    if (k + 1 == s->len)
        *pcp = span_end(idx, s);        /* the English is done */
    else if (k + 1 == s->served)
        *pcp = (u16)((int)s->virt + c_delta[slot]);  /* head done, the tail is virtual */
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
#ifndef TICK3
#define TICK3 50                /* one tick, in thirds of a millisecond */
#endif
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


/* Background-script pacing -- how fast scripted actors take their turns.
 *
 * 0x401980 runs, once per game tick:
 *
 *     0x402740   the popup countdown        (one decrement)
 *     0x43B5E0   the background script      (see below)
 *     0x43BBC0   a script-visible stopwatch (one increment)
 *
 * 0x43B5E0 saves the interpreter context, points it at the background script
 * named by (ds:0x469828, ds:0x46982C), and calls 0x4390F0 -- which is
 * `do { exec_token(...) } while (result >= 0)`, i.e. run this actor until it
 * blocks -- then restores the context.  So the game tick IS the rate at which
 * scripted actors act, and at 60 Hz the enemies in a battle take turns faster
 * than a person can answer: the player gets one party member in before the
 * other side has moved again.
 *
 * Lowering the loop rate instead does not work.  It is one clock for the whole
 * game, so 30 Hz and 40 Hz fix the battle and make walking around unbearable
 * (measured, not guessed).  Dividing here separates the two: the loop keeps
 * ticking at 60 for movement, drawing and input, and only the script's turn
 * rate comes down.
 *
 * SCRIPT_DIV of 1 is the original behaviour and is what the release exe gets;
 * the builder only redirects the call site when it is greater.
 */
#ifndef SCRIPT_DIV
#define SCRIPT_DIV 1
#endif

/* How many ticks one battle phase takes.  1 is the original behaviour and is
   what the release exe gets; the builder only redirects the call site when it is
   greater.  Combat is the only thing affected: the field, the menus and the
   battle command UI are separate states and still run every tick. */
#ifndef BATTLE_DIV
#define BATTLE_DIV 1
#endif

/* GAME only: the harness has no engine to call through to, and nothing in the
   overlay's semantics depends on this, so there is nothing for it to test. */
#ifdef GAME
static u32 step_phase;

EXPORT void script_step(void)
{
    if (++step_phase < SCRIPT_DIV)
        return;
    step_phase = 0;
    ORIG_SCRIPT_STEP();
}

static u32 battle_phase;

/* Skipping returns 0, which is what 0x0042B6A0 itself returns on its ordinary
   exit (`xor ax, ax`).  The caller, 0x004019D0, only treats -1 specially, so a
   skipped tick reads to it as "the battle state did not change" -- which is
   exactly what happened. */
EXPORT u16 battle_step(void)
{
    if (++battle_phase < BATTLE_DIV)
        return 0;
    battle_phase = 0;
    return ORIG_BATTLE_STEP();
}
#endif
