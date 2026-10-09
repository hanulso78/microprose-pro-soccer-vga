# -*- coding: utf-8 -*-
"""MicroProse Soccer (게임 본체 + EGAIO 드라이버) 코드를 C 로 옮긴다 (기계적 변환, 명령 하나씩 원본과 같게)

   SOCGAME=in  python tools/asm2c.py   -> soc_in.c   (실내 6인제, OPITCH.BIN)
   SOCGAME=out python tools/asm2c.py   -> soc_out.c  (실외 11인제, IPITCHC.BIN)

   - 원본은 손 어셈블리다.  코드와 자료가 한 세그먼트에 섞여 있고, 화면 흐름은 바이트 대본으로
     돌며(0x90 으로 시작하는 코드로 간접 점프), 복귀 주소를 꺼내 두었다가 나중에 jmp 로 돌아가는
     코루틴 모양도 있고, mov sp,[x] 로 스택을 통째로 되돌리기도 한다.
     그래서 프로그램 전체를 함수 하나(soc_run_xx)로 옮긴다:
       call/lcall -> 복귀 주소(와 CS)를 원본처럼 스택(M[])에 넣고 goto
       ret/retf/iret, 간접 jmp/call -> 주소를 계산해 dispatch switch 로 goto
     => 스택 메모리까지 원본과 똑같다.
   - 레지스터는 전역 변수(cpu.h), 메모리는 1MB 평면 배열 M[] (실모드 선형 주소).
     A0000 쪽 읽기/쓰기는 EGA 평면 흉내(vga.c).
   - 플래그(C Z S O)는 쓰이는 것만 계산한다 (프로그램 전체 흐름에서 생존 분석).
     바로 뒤 조건 분기 하나만 쓰는 cmp/test 따위는 조건식으로 접는다.
   - 폴 지점 (tools/polls.py: 인터럽트만이 풀 수 있는 대기 루프의 뒤로 가는 분기):
     루프를 다시 돌 때 soc_poll() 이 틱을 하나 흘리고 IRQ(타이머 int 8 / 자판 int 9) 를 넣는다.
     에뮬레이터(tools/emu.py)도 같은 자리에서 같은 규칙으로 넣는다 -> 결정적, 대조 가능.
"""
import sys, os, re
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import scan, polls, image
from scan import code, iseg, funcs, RELOC, IMG
from capstone.x86 import *

GAME = image.GAME
ROOT = image.ROOT
PFX = GAME                      # 레이블/함수 이름 앞붙이
POLL = {a: t for a, t in polls.POLLS}

# 256색 개선판 갈고리 (tools/vhooks.txt + 드라이버 API 진입): 그 명령 앞에 VH(선형)
VHOOKS = set((s * 16 + o) for s, o in image.DRV_API)
for _fn in ('vhooks.txt', 'vhooks_%s.txt' % GAME):
    if not os.path.exists(os.path.join(scan.HERE, _fn)):
        continue
    for ln in open(os.path.join(scan.HERE, _fn), encoding='utf-8'):
        ln = ln.split(';')[0].split()
        if ln:
            _s, _o = [int(x, 16) for x in ln[0].split(':')]
            VHOOKS.add(_s * 16 + _o)

# 빠른 길 (socfast.c): 바이트 무늬로 덩어리를 찾아 첫 명령에서 fast_xxx(다음 주소) 를 부른다
_PL = 'a403fd' * 7 + 'a4'
FAST_PATTERNS = [
    ('fast_tile', bytes.fromhex('8b3783c302b001ee' + (_PL + '81ef1901d0e0ee') * 3 + _PL + '81ef1801'), 0),
    ('fast_spr3', bytes.fromhex(('268a05a4' * 3 + '03f9') * 20 + '268a05a4' * 3 + '81ef2303'), 0),
]
FAST = {}
for _a in sorted(code):
    for _fn, _pat, _adj in FAST_PATTERNS:
        if bytes(IMG[_a:_a + len(_pat)]) == _pat:
            FAST[_a] = (_fn, _a + len(_pat) + _adj)
# 스크롤 래치 복사: 1209:082c jmp bx -> 1209:085c
_sc = image.DRVREL * 16 + 0x90 + 0x082c
if _sc in code and bytes(IMG[_sc:_sc + 2]) == bytes.fromhex('ffe3'):
    FAST[_sc] = ('fast_scroll', image.DRVREL * 16 + 0x90 + 0x085c)

names = {}
NAMES_TXT = os.path.join(scan.HERE, 'names.txt')
if os.path.exists(NAMES_TXT):
    for ln in open(NAMES_TXT, encoding='utf-8'):
        ln, _, note = ln.partition(';')
        p = ln.split()
        if len(p) >= 2:
            s, o = p[0].split(':')
            names[int(s, 16) * 16 + int(o, 16)] = p[1]

R16 = {'ax': 'AX', 'bx': 'BX', 'cx': 'CX', 'dx': 'DX', 'si': 'SI', 'di': 'DI', 'bp': 'BP', 'sp': 'SP',
       'cs': 'CS_', 'ds': 'DS_', 'es': 'ES_', 'ss': 'SS_'}
R8 = {'al': 'AL', 'ah': 'AH', 'bl': 'BL', 'bh': 'BH', 'cl': 'CL', 'ch': 'CH', 'dl': 'DL', 'dh': 'DH'}
JCC = {'je', 'jne', 'jl', 'jg', 'jge', 'jle', 'jb', 'jae', 'jns', 'js', 'ja', 'jbe'}
JCC_USES = {'je': 'Z', 'jne': 'Z', 'jl': 'SO', 'jge': 'SO', 'jg': 'ZSO', 'jle': 'ZSO', 'jb': 'C', 'jae': 'C',
            'jns': 'S', 'js': 'S', 'ja': 'CZ', 'jbe': 'CZ'}
ALLF = frozenset('CZSO')


def tgt(i):
    s = iseg[i.address]
    return s * 16 + ((i.operands[0].imm - s * 16) & 0xffff)


def far_tgt(a):
    return scan.w16(a + 3) * 16 + scan.w16(a + 1)


def next_of(a):
    """call 다음 (인라인 인자 건너뛴) 복귀 자리"""
    return scan.RETSITE.get(a, a + code[a].size)


# ---- 복귀 자리, dispatch 대상 ----
RETS = set()
for a, i in code.items():
    if i.mnemonic in ('call', 'lcall'):
        r = next_of(a)
        if r in code:
            RETS.add(r)
DISPATCH = set(RETS) | set(funcs) | set(x for x in scan.LABEL_ROOTS if x in code) | set(POLL.values())
for _t in list(scan.jtabs.values()) + list(scan.ncalls.values()):
    DISPATCH |= set(_t)
DISPATCH |= set(v[1] for v in FAST.values() if v[1] in code)
DISPATCH = set(x for x in DISPATCH if x in code)

# ---- 흐름 ----
RETP = 'RET'
DISP = 'DISP'


def succs(a):
    i = code[a]
    m = i.mnemonic
    op = i.operands
    nxt = a + i.size
    if m in ('ret', 'retf', 'iret'):
        return [RETP]
    if m == 'hlt' or (m == 'int' and op[0].imm == 0x20):
        return []
    if m == 'jmp':
        return [tgt(i)] if op[0].type == X86_OP_IMM else [DISP]
    if m == 'ljmp':
        return [far_tgt(a)] if op[0].type == X86_OP_IMM else [DISP]
    if m == 'call':
        return [tgt(i)] if op[0].type == X86_OP_IMM else [DISP]
    if m == 'lcall':
        return [far_tgt(a)] if op[0].type == X86_OP_IMM else [DISP]
    if m in JCC or m.startswith('loop') or m == 'jcxz':
        s = [nxt, tgt(i)]
        if a in POLL:
            s.append(DISP)
        return s
    return [nxt]


def flag_du(i):
    m = i.mnemonic
    if m in ('add', 'sub', 'cmp', 'neg', 'and', 'or', 'xor', 'test'):
        return ALLF, frozenset()
    if m in ('adc', 'sbb'):
        return ALLF, frozenset('C')
    if m in ('inc', 'dec'):
        return frozenset('ZSO'), frozenset()
    if m in ('shl', 'shr', 'sar'):
        if i.operands[1].type == X86_OP_REG:
            return frozenset(), frozenset()      # cl 번: 0 이면 그대로 (보수적으로 정의 안 함)
        return ALLF, frozenset()
    if m in ('rcl', 'rcr'):
        return frozenset('CO'), frozenset('C')
    if m in ('rol', 'ror'):
        if i.operands[1].type == X86_OP_REG:
            return frozenset(), frozenset()
        return frozenset('CO'), frozenset()
    if m == 'pushf':
        return frozenset(), ALLF
    if m in ('popf', 'iret'):
        return ALLF, frozenset()
    if m in ('mul', 'imul'):
        return frozenset('CO'), frozenset()
    if m in ('stc', 'clc'):
        return frozenset('C'), frozenset()
    if m == 'cmc':
        return frozenset('C'), frozenset('C')
    if m == 'int':
        return (frozenset('C') if i.operands[0].imm == 0x21 else frozenset()), frozenset()
    if m in JCC:
        return frozenset(), frozenset(JCC_USES[m])
    return frozenset(), frozenset()


def liveness():
    addrs = sorted(code)
    S = {a: succs(a) for a in addrs}
    DU = {a: flag_du(code[a]) for a in addrs}
    lin = {a: frozenset() for a in addrs}
    lout = {a: frozenset() for a in addrs}
    ret_live = frozenset()
    disp_live = frozenset()
    changed = True
    it = 0
    while changed:
        changed = False
        it += 1
        for a in reversed(addrs):
            out = set()
            for s in S[a]:
                if s == RETP:
                    out |= ret_live
                elif s == DISP:
                    out |= disp_live
                elif s in lin:
                    out |= lin[s]
            d, u = DU[a]
            inn = frozenset((out - d) | u)
            out = frozenset(out)
            if out != lout[a] or inn != lin[a]:
                lout[a] = out
                lin[a] = inn
                changed = True
        r = frozenset().union(*[lin[x] for x in RETS]) if RETS else frozenset()
        r |= frozenset().union(*[lin[x] for x in POLL.values()]) if POLL else frozenset()
        d = frozenset().union(*[lin[x] for x in DISPATCH])
        if r != ret_live or d != disp_live:
            ret_live, disp_live = r, d
            changed = True
    return lin, lout, it


# ---- 피연산자 ----
def has_reloc_at(a, k):
    return (a + k) in RELOC


def imm_text(i, v, size):
    # 즉치값은 명령 끝에 있다: 그 자리가 재배치되면 세그먼트
    if (i.address + i.size - 2) in RELOC and size == 2:
        return 'SEG(0x%x)' % (v & 0xffff)
    if size == 1:
        return '0x%x' % (v & 0xff)
    return '0x%x' % (v & 0xffff)


def mem_addr(i, op):
    mm = op.mem
    parts = []
    base = i.reg_name(mm.base) if mm.base else None
    index = i.reg_name(mm.index) if mm.index else None
    if base:
        parts.append(R16[base])
    if index:
        parts.append(R16[index])
    if mm.disp or not parts:
        parts.append('0x%x' % (mm.disp & 0xffff))
    off = ' + '.join(parts)
    if len(parts) > 1:
        off = '(uint16_t)(%s)' % off
    if mm.segment:
        seg = R16[i.reg_name(mm.segment)]
    elif base == 'bp':
        seg = 'SS_'
    else:
        seg = 'DS_'
    return seg, off


def rd(i, op, size=None):
    if op.type == X86_OP_REG:
        r = i.reg_name(op.reg)
        return R16.get(r) or R8[r]
    if op.type == X86_OP_IMM:
        return imm_text(i, op.imm, size or op.size)
    seg, off = mem_addr(i, op)
    return '%s(%s, %s)' % ('RB' if op.size == 1 else 'RW', seg, off)


def wr(i, op, val):
    if op.type == X86_OP_REG:
        r = i.reg_name(op.reg)
        return '%s = %s;' % (R16.get(r) or R8[r], val)
    seg, off = mem_addr(i, op)
    return '%s(%s, %s, %s);' % ('WB' if op.size == 1 else 'WW', seg, off, val)


def cast(sz):
    return 'uint8_t' if sz == 1 else 'uint16_t'


def scast(sz):
    return 'int8_t' if sz == 1 else 'int16_t'


def signbit(sz):
    return 7 if sz == 1 else 15


def lab(a):
    return 'L%05x' % a


class Gen:
    def __init__(self, lin, lout, labels):
        self.li, self.lo = lin, lout
        self.labels = labels
        self.fold = {}
        self.out = []

    def emit(self, s):
        self.out.append(s)

    def flags_code(self, live, kind, sz, A, B, R):
        sb = signbit(sz)
        mask = '0xff' if sz == 1 else '0xffff'
        c = []
        if 'Z' in live:
            c.append('ZF = ((%s & %s) == 0);' % (R, mask))
        if 'S' in live:
            c.append('SF = ((%s >> %d) & 1);' % (R, sb))
        if 'C' in live:
            if kind in ('add', 'adc'):
                c.append('CF = (%s > %s);' % (R, mask))
            elif kind in ('sub', 'cmp', 'sbb'):
                c.append('CF = ((%s >> %d) & 1);' % (R, sb + 1))
            elif kind in ('and', 'or', 'xor', 'test'):
                c.append('CF = 0;')
            elif kind == 'neg':
                c.append('CF = (%s != 0);' % A)
        if 'O' in live:
            if kind in ('add', 'adc', 'inc'):
                c.append('OF = (((%s ^ %s) & (%s ^ %s)) >> %d) & 1;' % (A, R, B, R, sb))
            elif kind in ('sub', 'cmp', 'dec', 'sbb'):
                c.append('OF = (((%s ^ %s) & (%s ^ %s)) >> %d) & 1;' % (A, B, A, R, sb))
            elif kind in ('and', 'or', 'xor', 'test'):
                c.append('OF = 0;')
            elif kind == 'neg':
                c.append('OF = (%s == %s);' % (A, '0x80' if sz == 1 else '0x8000'))
        return c

    def cond_expr(self, jcc, kind, sz, A, B, R):
        st = scast(sz)
        ut = cast(sz)
        if kind == 'cmp':
            return {'je': '%s == %s' % (A, B), 'jne': '%s != %s' % (A, B),
                    'jl': '(%s)%s < (%s)%s' % (st, A, st, B), 'jge': '(%s)%s >= (%s)%s' % (st, A, st, B),
                    'jg': '(%s)%s > (%s)%s' % (st, A, st, B), 'jle': '(%s)%s <= (%s)%s' % (st, A, st, B),
                    'jb': '%s < %s' % (A, B), 'jae': '%s >= %s' % (A, B),
                    'ja': '%s > %s' % (A, B), 'jbe': '%s <= %s' % (A, B),
                    'js': '(%s)(%s - %s) < 0' % (st, A, B), 'jns': '(%s)(%s - %s) >= 0' % (st, A, B)}.get(jcc)
        if kind in ('test', 'and', 'or', 'xor'):
            v = R
            return {'je': '(%s)%s == 0' % (ut, v), 'jne': '(%s)%s != 0' % (ut, v),
                    'js': '(%s)%s < 0' % (st, v), 'jns': '(%s)%s >= 0' % (st, v),
                    'jl': '(%s)%s < 0' % (st, v), 'jge': '(%s)%s >= 0' % (st, v),
                    'jg': '(%s)%s > 0' % (st, v), 'jle': '(%s)%s <= 0' % (st, v),
                    'jb': '0', 'jae': '1', 'ja': '(%s)%s != 0' % (ut, v), 'jbe': '(%s)%s == 0' % (ut, v)}.get(jcc)
        if kind in ('inc', 'dec', 'add', 'sub', 'shl', 'shr', 'neg'):
            if jcc in ('je', 'jne', 'js', 'jns'):
                v = R
                return {'je': '(%s)%s == 0' % (ut, v), 'jne': '(%s)%s != 0' % (ut, v),
                        'js': '(%s)%s < 0' % (st, v), 'jns': '(%s)%s >= 0' % (st, v)}[jcc]
        return None

    def can_fold(self, a, i, defs):
        nxt = a + i.size
        j = code.get(nxt)
        ok = (j is not None and j.mnemonic in JCC and not (self.lo[nxt] & defs) and nxt not in self.labels)
        return j if ok else None

    def alu(self, a, i):
        m = i.mnemonic
        ops = i.operands
        dst = ops[0]
        sz = dst.size
        ct = cast(sz)
        defs = flag_du(i)[0]
        live = self.lo[a] & defs
        j = self.can_fold(a, i, defs)
        nxt = a + i.size
        A0 = rd(i, dst)
        if m in ('cmp', 'test'):
            B0 = rd(i, ops[1], sz)
            if j:
                ce = (self.cond_expr(j.mnemonic, 'cmp', sz, A0, B0, None) if m == 'cmp' else
                      self.cond_expr(j.mnemonic, 'test', sz, None, None, '(%s & %s)' % (A0, B0)))
                if ce:
                    self.fold[nxt] = ce
                    return
            if not live:
                return
            self.emit('{ %s a_ = %s, b_ = %s; unsigned r_ = %s;' % (
                ct, A0, B0, '(unsigned)a_ - b_' if m == 'cmp' else '(unsigned)(a_ & b_)'))
            for c in self.flags_code(live, m, sz, 'a_', 'b_', 'r_'):
                self.emit('  ' + c)
            self.emit('}')
            return
        if m in ('inc', 'dec', 'neg', 'not'):
            B0 = '1'
            if m == 'not':
                self.emit(wr(i, dst, '(%s)~%s' % (ct, A0)))
                return
            opx = {'inc': '(unsigned)a_ + 1', 'dec': '(unsigned)a_ - 1', 'neg': '0u - a_'}[m]
            if dst.type == X86_OP_REG:
                short = {'inc': '%s++;' % A0, 'dec': '%s--;' % A0, 'neg': '%s = (%s)(0u - %s);' % (A0, ct, A0)}[m]
            else:
                short = wr(i, dst, '(%s)(%s)' % (ct, {'inc': A0 + ' + 1', 'dec': A0 + ' - 1', 'neg': '0u - ' + A0}[m]))
        else:
            B0 = rd(i, ops[1], sz)
            opx = {'add': '(unsigned)a_ + b_', 'sub': '(unsigned)a_ - b_', 'adc': '(unsigned)a_ + b_ + CF',
                   'sbb': '(unsigned)a_ - b_ - CF',
                   'and': '(unsigned)(a_ & b_)', 'or': '(unsigned)(a_ | b_)', 'xor': '(unsigned)(a_ ^ b_)'}[m]
            same = (dst.type == X86_OP_REG and ops[1].type == X86_OP_REG and ops[0].reg == ops[1].reg)
            if m in ('xor', 'sub') and same:
                self.emit('%s = 0;' % A0)
                if live:
                    self.emit(' '.join(c for c in ['CF = 0;' if 'C' in live else '', 'ZF = 1;' if 'Z' in live else '',
                                                   'SF = 0;' if 'S' in live else '', 'OF = 0;' if 'O' in live else ''] if c))
                return
            if m == 'sbb' and same:
                self.emit('%s = CF ? 0x%s : 0;' % (A0, 'ff' if sz == 1 else 'ffff'))
                if live:
                    self.emit(' '.join(c for c in ['ZF = !CF;' if 'Z' in live else '', 'SF = CF;' if 'S' in live else '',
                                                   'OF = 0;' if 'O' in live else ''] if c))
                return
            sop = {'add': '+', 'sub': '-', 'and': '&', 'or': '|', 'xor': '^'}.get(m)
            if sop is None:
                short = None
            elif dst.type == X86_OP_REG:
                short = '%s %s= %s;' % (A0, sop, B0)
            else:
                short = wr(i, dst, '(%s)(%s %s %s)' % (ct, A0, sop, B0))
        if short and not live:
            self.emit(short)
            return
        if short and j and dst.type == X86_OP_REG and m != 'neg':
            ce = self.cond_expr(j.mnemonic, m, sz, None, None, A0)
            if ce:
                self.emit(short)
                self.fold[nxt] = ce
                return
        self.emit('{ %s a_ = %s, b_ = %s; unsigned r_ = %s;' % (ct, A0, B0, opx))
        self.emit('  ' + wr(i, dst, '(%s)r_' % ct))
        for c in self.flags_code(live, m, sz, 'a_', 'b_', 'r_'):
            self.emit('  ' + c)
        self.emit('}')

    def shift(self, a, i):
        m = i.mnemonic
        dst, cnt = i.operands
        sz = dst.size
        ct = cast(sz)
        A0 = rd(i, dst)
        live = self.lo[a] & ALLF
        n = '1' if (cnt.type == X86_OP_IMM and cnt.imm == 1) else rd(i, cnt)
        sb = signbit(sz)
        if m in ('rcl', 'rcr'):
            assert n == '1', '%05x' % a
            if m == 'rcl':
                self.emit('{ %s a_ = %s; unsigned c_ = CF; CF = (a_ >> %d) & 1; %s' % (
                    ct, A0, sb, wr(i, dst, '(%s)((a_ << 1) | c_)' % ct)))
                if 'O' in live:
                    self.emit('  OF = ((a_ >> %d) & 1) ^ CF;' % sb)
            else:
                self.emit('{ %s a_ = %s; unsigned c_ = CF; CF = a_ & 1; %s' % (
                    ct, A0, wr(i, dst, '(%s)((a_ >> 1) | (c_ << %d))' % (ct, sb))))
                if 'O' in live:
                    self.emit('  OF = ((a_ >> %d) & 1) ^ c_;' % sb)
            self.emit('}')
            return
        if m == 'sar':
            expr = '(%s)((%s)a_ >> n_)' % (ct, scast(sz))
        elif m == 'shl':
            expr = '(%s)((unsigned)a_ << n_)' % ct
        else:
            expr = '(%s)(a_ >> n_)' % ct
        if not live:
            if dst.type == X86_OP_REG and m != 'sar':
                self.emit('%s %s= %s;' % (A0, '<<' if m == 'shl' else '>>', n if n == '1' else '(%s & 0x1f)' % n))
            else:
                self.emit('{ %s a_ = %s; unsigned n_ = %s & 0x1f; %s }' % (ct, A0, n, wr(i, dst, expr)))
            return
        self.emit('{ %s a_ = %s; unsigned n_ = %s & 0x1f;' % (ct, A0, n))
        self.emit('  if (n_) { %s r_ = %s;' % (ct, expr))
        self.emit('    ' + wr(i, dst, 'r_'))
        if 'C' in live:
            if m == 'shl':
                self.emit('    CF = n_ <= %d ? (a_ >> (%d - n_)) & 1 : 0;' % (sb + 1, sb + 1))
            elif m == 'sar':
                self.emit('    CF = (((%s)a_ >> (n_ - 1)) & 1);' % scast(sz))
            else:
                self.emit('    CF = n_ <= %d ? (a_ >> (n_ - 1)) & 1 : 0;' % (sb + 1))
        if 'Z' in live:
            self.emit('    ZF = (r_ == 0);')
        if 'S' in live:
            self.emit('    SF = (r_ >> %d) & 1;' % sb)
        if 'O' in live:
            if m == 'shl':
                self.emit('    OF = ((r_ >> %d) & 1) ^ CF;' % sb)
            elif m == 'sar':
                self.emit('    OF = 0;')
            else:
                self.emit('    OF = (a_ >> %d) & 1;' % sb)
        self.emit('  }')
        self.emit('}')
        # 접을 수 있으면 (shl/shr 뒤 je/jne/js/jns): 결과로 판단 -- 여기서는 접지 않는다

    def rot(self, a, i):
        m = i.mnemonic
        dst, cnt = i.operands
        sz = dst.size
        ct = cast(sz)
        bits = sz * 8
        A0 = rd(i, dst)
        live = self.lo[a] & frozenset('CO')
        n = '1' if (cnt.type == X86_OP_IMM and cnt.imm == 1) else rd(i, cnt)
        sb = bits - 1
        if m == 'rol':
            expr = '(%s)((a_ << k_) | (a_ >> (%d - k_)))' % (ct, bits)
        else:
            expr = '(%s)((a_ >> k_) | (a_ << (%d - k_)))' % (ct, bits)
        self.emit('{ %s a_ = %s; unsigned n_ = %s & 0x1f, k_ = n_ %% %d;' % (ct, A0, n, bits))
        self.emit('  if (n_) { %s r_ = k_ ? %s : a_;' % (ct, expr))
        self.emit('    ' + wr(i, dst, 'r_'))
        if live:
            if m == 'rol':
                self.emit('    CF = r_ & 1;')
                if 'O' in live:
                    self.emit('    OF = ((r_ >> %d) & 1) ^ CF;' % sb)
            else:
                self.emit('    CF = (r_ >> %d) & 1;' % sb)
                if 'O' in live:
                    self.emit('    OF = ((r_ >> %d) ^ (r_ >> %d)) & 1;' % (sb, sb - 1))
        self.emit('  }')
        self.emit('}')

    def jcc_cond(self, a, m):
        if a in self.fold:
            return self.fold[a]
        return {'je': 'ZF', 'jne': '!ZF', 'jl': 'SF != OF', 'jge': 'SF == OF', 'jg': '!ZF && SF == OF',
                'jle': 'ZF || SF != OF', 'jb': 'CF', 'jae': '!CF', 'jns': '!SF', 'js': 'SF',
                'ja': '!CF && !ZF', 'jbe': 'CF || ZF'}[m]

    def strop(self, a, i):
        m = i.mnemonic
        rep = m.split()[0] if ' ' in m else ''
        base = m.split()[-1]
        seg_src = 'DS_'
        for op in i.operands:
            if op.type == X86_OP_MEM and op.mem.base and i.reg_name(op.mem.base) == 'si' and op.mem.segment:
                seg_src = R16[i.reg_name(op.mem.segment)]
        one = {
            'movsb': 'MOVSB(%s);' % seg_src,
            'movsw': 'MOVSW(%s);' % seg_src,
            'stosb': 'STOSB();',
            'stosw': 'STOSW();',
            'lodsb': 'LODSB(%s);' % seg_src,
            'lodsw': 'LODSW(%s);' % seg_src,
        }
        if base in one:
            if rep and base == 'movsb':
                self.emit('REP_MOVSB(%s);' % seg_src)
            elif rep:
                self.emit('while (CX) { %s CX--; }' % one[base])
            else:
                self.emit(one[base])
            return
        if base in ('scasb', 'cmpsb', 'cmpsw'):
            w = 2 if base == 'cmpsw' else 1
            ct = cast(w)
            if base == 'scasb':
                load = 'uint8_t a_ = AL, b_ = RB(ES_, DI); DI += DF ? -1 : 1;'
            else:
                load = '%s a_ = %s(%s, SI), b_ = %s(ES_, DI); SI += DF ? -%d : %d; DI += DF ? -%d : %d;' % (
                    ct, 'RB' if w == 1 else 'RW', seg_src, 'RB' if w == 1 else 'RW', w, w, w, w)
            flags = 'unsigned r_ = (unsigned)a_ - b_; ZF = ((%s)r_ == 0); CF = (a_ < b_); SF = (r_ >> %d) & 1; ' \
                    'OF = (((a_ ^ b_) & (a_ ^ r_)) >> %d) & 1;' % (ct, signbit(w), signbit(w))
            if rep:
                cond = 'ZF' if rep == 'repe' else '!ZF'
                self.emit('while (CX) { %s %s CX--; if (!(%s)) break; }' % (load, flags, cond))
            else:
                self.emit('{ %s %s }' % (load, flags))
            return
        raise Exception('strop %s' % m)

    def dispatch_to(self, key_expr):
        self.emit('jkey = %s; goto dispatch;' % key_expr)

    def ins(self, a, i):
        m = i.mnemonic
        ops = i.operands
        seg = iseg[a]
        nxt = a + i.size
        nxt_off = nxt - seg * 16
        base = seg * 16
        if m == 'mov':
            self.emit(wr(i, ops[0], rd(i, ops[1], ops[0].size)))
        elif m == 'lea':
            s, off = mem_addr(i, ops[1])
            self.emit('%s = %s;' % (R16[i.reg_name(ops[0].reg)], off))
        elif m in ('lds', 'les'):
            s, off = mem_addr(i, ops[1])
            self.emit('{ uint16_t o_ = RW(%s, %s), s_ = RW(%s, (uint16_t)(%s + 2)); %s = o_; %s = s_; }' % (
                s, off, s, off, R16[i.reg_name(ops[0].reg)], 'DS_' if m == 'lds' else 'ES_'))
        elif m == 'xchg':
            A0, B0 = rd(i, ops[0]), rd(i, ops[1])
            ct = cast(ops[0].size)
            self.emit('{ %s t_ = %s; %s %s }' % (ct, A0, wr(i, ops[0], B0), wr(i, ops[1], 't_')))
        elif m == 'push':
            if ops[0].type == X86_OP_REG and i.reg_name(ops[0].reg) == 'sp':
                self.emit('PUSH((uint16_t)(SP - 2));')
            else:
                self.emit('PUSH(%s);' % rd(i, ops[0]))
        elif m == 'pop':
            if ops[0].type == X86_OP_REG:
                self.emit('%s = POP();' % R16[i.reg_name(ops[0].reg)])
            else:
                self.emit('{ uint16_t t_ = POP(); %s }' % wr(i, ops[0], 't_'))
        elif m in ('add', 'sub', 'adc', 'sbb', 'and', 'or', 'xor', 'cmp', 'test', 'inc', 'dec', 'neg', 'not'):
            self.alu(a, i)
        elif m in ('rol', 'ror'):
            self.rot(a, i)
        elif m in ('shl', 'shr', 'sar', 'rcl', 'rcr'):
            self.shift(a, i)
        elif m == 'mul':
            s = rd(i, ops[0])
            if ops[0].size == 1:
                self.emit('AX = (uint16_t)(AL * %s);' % s)
                if self.lo[a] & frozenset('CO'):
                    self.emit('CF = OF = (AH != 0);')
            else:
                self.emit('{ uint32_t p_ = (uint32_t)AX * %s; AX = (uint16_t)p_; DX = (uint16_t)(p_ >> 16); }' % s)
                if self.lo[a] & frozenset('CO'):
                    self.emit('CF = OF = (DX != 0);')
        elif m == 'imul':
            s = rd(i, ops[0])
            assert ops[0].size == 2 and len(ops) == 1
            self.emit('{ int32_t p_ = (int32_t)(int16_t)AX * (int16_t)%s; AX = (uint16_t)p_; DX = (uint16_t)((uint32_t)p_ >> 16); }' % s)
            if self.lo[a] & frozenset('CO'):
                self.emit('CF = OF = ((int32_t)(int16_t)AX != (int32_t)(((uint32_t)DX << 16) | AX));')
        elif m == 'div':
            s = rd(i, ops[0])
            if ops[0].size == 1:
                self.emit('{ uint8_t d_ = %s; uint16_t n_ = AX; if (!d_ || n_ / d_ > 0xff) soc_fault(0x%05x, 1);'
                          ' AL = (uint8_t)(n_ / d_); AH = (uint8_t)(n_ %% d_); }' % (s, a))
            else:
                self.emit('{ uint16_t d_ = %s; uint32_t n_ = ((uint32_t)DX << 16) | AX;'
                          ' if (!d_ || n_ / d_ > 0xffff) soc_fault(0x%05x, 1);'
                          ' AX = (uint16_t)(n_ / d_); DX = (uint16_t)(n_ %% d_); }' % (s, a))
        elif m == 'cwde' or m == 'cbw':
            self.emit('AX = (uint16_t)(int16_t)(int8_t)AL;')
        elif m == 'cdq' or m == 'cwd':
            self.emit('DX = (AX & 0x8000) ? 0xffff : 0;')
        elif m == 'cli':
            self.emit('IF_ = 0;')
        elif m == 'sti':
            self.emit('IF_ = 1;')
        elif m == 'nop':
            pass
        elif m == 'hlt':
            self.emit('soc_fault(0x%05x, 2);' % a)
        elif m == 'pushf':
            self.emit('PUSH(GETFLAGS());')
        elif m == 'popf':
            self.emit('SETFLAGS(POP());')
        elif m == 'cld':
            self.emit('DF = 0;')
        elif m == 'std':
            self.emit('DF = 1;')
        elif m == 'stc':
            self.emit('CF = 1;')
        elif m == 'clc':
            self.emit('CF = 0;')
        elif m == 'cmc':
            self.emit('CF = !CF;')
        elif m == 'xlatb':
            seg_src = 'DS_'
            for op in ops:
                if op.type == X86_OP_MEM and op.mem.segment:
                    seg_src = R16[i.reg_name(op.mem.segment)]
            self.emit('AL = RB(%s, (uint16_t)(BX + AL));' % seg_src)
        elif m.startswith('rep') or m in ('lodsb', 'lodsw', 'stosb', 'stosw', 'movsb', 'movsw', 'scasb', 'cmpsb', 'cmpsw'):
            self.strop(a, i)
        elif m == 'int':
            n = ops[0].imm
            if n == 0x20:
                self.emit('return;')
            else:
                self.emit('do_int(0x%02x);' % n)
        elif m == 'in':
            self.emit('%s = io_in(%s);' % (rd(i, ops[0]), rd(i, ops[1])))
        elif m == 'out':
            if ops[1].size == 2:
                self.emit('io_outw(%s, %s);' % (rd(i, ops[0]), rd(i, ops[1])))
            else:
                self.emit('io_out(%s, %s);' % (rd(i, ops[0]), rd(i, ops[1])))
        # ---- 흐름 ----
        elif m == 'call':
            r_off = nxt_off              # 인라인 인자가 있으면 불린 쪽이 건너뛴다
            if ops[0].type == X86_OP_IMM:
                t = tgt(i)
                self.emit('PUSH(0x%04x); goto %s;%s' % (r_off, lab(t), (' /* %s */' % names[t]) if t in names else ''))
            else:
                self.emit('{ uint16_t o_ = %s; PUSH(0x%04x); jkey = 0x%05x + o_; goto dispatch; }' % (rd(i, ops[0]), r_off, base))
        elif m == 'lcall':
            r_off = nxt_off
            if ops[0].type == X86_OP_IMM:
                s, o = scan.w16(a + 3), scan.w16(a + 1)
                t = s * 16 + o
                self.emit('PUSH(CS_); PUSH(0x%04x); CS_ = SEG(0x%x); goto %s;%s' % (
                    r_off, s, lab(t), (' /* %s */' % names[t]) if t in names else ''))
            else:
                s, off = mem_addr(i, ops[0])
                self.emit('{ uint16_t o_ = RW(%s, %s), s_ = RW(%s, (uint16_t)(%s + 2));' % (s, off, s, off))
                self.emit('  PUSH(CS_); PUSH(0x%04x); CS_ = s_; jkey = KEY(s_, o_); goto dispatch; }' % r_off)
        elif m == 'ret':
            n = ops[0].imm if ops else 0
            self.emit('{ uint16_t o_ = POP(); %sjkey = 0x%05x + o_; goto dispatch; }' % (
                ('SP += %d; ' % n) if n else '', base))
        elif m == 'retf':
            n = ops[0].imm if ops else 0
            self.emit('{ uint16_t o_ = POP(); CS_ = POP(); %sjkey = KEY(CS_, o_); goto dispatch; }' % (
                ('SP += %d; ' % n) if n else ''))
        elif m == 'iret':
            self.emit('{ uint16_t o_ = POP(); CS_ = POP(); SETFLAGS(POP()); irq_leave(); jkey = KEY(CS_, o_); goto dispatch; }')
        elif m == 'jmp':
            if ops[0].type == X86_OP_IMM:
                self.emit('goto %s;' % lab(tgt(i)))
            else:
                self.emit('jkey = 0x%05x + %s; goto dispatch;' % (base, rd(i, ops[0])))
        elif m == 'ljmp':
            if ops[0].type == X86_OP_IMM:
                s, o = scan.w16(a + 3), scan.w16(a + 1)
                self.emit('CS_ = SEG(0x%x); goto %s;' % (s, lab(s * 16 + o)))
            else:
                s, off = mem_addr(i, ops[0])
                self.emit('{ uint16_t o_ = RW(%s, %s), s_ = RW(%s, (uint16_t)(%s + 2)); CS_ = s_; jkey = KEY(s_, o_); goto dispatch; }' % (
                    s, off, s, off))
        elif m in JCC:
            t = tgt(i)
            if a in POLL:
                head = POLL[a]
                self.emit('if (%s) { POLL_POINT(0x%04x); goto %s; }' % (self.jcc_cond(a, m), head - base, lab(head)))
            else:
                self.emit('if (%s) goto %s;' % (self.jcc_cond(a, m), lab(t)))
        elif m == 'loop':
            self.emit('if (--CX) goto %s;' % lab(tgt(i)))
        elif m == 'loopne':
            self.emit('if (--CX && !ZF) goto %s;' % lab(tgt(i)))
        elif m == 'loope':
            self.emit('if (--CX && ZF) goto %s;' % lab(tgt(i)))
        elif m == 'jcxz':
            self.emit('if (CX == 0) goto %s;' % lab(tgt(i)))
        else:
            raise Exception('%05x %s %s' % (a, m, i.op_str))


ENDS = ('jmp', 'ret', 'retf', 'ljmp', 'iret', 'hlt')


def main():
    lin, lout, it = liveness()
    addrs = sorted(code)
    labels = set(DISPATCH)
    for a in addrs:
        i = code[a]
        m = i.mnemonic
        if (m in ('jmp', 'call', 'ljmp', 'lcall') or m in JCC or m.startswith('loop') or m == 'jcxz') and \
                i.operands[0].type == X86_OP_IMM:
            labels.add(far_tgt(a) if m in ('ljmp', 'lcall') else tgt(i))
    # 앞 명령에서 흘러 들어오지 않는 곳도 레이블 (앞이 자료거나 다른 흐름)
    prev_end = None
    for a in addrs:
        if prev_end != a:
            labels.add(a)
        prev_end = a + code[a].size
    g = Gen(lin, lout, labels)
    out = []
    w = out.append
    w('/* soc_%s.c - MicroProse Soccer (%s) 를 tools/asm2c.py 로 옮긴 것.  손대지 말 것. */' % (GAME, image.EXE))
    w('#include "cpu.h"')
    w('#include "socvga.h"')
    w('uint32_t fast_tile(uint32_t after), fast_scroll(uint32_t after), fast_spr3(uint32_t after);')
    w('')
    w('void soc_run_%s(void)' % GAME)
    w('{')
    w('    uint32_t jkey;')
    w('    CS_ = SEG(0x%x);' % image.GSEG_SYS)
    w('    goto %s;' % lab(image.GSEG_SYS * 16 + image.GH[10]))
    prev_end = None
    prev_m = None
    nl = 0
    for a in addrs:
        i = code[a]
        seg = iseg[a]
        if a in labels:
            if a in funcs or a in names:
                w('')
                w('/* ---- %s */' % names.get(a, 'f_%04x_%04x' % (seg, a - seg * 16)))
            w('%s:' % lab(a))
        g.out = []
        if a in VHOOKS:
            g.emit('VH(0x%05x);' % a)
        if a in FAST:
            g.emit('{ uint32_t k_ = %s(0x%05x); if (k_) { jkey = k_; goto dispatch; } }' % FAST[a])
        g.ins(a, i)
        txt = '/* %04x:%04x %s %s */' % (seg, a - seg * 16, i.mnemonic, i.op_str)
        body = ' '.join(g.out)
        w('    %s %s' % (body, txt) if body else '    %s' % txt)
        nl += 1
        prev_end = a + i.size
        prev_m = i.mnemonic
        if (prev_m not in ENDS and not (prev_m == 'int' and i.operands[0].imm == 0x20)) and prev_end not in code:
            w('    soc_fault(0x%05x, 3);' % prev_end)
    w('')
    w('dispatch:')
    w('    switch (jkey) {')
    for a in sorted(DISPATCH):
        w('    case 0x%05x: goto %s;' % (a, lab(a)))
    w('    }')
    w('    if (jkey == KEY(PSPSEG, 0)) return;          /* retf 로 PSP:0000 (int 20h) */')
    w('    jkey = soc_unknown(jkey);')
    w('    goto dispatch;')
    w('}')
    fn = os.path.join(ROOT, 'soc_%s.c' % GAME)
    open(fn, 'w', encoding='utf-8', newline='\n').write('\n'.join(out) + '\n')
    print('%s: %d instructions, %d labels, %d dispatch, %d polls, %d fast, liveness iters %d' % (
        os.path.basename(fn), nl, len(labels), len(DISPATCH), len(POLL), len(FAST), it))


if __name__ == '__main__':
    main()
