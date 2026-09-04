import os
D=r"D:\BrowserDownloads\Giten Megami Tensei - English - v0.05\Giten Megami Tensei - English\ddswin"
org=open(os.path.join(D,'dds_org.exe'),'rb').read()
d21=open(os.path.join(D,'dds.exe'),'rb').read()
d22=open(os.path.join(D,'dds_en.exe'),'rb').read()
A={i for i in range(len(org)) if org[i]!=d21[i]}      # org->21
B={i for i in range(len(org)) if org[i]!=d22[i]}      # org->22
C={i for i in range(len(org)) if d21[i]!=d22[i]}      # 21->22
print("len A(org->21)=%d B(org->22)=%d C(21->22)=%d"%(len(A),len(B),len(C)))
print("A subset of B?", A<=B)
print("A & C (offsets 2021 changed that 2022 changed again):", len(A&C))
print("A | C == B ?", (A|C)==B, " |A|C|=",len(A|C))
# for every offset in A, does d22 have the SAME byte as d21?
same = all(d21[i]==d22[i] for i in A)
print("every 2021-change byte preserved verbatim in 2022?", same)
# any offset where 2022 reverted to original?
rev = [i for i in A if d22[i]==org[i]]
print("offsets 2022 reverted to original:", len(rev))
print("C disjoint from A?", len(A&C)==0)
