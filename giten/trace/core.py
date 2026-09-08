"""Decode and diff interpreter traces written by the dev exe's ``.trc`` hook.

A trace is a flat file of fixed-size records (see ``exe/trace.S``).  v2 carries
an 8-byte ``"GTRC"`` header and 20-byte records::

    u16 file, u16 rec, u16 pc, u16 ch, i16 r, u8 capflag, u8 caplen,
    u16 idx_off, u16 idx_len, u16 pc0, u16 flags

v1 is headerless with 16-byte records (no ``pc0``/``flags``); both decode, since
the traces taken before 2026-09-06 are still the oracle the opcode model is
checked against.

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
MAGIC = b"GTRC"
HEADER = struct.Struct("<4sHH")

#: ``flags``
CTX_NULL_BEFORE = 1
CTX_NULL_AFTER = 2

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
        self.entry = None                             # overlay entry, if the build has one
        if self.sc.ok and self.sc.containers:
            recs = self.sc.containers[0]              # limitation: container 0
            rr = [records.Record(r.id, r.data) for r in recs]
            self.base = records.bases(rr)
            for r in recs:
                self.by_id.setdefault(r.id, r)
            if entries:
                fid, fp = int(rel[4:8], 16), overlay.fingerprint(rr)
                self.entry = next((e for e in entries if e.fid == fid and e.fp == fp), None)

    def _overlay_hit(self, pc: int, ch: int):
        """A logged pc produced by the overlay: inside a virtual range, or the
        real span end the last English byte hands the PC back to."""
        e = self.entry
        if e is None:
            return None
        for s in e.spans:
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
            in_head = s.start < pc <= s.start + s.head
            in_tail = s.tail and s.virt < pc <= s.vend
            if in_head or in_tail:
                kind = "TEXT"
            if in_head or in_tail or (pc == s.end and ch == last):
                rec_id = max((i for i, b in self.base.items() if b <= s.start), default=None)
                r = self.by_id.get(rec_id)
                if r is None or r.tokens is None:
                    return None
                off = s.start - self.base[rec_id]
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
    if data[:4] == MAGIC:
        _, ver, size = HEADER.unpack_from(data, 0)
        if ver != 2 or size != RECORD_V2.size:
            raise ValueError("%s: unknown trace format v%d, %d-byte records"
                             % (trace_path, ver, size))
        rs, body = RECORD_V2, data[HEADER.size:]
    else:
        rs, body = RECORD_V1, data          # pre-2026-09-06, headerless
    images = {}
    out = []
    for n in range(len(body) // rs.size):
        f = rs.unpack_from(body, n * rs.size)
        pc0, flags = (f[9], f[10]) if rs is RECORD_V2 else (0, 0)
        ev = Event(n, f[0], f[1], f[2], f[3], f[4], f[5], f[6], f[7], f[8],
                   pc0, flags, rel=_rel_of(f[0]))
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


def _mark_name_excursions(events: "list[Event]", images: dict) -> int:
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
      * the body is even PCs ascending from 2, each a character that decodes
        as cp932;
      * execution resumes inside a record (or the trace ends).

    Anything that fails those stays a disagreement.
    """
    def inside(ev):
        img = images.get(ev.rel)
        if img is None or ev.rec not in img.by_id:
            return None
        off = ev.pc - img.base[ev.rec]
        return off if 0 <= off <= len(img.by_id[ev.rec].data) else None

    def _tokens(ev):
        img = images.get(ev.rel)
        rec = img.by_id.get(ev.rec) if img else None
        return rec.tokens if rec is not None and rec.tokens is not None else None

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
        j, want, body = i + 1, 2, []
        while j < n and events[j].pc == want and events[j].ch > 0xFF and not events[j].ok:
            try:
                bytes([events[j].ch >> 8, events[j].ch & 0xFF]).decode("cp932")
            except UnicodeDecodeError:
                break
            body.append(j)
            want += 2
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




def _owned(entry, image_end: int):
    """The PC ranges that exist for one file: the real image, plus our tails."""
    out = [(0, image_end)]
    if entry is not None:
        for s in entry.spans:
            if s.tail:
                out.append((s.virt, s.virt + s.tail))
    return out


def _in_bounds(ranges, pc: int) -> bool:
    return any(lo <= pc < hi for lo, hi in ranges)


def _index_entry(img, rec_id: int):
    """Our model of the engine's index entry for one record: ``(off, len)``.

    The runtime index is 256 slots of ``{u16 offset, u16 length}``; a record the
    container does not carry is one byte long, which is what the loader leaves
    the slot at.  ``records.bases`` already encodes both halves.
    """
    if not img.base:
        return None
    r = img.by_id.get(rec_id)
    return img.base[rec_id], (len(r.data) if r is not None else records.ABSENT_LEN)


def _corroborated(img, ev) -> bool:
    """Does the engine's own index entry agree that ``ev`` names this file?

    ``file`` and ``rec`` come from two engine globals (``0x4911B0``,
    ``0x4911B2``) that are written when a script is *loaded*.  The interpreter
    runs whatever buffer its context points at and several scripts are resident
    at once, so while it runs an older one those globals still name the file
    loaded most recently -- the label is stale, and anything judged against it
    is judged against the wrong file.

    ``idx_off``/``idx_len`` are different: ``trace.S`` reads them out of the
    buffer the context actually points at.  So when they equal the entry our
    model gives that file for that record, both globals describe the running
    buffer and the label can be used.  When they do not, at least one of them
    does not, and there is no way to tell which -- so nothing is claimed.

    An event with no entry logged (a null context or handle, which the engine
    produces legitimately between scripts) is not corroborated either.
    """
    return bool(ev.idx_off) and _index_entry(img, ev.rec) == (ev.idx_off, ev.idx_len)


def paired(events, images) -> "tuple[int, int, int]":
    """``(agreeing, wrong byte, outside every tail)`` over virtual PCs.

    A virtual program counter -- one at or above the file's image end -- exists
    for exactly one reason: our hook put it there, because the English in some
    span did not fit where the Japanese was.  So for a file whose label the
    engine's index entry corroborates, every virtual PC in the trace has to lie
    inside one of that file's tails and carry the byte that tail holds.

    That makes this a test of whether the overlay handed to ``verify`` is the
    one that produced the trace, and it needs nothing stamped into either file.
    Drop one span and every virtual address above it shifts, so the bytes stop
    agreeing immediately.  Over the five traces on disk it separates them
    completely: the three taken on the overlay now installed agree on all
    31,430 of their virtual PCs, the two older ones disagree on 5,769.

    A program counter that is itself the *first* address of a tail is skipped.
    Landing there is the one fetch whose PC does not advance by one -- the hook
    hands it from the end of the in-place head straight to ``virt`` -- so the
    byte just read was in the head, at an address no subtraction recovers.
    Tails are allocated back to back, so this is also every ``vend``.
    """
    ok = wrong = outside = 0
    tails = {}
    for ev in events:
        img = images.get(ev.rel)
        if img is None or img.entry is None or not ev.pc0:
            continue
        if not _corroborated(img, ev):
            continue
        if ev.pc0 < img.entry.image_end:
            continue
        t = tails.get(ev.rel)
        if t is None:
            t = [s for s in img.entry.spans if s.tail]
            t.sort(key=lambda s: s.virt)
            t = (t, {s.virt for s in t})
            tails[ev.rel] = t
        spans, virts = t
        if ev.pc0 in virts:
            continue
        width = 2 if ev.ch > 0xFF else 1
        a = ev.pc0 - width
        want = (bytes([(ev.ch >> 8) & 0xFF, ev.ch & 0xFF]) if width == 2
                else bytes([ev.ch & 0xFF]))
        got = None
        for s in spans:
            if s.virt <= a and a + width <= s.vend:
                k = s.head + a - s.virt
                got = s.data[k:k + width]
                break
        if got is None:
            outside += 1
        elif got == want:
            ok += 1
        else:
            wrong += 1
    return ok, wrong, outside


def _served_bytes(img, pc: int, ch: int):
    """The bytes the overlay actually handed the engine at ``pc``, or None.

    ``pc`` here is ``pc0`` -- the program counter as the token was dispatched,
    which is one past what the caller fetched: one byte for an opcode (its
    operands are consumed later, inside the handler) or the width of the
    character for text.  The post-token ``pc`` will not do: after a pool call
    (opcodes ``01``-``08``, which our own spans contain wherever a word comes
    out of the dictionary) it names an address in the *pool* file, and asking
    this file about it produced a run of "byte does not match the original"
    findings against text that was ours and correct.

    A PC falling inside a span's address range only says where the hook *would*
    substitute.  What settles it is reconstructing the byte the hook would have
    returned and requiring it to equal what the engine logged -- so a one-byte
    token read ``english[pc-1]`` and a two-byte token read ``english[pc-2:pc]``.

    Asking the range alone was the first cut and it was wrong in every case
    sampled: a span serving ``'No one here...\\n'`` has ``0x20`` where the trace
    logged ``0x0D``.  If the overlay had served that byte the two would agree,
    so the engine was reading something else and the event is not the overlay's
    to answer for.
    """
    e = img.entry
    if e is None:
        return None
    one = bytes([ch & 0xFF])
    two = bytes([(ch >> 8) & 0xFF, ch & 0xFF]) if ch > 0xFF else None
    for s in e.spans:
        for lo, hi, data in ((s.start, s.start + s.head, s.data),
                             (s.virt, s.virt + s.tail, s.data[s.head:]) if s.tail
                             else (0, 0, b"")):
            if not hi:
                continue
            for width, want in ((1, one), (2, two)):
                if want is None:
                    continue
                start = pc - width
                if lo <= start and start + width <= hi:
                    got = data[start - lo:start - lo + width]
                    if got == want:
                        return want
    return None

def verify(trace_path: str, build_dir: "str | None" = None,
           overlay_path: "str | None" = None):
    """Did the overlay change control flow?  Answered from one English trace.

    The overlay's contract is local: for a translated span it serves English in
    place of the Japanese bytes and hands the program counter back at the span's
    end.  Two things follow, and both are checkable against a trace:

    * every token the engine dispatched from **outside** a served span must be
      the byte that is in the original file at that address -- the overlay must
      not have touched it;
    * every token dispatched from **inside** one must be text, or an inline
      opcode the codec is allowed to embed.  Never a branch.

    If both hold for every event, the instruction stream the interpreter walked
    *is* the Japanese instruction stream, and the English run cannot have gone
    anywhere the Japanese run would not.  That is why one trace is enough and no
    second play-through of the same route is needed -- which is what made the
    two-build ``diff`` expensive enough to keep being deferred.

    Returns ``(stats, findings)``.  A finding is
    ``(event, category, explanation)``.

    **What this does not prove.**  Flow equality on the routes actually walked,
    not universally; coverage grows with play.  And an event the decoder cannot
    place at all is counted as *unverified*, not as a pass -- those are the
    stale-context records the tracer's own notes describe, and pretending they
    are clean would be the whole point of the exercise thrown away.
    """
    build_dir = build_dir or paths.game_root()
    with open(trace_path, "rb") as fh:
        data = fh.read()
    entries = None
    # An explicit overlay lets a test pin a recorded trace against the exact
    # overlay that produced it: a trace means nothing against any other one, so
    # the two have to travel together.
    ovl = overlay_path or os.path.join(build_dir, "overlay.dat")
    if os.path.exists(ovl):
        with open(ovl, "rb") as fh:
            entries = overlay.parse(fh.read())

    if data[:4] == MAGIC:
        _, ver, size = HEADER.unpack_from(data, 0)
        if ver != 2 or size != RECORD_V2.size:
            raise ValueError("%s: unknown trace format v%d, %d-byte records"
                             % (trace_path, ver, size))
        rs, body = RECORD_V2, data[HEADER.size:]
    else:
        rs, body = RECORD_V1, data

    stats = {"records": 0, "served": 0, "from the file": 0, "unverified": 0,
             "in a name print": 0, "out of bounds": 0, "label contradicted": 0,
             "virtual PCs": 0, "unpaired virtual PCs": 0,
             "overlay entries": len(entries or [])}
    findings, images, events, bounds = [], {}, [], {}
    for n in range(len(body) // rs.size):
        f = rs.unpack_from(body, n * rs.size)
        pc0, flags = (f[9], f[10]) if rs is RECORD_V2 else (0, 0)
        ev = Event(n, f[0], f[1], f[2], f[3], f[4], f[5], f[6], f[7], f[8],
                   pc0, flags, rel=_rel_of(f[0]))
        events.append(ev)
        if ev.rel not in images:
            p = os.path.join(build_dir, *ev.rel.split("/"))
            images[ev.rel] = (_Image(ev.rel, open(p, "rb").read(), entries)
                              if os.path.exists(p) else None)

    # While the engine prints a runtime name the PC is inside a name buffer,
    # not the script, so its bytes are the name's characters and comparing them
    # with the script file is meaningless.  Without this the English names we
    # install read as script corruption -- 'e', ',', 'K' at consecutive PCs
    # just past a span serving 'Emi:'.
    _mark_name_excursions(events, images)

    # Is this overlay the one that produced this trace?  Asked before anything
    # is judged, because if it is not, every virtual address in the trace names
    # a different span than it did when it was recorded, and the findings are
    # about the wrong text.  That is what an older trace re-checked against a
    # newer overlay looks like, and it used to come out as 891 out-of-bounds
    # program counters instead of "these two do not go together".
    # Only the *wrong byte* count refuses.  A virtual PC that lands outside
    # every tail is left to the bounds check below, because that is exactly
    # what a stray program counter looks like -- refusing on it would let the
    # pairing gate swallow the bug the bounds check exists to find.  A stale
    # overlay is caught by the other half: shift or drop one span and every
    # address above it moves, so the addresses that are still claimed start
    # holding the wrong text.  Measured on the five traces on disk that is
    # enough on its own (0, 0, 0 against 1,871 and 3,008).
    ok, wrong, outside = paired(events, images)
    stats["virtual PCs"] = ok + wrong + outside
    stats["unpaired virtual PCs"] = wrong
    if wrong:
        stats["records"] = len(events)
        ev = events[0] if events else Event(0, 0, 0, 0, 0, 0, 0, 0)
        return stats, [(ev, "the overlay is not the one that produced this trace",
                        "%d of %d virtual program counters hold a different byte "
                        "than this overlay puts there.  Virtual addresses exist "
                        "only because the hook creates them, so this is not a "
                        "property of the game: either this is not the overlay "
                        "that ran -- the usual case, the tables changed since -- "
                        "or the hook did not serve what this overlay says "
                        "(tests/test_overlay.py is what settles that half).  "
                        "Either way, re-run the route on this build first."
                        % (wrong, ok + wrong + outside))]

    for ev in events:
        stats["records"] += 1
        if ev.kind == NAME_KIND:
            stats["in a name print"] += 1
            continue
        img = images[ev.rel]
        if img is None:
            stats["unverified"] += 1
            continue

        # Whose file is this really?  The label comes from an engine global
        # written on load, not on every context switch, so it can name a file
        # the interpreter is not running -- and then every question below is
        # asked of the wrong file.  Nothing is claimed unless the engine's own
        # index entry says the label describes the live buffer.
        if not _corroborated(img, ev):
            stats["label contradicted"] += 1
            continue

        # Does this program counter exist at all?  Checked before anything
        # else, because a PC that belongs to nobody makes every other question
        # meaningless -- the bytes it reads are whatever follows the record
        # buffer in memory.
        if ev.pc0:
            ranges = bounds.get(ev.rel)
            if ranges is None:
                # A file the overlay never touched still has a real image, and
                # its end is where the last record stops.  Computed rather than
                # read off an entry, so such a file is checked just as strictly.
                end = max((b + len(img.by_id[i].data)
                           for i, b in img.base.items() if i in img.by_id),
                          default=0)
                ranges = _owned(img.entry,
                                img.entry.image_end if img.entry else end)
                bounds[ev.rel] = ranges
            if not _in_bounds(ranges, ev.pc0):
                stats["out of bounds"] += 1
                findings.append((ev, "program counter outside the file and our overlay",
                                 "pc0 0x%04X is past the image and in no virtual "
                                 "range we declared; the engine is executing memory "
                                 "nobody owns.  The other reading is an overlay "
                                 "that has changed above every virtual address "
                                 "this route still agrees on -- rare, but check "
                                 "the trace is from this build before acting"
                                 % ev.pc0))
                continue

        served = _served_bytes(img, ev.pc0 or ev.pc, ev.ch)
        if served is not None:
            stats["served"] += 1
            if served[0] in FLOW_OPCODES and len(served) == 1:
                findings.append((ev, "branch served from our English",
                                 "the engine dispatched 0x%02X at pc 0x%04X out "
                                 "of bytes the overlay supplied"
                                 % (served[0], ev.pc)))
            continue

        hit = img.locate(ev.rec, ev.pc, ev.ch, ev.idx_off or None, ev.pc0 or None)
        if hit is None:
            stats["unverified"] += 1
            continue
        ev.span, ev.anchor, ev.kind, ev.ok = hit
        stats["from the file"] += 1
        if not ev.ok:
            findings.append((ev, "byte does not match the original",
                             "logged 0x%04X at pc 0x%04X, but %s has something "
                             "else there" % (ev.ch, ev.pc, ev.rel)))
    return stats, findings


def report_verify(trace_path: str, build_dir: "str | None" = None,
                  limit: int = 20, overlay_path: "str | None" = None):
    stats, findings = verify(trace_path, build_dir, overlay_path)
    out = ["%s" % os.path.basename(trace_path)]
    # The pairing gate answers before anything is placed, so it is reported
    # before the placement line -- otherwise a refused trace reads as "wrong
    # build directory", which sends the reader looking in the wrong place.
    unpaired = [f for f in findings if "not the one that produced" in f[1]]
    if unpaired:
        out.append("  REFUSED: %s" % unpaired[0][1])
        out.append("    %s" % unpaired[0][2])
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
    if stats["label contradicted"]:
        out.append("  %d record(s) whose file label the engine's own index entry"
                   " contradicts;" % stats["label contradicted"])
        out.append("    nothing is claimed about those -- the file register is "
                   "written on load,")
        out.append("    not on every context switch")
    if stats["virtual PCs"]:
        out.append("  %d virtual program counter(s), all of them served by this "
                   "overlay" % stats["virtual PCs"])
    if stats["out of bounds"]:
        out.append("  %d program counter(s) outside the file AND our overlay"
                   % stats["out of bounds"])
    if not findings:
        out.append("")
        out.append("  CLEAN: every token dispatched outside a served span "
                   "matched the original")
        out.append("  file, and every token inside one was text or an inline "
                   "opcode.  Over this")
        out.append("  route the overlay did not change control flow.")
        return "\n".join(out), 0
    out.append("")
    out.append("  %d FINDING(S):" % len(findings))
    for ev, cat, why in findings[:limit]:
        out.append("    #%d %s rec 0x%02X pc 0x%04X: %s" % (ev.n, ev.rel, ev.rec,
                                                            ev.pc, cat))
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
    if data[:4] == MAGIC:
        _, ver, size = HEADER.unpack_from(data, 0)
        rs, body = RECORD_V2, data[HEADER.size:]
    else:
        rs, body = RECORD_V1, data
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
