"""Quarantine translated rows whose source text has a {XX} control token followed
directly by text.

The byte after opcodes 01..08 / 0B / 0C is an operand.  When that operand byte is
>= 0x20 the extractor renders it as if it were text, so it shows up in `jp` as a
stray character glued to the token (e.g. `{0C}9しまった`, `{02}じゃd`).  A translator
who "cleans up" that stray character deletes an operand and corrupts the script.

Until the pipeline models operands, any edited row of that shape is reverted to
an empty `en` and tagged `@operand` in `note`, so it is re-done later instead of
being built.  Rows where the token is followed by another token, a colon, a line
break, a page wait, or end-of-text are left alone (the operand is already
preserved as its own token, or there is no operand in the text run).

Usage:  python tools/scripts/quarantine_operands.py text/m/MS00*.tsv
"""
import glob, re, sys

# A token directly preceded by another token is that token's operand (operands
# < 0x20 render as their own {XX}), so text after it is legitimate; only a token
# with no token before it and text right after it has swallowed an operand.
TOKEN_THEN_TEXT = re.compile(r'(?<!\})\{[0-9A-F]{2}\}(?!\{|：|:|\n|<wait>|$)')

def quarantine(path):
    lines = open(path, encoding='utf-8', newline='').read().split('\n')
    nl = '\r\n' if lines and lines[0].endswith('\r') else '\n'
    out, changed = [], 0
    for line in lines:
        raw = line.rstrip('\r')
        if raw.startswith('#') or raw.startswith('file\t') or not raw:
            out.append(raw); continue
        p = raw.split('\t')
        if len(p) < 8:
            out.append(raw); continue
        jp, en, note = p[5], p[6], p[7]
        if en and en != jp and TOKEN_THEN_TEXT.search(jp) and '@operand' not in note:
            p[6] = ''
            p[7] = (note + ' ' if note else '') + '@operand'
            changed += 1
        out.append('\t'.join(p))
    if changed:
        open(path, 'w', encoding='utf-8', newline='').write(nl.join(out))
    return changed

if __name__ == '__main__':
    total = 0
    for pat in sys.argv[1:]:
        for f in sorted(glob.glob(pat)):
            n = quarantine(f)
            if n: print(f'{n:5d}  {f}')
            total += n
    print(f'quarantined {total} rows')
