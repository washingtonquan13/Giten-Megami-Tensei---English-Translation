"""Giten Megami Tensei (1999) fan-translation pipeline.

Layers, bottom up:

``container``   the ``[u16 header][chain-XOR body]`` wrapper
``framing``     how a decoded body divides into frames, and which own a length
``spans``       where the translatable byte runs are
``tokens``      the reversible text <-> bytes codec for one span
``tables``      the TSV text tables under ``text/``
``extract`` / ``build`` / ``check`` / ``install`` / ``stats``  the commands

Nothing in this package writes into the game folder except ``install``, which
backs up every file it touches first.
"""

__all__ = [
    "container", "framing", "spans", "tokens", "tables", "dictionary",
    "files", "paths", "extract", "build", "check", "install", "stats",
]
