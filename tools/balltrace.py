# 공 찾기: 대본을 돌리며 틱마다 스프라이트 그리기(드라이버 API 9: BP 프레임, SI x, DI y)와 게임 자료(DS 0080) 를 모은다
#   python tools/balltrace.py 대본.txt 시작틱 끝틱 결과.pkl
import sys, os, pickle
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import emu, image, cover
from unicorn import UC_HOOK_CODE
from unicorn.x86_const import UC_X86_REG_BP, UC_X86_REG_SI, UC_X86_REG_DI

script, t0, t1, out = sys.argv[1], int(sys.argv[2]), int(sys.argv[3]), sys.argv[4]
m = emu.Machine(keys=cover.load_script(script))
SPR = (emu.LOADSEG << 4) + 0x12090 + 0x2803
draws = []


def hook(mu, addr, size, ud):
    r = mu.reg_read
    draws.append((m.ticks, r(UC_X86_REG_BP), r(UC_X86_REG_SI), r(UC_X86_REG_DI)))


m.mu.hook_add(UC_HOOK_CODE, hook, begin=SPR, end=SPR)
DS = (emu.LOADSEG + 0x80) * 16
snaps = {}
orig = m.on_poll


def on_poll(mu, addr, size, ud):
    if t0 <= m.ticks < t1 and m.ticks not in snaps:
        snaps[m.ticks] = bytes(mu.mem_read(DS, 0x10000))
    return orig(mu, addr, size, ud)


m.on_poll = on_poll
print(m.run_poll(t1))
pickle.dump((snaps, [d for d in draws if d[0] >= t0]), open(out, 'wb'))
print(len(snaps), 'ticks')
