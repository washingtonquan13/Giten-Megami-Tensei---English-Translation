"""The parse cache has to be invisible, and these are the ways it could not be.

Four questions, each with a test:

* does a **cached** parse hold the same values as a **fresh** one, for every
  file in the corpus?  (``GITEN_NO_CACHE=1`` gives the fresh side, in a child
  process so nothing in this one is memoised.)
* does editing one byte of any module that determines the answer change the
  key?  If it did not, a code change would keep serving the old parse.
* does one caller's mutation reach the next caller?  Three places in the tree
  assign ``rec.tokens`` / ``rec.spans`` / ``rec.data`` on a parsed record, so
  "the cache hands out a shared object" would be a real corruption.
* does the round trip through pickle survive?  A field that does not pickle
  would come back missing rather than wrong, which is worse.
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from giten import cache, files, paths, script                    # noqa: E402


# --- a structural comparison, because identity is not the question -----------
def _op_view(op):
    return (op.kind, op.off, op.size, op.raw)


def _tok_view(t):
    return (t.kind, t.off, t.size, t.idx, tuple(_op_view(o) for o in t.ops))


def _span_view(s):
    return (s.ci, s.rec_id, s.idx, s.tok_lo, s.tok_hi, s.off, s.end, s.tag,
            s.choice_width, s.split_head, s.cut_run, s.cut_inside)


def _rec_view(r):
    return (r.ci, r.id, r.order, r.data, r.body_off, r.raw_off,
            None if r.tokens is None else tuple(_tok_view(t) for t in r.tokens),
            r.tile_error, r.unimplemented,
            tuple(_span_view(s) for s in r.spans),
            r.cond, r.param, r.blocked, tuple(r.flags), r.no_overlay,
            None if r.known_tokens is None
            else tuple(_tok_view(t) for t in r.known_tokens),
            r.dup_loser, r.straddle)


def view(sc):
    """Every value a :class:`giten.script.Script` carries, as plain data."""
    return (sc.rel, sc.raw, sc.ok, sc.error,
            tuple(tuple(_rec_view(r) for r in c) for c in sc.containers),
            tuple(sc.cont_offsets), tuple(sc.duplicate_ids),
            tuple((b.count, tuple((x.id, x.data, x.cond, x.param, x.order)
                                  for x in b.records), b.tail, b.short_count,
                   b.error) for b in sc.bodies))


_FRESH_CHILD = r'''
import os, pickle, sys
sys.path.insert(0, %r)
os.environ["GITEN_NO_CACHE"] = "1"
from giten import files, script
sys.path.insert(0, %r)
from tests.test_speed_cache import view
out = {}
for rel in files.all_encoded():
    out[rel] = view(script.parse(rel, files.read_source(rel)))
with open(sys.argv[1], "wb") as fh:
    pickle.dump(out, fh, protocol=pickle.HIGHEST_PROTOCOL)
'''


def test_a_cached_parse_holds_exactly_what_a_fresh_parse_holds():
    """Every file, every record, every token, every span -- by value.

    The fresh side runs in a child process with ``GITEN_NO_CACHE=1``, so it is a
    real parse and not this process's memo; the cached side runs here, which is
    where the disk entry and the in-process skeleton both live.
    """
    tmp = tempfile.mkdtemp(prefix="giten-cache-")
    out = os.path.join(tmp, "fresh.pickle")
    src = os.path.join(tmp, "fresh.py")
    with open(src, "w", encoding="utf-8") as fh:
        fh.write(_FRESH_CHILD % (paths.REPO_ROOT, paths.REPO_ROOT))
    env = dict(os.environ, GITEN_NO_CACHE="1")
    subprocess.run([sys.executable, src, out], check=True, env=env,
                   cwd=paths.REPO_ROOT)
    import pickle
    with open(out, "rb") as fh:
        fresh = pickle.load(fh)

    n = 0
    for rel in files.all_encoded():
        got = view(script.parse(rel, files.read_source(rel)))
        assert got == fresh[rel], rel
        n += 1
    assert n == len(fresh) == 844, (n, len(fresh))


def test_the_key_moves_when_any_module_that_shapes_the_answer_moves():
    """One byte appended to each keyed file, one at a time, must change the key.

    This is the invalidation rule stated as a test.  A module that influences
    the parse but is missing from ``cache.KEYED_FILES`` would keep serving a
    stale answer after it was edited, silently and for ever, so every file on
    the list is checked -- and the list is checked against the modules
    ``giten/script.py`` actually imports, so a new dependency cannot be added
    without either keying it or failing here.

    The edit is made to a **copy** of the keyed tree, never to the installed
    modules: a test that rewrites ``giten/script.py`` for a moment is a race
    against every other worker the moment the suite runs in parallel, and it
    leaves the tree broken if it is interrupted.
    """
    tmp = tempfile.mkdtemp(prefix="giten-key-")
    copies = []
    for path in cache.KEYED_FILES:
        dst = os.path.join(tmp, os.path.basename(path))
        with open(path, "rb") as fh:
            blob = fh.read()
        with open(dst, "wb") as fh:
            fh.write(blob)
        copies.append(dst)
    copies = tuple(copies)

    base = cache.digest_of(copies)
    assert base == cache.code_key(), "the copy is not the tree it came from"

    for dst in copies:
        with open(dst, "rb") as fh:
            original = fh.read()
        with open(dst, "wb") as fh:
            fh.write(original + b"\n# cache-key probe\n")
        try:
            assert cache.digest_of(copies) != base, dst
        finally:
            with open(dst, "wb") as fh:
                fh.write(original)
    assert cache.digest_of(copies) == base

    # and the entry key carries the code key, so a module edit moves it too
    raw = files.read_source("m/MS0000.BIN")
    k = cache.key("parse", b"m/MS0000.BIN", raw)
    saved = cache._CODE_KEY
    try:
        cache._CODE_KEY = "0" * 64
        assert cache.key("parse", b"m/MS0000.BIN", raw) != k
    finally:
        cache._CODE_KEY = saved
    assert cache.key("parse", b"m/MS0000.BIN", raw) == k


def test_every_module_the_parse_imports_is_on_the_key():
    """The list is not allowed to drift away from what ``script.py`` imports.

    ``giten/script.py`` names its dependencies in one ``from . import`` line and
    two deferred imports; each of them, and each module *they* import from the
    package, has to be keyed or the cache can serve an answer produced by code
    that has since changed.
    """
    import ast

    keyed = {os.path.basename(p) for p in cache.KEYED_FILES}
    pkg = os.path.dirname(os.path.abspath(script.__file__))

    seen, todo = set(), ["script.py"]
    while todo:
        name = todo.pop()
        if name in seen:
            continue
        seen.add(name)
        path = os.path.join(pkg, name)
        if not os.path.exists(path):
            continue
        with open(path, "r", encoding="utf-8") as fh:
            tree = ast.parse(fh.read(), name)
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.level == 1:
                for a in node.names:
                    todo.append(a.name + ".py")

    # `cache` and `paths` are the cache's own plumbing: `paths` only resolves
    # directories and `cache` is what computes the key, so neither can change a
    # parsed value.  Everything else must be keyed.
    exempt = {"script.py", "cache.py", "paths.py"}
    missing = sorted(n for n in seen - exempt
                     if n not in keyed and os.path.exists(os.path.join(pkg, n)))
    assert not missing, ("these modules shape a parse but are not on the cache "
                         "key: %s" % ", ".join(missing))


def test_one_callers_mutation_never_reaches_the_next_caller():
    """``rec.tokens``, ``rec.spans`` and ``rec.data`` are assigned in the tree.

    ``tests/test_partial.py`` replaces ``tokens``, ``tests/test_straddle.py``
    clears it, ``tests/test_overlay.py`` recomputes ``spans``.  All three run in
    the same process as everything else, so a cache that handed out one shared
    object would let them rewrite the corpus for every test after them.
    """
    rel = "m/MS0000.BIN"
    raw = files.read_source(rel)
    a = script.parse(rel, raw)
    before = view(a)

    rec = a.containers[0][0]
    rec.tokens = None
    rec.spans = []
    rec.data = b"\x00"
    rec.flags.append("@probe")
    a.containers[0].append(rec)
    a.cont_offsets.append(-1)

    b = script.parse(rel, raw)
    assert view(b) == before

    # and the shared halves really are shared -- that is what makes it cheap
    c = script.parse(rel, raw)
    d = script.parse(rel, raw)
    rc, rd = c.containers[0][1], d.containers[0][1]
    assert rc is not rd
    assert rc.tokens is not rd.tokens
    assert rc.data is rd.data
    if rc.tokens:
        assert rc.tokens[0] is rd.tokens[0]


def test_the_disk_entry_round_trips_and_is_written_atomically():
    """A stored entry reads back equal, and only whole files ever appear."""
    tmp = tempfile.mkdtemp(prefix="giten-cachedir-")
    rel = "m/MS0001.BIN"
    sc = script.parse(rel, files.read_source(rel))
    k = cache.key("parse", rel.encode(), files.read_source(rel))
    assert cache.load(tmp, k) is None
    cache.store(tmp, k, sc)
    back = cache.load(tmp, k)
    assert back is not None
    assert view(back) == view(sc)
    # nothing half-written is left behind
    leftovers = [n for _d, _s, ns in os.walk(tmp) for n in ns
                 if n.startswith(".tmp-")]
    assert leftovers == [], leftovers


def test_the_bypass_really_bypasses():
    """``GITEN_NO_CACHE=1`` must not read or write the cache at all."""
    rel = "m/MS0002.BIN"
    raw = files.read_source(rel)
    k = cache.key("parse", rel.encode(), raw)
    os.environ["GITEN_NO_CACHE"] = "1"
    try:
        assert cache.disabled()
        script._MEMO.pop(k, None)
        script._SEEN.discard(k)
        sc = script.parse(rel, raw)
        assert k not in script._MEMO
    finally:
        os.environ.pop("GITEN_NO_CACHE", None)
    assert not cache.disabled()
    assert view(sc) == view(script.parse(rel, raw))
