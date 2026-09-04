import struct, sys

class PE:
    def __init__(self, path):
        self.path = path
        self.data = open(path,'rb').read()
        d = self.data
        assert d[:2]==b'MZ'
        self.e_lfanew = struct.unpack_from('<I', d, 0x3C)[0]
        assert d[self.e_lfanew:self.e_lfanew+4]==b'PE\0\0', d[self.e_lfanew:self.e_lfanew+4]
        fh = self.e_lfanew+4
        (self.machine, self.numsec, self.timedate, self.ptr_symtab,
         self.numsym, self.sizeopt, self.chars) = struct.unpack_from('<HHIIIHH', d, fh)
        oh = fh+20
        self.magic = struct.unpack_from('<H', d, oh)[0]
        assert self.magic == 0x10b, hex(self.magic)
        (self.majlink,self.minlink,self.sizecode,self.sizeinit,self.sizeuninit,
         self.entry,self.basecode,self.basedata,self.imagebase) = struct.unpack_from('<BBIIIIIII', d, oh+2)
        (self.secalign,self.filealign) = struct.unpack_from('<II', d, oh+32)
        self.sizeimage, self.sizeheaders = struct.unpack_from('<II', d, oh+56)
        self.subsystem = struct.unpack_from('<H', d, oh+68)
        self.numrva = struct.unpack_from('<I', d, oh+92)[0]
        self.dirs = []
        for i in range(self.numrva):
            rva,sz = struct.unpack_from('<II', d, oh+96+i*8)
            self.dirs.append((rva,sz))
        self.sections=[]
        so = oh + self.sizeopt
        for i in range(self.numsec):
            base = so+i*40
            name = d[base:base+8].rstrip(b'\0').decode('latin1')
            (vsize,vaddr,rawsize,rawptr,relptr,lnptr,numrel,numln,flags)=struct.unpack_from('<IIIIIIHHI', d, base+8)
            self.sections.append(dict(name=name,vsize=vsize,vaddr=vaddr,rawsize=rawsize,
                                      rawptr=rawptr,flags=flags))
    def sec_for_rva(self, rva):
        for s in self.sections:
            if s['vaddr'] <= rva < s['vaddr']+max(s['vsize'],s['rawsize']):
                return s
        return None
    def sec_for_off(self, off):
        for s in self.sections:
            if s['rawptr'] <= off < s['rawptr']+s['rawsize']:
                return s
        return None
    def rva2off(self, rva):
        s = self.sec_for_rva(rva)
        if not s: return None
        o = rva - s['vaddr'] + s['rawptr']
        if o >= s['rawptr']+s['rawsize']: return None
        return o
    def off2rva(self, off):
        s = self.sec_for_off(off)
        if not s: return None
        return off - s['rawptr'] + s['vaddr']
    def va2off(self, va):
        return self.rva2off(va - self.imagebase)
    def off2va(self, off):
        r = self.off2rva(off)
        return None if r is None else r + self.imagebase

if __name__=='__main__':
    p = PE(sys.argv[1])
    import datetime
    print("machine %04x numsec %d timedate %d (%s)" % (p.machine,p.numsec,p.timedate,
        datetime.datetime.utcfromtimestamp(p.timedate)))
    print("imagebase %08x entry rva %08x (va %08x) sizeimage %08x secalign %x filealign %x" %
          (p.imagebase,p.entry,p.imagebase+p.entry,p.sizeimage,p.secalign,p.filealign))
    print("linker %d.%d subsystem %s" % (p.majlink,p.minlink,p.subsystem))
    print("%-9s %-9s %-9s %-9s %-9s %s" % ("name","vaddr","vsize","rawptr","rawsize","flags"))
    for s in p.sections:
        print("%-9s %08x  %08x  %08x  %08x  %08x" % (s['name'],s['vaddr'],s['vsize'],s['rawptr'],s['rawsize'],s['flags']))
    names=["EXPORT","IMPORT","RESOURCE","EXCEPTION","SECURITY","BASERELOC","DEBUG","ARCH","GLOBALPTR","TLS","LOADCFG","BOUNDIMP","IAT","DELAYIMP","CLR","RES"]
    for i,(r,sz) in enumerate(p.dirs):
        if r or sz:
            print("DIR %-10s rva %08x size %08x off %s" % (names[i] if i<len(names) else i, r, sz, p.rva2off(r)))
    print("file size", len(p.data))
