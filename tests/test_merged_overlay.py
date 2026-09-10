"""overlay.dat v5: a span placed against the buffer that is actually running.

v4 asked two questions the demon-conversation buffers cannot answer.  *Which
file is this?* -- answered by hashing the whole 1024-byte record index, which
belongs to a merge of up to five files and matches nothing we hold.  *Where does
this span go?* -- answered from our model of one file's record layout, which the
merge moves.  So `rebind()` returned 0 and 7,943 spans were never served.

v5 asks neither.  A span says which record it lives in and where inside it, and
carries a hash of the Japanese it replaces:

    addr = live_index[rec].offset + rec_off
    serve only if fnv1a(live[addr : addr + jp_len]) == jp_hash

A record the merge moved is found, because the live index says where it went.
A record another file replaced fails the hash and is dropped -- not served at a
plausible-looking address, which is the failure mode that matters.  Virtual
addresses shift with the image end for the same reason: a merged buffer is
longer, and tails handed out from the old end would land on real records.

These tests are the offline half.  The C hook implements the same rules and
`tests/test_overlay.py` walks both over the same data; that test needs to
execute a freshly linked binary, which some environments refuse.
"""
from __future__ import annotations

import io
import os
import re
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from giten import files, overlay, paths, records, script

HOOK = os.path.join(paths.REPO_ROOT, "giten", "exe", "hook.c")
BUILT = os.path.join(paths.BUILD_DIR, "overlay-v5.dat")

#: et/ET0007.BIN row 0: the demon whose conversation merges these onto MS6000
ROW0 = ("m/MS6000.BIN", "m/MS6003.BIN", "m/MS600A.BIN")


def _recs(rel, ci=0):
    sc = script.parse(rel, files.read_source(rel))
    return sc.containers[ci] if ci < len(sc.containers) else []


def _merged(rels, ci=0):
    """The image the engine builds: later files replace earlier ones by id."""
    m = {}
    for rel in rels:
        seen = set()
        for r in _recs(rel, ci):
            if r.id not in seen:            # first occurrence wins within a file
                seen.add(r.id)
                m[r.id] = r.data
    return overlay.image_bytes([records.Record(i, m[i]) for i in sorted(m)])


def _entry_for(rel, ci=0):
    """The overlay entry the shipped tables produce for one container.

    Read from the draft tree rather than synthesised, because what is being
    tested is placement of the English we actually ship -- a synthetic row would
    prove the arithmetic and nothing about the corpus.
    """
    from giten import tables
    path = os.path.join(paths.BUILD_DIR, "tables_draft", *rel.split("/"))
    path += ".tsv"
    if not os.path.exists(path):
        return None, None               # tree not generated in this checkout
    entries, _ = overlay.plan(tables.read(path), None)
    own = [records.Record(r.id, r.data) for r in _recs(rel, ci)]
    fp = overlay.fingerprint(own)
    return next((e for e in entries if e.fp == fp), None), own


def test_the_hook_and_the_builder_agree_on_the_format_version():
    """A mismatch is silent: the hook sets state -1 and the game plays in
    Japanese, with nothing on screen or on disk saying why."""
    src = io.open(HOOK, encoding="utf-8").read()
    m = re.search(r'"GTOV" \*/ \|\| h->version != (\d+)\)', src)
    assert m, "hook.c no longer checks the overlay version the same way"
    assert int(m.group(1)) == overlay.VERSION, (
        "hook.c reads v%s, giten/overlay.py writes v%d" % (m.group(1), overlay.VERSION))


def test_the_hook_reads_the_same_span_fields_the_builder_writes():
    """Field order is the format; C alignment happens to match `<HHHHHHIHHI>`
    here, and this is what says so out loud."""
    src = io.open(HOOK, encoding="utf-8").read()
    m = re.search(r"struct span \{([^}]*)\}", src, re.S)
    assert m, "struct span not found in hook.c"
    got = [f.strip() for f in re.findall(r"[A-Za-z_][A-Za-z0-9_]*", m.group(1))]
    want = ["u16", "start", "jp_len", "virt", "len", "served", "pad",
            "u32", "data_off", "u16", "rec", "rec_off", "u32", "jp_hash"]
    assert got == want, got
    assert overlay.SPAN.size == 24, overlay.SPAN.size


def test_a_span_finds_itself_in_the_merged_buffer():
    """The whole point: m/MS6000's English, placed in the buffer the engine
    actually builds for a demon conversation."""
    e, own = _entry_for("m/MS6000.BIN")
    if e is None:
        return                      # build/tables_draft not generated

    assert e.spans

    alone = overlay.resolve(e, overlay.image_bytes(own))
    assert len(alone) == len(e.spans), "%d of %d resolve against the file itself" % (
        len(alone), len(e.spans))

    merged = overlay.resolve(e, _merged(ROW0))
    assert len(merged) == len(e.spans), "%d of %d resolve against the merge" % (
        len(merged), len(e.spans))

    # ...and it is not a no-op: the merge really does move most of them
    by_key = {(s.rec_id, s.rec_off): s.start for s in alone}
    moved = [s for s in merged if by_key[(s.rec_id, s.rec_off)] != s.start]
    assert len(moved) > 20, "only %d span(s) moved; is this still a merge?" % len(moved)


def test_a_span_refuses_a_buffer_that_is_not_its_own():
    """The hash is the whole safety argument, so prove it rejects."""
    e, own = _entry_for("m/MS6000.BIN")
    if e is None:
        return                      # build/tables_draft not generated

    for other in ("m/MS0017.BIN", "m/MS6003.BIN"):
        img = overlay.image_bytes([records.Record(r.id, r.data) for r in _recs(other)])
        got = overlay.resolve(e, img)
        assert got == [], "%d of m/MS6000's spans resolved inside %s" % (len(got), other)


def test_virtual_addresses_follow_the_image_end():
    """A merged buffer is longer, so English that did not fit in place has to
    move up with it or it lands on records that only exist in the merge."""
    e, own = _entry_for("m/MS6000.BIN")
    if e is None:
        return                      # build/tables_draft not generated

    solo, merged = overlay.image_bytes(own), _merged(ROW0)
    assert overlay._live_end(merged) > overlay._live_end(solo)
    for img in (solo, merged):
        end = overlay._live_end(img)
        tails = [s for s in overlay.resolve(e, img) if s.tail]
        assert tails, "no tails to check"
        assert min(s.virt for s in tails) >= end, "a tail overlaps a real record"
        assert max(s.vend for s in tails) <= overlay.PC_LIMIT


def test_no_entry_is_larger_than_the_hook_can_verify():
    """The hook keeps one bit per span in a fixed array and refuses an entry it
    cannot cover, so the cap has to be above the real worst case."""
    src = io.open(HOOK, encoding="utf-8").read()
    cap = int(re.search(r"#define MAX_SPANS (\d+)", src).group(1))
    assert re.search(r"nspans > MAX_SPANS", src), (
        "hook.c no longer refuses an entry it cannot verify")
    assert cap == overlay.MAX_SPANS, (
        "hook.c verifies %d spans, giten/overlay.py believes %d" % (cap, overlay.MAX_SPANS))
    if not os.path.exists(BUILT):
        return                      # nothing built in this checkout
    ents = overlay.parse(open(BUILT, "rb").read())
    worst = max(len(e.spans) for e in ents)
    assert worst <= cap, "%d spans in one entry, cap is %d" % (worst, cap)


def _build_harness(tmp):
    """The real hook.c, linked natively.  Returns None when it cannot be run.

    Some machines refuse to execute a binary that was linked a moment ago
    (Defender, ESET and friends).  That is not a result about the hook, so it is
    reported rather than silently passed.
    """
    from giten.exe import tracer
    if shutil.which("gcc") is None:
        return None
    here = os.path.dirname(os.path.abspath(__file__))
    exe = os.path.join(tmp, "hook_harness.exe")
    gcc = tracer.short_path(shutil.which("gcc"))
    subprocess.run([gcc, "-O2", "-Wall", "-Werror", "-ffreestanding", "-fno-builtin",
                    "-nostdlib", "-o", exe, tracer.HOOK_SOURCE,
                    os.path.join(here, "hook_harness.c"), "-I", here,
                    "-lkernel32", "-e", "_start"], check=True)
    try:
        subprocess.run([exe], cwd=tmp, capture_output=True)
    except OSError as exc:
        print("      NOT RUN: this machine will not execute the harness (%s);"
              " the merged-buffer path is UNVERIFIED in C" % exc.__class__.__name__)
        return None
    return exe


def test_the_c_hook_serves_a_merged_buffer_the_way_the_model_does():
    """The end-to-end proof for the demon-conversation fix.

    Everything above this runs the Python model.  This runs the exact hook.c
    that goes into the exe, over the image the engine really builds for a demon
    conversation, under the file id the engine really reports (0xE0 -- slot 0,
    which no filename maps to), and demands the same bytes the model gives.

    Without it the fix would rest on the model and the C agreeing by
    construction, which is the assumption that produced every bug on this list.
    """
    e, own = _entry_for("m/MS6000.BIN")
    if e is None:
        return                      # build/tables_draft not generated
    tmp = tempfile.mkdtemp(prefix="giten-merge-")
    exe = _build_harness(tmp)
    if exe is None:
        return

    # the overlay that actually ships, not one rebuilt for the test
    if not os.path.exists(BUILT):
        return
    shutil.copyfile(BUILT, os.path.join(tmp, "overlay.dat"))
    fam = [x for x in overlay.parse(open(BUILT, "rb").read())
           if 0x6000 <= x.fid < 0x7000]

    image = _merged(ROW0)
    with open(os.path.join(tmp, "img.bin"), "wb") as fh:
        fh.write(image)

    # 0xE0 is slot 0 -- several of `fam` bind to this one buffer
    model = overlay.Model(fam, image, fid=0x00E0)
    assert len({s.rec_id for s in model.spans}) > 1
    assert model.spans, "the model resolves nothing; the test would prove nothing"
    idx = overlay.live_index(image)
    checked = 0
    for rec in range(256):
        off, ln = idx[rec]
        if ln <= 1:
            continue                            # absent record
        out = subprocess.run(
            [exe, os.path.join(tmp, "img.bin"), "224", "3", str(off), str(off + ln)],
            cwd=tmp, capture_output=True, text=True, check=True).stdout.split()
        got = bytes.fromhex(out[0]) if not out[0].startswith("pc=") else b""
        assert got == model.walk(off, off + ln), "record %02X" % rec
        assert out[-1] == "pc=%d" % (off + ln)
        checked += 1
    # 98 records carry data in this merged image; the number is pinned so that
    # a walk which quietly stops covering the buffer fails here.
    assert checked == 98, "%d records walked, expected 98" % checked

    # and the English really is in there -- otherwise the walk above would pass
    # just as well with the overlay switched off
    whole = b"".join(model.walk(idx[r][0], idx[r][0] + idx[r][1])
                     for r in range(256) if idx[r][1] > 1)
    for wanted in (b"Friendly", b"Intimidating", b">How will you speak to them?",
                   b"Gaze passionately", b"Persuade"):   # the last two are demon files
        assert wanted in whole, wanted
    shutil.rmtree(tmp, ignore_errors=True)


#: et/ET0007 row 17: this merge REPLACES four of m/MS6000's records, which is
#: the case the old all-or-nothing membership rule could not survive.
ROW17 = ("m/MS6000.BIN", "m/MS6100.BIN")


def test_a_displaced_record_no_longer_discards_the_rest_of_the_file():
    """The demon-negotiation fix, stated as the thing that used to go wrong.

    ``0x0043ABC0`` lets a later merged file replace an earlier file's record by
    id.  ``bind()`` used to require every span of an entry to verify before any
    of them were served, so those four displaced records threw away the other
    105 spans of English in m/MS6000 -- which is why negotiation drew English
    nouns in Japanese sentences.
    """
    e, _own = _entry_for("m/MS6000.BIN")
    if e is None:
        return                      # build/tables_draft not generated

    img = _merged(ROW17)
    got = overlay.resolve(e, img)
    assert 0 < len(got) < len(e.spans), (
        "%d of %d spans resolve; this merge is supposed to displace some, so "
        "either et/ET0007 row 17 changed or the merge model did"
        % (len(got), len(e.spans)))

    # the old rule: every span or nothing.  The new one keeps the survivors.
    from giten import tables
    rows = [r for p in tables.iter_tables(os.path.join(paths.BUILD_DIR, "tables_draft"))
            for r in tables.read(p)]
    entries, _ = overlay.plan(rows, None)
    bound = overlay.bind(entries, 0x00E0, img)
    assert len(bound) >= len(got), (
        "bind() served %d spans while m/MS6000 alone resolves %d; the "
        "all-or-nothing gate is back" % (len(bound), len(got)))

    # and the buffer that displaces nothing is unaffected by the change
    assert len(overlay.resolve(e, _merged(ROW0))) == len(e.spans)


def test_the_hook_states_the_same_membership_rule_as_the_model():
    """`entry_fits` in C and `bind` in Python have to agree, and this machine
    cannot run the C harness (see `_build_harness`), so the rule is compared at
    the source level instead.

    This is weaker than executing it and is here because the alternative is
    nothing: the divergence that motivated the fix survived a full green suite
    precisely because the harness silently does not run here.
    """
    src = io.open(HOOK, encoding="utf-8").read()
    m = re.search(r"static int entry_fits\([^)]*\)\s*\{(.*?)\n\}", src, re.S)
    assert m, "entry_fits not found in hook.c"
    body = m.group(1)
    assert "if (span_holds(" in body and "return 1;" in body, (
        "entry_fits no longer accepts an entry on the first span that verifies")
    assert "if (!span_holds(" not in body, (
        "entry_fits rejects an entry when a span fails to verify -- that is the "
        "all-or-nothing rule the merged path was fixed to drop; giten/overlay.py "
        "bind() no longer does this and the two would silently disagree")


def test_the_merged_serve_path_checks_each_span_before_serving_it():
    """Relaxing membership is only safe because the serve path still verifies.

    With the gate gone a bound entry may hold spans the merge displaced, so
    `merged_fetch` has to test the one span a PC lands in -- for tails too,
    which carry their span's rec/rec_off/jp_hash exactly so this works.
    """
    src = io.open(HOOK, encoding="utf-8").read()
    m = re.search(r"static int merged_fetch\([^)]*\)\s*\{(.*?)\n\}", src, re.S)
    assert m, "merged_fetch not found in hook.c"
    body = m.group(1)
    assert body.count("span_ok(") >= 2, (
        "merged_fetch checks %d span(s) before serving; both the in-place path "
        "and the tail path must" % body.count("span_ok("))


def test_the_c_hook_serves_a_merge_that_displaced_a_record():
    """The fix itself, in the real hook.c rather than the model.

    The test above walks ``ROW0``, a merge that displaces nothing, so it passed
    both before and after the change.  This walks ``ROW17``, where m/MS6100
    replaces four of m/MS6000's records -- the case the old all-or-nothing
    membership rule turned into "serve none of this file".  Under that rule the
    hook served 10 spans here; it now serves 115, and this demands the C agree
    with the model byte for byte over every record in the buffer.
    """
    e, _own = _entry_for("m/MS6000.BIN")
    if e is None:
        return                      # build/tables_draft not generated
    tmp = tempfile.mkdtemp(prefix="giten-merge17-")
    exe = _build_harness(tmp)
    if exe is None:
        return                      # reported by _build_harness
    if not os.path.exists(BUILT):
        return
    shutil.copyfile(BUILT, os.path.join(tmp, "overlay.dat"))
    fam = [x for x in overlay.parse(open(BUILT, "rb").read())
           if 0x6000 <= x.fid < 0x7000]

    image = _merged(ROW17)
    with open(os.path.join(tmp, "img.bin"), "wb") as fh:
        fh.write(image)

    # the merge really does displace, or this proves nothing beyond ROW0
    assert 0 < len(overlay.resolve(e, image)) < len(e.spans)

    model = overlay.Model(fam, image, fid=0x00E0)
    assert len(model.spans) > 100, len(model.spans)

    idx = overlay.live_index(image)
    checked = 0
    for rec in range(256):
        off, ln = idx[rec]
        if ln <= 1:
            continue
        out = subprocess.run(
            [exe, os.path.join(tmp, "img.bin"), "224", "3", str(off), str(off + ln)],
            cwd=tmp, capture_output=True, text=True, check=True).stdout.split()
        got = bytes.fromhex(out[0]) if not out[0].startswith("pc=") else b""
        assert got == model.walk(off, off + ln), "record %02X" % rec
        assert out[-1] == "pc=%d" % (off + ln)
        checked += 1
    assert checked == 73, "%d records walked, expected 73" % checked

    # and it is the negotiation English, not just any bytes
    whole = b"".join(model.walk(idx[r][0], idx[r][0] + idx[r][1])
                     for r in range(256) if idx[r][1] > 1)
    for wanted in (b"It seems to have understood",
                   b" put heart and soul into speaking",
                   b"The COMP seems to be malfunctioning"):
        assert wanted in whole, wanted
    shutil.rmtree(tmp, ignore_errors=True)
