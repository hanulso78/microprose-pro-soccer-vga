# 공 구조만 틱마다 기록 (가볍게): SOCGAME=in|out python tools/balllog.py 대본.txt 끝틱 BASE16진 결과.txt
#   줄: 틱 x y 바닥y 상태(+0x19) 그리고 곡 올리기(101a:02f0/0f61:02f0) 가 있으면 "song N"
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import emu, image, cover
from unicorn import UC_HOOK_CODE
from unicorn.x86_const import UC_X86_REG_AX, UC_X86_REG_SI

script, t1, base, out = sys.argv[1], int(sys.argv[2]), int(sys.argv[3], 16), sys.argv[4]
m = emu.Machine(keys=cover.load_script(script))
A = (emu.LOADSEG + 0x3AB) * 16 + base
f = open(out, 'w')
orig = m.on_poll
last = [-1]


def w(a):
    b = bytes(m.mu.mem_read(a, 2))
    return b[0] | b[1] << 8


def on_poll(mu, addr, size, ud):
    if m.ticks != last[0]:
        last[0] = m.ticks
        st = bytes(mu.mem_read(A + 0x19, 1))[0]
        f.write('%d %d %d %d %d\n' % (m.ticks, w(A + 4), w(A + 9), w(A + 0x17), st))
    return orig(mu, addr, size, ud)


SND = (emu.LOADSEG << 4) + (image.GSEG_SYS * 16 + 0x02F0)


def hs(mu, a, sz, ud):
    if mu.reg_read(UC_X86_REG_AX) == 0:
        f.write('song %d %d\n' % (m.ticks, mu.reg_read(UC_X86_REG_SI)))


m.mu.hook_add(UC_HOOK_CODE, hs, begin=SND, end=SND)
m.on_poll = on_poll
print(m.run_poll(t1))
f.close()
