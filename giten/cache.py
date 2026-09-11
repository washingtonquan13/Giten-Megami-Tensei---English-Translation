"""A content-addressed disk cache for the one expensive thing this pipeline does.

Every tool and most tests decode and tile the whole corpus from scratch: 844
files, 20 690 records, roughly 773 000 tokens.  ``check`` alone does it four
times in one process (capture, stale, overlay, record size), the test suite does
it dozens of times, and each of those passes reads exactly the same bytes and
produces exactly the same objects.  Nothing about it is per-run: the answer is a
pure function of the file's bytes and of the code that reads them.

So it is cached, under ``build/cache/parse/``, keyed by a SHA-256 of

* the **raw file bytes** (not its path or mtime -- a file the tables never touch
  and a file copied in from another tree with the same contents are the same
  parse), and
* the **source text of every module that determines the result**
  (:data:`KEYED_FILES`), read and hashed as bytes.  Editing one byte of any of
  them changes the key of every entry, so a stale answer cannot survive a change
  to the code that produced it.  The key is computed from the files' actual
  contents rather than from a version constant nobody remembers to bump.

The design rule
---------------
**The cache must be invisible.**  A cached parse has to be indistinguishable
from a fresh one -- same values, and safe to mutate the way the caller has
always been able to.  Three things make that true:

1. the key covers every input, so a hit can only be the same answer;
2. :func:`giten.script.parse` never hands two callers the same
   :class:`~giten.script.Rec`.  The cached :class:`~giten.script.Script` is a
   template; every call returns a fresh skeleton over it -- new ``Script``, new
   ``Rec`` objects, new ``spans``/``tokens``/``flags`` lists.  Tokens, operands,
   spans and the record bytes are shared, because nothing in the tree assigns
   an attribute of one; what *is* assigned is a ``Rec`` field, and
   ``tests/test_speed_cache.py`` proves each of those is per-copy;
3. ``GITEN_NO_CACHE=1`` bypasses it entirely, so "is this the cache's fault"
   is one environment variable away.

Concurrency: entries are written to a temp file in the same directory and
``os.replace``d into place, which is atomic on Windows and POSIX alike, so two
processes racing on the same key both end up with a complete file and neither
reads a half-written one.  A failed write is not an error -- the cache is an
optimisation, and a read-only ``build/`` must not stop a tool from running.
"""
from __future__ import annotations

import hashlib
import os
import pickle
import tempfile

from . import paths

#: Every module whose source text can change what ``script.parse`` returns.
#: The list is deliberately generous: adding a file that turns out not to matter
#: costs a few recomputes after an edit, leaving one out costs a wrong answer.
#: ``tests/test_speed_cache.py`` asserts the key moves when each of these does.
KEYED_MODULES = (
    "script.py",        # the parse itself
    "vmops.py",         # the tokenizer and the opcode table reader
    "records.py",       # the record layer
    "container.py",     # the chain-XOR container layer
    "codec.py",         # span text rendering
    "spans.py",         # span tags and the p/ name field
    "pool.py",          # the 08 nn pool the renderer expands
    "partial.py",       # the partial-tiling reader
    "observed.py",      # DEAD / UNREACHED / UNUSED, read by the refusal rule
    "loaders.py",       # DATA_FILES, read by the refusal rule
    "files.py",         # which file is in which family, and EXCLUDE_FROM_TEXT
)

#: Data files that are as much an input as the code is.
KEYED_DATA = (
    os.path.join(paths.REPO_ROOT, "docs", "opcodes.json"),
)

KEYED_FILES = tuple(os.path.join(os.path.dirname(os.path.abspath(__file__)), m)
                    for m in KEYED_MODULES) + KEYED_DATA

CACHE_ROOT = os.path.join(paths.BUILD_DIR, "cache")
PARSE_DIR = os.path.join(CACHE_ROOT, "parse")

_CODE_KEY: "str | None" = None


def disabled() -> bool:
    """``GITEN_NO_CACHE=1`` turns every cache in this module off."""
    return os.environ.get("GITEN_NO_CACHE", "") not in ("", "0")


def digest_of(paths_: "tuple[str, ...]") -> str:
    """SHA-256 over the text of every file in ``paths_``.

    The *name* of each file goes into the digest as well as its bytes, so
    swapping two files' contents is a different key.  Kept separate from
    :func:`code_key` so a test can digest a copy of the tree with one byte
    changed rather than editing the running installation, which would be a race
    the moment the suite runs in parallel.
    """
    h = hashlib.sha256()
    for p in paths_:
        h.update(os.path.basename(p).encode("utf-8"))
        h.update(b"\0")
        try:
            with open(p, "rb") as fh:
                h.update(fh.read())
        except OSError:
            h.update(b"<missing>")
        h.update(b"\0")
    return h.hexdigest()


def code_key() -> str:
    """:func:`digest_of` over :data:`KEYED_FILES`, computed once per process."""
    global _CODE_KEY
    if _CODE_KEY is None:
        _CODE_KEY = digest_of(KEYED_FILES)
    return _CODE_KEY


def reset() -> None:
    """Forget the memoised :func:`code_key` -- for the test that edits a file."""
    global _CODE_KEY
    _CODE_KEY = None


def key(kind: str, *parts: bytes) -> str:
    """The cache key for one entry: the code key, the kind, and the inputs."""
    h = hashlib.sha256()
    h.update(code_key().encode("ascii"))
    h.update(b"\0")
    h.update(kind.encode("utf-8"))
    h.update(b"\0")
    for p in parts:
        h.update(len(p).to_bytes(8, "little"))
        h.update(p)
    return h.hexdigest()


def _path(where: str, k: str) -> str:
    return os.path.join(where, k[:2], k + ".pickle")


def load(where: str, k: str):
    """The cached object, or ``None`` on a miss or an unreadable entry."""
    p = _path(where, k)
    try:
        with open(p, "rb") as fh:
            return pickle.loads(fh.read())
    except (OSError, EOFError, pickle.UnpicklingError, AttributeError,
            ImportError, ValueError):
        return None


def store(where: str, k: str, obj) -> None:
    """Write one entry.  Best effort: a cache that cannot be written is not an
    error, it is a cache miss next time."""
    p = _path(where, k)
    d = os.path.dirname(p)
    try:
        os.makedirs(d, exist_ok=True)
        blob = pickle.dumps(obj, protocol=pickle.HIGHEST_PROTOCOL)
        fd, tmp = tempfile.mkstemp(dir=d, prefix=".tmp-", suffix=".pickle")
        try:
            with os.fdopen(fd, "wb") as fh:
                fh.write(blob)
            os.replace(tmp, p)              # atomic; a racing writer is fine
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
    except (OSError, pickle.PicklingError, RecursionError, TypeError):
        pass
