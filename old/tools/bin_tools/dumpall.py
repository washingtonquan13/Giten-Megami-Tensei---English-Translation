import os,sys,json,datetime
sys.path.insert(0,os.path.dirname(os.path.abspath(__file__)))
from giten import ROOT, unxor, dump_all
os.makedirs('decoded',exist_ok=True)
summary=[]
for d in ['m','p','et']:
    os.makedirs(f'decoded/{d}',exist_ok=True)
    for f in sorted(os.listdir(os.path.join(ROOT,d))):
        fp=os.path.join(ROOT,d,f)
        raw=open(fp,'rb').read()
        st=os.stat(fp); yr=datetime.datetime.fromtimestamp(st.st_mtime).year
        hdr=int.from_bytes(raw[:2],'little')
        # A* and CA* are plain
        plain = f.startswith('A') or f.startswith('CA')
        body = raw if plain else unxor(raw[2:])
        open(f'decoded/{d}/{f}','wb').write(body)
        strs=dump_all(body,3)
        jp=sum(1 for o,t in strs if any(ord(c)>0x7f for c in t))
        en=sum(1 for o,t in strs if all(ord(c)<0x80 for c in t))
        summary.append(dict(dir=d,file=f,size=len(raw),hdr=hdr,hdr_ok=(hdr==len(raw)-2),
                            year=yr,plain=plain,nstr=len(strs),jp=jp,en=en,
                            jptext=[t for o,t in strs if any(ord(c)>0x7f for c in t)][:40]))
json.dump(summary,open('summary.json','w',encoding='utf-8'),ensure_ascii=False,indent=0)
# report
print("=== header==size-2 check ===")
for d in ['m','p','et']:
    rows=[s for s in summary if s['dir']==d and not s['plain']]
    ok=sum(1 for s in rows if s['hdr_ok'])
    print(f"{d}: {ok}/{len(rows)} match")
    bad=[s['file'] for s in rows if not s['hdr_ok']]
    if bad: print("   mismatch:", bad[:30], f"(total {len(bad)})")
