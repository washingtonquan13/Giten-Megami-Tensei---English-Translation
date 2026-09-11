"""The screen audit reads the glyph log the way the log is written.

Two defects this pins, both found on 2026-09-11 while auditing the Roppongi
session:

1. **The character code is a ``u16`` in a ``u32`` field.**  ``textlog.Rec.ch``
   masks ``args[0] & 0xFFFF``; the audit tool had its own reader that took the
   raw dword, so any glyph whose argument carried anything in the high half
   grew a spurious leading byte.  About one glyph in nine on the real log, and
   a corrupted fragment reports "no table row" for text sitting in a table.
2. **The verdict has to be judged on what the English renders to**, not on the
   ``en`` cell: an English line that splices an untranslated pool call reaches
   the screen in Japanese, which is the fault being looked for.

The log here is written by the test rather than sampled, so the mask is pinned
against the format and not against one recording.
"""
from __future__ import annotations

import os
import struct
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))

from giten import tables, textlog  # noqa: E402
import screen_audit  # noqa: E402

#: a line the real log drew, and one the tables hold
SAMPLE = "手に入れた"
#: a district name: flat et/ data, not script
DATA_SAMPLE = "六本木"


def _log(path, calls):
    """Write a GTXT v3 log.  ``calls`` is ``[(variant, text, high)]``.

    ``high`` goes in the top 16 bits of every glyph's first argument -- which is
    what the real exe leaves there and what the old reader mistook for part of
    the character.
    """
    with open(path, "wb") as fh:
        fh.write(textlog.MAGIC + struct.pack("<HH", textlog.VERSION, textlog.REC))
        for variant, text, high in calls:
            fh.write(struct.pack("<HH", variant, 0) + b"\0" * 32)
            for b in text.encode("cp932"):
                pass
            raw = text.encode("cp932")
            i = 0
            while i < len(raw):
                if raw[i] >= 0x81 and i + 1 < len(raw):
                    ch = (raw[i] << 8) | raw[i + 1]
                    i += 2
                else:
                    ch = raw[i]
                    i += 1
                fh.write(struct.pack("<HH", 0, 0)
                         + struct.pack("<I", (high << 16) | ch) + b"\0" * 28)


def _unmasked(path):
    """The old reader: the raw ``u32`` instead of ``args[0] & 0xFFFF``."""
    with open(path, "rb") as fh:
        blob = fh.read()
    raw, at = bytearray(), textlog.HEADER
    while at + textlog.REC <= len(blob):
        if not struct.unpack_from("<H", blob, at)[0]:
            ch = struct.unpack_from("<I", blob, at + 4)[0]
            if ch > 0xFF:
                raw.append((ch >> 8) & 0xFF)
            raw.append(ch & 0xFF)
        at += textlog.REC
    return bytes(raw)


def test_the_glyph_code_is_masked_to_sixteen_bits():
    """The bug bites on **one-byte** glyphs: ASCII and half-width katakana.

    A two-byte character survives the unmasked read by luck -- shifting right
    by 8 happens to recover its lead byte -- so a sample of kanji alone would
    not have caught this.  Anything the exe left in the high half of the
    argument turns a one-byte glyph into two, and the byte that comes out is
    whatever that garbage was.
    """
    tmp = tempfile.mkdtemp(prefix="giten-audit-")
    try:
        p = os.path.join(tmp, "textout.bin")
        mixed = SAMPLE + "AB"
        _log(p, [(1, mixed, 0x1234)])
        got = screen_audit.drawn_strings(p)
        assert len(got) == 1, got
        assert got[0][1].decode("cp932") == mixed, got

        bad = _unmasked(p)
        assert bad != mixed.encode("cp932"), "the mutation changed nothing"
        assert len(bad) == len(mixed.encode("cp932")) + 2, bad
        # and the byte each one-byte glyph grew is the NUL the Roppongi audit
        # saw in front of about one glyph in nine
        assert bad.endswith(b"\x00A\x00B"), bad

        # with a clean high half both readers agree, which is why this went
        # unnoticed on the small logs
        p2 = os.path.join(tmp, "clean.bin")
        _log(p2, [(1, mixed, 0)])
        assert _unmasked(p2) == mixed.encode("cp932")
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


def test_a_typewriter_variant_is_glued_back_into_one_string():
    """Variant 6 calls the glyph drawer once per character; counting those calls
    separately shreds every sentence into single characters, and the audit's
    two-character floor then drops all of them."""
    tmp = tempfile.mkdtemp(prefix="giten-audit-")
    try:
        p = os.path.join(tmp, "textout.bin")
        _log(p, [(6, c, 0) for c in SAMPLE])
        got = screen_audit.drawn_strings(p)
        assert len(got) == 1, got
        assert got[0][1].decode("cp932") == SAMPLE
        # a non-typewriter variant is NOT glued
        p2 = os.path.join(tmp, "t2.bin")
        _log(p2, [(1, c, 0) for c in SAMPLE])
        assert len(screen_audit.drawn_strings(p2)) == len(SAMPLE)
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


def test_the_verdict_is_judged_on_what_the_english_renders_to():
    """`en` can look English and still draw Japanese, because a pool call it
    keeps is untranslated.  That is the fault the audit exists to find."""
    epool = {("08", "60"): "obtained", ("08", "61"): "入れた"}
    R = tables.Row

    assert screen_audit.verdict_of(None, epool) == "NO TABLE ROW"
    assert screen_audit.verdict_of(
        R("m/X.BIN", "0:00", 0, 0, "18", SAMPLE, ""), epool) == "NOT TRANSLATED"
    assert screen_audit.verdict_of(
        R("m/X.BIN", "0:00", 0, 0, "18", SAMPLE, "It was {08:60}."),
        epool) == "SERVED?"
    # the same row whose call renders Japanese
    assert screen_audit.verdict_of(
        R("m/X.BIN", "0:00", 0, 0, "18", SAMPLE, "It was {08:61}."),
        epool) == "EN IS JAPANESE"
    # ...and plain Japanese left in the cell
    assert screen_audit.verdict_of(
        R("m/X.BIN", "0:00", 0, 0, "18", SAMPLE, SAMPLE),
        epool) == "EN IS JAPANESE"


def test_the_ch_stream_is_the_bytes_the_interpreter_dispatched():
    """One event per character, each contributing its own bytes, so a byte
    offset in the stream names the event that drew it."""
    class E:
        def __init__(self, ch):
            self.ch = ch

    raw = SAMPLE.encode("cp932")
    evs = [E((raw[i] << 8) | raw[i + 1]) for i in range(0, len(raw), 2)]
    evs = [E(0)] + evs + [E(0x41)]          # a no-char event and an ASCII one
    stream, owner = screen_audit.ch_stream(evs)
    assert stream == raw + b"A", stream
    assert len(owner) == len(stream)
    # every byte is charged to the event that produced it
    at = stream.find(SAMPLE[2].encode("cp932"))
    assert owner[at] == 3, owner[:8]        # index 0 is the ch == 0 event
    assert owner[-1] == len(evs) - 1


def test_the_flat_et_tables_are_recognised_as_their_own_source():
    """A district name must not be matched against the script tables: 新宿
    appears in 148 dialogue rows and crediting one of them reports "here is the
    row" about a row the location strip never reads.

    This also replaces the hard-coded UNEXTRACTED list, which still claimed
    et/ET000D had no extractor after the districts work shipped one.
    """
    data = screen_audit.data_strings()
    assert DATA_SAMPLE in data, "%r is not in any flat et/ table" % DATA_SAMPLE
    src, en = data[DATA_SAMPLE]
    assert "ET000D" in src, src
    assert en, "the districts table has no English for %r" % DATA_SAMPLE
    # the skill database is in there too, and carries English
    assert any("ET0004" in s for s, _e in data.values())
    assert sum(1 for _s, e in data.values() if e) > 100
