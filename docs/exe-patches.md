# Exe patches

Source of truth for `python -m giten exe build-*`. Every row is applied to `original/ddswin/dds_org.exe` and the applier asserts the `old` bytes before writing.

Sets: `xp` (base), `locale` (release = base + locale), `dev` (dev = release + tracer + debug arm; see below).

| set | file offset | old | new | note |
|---|---|---|---|---|
| xp | 0x506BC | `837c240c07772c33d28a4c142083c2048ac1c0f9` | `8bd8c1eb02837c240c07772c33d28a4c142083c2` | XP compatibility patch r0.2b (code only; its font edits at 0x69E42+ are NOT carried) |
| xp | 0x506D1 | `80e10f240f884c141c8a4c141dc0e004c0f9040ac183fa408844141d7cd66681fe518174398b5424188b0495d0cf460083f81e7d318d4c24218a51ff83c104885438028a51fc8854380383c00283f81e7ce78bc75f5e5b81c494000000c3b0ff88471f88471e8bc75f5e5b81c494000000c39090909090909090` | `8ac1c0f90480e10f240f884c141c8a4c141dc0e004c0f9040ac183fa408844141d7cd66681fe5181743c8b5424188b0495d0cf460083f81e7d348d4c24218a51ff83c104885438028a51fc8854380383c00283f81e7d034b75e48bc75f5e5b81c494000000c3b0ff88471f88471e8bc75f5e5b81c494000000c3` | XP compatibility patch r0.2b (code only; its font edits at 0x69E42+ are NOT carried) |
| xp | 0x54B8B | `0f8440010000` | `909090909090` | XP compatibility patch r0.2b (code only; its font edits at 0x69E42+ are NOT carried) |
| xp | 0x5AB04 | `75` | `74` | XP compatibility patch r0.2b (code only; its font edits at 0x69E42+ are NOT carried) |
| locale | 0x59DE0 | `6afde819fbffff83c404c39090909090` | `68a4030000e816fbffff83c404c39090` | __initmbctable: _setmbcp(-3=ANSI) -> _setmbcp(932); rel32 = 0x45A500-0x45A9EA |
| locale | 0x509A9 | `01` | `80` | CreateFontA lfCharSet DEFAULT_CHARSET -> SHIFTJIS_CHARSET |
