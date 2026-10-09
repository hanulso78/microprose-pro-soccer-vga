# 실행 경로 모으기: 에뮬레이터를 키 대본대로 돌리며 기본 블록 시작점(LOADSEG 기준 선형, 세그먼트)을 모은다
#   python tools/cover.py 대본.txt 틱수 [결과.txt]
#   대본: "틱 스캔코드" 줄 (스캔코드 16진, 떼기는 80 더한 값) 또는 "틱 +키이름" (누르고 8틱 뒤 뗌)
#   결과: tools/_cover_<game>.txt 에 "SSSS:OOOO" 줄을 더한다 (합집합)
#   덤: 코드로 실행된 바이트에 쓴 적이 있으면 (자기 수정 코드) 알린다
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import emu, image
from unicorn import UC_HOOK_BLOCK, UC_HOOK_MEM_WRITE
from unicorn.x86_const import *

KEYS = {'enter': 0x1C, 'up': 0x48, 'down': 0x50, 'left': 0x4B, 'right': 0x4D, 'space': 0x39, 'esc': 0x01,
        'f1': 0x3B, 'p': 0x19, 'y': 0x15, 'n': 0x31, '0': 0x0B, '1': 0x02, '2': 0x03}


def load_script(fn):
    keys = []
    for ln in open(fn, encoding='utf-8'):
        ln = ln.split('#')[0].split()
        if len(ln) < 2:
            continue
        t = int(ln[0])
        k = ln[1]
        if k.startswith('+'):
            hold = int(ln[2]) if len(ln) > 2 else 8
            sc = KEYS[k[1:]]
            keys.append((t, sc))
            keys.append((t + hold, sc | 0x80))
        else:
            keys.append((t, int(k, 16)))
    keys.sort(key=lambda x: x[0])
    return keys


def main():
    script, nt = sys.argv[1], int(sys.argv[2])
    out = sys.argv[3] if len(sys.argv) > 3 else os.path.join(image.HERE, '_cover_%s.txt' % image.GAME)
    m = emu.Machine(keys=load_script(script))
    blocks = set()
    L = emu.LOADSEG * 16

    def hb(mu, addr, size, ud):
        cs = mu.reg_read(UC_X86_REG_CS)
        blocks.add((cs - emu.LOADSEG, addr - cs * 16, size))
    m.mu.hook_add(UC_HOOK_BLOCK, hb)
    written = set()
    lo = L + image.GSEG_CODE * 16
    hi = L + image.CEND

    def hw(mu, acc, addr, size, value, ud):
        for k in range(size):
            written.add(addr + k - L)
    m.mu.hook_add(UC_HOOK_MEM_WRITE, hw, None, lo, hi)
    res = m.run_ticks(nt, int(os.environ.get('SHOT', '0')))
    print(res, 'blocks', len(blocks))
    old = set()
    if os.path.exists(out):
        old = set(open(out).read().split())
    new = set('%04x:%04x' % (s, o) for s, o, z in blocks if s >= 0)
    open(out, 'w').write('\n'.join(sorted(old | new)) + '\n')
    print('cover: %d old, %d now, %d total' % (len(old), len(new), len(old | new)))
    smc = []
    for s, o, z in blocks:
        a = s * 16 + o
        for k in range(z):
            if a + k in written:
                smc.append('%04x:%04x' % (s, o + k))
    if smc:
        smc = [x for x in set(smc) if not (x.startswith('101a:0d') or x.startswith('101a:0de'))]
        print('SELF-MODIFIED CODE bytes:', sorted(smc)[:60])


if __name__ == '__main__':
    main()
