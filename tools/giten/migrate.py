"""``migrate --from text --to text_v2``: carry finished translations forward.

Five translators are editing ``text/`` while this runs, so migration is strictly
additive and one-way: it **reads** ``text/``, extracts a fresh set of v2 tables,
copies every real translation across, and writes only under ``text_v2/``.
Nothing under ``text/`` is touched.

Matching a v1 row to a v2 row
-----------------------------
The two extractions disagree about where a span starts and how it is framed --
that is the whole point of the upgrade -- so several keys are tried in order,
strongest first, and each v2 row is claimed at most once:

1. **byte offset.**  Both extractions read the same shipped bytes, and a v1
   ``off`` is an offset into ``unxor(raw[2:])`` while a v2 span's offset resolves
   to ``container.off + record data offset + span offset`` in the same raw file.
   For the great majority of rows these are the *same byte*, which makes this
   an exact identity rather than a similarity guess.
2. **(record id, span index)** within the record.  v1 named a record ``R7:AA``
   only in the files it framed as pools; for the rest the record id is recovered
   from the row's offset, so this key works everywhere.
3. **identical text within the same record** -- the v2 span rendered the way v1
   would have rendered it (``08 nn`` expanded, control tokens stripped).
4. **identical text, unique within the file.**

Only *real* translations are carried: a v1 row whose ``en`` equals its ``jp`` was
a pre-fill of already-English source, and the v2 extractor re-derives those
itself from the current bytes.

Operand quarantine
------------------
796 v1 rows carry an ``@operand`` marker -- spans that were really opcode
operands leaking into text.  Their ``en`` is deliberately **not** carried: the v2
``jp`` for that place is a different (correct) string and needs translating from
scratch.  The report prints the old and new ``jp`` side by side for every one of
them, so the fix can be eyeballed.
"""
from __future__ import annotations

import collections
import os
import re

from . import (codec, extract_v2, files, paths, pool, script, tables, tokens)

OPERAND_MARKER = "@operand"


# --- the v1-comparable rendering of a v2 span -------------------------------
def legacy_key(rec, sp, pools) -> str:
    """A v2 span rendered the way v1 rendered the same bytes, tokens stripped.

    v1 expanded ``08 nn`` (and only ``08 nn``) into literal text and dropped
    every other control token, so reproducing that gives a key the two
    extractions agree on wherever they found the same run of text.
    """
    out = []
    for t in rec.tokens[sp.tok_lo:sp.tok_hi]:
        if t.kind == "text":
            try:
                out.append(rec.data[t.off:t.end].decode("cp932"))
            except UnicodeDecodeError:
                pass
        elif t.idx == 0x008 and t.ops:
            out.append(pool.expand(0x008, t.ops[0].value, pools))
    return "".join(out)


_V1_TOKEN_RE = re.compile(r"\\.|<wait>|\{DICT:[0-9A-Fa-f]{2}\}|\{[0-9A-Fa-f]{2}\}")


def port_en(new_jp: str, en: str) -> "tuple[str | None, str]":
    """Rewrite a v1 translation into the v2 token language.

    v1 rendered a pool call as a bare ``{01}`` and then let the operand byte leak
    into the following text; v2 renders the same two bytes as one ``{01:03}``.  A
    carried ``en`` therefore has to have its tokens re-bound, and the binding
    comes from the *new* ``jp``: the k-th ``{01}`` in the English is the k-th
    ``{01:nn}`` of the correctly-tokenized source line.

    Returns ``(ported, "")`` or ``(None, why)``.  A refusal is the right answer
    for the rows where v1's reading was wrong at the byte level -- an ``en``
    containing ``{0B}`` or ``{0C}`` was written against a branch opcode that v1
    mistook for an inline insert, so there is nothing to port it onto.
    """
    avail = collections.defaultdict(list)
    for t in codec.control_tokens(new_jp):
        m = re.match(r"\{(0[1-8]):([0-9A-Fa-f]{2})\}$", t)
        if m:
            avail[m.group(1).upper()].append(t)
    used = collections.Counter()

    out = []
    i = 0
    n = len(en)
    while i < n:
        m = _V1_TOKEN_RE.match(en, i)
        if not m:
            out.append(en[i])
            i += 1
            continue
        tok = m.group(0)
        i = m.end()
        if tok.startswith("\\") or tok == codec.WAIT_TOKEN:
            out.append(tok)
            continue
        if tok.startswith("{DICT:"):
            return None, "unresolved v1 dictionary reference %s" % tok
        hh = tok[1:3].upper()
        if hh not in avail:
            return None, ("v1 control token %s has no counterpart in the v2 "
                          "source line" % tok)
        k = used[hh]
        used[hh] += 1
        if k >= len(avail[hh]):
            return None, "more %s tokens in the translation than in the source" % tok
        out.append(avail[hh][k])
    ported = "".join(out)
    try:
        codec.encode(ported)
    except codec.CodecError as exc:
        return None, str(exc)
    return ported, ""


def _v1_record_id(rec: str) -> "int | None":
    """``"R7:AA"`` -> 0xAA.  ``"F0"`` (v1's un-framed files) -> ``None``."""
    if rec.startswith("R") and ":" in rec:
        try:
            return int(rec.split(":", 1)[1], 16)
        except ValueError:
            return None
    return None


class V2Index:
    """The v2 rows of one game file, indexed by every key migration can use."""

    def __init__(self, rel: str, raw: bytes, pools):
        self.rel = rel
        self.rows = []
        self.by_offset = {}
        self.by_rec_idx = {}
        self.by_rec_text = collections.defaultdict(list)
        self.by_text = collections.defaultdict(list)
        self.record_at = []          # sorted (lo, hi, record id) in raw coords
        self.claimed = set()

        if rel.startswith("p/"):
            self.rows = extract_v2.pname_rows(rel, raw)
            for r in self.rows:
                self.by_offset[r.off] = r
            return
        sc = script.parse(rel, raw)
        if not sc.ok:
            return
        self.rows = extract_v2.script_rows(rel, sc, pools)
        rowmap = {(r.rec, r.idx): r for r in self.rows}
        for rec in sc.iter_records():
            lo = rec.raw_off - 2         # v1's body index == raw index - 2
            self.record_at.append((lo, lo + len(rec.data), rec.id))
            if rec.untiled:
                continue
            for sp in rec.spans:
                row = rowmap.get((sp.rec_key, sp.idx))
                if row is None:
                    continue
                self.by_offset[lo + sp.off] = row
                self.by_rec_idx[(rec.id, sp.idx)] = row
                key = legacy_key(rec, sp, pools)
                if key.strip():
                    self.by_rec_text[(rec.id, key)].append(row)
                    self.by_text[key].append(row)
        self.record_at.sort()

    def record_of(self, off: int) -> "int | None":
        import bisect

        i = bisect.bisect_right(self.record_at, (off, float("inf"), 0)) - 1
        if 0 <= i < len(self.record_at):
            lo, hi, rid = self.record_at[i]
            if lo <= off < hi:
                return rid
        return None

    def take(self, row) -> "tables.Row | None":
        if row is None or row.key in self.claimed:
            return None
        self.claimed.add(row.key)
        return row

    def match(self, old: tables.Row) -> "tuple[tables.Row | None, str]":
        r = self.take(self.by_offset.get(old.off))
        if r is not None:
            return r, "offset"
        rid = self.record_of(old.off)
        # (record, index) is only meaningful where v1 *had* a record framing --
        # its "R7:AA" pool rows.  In a v1 "F0" flat file `idx` counts spans across
        # the whole file, so keying on it would manufacture confident nonsense.
        if rid is not None and _v1_record_id(old.rec) == rid:
            r = self.take(self.by_rec_idx.get((rid, old.idx)))
            if r is not None:
                return r, "rec+idx"
        key = tokens.strip_tokens(old.jp)
        if key.strip():
            if rid is not None:
                cands = [c for c in self.by_rec_text.get((rid, key), [])
                         if c.key not in self.claimed]
                if len(cands) == 1:
                    return self.take(cands[0]), "rec+text"
            cands = [c for c in self.by_text.get(key, []) if c.key not in self.claimed]
            if len(cands) == 1:
                return self.take(cands[0]), "text"
        return None, "unmatched"


# --- run --------------------------------------------------------------------
def run(from_dir: "str | None" = None, to_dir: "str | None" = None,
        root: "str | None" = None, quiet: bool = False,
        report_path: "str | None" = None) -> dict:
    from_dir = from_dir or paths.TEXT_DIR
    to_dir = to_dir or extract_v2.text_v2_dir()
    pools = pool.load(root)

    old_by_file = collections.defaultdict(list)
    for p in tables.iter_tables(from_dir):
        for r in tables.read(p):
            old_by_file[r.file].append(r)

    st = collections.Counter()
    how = collections.Counter()
    unmatched = []
    quarantine = []
    by_table, order = {}, []

    for rel in files.iter_files(files.TEXT_FAMILIES, root):
        raw = files.read_source(rel, root)
        idx = V2Index(rel, raw, pools)
        if not idx.rows:
            if rel in old_by_file:
                for old in old_by_file[rel]:
                    if old.en and old.en != old.jp:
                        st["dropped_no_v2_rows"] += 1
                        unmatched.append((rel, old, "file has no v2 text layer"))
            continue
        st["v2_rows"] += len(idx.rows)
        for old in old_by_file.get(rel, []):
            st["v1_rows"] += 1
            is_quarantine = OPERAND_MARKER in old.note
            real = bool(old.en) and old.en != old.jp
            new, key = idx.match(old)
            how[key] += 1
            if new is None:
                if real and not is_quarantine:
                    st["unmatched_translations"] += 1
                    unmatched.append((rel, old, "no v2 row"))
                elif is_quarantine:
                    quarantine.append((rel, old, None))
                    st["quarantine_unmatched"] += 1
                continue
            if is_quarantine:
                quarantine.append((rel, old, new))
                st["quarantine_carried_empty"] += 1
                new.en = "" if codec.has_japanese(new.jp) else new.jp
                new.note = _add_note(new.note, "was @operand in v1; jp is now "
                                               "correct and needs translating")
                continue
            if real and script.NOEDIT_NOTE in new.note:
                # The v2 pipeline will not edit this record, so an `en` here
                # could never reach a build.  Keep the work in the note rather
                # than parking a translation somewhere it silently does nothing.
                st["landed_on_noedit"] += 1
                new.note = _add_note(new.note, "v1 translation, not applicable "
                                               "here: " + old.en)
                continue
            if real:
                ported, why = port_en(new.jp, old.en)
                if ported is None:
                    st["unportable"] += 1
                    unmatched.append((rel, old, "cannot be ported: " + why))
                    new.note = _add_note(
                        new.note, "v1 had a translation here but it was written "
                                  "against a mis-read line (%s); re-translate" % why)
                else:
                    new.en = ported
                    st["carried"] += 1
                    if ported != old.en:
                        st["retokenised"] += 1
                    if old.note:
                        new.note = _add_note(new.note, _carry_note(old.note))
            elif old.note and _carry_note(old.note):
                new.note = _add_note(new.note, _carry_note(old.note))

        path = files.table_path(rel, to_dir)
        if path not in by_table:
            by_table[path] = []
            order.append(path)
        by_table[path].extend(idx.rows)

    for path in order:
        tables.write(path, by_table[path])
        st["tables"] += 1

    report = _format_report(st, how, unmatched, quarantine, from_dir, to_dir)
    report_path = report_path or os.path.join(paths.BUILD_DIR, "migrate-report.txt")
    os.makedirs(os.path.dirname(report_path), exist_ok=True)
    with open(report_path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(report)
    if not quiet:
        print(report)
        print("full report written to %s"
              % os.path.relpath(report_path, paths.REPO_ROOT))
    return {"stats": st, "how": how, "unmatched": unmatched,
            "quarantine": quarantine, "report": report}


#: v1 note fragments that describe the v1 tokenizer's mistakes, not the text.
_STALE_NOTES = ("runtime inserts", "suspect:", "unresolved dictionary reference",
                OPERAND_MARKER)


def _carry_note(note: str) -> str:
    keep = [p for p in note.split("; ")
            if p.strip() and not any(s in p for s in _STALE_NOTES)]
    return "; ".join(keep)


def _add_note(note: str, extra: str) -> str:
    if not extra:
        return note
    if not note:
        return extra
    return note if extra in note else note + "; " + extra


def _format_report(st, how, unmatched, quarantine, from_dir, to_dir) -> str:
    L = []
    L.append("migrate %s -> %s" % (os.path.relpath(from_dir, paths.REPO_ROOT),
                                   os.path.relpath(to_dir, paths.REPO_ROOT)))
    L.append("=" * 72)
    L.append("v1 rows read              %6d" % st["v1_rows"])
    L.append("v2 rows written           %6d  in %d tables" % (st["v2_rows"], st["tables"]))
    L.append("translations carried      %6d  (%d needed their control tokens "
             "re-bound to the corrected source)"
             % (st["carried"], st["retokenised"]))
    L.append("could not be ported       %6d  (v1 read those bytes wrongly; the "
             "line needs re-translating)" % st["unportable"])
    L.append("landed on a @noedit row  %6d  (kept in the note; the builder "
             "cannot edit those records)" % st["landed_on_noedit"])
    L.append("@operand rows re-opened   %6d  (carried as empty; jp is now correct)"
             % st["quarantine_carried_empty"])
    L.append("no v2 row at all          %6d" % (st["unmatched_translations"]
                                                + st["dropped_no_v2_rows"]))
    L.append("")
    L.append("how each v1 row was matched:")
    for k in ("offset", "rec+idx", "rec+text", "text", "unmatched"):
        if how[k]:
            L.append("  %-10s %6d" % (k, how[k]))
    L.append("")

    L.append("unmatched rows that held a real translation: %d" % len(unmatched))
    for rel, old, why in unmatched[:60]:
        L.append("  %-22s %-8s idx=%-4d off=%-6d %s" % (rel, old.rec, old.idx,
                                                        old.off, why))
        L.append("      jp %s" % old.jp[:90])
        L.append("      en %s" % old.en[:90])
    if len(unmatched) > 60:
        L.append("  ... and %d more" % (len(unmatched) - 60))
    L.append("")

    L.append("@operand quarantine rows, v1 jp vs v2 jp: %d" % len(quarantine))
    clean = sum(1 for _r, _o, n in quarantine if n is not None)
    L.append("  %d now resolve to a v2 span, %d have no v2 counterpart "
             "(the bytes were operands, not text)" % (clean, len(quarantine) - clean))
    for rel, old, new in quarantine[:80]:
        L.append("  %-22s %-8s idx=%d" % (rel, old.rec, old.idx))
        L.append("      v1 jp  %s" % old.jp[:90])
        L.append("      v2 jp  %s" % (new.jp[:90] if new is not None
                                      else "(no v2 span here)"))
    if len(quarantine) > 80:
        L.append("  ... and %d more" % (len(quarantine) - 80))
    return "\n".join(L) + "\n"
