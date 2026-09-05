"""Second reference pass: align the original script files with v0.05's *files*.

``carry`` pairs table rows by tag sequence.  That breaks wherever v0.05
stripped the runtime name prints (``1F01 nn`` + ``00``, see format-notes 2.11):
the ``00`` terminator was the tag of the following span, so a Japanese record
shows ``00``-tagged name and body spans where v0.05 shows ``1FD2``/``1FD3``,
and a line the engine prints a name *inside* is two or three Japanese spans
where v0.05 hard-coded the name into one.  Whole friend scenes of the
prologue lost their reference that way (``MS0027`` 269 lines, ``MS0034`` 226).

This pass aligns per record on what v0.05 could not have changed:

1. **structural spans** -- choice options and anything after a branch or
   switch -- must match one to one; they anchor the sequence (``difflib`` on
   the structural tags, every text span reduced to one key);
2. inside a run of text spans, **name spans** pair with name spans in order
   (Japanese: a name macro and ``：``; v0.05: ``Word:``);
   -- and by *speaker*: a name macro is mapped to the English name it appears
   with wherever both sides already agree, so a dropped or added speaker
   turn does not shift every line after it;
3. between two names, **body spans** pair positionally when the counts agree;
   when Japanese has more (a name print splits the line) the whole v0.05 text
   goes into the first Japanese span and the rest get a single space, with
   :data:`MERGED` in the note so a translator re-splits it around the name;
   when v0.05 has more, its extra lines are appended to the last pair.

Only rows without a reference are touched, and only with ``ref_src = v005``.
Everything this pass writes is a *draft candidate*; it is never ``en``.
"""
from __future__ import annotations

import difflib
import os
import re

from . import codec, files, paths, script, tables
from .carry import is_english

MARK = "@refalign"
MERGED = "@refalign-merged"
NL = "\\n"                    # the rendered newline token, as the tables carry it

#: tags of spans whose position v0.05 could not change: menu options and the
#: text right after a branch, switch, call or jump
STRUCT_PREFIXES = ("1FB2", "09", "0E", "0F", "18", "1F03", "1F1", "1DB", "1E07", "1E08", "1FCD", "DATA", "UNTILED")

_JP_NAME = re.compile(r"^(\{[0-9A-F]{2}:[0-9A-F]{2}\}|\{=[0-9A-F]{2}\})*：$")
_EN_NAME = re.compile(r"^[A-Za-z][A-Za-z .'\-]{0,24}:$")


def _structural(tag: str) -> bool:
    return any(tag.startswith(p) for p in STRUCT_PREFIXES)


def _key(tag: str) -> str:
    return tag if _structural(tag) else "T"


def _is_name(text: str, english: bool) -> bool:
    return bool((_EN_NAME if english else _JP_NAME).match(text.strip()))


def _units(seq, english):
    """[(speaker key, name item or None, [body items])] for one run of text spans."""
    res = [("^", None, [])]
    for item in seq:
        if _is_name(item[1], english):
            res.append((item[1].strip(), item, []))
        else:
            res[-1][2].append(item)
    return res


def _pair_bodies(jb, eb, out):
    if len(jb) == len(eb):
        for (ji, _), (_, et) in zip(jb, eb):
            out[ji] = (et, False)
    elif len(jb) > len(eb):
        if not eb:
            return
        out[jb[0][0]] = (NL.join(t for _, t in eb), True)
        for ji, _ in jb[1:]:
            out[ji] = (" ", True)
    else:
        for k, (ji, _) in enumerate(jb):
            if k < len(jb) - 1:
                out[ji] = (eb[k][1], False)
            else:
                out[ji] = (NL.join(t for _, t in eb[k:]), True)


def _pair_run(jp, en, out, speakers=None):
    """Pair one run of text spans: ``jp``/``en`` are lists of (idx, text).

    Speaker units (a name span and the lines under it) are aligned by speaker
    identity: a Japanese name macro is mapped to the English name it was seen
    with wherever the two sides already agreed (``speakers``).
    """
    uj, ue = _units(jp, False), _units(en, True)
    speakers = speakers or {}
    kj = [speakers.get(k, k) for k, _, _ in uj]
    ke = [k for k, _, _ in ue]
    sm = difflib.SequenceMatcher(None, kj, ke, autojunk=False)
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op in ("equal", "replace"):
            for (kjn, jn, jb), (ken, en_, eb) in zip(uj[i1:i2], ue[j1:j2]):
                if jn and en_:
                    out[jn[0]] = (en_[1], False)
                if jb:
                    _pair_bodies(jb, eb, out)


def _segments(spans):
    """[(anchor span or None, [text spans])]: the text runs between structural spans."""
    out = [(None, [])]
    for item in spans:                     # item = (idx, tag, text)
        if _structural(item[1]):
            out.append((item, []))
        else:
            out[-1][1].append((item[0], item[2]))
    return out


def learn_speakers(pairs) -> "dict[str, str]":
    """``{japanese name macro: english name}`` from every text run whose two
    sides have the same number of speaker units."""
    votes = {}
    for jp, en in pairs:
        uj, ue = _units(jp, False), _units(en, True)
        if len(uj) != len(ue):
            continue
        for (kj, jn, _), (ke, en_, _) in zip(uj, ue):
            if jn and en_:
                votes.setdefault(kj, {}).setdefault(ke, 0)
                votes[kj][ke] += 1
    return {k: max(v, key=v.get) for k, v in votes.items()}


def text_runs(a: "script.Rec", b: "script.Rec"):
    """The paired text runs of two records: ``[(jp run, en run)]`` between
    matching structural anchors, plus ``[(jp anchor idx, en text)]``."""
    ja = [(sp.idx, sp.tag, script.span_text(a, sp)) for sp in a.spans]
    jb = [(sp.idx, sp.tag, script.span_text(b, sp)) for sp in b.spans]
    sa, sb = _segments(ja), _segments(jb)
    sm = difflib.SequenceMatcher(None, [x[0][1] if x[0] else "^" for x in sa],
                                 [x[0][1] if x[0] else "^" for x in sb], autojunk=False)
    runs, anchors = [], []
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op == "equal":
            for (an_a, ta), (an_b, tb) in zip(sa[i1:i2], sb[j1:j2]):
                if an_a and an_b:
                    anchors.append((an_a[0], an_b[2]))
                runs.append((ta, tb))
        elif op == "replace":
            # anchors disagree: pair all the text between them as one run
            runs.append(([t for _, ts in sa[i1:i2] for t in ts], [t for _, ts in sb[j1:j2] for t in ts]))
    return runs, anchors


def align_record(a: "script.Rec", b: "script.Rec", speakers=None) -> "dict[int, tuple[str, bool]]":
    """``{jp span idx: (english, merged)}`` for one record pair."""
    runs, anchors = text_runs(a, b)
    out = {}
    for idx, text in anchors:
        out[idx] = (text, False)
    for jp, en in runs:
        _pair_run(jp, en, out, speakers)
    return out


def run(v005_root: str, text_dir: "str | None" = None, quiet: bool = False) -> dict:
    text_dir = text_dir or paths.TEXT_DIR
    st = {"filled": 0, "merged": 0, "files": 0, "replaced": 0}
    for path in tables.iter_tables(text_dir):
        rows = tables.read(path)
        if not rows or not rows[0].file.startswith("m/"):
            continue
        rel = rows[0].file
        need = [r for r in rows if not r.en and r.ref_src != "ours" and codec.strip_tokens(r.jp).strip()]
        if not need:
            continue
        vpath = os.path.join(v005_root, *rel.split("/"))
        if not os.path.exists(vpath):
            continue
        a = script.parse(rel, files.read_source(rel))
        b = script.parse(rel, open(vpath, "rb").read())
        if not (a.ok and b.ok):
            continue
        by_key = {(r.rec, r.idx): r for r in rows}
        bmap = {}
        for rec in b.iter_records():
            bmap.setdefault((rec.ci, rec.id), rec)
        pairs = [(rec, bmap[(rec.ci, rec.id)]) for rec in a.iter_records()
                 if rec.tokens is not None and (rec.ci, rec.id) in bmap
                 and bmap[(rec.ci, rec.id)].tokens is not None]
        speakers = learn_speakers([run for x, y in pairs for run in text_runs(x, y)[0]])
        changed = False
        for rec, other in pairs:
            for idx, (text, merged) in align_record(rec, other, speakers).items():
                row = by_key.get((rec.key, idx))
                if row is None or row.en or not codec.strip_tokens(row.jp).strip():
                    continue
                if row.ref_en and (row.ref_src == "ours" or MARK in row.note):
                    continue                       # our own translation, or already placed here
                if text.strip() == "" and not merged:
                    continue
                if not is_english(text) and text.strip():
                    continue                       # v0.05 left it Japanese too
                if row.ref_en and row.ref_en != text:
                    st["replaced"] += 1            # the tag-sequence carry had shifted this one
                row.ref_en, row.ref_src = text, "v005"
                row.note = (row.note + " " + MARK + (" " + MERGED if merged else "")).strip()
                st["filled"] += 1
                st["merged"] += merged
                changed = True
        if changed:
            st["files"] += 1
            tables.write(path, rows)
    if not quiet:
        print("refalign: placed %d v0.05 references in %d files (%d replaced a shifted carry, "
              "%d merged around a name print)" % (st["filled"], st["files"], st["replaced"], st["merged"]))
    return st
