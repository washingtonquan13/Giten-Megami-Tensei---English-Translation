import sys,os,re
def strings(buf,minlen=2):
    res=[];i=0;n=len(buf)
    while i<n:
        if buf[i]==0: i+=1; continue
        j=i
        while j<n and buf[j]!=0: j+=1
        ch=buf[i:j]
        try: t=ch.decode('cp932')
        except Exception: i=j+1; continue
        if len(t)>=minlen and all(c=='\n' or ord(c)>=0x20 for c in t):
            res.append((i,t))
        i=j+1
    return res
if __name__=='__main__':
    b=open('decoded/'+sys.argv[1],'rb').read()
    lim=int(sys.argv[2]) if len(sys.argv)>2 else 60
    for o,t in strings(b,int(sys.argv[3]) if len(sys.argv)>3 else 2)[:lim]:
        print(f'{o:06x}  {t[:100]}')
