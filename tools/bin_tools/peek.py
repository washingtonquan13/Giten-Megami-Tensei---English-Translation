import sys,re
sys.path.insert(0,'.')
from jpscan import sjis_runs
f=sys.argv[1]; n=int(sys.argv[2]) if len(sys.argv)>2 else 30
buf=open(f'decoded/{f}','rb').read()
for o,s in sjis_runs(buf)[:n]: print(f"{o:06x}  {s[:110]}")
