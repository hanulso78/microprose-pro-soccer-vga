# 대기 루프 찾기: 뒤로 가는 조건 분기 중 몸통이 메모리 읽기/비교뿐인 것 (쓰기, 호출, 포트 없음)
#   이런 루프는 인터럽트만이 풀 수 있다 -> 폴 지점 (타이머/자판 IRQ 를 여기서 넣는다)
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import scan, image
from capstone.x86 import *

# 루프 안에서 불러도 되는 함수 (키 상태를 읽기만 하는 짧은 함수): 바이트 무늬로 찾는다
#   난수(1bc7) 를 부르는 루프는 '다른 값이 나올 때까지' 되돌이라 폴이 아니다 (넣지 않는다)
PURE_PATTERNS = [
    bytes.fromhex('ba80008eda8a874400baab038edac3'),       # 키 상태 읽기: mov dx,80; mov ds,dx; mov al,[bx+44]; ...
]


def find_pure():
    res = set()
    for f in scan.funcs:
        for pat in PURE_PATTERNS:
            if bytes(scan.IMG[f:f + len(pat)]) == pat:
                res.add(f)
    return res


PURE = find_pure()
# 손으로 더하는 폴 지점 (tools/polls_<game>.txt: "SSSS:OOOO 머리SSSS:OOOO")
EXTRA = []
_pe = os.path.join(scan.HERE, 'polls_%s.txt' % image.GAME)
if os.path.exists(_pe):
    for ln in open(_pe, encoding='utf-8'):
        ln = ln.split(';')[0].split()
        if len(ln) >= 2:
            a = [int(x, 16) for x in ln[0].split(':')]
            h = [int(x, 16) for x in ln[1].split(':')]
            EXTRA.append((a[0] * 16 + a[1], h[0] * 16 + h[1]))

JCC = {'je', 'jne', 'jl', 'jg', 'jge', 'jle', 'jb', 'jae', 'jns', 'js', 'ja', 'jbe', 'jmp'}
OKM = {'cmp', 'test', 'mov', 'or', 'and', 'nop', 'xor', 'jmp', 'je', 'jne', 'jb', 'jae', 'js', 'jns', 'ja', 'jbe', 'jl', 'jg', 'jge', 'jle'}


def find():
    res = []
    for a, i in sorted(scan.code.items()):
        if i.mnemonic not in JCC or i.operands[0].type != X86_OP_IMM:
            continue
        s = scan.iseg[a]
        t = s * 16 + ((i.operands[0].imm - s * 16) & 0xffff)
        if t > a or a - t > 40:
            continue
        # 몸통: t .. a (주소 차례로; 사이 명령이 모두 알려져 있어야)
        b = t
        ok = True
        reads_mem = False
        while b < a:
            j = scan.code.get(b)
            if j is None:
                ok = False
                break
            if j.mnemonic == 'call' and j.operands[0].type == X86_OP_IMM:
                tt = s * 16 + ((j.operands[0].imm - s * 16) & 0xffff)
                if tt in PURE:
                    reads_mem = True
                    b += j.size
                    continue
            if j.mnemonic not in OKM or j.mnemonic == 'jmp':
                ok = False
                break
            if j.mnemonic in JCC:
                tt = s * 16 + ((j.operands[0].imm - s * 16) & 0xffff)
                if t < tt <= a:          # 몸통 안으로 가는 가지: 단순 루프가 아님
                    ok = False
                    break
            for k, op in enumerate(j.operands):
                if op.type == X86_OP_MEM:
                    if k == 0 and j.mnemonic in ('mov', 'or', 'and', 'xor'):
                        ok = False
                    reads_mem = True
            if j.mnemonic == 'mov' and j.operands[0].type == X86_OP_REG and j.reg_name(j.operands[0].reg) in ('sp', 'ss'):
                ok = False
            b += j.size
        if ok and b == a and reads_mem:
            res.append((a, t))
    return res


# ---- 규칙 2: 인터럽트(타이머/자판 처리기)가 쓰는 변수로 탈출을 판정하는 되돌이 ----
ISR_ENTRIES = [image.GSEG_SYS * 16 + 0x027E, image.GSEG_SYS * 16 + 0x01D2]
ISR_CODE = set()


def isr_writes():
    # 처리기에서 닿는 코드의 고정 주소 메모리 쓰기 (세그먼트는 함수의 DS 로 어림: 03ab 코드는 03ab, 101a 는 0080)
    seen = ISR_CODE
    work = list(ISR_ENTRIES)
    W = set()
    while work:
        a = work.pop()
        if a in seen or a not in scan.code:
            continue
        seen.add(a)
        i = scan.code[a]
        seg = scan.iseg[a]
        ds = 0x03AB if seg == image.GSEG_CODE else 0x0080
        if i.operands and i.operands[0].type == X86_OP_MEM and i.mnemonic not in ('cmp', 'test', 'push', 'call', 'lcall', 'jmp', 'ljmp'):
            mm = i.operands[0].mem
            if not mm.base and not mm.index and not mm.segment:
                W.add((ds, mm.disp & 0xffff))
                W.add((ds, (mm.disp + 1) & 0xffff))
        m = i.mnemonic
        nxt = a + i.size
        if m in ('ret', 'retf', 'iret'):
            continue
        if m == 'call' and i.operands[0].type == X86_OP_IMM:
            work.append(seg * 16 + ((i.operands[0].imm - seg * 16) & 0xffff))
        elif m == 'lcall' and i.operands[0].type == X86_OP_IMM:
            work.append(scan.w16(a + 3) * 16 + scan.w16(a + 1))
        elif m == 'call':
            # call [0xd4] (타이머 되부름): 알려진 대상
            work.append(image.GSEG_SYS * 16 + 0x00D5)
        if m == 'jmp' and i.operands[0].type == X86_OP_IMM:
            work.append(seg * 16 + ((i.operands[0].imm - seg * 16) & 0xffff))
            continue
        if m in ('jmp', 'ljmp'):
            continue
        if m.startswith('j') or m.startswith('loop'):
            work.append(seg * 16 + ((i.operands[0].imm - seg * 16) & 0xffff))
        work.append(nxt)
    return W


ISRW = isr_writes()


def prev_insns(a, n):
    out = []
    b = a
    for _ in range(n):
        p = None
        for sz in range(1, 7):
            j = scan.code.get(b - sz)
            if j is not None and j.size == sz:
                p = j
                break
        if p is None:
            break
        out.append(p)
        b = p.address
    return out


def find2(have):
    res = []
    for a, i in sorted(scan.code.items()):
        if i.mnemonic not in JCC or i.mnemonic == 'jmp' or i.operands[0].type != X86_OP_IMM or a in have:
            continue
        s = scan.iseg[a]
        t = s * 16 + ((i.operands[0].imm - s * 16) & 0xffff)
        if t > a or a - t > 200:
            continue
        ds = 0x03AB if s == image.GSEG_CODE else 0x0080
        # 판정하는 명령: 바로 앞 명령이 메모리를 읽으며 플래그를 정하거나 (cmp/test/or/and/dec/inc),
        # 바로 앞이 레지스터 판정이면 그 앞의 mov reg, [mem]
        hit = False
        pv = prev_insns(a, 2)

        def isr_mem(j):
            for op in j.operands:
                if op.type == X86_OP_MEM and not op.mem.base and not op.mem.index and not op.mem.segment:
                    if (ds, op.mem.disp & 0xffff) in ISRW:
                        return True
            return False
        if pv and pv[0].mnemonic in ('cmp', 'test', 'or', 'and', 'dec', 'inc'):
            if any(op.type == X86_OP_MEM for op in pv[0].operands):
                hit = isr_mem(pv[0])
            elif len(pv) > 1 and pv[1].mnemonic == 'mov':
                hit = isr_mem(pv[1])
        if a in ISR_CODE:
            hit = False
        if hit:
            res.append((a, t))
    return res


_p1 = find()
POLLS = _p1 + find2(set(a for a, t in _p1)) + [e for e in EXTRA]
if __name__ == '__main__':
    print('ISR writes:', ' '.join('%04x:%04x' % w for w in sorted(ISRW)))
    for a, t in POLLS:
        s = scan.iseg[a]
        print('%04x:%04x -> %04x  %s' % (s, a - s * 16, t - s * 16,
              ' ; '.join('%s %s' % (scan.code[x].mnemonic, scan.code[x].op_str) for x in sorted(scan.code) if t <= x <= a and scan.iseg[x] == s)))
