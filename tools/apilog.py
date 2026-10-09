# 드라이버 API 부름 기록: python tools/apilog.py 대본 시작틱 끝틱
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import emu, image, cover
from unicorn import UC_HOOK_CODE
from unicorn.x86_const import *
script, t0, t1 = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
m = emu.Machine(keys=cover.load_script(script))
L = emu.LOADSEG * 16
seen = {}
def hk(mu, addr, size, n):
    if m.ticks < t0:
        return
    r = mu.reg_read
    ss, sp = r(UC_X86_REG_SS), r(UC_X86_REG_SP)
    ret = mu.mem_read(ss * 16 + sp, 4)
    ro, rs = ret[0] | ret[1] << 8, ret[2] | ret[3] << 8
    print('t%d api%-2d AX=%04X BX=%04X CX=%04X DX=%04X SI=%04X DI=%04X BP=%04X DS=%04X ES=%04X  from %04X:%04X' % (
        m.ticks, n, r(UC_X86_REG_AX), r(UC_X86_REG_BX), r(UC_X86_REG_CX), r(UC_X86_REG_DX), r(UC_X86_REG_SI),
        r(UC_X86_REG_DI), r(UC_X86_REG_BP), r(UC_X86_REG_DS), r(UC_X86_REG_ES), rs - 0x1000, ro))
done = set()
for n, (s, o) in enumerate(image.DRV_API):
    a = s * 16 + o
    if a in done:
        continue
    done.add(a)
    m.mu.hook_add(UC_HOOK_CODE, hk, n, L + a, L + a)
print(m.run_poll(t1))
