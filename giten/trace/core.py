"""Decode and diff interpreter traces written by the dev exe's ``.trc`` hook.

A trace is a flat file of fixed-size records (see ``exe/trace.S``).  v5 carries
an 8-byte ``"GTRC"`` header and 30-byte records::

    u16 file, u16 rec, u16 pc, u16 ch, i16 r, u8 capflag, u8 caplen,
    u16 idx_off, u16 idx_len, u16 pc0, u16 flags, u16 state,
    u32 rec_hash, u16 image_end, u16 handle

v1 is headerless with 16-byte records (no ``pc0``/``flags``); v2 adds those, v3
adds ``state``, v4 adds ``rec_hash`` and ``image_end``, v5 adds ``handle`` and
changes what ``rec``/``idx``/``rec_hash`` describe.  All of them decode, since
the traces taken before 2026-09-06 are still the oracle the opcode model is
checked against -- but :func:`verify` needs v4 or better, because overlay v6
keys a translated span on the CONTENT of the record it lives in and nothing
older logs that.  ``rec_hash`` is FNV-1a over the record the interpreter is
standing in; ``image_end`` is the buffer's own ``idx[255].off + idx[255].len``,
the same four bytes the hook reads to tell a real program counter from a
virtual one.

**v5: the record is the one the program counter is in.**  Through v4 the hook
took the record id from ``ds:RECID``, an engine global written on *load*, while
``hook.c`` found it by searching the live index for the record containing the
program counter.  The oracle therefore answered a different question than the
thing it was checking, and on the 2026-09-11 Roppongi session that produced 165
false findings, 450 events reported unverified and 611 served events charged to
the wrong record.  v5 scans the index exactly as ``hook.c`` does and says which
answer it gave: ``REC_FROM_PC`` means the scan found the record, its absence
means ``rec`` is still the stale global.  ``VIRTUAL`` means the program counter
was at or above the image end, where it names no record at all -- those are
attributed offline to the last real fetch on the same ``handle``, which is why
the handle is logged.

``decode`` maps each record back to the script: the hook logs after exec_token
returns, so ``pc`` is the byte after the whole token (operands included), and
the token is the one that *ends* there in the runtime image; the runtime
image is ``records.bases`` over the loaded container.  From the token we get the
span index, the same numbering the tables use -- so a trace line names a table
row.

``diff`` compares two traces for the same route on different builds.  Byte
offsets differ between a Japanese and an English build, so records are first
normalised to *structural events* ``(file, rec, anchor, kind)`` where ``anchor``
is the number of non-inline opcodes before the token (the notion ``audit`` keys
on) and runs of text collapse to one ``TEXT`` event.  Two builds that run the
same script produce the same event sequence; the first difference is the bug,
and the record's ``r`` and ``caplen`` say which kind (``r == -1``: page full and
the interpreter loop exited; ``caplen`` near 255: capture-buffer overflow).

What this does not know
-----------------------
* Which *container* of a multi-container file (``m/MS6xxx``, ``et/ID*``) is
  loaded: the record carries no container index.  Container 0 is assumed and
  the self-check flags a mismatch.
* Whether ``FILEID``/``RECID`` are current on every path (they are written at
  two sites).  The self-check compares the logged ``ch`` with the bytes at the
  decoded offset; a run of mismatches means the globals were stale there.

Closed in v2: a token that *ended* a script used to be unplaceable.  The engine
clears the context when a script ends, and v1 read ``file``/``rec``/``pc`` and
the index entry only after ``exec_token`` returned -- so all four came back
zero.  That was 106 of 18,683 events on the traced routes, a hole in the oracle
rather than in the model.  v2 snapshots them before the call and adds ``pc0``,
the PC the token started at, which places the event even when the post-call PC
is gone.  ``pc0`` with ``pc`` also gives the engine's own length for every
token, which is the thing an operand model is judged on.
"""
from __future__ import annotations

import difflib
import os
import struct
from dataclasses import dataclass

from .. import codec, files, overlay, paths, records, script, vmops

#: v1: file, rec, pc, ch, r, capflag, caplen, idx_off, idx_len.  Headerless, and
#: everything was read *after* exec_token returned -- so a token that ended a
#: script logged pc 0 and idx_off 0, because the engine had already cleared the
#: context.  Those events cannot be placed at all.  Kept because the traces taken
#: before 2026-09-06 are still the oracle.
RECORD_V1 = struct.Struct("<HHHHhBBHH")

#: v2 adds pc0 (the PC *before* the token, i.e. where it starts) and flags, and
#: takes file/rec/pc0/idx from a snapshot made before the call, when the context
#: is guaranteed live.  Behind an 8-byte header so both formats decode.
RECORD_V2 = struct.Struct("<HHHHhBBHHHH")

#: v3 appends ``state`` -- ``ds:0x0047BB70``, the top-level engine state, read at
#: record-write time (so *after* the token, like capflag).  Added 2026-09-09 to
#: answer which state a battle runs in; the static answer turned out to be
#: state 16 sub-state 2, and this makes the question checkable from any session.
RECORD_V3 = struct.Struct("<HHHHhBBHHHHH")

#: v4 appends ``rec_hash`` -- FNV-1a over the current record's own bytes, taken
#: from the same index entry the snapshot already reads -- and ``image_end``,
#: ``idx[255].off + idx[255].len``.  Added 2026-09-10 with overlay v6, which
#: keys a translated span on record CONTENT and so cannot be checked against a
#: trace that carries only the engine's file label.
RECORD_V4 = struct.Struct("<HHHHhBBHHHHHIH")

#: v5 appends ``handle`` -- ``[ds:CTX]+0x0A``, the script buffer the context
#: points at -- and redefines ``rec``/``idx_off``/``idx_len``/``rec_hash`` as
#: the record the PROGRAM COUNTER is in rather than the one ``ds:RECID`` names.
#: Added 2026-09-11: the global is written on load and goes stale, so the
#: oracle was answering a different question than ``hook.c``.  Two new flag
#: bits say which answer this record carries (``VIRTUAL``, ``REC_FROM_PC``).
RECORD_V5 = struct.Struct("<HHHHhBBHHHHHIHH")
MAGIC = b"GTRC"
HEADER = struct.Struct("<4sHH")
BY_VERSION = {2: RECORD_V2, 3: RECORD_V3, 4: RECORD_V4, 5: RECORD_V5}


def _pick(data, path):
    """``(record struct, body)`` for a trace of any version this decodes."""
    if data[:4] != MAGIC:
        return RECORD_V1, data                    # pre-2026-09-06, headerless
    _, ver, size = HEADER.unpack_from(data, 0)
    rs = BY_VERSION.get(ver)
    if rs is None or size != rs.size:
        raise ValueError("%s: unknown trace format v%d, %d-byte records"
                         % (path, ver, size))
    return rs, data[HEADER.size:]


def _fields(rs, f):
    """``(pc0, flags, state, rec_hash, image_end, handle)`` from one record.

    ``rec_hash`` is 0 and ``image_end`` is 0 on anything older than v4, and
    ``handle`` is 0 on anything older than v5, which means "not logged" -- not
    "zero".  ``verify`` refuses to judge an event whose hash is not logged
    rather than guessing, because the overlay is keyed on the hash.
    """
    if rs is RECORD_V1:
        return 0, 0, -1, 0, 0, 0
    state = f[11] if rs in (RECORD_V3, RECORD_V4, RECORD_V5) else -1
    if rs is RECORD_V5:
        return f[9], f[10], state, f[12], f[13], f[14]
    if rs is RECORD_V4:
        return f[9], f[10], state, f[12], f[13], 0
    return f[9], f[10], state, 0, 0, 0

#: ``flags``
CTX_NULL_BEFORE = 1
CTX_NULL_AFTER = 2

#: v5.  ``VIRTUAL``: ``pc0`` was at or above the buffer's image end, so it names
#: no record and ``idx_off``/``idx_len``/``rec_hash`` are logged as 0.
#: ``REC_FROM_PC``: ``rec`` and its index entry came from the hook's own scan of
#: the live index for the record containing the program counter -- the question
#: ``hook.c`` asks.  Without it, ``rec`` is ``ds:RECID``, which is written on
#: load and can name a record the interpreter is not in.  Both read back 0 on
#: v4 and older, so those traces decode unchanged and are simply never trusted
#: about which record an address belongs to.
VIRTUAL = 4
REC_FROM_PC = 8

#: ``flags >> 8`` is the low byte of the wrapper's own return address, i.e.
#: WHICH of exec_token's three call sites dispatched this token.  Spare bits,
#: so no format change: a trace taken before 2026-09-07 has 0 here and decodes
#: as ``site = None``.
#:
#: It exists because ``0x4390F0`` -- "run this script until it blocks" -- is
#: reached from two places, the per-tick background script and ``0x42F334``,
#: and telling them apart is the difference between two entirely different
#: explanations of a loop.
CALL_SITE_BY_RETURN = {0xC9: 0x4390C4, 0x08: 0x439103, 0x41: 0x43913C}

#: what each site is, for reports
CALL_SITE_ROLE = {
    0x4390C4: "0x4390C4 inside 0x439090 (run-until-blocked, the popup driver)",
    0x439103: "0x439103 inside 0x4390F0 (run-until-blocked)",
    0x43913C: "0x43913C direct",
}

RECORD = RECORD_V1          # kept for callers that only want the v1 field order


@dataclass
class Event:
    n: int                  # record index in the trace
    file: int
    rec: int
    pc: int
    ch: int
    r: int
    capflag: int
    caplen: int
    idx_off: int = 0        # where the ENGINE put this record (0 = not logged)
    idx_len: int = 0        # how long the ENGINE thinks it is
    pc0: int = 0            # PC before the token ran, i.e. where it starts (v2)
    flags: int = 0          # CTX_NULL_BEFORE | CTX_NULL_AFTER, plus the
                            # call-site byte in bits 8-15 (v2, since 2026-09-07)
    state: int = -1         # ds:0x0047BB70, the top-level engine state (v3).
                            # -1 on any trace older than v3.
    rec_hash: int = 0       # FNV-1a over the record's own bytes (v4); 0 = not
                            # logged, which is not the same as a hash of zero
    image_end: int = 0      # idx[255].off + idx[255].len of the live buffer (v4)
    handle: int = 0         # [ds:CTX]+0x0A, the script buffer (v5); 0 = not
                            # logged.  A VIRTUAL event is attributed through it

    rel: str = ""           # "m/MS0017.BIN"
    span: "int | None" = None
    anchor: "int | None" = None
    kind: str = "?"         # opcode encoding, "TEXT", or "?"
    ok: bool = False        # self-check: logged ch matches the bytes at pc

    @property
    def site(self) -> "int | None":
        """Which exec_token call site dispatched this token, or None.

        None for any trace taken before 2026-09-07: the bits were spare and
        read back as zero, so old traces decode unchanged.
        """
        return CALL_SITE_BY_RETURN.get(self.flags >> 8)

    def key(self):
        return (self.rel, self.rec, self.anchor, self.kind)


def _rel_of(file_id: int) -> str:
    return "m/MS%04X.BIN" % file_id


class _Image:
    """One parsed script file: runtime bases and per-record token lookup."""

    def __init__(self, rel: str, raw: bytes, entries=None):
        self.sc = script.parse(rel, raw)
        self.by_id = {}
        self.base = {}
        self.image_end = 0
        #: ``{record id: overlay.RecEntry}`` -- found by the record's CONTENT,
        #: which is the only thing v6 keys on.  There is no per-file entry any
        #: more, so this is built per record and a file that happens to share a
        #: record with another file shares its entry too.
        self.ovl = {}
        if self.sc.ok and self.sc.containers:
            recs = self.sc.containers[0]              # limitation: container 0
            rr = [records.Record(r.id, r.data) for r in recs]
            self.base = records.bases(rr)
            self.image_end = overlay.image_end(rr)
            for r in recs:
                self.by_id.setdefault(r.id, r)
            if entries:
                table = sorted(entries, key=lambda e: e.key)
                for rid, r in self.by_id.items():
                    hit = overlay.find_entry(table, rid, len(r.data),
                                             overlay.fnv1a(r.data))
                    if hit is not None:
                        self.ovl[rid] = hit

    def _spans(self):
        """``(span, start, virt)`` for every span this file's records carry.

        ``start`` and ``virt`` are addresses in *this file's* image, which is
        what a decoded trace of a run of this file is measured in.
        """
        for rid, e in self.ovl.items():
            for s in e.spans:
                yield s, self.base[rid] + s.rec_off, self.image_end + s.virt_off

    def _overlay_hit(self, pc: int, ch: int):
        """A logged pc produced by the overlay: inside a virtual range, or the
        real span end the last English byte hands the PC back to."""
        for s, s_start, s_virt in self._spans():
            # inside the in-place head, inside the virtual tail, or the hand-back to s.end after the
            # last English token -- which must then be what was logged: the
            # last character, or the opcode byte of a trailing inline opcode
            # (a page wait or newline ending the line).  A jump can land on
            # s.end too, and its ch is a different opcode, so it is not taken.
            toks = vmops.tokenize(s.data)
            lt = toks[-1]
            if lt.kind == "op":
                last, kind = s.data[lt.off], vmops.table().encoding(lt.idx)
            else:
                last, kind = int.from_bytes(s.data[lt.off:lt.end], "big"), "TEXT"
            in_head = s_start < pc <= s_start + s.served
            in_tail = s.tail and s_virt < pc <= s_virt + s.tail
            if in_head or in_tail:
                kind = "TEXT"
            if in_head or in_tail or (pc == s_start + s.jp_len and ch == last):
                rec_id = max((i for i, b in self.base.items() if b <= s_start), default=None)
                r = self.by_id.get(rec_id)
                if r is None or r.tokens is None:
                    return None
                off = s_start - self.base[rec_id]
                k = next((i for i, t in enumerate(r.tokens) if t.off == off), None)
                if k is None:
                    return None
                anchor = sum(1 for u in r.tokens[:k] if u.kind == "op" and u.idx not in codec.INLINE_OPS)
                span = next((sp.idx for sp in r.spans if sp.tok_lo <= k < sp.tok_hi), None)
                return span, anchor, kind, True
        return None

    def locate(self, rec_id: int, pc: int, ch: int, base: "int | None" = None,
               pc0: "int | None" = None):
        r = self.by_id.get(rec_id)
        if r is None or r.tokens is None:
            return None
        # The hook logs *after* exec_token returns, and an opcode's handler has
        # consumed its operands by then -- so pc is the END of the token, for
        # text (1 or 2 bytes) and opcodes alike.  Measured: consecutive opcode
        # steps in a real trace sit exactly one token length apart.
        # ``base`` is the engine's own index entry when the trace carries it;
        # our model's base is only the fallback.
        hit_ = self._overlay_hit(pc, ch)
        if hit_ is not None:
            return hit_
        b = base if base else self.base[rec_id]
        end = pc - b
        if not 0 <= end <= len(r.data):
            # a v2 trace can still place this by where the token started
            if pc0 is None:
                return None
            end = -1
        want = bytes([ch]) if ch <= 0xFF else bytes([ch >> 8, ch & 0xFF])
        def hit(k, t, jumped):
            anchor = sum(1 for u in r.tokens[:k]
                         if u.kind == "op" and u.idx not in codec.INLINE_OPS)
            span = next((s.idx for s in r.spans if s.tok_lo <= k < s.tok_hi), None)
            if jumped:
                # a control opcode ran and execution *landed* here: name the
                # opcode that ran (ch) and the place it went (this token)
                kind = "%s->" % vmops.table().encoding(ch)
                return span, anchor, kind, ch < 0x20
            got = r.data[t.off:t.end]
            kind = "TEXT" if t.kind == "text" else vmops.table().encoding(t.idx)
            return span, anchor, kind, got == want or (t.kind == "op" and got[:1] == want[:1])
        # 1. the token that ends at pc: text, or an opcode that fell through.
        #    A text token has to *match the logged character* to claim the pc.
        #    Accepting any text token that merely ends there shadowed rule 2 and
        #    reported a mismatch: at m/MS7F04 r07 0x2A the engine had branched
        #    onto the `18` opcode starting there, and the two text bytes ending
        #    there were charged with the disagreement instead.
        for k, t in enumerate(r.tokens):
            if t.end != end:
                continue
            if t.kind == "text" and r.data[t.off:t.end] != want:
                continue
            if t.kind == "op" and r.data[t.off] != ch:
                continue
            return hit(k, t, False)
        # 2. the token that starts at pc: a taken branch, a call, a return
        for k, t in enumerate(r.tokens):
            if t.off == end:
                return hit(k, t, True)
        # 3. v2 only: the token pc0 sits just past the front of.  The post-call
        #    pc is 0 whenever the token ended the script, because the engine
        #    clears the context before the hook reads it back -- but pc0 was
        #    snapshotted before the call and is always good.  This is what
        #    rescues those events; it is a weaker anchor than 1., so it is
        #    tried last.
        #
        #    pc0 is NOT the token's first byte: the caller fetches that byte
        #    (two, for a wide character) before it calls exec_token, and the
        #    fetch is what advances the PC -- an opcode's operands are consumed
        #    later, inside the handler.  So the token starts at pc0 minus the
        #    width of what was fetched.  Measured over the soft-lock trace,
        #    restricted to corroborated files at addresses the overlay does not
        #    serve: 35,713 events have the logged character at pc0 - width and
        #    none has it at pc0 alone.  This rule used to take pc0 itself and
        #    so placed every event it rescued one token too far along.
        if pc0 is not None:
            start = pc0 - (2 if ch > 0xFF else 1) - b
            if 0 <= start < len(r.data):
                for k, t in enumerate(r.tokens):
                    if t.off == start:
                        return hit(k, t, False)
        return None


def decode(trace_path: str, build_dir: "str | None" = None) -> "list[Event]":
    """Every record of a trace, resolved against the build that produced it."""
    build_dir = build_dir or paths.game_root()
    with open(trace_path, "rb") as fh:
        data = fh.read()
    entries = None
    ovl = os.path.join(build_dir, "overlay.dat")
    if os.path.exists(ovl):
        with open(ovl, "rb") as fh:
            entries = overlay.parse(fh.read())
    rs, body = _pick(data, trace_path)
    images = {}
    out = []
    for n in range(len(body) // rs.size):
        f = rs.unpack_from(body, n * rs.size)
        pc0, flags, state, rec_hash, image_end_, handle = _fields(rs, f)
        ev = Event(n, f[0], f[1], f[2], f[3], f[4], f[5], f[6], f[7], f[8],
                   pc0, flags, state, rec_hash, image_end_, handle,
                   rel=_rel_of(f[0]))
        if ev.rel not in images:
            p = os.path.join(build_dir, *ev.rel.split("/"))
            images[ev.rel] = _Image(ev.rel, open(p, "rb").read(), entries) if os.path.exists(p) else None
        img = images[ev.rel]
        hit = img.locate(ev.rec, ev.pc, ev.ch, ev.idx_off or None,
                         ev.pc0 or None) if img else None
        if hit:
            ev.span, ev.anchor, ev.kind, ev.ok = hit
        out.append(ev)
    _mark_name_excursions(out, images)
    return out


#: the kind given to events that are not script addresses at all
NAME_KIND = "NAME"


def _name_char_width(ch: int) -> "int | None":
    """How many bytes this logged character is, or None if it is not one.

    A name buffer holds text and nothing else, so every step of the walk has to
    be a printable cp932 character: a two-byte one, an ASCII one, or a
    half-width katakana byte.  Control bytes below 0x20 are where the opcodes
    live, so they end the run rather than extending it.
    """
    if ch > 0xFF:
        try:
            bytes([ch >> 8, ch & 0xFF]).decode("cp932")
        except UnicodeDecodeError:
            return None
        return 2
    if 0x20 <= ch <= 0x7E or 0xA1 <= ch <= 0xDF:
        return 1
    return None


def _mark_name_excursions(events: "list[Event]", images: dict, place=None) -> int:
    """Mark the runs where the engine left the script to print a runtime string.

    ``1F01 nn`` prints party-member name *nn*.  The interpreter reads it through
    the same byte fetch the hook watches, so each character arrives as a token --
    but from a string buffer, not the script: the PC restarts at 0 and counts up
    in twos.  No record contains those addresses and none ever will, so scoring
    them against our token boundaries measures nothing about the opcode model.
    On the traced routes they are 262 of 18,683 events, and counting them as
    disagreements is what held "engine agreement" at 98.4% instead of 99.8%.

    A run is only marked when it is bounded at both ends and by the opcode that
    causes it, which is what makes this a classification rather than an excuse:

      * the script token about to run is a ``1F01``;
      * the entry event carries the ``1F`` escape at pc 0;
      * the body is PCs ascending by the width of each character from the width
        of the first, each character decoding as cp932;
      * execution resumes inside a record (or the trace ends).

    Anything that fails those stays a disagreement.

    ``place(ev)`` answers "where inside its record is ``ev.pc``, and what are
    that record's tokens", as ``(offset or None, tokens or None)``.  The default
    reads the file the event is *labelled* with; :func:`verify` passes one that
    reads the record's own content instead, because the label comes from an
    engine global written on load and can name a file that is not running.
    """
    if place is None:
        def place(ev):
            img = images.get(ev.rel)
            if img is None or ev.rec not in img.by_id:
                return None, None
            rec = img.by_id[ev.rec]
            off = ev.pc - img.base[ev.rec]
            return (off if 0 <= off <= len(rec.data) else None), rec.tokens

    def inside(ev):
        return place(ev)[0]

    def _tokens(ev):
        return place(ev)[1]

    def _is_1f01(t):
        return (t is not None and t.kind == "op"
                and vmops.table().encoding(t.idx).replace(" ", "") == "1F01")

    def bounded_by_1f01(i, resume):
        """A 1F01 on either side of the excursion; only that opcode is proven.

        Before: the token about to run where the last in-record event ended.
        After: the token execution resumes on begins exactly where a 1F01 ends.
        The second test exists because the events before an excursion can belong
        to a *different* file -- the engine expands a pool call and returns --
        so walking back a few events can leave the record entirely.
        """
        for j in range(i - 1, max(-1, i - 4), -1):
            off = inside(events[j])
            if off is None:
                continue
            toks = _tokens(events[j])
            if toks is None:
                break
            if _is_1f01(next((t for t in toks if t.off == off), None)):
                return True
            break
        off = inside(resume) if resume is not None else None
        toks = _tokens(resume) if resume is not None else None
        if off is None or toks is None:
            return False
        cur = next((t for t in toks if t.end == off or t.off == off), None)
        return cur is not None and _is_1f01(
            next((t for t in toks if t.end == cur.off), None))

    marked = i = 0
    n = len(events)
    while i < n:
        e = events[i]
        if e.ok or e.pc != 0 or e.ch != 0x1F:
            i += 1
            continue
        j, want, body = i + 1, None, []
        while j < n and not events[j].ok:
            w = _name_char_width(events[j].ch)
            if w is None:
                break
            if want is None:
                # The walk starts at the width of its first character -- 2 for a
                # Japanese name, 1 for the ASCII ones we install -- so the first
                # body PC is 1 or 2 and never more.  Requiring 2 is what made
                # this classify nothing at all once party names became ASCII:
                # the run counts 1,2,3... now, not 2,4,6...
                if events[j].pc != w:
                    break
                want = w
            elif events[j].pc != want:
                break
            body.append(j)
            want += w
            j += 1
        resume = events[j] if j < n else None
        if not body or (resume is not None and inside(resume) is None):
            i += 1
            continue
        if not bounded_by_1f01(i, resume):
            i += 1
            continue
        for k in [i] + body:
            events[k].kind = NAME_KIND
            events[k].ok = True
        marked += 1 + len(body)
        i = j
    return marked


POOL_CALLS = {"%02X->" % k for k in range(1, 9)}
#: inline opcodes (newline ``0A``, page wait ``1E10``): translators add and
#: remove these freely inside a span, so they are text, not flow
INLINE_KINDS = {vmops.table().encoding(k) for k in codec.INLINE_OPS} - POOL_CALLS
MAX_CYCLE = 12


def normalise(events: "list[Event]") -> "list[Event]":
    """Reduce a trace to the structural flow two builds must share.

    Three things that legitimately differ between a Japanese and an English run
    are folded away, each learned from the first real pair of traces:

    * **text** -- runs of characters collapse to one TEXT event per anchor;
    * **pool words** -- a ``01``-``08`` call and everything executed inside the
      pool files ``m/MS7F0x`` is part of the text run (English inlines the
      dictionary word the Japanese fetched), so those events become TEXT too;
    * **inline opcodes** -- newlines and page waits inside a span are re-flowed
      by the translator, so they fold into the text run as well;
    * **idle polling** -- the engine spins in a tiny cycle (``1F57`` / jump /
      jump / ``18`` back in ``m/MS002D`` r01) until input arrives, so how long
      the player waited shows up as thousands of repeated events.  Immediately
      repeating cycles of up to :data:`MAX_CYCLE` events collapse to one.
    """
    out = []
    for ev in events:
        if ev.rel.startswith("m/MS7F0") or ev.kind in POOL_CALLS:
            continue                          # a word, not flow: see above
        if ev.kind in INLINE_KINDS:
            ev.kind = "TEXT"                  # a newline or page wait is part of the text
        if out and ev.kind == "TEXT" and out[-1].kind == "TEXT" and out[-1].key() == ev.key():
            out[-1].r = ev.r                      # keep the *last* r of the run
            out[-1].caplen = max(out[-1].caplen, ev.caplen)
            continue
        out.append(ev)
        # drop an immediate repeat of the last p events, for any small p
        for p_ in range(1, MAX_CYCLE + 1):
            if len(out) >= 2 * p_ and [e.key() for e in out[-p_:]] == [e.key() for e in out[-2 * p_:-p_]]:
                del out[-p_:]
                break
    return out


def diff(jp_trace: str, en_trace: str, jp_build: str, en_build: str, context: int = 6):
    """First divergence between two traces of the same route.

    Returns ``(index_jp, index_en, jp_events, en_events)`` or ``None`` when the
    normalised event sequences are identical.
    """
    a = normalise(decode(jp_trace, jp_build))
    b = normalise(decode(en_trace, en_build))
    sm = difflib.SequenceMatcher(None, [e.key() for e in a], [e.key() for e in b], autojunk=False)
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op != "equal":
            return i1, j1, a, b
    return None


def describe(ev: Event) -> str:
    where = "%s r%02X" % (ev.rel, ev.rec)
    if ev.span is not None:
        where += "[%d]" % ev.span
    return "%-24s anchor=%-5s %-6s pc=0x%04X ch=0x%04X r=%d cap=%s/%d%s" % (
        where, ev.anchor, ev.kind, ev.pc, ev.ch, ev.r, "on" if ev.capflag else "off",
        ev.caplen, "" if ev.ok else "  (self-check: bytes at pc differ)")


def report_diff(jp_trace, en_trace, jp_build, en_build, context=6) -> str:
    res = diff(jp_trace, en_trace, jp_build, en_build)
    if res is None:
        return "no divergence: both traces run the same script"
    i, j, a, b = res
    lines = ["first divergence at JP event %d / EN event %d" % (i, j), "", "JP:"]
    for ev in a[max(0, i - context):i + 2]:
        lines.append(("  >> " if ev is a[i] else "     ") + describe(ev))
    lines += ["", "EN:"]
    for ev in b[max(0, j - context):j + 2]:
        lines.append(("  >> " if ev is b[j] else "     ") + describe(ev))
    return "\n".join(lines)



#: Opcodes that move the program counter somewhere the next byte would not have
#: gone: goto-record, call-record, and the branch family that shares
#: ``0x004348B0``.  If the interpreter ever dispatches one of these *out of
#: bytes the overlay served*, the English run has taken a path the Japanese run
#: would not, and every guarantee the overlay is supposed to give is void.
FLOW_OPCODES = frozenset({0x0C, 0x0D}) | frozenset(range(0x10, 0x19))




def corpus_records(root: "str | None" = None) -> "dict[tuple[int, int, int], bytes]":
    """``{(record id, length, FNV-1a): bytes}`` over every container of every file.

    The other half of content addressing.  A v4 trace record says which record
    the engine was in by its *content* -- id, length and hash -- and says
    nothing about the file, deliberately, because the engine's file label is
    written on load and routinely names a script that is not running.  So to ask
    "what does the original say at this address" the bytes have to be found by
    the same key the overlay uses.

    Read straight out of the containers rather than through :mod:`.script`: this
    needs the bytes, not a tokenisation, and parsing 700-odd files twice is the
    difference between a verify that takes seconds and one that takes minutes.
    """
    from .. import container

    root = root or paths.game_root()
    out = {}
    for sub in ("m", "et"):
        d = os.path.join(root, sub)
        if not os.path.isdir(d):
            continue
        for name in sorted(os.listdir(d)):
            if not name.lower().endswith(".bin"):
                continue
            try:
                with open(os.path.join(d, name), "rb") as fh:
                    conts, _ = container.split(fh.read())
            except Exception:
                continue
            for c in conts:
                try:
                    recs = records.parse_body(c.body).records
                except Exception:
                    continue
                seen = set()
                for r in recs:
                    if r.id in seen:
                        continue            # first occurrence wins, as the loader does
                    seen.add(r.id)
                    out.setdefault((r.id, len(r.data), overlay.fnv1a(r.data)), r.data)
    return out


def _ranges(entry, idx_off: int, image_end: int):
    """``[(lo, hi, bytes)]`` -- every address this record's entry answers.

    In the running buffer's own coordinates: a span in place at
    ``idx_off + rec_off``, and its tail, if it has one, at
    ``image_end + virt_off``.  Exactly what ``hook.c`` computes.
    """
    out = []
    if entry is None:
        return out
    for s in entry.spans:
        if s.served:
            out.append((idx_off + s.rec_off, idx_off + s.rec_off + s.served,
                        s.data[:s.served]))
        if s.tail:
            out.append((image_end + s.virt_off, image_end + s.virt_off + s.tail,
                        s.data[s.served:]))
    return out


def _handoffs(entry, idx_off: int, image_end: int):
    """``{target pc: [source address]}`` -- the fetches whose next pc is not +1.

    Two, and only two, exist.  Serving the last byte of a span's English hands
    the program counter to the span's END, and serving the last byte that fits
    in place hands it to the TAIL's virtual address.  An event logged at one of
    those program counters had its bytes fetched further back than ``pc0 -
    width`` says, and without this it reads as "the byte does not match".
    """
    out = {}
    if entry is None:
        return out
    for s in entry.spans:
        end = idx_off + s.rec_off + s.jp_len
        if s.tail:
            virt = image_end + s.virt_off
            out.setdefault(virt, []).append(idx_off + s.rec_off + s.served - 1)
            out.setdefault(end, []).append(virt + s.tail - 1)
        elif s.served:
            out.setdefault(end, []).append(idx_off + s.rec_off + s.served - 1)
    return out


def _byte_at(ranges, data: bytes, idx_off: int, idx_len: int, a: int):
    """``(byte, "overlay" | "file")`` at address ``a``, or ``(None, why)``."""
    for lo, hi, blob in ranges:
        if lo <= a < hi:
            return blob[a - lo], "overlay"
    if idx_off <= a < idx_off + idx_len:
        return data[a - idx_off], "file"
    return None, "outside"


def _read(ranges, data: bytes, idx_off: int, idx_len: int, addrs):
    """``(bytes, "overlay"|"file")`` at those addresses, or ``(None, why)``.

    The addresses are given one by one rather than as a start and a width,
    because a wide character can straddle a handoff: its lead byte is the last
    one served in place and its trail byte is the first of the virtual tail, so
    the two are nowhere near each other.  Reading byte by byte also makes a
    token honest whose first byte comes from the file and whose second comes
    from a span starting there -- and "overlay" wins the label, because an
    overlay byte is the thing that would be wrong if anything were.
    """
    out, source = bytearray(), "file"
    for a in addrs:
        b, how = _byte_at(ranges, data, idx_off, idx_len, a)
        if b is None:
            return None, how
        out.append(b)
        if how == "overlay":
            source = "overlay"
    return bytes(out), source


def _candidates(pc0: int, width: int, handoffs) -> "list[tuple]":
    """Where the ``width`` bytes logged at ``pc0`` were read from.

    Normally the fetches are consecutive and end just before ``pc0``.  The
    exceptions are the two program-counter moves the hook makes that are not
    ``+1``: the last byte of a span's English hands the counter to the span's
    end, and the last byte that fits in place hands it to the tail.  Either can
    fall at the end of a token -- or, for a wide character, in the middle of
    one.
    """
    out = [tuple(range(pc0 - width, pc0))]
    for src in handoffs.get(pc0, ()):                 # handoff after the token
        out.append(tuple(range(src - width + 1, src + 1)))
    if width == 2:
        for src in handoffs.get(pc0 - 1, ()):         # handoff inside the token
            out.append((src, pc0 - 1))
    return out


def _attribute_virtual(events: "list[Event]") -> int:
    """Give every ``VIRTUAL`` event the record the same handle was last in.

    A virtual program counter exists only because the hook invented one, and it
    is invented from the record the previous fetch was in -- every record's
    tails begin at the same ``image_end``, so the address names no record on its
    own and the hook itself resolves it through a per-handle memo.  v5 logs the
    handle for exactly this: the trace can do the same lookup offline, which is
    what turns an event the hook served into one the verifier can judge instead
    of one it has to decline.

    The events are rewritten in place -- ``rec``, the index entry, the hash, and
    ``REC_FROM_PC`` if the record it is taken from was itself found from a
    program counter.  Nothing happens on a v4 trace: ``VIRTUAL`` is never set
    there, and ``handle`` is not logged.

    Returns how many events were attributed.
    """
    last, n = {}, 0
    for ev in events:
        if ev.flags & VIRTUAL:
            src = last.get(ev.handle)
            if src is not None:
                ev.rec, ev.idx_off, ev.idx_len, ev.rec_hash, from_pc = src
                ev.flags |= from_pc
                n += 1
        elif ev.idx_len:
            last[ev.handle] = (ev.rec, ev.idx_off, ev.idx_len, ev.rec_hash,
                               ev.flags & REC_FROM_PC)
    return n


def verify(trace_path: str, build_dir: "str | None" = None,
           overlay_path: "str | None" = None):
    """Did the overlay change control flow?  Answered from one English trace.

    The overlay's contract is local: for a translated span it serves English in
    place of the Japanese bytes and hands the program counter back at the span's
    end.  Two things follow, and both are checkable against a trace:

    * every token the engine dispatched from **outside** a served range must be
      the byte that is in the original record at that address -- the overlay
      must not have touched it;
    * every token dispatched from **inside** one must be text, or an inline
      opcode the codec is allowed to embed.  Never a branch.

    If both hold for every event, the instruction stream the interpreter walked
    *is* the Japanese instruction stream, and the English run cannot have gone
    anywhere the Japanese run would not.  That is why one trace is enough and no
    second play-through of the same route is needed.

    **No file is identified, anywhere in here.**  A v4 trace record carries the
    engine's own index entry for the record it was in -- offset, length -- plus
    FNV-1a over that record's bytes and the buffer's own image end.  That triple
    is the overlay's key, so the same lookup the hook does answers "what were we
    serving here", and :func:`corpus_records` answers "what does the original
    say".  Everything the old version needed the file label for -- the
    corroboration gate, the pairing gate, the stale-label carve-out -- is gone,
    because the label was never the question.

    Returns ``(stats, findings)``.  A finding is
    ``(event, category, explanation)``.

    **What this does not prove.**  Flow equality on the routes actually walked,
    not universally; coverage grows with play.  An event the decoder cannot
    place is counted as *unverified*, not as a pass.
    """
    build_dir = build_dir or paths.game_root()
    with open(trace_path, "rb") as fh:
        data = fh.read()
    entries = []
    # An explicit overlay lets a test pin a trace against the exact overlay that
    # produced it.  A v6 table needs no such pinning to be *placed* -- addresses
    # come out of the record in front of us -- but the English it serves is
    # still the English of one build.
    ovl = overlay_path or os.path.join(build_dir, "overlay.dat")
    if os.path.exists(ovl):
        with open(ovl, "rb") as fh:
            entries = overlay.parse(fh.read())
    table = sorted(entries, key=lambda e: e.key)

    rs, body = _pick(data, trace_path)
    stats = {"records": 0, "served": 0, "from the file": 0, "unverified": 0,
             "in a name print": 0, "out of bounds": 0, "no context": 0,
             "record not in the corpus": 0, "virtual PCs": 0,
             "record does not contain pc0": 0, "virtual PCs attributed": 0,
             "overlay entries": len(entries)}
    findings, events = [], []
    for n in range(len(body) // rs.size):
        f = rs.unpack_from(body, n * rs.size)
        pc0, flags, state, rec_hash, image_end_, handle = _fields(rs, f)
        events.append(Event(n, f[0], f[1], f[2], f[3], f[4], f[5], f[6], f[7],
                            f[8], pc0, flags, state, rec_hash, image_end_,
                            handle, rel=_rel_of(f[0])))
    stats["records"] = len(events)
    if rs not in (RECORD_V4, RECORD_V5):
        ev = events[0] if events else Event(0, 0, 0, 0, 0, 0, 0, 0)
        return stats, [(ev, "this trace predates content addressing",
                        "overlay v6 keys a translated span on the CONTENT of "
                        "the record it lives in, and only a v4 trace logs that "
                        "(the record's FNV-1a and the buffer's image end).  An "
                        "older trace carries the engine's file label instead, "
                        "which is written on load and names whatever script was "
                        "loaded most recently -- not necessarily the one "
                        "running.  Re-record the route on this build.")]
    stats["virtual PCs attributed"] = _attribute_virtual(events)

    corpus = corpus_records(build_dir)
    bytes_of = {}

    def record_of(ev):
        key = (ev.rec, ev.idx_len, ev.rec_hash)
        if key not in bytes_of:
            bytes_of[key] = corpus.get(key)
        return bytes_of[key]

    # While the engine prints a runtime name the PC is inside a name buffer,
    # not the script, so its bytes are the name's characters and comparing them
    # with the script is meaningless.  Without this the English names we install
    # read as script corruption -- 'e', ',', 'K' at consecutive PCs just past a
    # span serving 'Emi:'.  Placed by content, like everything else here.
    tokens_of = {}

    def place(ev):
        data_ = record_of(ev)
        if data_ is None:
            return None, None
        off = ev.pc - ev.idx_off
        key = (ev.rec, ev.idx_len, ev.rec_hash)
        if key not in tokens_of:
            try:
                tokens_of[key] = vmops.tokenize(data_)
            except Exception:
                tokens_of[key] = None
        return (off if 0 <= off <= len(data_) else None), tokens_of[key]

    _mark_name_excursions(events, {}, place)
    shaped = {}

    for ev in events:
        if ev.kind == NAME_KIND:
            stats["in a name print"] += 1
            continue
        if not ev.pc0 or not ev.idx_len:
            stats["no context"] += 1        # null context or handle: legitimate
            continue
        data_ = record_of(ev)
        if data_ is None:
            # The engine is in a record no file on disk holds.  Real: record
            # 0x97 of a demon merge is 976 bytes at run time against 82 on
            # disk, built by the loader.  Nothing is claimed about those.
            stats["record not in the corpus"] += 1
            continue
        key = (ev.rec, ev.idx_len, ev.rec_hash, ev.idx_off, ev.image_end)
        if key not in shaped:
            entry = overlay.find_entry(table, ev.rec, ev.idx_len, ev.rec_hash)
            shaped[key] = (_ranges(entry, ev.idx_off, ev.image_end),
                           _handoffs(entry, ev.idx_off, ev.image_end))
        ranges, handoffs = shaped[key]

        # pc0 is one past what the caller fetched -- one byte for an opcode
        # (its operands are consumed later, inside the handler) or the width of
        # the character for text -- so the dispatched bytes end there.  Except
        # at a handoff, where the hook moved the program counter somewhere other
        # than +1; then the bytes are at the address that handed it over.
        width = 2 if ev.ch > 0xFF else 1
        want = (bytes([(ev.ch >> 8) & 0xFF, ev.ch & 0xFF]) if width == 2
                else bytes([ev.ch & 0xFF]))
        starts = _candidates(ev.pc0, width, handoffs)
        hit, readable = None, None
        for addrs in starts:
            got, how = _read(ranges, data_, ev.idx_off, ev.idx_len, addrs)
            if got is not None and got == want:
                hit = (addrs[0], got, how)
                break
            if got is not None and readable is None:
                readable = (addrs[0], how)  # in range, but not what was logged
        if hit is None:
            a, how = readable if readable else (starts[0][0], "outside")
            if how == "outside":
                # Does the record this event names hold the address the token
                # was fetched from at all?  Through v4 the hook took the record
                # id from ds:RECID, written on load, so the answer is routinely
                # no and nothing about the address can be concluded -- 165
                # "outside the record" findings and 450 "unverified" events on
                # the Roppongi session were this and only this.  A v5 trace
                # finds the record from the program counter and says so with
                # REC_FROM_PC; only then is an unplaceable address a finding.
                holds = ev.idx_off <= ev.pc0 - 1 < ev.idx_off + ev.idx_len
                if not holds and not (ev.flags & REC_FROM_PC):
                    stats["record does not contain pc0"] += 1
                elif a >= ev.image_end:
                    stats["out of bounds"] += 1
                    findings.append((ev, "program counter outside the record and our overlay",
                                     "pc0 0x%04X is above the buffer's image end "
                                     "(0x%04X) and in no virtual range this overlay "
                                     "declares for record %02X.  A virtual address "
                                     "exists only because the hook invents one, so "
                                     "either the overlay that ran is not this one "
                                     "or the engine is executing memory nobody owns"
                                     % (ev.pc0, ev.image_end, ev.rec)))
                else:
                    # the record holds pc0 - 1, but the token's other bytes run
                    # off its start: nothing is claimed either way
                    stats["unverified"] += 1
                continue
            got, how = _read(ranges, data_, ev.idx_off, ev.idx_len, starts[0])
            findings.append((ev, "byte does not match what %s holds" % (
                "the overlay serves" if how == "overlay" else "the original record"),
                             "logged 0x%04X at pc0 0x%04X, but record %02X "
                             "(%d bytes, hash %08X) has 0x%s at 0x%04X"
                             % (ev.ch, ev.pc0, ev.rec, ev.idx_len, ev.rec_hash,
                                (got or b"").hex(), starts[0][0])))
            continue
        a, got, how = hit
        if a >= ev.image_end:
            stats["virtual PCs"] += 1
        if how == "overlay":
            stats["served"] += 1
            if width == 1 and got[0] in FLOW_OPCODES:
                findings.append((ev, "branch served from our English",
                                 "the engine dispatched 0x%02X at pc 0x%04X out "
                                 "of bytes the overlay supplied"
                                 % (got[0], ev.pc0)))
        else:
            stats["from the file"] += 1
    return stats, findings


def report_verify(trace_path: str, build_dir: "str | None" = None,
                  limit: int = 20, overlay_path: "str | None" = None):
    stats, findings = verify(trace_path, build_dir, overlay_path)
    out = ["%s" % os.path.basename(trace_path)]
    refused = [f for f in findings if "predates content addressing" in f[1]]
    if refused:
        out.append("  REFUSED: %s" % refused[0][1])
        out.append("    %s" % refused[0][2])
        return "\n".join(out), 1
    placed = stats["served"] + stats["from the file"]
    out.append("  %d records: %d placed (%d served by the overlay, %d read "
               "from the file), %d unverified"
               % (stats["records"], placed, stats["served"],
                  stats["from the file"], stats["unverified"]))
    if not placed:
        out.append("  NOTHING could be placed -- wrong build directory?")
        return "\n".join(out), 1
    out.append("  %.1f%% of the trace was checked"
               % (100.0 * placed / max(1, stats["records"])))
    if stats["no context"]:
        out.append("  %d record(s) with no live context or handle; the engine "
                   "produces those between scripts" % stats["no context"])
    if stats["record not in the corpus"]:
        out.append("  %d record(s) whose bytes no file on disk holds -- the "
                   "loader builds some at run time" % stats["record not in the corpus"])
    if stats["virtual PCs"]:
        out.append("  %d virtual program counter(s), all inside a tail this "
                   "overlay declares" % stats["virtual PCs"])
    if stats.get("virtual PCs attributed"):
        out.append("  %d event(s) logged no record (v5 VIRTUAL) and were "
                   "attributed to the record their buffer handle was last in"
                   % stats["virtual PCs attributed"])
    if stats.get("record does not contain pc0"):
        out.append("  %d record(s) the trace could not attribute: the record it "
                   "names does not hold pc0" % stats["record does not contain pc0"])
        out.append("    (a v4 trace names the record from ds:RECID, which is "
                   "written on load and goes stale; re-record on a v5 build to "
                   "have these judged)")
    if stats["out of bounds"]:
        out.append("  %d program counter(s) outside the record AND our overlay"
                   % stats["out of bounds"])
    if not findings:
        out.append("")
        out.append("  CLEAN: every token dispatched outside a served span "
                   "matched the original")
        out.append("  record, and every token inside one was text or an inline "
                   "opcode.  Over this")
        out.append("  route the overlay did not change control flow.")
        return "\n".join(out), 0
    out.append("")
    out.append("  %d FINDING(S):" % len(findings))
    for ev, cat, why in findings[:limit]:
        out.append("    #%d rec 0x%02X pc 0x%04X: %s" % (ev.n, ev.rec, ev.pc, cat))
        out.append("        %s" % why)
    return "\n".join(out), 1


def files_seen(trace_path: str, build_dir: "str | None" = None):
    """Every file id the trace visited, resolved to a name where one exists.

    The engine's current-file register is a ``u16``, and the script families do
    not share one id space cleanly: ``m/MS####`` and ``et/ID####`` both derive
    an id from their name and two of them genuinely collide.  So a raw id is
    ambiguous, and this reports every file whose name matches it rather than
    guessing.

    The question it exists to answer: **do the et/ID demon-negotiation scripts
    ever run through the interpreter?**  If they never appear here, the overlay
    cannot reach them -- the hook is on the interpreter's byte fetch -- and the
    byte build has to stay, exactly as it must for the shop text in m/MS01xx.
    """
    import collections
    build_dir = build_dir or paths.game_root()
    with open(trace_path, "rb") as fh:
        data = fh.read()
    rs, body = _pick(data, trace_path)
    counts = collections.Counter()
    for n in range(len(body) // rs.size):
        counts[rs.unpack_from(body, n * rs.size)[0]] += 1

    known = {}
    for sub, prefix in (("m", "MS"), ("et", "ID")):
        d = os.path.join(build_dir, sub)
        if not os.path.isdir(d):
            continue
        for name in sorted(os.listdir(d)):
            if name.startswith(prefix) and name.endswith(".BIN"):
                try:
                    known.setdefault(overlay._fid("%s/%s" % (sub, name)), []).append(
                        "%s/%s" % (sub, name))
                except ValueError:
                    pass
    return [(fid, n, known.get(fid, [])) for fid, n in counts.most_common()]


def report_files(trace_path: str, build_dir: "str | None" = None, limit: int = 60):
    rows = files_seen(trace_path, build_dir)
    out = ["%s: %d distinct file id(s)" % (os.path.basename(trace_path), len(rows))]
    et = [r for r in rows if any(x.startswith("et/") for x in r[2])]
    unknown = [r for r in rows if not r[2]]
    for fid, n, names in rows[:limit]:
        tag = ", ".join(names) if names else "-- no file has this id --"
        out.append("   0x%04X %8d tokens   %s" % (fid, n, tag))
    out.append("")
    out.append("   %d id(s) match an et/ID script; %d match no file at all"
               % (len(et), len(unknown)))
    if not et:
        out.append("   No et/ID script ran: the overlay cannot serve them, so")
        out.append("   the byte build for those 17 files has to stay.")
    return "\n".join(out), 0

def selfcheck(trace_path: str, build_dir: str) -> "tuple[int, int]":
    """``(records, records whose logged bytes did not match the build)``."""
    evs = decode(trace_path, build_dir)
    return len(evs), sum(1 for e in evs if not e.ok)


def bases(trace_path: str, build_dir: str):
    """The engine's record placement against our model, per (file, record).

    Returns ``[(rel, rec, engine_off, engine_len, model_off, model_len)]`` for
    every record the trace visited with the index entry logged.  Any non-zero
    difference is the layout rule we have not modelled; the whole point of
    logging the entry is to read that rule off real numbers instead of fitting
    a theory to displaced branches.
    """
    build_dir = build_dir or paths.game_root()
    seen = {}
    images = {}
    for ev in decode(trace_path, build_dir):
        if not ev.idx_off or (ev.rel, ev.rec) in seen:
            continue
        if ev.rel not in images:
            p = os.path.join(build_dir, *ev.rel.split("/"))
            images[ev.rel] = _Image(ev.rel, open(p, "rb").read()) if os.path.exists(p) else None
        img = images[ev.rel]
        r = img.by_id.get(ev.rec) if img else None
        seen[(ev.rel, ev.rec)] = (ev.rel, ev.rec, ev.idx_off, ev.idx_len,
                                  img.base.get(ev.rec) if img else None,
                                  len(r.data) if r else None)
    return list(seen.values())
