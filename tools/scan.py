# 코드 훑기: 함수 시작점, 명령, switch 점프표를 모은다 (게임 + 드라이버 합친 그림, image.py)
#   code[선형주소] = capstone 명령 (주소 = 세그먼트*16+오프셋, LOADSEG 기준)
#   funcs[함수 선형주소] = 그 함수의 CS (LOADSEG 기준 세그먼트 값)
import struct, os, sys
from capstone import Cs, CS_ARCH_X86, CS_MODE_16
from capstone.x86 import *

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import image
from image import IMG, RELOC, ROOT, w16, GAME

md = Cs(CS_ARCH_X86, CS_MODE_16)
md.detail = True

# 코드 구역 (선형, LOADSEG 기준): 이 밖으로 가는 호출은 문제로 적는다
DS = image.GSEG_DATA
CODE_RANGES = [(image.GSEG_CODE * 16, image.GSEG_SYS * 16 + 0x2000),
               (image.DRVREL * 16, image.DRVREL * 16 + len(image.DIMG))]


def in_code(a):
    return any(s <= a < e for s, e in CODE_RANGES)


def dis1(a):
    for i in md.disasm(bytes(IMG[a:a + 16]), a):
        return i
    return None


code = {}
iseg = {}
# 부른 뒤에 인자 바이트가 붙는 함수 (선형 -> 바이트 수): 드라이버 5 번 (글자 찍기, far 포인터 4 바이트)
INLINE = {image.GSEG_SYS * 16 + 0x0D40 + 5 * 5: 4}
RETSITE = {}                # call 주소 -> 돌아오는 곳 (인자 건너뛴)
funcs = {}
jtabs = {}                  # 간접 jmp 주소 -> [대상 선형 ...]
ncalls = {}                 # 간접 near call 주소 -> [대상 선형 ...]
problems = []
pending = []

# 손으로 알려 주는 것들 (tools/roots_<game>.txt): 함수 시작, 간접 점프/호출 대상
#   func SSSS:OOOO           함수 시작점
#   jtab SSSS:OOOO n TAB     SSSS:OOOO 의 jmp [reg+TAB] (DS 표, n 개)
#   jlist SSSS:OOOO T1 T2..  간접 jmp 대상 (같은 세그먼트 오프셋)
#   clist SSSS:OOOO T1 T2..  간접 near call 대상
MANUAL_J = {}
MANUAL_C = {}
ROOTS = []


def parse_roots():
    for fn in ('roots.txt', 'roots_%s.txt' % GAME):
        p = os.path.join(HERE, fn)
        if not os.path.exists(p):
            continue
        for ln in open(p, encoding='utf-8'):
            ln = ln.split(';')[0].split()
            if not ln:
                continue
            s, o = [int(x, 16) for x in ln[1].split(':')]
            a = s * 16 + o
            if ln[0] == 'func':
                ROOTS.append((s, o))
            elif ln[0] == 'jlist':
                MANUAL_J[a] = [s * 16 + int(x, 16) for x in ln[2:]]
            elif ln[0] == 'clist':
                MANUAL_C[a] = [s * 16 + int(x, 16) for x in ln[2:]]
            elif ln[0] == 'jtab':
                n = int(ln[2], 0)
                tab = int(ln[3], 16)
                tseg = int(ln[4], 16) if len(ln) > 4 else DS
                MANUAL_J[a] = [s * 16 + w16(tseg * 16 + tab + 2 * k) for k in range(n)]
            elif ln[0] == 'ctab':
                n = int(ln[2], 0)
                tab = int(ln[3], 16)
                tseg = int(ln[4], 16) if len(ln) > 4 else DS
                MANUAL_C[a] = [s * 16 + w16(tseg * 16 + tab + 2 * k) for k in range(n)]


parse_roots()


def add_func(seg, off, why=''):
    a = seg * 16 + off
    if not in_code(a):
        problems.append('func outside code %04x:%04x %s' % (seg, off, why))
        return
    if a not in funcs:
        funcs[a] = seg
        pending.append((a, seg))


def walk(start, seg):
    work = [start]
    while work:
        a = work.pop()
        while True:
            if a in code:
                if iseg[a] != seg:
                    problems.append('code at %05x seen with two segs %04x %04x' % (a, iseg[a], seg))
                break
            i = dis1(a)
            if i is None:
                problems.append('bad insn at %04x:%04x' % (seg, a - seg * 16))
                break
            code[a] = i
            iseg[a] = seg
            m = i.mnemonic
            nxt = a + i.size
            off = a - seg * 16
            if m == 'lcall' and i.operands[0].type == X86_OP_IMM:
                o = w16(a + 1)
                s = w16(a + 3)
                if (a + 3) in RELOC:
                    add_func(s, o, 'lcall at %04x:%04x' % (seg, off))
                else:
                    problems.append('lcall without reloc at %04x:%04x' % (seg, off))
                k = INLINE.get(s * 16 + o, 0)
                if k:
                    RETSITE[a] = nxt + k
                    nxt += k
            elif m == 'call' and i.operands[0].type == X86_OP_IMM:
                t = (i.operands[0].imm - seg * 16) & 0xffff
                add_func(seg, t, 'near call at %04x:%04x' % (seg, off))
                k = INLINE.get(seg * 16 + t, 0)
                if k:
                    RETSITE[a] = nxt + k
                    nxt += k
            elif m == 'call':
                if a in MANUAL_C:
                    for t in MANUAL_C[a]:
                        add_func(seg, t - seg * 16, 'ncall list')
                    ncalls[a] = MANUAL_C[a]
                else:
                    IND_SITES.append(a)
            elif m == 'lcall':
                IND_SITES.append(a)
            if m in ('ret', 'retf', 'iret', 'hlt'):
                break
            if m == 'jmp' or m == 'ljmp':
                op = i.operands[0]
                if m == 'jmp' and op.type == X86_OP_IMM:
                    a = seg * 16 + ((op.imm - seg * 16) & 0xffff)
                    continue
                if m == 'ljmp' and op.type == X86_OP_IMM:
                    if (a + 3) in RELOC:
                        add_func(w16(a + 3), w16(a + 1), 'ljmp at %04x:%04x' % (seg, off))
                    else:
                        problems.append('ljmp without reloc at %04x:%04x' % (seg, off))
                    break
                if a in MANUAL_J:
                    jtabs[a] = MANUAL_J[a]
                    work.extend(MANUAL_J[a])
                    break
                IND_SITES.append(a)
                break
            if m.startswith('j') or m.startswith('loop') or m == 'jcxz':
                work.append(seg * 16 + ((i.operands[0].imm - seg * 16) & 0xffff))
            a = nxt


# 진입점
add_func(image.GSEG_SYS, image.GH[10], 'entry')
for s, o in ROOTS:
    add_func(s, o, 'roots')
# 에뮬레이터로 실제 실행된 블록 시작점 (tools/cover.py): 간접 분기 대상 (레이블로만 쓴다)
LABEL_ROOTS = set()
_cv = os.path.join(HERE, '_cover_%s.txt' % GAME)
if os.path.exists(_cv):
    for ln in open(_cv).read().split():
        s_, o_ = [int(x, 16) for x in ln.split(':')]
        a_ = s_ * 16 + o_
        LABEL_ROOTS.add(a_)
        if a_ not in code and in_code(a_):
            pending.append((a_, s_))
IND_SITES = []          # 대상 목록을 모르는 간접 분기 (전체 dispatch 로)
# 드라이버 API 32 개 (점프표로 들어가지만 겹치는 것도 있으니 모두)
for s, o in image.DRV_API:
    add_func(s, o, 'drv api')

while pending:
    a, seg = pending.pop()
    walk(a, seg)

# 명령끼리 겹치는 곳 (자료를 코드로 읽었거나 정렬이 다른 두 흐름)
OVERLAPS = []
_prev = None
for _a in sorted(code):
    if _prev is not None and _prev + code[_prev].size > _a:
        OVERLAPS.append((_prev, _a))
    _prev = _a

if __name__ == '__main__':
    print('funcs', len(funcs), 'insns', len(code), 'jtabs', len(jtabs), 'indirect', len(IND_SITES))
    for x, y in OVERLAPS:
        print('overlap %04x:%04x / %04x:%04x' % (iseg[x], x - iseg[x] * 16, iseg[y], y - iseg[y] * 16))
    seen = set()
    for p in problems:
        if p not in seen:
            print(p)
            seen.add(p)
