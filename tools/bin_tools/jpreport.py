import json,sys
s=json.load(open('summary.json',encoding='utf-8'))
def isjp(t):
    return any('぀'<=c<='ヿ' or '一'<=c<='鿿' or '！'<=c<='ﾟ' for c in t)
print("FILES CONTAINING JAPANESE (kana/kanji) TEXT")
tot=0
for r in s:
    jl=[t for t in r['jptext'] if isjp(t)]
    if jl:
        tot+=1
        print(f"--- {r['dir']}/{r['file']}  size={r['size']} year={r['year']} nstr={r['nstr']} jpstr={r['jp']} en={r['en']}")
        for t in jl[:6]: print("     ", t[:90])
print("total files with JP:",tot,"of",len(s))
