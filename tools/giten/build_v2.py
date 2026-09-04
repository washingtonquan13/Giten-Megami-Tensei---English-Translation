"""``build --engine v2``: source game files + ``text_v2/`` -> an output tree.

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
    not_a_branch: int = 0
    size_delta: int = 0
    errors: "list[str]" = field(default_factory=list)
    warnings: "list[str]" = field(default_factory=list)


def _edits_from_rows(rows) -> "dict[tuple[int, int, int], str]":
    """``{(container, record id, span index): english}`` from a file's rows."""
    out = {}
    for r in rows:
        if not r.edited or r.rec == extract_v2.PNAME_REC:
            continue
        if r.tag == extract_v2.UNTILED_TAG:
            continue
        ci, _, rid = r.rec.partition(":")
        try:
            out[(int(ci), int(rid, 16), r.idx)] = r.en
        except ValueError:
            continue
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
    edits = _edits_from_rows(rows)
    out, rep = script.build(sc, edits)
    return Result(rel, out, rep.changed_spans, rep.changed_records, rep.relocated,
                  rep.unmapped, rep.unmapped_in_edit, rep.branched_into,
                  rep.not_a_branch, rep.size_delta,
                  list(rep.errors), list(rep.warnings))


def run(out_dir: "str | None" = None, family: str = "all",
        root: "str | None" = None, text_dir: "str | None" = None,
        quiet: bool = False, ignore_tables: bool = False) -> dict:
    out_dir = out_dir or os.path.join(paths.BUILD_DIR, "ddswin_v2")
    text_dir = text_dir or extract_v2.text_v2_dir()
    wanted = set(files.iter_files(files.expand_family(family), root))

    cache = {}
    st = {"files": 0, "changed_files": 0, "changed_spans": 0, "changed_records": 0,
          "relocated": 0, "unmapped": 0, "unmapped_in_edit": 0,
          "branched_into": 0, "not_a_branch": 0, "identical": 0,
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
        st["files"] += 1
        st["changed_spans"] += res.changed_spans
        st["changed_records"] += res.changed_records
        st["relocated"] += res.relocated
        st["unmapped"] += res.unmapped
        st["unmapped_in_edit"] += res.unmapped_in_edit
        st["branched_into"] += res.branched_into
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

    if not quiet:
        print("built %d files into %s" % (st["files"], out_dir))
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
            print("  %d rel16 slots left untouched: the operand does not point "
                  "at an instruction, so it is not a displacement"
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
