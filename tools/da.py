# 풀린 MZ 역어셈블: python da.py 파일 seg:off 끝off
import sys, struct
from capstone import *
d = open(sys.argv[1], 'rb').read()
h = struct.unpack('<14H', d[:28]); img = d[h[4] * 16:]
seg, off = [int(x, 16) for x in sys.argv[2].split(':')]
end = int(sys.argv[3], 16)
md = Cs(CS_ARCH_X86, CS_MODE_16)
for i in md.disasm(img[seg * 16 + off:seg * 16 + end], off):
    print('%04x:%04x  %-16s %s %s' % (seg, i.address, i.bytes.hex(), i.mnemonic, i.op_str))
