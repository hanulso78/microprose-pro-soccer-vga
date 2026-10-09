# 공 구조(03ab:BASE, 0x20 바이트)에 쓰는 코드 자리를 틱과 함께 모은다 (차기 루틴 찾기)
#   SOCGAME=in|out python tools/ballwrite.py 대본.txt 끝틱 BASE16진 [결과.txt]
import sys, os, collections
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import emu, image, cover
from unicorn import UC_HOOK_MEM_WRITE
from unicorn.x86_const import UC_X86_REG_CS, UC_X86_REG_IP

script, t1, base = sys.argv[1], int(sys.argv[2]), int(sys.argv[3], 16)
out = sys.argv[4] if len(sys.argv) > 4 else None
m = emu.Machine(keys=cover.load_script(script))
lo = (emu.LOADSEG + 0x3AB) * 16 + base
log = []


def hw(mu, access, addr, size, value, ud):
    cs = mu.reg_read(UC_X86_REG_CS)
    ip = mu.reg_read(UC_X86_REG_IP)
    log.append((m.ticks, '%04x:%04x' % (cs - emu.LOADSEG, ip), addr - lo, size, value))


m.mu.hook_add(UC_HOOK_MEM_WRITE, hw, begin=lo, end=lo + 0x1F)
print(m.run_poll(t1))
c = collections.Counter((ip, off) for t, ip, off, sz, v in log)
by = collections.defaultdict(list)
for t, ip, off, sz, v in log:
    by[ip].append(t)
for ip, ts in sorted(by.items(), key=lambda kv: len(kv[1])):
    offs = sorted(set(o for (i, o) in c if i == ip))
    print(ip, len(ts), 'offs', ['%02x' % o for o in offs], 'ticks', sorted(set(ts))[:12])
if out:
    with open(out, 'w') as f:
        for e in log:
            f.write('%d %s %02x %d %x\n' % e)
