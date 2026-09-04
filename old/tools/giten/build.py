"""``build``: source game files + text tables -> ``build/ddswin``.

The source of truth is always the *game file*, never a previous build: a rebuild
starts from the shipped bytes, substitutes the spans whose ``en`` is filled in,
and re-emits everything else verbatim.  With no substitutions the output is
byte-identical to the input -- that is the identity test in :mod:`.check`, and it
is what makes every other guarantee checkable.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

from . import container, dictionary, files, framing, paths, spans, tables, tokens


class BuildError(Exception):
    pass


@dataclass
class FileResult:
    rel: str
    raw: bytes
    changed: int = 0            # spans substituted
    size_delta: int = 0         # bytes gained/lost
    unframed_resize: int = 0    # resized spans in a frame with no length field
    errors: "list[str]" = None

    def __post_init__(self):
        if self.errors is None:
            self.errors = []


def _encode_span(sp: spans.Span, row: tables.Row) -> bytes:
    """Encode a row's ``en`` into the bytes that replace the span."""
    data = tokens.encode(row.en)          # raises on {DICT:..}, bad escape, non-cp932
    if sp.fixed_len is not None:
        if len(data) > sp.fixed_len - 1:
            raise tokens.SpanEncodeError(
                "%d bytes does not fit the %d-byte field (max %d + NUL)"
                % (len(data), sp.fixed_len, sp.fixed_len - 1))
        data = data + b"\x00" * (sp.fixed_len - len(data))
    return data


def build_body(rel: str, body: bytes, frames, found, rowmap) -> "tuple[bytes, FileResult]":
    """Splice edited spans into ``body``, fixing up record length fields."""
    res = FileResult(rel, b"")
    by_frame = {}
    for sp in found:
        by_frame.setdefault(sp.frame_index, []).append(sp)

    out = bytearray()
    cursor = 0
    for fr in frames:
        if fr.data_start < cursor:
            raise BuildError("%s: overlapping frames" % rel)
        out += body[cursor : fr.data_start]

        payload = bytearray()
        p = fr.data_start
        for sp in by_frame.get(fr.index, []):
            row = rowmap.get((sp.rec, sp.idx))
            payload += body[p : sp.start]
            src = body[sp.start : sp.end]
            if row is not None and row.edited:
                try:
                    new = _encode_span(sp, row)
                except tokens.SpanEncodeError as exc:
                    res.errors.append("%s %s[%d]: %s" % (rel, sp.rec, sp.idx, exc))
                    new = src
                if new != src:
                    res.changed += 1
                    if len(new) != len(src):
                        res.size_delta += len(new) - len(src)
                        if fr.len_off is None:
                            res.unframed_resize += 1
                payload += new
            else:
                payload += src
            p = sp.end
        payload += body[p : fr.data_end]

        if fr.len_off is not None:
            # The length field sits in the bytes we just copied before the payload.
            pos = len(out) - (fr.data_start - fr.len_off)
            value = len(payload) + fr.len_bias
            if not 0 <= value <= 0xFFFF:
                raise BuildError("%s: record %s length %d out of range"
                                 % (rel, fr.key, value))
            out[pos : pos + 2] = value.to_bytes(2, "little")
        out += payload
        cursor = fr.data_end

    out += body[cursor:]
    return bytes(out), res


def build_file(rel: str, raw: bytes, dic, rowmap) -> FileResult:
    hdr, body = container.unpack(raw)
    frames, found = spans.scan(rel, body, dic)
    new_body, res = build_body(rel, body, frames, found, rowmap)
    new_hdr = container.recompute_header(rel, hdr, body, new_body)
    res.raw = container.pack(new_body, new_hdr)
    return res


def run(out_dir: "str | None" = None, family: str = "all",
        root: "str | None" = None, text_dir: "str | None" = None,
        quiet: bool = False, ignore_tables: bool = False) -> "dict":
    """Rebuild every encoded file into ``out_dir`` (default ``build/ddswin``).

    ``ignore_tables=True`` builds as if every ``en`` were empty -- the identity
    build used by ``check``.
    """
    out_dir = out_dir or paths.BUILD_DDSWIN
    text_dir = text_dir or paths.TEXT_DIR
    dic = dictionary.load(root)

    # A file is rebuilt whichever family it is in; only the table lookup depends
    # on `family`, so `build --family ms` still emits a complete, installable set.
    wanted = set(files.iter_files(files.expand_family(family), root))

    table_cache = {}
    stats = {"files": 0, "changed_files": 0, "changed_spans": 0,
             "errors": [], "unframed_resize": 0, "identical": 0}

    for rel in files.all_encoded(root):
        raw = files.read_source(rel, root)
        rowmap = {}
        if not ignore_tables and rel in wanted and rel not in files.EXCLUDE_FROM_TEXT:
            tp = files.table_path(rel, text_dir)
            if tp not in table_cache:
                table_cache[tp] = tables.read(tp)
            rowmap = {(r.rec, r.idx): r for r in table_cache[tp] if r.file == rel}

        res = build_file(rel, raw, dic, rowmap)
        stats["files"] += 1
        stats["changed_spans"] += res.changed
        stats["unframed_resize"] += res.unframed_resize
        stats["errors"].extend(res.errors)
        if res.changed:
            stats["changed_files"] += 1
        if res.raw == raw:
            stats["identical"] += 1

        dst = os.path.join(out_dir, *rel.split("/"))
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        with open(dst, "wb") as fh:
            fh.write(res.raw)

    if not quiet:
        print("built %d files into %s" % (stats["files"], out_dir))
        print("  %d files changed, %d spans substituted, %d byte-identical"
              % (stats["changed_files"], stats["changed_spans"], stats["identical"]))
        if stats["unframed_resize"]:
            print("  %d resized spans live in frames with no known length field "
                  "(see docs/pipeline.md)" % stats["unframed_resize"])
        for e in stats["errors"][:20]:
            print("  ERROR " + e)
        if len(stats["errors"]) > 20:
            print("  ... and %d more errors" % (len(stats["errors"]) - 20))
    return stats
