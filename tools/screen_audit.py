"""What Japanese actually reached the screen in a play session, and why.

    python tools/screen_audit.py <textout.bin> [--trace <trace.bin>]
                                 [--tables DIR] [--build DIR]
                                 [--min N] [--csv OUT.tsv]

The translation tables say what *should* draw.  `giten check` says what is
unreviewed.  Neither says what a player actually saw, and those differ: a row
can be translated, reviewed and still render in Japanese because the overlay
failed to serve it.  This reads a dev build's glyph log -- the record of every
character the game drew -- and reports the Japanese that survived, ranked by how
often the player saw it, with a verdict on the cause of each.

Verdicts, and what each one means for the fix:

    NO TABLE ROW    no row anywhere carries this text.  It lives in a file no
                    extractor reads.  Fix: find the file, then the extractor.
    NOT TRANSLATED  the row exists and `en` is empty.  Fix: translate it.
    EN IS JAPANESE  `en` is set but what it *renders to* still holds kana or
                    kanji -- including English that splices an untranslated
                    pool call.  Fix: finish it, or the pool record it calls.
    SERVED?         the row has clean English and the game drew Japanese
                    anyway.  Nothing is wrong with the table -- this is an
                    overlay-side fault.  See docs/overlay.md.

Each verdict is also reported as ``DATA <verdict>`` when the string belongs to
one of the flat ``et/`` tables (skills, map labels, districts, race names, the
item database) rather than to the script: those have their own tables and their
own build commands, so the fix is a different one.

**Attribution.**  With ``--trace`` the tool names the row *the engine was
standing in when it drew the fragment*, rather than whichever row happens to
contain the same characters: it searches the trace's own ``ch`` stream for the
fragment's cp932 bytes, takes that event's ``(rec, idx_len, rec_hash)`` -- the
same content key overlay v6 uses -- and resolves it to a record, an offset
inside it, and the table row that owns that offset.  Without ``--trace`` it
falls back to substring matching over every table, which *cannot* distinguish
two rows that share a phrase, and says so in the output.

Three details that are easy to get wrong and that this handles:

* **The glyph log's character code is a u16 in a u32 field.**  `textlog.Rec.ch`
  masks it; reading the raw dword instead emits a spurious high byte for about
  one glyph in nine, which corrupts the fragment and reports "no table row" for
  text that is sitting in a table.  This reads the log through
  ``giten.textlog.read``/``calls``, which is the same reader ``giten trace
  textout`` uses.
* **Pool calls must be expanded, not stripped.**  A drawn line is contiguous
  kana; the file stores ``手に入{08:60}`` and ``{08:60}`` is ``れた``.  Deleting
  the marker breaks the join and reports "no table row" for text that is sitting
  right there in a table.  The same is true on the English side, which is why
  the verdict runs ``check_v2.render_english`` rather than looking at ``en``.
* **The tables to audit are the ones that were built.**  The playable build
  comes from ``build/tables_draft`` (every ``ref_en`` promoted), not from
  ``tables/``.  Auditing ``tables/`` against a draft build reports hundreds of
  rows as untranslated that shipped in English.  ``--tables`` defaults to
  ``build/tables_draft`` when it exists.

The log is truncated every time the game launches, so run this against a copy.
"""
from __future__ import annotations

import collections
import io
import os
import re
import sys

R = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, R)

from giten import check_v2, paths, pool, tables, textlog  # noqa: E402

#: kana and kanji.  NOT U+FF01..U+FF60: that is the fullwidth ASCII block, where
#: the game's own digits live (the damage printer converts every ASCII digit
#: into one), and counting those calls "1" untranslated Japanese.
RUN = re.compile(r"[぀-ヿ一-鿿]+")
MARK = re.compile(r"\{[0-9A-Fa-f:]+\}|<wait>|\\n")


#: draw-string variants that are typewriters -- one call per glyph.  Counting
#: those calls separately shreds every sentence into single characters, so runs
#: of consecutive calls from the same variant are glued back together.
TYPEWRITER = {6}


def has_jp(s: str) -> bool:
    return bool(RUN.search(s))


def drawn_strings(path):
    """``(variant, bytes)`` per drawn string, with typewriter runs glued."""
    out, cur = [], None
    for variant, _args, drawn in textlog.calls(textlog.read(path)):
        if cur is not None and variant in TYPEWRITER and cur[0] == variant:
            cur[1].extend(drawn)
            continue
        if cur is not None:
            out.append((cur[0], bytes(cur[1])))
        cur = (variant, bytearray(drawn))
    if cur is not None:
        out.append((cur[0], bytes(cur[1])))
    return out


# ------------------------------------------------------------- data tables --
#
# The flat `et/` tables are not script and have their own extractors, their own
# TSVs and their own build commands (`giten etdb`, `giten districts`, `giten
# racenames`, `giten itemdb`).  A fragment drawn from one of them must not be
# matched against the script tables: 新宿 appears in 148 dialogue rows, and
# crediting one of them would report "not translated, here is the row" about a
# row the location strip never reads.
#
# Until 2026-09-11 this module carried a hard-coded UNEXTRACTED entry saying
# et/ET000D had no extractor.  It has had one since the districts work; the sets
# are now read from the tables themselves, so a file that gains an extractor
# stops being reported as lacking one without anybody editing this list.


def data_strings():
    """``{japanese: (source, english)}`` over every flat ``et/`` table."""
    out = {}

    def add(src, jp, en):
        if jp and has_jp(jp):
            out.setdefault(jp, (src, en or ""))

    from giten import districts, etdb, itemdb, racenames

    for name, spec in sorted(etdb.SPECS.items()):
        english = etdb.read_table(spec)
        for rec in etdb.parse(spec, etdb.source(spec, paths.ORIGINAL_DDSWIN)):
            for i in range(spec.fields):
                add("%s (%s)" % (spec.rel, name), rec.text(i),
                    english.get((rec.index, i), ""))

    for fn, src in ((districts, "et/ET000D.BIN (districts)"),
                    (racenames, "et/ET0000.BIN (race names)")):
        try:
            pairs = fn.audit_pairs()
        except AttributeError:
            pairs = _pairs_from_tsv(fn)
        for jp, en in pairs:
            add(src, jp, en)

    # The exe's own .rdata strings.  Not a "table" at all, but the same thing
    # is true of them: they have their own translator (giten/exe/menus.py,
    # names.py) and matching them against the script tables credits a dialogue
    # row for a word the analyze box drew.  敵対的 was reported that way.
    try:
        from giten.exe import menus, names, patch
        from giten.exe.pe import PE
        with open(patch.ORG, "rb") as fh:
            img = fh.read()
        pe = PE(img, "audit")
        for va, en in menus.STRINGS.items():
            try:
                add("dds.exe (menus.py)", menus.cstring_at(img, pe, va), en)
            except (ValueError, UnicodeDecodeError):
                pass
        for jp, en in menus.EFFECTS:
            add("dds.exe (menus.py EFFECTS)", jp, en)
        for jp, en in names.NAMES.items():
            add("dds.exe (names.py)", jp, en)
    except Exception:
        pass

    for name, jpcol, encol in (("mapnames.tsv", 1, 2),):
        p = os.path.join(paths.REPO_ROOT, "tables", name)
        if not os.path.exists(p):
            continue
        for line in io.open(p, encoding="utf-8"):
            if line.startswith("#") or not line.strip():
                continue
            f = line.rstrip("\n").split("\t")
            if len(f) > encol:
                add("tables/" + name, f[jpcol], f[encol])

    table = os.path.join(paths.REPO_ROOT, "tables", "itemdb.tsv")
    if os.path.exists(table):
        recs = itemdb.parse(itemdb.source_body(paths.ORIGINAL_DDSWIN))
        english = itemdb.read_table(table)
        for rec in recs:
            row = english.get(rec.index)
            en_name, en_desc = (row[0], row[1]) if row else ("", "")
            for raw, en in ((rec.name, en_name), (rec.desc, en_desc)):
                try:
                    add("et/ET0001.BIN (items)", (raw or b"").decode("cp932"), en)
                except UnicodeDecodeError:
                    pass
    return out


def _pairs_from_tsv(mod):
    """``[(jp, en)]`` from a module's own TSV, whatever its column names are."""
    path = getattr(mod, "TABLE", None)
    if path is None:
        for attr in dir(mod):
            v = getattr(mod, attr)
            if isinstance(v, str) and v.endswith(".tsv"):
                path = v
                break
    if not path or not os.path.exists(path):
        return []
    out, head = [], None
    for line in io.open(path, encoding="utf-8"):
        if line.startswith("#") or not line.strip():
            continue
        f = line.rstrip("\n").split("\t")
        if head is None:
            head = f
            continue
        d = dict(zip(head, f))
        jp = d.get("jp") or d.get("jp_name") or ""
        en = d.get("en") or d.get("en_name") or ""
        if jp:
            out.append((jp, en))
    return out


# ------------------------------------------------------------------- rows ---

def default_tables():
    draft = os.path.join(paths.BUILD_DIR, "tables_draft")
    return draft if os.path.isdir(draft) else os.path.join(R, "tables")


def load_rows(text_dir, pools):
    """Every table row, with its Japanese pool-expanded for matching."""
    rows = []
    for p in tables.iter_tables(text_dir):
        for r in tables.read(p):
            r._table = os.path.relpath(p, R).replace(os.sep, "/")
            r._flat = MARK.sub("", pool.reading(r.jp, pools)) if r.jp else ""
            rows.append(r)
    return rows


def verdict_of(row, epool):
    """The verdict for one row, judged on what its English *renders to*."""
    if row is None:
        return "NO TABLE ROW"
    if not row.en.strip():
        return "NOT TRANSLATED"
    if has_jp(MARK.sub("", check_v2.render_english(row.en, epool))):
        return "EN IS JAPANESE"
    return "SERVED?"


# -------------------------------------------------------------- the trace ---

def ch_stream(events):
    """The bytes the interpreter dispatched, plus which event produced each."""
    buf, owner = bytearray(), []
    for i, ev in enumerate(events):
        c = ev.ch
        if c > 0xFF:
            buf += bytes([(c >> 8) & 0xFF, c & 0xFF])
            owner += [i, i]
        elif c:
            buf.append(c)
            owner.append(i)
    return bytes(buf), owner


def corpus_index(root=None):
    """``{(id, len, FNV-1a): (rel, container, bytes)}``.

    The same key :func:`giten.trace.core.corpus_records` builds, but carrying
    where the bytes came from -- which is what turns a trace event into a table
    row.
    """
    from giten import container, overlay, records
    root = root or paths.ORIGINAL_DDSWIN
    out = {}
    for sub in ("m", "et"):
        d = os.path.join(root, sub)
        if not os.path.isdir(d):
            continue
        for name in sorted(os.listdir(d)):
            if not name.lower().endswith(".bin"):
                continue
            rel = "%s/%s" % (sub, name)
            try:
                with open(os.path.join(d, name), "rb") as fh:
                    conts, _end = container.split(fh.read())
            except Exception:
                continue
            for ci, c in enumerate(conts):
                try:
                    recs = records.parse_body(c.body).records
                except Exception:
                    continue
                keep = {}
                for r in recs:
                    keep[r.id] = r          # last wins, as the loader does
                for r in keep.values():
                    key = (r.id, len(r.data), overlay.fnv1a(r.data))
                    out.setdefault(key, (rel, ci, r.data))
    return out


class Attributor:
    """Names the row the engine was standing in when a fragment was drawn."""

    def __init__(self, trace_path, build_dir, rows, root=None):
        from giten import overlay
        from giten.trace import core
        self.events = core.decode(trace_path, build_dir)
        self.stream, self.owner = ch_stream(self.events)
        self.corpus = corpus_index(root)
        self.entries, _findings = overlay.plan(rows, root)
        self.by_key = {e.key: e for e in self.entries}
        self.by_row = {}
        for r in rows:
            self.by_row.setdefault((r.file, r.rec), []).append(r)
        for v in self.by_row.values():
            v.sort(key=lambda r: r.off)

    def attribute(self, fragment):
        """``(row, note)`` for the event that drew ``fragment``.

        The drawn fragment is contiguous kana on screen, but in the *stored*
        bytes it can be interrupted by pool calls -- ``へ続く階段が{08:7B}ある``
        draws as one run and is three tokens.  The ``ch`` stream is the tokens,
        so the whole fragment is often not contiguous in it.  Matching therefore
        walks down from the whole fragment to its longest prefix that is, which
        is enough: the event that drew the first characters is the event that
        was standing in the record that owns the line.

        A hit whose record content actually holds those bytes at the offset the
        event reports is preferred over one that does not.  On a v4 trace the
        record id comes from the stale ``RECID`` global rather than from the
        program counter (Item 1), so the content check is what separates the
        events that were charged to the right record from the ones that were
        not.
        """
        try:
            full = fragment.encode("cp932")
        except UnicodeEncodeError:
            return None, "not cp932"
        fallback = None
        n = len(full)
        while n >= 4:
            needle, seen = full[:n], 0
            chars = len(needle.decode("cp932", "ignore"))
            how = "" if n == len(full) else ", first %d chars" % chars
            at = self.stream.find(needle)
            while at >= 0 and seen < 64:
                seen += 1
                row, note, ok = self._row_for(self.events[self.owner[at]], needle)
                if row is not None:
                    if ok:
                        return row, note + how
                    if fallback is None:
                        fallback = (row, note + how)
                at = self.stream.find(needle, at + 1)
            if fallback is not None:
                return fallback
            n -= 2 if n >= 6 else 1
        return None, "no trace event drew it"

    def _row_for(self, ev, needle):
        """``(row, note, content-confirmed)``.

        The confirmation is on the event's **own** character, not on the whole
        needle: a prefix that runs into a pool call is contiguous on screen and
        in the ``ch`` stream but not in any one record's bytes, because the
        pool's characters come out of a different record.  What can be checked
        is that the record this event was charged to really holds the character
        it drew, at the offset it reports -- which is exactly the question a v4
        trace's stale ``RECID`` puts in doubt.
        """
        if not ev.idx_len or not ev.rec_hash:
            return None, "event has no record", False
        key = (ev.rec, ev.idx_len, ev.rec_hash)
        hit = self.corpus.get(key)
        if hit is None:
            return None, "record content not in the corpus", False
        rel, ci, data = hit
        mine = (bytes([(ev.ch >> 8) & 0xFF, ev.ch & 0xFF]) if ev.ch > 0xFF
                else bytes([ev.ch]) if ev.ch else b"")
        # `pc0` is one past the token it logged (docs/limits.md), so the
        # character's own offset in the record is `pc0 - idx_off - len`.  Both
        # readings are tried and the one the bytes agree with is taken, which
        # makes the check the thing that decides rather than the comment.
        off = None
        base = ev.pc0 - ev.idx_off
        for cand in (base - len(mine), base):
            if mine and 0 <= cand and data[cand:cand + len(mine)] == mine:
                off = cand
                break
        ok = off is not None
        if off is None:
            off = base - len(mine) if base >= len(mine) else None
        note = "trace" if ok else "trace (record unconfirmed)"
        ent = self.by_key.get(key)
        if ent is not None and off is not None:
            for sp in ent.spans:
                if sp.rec_off <= off < sp.rec_off + sp.jp_len and sp.sources:
                    srel, sci, rid, idx = sp.sources[0]
                    for r in self.by_row.get((srel, "%d:%02X" % (sci, rid)), ()):
                        if r.idx == idx:
                            return r, note + ", overlay span", ok
        cands = self.by_row.get((rel, "%d:%02X" % (ci, key[0])), ())
        best = None
        for r in cands:
            if off is None or r.off <= off:
                best = r
        return best, note, ok and best is not None


# ------------------------------------------------------------------- main ---

def _arg(argv, name, default=None):
    return argv[argv.index(name) + 1] if name in argv else default


def main(argv):
    if not argv or argv[0].startswith("-"):
        raise SystemExit(__doc__.strip().splitlines()[2].strip())
    path = argv[0]
    lo = int(_arg(argv, "--min", 1))
    csv = _arg(argv, "--csv")
    trace = _arg(argv, "--trace")
    text_dir = _arg(argv, "--tables") or default_tables()
    build_dir = _arg(argv, "--build")

    out = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    pools = pool.load()
    rows = load_rows(text_dir, pools)
    epool = check_v2.english_pool(rows)
    data = data_strings()

    att = None
    if trace:
        att = Attributor(trace, build_dir or paths.game_root(), rows)

    drawn_jp = collections.Counter()
    calls = 0
    for _variant, drawn in drawn_strings(path):
        calls += 1
        if not drawn:
            continue
        s = drawn.decode("cp932", "replace").rstrip("\0")
        if has_jp(s):
            drawn_jp[s] += 1

    frags = collections.Counter()
    for s, n in drawn_jp.items():
        for run in RUN.findall(s):
            if len(run) >= 2:
                frags[run] += n

    out.write("%s\n" % os.path.basename(path))
    out.write("  %d draw-string calls, %d drew Japanese, %d distinct fragments\n"
              % (calls, sum(drawn_jp.values()), len(frags)))
    out.write("  tables: %s\n" % os.path.relpath(text_dir, R).replace(os.sep, "/"))
    if att is None:
        out.write("  NO TRACE: rows are matched by substring, so a phrase two "
                  "rows share is credited to the shorter one.  Pass --trace "
                  "for the row the engine was actually in.\n")
    else:
        out.write("  trace: %s (%d events)\n"
                  % (os.path.basename(trace), len(att.events)))
    out.write("\n")

    weighted = collections.Counter()
    lines = []
    for run, n in frags.most_common():
        src = data.get(run)
        row, how, nhit = None, "", 0
        if src is not None:
            v = "DATA " + ("SERVED?" if src[1].strip() else "NOT TRANSLATED")
            how = src[0]
        else:
            if att is not None:
                row, how = att.attribute(run)
                nhit = 1 if row is not None else 0
            if row is None:
                hits = [d for d in rows if d._flat and run in d._flat]
                nhit = len(hits)
                row = min(hits, key=lambda d: len(d._flat)) if hits else None
                how = (how + "; " if how else "") + "substring"
            v = verdict_of(row, epool)
        weighted[v] += n
        lines.append((n, v, run, row, nhit, how))

    total = sum(weighted.values()) or 1
    out.write("  cause, weighted by how often the player saw it:\n")
    for v, n in weighted.most_common():
        out.write("     %-20s %5d  %4.1f%%\n" % (v, n, 100.0 * n / total))
    out.write("\n")

    for n, v, run, row, nhit, how in lines:
        if n < lo:
            continue
        out.write("%6d  %-20s %s\n" % (n, v, run))
        out.write("            via: %s\n" % how)
        if row is not None:
            out.write("            %s %s[%s]  status=%s%s\n"
                      % (row._table, row.rec, row.idx, row.status,
                         "  (+%d other rows)" % (nhit - 1) if nhit > 1 else ""))
            out.write("            jp: %s\n" % row.jp[:110])
            out.write("            en: %s\n" % row.en[:110])
        out.write("\n")

    if csv:
        with open(csv, "w", encoding="utf-8", newline="\n") as fh:
            fh.write("draws\tverdict\tfragment\tvia\ttable\trec\tidx\tstatus\ten\n")
            for n, v, run, row, _nhit, how in lines:
                fh.write("%d\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n"
                         % (n, v, run, how,
                            getattr(row, "_table", "") if row else "",
                            row.rec if row else "", row.idx if row else "",
                            row.status if row else "",
                            (row.en if row else "").replace("\t", " ")))
        out.write("wrote %s\n" % csv)
    out.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
