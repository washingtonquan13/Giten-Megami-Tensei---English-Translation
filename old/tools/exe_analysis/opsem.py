"""opsem.py -- classify every implemented script opcode by the VM primitives it reaches."""
import os, sys, struct, json, collections
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout.reconfigure(encoding='utf-8')
from da import _p, _buf
from callgraph import reaches, GRAPH
from script_tokens import load_table

TABLE_VA, TABLE_N, DEFAULT = 0x4318B0, 0x2FE, 0x4318AA
PRIM = {
 0x433EC0:'reltarget', 0x433EE0:'jump', 0x433EF0:'condjump', 0x433F10:'gosub',
 0x433C40:'set_pc', 0x433C50:'set_script', 0x433C70:'set_script_ex',
 0x439150:'menu', 0x4394E0:'flagtest',
 0x401E19:'openfile',
}
def label(i):
    return ("%02X"%i if i<0x100 else "1F %02X"%(i-0x100) if i<0x200
            else "1E %02X"%(i-0x200) if i<0x300 else "1D %02X"%(i-0x300))

o=_p.va2off(TABLE_VA)
T=[struct.unpack_from('<I',_buf,o+4*k)[0] for k in range(TABLE_N)]
tbl=load_table()
rows=[]
for i,h in enumerate(T):
    if h==DEFAULT:
        rows.append(dict(idx=i,label=label(i),handler=None,impl=False,operands=0,prims=[]))
        continue
    hits=reaches(h,set(PRIM),maxdepth=int(sys.argv[1]) if len(sys.argv)>1 else 3)
    rows.append(dict(idx=i,label=label(i),handler=h,impl=True,
                     operands=tbl.get(i,0),
                     prims=sorted(PRIM[k] for k in hits)))
json.dump(rows,open(os.path.join(os.path.dirname(os.path.abspath(__file__)),'opsem.json'),'w'),indent=0)
br=[r for r in rows if r['impl'] and ({'reltarget','jump','condjump','gosub','set_pc'} & set(r['prims']))]
print("implemented: %d"%sum(1 for r in rows if r['impl']))
print("branch/offset-bearing opcodes: %d"%len(br))
for r in br:
    print("   %-8s idx=0x%03x h=%08x operands=%-3d %s"%(r['label'],r['idx'],r['handler'],r['operands'],','.join(r['prims'])))
