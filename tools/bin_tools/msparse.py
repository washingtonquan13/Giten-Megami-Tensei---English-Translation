"""Parse Giten MS*.BIN / M*.BIN decoded script bodies into readable text.
Byte stream: 0x1F <op>  = escape/control (text colour, speaker box, etc.)
             <0x20      = raw control byte (0x0A newline, 0x1E page, 0x00 end...)
             0x81-0x9F / 0xE0-0xEF + trail = Shift-JIS double byte
             0xA1-0xDF  = half-width katakana
             0x20-0x7E  = ASCII
"""
import sys, os, re
def parse(buf, want_text_only=False):
    out=[]; i=0; n=len(buf); cur=[]
    def flush():
        if cur:
            s=''.join(cur)
            if s.strip(): out.append(s)
            cur.clear()
    while i<n:
        b=buf[i]
        if b==0x1f and i+1<n:
            flush(); 
            if not want_text_only: out.append(f"<1F{buf[i+1]:02X}>")
            i+=2; continue
        if b<0x20:
            if b==0x0a: cur.append('\n'); i+=1; continue
            flush()
            if not want_text_only: out.append(f"<{b:02X}>")
            i+=1; continue
        if (0x81<=b<=0x9f or 0xe0<=b<=0xef) and i+1<n and 0x40<=buf[i+1]<=0xfc and buf[i+1]!=0x7f:
            try: cur.append(buf[i:i+2].decode('cp932')); i+=2; continue
            except Exception: pass
        if 0x20<=b<0x7f: cur.append(chr(b)); i+=1; continue
        if 0xa1<=b<=0xdf: cur.append(bytes([b]).decode('cp932')); i+=1; continue
        flush()
        if not want_text_only: out.append(f"<{b:02X}>")
        i+=1
    flush()
    return out

JP=re.compile(r'[぀-ゟ゠-ヿ一-鿿]')
def texts(buf, minjp=0):
    """Return only the human-readable text chunks."""
    res=[]
    for s in parse(buf, want_text_only=True):
        s=s.strip()
        if len(s)>=2: res.append(s)
    return res

if __name__=='__main__':
    fn=sys.argv[1]
    buf=open(fn if os.path.exists(fn) else f'decoded/{fn}','rb').read()
    mode=sys.argv[2] if len(sys.argv)>2 else 'text'
    lim=int(sys.argv[3]) if len(sys.argv)>3 else 10**9
    if mode=='raw':
        print(' '.join(parse(buf))[:lim*200])
    else:
        for t in texts(buf)[:lim]: print(t)
