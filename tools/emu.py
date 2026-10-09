# MicroProse Soccer 원판(EXEPACK 푼 것 + EGAIO 드라이버)을 unicorn 실모드로 돌리는 기준 에뮬레이터
#   - 메모리 그림은 image.py (게임 LOADSEG, 드라이버 DRVSEG, 드라이버 점프표 미리 채움)
#   - A0000 은 EGA 평면 메모리 흉내
#   - 시계: IRQ 는 정해진 '폴 자리'(POLL, 대기 되돌이) 에서만 넣는다 -> 결정적
#       (POLL 이 비어 있으면 탐색용으로 명령 CHUNK 개마다 넣는다)
#   - 자판: 게임이 건 int 9 처리기에 스캔 코드를 넣는다 (포트 60h)
import struct, sys, os
from unicorn import *
from unicorn.x86_const import *

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import image
from image import LOADSEG, PSP, DRVSEG, ROOT

BIOSSEG = 0xF000
MEMTOP = 0x9FFF


class Exit(Exception):
    pass


class VGA:
    def __init__(self):
        self.pl = [bytearray(0x10000) for _ in range(4)]
        self.latch = [0, 0, 0, 0]
        self.seq = [0] * 8
        self.seq[2] = 0xF
        self.gc = [0] * 9
        self.gc[8] = 0xFF
        self.seqi = self.gci = 0
        self.crtc = [0] * 32
        self.crtci = 0
        self.atc = list(range(16))
        self.atci = None
        self.atcflip = 0

    def read(self, off):
        for p in range(4):
            self.latch[p] = self.pl[p][off]
        if self.gc[5] & 8:
            cc, dc = self.gc[2], self.gc[7]
            r = 0
            for b in range(8):
                ok = True
                for p in range(4):
                    if dc >> p & 1 and ((self.latch[p] >> b & 1) != (cc >> p & 1)):
                        ok = False
                if ok:
                    r |= 1 << b
            return r
        return self.latch[self.gc[4] & 3]

    def write(self, off, v):
        mode = self.gc[5] & 3
        mm = self.seq[2]
        bm = self.gc[8]
        fn = (self.gc[3] >> 3) & 3
        rot = self.gc[3] & 7
        if mode == 1:
            for p in range(4):
                if mm >> p & 1:
                    self.pl[p][off] = self.latch[p]
            return
        if rot:
            v = ((v >> rot) | (v << (8 - rot))) & 0xFF
        for p in range(4):
            if not (mm >> p & 1):
                continue
            if mode == 0:
                if self.gc[1] >> p & 1:
                    d = 0xFF if self.gc[0] >> p & 1 else 0
                else:
                    d = v
            elif mode == 2:
                d = 0xFF if v >> p & 1 else 0
            else:
                d = 0xFF if self.gc[0] >> p & 1 else 0
                bm2 = bm & v
                la = self.latch[p]
                self.pl[p][off] = (d & bm2) | (la & ~bm2 & 0xFF)
                continue
            la = self.latch[p]
            if fn == 1:
                d &= la
            elif fn == 2:
                d |= la
            elif fn == 3:
                d ^= la
            self.pl[p][off] = (d & bm) | (la & ~bm & 0xFF)

    def out(self, port, v):
        if port == 0x3C4:
            self.seqi = v & 7
        elif port == 0x3C5:
            self.seq[self.seqi] = v
        elif port == 0x3CE:
            self.gci = v & 15
        elif port == 0x3CF:
            if self.gci < 9:
                self.gc[self.gci] = v
        elif port == 0x3D4:
            self.crtci = v & 31
        elif port == 0x3D5:
            self.crtc[self.crtci] = v
        elif port == 0x3C0:
            if self.atcflip == 0:
                self.atci = v & 0x3F
                self.atcflip = 1
            else:
                if self.atci < 16:
                    self.atc[self.atci] = v & 0x3F
                self.atcflip = 0

    def pixels(self, w=320, h=200, start=0):
        out = bytearray(w * h)
        pl = self.pl
        bpr = w // 8
        for y in range(h):
            for xb in range(bpr):
                o = (start + y * bpr + xb) & 0xFFFF
                b0, b1, b2, b3 = pl[0][o], pl[1][o], pl[2][o], pl[3][o]
                base = y * w + xb * 8
                for k in range(8):
                    s = 7 - k
                    out[base + k] = (b0 >> s & 1) | (b1 >> s & 1) << 1 | (b2 >> s & 1) << 2 | (b3 >> s & 1) << 3
        return out


def ega64(c):
    # EGA 64색 번호 -> RGB (rgbRGB)
    r = ((c >> 2) & 1) * 2 + ((c >> 5) & 1)
    g = ((c >> 1) & 1) * 2 + ((c >> 4) & 1)
    b = (c & 1) * 2 + ((c >> 3) & 1)
    return (r * 85, g * 85, b * 85)


class Machine:
    def __init__(self, keys=None, adapter=b'E', chunk=20000, poll=None):
        mu = self.mu = Uc(UC_ARCH_X86, UC_MODE_16)
        self.low = bytearray(0x1000)
        mu.mmio_map(0, 0x1000, self.low_r, None, self.low_w, None)
        mu.mem_map(0x1000, 0x9F000)
        self.vga = VGA()
        mu.mmio_map(0xA0000, 0x10000, self.mmio_r, None, self.mmio_w, None)
        mu.mem_map(0xB0000, 0x50000)
        mu.mem_write(LOADSEG * 16, bytes(image.IMG))
        for r in image.RELOC:
            v = struct.unpack('<H', image.IMG[r:r + 2])[0]
            mu.mem_write(LOADSEG * 16 + r, struct.pack('<H', (v + LOADSEG) & 0xFFFF))
        h = image.GH
        # PSP + 명령 꼬리: [80]=길이, [82]=어댑터 글자, [83]/[85] = 불러 준 쪽 자료 far 포인터
        mu.mem_write(PSP * 16, b'\xcd\x20')
        mu.mem_write(PSP * 16 + 2, struct.pack('<H', MEMTOP + 1))
        mu.mem_write(PSP * 16 + 0x2C, struct.pack('<H', 0x0F00))
        mu.mem_write(0xF000, b'PATH=C:\\\0COMSPEC=C:\\COMMAND.COM\0\0\x01\0C:\\SOCCER.EXE\0')
        self.comm = 0x0E00          # SOCCER.COM 이 넘기는 자료 (세그먼트 0E00:0000)
        mu.mem_write(PSP * 16 + 0x80, bytes([6, 0x20]) + adapter + struct.pack('<HH', 0, self.comm) + b'\r')
        for n in range(256):
            mu.mem_write(n * 4, struct.pack('<HH', n * 4, BIOSSEG))
            mu.mem_write(BIOSSEG * 16 + n * 4, bytes([0xCD, n, 0xCF, 0x90]))
        mu.mem_write(0x410, struct.pack('<H', 0x0021))
        mu.mem_write(0x41A, struct.pack('<HH', 0x1E, 0x1E))
        mu.mem_write(0x413, struct.pack('<H', 640))
        mu.mem_write(0x449, bytes([3]))
        mu.mem_write(0x44A, struct.pack('<H', 80))
        mu.mem_write(0x463, struct.pack('<H', 0x3D4))
        mu.mem_write(0x484, bytes([24]))
        mu.mem_write(0x487, bytes([0x60]))
        mu.mem_write(0x488, bytes([0x09]))
        mu.mem_write(0x489, bytes([0x11]))
        mu.mem_write(0xFFFFE, bytes([0xFC]))
        mu.reg_write(UC_X86_REG_CS, LOADSEG + h[11])
        mu.reg_write(UC_X86_REG_IP, h[10])
        mu.reg_write(UC_X86_REG_SS, LOADSEG + h[7])
        mu.reg_write(UC_X86_REG_SP, h[8])
        mu.reg_write(UC_X86_REG_DS, PSP)
        mu.reg_write(UC_X86_REG_ES, PSP)
        mu.hook_add(UC_HOOK_INTR, self.on_int)
        mu.hook_add(UC_HOOK_INSN, self.on_in, None, 1, 0, UC_X86_INS_IN)
        mu.hook_add(UC_HOOK_INSN, self.on_out, None, 1, 0, UC_X86_INS_OUT)
        self.keys = list(keys or [])        # (틱, 스캔코드)
        self.chunk = chunk
        self.handles = {}
        self.ticks = 0
        self.pit_period = 0x10000
        self.pit_lohi = 0
        self.pending_irq = 0
        self.log = []
        self.memfree = image.DRVSEG + image.DRVPARAS + 1
        self.vmode = 3
        self.port60 = 0
        self.nint = 0
        self.spk = []
        self.shots = []
        self.irq_ret = []
        self.irq_hook = None
        self.frames = 0
        import tempfile, shutil
        self.savedir = os.path.join(tempfile.gettempdir(), 'socemu_save_%d' % os.getpid())
        shutil.rmtree(self.savedir, ignore_errors=True)
        os.makedirs(self.savedir, exist_ok=True)

    # ---- 메모리 ----
    def low_r(self, uc, off, size, ud):
        return int.from_bytes(self.low[off:off + size], 'little')

    def low_w(self, uc, off, size, value, ud):
        self.low[off:off + size] = (value & ((1 << (8 * size)) - 1)).to_bytes(size, 'little')

    def mmio_r(self, uc, off, size, ud):
        v = self.vga.read(off)
        if size == 2:
            v |= self.vga.read(off + 1) << 8
        return v

    def mmio_w(self, uc, off, size, value, ud):
        self.vga.write(off, value & 0xFF)
        if size == 2:
            self.vga.write(off + 1, value >> 8 & 0xFF)

    # ---- 포트 ----
    def on_out(self, mu, port, size, value, ud):
        if port == 0x43:
            self.pit_lohi = 0 if (value & 0xC0) == 0 else self.pit_lohi
            return
        if port == 0x40:
            if self.pit_lohi == 0:
                self.pit_lo = value & 0xFF
                self.pit_lohi = 1
            else:
                self.pit_period = (self.pit_lo | (value & 0xFF) << 8) or 0x10000
                self.pit_lohi = 0
                self.log.append('pit0 period %d' % self.pit_period)
            return
        if port in (0x61, 0x42):
            self.spk.append((self.ticks, port, value & 0xFF))
            return
        if size == 2:
            self.vga.out(port, value & 0xFF)
            self.vga.out(port + 1, value >> 8)
        else:
            self.vga.out(port, value & 0xFF)

    def on_in(self, mu, port, size, ud):
        if port == 0x60:
            return self.port60
        if port == 0x61:
            return 0
        if port == 0x201:
            return 0xFF
        if port == 0x3DA or port == 0x3BA:
            self.vga.atcflip = 0
            self.nint += 1
            return 0x09 if self.nint & 1 else 0
        if port == 0x21:
            return 0xB8
        return 0xFF

    # ---- 인터럽트 넣기 ----
    def ivt(self, n):
        return struct.unpack('<HH', self.low[n * 4:n * 4 + 4])

    def call_isr(self, n):
        """지금 자리에서 n 번 처리기를 부르고 돌아올 때까지 돌린다"""
        mu = self.mu
        o, sg = self.ivt(n)
        if sg == BIOSSEG:
            return
        fl = mu.reg_read(UC_X86_REG_EFLAGS)
        cs, ip = mu.reg_read(UC_X86_REG_CS), mu.reg_read(UC_X86_REG_IP)
        ss, sp = mu.reg_read(UC_X86_REG_SS), mu.reg_read(UC_X86_REG_SP)
        sp = (sp - 6) & 0xFFFF
        # 돌아올 자리: F000:0400 의 hlt 같은 것 대신 BIOS 영역의 'int FFh' 로 멈춘다
        mu.mem_write(ss * 16 + sp, struct.pack('<HHH', 0x0800, BIOSSEG, (fl & 0x0600) | 0x0002))
        mu.mem_write(BIOSSEG * 16 + 0x800, b'\xf4')
        mu.reg_write(UC_X86_REG_SP, sp)
        mu.reg_write(UC_X86_REG_EFLAGS, fl & ~0x300)
        mu.reg_write(UC_X86_REG_CS, sg)
        mu.emu_start(sg * 16 + o, BIOSSEG * 16 + 0x800, 0, 2000000)
        mu.reg_write(UC_X86_REG_CS, cs)
        mu.reg_write(UC_X86_REG_IP, ip)
        mu.reg_write(UC_X86_REG_EFLAGS, fl)

    # ---- int ----
    def setcf(self, on):
        f = self.mu.reg_read(UC_X86_REG_EFLAGS)
        self.mu.reg_write(UC_X86_REG_EFLAGS, (f | 1) if on else (f & ~1))

    def setzf(self, on):
        f = self.mu.reg_read(UC_X86_REG_EFLAGS)
        self.mu.reg_write(UC_X86_REG_EFLAGS, (f | 0x40) if on else (f & ~0x40))

    def cstr(self, seg, off):
        s = b''
        while True:
            c = self.mu.mem_read(seg * 16 + off, 1)[0]
            if c == 0:
                return s
            s += bytes([c])
            off += 1

    def path(self, seg, off, save=False):
        s = self.cstr(seg, off).decode('latin1').replace('\\', '/').split('/')[-1]
        if save:
            return os.path.join(self.savedir, s.upper())
        for f in os.listdir(os.path.join(ROOT, 'orig')):
            if f.lower() == s.lower():
                return os.path.join(ROOT, 'orig', f)
        return os.path.join(ROOT, 'orig', s.upper())

    def on_int(self, mu, n, ud):
        r = mu.reg_read
        w = mu.reg_write
        ax = r(UC_X86_REG_AX)
        ah, al = ax >> 8, ax & 0xFF
        if n == 0x10:
            if ah == 0:
                self.vmode = al & 0x7F
                mu.mem_write(0x449, bytes([self.vmode]))
                for p in self.vga.pl:
                    p[:] = bytes(0x10000)
                self.vga.atc = [0, 1, 2, 3, 4, 5, 20, 7, 56, 57, 58, 59, 60, 61, 62, 63] if self.vmode != 0xD else \
                    [0, 1, 2, 3, 4, 5, 6, 7, 16, 17, 18, 19, 20, 21, 22, 23]
                self.vga.crtc[0xC] = self.vga.crtc[0xD] = 0
                self.log.append('mode %02X' % al)
            elif ah == 0x0F:
                w(UC_X86_REG_AX, 0x2800 | self.vmode)
                w(UC_X86_REG_BX, 0)
            elif ah == 0x12:
                w(UC_X86_REG_BX, 0x0003)
                w(UC_X86_REG_CX, 0x0009)
            elif ah == 0x1A:
                w(UC_X86_REG_AX, 0x0000)        # VGA 아님 (EGA 로 보이게)
            elif ah == 0x10:
                bx = r(UC_X86_REG_BX)
                if al == 0:
                    self.vga.atc[bx & 15] = bx >> 8
                elif al == 2:
                    a = r(UC_X86_REG_ES) * 16 + r(UC_X86_REG_DX)
                    self.vga.atc = list(mu.mem_read(a, 16))
                else:
                    self.log.append('int10 10/%02X' % al)
            else:
                self.log.append('int10 ah=%02X al=%02X' % (ah, al))
        elif n == 0x11:
            w(UC_X86_REG_AX, 0x0021)
        elif n == 0x16:
            self.log.append('int16 ah=%02X' % ah)
            if ah == 0:
                w(UC_X86_REG_AX, 0x1C0D)
            else:
                self.setzf(True)
        elif n == 0x21:
            self.int21(ah, al)
        elif n == 0x20:
            raise Exit(0)
        else:
            self.log.append('int %02X ax=%04X at %04X:%04X' % (n, ax, r(UC_X86_REG_CS), r(UC_X86_REG_IP)))

    def int21(self, ah, al):
        mu = self.mu
        r = mu.reg_read
        w = mu.reg_write
        ok = True
        if ah == 0x25:
            mu.mem_write(al * 4, struct.pack('<HH', r(UC_X86_REG_DX), r(UC_X86_REG_DS)))
            self.log.append('setvec %02X -> %04X:%04X' % (al, r(UC_X86_REG_DS), r(UC_X86_REG_DX)))
        elif ah == 0x35:
            o, s = self.ivt(al)
            w(UC_X86_REG_BX, o)
            w(UC_X86_REG_ES, s)
        elif ah == 0x4A:
            pass
        elif ah == 0x48:
            want = r(UC_X86_REG_BX)
            if want == image.DRVPARAS and not hasattr(self, 'drv_given'):
                self.drv_given = 1
                w(UC_X86_REG_AX, DRVSEG)
            else:
                seg = self.memfree + 1
                if seg + want > MEMTOP:
                    w(UC_X86_REG_BX, max(0, MEMTOP - seg))
                    w(UC_X86_REG_AX, 8)
                    ok = False
                else:
                    self.memfree += want + 1
                    w(UC_X86_REG_AX, seg)
            self.log.append('alloc %04X -> %s' % (want, 'ok' if ok else 'fail'))
        elif ah == 0x49:
            pass
        elif ah == 0x4B and al == 3:
            name = self.cstr(r(UC_X86_REG_DS), r(UC_X86_REG_DX))
            pb = r(UC_X86_REG_ES) * 16 + r(UC_X86_REG_BX)
            seg, fac = struct.unpack('<HH', mu.mem_read(pb, 4))
            self.log.append('overlay %s at %04X/%04X' % (name, seg, fac))
            assert seg == DRVSEG and fac == DRVSEG, (hex(seg), hex(fac))
            # 이미 image.IMG 에 올려 두었다
        elif ah == 0x3D or ah == 0x3C:
            p = self.path(r(UC_X86_REG_DS), r(UC_X86_REG_DX), True)
            try:
                if ah == 0x3C:
                    f = open(p, 'w+b')
                elif al & 3:
                    if not os.path.exists(p):
                        src = self.path(r(UC_X86_REG_DS), r(UC_X86_REG_DX))
                        if os.path.exists(src):
                            open(p, 'wb').write(open(src, 'rb').read())
                    f = open(p, 'r+b')
                elif os.path.exists(p):
                    f = open(p, 'rb')
                else:
                    p = self.path(r(UC_X86_REG_DS), r(UC_X86_REG_DX))
                    f = open(p, 'rb')
                hnd = 5
                while hnd in self.handles:
                    hnd += 1
                self.handles[hnd] = f
                w(UC_X86_REG_AX, hnd)
                self.log.append('open %s -> %d' % (os.path.basename(p), hnd))
            except OSError:
                self.log.append('open %s failed' % os.path.basename(p))
                w(UC_X86_REG_AX, 2)
                ok = False
        elif ah == 0x3E:
            f = self.handles.pop(r(UC_X86_REG_BX), None)
            if f:
                f.close()
        elif ah == 0x3F:
            hnd, n = r(UC_X86_REG_BX), r(UC_X86_REG_CX)
            a = r(UC_X86_REG_DS) * 16 + r(UC_X86_REG_DX)
            f = self.handles.get(hnd)
            if f is None:
                w(UC_X86_REG_AX, 6)
                ok = False
            else:
                b = f.read(n)
                mu.mem_write(a, b)
                w(UC_X86_REG_AX, len(b))
                self.log.append('read %d -> %04X:%04X got %d' % (n, r(UC_X86_REG_DS), r(UC_X86_REG_DX), len(b)))
        elif ah == 0x40:
            hnd, n = r(UC_X86_REG_BX), r(UC_X86_REG_CX)
            f = self.handles.get(hnd)
            if f is None:
                w(UC_X86_REG_AX, 6)
                ok = False
            else:
                f.write(bytes(mu.mem_read(r(UC_X86_REG_DS) * 16 + r(UC_X86_REG_DX), n)))
                f.flush()
                w(UC_X86_REG_AX, n)
                self.log.append('write %d' % n)
        elif ah == 0x42:
            f = self.handles.get(r(UC_X86_REG_BX))
            off = (r(UC_X86_REG_CX) << 16) | r(UC_X86_REG_DX)
            f.seek(off, al)
            p = f.tell()
            w(UC_X86_REG_AX, p & 0xFFFF)
            w(UC_X86_REG_DX, p >> 16)
        elif ah == 0x4C:
            raise Exit(al)
        elif ah == 0x30:
            w(UC_X86_REG_AX, 0x0005)
        else:
            self.log.append('int21 ah=%02X al=%02X' % (ah, al))
        self.setcf(not ok)

    # ---- 돌리기 (탐색용: 명령 chunk 개마다 타이머 IRQ) ----
    def run_ticks(self, nticks, shot_every=0, shot_prefix='_s'):
        mu = self.mu
        for t in range(nticks):
            cs = mu.reg_read(UC_X86_REG_CS)
            ip = mu.reg_read(UC_X86_REG_IP)
            try:
                mu.emu_start(cs * 16 + ip, 0xFFFFF, 0, self.chunk)
            except Exit as e:
                return 'exit %s' % e
            except UcError as e:
                cs = mu.reg_read(UC_X86_REG_CS)
                ip = mu.reg_read(UC_X86_REG_IP)
                return 'ucerror %s at %04X:%04X' % (e, cs, ip)
            self.ticks += 1
            while self.keys and self.keys[0][0] <= self.ticks:
                self.port60 = self.keys.pop(0)[1]
                if mu.reg_read(UC_X86_REG_EFLAGS) & 0x200:
                    self.call_isr(9)
            if mu.reg_read(UC_X86_REG_EFLAGS) & 0x200:
                self.call_isr(8)
            if shot_every and t % shot_every == 0:
                fn = os.path.join(ROOT, '%s%04d.png' % (shot_prefix, t))
                self.screen(fn)
                self.shots.append(fn)
        return 'ok'

    # ---- 폴 지점 모델 (옮긴 C 와 같은 규칙: socrt.c soc_poll) ----
    def run_poll(self, maxticks, trace=None, shots=None, every=1, blocks=None):
        import zlib, polls
        from unicorn import UC_HOOK_CODE, UC_HOOK_BLOCK
        mu = self.mu
        L = LOADSEG * 16
        self.maxticks = maxticks
        self.tpend = 0
        self.kbuf = -1
        self.npoll = 0
        self.nirq = 0
        self.trace = open(trace, 'w') if trace else None
        self.every = every
        self.shotlist = dict(shots or {})
        self.keys.sort(key=lambda e: e[0])
        FL = {'je': lambda f: f & 0x40, 'jne': lambda f: not f & 0x40,
              'jb': lambda f: f & 1, 'jae': lambda f: not f & 1,
              'js': lambda f: f & 0x80, 'jns': lambda f: not f & 0x80,
              'ja': lambda f: not f & 1 and not f & 0x40, 'jbe': lambda f: f & 1 or f & 0x40,
              'jl': lambda f: bool(f & 0x80) != bool(f & 0x800), 'jge': lambda f: bool(f & 0x80) == bool(f & 0x800),
              'jg': lambda f: not f & 0x40 and bool(f & 0x80) == bool(f & 0x800),
              'jle': lambda f: f & 0x40 or bool(f & 0x80) != bool(f & 0x800)}
        import scan
        for a, head in polls.POLLS:
            cond = FL[scan.code[a].mnemonic]
            seg = scan.iseg[a]
            mu.hook_add(UC_HOOK_CODE, self.on_poll, (cond, (head - seg * 16) & 0xFFFF), L + a, L + a)
        for a, i in scan.code.items():
            if i.mnemonic == 'pushf':
                mu.hook_add(UC_HOOK_CODE, self.on_after_pushf, None, L + a + 1, L + a + 1)
        if blocks is not None:
            def hb(mu, addr, size, ud):
                cs = mu.reg_read(UC_X86_REG_CS)
                blocks.add((cs - LOADSEG, addr - cs * 16))
            mu.hook_add(UC_HOOK_BLOCK, hb)
        res = 'stopped'
        self.stopped = False
        # 감시견: 명령 5 천만 개 동안 폴이 하나도 없으면 폴 없는 대기 루프에 걸린 것으로 보고 멈춘다
        idle = 0
        while True:
            cs = mu.reg_read(UC_X86_REG_CS)
            ip = mu.reg_read(UC_X86_REG_IP)
            n0 = self.npoll
            try:
                mu.emu_start(cs * 16 + ip, 0xFFFFF, 0, 5000000)
            except Exit as e:
                res = 'exit %s' % e
                break
            except UcError as e:
                cs = mu.reg_read(UC_X86_REG_CS)
                ip = mu.reg_read(UC_X86_REG_IP)
                res = 'ucerror %s at %04X:%04X' % (e, cs, ip)
                break
            if self.stopped:
                break
            idle = idle + 1 if self.npoll == n0 else 0
            if idle >= 10:
                cs = mu.reg_read(UC_X86_REG_CS)
                ip = mu.reg_read(UC_X86_REG_IP)
                res = 'HANG (no poll in 50M insns) at %04X:%04X' % (cs - LOADSEG, ip)
                break
        if self.trace:
            self.trace.close()
        return res + ' ticks %d polls %d irqs %d' % (self.ticks, self.npoll, self.nirq)

    def on_after_pushf(self, mu, addr, size, ud):
        a = mu.reg_read(UC_X86_REG_SS) * 16 + mu.reg_read(UC_X86_REG_SP)
        v = struct.unpack('<H', mu.mem_read(a, 2))[0]
        mu.mem_write(a, struct.pack('<H', (v & 0x0EC1) | 0x0002))

    def plat_key(self):
        if self.keys and self.keys[0][0] <= self.ticks:
            return self.keys.pop(0)[1]
        return -1

    def hooked(self, n):
        return self.ivt(n)[1] != BIOSSEG

    def on_poll(self, mu, addr, size, ud):
        cond, head = ud
        fl = mu.reg_read(UC_X86_REG_EFLAGS)
        if not cond(fl) or not fl & 0x200:
            return
        # socrt.c soc_poll 과 같은 규칙
        self.npoll += 1
        if self.kbuf < 0:
            self.kbuf = self.plat_key()
        if self.kbuf < 0 and not self.tpend:
            self.ticks += 1
            self.tpend = 1
            if self.ticks in self.shotlist:
                self.screen(self.shotlist[self.ticks])
            if self.ticks >= self.maxticks:
                self.stopped = True
                mu.emu_stop()
                return
            self.kbuf = self.plat_key()
        irq = 9 if self.kbuf >= 0 else 8 if self.tpend else 0
        if self.trace and self.npoll % self.every == 0:
            self.trace.write(self.state_line(irq) + '\n')
        n = 0
        if self.kbuf >= 0:
            k = self.kbuf
            self.kbuf = -1
            if self.hooked(9):
                self.port60 = k
                n = 9
        elif self.tpend:
            self.tpend = 0
            if self.hooked(8):
                n = 8
        if not n:
            return
        # IRQ: FLAGS(IF|DF), CS, 루프 머리 를 넣고 처리기로
        self.nirq += 1
        ss, sp = mu.reg_read(UC_X86_REG_SS), mu.reg_read(UC_X86_REG_SP)
        cs = mu.reg_read(UC_X86_REG_CS)
        sp = (sp - 6) & 0xFFFF
        mu.mem_write(ss * 16 + sp, struct.pack('<HHH', head, cs, (fl & 0x0600) | 0x0002))
        mu.reg_write(UC_X86_REG_SP, sp)
        mu.reg_write(UC_X86_REG_EFLAGS, fl & ~0x300)
        o, sg = self.ivt(n)
        mu.reg_write(UC_X86_REG_CS, sg)
        mu.reg_write(UC_X86_REG_IP, o)

    def state_line(self, irq):
        import zlib
        mu = self.mu
        r = mu.reg_read
        m = bytes(self.low) + bytes(mu.mem_read(0x1000, 0x9F000))
        c1 = zlib.crc32(m)
        c2 = zlib.crc32(b''.join(bytes(p) for p in self.vga.pl))
        regs = [r(x) for x in (UC_X86_REG_AX, UC_X86_REG_BX, UC_X86_REG_CX, UC_X86_REG_DX, UC_X86_REG_SI,
                               UC_X86_REG_DI, UC_X86_REG_BP, UC_X86_REG_SP, UC_X86_REG_CS, UC_X86_REG_DS,
                               UC_X86_REG_ES, UC_X86_REG_SS)]
        return '%d %d %d %s %08X %08X' % (self.npoll, self.ticks, irq, ' '.join('%04X' % v for v in regs), c1, c2)

    def screen(self, fn, page=None):
        from PIL import Image
        start = (self.vga.crtc[0x0C] << 8 | self.vga.crtc[0x0D]) if page is None else page
        px = self.vga.pixels(320, 200, start)
        pal = []
        for i in range(16):
            pal += list(ega64(self.vga.atc[i]))
        im = Image.frombytes('P', (320, 200), bytes(px))
        im.putpalette(pal + [0] * (768 - len(pal)))
        im.convert('RGB').resize((640, 400), Image.NEAREST).save(fn)


if __name__ == '__main__':
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 200
    every = int(sys.argv[2]) if len(sys.argv) > 2 else 50
    m = Machine(keys=[])
    print(m.run_ticks(n, every))
    print('\n'.join(m.log[:100]))
    print(m.shots)
