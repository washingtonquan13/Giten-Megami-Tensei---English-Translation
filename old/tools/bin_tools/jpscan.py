import os,sys,re,datetime,json
sys.path.insert(0,os.path.dirname(os.path.abspath(__file__)))
from giten import ROOT
JP=re.compile(r'[぀-ゟ゠-ヿ一-鿿　-〿！-｠]')
def sjis_runs(buf,minlen=2):
    """Extract runs where DOUBLE-BYTE sjis chars dominate -> real Japanese."""
    res=[];i=0;n=len(buf)
    while i<n-1:
        b,c=buf[i],buf[i+1]
        if (0x81<=b<=0x9f or 0xe0<=b<=0xef) and 0x40<=c<=0xfc and c!=0x7f:
            j=i;txt=[]
            while j<n-1:
                b2,c2=buf[j],buf[j+1]
                if (0x81<=b2<=0x9f or 0xe0<=b2<=0xef) and 0x40<=c2<=0xfc and c2!=0x7f:
                    try: txt.append(buf[j:j+2].decode('cp932'))
                    except Exception: break
                    j+=2
                elif 0x20<=b2<0x7f and txt:
                    txt.append(chr(b2)); j+=1
                else: break
            s=''.join(txt).rstrip()
            if len(JP.findall(s))>=minlen: res.append((i,s))
            i=max(j,i+1)
        else: i+=1
    return res
rows=[]
for d in ['m','p','et']:
    for f in sorted(os.listdir(f'decoded/{d}')):
        buf=open(f'decoded/{d}/{f}','rb').read()
        r=sjis_runs(buf)
        if r:
            st=os.stat(os.path.join(ROOT,d,f))
            rows.append((d,f,len(buf),datetime.datetime.fromtimestamp(st.st_mtime).strftime('%Y-%m-%d'),r))
tot=0
for d,f,sz,dt,r in rows:
    tot+=len(r)
    print(f"=== {d}/{f}  {sz}B  mtime={dt}  jp_runs={len(r)}")
    for o,s in r[:8]: print(f"    {o:06x}  {s[:100]}")
    if len(r)>8: print(f"    ... +{len(r)-8} more")
print(f"\nTOTAL files with real Japanese: {len(rows)}, total runs: {tot}")
