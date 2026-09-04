"""Which game files the pipeline knows about, grouped into families."""
from __future__ import annotations

import os

from . import paths

#: ``m/MS7F07.BIN`` is the ``08 nn`` macro dictionary, not display text.  Its
#: entries are spliced into other files' Japanese at render time and expanded to
#: literal bytes on build, so editing it would silently change the *source* text
#: of every span that still references it.  Excluded from extraction; still
#: rebuilt (byte-identically) like any other file.
EXCLUDE_FROM_TEXT = {"m/MS7F07.BIN"}

#: family -> (directory, filename predicate)
_FAMILY_RULES = {
    "ms": ("m", lambda f: f.upper().startswith("MS")),
    "m":  ("m", lambda f: f.upper().startswith("M") and not f.upper().startswith("MS")),
    "id": ("et", lambda f: f.upper().startswith("ID")),
    "et": ("et", lambda f: f.upper().startswith("ET")),
    "p":  ("p", lambda f: f.upper().startswith("P")),
}

#: Families that ``extract`` walks when ``--family all`` is given.
TEXT_FAMILIES = ("ms", "id", "et", "p")

#: Everything the container round trip is known to hold for -- 844 files.
ALL_FAMILIES = ("ms", "m", "id", "et", "p")

FAMILY_CHOICES = tuple(sorted(set(ALL_FAMILIES))) + ("all",)


def expand_family(name: str) -> "tuple[str, ...]":
    if name == "all":
        return TEXT_FAMILIES
    if name not in _FAMILY_RULES:
        raise SystemExit("unknown family %r (choose from %s)"
                         % (name, ", ".join(FAMILY_CHOICES)))
    return (name,)


def iter_family(name: str, root: "str | None" = None):
    """Yield ``"dir/FILE.BIN"`` keys for one family, sorted."""
    base = root or paths.game_root()
    d, pred = _FAMILY_RULES[name]
    folder = os.path.join(base, d)
    if not os.path.isdir(folder):
        return
    for f in sorted(os.listdir(folder)):
        if f.upper().endswith(".BIN") and pred(f):
            yield "%s/%s" % (d, f)


def iter_files(families, root: "str | None" = None):
    """Yield keys for several families, de-duplicated, in family order."""
    seen = set()
    for fam in families:
        for rel in iter_family(fam, root):
            if rel not in seen:
                seen.add(rel)
                yield rel


def all_encoded(root: "str | None" = None):
    """Every chain-XOR encoded file (the 844 the round trip is verified on)."""
    return iter_files(ALL_FAMILIES, root)


def family_of(rel: str) -> str:
    d, f = rel.split("/", 1)
    for fam, (fd, pred) in _FAMILY_RULES.items():
        if fd == d and pred(f):
            return fam
    return "?"


def read_source(rel: str, root: "str | None" = None) -> bytes:
    base = root or paths.game_root()
    with open(os.path.join(base, *rel.split("/")), "rb") as fh:
        return fh.read()


def table_path(rel: str, text_dir: "str | None" = None) -> str:
    """Path of the text table for a file, under ``text_dir`` (default ``text/``).

    ``m/MS0000.BIN`` -> ``text/m/MS0000.BIN.tsv``.  The ``p/`` family is the one
    exception: 432 character records with a single 16-byte name each become 432
    two-line files, which is hostile to work with, so they share one table.
    """
    base = text_dir or paths.TEXT_DIR
    if rel.startswith("p/"):
        return os.path.join(base, "p", "_P_NAMES.tsv")
    d, f = rel.split("/", 1)
    return os.path.join(base, d, f + ".tsv")
