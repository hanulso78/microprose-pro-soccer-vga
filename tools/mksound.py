# -*- coding: utf-8 -*-
"""PC 스피커 소리를 애드립(OPL2) VGM 으로 바꿔 SOUND.DAT 하나로 묶는다

   python tools/mksound.py [--wav]

   원판 소리는 채널 4 개짜리 순서기(101a:02f0 이 곡 시작, 03bc 가 1/60 초마다 한 걸음)이고,
   스피커가 하나라 채널들을 번갈아 낸다.  여기서는 에뮬레이터로 원판 순서기를 곡마다 직접 돌려
   채널 0 의 음 (PIT 나눗수 [f4], 음 길이 세기 [f8]) 을 1/60 초마다 받아 OPL2 VGM 으로 쓴다.
   게임은 늘 채널 0 에 곡을 하나씩만 올리므로 곡 하나가 애드립 목소리 9 개를 다 쓴다:
     목소리 0  리드 (여운이 긴 브라스)      목소리 1  같은 옥타브에서 살짝 어긋나게 (코러스, 두께)
     목소리 2  베이스: 멜로디 음을 낮은 옥타브로 접어 8 분음표로 밀어 준다 (옥타브 튀지 않게)   (음악 곡만)
     목소리 3  한 옥타브 아래 브라스, 목소리 4  5 도 아래 깨끗한 브라스: 파워 코드처럼 두껍게 (음악 곡만)
     6..8     리듬 모드 드럼: 킥 1, 3, 3& / 스네어 2, 4 / 하이햇 없음, 네 마디마다 스네어+탐 필인 (심벌 없음)
   박자는 원곡의 음 사이 간격에서 가장 흔한 것으로 잡는다 (한 박 20..40 프레임).
   반복하는 곡은 순서기 상태가 처음 되풀이되는 곳을 VGM 반복 지점으로 적는다.

   SOUND.DAT : "SOCSND1\\0", 곡 수(2), [이름 8, 자리 4, 길이 4] ..., 자료들
               이름 = S00..S15: VGM (실내와 실외의 곡 자료가 같아 한 벌만)
                      P00: 골 함성 (8 비트 부호 없는 PCM, 11025 Hz, 사운드 블래스터로)
                      P01: 공 차기 "퍽" (같은 형식, 크게)
                      P02: 심판 휘슬 한 번 (킥오프), P03: 세 번 "삑 삑 삐이익" (쿼터 끝)
   함성은 여기서 합성한다: 사람 목소리 수십 개 ("와아" 모음을 공명 필터로) + 걸러낸 잡음 + 휘파람.
"""
import sys, os, struct, importlib
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

NSONG = 16
MAXF = 60 * 90                  # 한 곡 최대 90 초
CLOCK = 3579545                 # YM3812
SPF = 735                       # 1/60 초 = 735 샘플 (44100)

# 악기: (연산자 자리, 20, 40, 60, 80, E0) 두 개 + C0
def patch(v, mod, car, c0):
    ofs = (0, 1, 2, 8, 9, 10, 16, 17, 18)[v]
    out = []
    for op, regs in ((ofs, mod), (ofs + 3, car)):
        for base, val in zip((0x20, 0x40, 0x60, 0x80, 0xE0), regs):
            out.append((base + op, val))
    out.append((0xC0 + v, c0))
    return out


LEAD = patch(0, (0x21, 0x1C, 0xE2, 0x24, 0x00), (0x21, 0x02, 0xE1, 0x14, 0x00), 0x0C)     # 브라스 리드 (여운 길게)
CHORUS = patch(1, (0x21, 0x2A, 0xD2, 0x24, 0x00), (0x21, 0x0C, 0xD1, 0x14, 0x00), 0x0A)   # 같은 옥타브 코러스 (부드럽게)
BASS = patch(2, (0x21, 0x18, 0xF3, 0x25, 0x00), (0x21, 0x00, 0xF2, 0x25, 0x00), 0x0A)     # 이어지는 베이스 (굵게)
LOW = patch(3, (0x21, 0x1A, 0xE2, 0x24, 0x00), (0x21, 0x08, 0xE1, 0x14, 0x00), 0x0C)      # 옥타브 아래 브라스
POWER = patch(4, (0x21, 0x1C, 0xE2, 0x24, 0x00), (0x21, 0x0E, 0xE1, 0x14, 0x00), 0x08)    # 5 도 아래 (되먹임 4, 깨끗한 브라스: 잡음처럼 지직거리지 않게)
DRUMS = ([(0x30, 0x00), (0x50, 0x0A), (0x70, 0xA8), (0x90, 0x4C), (0xF0, 0x00),         # 킥 (목소리 6)
          (0x33, 0x00), (0x53, 0x00), (0x73, 0xD6), (0x93, 0x4F), (0xF3, 0x00), (0xC6, 0x00),
          (0x31, 0x01), (0x51, 0x22), (0x71, 0xFB), (0x91, 0xFB), (0xF1, 0x00),         # 하이햇 (목소리 7 앞, 작고 짧게)
          (0x34, 0x01), (0x54, 0x08), (0x74, 0xF8), (0x94, 0x88), (0xF4, 0x00),         # 스네어 (목소리 7 뒤)
          (0x32, 0x05), (0x52, 0x0A), (0x72, 0xF6), (0x92, 0x66), (0xF2, 0x00),         # 탐 (목소리 8 앞)
          (0x35, 0x01), (0x55, 0x3F), (0x75, 0xFF), (0x95, 0xFF), (0xF5, 0x00),         # 심벌 (목소리 8 뒤): 쓰지 않음, 소리 없게
          (0xC7, 0x00), (0xC8, 0x00),
          (0xA6, 0x57), (0xB6, 0x05), (0xA7, 0x03), (0xB7, 0x0A), (0xA8, 0x57), (0xB8, 0x09)])
BD, SD, TT, CY, HH = 0x10, 0x08, 0x04, 0x02, 0x01


def machine(game):
    os.environ['SOCGAME'] = game
    for m in ('image', 'scan', 'polls', 'emu', 'cover'):
        if m in sys.modules:
            importlib.reload(sys.modules[m])
    import emu, image
    m = emu.Machine(keys=[])
    m.run_poll(300)
    return m, emu, image


def call(m, emu, seg, off, ax=0, si=0):
    """원판 함수 seg:off (retf 로 끝남) 를 부르고 돌아올 때까지"""
    from unicorn.x86_const import UC_X86_REG_CS, UC_X86_REG_IP, UC_X86_REG_SP, UC_X86_REG_SS, UC_X86_REG_AX, UC_X86_REG_SI
    mu = m.mu
    r, w = mu.reg_read, mu.reg_write
    cs0, ip0 = r(UC_X86_REG_CS), r(UC_X86_REG_IP)
    ss, sp = r(UC_X86_REG_SS), r(UC_X86_REG_SP)
    sp = (sp - 0x40) & 0xFFFF
    sp = (sp - 4) & 0xFFFF
    mu.mem_write(ss * 16 + sp, struct.pack('<HH', 0x0800, emu.BIOSSEG))
    mu.mem_write(emu.BIOSSEG * 16 + 0x800, b'\xf4')
    w(UC_X86_REG_SP, sp)
    w(UC_X86_REG_AX, ax)
    w(UC_X86_REG_SI, si)
    w(UC_X86_REG_CS, seg)
    mu.emu_start(seg * 16 + off, emu.BIOSSEG * 16 + 0x800, 0, 5000000)
    w(UC_X86_REG_SP, (sp + 4 + 0x40) & 0xFFFF)
    w(UC_X86_REG_CS, cs0)
    w(UC_X86_REG_IP, ip0)


def capture(m, emu, image, song):
    sys_seg = emu.LOADSEG + image.GSEG_SYS
    ds = (emu.LOADSEG + 0x80) * 16
    mu = m.mu
    rd = lambda a, n=2: int.from_bytes(bytes(mu.mem_read(ds + a, n)), 'little')
    call(m, emu, sys_seg, 0x02F0, ax=0x0A)          # 모두 멈춤
    call(m, emu, sys_seg, 0x02F0, ax=0x00, si=song)
    frames = []
    seen = {}
    loop = None
    for f in range(MAXF):
        call(m, emu, sys_seg, 0x03BC)
        act = rd(0xF0)
        div = rd(0xF4)
        cnt = rd(0xF8)
        frames.append((div if act else 0xFFFF, cnt))
        if not act:
            break
        st = bytes(mu.mem_read(ds + 0xF0, 0x40))
        if st in seen:
            loop = seen[st]
            frames.pop()
            break
        seen[st] = f
    return frames, loop


def fnum_block(hz):
    for block in range(8):
        fn = int(round(hz * (1 << (20 - block)) / 49716.0))
        if fn < 1024:
            return fn, block
    return 1023, 7


def onsets(frames):
    ons, prev, pc = [], None, None
    for i, (d, c) in enumerate(frames):
        if d != 0xFFFF and d >= 20 and (prev is None or d != prev or (pc is not None and c < pc)):
            ons.append(i)
        prev = d if d != 0xFFFF else None
        pc = c
    return ons


def tempo(ons):
    """한 박 (프레임): 흔한 음 간격 중 가장 짧은 것을 두 배씩 늘려 20..40 안으로"""
    import collections
    ioi = collections.Counter(b - a for a, b in zip(ons, ons[1:]))
    cands = [d for d, n in ioi.items() if d >= 5 and n >= 0.15 * max(1, len(ons) - 1)]
    if not cands:
        return None
    beat = min(cands)
    while beat < 20:
        beat *= 2
    while beat > 40 and beat % 2 == 0:
        beat //= 2
    return beat


def to_vgm(frames, loop):
    ons = onsets(frames)
    music = len(frames) >= 300 and len(ons) >= 8
    beat = tempo(ons) if music else None
    eighth = beat // 2 if beat else None
    data = bytearray()

    def w(reg, val):
        data.extend((0x5A, reg, val))

    w(0x01, 0x20)
    w(0xBD, 0x20 if beat else 0x00)
    for reg, val in LEAD + CHORUS + BASS + LOW + POWER + (DRUMS if beat else []):
        w(reg, val)
    on = [None] * 5                  # 목소리 0..4 의 (fnum, block)
    lastmel = None
    loop_off = None
    grid0 = ons[0] if ons else 0
    drum_off = False

    def key(v, fb, down):
        if fb is None:
            return
        fn, bl = fb
        w(0xB0 + v, (0x20 if down else 0) | (bl << 2) | (fn >> 8))

    def press(v, fb):
        if on[v] is not None:
            key(v, on[v], False)
        fn, bl = fb
        w(0xA0 + v, fn & 0xFF)
        key(v, fb, True)
        on[v] = fb

    def release(v):
        if on[v] is not None:
            key(v, on[v], False)
            on[v] = None

    prevcnt = None
    cur = None
    for i, (div, cnt) in enumerate(frames):
        if i == loop:
            loop_off = len(data)
            cur = None
            grid0 = i
            for v in range(5):
                release(v)
        if drum_off:
            w(0xBD, 0x20)
            drum_off = False
        retrig = prevcnt is not None and cnt < prevcnt
        if div == 0xFFFF or div < 20:
            if cur is not None:
                for v in (0, 1, 3, 4):
                    release(v)
                cur = None
        else:
            hz = 1193182.0 / div
            if cur != div or retrig:
                press(0, fnum_block(hz))
                fn, bl = fnum_block(hz)                             # 코러스: 같은 음을 살짝 높게
                press(1, (min(1023, int(fn * 1.006 + 1)), bl))
                if beat:                                            # 파워 코드: 옥타브 아래 + 5 도 아래
                    press(3, fnum_block(hz / 2))
                    press(4, fnum_block(hz / 1.5))
                cur = div
            lastmel = hz
        prevcnt = cnt
        if beat and i >= grid0:
            t = i - grid0
            if t % eighth == 0:
                e = (t // eighth) % 32                      # 네 마디 (8 분음표 32 개)
                bits = 0                                    # 하이햇 없음 (칙칙 거슬림)
                if e % 8 in (0, 4, 5):
                    bits |= BD
                if e % 8 in (2, 6):
                    bits |= SD
                if e >= 28:                                 # 네 마디 끝 필인: 스네어 + 탐
                    bits = (bits & BD) | SD | (TT if e % 2 else 0)
                w(0xBD, 0x20 | bits)
                drum_off = True
                if lastmel:                                   # 베이스: 멜로디 음을 55..110 Hz 로 접어 8 분음표로
                    bh = lastmel
                    while bh >= 110:
                        bh /= 2
                    while bh < 55:
                        bh *= 2
                    press(2, fnum_block(bh))
            elif t % eighth == eighth - 1:
                release(2)
        data += b'\x62'                               # 1/60 초
    if loop_off is None:
        for v in range(5):
            release(v)
        if beat:
            w(0xBD, 0x20)
    data += b'\x66'
    nsamp = len(frames) * SPF
    hdr = bytearray(0x80)
    hdr[0:4] = b'Vgm '
    struct.pack_into('<I', hdr, 0x04, 0x80 + len(data) - 4)
    struct.pack_into('<I', hdr, 0x08, 0x151)
    struct.pack_into('<I', hdr, 0x18, nsamp)
    if loop_off is not None:
        struct.pack_into('<I', hdr, 0x1C, 0x80 + loop_off - 0x1C)
        struct.pack_into('<I', hdr, 0x20, (len(frames) - loop) * SPF)
    struct.pack_into('<I', hdr, 0x34, 0x80 - 0x34)
    struct.pack_into('<I', hdr, 0x50, CLOCK)
    to_vgm.info = 'beat %s' % beat if beat else 'effect'
    return bytes(hdr) + bytes(data)


PCM_RATE = 11025


def biquad_bp(x, f, q, rate=PCM_RATE):
    """2 극 띠 통과 (공명)"""
    import math
    w = 2 * math.pi * f / rate
    al = math.sin(w) / (2 * q)
    b0, b2 = al, -al
    a0, a1, a2 = 1 + al, -2 * math.cos(w), 1 - al
    b0, b2, a1, a2 = b0 / a0, b2 / a0, a1 / a0, a2 / a0
    y = [0.0] * len(x)
    x1 = x2 = y1 = y2 = 0.0
    for i, v in enumerate(x):
        o = b0 * v + b2 * x2 - a1 * y1 - a2 * y2
        x2, x1 = x1, v
        y2, y1 = y1, o
        y[i] = o
    return y


def crowd_cheer(secs=5.5, seed=1989):
    """골 함성: 목소리 + 잡음 + 휘파람, 처음에 확 올라 천천히 가라앉는다"""
    import math, random
    rnd = random.Random(seed)
    n = int(secs * PCM_RATE)
    out = [0.0] * n
    # 목소리: 톱니파 -> 모음 공명 두 개 ("아" / "에")
    for k in range(48):
        st = int(rnd.random() ** 1.8 * 2.6 * PCM_RATE)
        du = int((0.5 + rnd.random() * 1.6) * PCM_RATE)
        f0 = 150 + rnd.random() * 230
        glide = 1.0 + rnd.random() * 0.35
        vib = 4 + rnd.random() * 3
        f1, f2 = (rnd.choice(((760, 1150), (620, 1700), (700, 1250), (560, 1900))))
        ln = min(du, n - st)
        if ln <= 0:
            continue
        src = [0.0] * ln
        ph = 0.0
        for i in range(ln):
            t = i / du
            f = f0 * (1 + (glide - 1) * math.sin(math.pi * min(1, t * 1.6))) * (1 + 0.02 * math.sin(2 * math.pi * vib * i / PCM_RATE))
            ph = (ph + f / PCM_RATE) % 1.0
            env = min(1.0, t * 12) * (1 - t) ** 0.6
            src[i] = (ph * 2 - 1) * env
        v = [a + b * 0.6 for a, b in zip(biquad_bp(src, f1, 6), biquad_bp(src, f2, 8))]
        g = 0.5 + rnd.random() * 0.5
        for i in range(ln):
            out[st + i] += v[i] * g
    # 관중 웅성임: 잡음을 500..2500 Hz 로
    noise = [rnd.random() * 2 - 1 for _ in range(n)]
    hiss = biquad_bp(noise, 1100, 0.7)
    for i in range(n):
        t = i / PCM_RATE
        out[i] += hiss[i] * 2.2 * min(1.0, t / 0.3) * max(0.0, 1 - t / secs) ** 0.8
    # 손가락 휘파람 두 번
    for st_s, f0 in ((0.35, 2300), (1.3, 2600)):
        st, du = int(st_s * PCM_RATE), int(0.55 * PCM_RATE)
        ph = 0.0
        for i in range(min(du, n - st)):
            t = i / du
            f = f0 * (1 + 0.18 * math.sin(math.pi * t))
            ph = (ph + f / PCM_RATE) % 1.0
            out[st + i] += math.sin(2 * math.pi * ph) * 0.35 * min(1, t * 10) * (1 - t)
    # 전체 모양: 0.25 초에 꼭대기, 끝으로 가라앉음
    pk = max(abs(v) for v in out) or 1.0
    pcm = bytearray(n)
    for i in range(n):
        t = i / PCM_RATE
        env = min(1.0, t / 0.25) * (1 - max(0.0, t - 2.0) / (secs - 2.0)) ** 1.3
        v = math.tanh(out[i] / pk * 2.2) * env
        pcm[i] = max(0, min(255, int(128 + v * 118)))
    return bytes(pcm)


def kick_thud(secs=0.16, seed=7):
    """공 차기: 짧은 잡음 딸깍 + 음높이가 떨어지는 쿵 (크게)"""
    import math, random
    rnd = random.Random(seed)
    n = int(secs * PCM_RATE)
    pcm = bytearray(n)
    ph = 0.0
    lp = 0.0
    for i in range(n):
        t = i / PCM_RATE
        f = 60 + 140 * math.exp(-t * 35)                 # 200 Hz -> 60 Hz
        ph += f / PCM_RATE
        body = math.sin(2 * math.pi * ph) * math.exp(-t * 22)
        lp += (rnd.random() * 2 - 1 - lp) * 0.5
        click = lp * math.exp(-t * 180) * 1.4
        v = math.tanh((body + click) * 2.4)
        pcm[i] = max(0, min(255, int(128 + v * 126)))
    return bytes(pcm)


def whistle_blasts(blasts, seed=5):
    """심판 휘슬: 2.6 kHz 음을 구슬이 떨듯 초당 30 번쯤 흔들고 입김 잡음을 섞는다.  blasts = [(시작초, 길이초)]"""
    import math, random
    rnd = random.Random(seed)
    secs = max(st + du for st, du in blasts) + 0.05
    n = int(secs * PCM_RATE)
    out = [0.0] * n
    noise = biquad_bp([rnd.random() * 2 - 1 for _ in range(n)], 2600, 3)
    for st, du in blasts:
        a, m = int(st * PCM_RATE), int(du * PCM_RATE)
        ph = 0.0
        for i in range(min(m, n - a)):
            t = i / PCM_RATE
            trill = math.sin(2 * math.pi * 31 * t)
            f = 2600 * (1 + 0.035 * trill)
            ph = (ph + f / PCM_RATE) % 1.0
            env = min(1.0, t / 0.02) * min(1.0, (du - t) / 0.05)
            am = 0.75 + 0.25 * trill
            out[a + i] += (math.sin(2 * math.pi * ph) * am + noise[a + i] * 1.5) * env
    pk = max(abs(v) for v in out) or 1.0
    return [v / pk for v in out]


def to_pcm8(x, gain=1.0):
    import math
    return bytes(max(0, min(255, int(128 + math.tanh(v * gain * 1.6) * 122))) for v in x)


def main():
    songs = []
    os.makedirs(os.path.join(HERE, '..', 'vgm'), exist_ok=True)
    for game, pfx in (('in', 'S'),):
        m, emu, image = machine(game)
        for s in range(NSONG):
            frames, loop = capture(m, emu, image, s)
            v = to_vgm(frames, loop)
            name = '%s%02d' % (pfx, s)
            open(os.path.join(HERE, '..', 'vgm', name + '.vgm'), 'wb').write(v)
            notes = sum(1 for d, c in frames if d != 0xFFFF)
            print('%s: %d frames (%.1fs)%s, %d sounding, %s' % (name, len(frames), len(frames) / 60.0,
                                                            ' loop@%d' % loop if loop is not None else '', notes,
                                                            to_vgm.info))
            songs.append((name, v))
    cheer = crowd_cheer()
    wh = whistle_blasts([(0.0, 0.55)])                  # 골: 심판 휘슬 한 번이 함성 위로
    cheer = bytes(max(0, min(255, int(c + w * 70))) for c, w in zip(cheer, wh + [0.0] * (len(cheer) - len(wh))))
    open(os.path.join(HERE, '..', 'wav', 'cheer.raw'), 'wb').write(cheer)
    songs.append(('P00', cheer))
    thud = kick_thud()
    songs.append(('P01', thud))
    songs.append(('P02', to_pcm8(whistle_blasts([(0.0, 0.7)]))))
    songs.append(('P03', to_pcm8(whistle_blasts([(0.0, 0.22), (0.35, 0.22), (0.7, 1.1)]))))
    for nm, dat in songs[-2:] + [('cheer', cheer)]:
        import wave
        wv = wave.open(os.path.join(HERE, '..', 'wav', nm + '.wav'), 'wb')
        wv.setnchannels(1)
        wv.setsampwidth(1)
        wv.setframerate(PCM_RATE)
        wv.writeframes(dat)
        wv.close()
    print('P00: goal cheer %d bytes (%.1fs PCM)' % (len(cheer), len(cheer) / PCM_RATE))
    out = bytearray(b'SOCSND1\0' + struct.pack('<H', len(songs)))
    pos = len(out) + 16 * len(songs)
    for name, v in songs:
        out += name.encode().ljust(8, b'\0') + struct.pack('<II', pos, len(v))
        pos += len(v)
    for name, v in songs:
        out += v
    fn = os.path.join(HERE, '..', 'SOUND.DAT')
    open(fn, 'wb').write(out)
    print('SOUND.DAT', len(out), 'bytes')


if __name__ == '__main__':
    main()
