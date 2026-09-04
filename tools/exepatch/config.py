"""Paths and hard constants for the exe patcher.

Every path is derived from the repository root so the tool works no matter what
the current working directory is.  The game folder is *read-only*: nothing in
this package opens a file inside it for writing.
"""
from __future__ import annotations

import os

# tools/exepatch/config.py -> tools/exepatch -> tools -> <repo root>
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# The game tree sits next to the repo, not inside it.
DEFAULT_GAME_DIR = os.path.join(
    os.path.dirname(REPO_ROOT),
    "Giten Megami Tensei - English",
    "ddswin",
)

GAME_DIR = os.environ.get("GITEN_DDSWIN", DEFAULT_GAME_DIR)

EN_EXE = os.path.join(GAME_DIR, "dds_en.exe")     # v0.05 patched build (patch base)
ORG_EXE = os.path.join(GAME_DIR, "dds_org.exe")   # pristine 1999 Japanese original

TABLE_PATH = os.path.join(REPO_ROOT, "text_v2", "exe", "strings.tsv")
BUILD_DIR = os.path.join(REPO_ROOT, "build")
OUT_EXE = os.path.join(BUILD_DIR, "dds_en.exe")

# ---------------------------------------------------------------- PE constants
IMAGE_BASE = 0x400000

# Sections whose NUL-terminated strings we enumerate.
STRING_SECTIONS = (".rdata", ".data")

# Sections scanned for 32-bit absolute references (the exe has no .reloc, so
# every string reference in code is a literal imm32).
REF_SECTIONS = (".text", ".rdata", ".data")

# ------------------------------------------------------------ new .eng section
ENG_SECTION_NAME = ".eng"
# IMAGE_SCN_CNT_INITIALIZED_DATA | IMAGE_SCN_MEM_READ
ENG_CHARACTERISTICS = 0x40000040

# --------------------------------------------------------------- do-not-touch
# The exe renders half-width ASCII from its own 8x16 bitmap font.  Overwriting
# any of it turns the whole UI into confetti.
FONT_TABLE_START = 0x69E30
FONT_TABLE_END = 0x6AA30          # exclusive

# ``push 80h`` -- the SHIFTJIS_CHARSET argument handed to CreateFont for the
# double-byte GDI path.  Changing it kills every Japanese glyph still in use.
# The ``push`` opcode sits at 0x509A8; 0x509A9 is the charset value byte itself.
CHARSET_OFFSET = 0x509A8
CHARSET_BYTES = b"\x6a\x80"
CHARSET_VALUE_OFFSET = 0x509A9

# Half-width ASCII cell width in the bitmap font, in pixels.
ASCII_CELL_PX = 8
# Double-byte glyphs are drawn by GDI at twice that.
WIDE_CELL_PX = 16
