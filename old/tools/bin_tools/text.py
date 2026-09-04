"""Extract player-visible text lines from a decoded Giten script body."""
import sys,os,re
CTRL_TEXT={0xd0,0xd2,0xd3,0xba,0xb1,0xb2,0xb7,0xbb,0xbc,0xbd,0xbe,0xbf}
def lines(buf):
    """Yield (offset, tag, text). Text starts after a 0x1F xx control and runs
    until the next control byte < 0x20 (0x0A newline is kept)."""
    out=[];i=0;n=len(buf)
    while i<n:
        if buf[i]==0x1f and i+1<n:
            tag=buf[i+1]; j=i+2; chars=[]
            while j<n:
                b=buf[j]
                if b==0x1f or b<0x20 or b==0x7f: break
                if (0x81<=b<=0x9f or 0xe0<=b<=0xef) and j+1<n and 0x40<=buf[j+1]<=0xfc and buf[j+1]!=0x7f:
                    try: chars.append(buf[j:j+2].decode('cp932')); j+=2; continue
                    except Exception: break
                if 0x20<=b<0x7f: chars.append(chr(b)); j+=1; continue
                if 0xa1<=b<=0xdf: chars.append(bytes([b]).decode('cp932')); j+=1; continue
                break
            s=''.join(chars)
            if s.strip(): out.append((i,f'1F{tag:02X}',s))
            i=max(j,i+2); continue
        i+=1
    return out
JP=re.compile(r'[぀-ゟ゠-ヿ一-鿿]')
if __name__=='__main__':
    b=open('decoded/'+sys.argv[1],'rb').read()
    only=('--jp' in sys.argv)
    lim=10**9
    for a in sys.argv[2:]:
        if a.isdigit(): lim=int(a)
    c=0
    for o,t,s in lines(b):
        if only and not JP.search(s): continue
        print(f'{o:06x} {t}  {s[:110]}'); c+=1
        if c>=lim: break
