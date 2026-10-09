# 256색 개선판 자료 SOCVGA.DAT 만들기
#   python tools/mkvga.py [미리보기 폴더]
#   두 게임(실내/실외)을 에뮬레이터로 잠깐 돌려 (그림 파일을 드라이버가 읽은 뒤) 메모리에서
#   스프라이트 뱅크와 경기장 타일 지도를 읽는다.
#     스프라이트: 마스크 모양의 거리장으로 높이를 만들고, 왼쪽 위에서 비추는 빛으로 음영 (0..15, 8=원래)
#     경기장: 원래 색을 보고 잔디는 깎은 줄무늬 + 결 + 가장자리 어둡게, 흰 선은 가운데 밝게
#   덩어리: "PIT0"/"PIT1" (704x1112), "SPR0"/"SPR1" (작은 프레임 24x21), "BIG0"/"BIG1" (큰 프레임)
import sys, os, struct, math, random, importlib
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

PW, PH = 704, 1112
DRV = 0x254F0


def grab(game):
    os.environ['SOCGAME'] = game
    for m in ('image', 'scan', 'polls', 'emu', 'cover'):
        if m in sys.modules:
            importlib.reload(sys.modules[m])
    import emu
    m = emu.Machine(keys=[])
    m.run_poll(300)
    return bytes(m.low) + bytes(m.mu.mem_read(0x1000, 0x9F000))


def w16(M, a):
    return M[a] | M[a + 1] << 8


# ---- 스프라이트 ----
def frame_info(M, n, big):
    base = w16(M, DRV + 0x1193) * 16
    amap, body, maskb = w16(M, DRV + 0x9ee), w16(M, DRV + 0x9f0), w16(M, DRV + 0x9f2)
    e = base + (n + 1) * 10 + amap
    ofs = w16(M, e)
    if big:
        wb, h = M[e + 4] >> 2, M[e + 6]
    else:
        wb, h = 3, 21
    pl = base + ofs + body
    mk = base + ((ofs - 2) >> 1) + maskb
    mask = [[not (M[mk + y * wb + (x >> 3)] >> (7 - (x & 7)) & 1) for x in range(wb * 8)] for y in range(h)]
    col = [[sum((M[pl + p * wb * h + y * wb + (x >> 3)] >> (7 - (x & 7)) & 1) << p for p in range(4))
            for x in range(wb * 8)] for y in range(h)]
    # 유니폼 마스크: 불투명 마스크 바로 뒤 (드라이버가 두 번째로 OR 하며 팀 색 평면에 칠한다)
    km = mk + wb * h
    kit = [[bool(M[km + y * wb + (x >> 3)] >> (7 - (x & 7)) & 1) and mask[y][x] for x in range(wb * 8)] for y in range(h)]
    frame_info.kit = kit
    return wb * 8, h, mask, col


def shade_sprite(w, h, mask, col=None, kit=None, big=False):
    INF = 99
    d = [[0 if not mask[y][x] else INF for x in range(w)] for y in range(h)]
    # 거리장 (8 이웃, 두 번 훑기)
    for y in range(h):
        for x in range(w):
            if d[y][x]:
                v = d[y][x]
                for dy, dx in ((-1, -1), (-1, 0), (-1, 1), (0, -1)):
                    yy, xx = y + dy, x + dx
                    v = min(v, (d[yy][xx] if 0 <= yy < h and 0 <= xx < w else 0) + 1)
                d[y][x] = v
    for y in range(h - 1, -1, -1):
        for x in range(w - 1, -1, -1):
            if d[y][x]:
                v = d[y][x]
                for dy, dx in ((1, 1), (1, 0), (1, -1), (0, 1)):
                    yy, xx = y + dy, x + dx
                    v = min(v, (d[yy][xx] if 0 <= yy < h and 0 <= xx < w else 0) + 1)
                d[y][x] = v
    # 높이: 둥글게 (반지름 3 까지)
    H = [[math.sqrt(max(0.0, 1.0 - (1.0 - min(d[y][x], 3.5) / 3.5) ** 2)) * 3.0 if mask[y][x] else 0.0
          for x in range(w)] for y in range(h)]
    L = (-0.55, -0.7, 0.9)
    ln = math.sqrt(sum(c * c for c in L))
    L = tuple(c / ln for c in L)
    out = bytearray(w * h)
    for y in range(h):
        for x in range(w):
            if not mask[y][x]:
                out[y * w + x] = 0
                continue
            hx = (H[y][min(w - 1, x + 1)] - H[y][max(0, x - 1)]) / 2
            hy = (H[min(h - 1, y + 1)][x] - H[max(0, y - 1)][x]) / 2
            n = (-hx, -hy, 1.0)
            nl = math.sqrt(sum(c * c for c in n))
            lam = sum(a * b for a, b in zip(n, L)) / nl
            # 스프라이트 칸: 유니폼/검정 0..3 (그늘 -> 빛), 피부 4..6
            v = 1.7 + (lam - 0.62) * 3.6
            if d[y][x] == 1:
                v -= 0.5
            out[y * w + x] = 100 + max(0, min(30, int(round(v * 10))))     # 임시: 빛 (x10)
    if col is not None:
        finish_sprite(w, h, mask, col, kit, out, big)
    return out


SKIN = {12: 0.0, 6: -0.8, 4: -1.1}      # 원판은 피부(12)에 갈색/빨강을 체크로 섞어 그늘을 냈다


def finish_sprite(w, h, mask, col, kit, out, big=False):
    def at(x, y):
        return 0 <= x < w and 0 <= y < h
    light = [[(out[y * w + x] - 100) / 10.0 if mask[y][x] else 0 for x in range(w)] for y in range(h)]
    skin = [[mask[y][x] and not kit[y][x] and col[y][x] in SKIN for x in range(w)] for y in range(h)]
    black = [[mask[y][x] and not kit[y][x] and col[y][x] == 0 for x in range(w)] for y in range(h)]
    for y in range(h):
        for x in range(w):
            if not mask[y][x]:
                out[y * w + x] = 255
                continue
            v = light[y][x]
            bn = sum(1 for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)) if at(x + dx, y + dy) and black[y + dy][x + dx])
            sn = sum(1 for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)) if at(x + dx, y + dy) and skin[y + dy][x + dx])
            # 머리카락 (경기장의 작은 선수만; 큰 초상화는 눈/무릎이 검정 옆 피부라 건드리지 않는다):
            # 원판은 피부색(갈색)과 검정을 체크로 섞었다 -> 두 쪽 다 짙은 갈색 한 가지로
            if not big and skin[y][x] and bn >= 2:
                out[y * w + x] = 4
                continue
            if not big and black[y][x] and sn >= 2:
                out[y * w + x] = 3
                continue
            if skin[y][x]:
                # 3x3 안 피부 점들의 어둡기 평균 -> 체크무늬가 풀린 부드러운 그늘
                acc, n = 0.0, 0
                for dy in (-1, 0, 1):
                    for dx in (-1, 0, 1):
                        if at(x + dx, y + dy) and skin[y + dy][x + dx]:
                            acc += SKIN[col[y + dy][x + dx]]
                            n += 1
                sv = v * 0.6 + 1.0 + acc / max(1, n)
                out[y * w + x] = 5 if sv < (1.0 if big else 1.5) else 6     # 얼굴은 5..6 (4 는 머리카락); 초상화는 얼룩이 덜 지게
                continue
            kn = sum(1 for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)) if at(x + dx, y + dy) and kit[y + dy][x + dx])
            if black[y][x] and kn >= 2:
                v = 2                   # 유니폼 속 검은 체크 (옷 주름): 짙은 그늘 (회색으로 뜨지 않게)
            elif kit[y][x] and bn >= 2:
                v = min(v, 1)           # 주름 둘레 유니폼은 조금 어둡게
            out[y * w + x] = max(0, min(3, int(round(v))))


def mark_shadow(w, h, mask, col, sh):
    """공 프레임 0..11: 공 (검정이 아닌 점) 의 가장 아랫줄보다 아래의 검은 점 = 그림자 -> 8
       (socvga.c 가 그 아래 잔디를 어둡게 한 색으로 칠한다: 잔디가 비쳐 보이는 그림자)"""
    yb = -1
    for y in range(h):
        if any(mask[y][x] and col[y][x] != 0 for x in range(w)):
            yb = y
    for y in range(yb + 1, h):
        for x in range(w):
            if mask[y][x] and col[y][x] == 0:
                sh[y * w + x] = 8


# ---- 경기장 ----
def pitch_colors(M):
    base = w16(M, DRV + 0x1177) * 16
    img = bytearray(PW * PH)
    for r in range(PH // 8):
        for c in range(PW // 8):
            t = w16(M, base + (r * 88 + c) * 2)
            for y in range(8):
                p = [M[base + t + q * 8 + y] for q in range(4)]
                for x in range(8):
                    s = 7 - x
                    img[(r * 8 + y) * PW + c * 8 + x] = sum(((p[q] >> s) & 1) << q for q in range(4))
    return img


# ---- socvga.c 와 같은 팔레트 램프 ----
ATC_D = [0, 1, 2, 3, 4, 5, 6, 7, 16, 17, 18, 19, 20, 21, 22, 23]


def base_rgb(c):
    R = ((c >> 2) & 1) * 2 + ((c >> 5) & 1)
    G = ((c >> 1) & 1) * 2 + ((c >> 4) & 1)
    B = (c & 1) * 2 + ((c >> 3) & 1)
    L = (0, 92, 176, 250)
    r, g, b = L[R], L[G], L[B]
    if G > R and G > B:
        r = r * 7 // 10 + 18
        g = g * 85 // 100 + 20
        b = b * 6 // 10 + 30
    return r, g, b


def ramp(c, s, atc=ATC_D):
    r0, g0, b0 = base_rgb(atc[c] & 63)
    t = (s - 8) / 7.0
    r, g, b = float(r0), float(g0), float(b0)
    if t < 0:
        k = 1.0 + 0.62 * t
        r *= k
        g *= k
        b = b * k + 14 * -t
    elif t > 0:
        mx = max(r0, g0, b0)
        k = 0.28 * t if mx == 0 else 0.6 * t
        r += (255 - r) * k + 10 * t
        g += (255 - g) * k + 4 * t
        b += (255 - b) * k * 0.85
    return tuple(max(0, min(255, int(v))) for v in (r, g, b))


RAMP = [[ramp(c, s) for s in range(16)] for c in range(16)]


def best_shade(c, target, lo=2, hi=14):
    best, bs = None, 8
    for s in range(lo, hi + 1):
        q = RAMP[c][s]
        d = (q[0] - target[0]) ** 2 * 3 + (q[1] - target[1]) ** 2 * 4 + (q[2] - target[2]) ** 2 * 2
        if best is None or d < best:
            best, bs = d, s
    return bs


PIT = 7     # 경기장 칸 7..11 (socvga.c PIT_BASE): 5 단계, 잔디 색(2, 10, 14)은 모두 같은 녹색 계열


def shade_pitch(img, game):
    from collections import Counter
    GRASS = (2, 10, 14)
    rnd = random.Random(7)
    out = bytearray(PW * PH)
    ys = [y for y in range(PH) if img[y * PW + 160] in GRASS]
    y0, y1 = (min(ys), max(ys)) if ys else (0, PH)
    xs = [x for x in range(PW) if img[((y0 + y1) // 2) * PW + x] in GRASS]
    x0, x1 = (min(xs), max(xs)) if xs else (0, 320)
    for y in range(PH):
        band = ((y - y0) // 24) & 1          # 가로로 깎은 줄무늬
        for x in range(PW):
            c = img[y * PW + x]
            if c in GRASS:
                v = 2.7 if band else 1.6
                dx = (x - (x0 + x1) / 2) / max(1, (x1 - x0) / 2)
                dy = (y - (y0 + y1) / 2) / max(1, (y1 - y0) / 2)
                v -= 1.4 * max(0.0, (dx * dx + dy * dy) ** 0.5 - 0.65)     # 가장자리 그늘
                r = rnd.random()
                if r < 0.10:
                    v -= 0.9
                elif r < 0.20:
                    v += 0.9
                out[y * PW + x] = PIT + max(0, min(4, int(round(v))))
            elif c == 15:
                nb = sum(1 for ddx, ddy in ((1, 0), (-1, 0), (0, 1), (0, -1))
                         if 0 <= x + ddx < PW and 0 <= y + ddy < PH and img[(y + ddy) * PW + x + ddx] == 15)
                out[y * PW + x] = PIT + (4 if nb >= 3 else 3)
            else:
                r = rnd.random()
                out[y * PW + x] = PIT + 2 + (1 if r < 0.12 else -1 if r < 0.24 else 0)
    return out


def main():
    prev = sys.argv[1] if len(sys.argv) > 1 else None
    chunks = []
    for g, name in ((0, 'in'), (1, 'out')):
        M = grab(name)
        img = pitch_colors(M)
        ps = shade_pitch(img, g)
        chunks.append((b'PIT%d' % g, bytes(ps)))
        cnt = w16(M, DRV + 0x9f4) + 1
        for big in (False, True):
            data = bytearray(struct.pack('<H', cnt))
            for n in range(cnt):
                w, h, mask, col = frame_info(M, n, big)
                kit = frame_info.kit
                if w == 0 or h == 0 or w > 255 or h > 255:
                    w, h, sh = 0, 0, b''
                else:
                    sh = shade_sprite(w, h, mask, col, kit, big)
                    if not big and n <= 11:
                        mark_shadow(w, h, mask, col, sh)
                data += struct.pack('<HBB', n, w, h) + bytes(sh)
            chunks.append(((b'BIG%d' if big else b'SPR%d') % g, bytes(data)))
        print(name, 'frames', cnt)
        if prev:
            from PIL import Image
            os.makedirs(prev, exist_ok=True)
            EGA = [(0, 0, 0), (0, 0, 170), (0, 170, 0), (0, 170, 170), (170, 0, 0), (170, 0, 170), (170, 85, 0),
                   (170, 170, 170), (85, 85, 85), (85, 85, 255), (85, 255, 85), (85, 255, 255), (255, 85, 85),
                   (255, 85, 255), (255, 255, 85), (255, 255, 255)]
            im = Image.new('RGB', (PW, PH))
            px = im.load()
            for y in range(PH):
                for x in range(PW):
                    c = EGA[img[y * PW + x]]
                    k = 0.55 + 0.12 * (ps[y * PW + x] - PIT)
                    px[x, y] = tuple(min(255, int(v * k)) for v in c)
            im.save(os.path.join(prev, 'pitch_%s.png' % name))
    with open(os.path.join(os.path.dirname(HERE), 'SOCVGA.DAT'), 'wb') as f:
        for tag, data in chunks:
            f.write(tag + struct.pack('<I', len(data)) + data)
    print('SOCVGA.DAT', sum(8 + len(d) for t, d in chunks), 'bytes')


if __name__ == '__main__':
    main()
