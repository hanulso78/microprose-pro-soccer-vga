# 폴 없는 대기 루프 찾기: python tools/hang.py 대본 걸린틱   (SOCGAME)
#   걸린 틱 가까이부터 블록 수를 세어, 가장 자주 도는 블록과 스택의 복귀 주소를 보인다
import sys, os, collections
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import emu, cover, scan
from unicorn import UC_HOOK_BLOCK
from unicorn.x86_const import *
m = emu.Machine(keys=cover.load_script(sys.argv[1]))
T = int(sys.argv[2])
c = collections.Counter()
rets = collections.Counter()
n = [0]


def hb(mu, a, s, u):
    if m.ticks < T:
        return
    cs = mu.reg_read(UC_X86_REG_CS)
    c[(cs - 0x1000, a - cs * 16)] += 1
    n[0] += 1
    if n[0] % 997 == 0:
        ss, sp = mu.reg_read(UC_X86_REG_SS), mu.reg_read(UC_X86_REG_SP)
        st = mu.mem_read(ss * 16 + sp, 16)
        for k in range(0, 16, 2):
            v = st[k] | st[k + 1] << 8
            rets[v] += 1
    if n[0] > 3000000:
        mu.emu_stop()


m.mu.hook_add(UC_HOOK_BLOCK, hb)
print(m.run_poll(T + 50000))
print('hot blocks:', ' '.join('%04x:%04x/%d' % (k[0], k[1], v) for k, v in c.most_common(24)))
print('stack words:', ' '.join('%04x/%d' % (k, v) for k, v in rets.most_common(12)))
