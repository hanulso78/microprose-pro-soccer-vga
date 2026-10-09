# 실외 재개(공 놓기) 루틴 03ab:25ad 가 불릴 때 틱, 재개 종류 [253c], 공 자리를 적는다
#   SOCGAME=out python tools/restartlog.py 대본.txt 끝틱 [주소16진=25ad] [종류주소16진=253c]
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import emu, image, cover
from unicorn import UC_HOOK_CODE

script, t1 = sys.argv[1], int(sys.argv[2])
at = int(sys.argv[3], 16) if len(sys.argv) > 3 else 0x25ad
ty = int(sys.argv[4], 16) if len(sys.argv) > 4 else 0x253c
m = emu.Machine(keys=cover.load_script(script))
DS = (emu.LOADSEG + 0x3AB) * 16


def h(mu, a, sz, ud):
    b = bytes(mu.mem_read(DS + ty, 4))
    print('restart', m.ticks, 'type', b[0], 'pos', b[2], b[3])


m.mu.hook_add(UC_HOOK_CODE, h, begin=DS + at, end=DS + at)
print(m.run_poll(t1))
