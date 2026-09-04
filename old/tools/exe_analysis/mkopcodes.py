"""mkopcodes.py -- emit docs/opcodes.json, the table the insertion pipeline consumes.

Per opcode index (0x000-0x2FD plus the always-no-op 0x300+ space):
  encoding        the literal byte(s) that select it
  implemented     false -> the engine consumes prefix+byte and does nothing
  operands        ordered list of operand slots, each {kind, size|"var"}
  fixed_size      total operand bytes when every slot is fixed-size, else null
  variable        true when the length depends on operand data (expr / list / rule)
  has_offset      true when one operand is a PC-relative branch displacement
  offset_slots    indices into `operands` that are pc-relative u16 displacements
  refs_record     true when the opcode switches to another file/record
  handler         handler VA in dds_en.exe
  uses            how many times it occurs in the shipped data
Operand kinds:
  u8 / u16 / u32  little-endian literals
  rel16           u16 PC-RELATIVE branch displacement, measured from the byte
                  right after the displacement itself: target = pc_after + imm16
  expr            a recursive expression tree; grammar in `expressions`
  list_ff         bytes up to and including a 0xFF terminator
  rule:<name>     length determined by a documented special rule
"""
import os, sys, json, collections
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout.reconfigure(encoding='utf-8')
HERE = os.path.dirname(os.path.abspath(__file__))
DOCS = os.path.normpath(os.path.join(HERE, '..', '..', 'docs'))

OPDESC = {int(k): v for k, v in json.load(open(os.path.join(HERE, 'opdesc.json'))).items()}
EVALTAB = json.load(open(os.path.join(HERE, 'evaltab.json')))
FIXED = {'u8': 1, 'u16': 2, 'u32': 4, 'rel16': 2, 'expr2': 0}

SPECIAL_RULE = {
    0x210: dict(name='wait_1E10',
                doc='a = u8; b = u8; if b == 0 or b == 2 a third u8 follows '
                    '(handler 0x43C0C0)'),
}
# opcodes that switch the interpreter to another file/record
POOL = {i: dict(file='m/MS7F%02X.BIN' % (i - 1), record='operand 0 (u8)',
                mode='call (return context pushed)') for i in range(1, 9)}
POOL[0x0C] = dict(file='m/MS00%s.BIN from operand 0 (u8 file id)', record='operand 1 (u8)',
                  mode='goto (no return)')
POOL[0x0D] = dict(file='m/MS00%s.BIN from operand 0 (u8 file id)', record='operand 1 (u8)',
                  mode='call (return context pushed)')

def usage():
    try:
        from vm import tokenize, files
        from cont import split_containers, parse_records
    except Exception:
        return collections.Counter()
    c = collections.Counter()
    for name, path in files():
        raw = open(path, 'rb').read()
        conts, endp = split_containers(raw)
        if not conts or endp != len(raw) or any(x['short'] for x in conts): continue
        for cc in conts:
            cnt, recs, end, err = parse_records(cc['body'])
            if err or end != cc['hdr']: break
            for r in recs:
                toks, st = tokenize(r['data'])
                if st: continue
                for off, kind, idx, n in toks:
                    if kind == 'op': c[idx] += 1
    return c

def encoding(i):
    if i < 0x20:  return '%02X' % i
    if i < 0x100: return '%02X' % i
    if i < 0x200: return '1F %02X' % (i - 0x100)
    if i < 0x300: return '1E %02X' % (i - 0x200)
    return '1D %02X' % (i - 0x300)

def main():
    use = usage()
    ops = {}
    for i in range(0x300):
        d = OPDESC.get(i, dict(impl=False, ops=[], handler=None))
        slots = []
        for a in d['ops']:
            if a == 'expr2': continue          # evaluated value, consumes no bytes
            if a == 'expr':    slots.append(dict(kind='expr', size='var'))
            elif a == 'list_ff': slots.append(dict(kind='list_ff', size='var'))
            elif a == 'rel16': slots.append(dict(kind='rel16', size=2))
            else:              slots.append(dict(kind=a, size=FIXED[a]))
        rule = SPECIAL_RULE.get(i)
        if rule:
            slots = [dict(kind='rule:' + rule['name'], size='var')]
        fixed = (sum(s['size'] for s in slots)
                 if all(isinstance(s['size'], int) for s in slots) else None)
        offs = [k for k, s in enumerate(slots) if s['kind'] == 'rel16']
        e = dict(encoding=encoding(i),
                 implemented=bool(d['impl']),
                 handler=('0x%08X' % d['handler']) if d.get('handler') else None,
                 operands=slots,
                 fixed_size=fixed,
                 variable=fixed is None,
                 has_offset=bool(offs),
                 offset_slots=offs,
                 refs_record=i in POOL,
                 uses=use.get(i, 0))
        if i in POOL: e['record_ref'] = POOL[i]
        if rule: e['rule'] = rule['doc']
        ops['0x%03X' % i] = e

    doc = dict(
        _about='Giten Megami Tensei script VM opcode table, recovered from '
               'dds_en.exe (dispatch table at VA 0x4318B0, 0x2FE entries).',
        _text_model='Bytes >= 0x20 are literal Shift-JIS text (2 bytes when the '
                    'first is an SJIS lead byte). There is NO length field for '
                    'text anywhere; a text run ends at the next control byte. '
                    '0x00 terminates a record fragment.',
        _escapes={'0x1D': 'index 0x300 + next byte -- ALWAYS a 2-byte no-op '
                          '(dispatcher rejects > 0x2FD)',
                  '0x1E': 'index 0x200 + next byte',
                  '0x1F': 'index 0x100 + next byte'},
        _branches='rel16 operands are PC-RELATIVE: target = (offset_of_byte_after'
                  '_the_rel16 + imm16) & 0xFFFF, measured inside the runtime '
                  'buffer, which is [0x400-byte, 256-entry index][record data in '
                  'id order]. Relocate a rel16 whenever the byte count between '
                  'the end of the operand and its target changes.',
        _conditional_branch='Every conditional form is [rel16][condition operands] '
                            'and branches when the condition evaluates to 0.',
        expressions=dict(
            _about='Operand slots of kind "expr" are recursive trees read by '
                   '0x436B00. First byte selects the node; the map below gives '
                   'that node\'s ordered payload ("expr" = a nested tree). Node '
                   'bytes above 0x5D are invalid.',
            nodes=EVALTAB),
        opcodes=ops)
    os.makedirs(DOCS, exist_ok=True)
    p = os.path.join(DOCS, 'opcodes.json')
    json.dump(doc, open(p, 'w', encoding='utf-8'), indent=1, ensure_ascii=False)
    print('wrote', p)
    print('implemented %d, with rel16 %d, record refs %d'
          % (sum(1 for v in ops.values() if v['implemented']),
             sum(1 for v in ops.values() if v['has_offset']),
             sum(1 for v in ops.values() if v['refs_record'])))

if __name__ == '__main__':
    main()
