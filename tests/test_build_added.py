"""A build tree is the whole shipping tree, including the files only a
dedicated command used to be able to write.

Three ``et/`` files were outside ``giten build`` until 2026-09-11:

* ``et/ET0004.BIN`` (skills) and ``et/ET0101.BIN`` (map labels) were identity
  copies here, so a build tree carried the *Japanese* ones while the play
  install carried English ones somebody had produced by hand with ``giten
  etdb``.  Nothing in the repo could reproduce what was installed, which is the
  exact hazard ``tools/make_draft_tree.py`` exists to prevent for tables.
* ``et/et0102.bin`` is not in the original tree at all -- the English item
  database does not fit ``et/ET0001.BIN``'s three separate 64 KB ceilings, so
  the patched loader is re-pointed at a file we add.  ``giten install``'s "no
  counterpart in the game folder" rule refused it.

These tests pin both halves: the builders produce exactly what the dedicated
commands produce, and the install guards fire.
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from giten import build_v2, container, etdb, files, install, itemdb, paths  # noqa: E402


def test_the_build_writes_the_same_etdb_files_that_giten_etdb_writes():
    for name, rel in (("skills", "et/ET0004.BIN"), ("maplabels", "et/ET0101.BIN")):
        spec = etdb.SPECS[name]
        assert spec.rel == rel
        # what `giten etdb` writes
        recs = etdb.parse(spec, etdb.source(spec, paths.ORIGINAL_DDSWIN))
        want = etdb.pack_file(spec, etdb.build(spec, recs, etdb.read_table(spec)))
        # what the build writes, from the file's own bytes
        raw = files.read_source(rel, paths.ORIGINAL_DDSWIN)
        got = build_v2.DATA_TABLE_BUILDERS[rel](raw)
        assert got == want, "%s: build %d bytes, etdb %d" % (rel, len(got), len(want))
        # ...and it is not simply the original copied through
        assert got != raw, "%s came out identical to the Japanese" % rel


def test_the_build_writes_the_same_item_database_that_giten_itemdb_writes():
    rel, (src_rel, fn) = "et/et0102.bin", build_v2.ADDED_FILES["et/et0102.bin"]
    assert src_rel == "et/ET0001.BIN"
    recs = itemdb.parse(itemdb.source_body(paths.ORIGINAL_DDSWIN))
    table = os.path.join(paths.REPO_ROOT, "tables", "itemdb.tsv")
    strings, _findings = itemdb.strings_from_table(table, recs)
    want = itemdb.pack_file(recs, strings)
    got, _f = fn(files.read_source(src_rel, paths.ORIGINAL_DDSWIN))
    assert got == want, "%s: build %d bytes, itemdb %d" % (rel, len(got), len(want))
    # and the original it is derived from is left alone
    assert got != files.read_source(src_rel, paths.ORIGINAL_DDSWIN)


def test_the_english_etdb_files_actually_carry_english():
    """Not vacuous: if the tables were empty these builders would be identity
    copies and the test above would still pass on the second assert alone."""
    for name in ("skills", "maplabels"):
        spec = etdb.SPECS[name]
        assert etdb.read_table(spec), "%s has no English at all" % spec.table
        raw = files.read_source(spec.rel, paths.ORIGINAL_DDSWIN)
        body = container.split(build_v2.DATA_TABLE_BUILDERS[spec.rel](raw))[0][0].body
        recs = etdb.parse(spec, body)
        ascii_names = sum(1 for r in recs
                          if r.text(0) and r.text(0).isascii())
        assert ascii_names > 10, "%s: only %d ASCII strings" % (spec.rel, ascii_names)


# ----------------------------------------------------------------- install --

def _tree(base, paths_and_bytes):
    for rel, data in paths_and_bytes.items():
        p = os.path.join(base, *rel.split("/"))
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "wb") as fh:
            fh.write(data)
    return base


def test_install_adds_an_allow_listed_file_and_refuses_any_other():
    tmp = tempfile.mkdtemp(prefix="giten-install-")
    try:
        src = _tree(os.path.join(tmp, "src"), {
            "et/ET0000.BIN": b"new",
            "et/et0102.bin": b"added",
            "dds.exe": b"exe",
        })
        dst = _tree(os.path.join(tmp, "dst"), {
            "et/ET0000.BIN": b"old",
            "dds.exe": b"exe",
        })
        st = install.run(src, dst, backup_dir=os.path.join(tmp, "bk"),
                         dry_run=False, quiet=True)
        assert st["added"] == 1, st
        assert st["copied"] == 2, st           # the replacement and the addition
        with open(os.path.join(dst, "et", "et0102.bin"), "rb") as fh:
            assert fh.read() == b"added"

        # a file that is neither present nor allow-listed is still refused
        with open(os.path.join(src, "et", "ET9999.BIN"), "wb") as fh:
            fh.write(b"stray")
        try:
            install.run(src, dst, backup_dir=os.path.join(tmp, "bk2"),
                        dry_run=True, quiet=True)
        except SystemExit as exc:
            assert "no counterpart" in str(exc), exc
        else:
            raise AssertionError("a stray file was accepted")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_install_refuses_byte_built_m_files_over_an_overlay_install():
    """An overlay install's m/ files are the originals, and they have to stay
    that way: v6 keys every span on the content of its record."""
    tmp = tempfile.mkdtemp(prefix="giten-install-")
    try:
        src = _tree(os.path.join(tmp, "src"), {"m/MS0000.BIN": b"built"})
        dst = _tree(os.path.join(tmp, "dst"), {"m/MS0000.BIN": b"original",
                                               "overlay.dat": b"v6"})
        try:
            install.run(src, dst, backup_dir=os.path.join(tmp, "bk"),
                        dry_run=True, quiet=True)
        except SystemExit as exc:
            assert "overlay.dat" in str(exc) and "m/MS0000" in str(exc).replace(os.sep, "/"), exc
        else:
            raise AssertionError("m/ files were installed over an overlay build")
        with open(os.path.join(dst, "m", "MS0000.BIN"), "rb") as fh:
            assert fh.read() == b"original"

        # ...and with no overlay.dat there, the same install is fine
        os.remove(os.path.join(dst, "overlay.dat"))
        st = install.run(src, dst, backup_dir=os.path.join(tmp, "bk2"),
                         dry_run=False, quiet=True)
        assert st["copied"] == 1, st
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
