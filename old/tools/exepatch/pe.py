"""Minimal PE32 reader plus a single mutation: append a new section.

Deliberately independent of ``tools/exe_analysis/pe.py`` (which is read-only
analysis scaffolding) so the patcher can be tested in isolation, but the header
layout logic is the same.
"""
from __future__ import annotations

import struct

SECTION_HEADER_SIZE = 40


class PEError(Exception):
    pass


class PE:
    """Parsed PE32 image.  ``data`` stays a plain ``bytes``; mutations return
    new ``bytes`` rather than editing in place."""

    def __init__(self, data: bytes, path: str = "<bytes>"):
        if isinstance(data, bytearray):
            data = bytes(data)
        self.data = data
        self.path = path
        d = data
        if d[:2] != b"MZ":
            raise PEError("not an MZ image")
        self.e_lfanew = struct.unpack_from("<I", d, 0x3C)[0]
        if d[self.e_lfanew:self.e_lfanew + 4] != b"PE\0\0":
            raise PEError("bad PE signature")
        fh = self.e_lfanew + 4
        (self.machine, self.numsec, self.timedate, self.ptr_symtab,
         self.numsym, self.sizeopt, self.chars) = struct.unpack_from("<HHIIIHH", d, fh)
        self.file_header_off = fh
        oh = fh + 20
        self.opt_off = oh
        magic = struct.unpack_from("<H", d, oh)[0]
        if magic != 0x10B:
            raise PEError("not PE32 (magic %04x)" % magic)
        (self.majlink, self.minlink, self.sizecode, self.sizeinit, self.sizeuninit,
         self.entry, self.basecode, self.basedata, self.imagebase) = struct.unpack_from(
            "<BBIIIIIII", d, oh + 2)
        self.secalign, self.filealign = struct.unpack_from("<II", d, oh + 32)
        self.sizeimage, self.sizeheaders = struct.unpack_from("<II", d, oh + 56)
        self.checksum = struct.unpack_from("<I", d, oh + 64)[0]
        self.numrva = struct.unpack_from("<I", d, oh + 92)[0]
        self.sectbl_off = oh + self.sizeopt
        self.sections = []
        for i in range(self.numsec):
            base = self.sectbl_off + i * SECTION_HEADER_SIZE
            name = d[base:base + 8].rstrip(b"\0").decode("latin1")
            (vsize, vaddr, rawsize, rawptr, relptr, lnptr,
             numrel, numln, flags) = struct.unpack_from("<IIIIIIHHI", d, base + 8)
            self.sections.append(dict(index=i, name=name, vsize=vsize, vaddr=vaddr,
                                      rawsize=rawsize, rawptr=rawptr, flags=flags,
                                      header_off=base))

    # ------------------------------------------------------------- lookups
    def section(self, name):
        for s in self.sections:
            if s["name"] == name:
                return s
        return None

    def sec_for_rva(self, rva):
        for s in self.sections:
            if s["vaddr"] <= rva < s["vaddr"] + max(s["vsize"], s["rawsize"]):
                return s
        return None

    def sec_for_off(self, off):
        for s in self.sections:
            if s["rawptr"] <= off < s["rawptr"] + s["rawsize"]:
                return s
        return None

    def rva2off(self, rva):
        s = self.sec_for_rva(rva)
        if not s:
            return None
        o = rva - s["vaddr"] + s["rawptr"]
        if o >= s["rawptr"] + s["rawsize"]:
            return None
        return o

    def off2rva(self, off):
        s = self.sec_for_off(off)
        if not s:
            return None
        return off - s["rawptr"] + s["vaddr"]

    def va2off(self, va):
        return self.rva2off(va - self.imagebase)

    def off2va(self, off):
        r = self.off2rva(off)
        return None if r is None else r + self.imagebase

    def cstring_at_va(self, va, limit=4096):
        off = self.va2off(va)
        if off is None:
            return None
        end = self.data.find(b"\0", off, off + limit)
        if end < 0:
            return None
        return self.data[off:end]

    # ------------------------------------------------------------ mutation
    def append_section(self, name: str, blob: bytes, characteristics: int) -> bytes:
        """Return a new image with ``blob`` appended as a fresh section.

        The section header goes into the slack after the existing section table
        (this image has 0x1A0 bytes of zeroed slack before ``SizeOfHeaders``),
        the raw data goes at the current end of file, and the virtual address is
        the image's current ``SizeOfImage`` (already section-aligned).
        """
        if not blob:
            raise PEError("refusing to append an empty section")
        d = bytearray(self.data)

        hdr_off = self.sectbl_off + self.numsec * SECTION_HEADER_SIZE
        hdr_end = hdr_off + SECTION_HEADER_SIZE
        if hdr_end > self.sizeheaders:
            raise PEError("no room in SizeOfHeaders for another section header")
        if any(d[hdr_off:hdr_end]):
            raise PEError("section-header slack at 0x%x is not zero" % hdr_off)

        rawptr = len(d)
        if rawptr % self.filealign:
            pad = self.filealign - (rawptr % self.filealign)
            d.extend(b"\0" * pad)
            rawptr = len(d)

        vaddr = self.sizeimage
        if vaddr % self.secalign:
            raise PEError("SizeOfImage 0x%x is not section-aligned" % vaddr)

        vsize = len(blob)
        rawsize = (vsize + self.filealign - 1) // self.filealign * self.filealign
        d.extend(blob)
        d.extend(b"\0" * (rawsize - vsize))

        raw_name = name.encode("ascii")
        if len(raw_name) > 8:
            raise PEError("section name too long")
        struct.pack_into("<8sIIIIIIHHI", d, hdr_off,
                         raw_name.ljust(8, b"\0"), vsize, vaddr, rawsize, rawptr,
                         0, 0, 0, 0, characteristics)

        # NumberOfSections
        struct.pack_into("<H", d, self.file_header_off + 2, self.numsec + 1)
        # SizeOfImage
        new_sizeimage = vaddr + (vsize + self.secalign - 1) // self.secalign * self.secalign
        struct.pack_into("<I", d, self.opt_off + 56, new_sizeimage)
        # SizeOfInitializedData (cosmetic, but keep it honest)
        struct.pack_into("<I", d, self.opt_off + 10, self.sizeinit + rawsize)
        # A zero checksum stays zero; Windows does not verify EXE checksums.
        return bytes(d)
