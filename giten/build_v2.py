"""``build --engine v2``: source game files + ``tables/`` -> an output tree.

Always starts from the shipped bytes, never from a previous build.  With no
substitutions the output is byte-identical to the input for all 844 files; that
identity is what makes every other guarantee checkable.

Three families of file:

``m/MS*``, ``et/ID*``   full script treatment -- containers, records, tokens,
                        span substitution, record-length rewrite, container
                        header + cipher reseed, ``rel16`` relocation.
``p/P*``                the fixed 16-byte name field, spliced in place (the
                        length never changes, so nothing has to move).
everything else         copied through byte for byte.
"""
from __future__ import annotations

import os
import shutil
from dataclasses import dataclass, field

from . import (codec, container, extract_v2, files, paths, pool, script, spans,
               tables)


@dataclass
class Result:
    rel: str
    raw: bytes
    changed_spans: int = 0
    changed_records: int = 0
    relocated: int = 0
    unmapped: int = 0
    unmapped_in_edit: int = 0
    branched_into: int = 0
    #: spans a branch jumps into that shipped anyway, because the target sits on
    #: a trailing escape the translation preserves byte-for-byte
    tail_anchored: int = 0
    not_a_branch: int = 0
    size_delta: int = 0
    errors: "list[str]" = field(default_factory=list)
    warnings: "list[str]" = field(default_factory=list)


def _edits_from_rows(rows) -> "dict[tuple[int, int, int], object]":
    """``{(container, record id, span index): row}`` for a file's edited rows."""
    out = {}
    for r in rows:
        if not r.edited or r.rec == extract_v2.PNAME_REC:
            continue
        if r.tag == extract_v2.UNTILED_TAG:
            continue
        ci, _, rid = r.rec.partition(":")
        try:
            out[(int(ci), int(rid, 16), r.idx)] = r
        except ValueError:
            continue
    return out


def stale_rows(sc, keyed: dict) -> "list[tuple[tuple, str]]":
    '''Rows whose ``jp`` is not what span ``idx`` of that record says *now*.

    A table is addressed by span index, and span numbering is a property of the
    tokenizer: when the opcode model improves (the switch tables of 2026-09-04
    renumbered every record that holds one) a row written against the old
    numbering would silently put its English on some other line.  The ``jp``
    column is the row's fingerprint; it must match byte for byte or the row is
    not applied.  Returns ``[(key, reason)]``.
    '''
    by_key = {}
    for rec in sc.iter_records():
        # `span_tokens`, not `tokens`: a straddling record keeps `tokens` None so
        # the byte builder and `audit` treat it as untiled, but its spans are
        # complete and the overlay serves them, so they must be addressable here
        # or every row in one reads as 'no span N in this record any more'.
        if rec.span_tokens is None:
            continue
        for sp in rec.spans:
            by_key[(rec.ci, rec.id, sp.idx)] = script.span_text(rec, sp)
    out = []
    for key, row in keyed.items():
        now = by_key.get(key)
        if now is None:
            out.append((key, "no span %d in this record any more" % key[2]))
        elif now != row.jp:
            out.append((key, "stale row: jp is %r but the span now reads %r"
                        % (row.jp[:40], now[:40])))
    return out


def _build_pname(rel: str, raw: bytes, rows) -> Result:
    res = Result(rel, raw)
    row = next((r for r in rows if r.rec == extract_v2.PNAME_REC and r.edited), None)
    if row is None:
        return res
    conts, end = container.split(raw)
    if not conts or end != len(raw) or conts[0].short:
        res.errors.append("%s: not a clean container chain" % rel)
        return res
    try:
        data = codec.encode(row.en, allow=frozenset())
    except codec.CodecError as exc:
        res.errors.append("%s NAME: %s" % (rel, exc))
        return res
    if len(data) > spans.PNAME_LEN - 1:
        res.errors.append("%s NAME: %d bytes does not fit the %d-byte field "
                          "(%d + NUL)" % (rel, len(data), spans.PNAME_LEN,
                                          spans.PNAME_LEN - 1))
        return res
    body = bytearray(conts[0].body)
    body[spans.PNAME_OFF:spans.PNAME_OFF + spans.PNAME_LEN] = (
        data + b"\x00" * (spans.PNAME_LEN - len(data)))
    bodies = [bytes(body)] + [c.body for c in conts[1:]]
    res.raw = container.join(bodies)
    res.changed_spans = 1
    return res


def build_file(rel: str, raw: bytes, rows) -> Result:
    if rel.startswith("p/"):
        return _build_pname(rel, raw, rows)
    sc = script.parse(rel, raw)
    if not sc.ok:
        return Result(rel, raw)                 # no text layer: copy through
    keyed = _edits_from_rows(rows)
    stale = stale_rows(sc, keyed)
    for key, why in stale:
        keyed.pop(key)
    edits = {k: r.en for k, r in keyed.items()}
    out, rep = script.build(sc, edits)
    for (ci, rid, idx), why in stale:
        rep.errors.append("%s %d:%02X[%d]: %s -- not applied; re-extract and carry"
                          % (rel, ci, rid, idx, why))
    return Result(rel, out, rep.changed_spans, rep.changed_records, rep.relocated,
                  rep.unmapped, rep.unmapped_in_edit, rep.branched_into,
                  getattr(rep, "tail_anchored", 0),
                  rep.not_a_branch, rep.size_delta,
                  list(rep.errors), list(rep.warnings))


def _racenames(raw):
    from . import racenames
    return racenames.build(raw)


def _districts(raw):
    from . import districts
    return districts.build(raw)


def _etdb(name):
    """A builder for one of the ``etdb`` files, from that file's own bytes.

    The same four steps ``giten etdb`` runs -- split the container, parse the
    ``u16 count; u16 offset[]; records`` body, rebuild it with whatever English
    the table holds, wrap it back into a container -- so a build tree carries
    the same bytes that command writes.  Until 2026-09-11 it did not: these two
    were identity copies here and the play install's English ones came from a
    hand-run ``giten etdb``, which is exactly the "not reproducible from the
    tree" hazard the rest of this module exists to prevent.
    """
    def build_one(raw):
        from . import container, etdb
        spec = etdb.SPECS[name]
        conts, _end = container.split(raw)
        if len(conts) != 1:
            raise etdb.EtDbError("%s: %d containers, expected 1"
                                 % (spec.rel, len(conts)))
        recs = etdb.parse(spec, conts[0].body)
        return etdb.pack_file(spec, etdb.build(spec, recs, etdb.read_table(spec)))
    return build_one


#: ``dir/FILE.BIN`` -> a function from the original bytes to the built bytes,
#: for files the script pipeline cannot parse.  ``et/ET0001.BIN`` is deliberately
#: absent: the item database is never modified in place, its English ships as the
#: separate ``et/et0102.bin`` (:data:`ADDED_FILES`), so an identity copy is correct.
DATA_TABLE_BUILDERS = {
    "et/ET0000.BIN": _racenames,          # giten racenames
    "et/ET000D.BIN": _districts,          # giten districts -- the location strip
    "et/ET0004.BIN": _etdb("skills"),     # giten etdb skills
    "et/ET0101.BIN": _etdb("maplabels"),  # giten etdb maplabels
}


def _itemdb(raw):
    from . import container, itemdb, paths as _paths
    recs = itemdb.parse(container.split(raw)[0][0].body)
    table = os.path.join(_paths.REPO_ROOT, "tables", "itemdb.tsv")
    strings, findings = itemdb.strings_from_table(table, recs)
    return itemdb.pack_file(recs, strings), findings


#: Files the build *adds* that the original tree does not have, as
#: ``new path -> (the shipped file its content is derived from, builder)``.
#:
#: There is exactly one, and it exists because ``et/ET0001.BIN`` is capped at
#: 65,535 bytes three separate ways and the English item database does not fit
#: (``docs/exe-patches.md``, ``giten/exe/database.py``).  The original is left
#: untouched and the patched loader is re-pointed at this one, so an unpatched
#: exe still reads the Japanese.  The builder returns ``(bytes, findings)``;
#: a finding is a row the item table could not encode and is reported, not
#: silently dropped.
ADDED_FILES = {
    "et/et0102.bin": ("et/ET0001.BIN", _itemdb),
}


def run(out_dir: "str | None" = None, family: str = "all",
        root: "str | None" = None, text_dir: "str | None" = None,
        quiet: bool = False, ignore_tables: bool = False,
        only: "list[str] | None" = None) -> dict:
    """Build every file; apply tables only to those in ``family`` and ``only``.

    ``only`` is a list of ``fnmatch`` patterns against the ``dir/FILE.BIN`` key
    (``m/MS0017.BIN``, ``m/MS001*``).  Files that do not match are still built,
    as identity copies, so the output is always a complete game tree -- this is
    what lets a translation be switched on one section at a time and each
    section play-tested before the next is enabled.

    A few files in ``et/`` are not record-structured scripts at all but flat
    ``u16 count; u16 offset[]; strings`` tables, so ``script.parse`` rejects them
    ("record 1 overruns the body"), ``extract`` never writes them a table, and
    this builder would otherwise emit an identity copy -- quietly reverting work
    that a different command owns.  :data:`DATA_TABLE_BUILDERS` hands those files
    to the command that does understand them.  ``--identity`` still bypasses this,
    so the round-trip guarantee is unaffected.
    """
    out_dir = out_dir or os.path.join(paths.BUILD_DIR, "ddswin_v2")
    text_dir = text_dir or extract_v2.text_v2_dir()
    wanted = set(files.iter_files(files.expand_family(family), root))
    if only:
        import fnmatch
        wanted = {rel for rel in wanted
                  if any(fnmatch.fnmatch(rel, pat) for pat in only)}

    cache = {}
    st = {"files": 0, "changed_files": 0, "changed_spans": 0, "changed_records": 0,
          "relocated": 0, "unmapped": 0, "unmapped_in_edit": 0,
          "branched_into": 0, "tail_anchored": 0, "not_a_branch": 0, "identical": 0,
          "errors": [], "warnings": []}

    for rel in files.all_encoded(root):
        raw = files.read_source(rel, root)
        rows = []
        if not ignore_tables and rel in wanted:
            tp = files.table_path(rel, text_dir)
            if tp not in cache:
                cache[tp] = tables.read(tp)
            rows = [r for r in cache[tp] if r.file == rel]

        res = build_file(rel, raw, rows)
        if not ignore_tables and rel in wanted and rel in DATA_TABLE_BUILDERS:
            res.raw = DATA_TABLE_BUILDERS[rel](raw)
        st["files"] += 1
        st["changed_spans"] += res.changed_spans
        st["changed_records"] += res.changed_records
        st["relocated"] += res.relocated
        st["unmapped"] += res.unmapped
        st["unmapped_in_edit"] += res.unmapped_in_edit
        st["branched_into"] += res.branched_into
        st["tail_anchored"] += getattr(res, "tail_anchored", 0)
        st["not_a_branch"] += res.not_a_branch
        st["errors"].extend(res.errors)
        st["warnings"].extend(res.warnings)
        if res.changed_spans:
            st["changed_files"] += 1
        if res.raw == raw:
            st["identical"] += 1

        dst = os.path.join(out_dir, *rel.split("/"))
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        with open(dst, "wb") as fh:
            fh.write(res.raw)

    _copy_untouched(root, out_dir)

    if not ignore_tables:
        for rel, (src_rel, fn) in sorted(ADDED_FILES.items()):
            blob, findings = fn(files.read_source(src_rel, root))
            dst = os.path.join(out_dir, *rel.split("/"))
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            with open(dst, "wb") as fh:
                fh.write(blob)
            st["added"] = st.get("added", 0) + 1
            for idx, msg in findings:
                st["warnings"].append("%s record %d: %s" % (rel, idx, msg))

    if not quiet:
        print("built %d files into %s" % (st["files"], out_dir))
        if st.get("added"):
            print("  %d added file(s): %s"
                  % (st["added"], ", ".join(sorted(ADDED_FILES))))
        print("  %d files changed, %d spans in %d records, %d branch "
              "displacements relocated, %d byte-identical"
              % (st["changed_files"], st["changed_spans"], st["changed_records"],
                 st["relocated"], st["identical"]))
        if st["unmapped"]:
            print("  %d branches could not be relocated (%d of them target a byte "
                  "inside a replaced span; the rest already pointed outside their "
                  "container image).  Displacements left unchanged."
                  % (st["unmapped"], st["unmapped_in_edit"]))
        if st["branched_into"]:
            print("  %d edits skipped because a branch lands inside the span"
                  % st["branched_into"])
        if st["not_a_branch"]:
            print("  %d rel16 slots left untouched: their opcode's slot does not "
                  "hold a branch displacement (script.NOT_A_BRANCH)"
                  % st["not_a_branch"])
        for e in st["errors"][:20]:
            print("  ERROR " + e)
        if len(st["errors"]) > 20:
            print("  ... and %d more errors" % (len(st["errors"]) - 20))
    return st


def _copy_untouched(root, out_dir) -> None:
    """Copy the files the pipeline never opens (``et/A*``, ``et/CA*``, loose data).

    A build tree has to be installable on its own, so anything the encoded-file
    walk does not cover is copied verbatim rather than left missing.
    """
    base = root or paths.game_root()
    known = {os.path.normcase(os.path.join(out_dir, *rel.split("/")))
             for rel in files.all_encoded(root)}
    for dirpath, _dirs, names in os.walk(base):
        rel_dir = os.path.relpath(dirpath, base)
        for n in names:
            src = os.path.join(dirpath, n)
            dst = os.path.normpath(os.path.join(out_dir, rel_dir, n))
            if os.path.normcase(dst) in known or os.path.exists(dst):
                continue
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copy2(src, dst)
