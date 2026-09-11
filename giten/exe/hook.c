/* Runtime text overlay for dds.exe -- the byte-fetch hook.
 *
 * The interpreter reads every script byte through one routine,
 * FETCH(handle, &pc) at 0x438E50 (cdecl, returns the byte in al).  Its five
 * call sites are redirected here.  See giten/overlay.py for the rules and the
 * overlay.dat layout; this file and overlay.Model must agree byte for byte
 * (tests/test_overlay.py runs both).
 *
 * CONTENT ADDRESSING (v6).  This hook never asks which FILE a buffer is.  It
 * finds the record the program counter is in, from the buffer's own index,
 * hashes that record's bytes, and looks the triple
 *
 *     (record id, record length, FNV-1a of the record's bytes)
 *
 * up in one flat table.  If the Japanese in front of us is the Japanese we
 * translated, we serve the English; if it is not, we serve nothing.  Every
 * earlier version identified the buffer instead -- by the engine's current-file
 * global, by a fingerprint of the record index, by a cached (handle, fid)
 * binding -- and every one of those goes stale, because the engine reuses one
 * handle and one pseudo file id (0x7F) for every shop, terminal and bar on a
 * map and rebuilds the demon merge under 0xE0 for every demon.  The hook then
 * served the previous script's English at the new script's addresses.
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
#define OVERLAY_VERSION 6

struct hdr { u32 magic, version, nrecs, nspans; };

/* One record CONTENT.  The table is sorted by (rec_id, jp_len, jp_hash), so
   this is binary-searchable, and nothing in it names a file. */
struct rec { u16 rec_id, jp_len; u32 jp_hash, span_first; u16 nspans, tail_total; };

/* One translated span, addressed inside its record.  `served` is how many bytes
   it answers from `rec_off`; the hook never answers `rec_off + served` or
   beyond.  It is stored rather than derived as min(len, jp_len), because a span
   some branch jumps into stops at that branch's target so the jump reads the
   original file.  `virt_off` is where the tail sits above the buffer's own
   image end. */
struct span { u16 rec_off, jp_len, served, len, virt_off, pad; u32 data_off; };

static u8 *ovl;                 /* the whole overlay.dat in memory */
static int state;               /* 0 not loaded, 1 loaded, -1 unavailable */
static struct rec *recs;
static struct span *spans;
static u32 nrecs;

/* The memo, and the ONLY thing remembered between fetches.
 *
 * A slot is valid only when its handle and base pointer still match and the
 * buffer's own index entry for the memoised record is still (off, len) -- which
 * is re-checked on every fetch, never trusted.  That is the difference between
 * this and the (handle, fid) cache it replaces: this one cannot outlive the
 * buffer contents it describes.
 *
 * Four slots, because several buffers are resident at once: a pool call
 * (opcodes 01-08, the only control transfer our own English may contain)
 * switches to the pool file's buffer and returns, so both memos have to
 * survive it.  `entry` may be a null pointer, meaning "this record is not
 * translated" -- memoised too, so an untranslated record costs one hash and
 * not one per byte. */
#define MEMO_SLOTS 4
static u32 m_handle[MEMO_SLOTS];
static const u8 *m_base[MEMO_SLOTS];
static u16 m_rec[MEMO_SLOTS], m_off[MEMO_SLOTS], m_len[MEMO_SLOTS];
static const struct rec *m_entry[MEMO_SLOTS];
static u8 m_used[MEMO_SLOTS];
static u32 m_next;

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
    if (h->magic != 0x564F5447u /* "GTOV" */ || h->version != OVERLAY_VERSION)
        return;
    recs = (struct rec *)(ovl + sizeof(struct hdr));
    nrecs = h->nrecs;
    spans = (struct span *)(recs + nrecs);
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

/* Which record holds `pc`?  Offsets are non-decreasing in id (an absent record
   occupies one byte at its slot), so the last entry at or below pc is the only
   candidate, and it holds pc only if pc is inside its length. */
static int find_record(const u16 *idx, u32 pc)
{
    int lo = 0, hi = 255, best = -1;
    while (lo <= hi) {
        int mid = (lo + hi) >> 1;
        if ((u32)idx[mid * 2] <= pc) {
            best = mid;
            lo = mid + 1;
        } else {
            hi = mid - 1;
        }
    }
    if (best < 0)
        return -1;
    if (pc >= (u32)idx[best * 2] + idx[best * 2 + 1])
        return -1;
    return best;
}

/* The table entry for one record CONTENT, or 0.  Sorted by (rec_id, jp_len,
   jp_hash), which is exactly the order overlay.build() writes. */
static const struct rec *find_entry(u16 rec_id, u16 jp_len, u32 hash)
{
    int lo = 0, hi = (int)nrecs - 1;
    while (lo <= hi) {
        int mid = (lo + hi) >> 1;
        const struct rec *r = &recs[mid];
        if (rec_id != r->rec_id) {
            if (rec_id < r->rec_id) hi = mid - 1; else lo = mid + 1;
        } else if (jp_len != r->jp_len) {
            if (jp_len < r->jp_len) hi = mid - 1; else lo = mid + 1;
        } else if (hash != r->jp_hash) {
            if (hash < r->jp_hash) hi = mid - 1; else lo = mid + 1;
        } else {
            return r;
        }
    }
    return 0;
}

static int memo_valid(int slot, u32 handle, const u8 *base, const u16 *idx)
{
    u32 r;
    if (!m_used[slot] || m_handle[slot] != handle || m_base[slot] != base)
        return 0;
    r = m_rec[slot];
    return idx[r * 2] == m_off[slot] && idx[r * 2 + 1] == m_len[slot];
}

/* The slot this handle owns, or a fresh one.  A reused slot is marked unused
   first, so nothing can read it as valid before it is filled. */
static int memo_slot(u32 handle)
{
    int i;
    for (i = 0; i < MEMO_SLOTS; i++)
        if (m_used[i] && m_handle[i] == handle)
            return i;
    i = (int)m_next;
    m_next = (m_next + 1) & (MEMO_SLOTS - 1);
    m_used[i] = 0;
    return i;
}

/* The table entry for the record `rec` of this buffer, memoised.  The hash is
   the cost this exists to pay once per record transition rather than per byte;
   everything else is four u16 compares. */
static const struct rec *entry_for(int slot, u32 handle, const u8 *base,
                                   const u16 *idx, int rec)
{
    u16 off = idx[rec * 2], ln = idx[rec * 2 + 1];
    if (memo_valid(slot, handle, base, idx) && m_rec[slot] == (u16)rec)
        return m_entry[slot];
    m_handle[slot] = handle;
    m_base[slot] = base;
    m_rec[slot] = (u16)rec;
    m_off[slot] = off;
    m_len[slot] = ln;
    m_entry[slot] = find_entry((u16)rec, ln, fnv1a(base + off, ln));
    m_used[slot] = 1;
    return m_entry[slot];
}

/* the span of this record whose [rec_off, rec_off + served) holds `k`, or 0.
   Spans are sorted by rec_off and do not overlap. */
static struct span *find_span(struct span *s, u32 n, u32 k)
{
    int lo = 0, hi = (int)n - 1;
    while (lo <= hi) {
        int mid = (lo + hi) >> 1;
        if (k < (u32)s[mid].rec_off)
            hi = mid - 1;
        else if (k >= (u32)s[mid].rec_off + s[mid].served)
            lo = mid + 1;
        else
            return &s[mid];
    }
    return 0;
}

/* the same search over the virtual side.  `virt_off` is non-decreasing in the
   same array order -- a span whose English fits in place still carries the
   cursor, so it is an empty range the search steps over rather than a zero that
   would break the ordering. */
static struct span *find_tail(struct span *s, u32 n, u32 k)
{
    int lo = 0, hi = (int)n - 1;
    while (lo <= hi) {
        int mid = (lo + hi) >> 1;
        u32 tail = (u32)s[mid].len - s[mid].served;
        if (k < (u32)s[mid].virt_off)
            hi = mid - 1;
        else if (k >= (u32)s[mid].virt_off + tail)
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

ENTRY u8 hook(u32 handle, u16 *pcp)
{
    const struct rec *e;
    struct span *sp, *s;
    const u8 *base;
    const u16 *idx;
    u16 pc;
    u32 k, end, off;
    int slot, rec;
    if (state == 0)
        load();
    if (state < 0)
        return ORIG_FETCH(handle, pcp);
    base = script_buffer(handle);
    if (!base)
        return ORIG_FETCH(handle, pcp);
    idx = (const u16 *)base;
    end = image_end_of(base);
    pc = *pcp;
    slot = memo_slot(handle);
    if (pc < end) {
        rec = find_record(idx, pc);
        if (rec < 0)
            return ORIG_FETCH(handle, pcp);     /* the index itself, or a gap */
        e = entry_for(slot, handle, base, idx, rec);
        if (!e)
            return ORIG_FETCH(handle, pcp);     /* this record is not translated */
        off = idx[rec * 2];
        sp = spans + e->span_first;
        s = find_span(sp, e->nspans, pc - off);
        if (!s)
            return ORIG_FETCH(handle, pcp);
        k = pc - off - s->rec_off;
        if (k + 1 == s->len)
            *pcp = (u16)(off + s->rec_off + s->jp_len);   /* the English is done */
        else if (k + 1 == s->served)
            *pcp = (u16)(end + s->virt_off);              /* in place done, tail is virtual */
        else
            *pcp = (u16)(pc + 1);
        return ovl[s->data_off + k];
    }
    /* A virtual PC names no record on its own -- every record's tails start at
       the same image end -- so it is resolved through the memo, which is the
       record the fetch that created this address was in.  That holds because no
       opcode the codec may put inside a span transfers control within this
       handle: a pool call switches buffers, and that buffer has its own slot. */
    if (!memo_valid(slot, handle, base, idx))
        return passthrough(handle, pcp);
    e = m_entry[slot];
    if (!e)
        return passthrough(handle, pcp);
    sp = spans + e->span_first;
    s = find_tail(sp, e->nspans, pc - end);
    if (!s)
        return passthrough(handle, pcp);
    k = s->served + (pc - end - s->virt_off);
    if (k + 1 == s->len)
        *pcp = (u16)((u32)m_off[slot] + s->rec_off + s->jp_len);
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
