import sys
from msparse import parse
buf=open('decoded/'+sys.argv[1],'rb').read()
lim=int(sys.argv[2]) if len(sys.argv)>2 else 20
i=2; recs=[]; gaps=0
while i+3<=len(buf):
    rid=buf[i]; ln=int.from_bytes(buf[i+1:i+3],'little')
    if ln>0 and i+3+ln<=len(buf) and buf[i+3+ln-1]==0:
        recs.append((i,rid,ln,buf[i+3:i+3+ln])); i+=3+ln
    else:
        i+=1; gaps+=1
print(f"file={sys.argv[1]} bodylen={len(buf)} hdr={int.from_bytes(buf[:2],'little')} records={len(recs)} unparsed_bytes={gaps}")
for off,rid,ln,d in recs[:lim]:
    print(f"{off:06x} id={rid:02X} len={ln:4d}  {' '.join(parse(d))[:150]}")
