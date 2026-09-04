import os, sys, re, time, collections, io
sys.stdout.reconfigure(encoding='utf-8')
ROOT = r"D:\BrowserDownloads\Giten Megami Tensei - English - v0.05\Giten Megami Tensei - English\ddswin"
FOLDERS = ["et","fc","m","p","s","w"]

out = io.StringIO()
def P(*a):
    print(*a, file=out)

for f in FOLDERS:
    d = os.path.join(ROOT,f)
    files = sorted(os.listdir(d))
    tot = 0
    years = collections.Counter()
    pat = collections.Counter()
    exts = collections.Counter()
    modern = []
    for fn in files:
        p = os.path.join(d,fn)
        if not os.path.isfile(p): continue
        st = os.stat(p)
        tot += st.st_size
        y = time.localtime(st.st_mtime).tm_year
        years[y]+=1
        base,ext = os.path.splitext(fn)
        exts[ext.upper()]+=1
        # pattern: letters prefix + digits
        m = re.match(r'^([A-Za-z_]*)(\d*)(.*)$', base)
        pat[(m.group(1), len(m.group(2)))]+=1
        if y>=2000:
            modern.append((fn, y, time.strftime('%Y-%m-%d', time.localtime(st.st_mtime)), st.st_size))
    P(f"### {f}: {len([x for x in files if os.path.isfile(os.path.join(d,x))])} files, {tot} bytes")
    P("  exts:", dict(exts))
    P("  name patterns (prefix, numdigits)->count:", dict(pat))
    P("  years:", dict(sorted(years.items())))
    P(f"  modern(>=2000) count: {len(modern)}")
    for fn,y,ds,sz in modern[:60]:
        P(f"    {fn}  {ds}  {sz}b")
    if len(modern)>60: P(f"    ... +{len(modern)-60} more")
    # date range of originals
    olds = []
    for fn in files:
        p=os.path.join(d,fn)
        if os.path.isfile(p):
            st=os.stat(p)
            olds.append((st.st_mtime,fn))
    olds.sort()
    P("  oldest:", time.strftime('%Y-%m-%d %H:%M', time.localtime(olds[0][0])), olds[0][1])
    P("  newest:", time.strftime('%Y-%m-%d %H:%M', time.localtime(olds[-1][0])), olds[-1][1])
    P("")

open(os.path.join(os.path.dirname(__file__),'survey_out.txt'),'w',encoding='utf-8').write(out.getvalue())
print(out.getvalue()[:20000])
