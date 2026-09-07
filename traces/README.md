# Recovered interpreter traces

`*.bin` is gitignored, so these files are **not in git** — they live here only so a
reinstall of `play/` does not destroy them. Back them up with the repo if you care
about them.

| file | what |
|---|---|
| `2026-09-06-en-dev.bin` | The first real play session on record. `dds_dev.exe` + the draft overlay, English. The machine lost power mid-session and the trace still came out clean: 150,019 complete 20-byte records, no torn tail. It is what `docs/playtest-2026-09-06.md` cites throughout, and it settled reports 2 and 7. |

Decode with `python -m giten trace decode traces/<file> --build <tree the trace ran on>`.
A `selfcheck` mismatch rate of roughly the served share is expected when the trace
ran with an overlay and the check is against the Japanese `m/` — see the reading
notes at the end of `docs/playtest-2026-09-06.md`.
