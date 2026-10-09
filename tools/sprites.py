# 스프라이트 뱅크 풀기 (메모리 덤프에서, 드라이버 API 9 / 18 이 읽는 대로)
#   python tools/sprites.py 덤프.bin 결과.png [in|out]
#   작은 프레임 (API 9): 24x21, 마스크 3x21 바이트 (0 = 불투명) + 평면 4 x 63 바이트
#   큰 프레임 (API 18): AMAP 의 너비(바이트*4)/높이, 같은 모양
import sys, struct
from PIL import Image

DRV = 0x254F0


def load(dump):
    d = open(dump, 'rb').read()
    M = d[:0xA0000]
    w16 = lambda a: M[a] | M[a + 1] << 8
    seg = w16(DRV + 0x1193)
    return M, w16, seg * 16, w16(DRV + 0x9ee), w16(DRV + 0x9f0), w16(DRV + 0x9f2), w16(DRV + 0x9f4)


def frame(M, w16, base, amap, body, maskb, n, big=False):
    e = base + (n + 1) * 10 + amap
    ofs = w16(e)
    if big:
        wb = M[e + 4] >> 2
        h = M[e + 6]
    else:
        wb, h = 3, 21
    pl = base + ofs + body
    mk = base + ((ofs - 2) >> 1) + maskb
    img = []
    for y in range(h):
        row = []
        for x in range(wb * 8):
            byte, bit = x >> 3, 7 - (x & 7)
            m = M[mk + y * wb + byte] >> bit & 1
            c = 0
            for p in range(4):
                c |= (M[pl + p * wb * h + y * wb + byte] >> bit & 1) << p
            row.append(None if m else c)
        img.append(row)
    return img, (w16(e), M[e + 2], M[e + 3], M[e + 4], M[e + 5], M[e + 6], M[e + 7], w16(e + 8))


EGA = [(0, 0, 0), (0, 0, 170), (0, 170, 0), (0, 170, 170), (170, 0, 0), (170, 0, 170), (170, 85, 0), (170, 170, 170),
       (85, 85, 85), (85, 85, 255), (85, 255, 85), (85, 255, 255), (255, 85, 85), (255, 85, 255), (255, 255, 85), (255, 255, 255)]

if __name__ == '__main__':
    M, w16, base, amap, body, maskb, cnt = load(sys.argv[1])
    print('amap %04x body %04x mask %04x count %d' % (amap, body, maskb, cnt))
    big = len(sys.argv) > 3 and sys.argv[3] == 'big'
    N = min(cnt + 1, 256)
    cols = 16
    W = Image.new('RGB', (cols * 34, ((N + cols - 1) // cols) * 40), (60, 60, 90))
    for n in range(N):
        img, info = frame(M, w16, base, amap, body, maskb, n, big)
        if n < 8:
            print(n, info)
        for y, row in enumerate(img[:38]):
            for x, c in enumerate(row[:32]):
                if c is not None:
                    W.putpixel(((n % cols) * 34 + x, (n // cols) * 40 + y), EGA[c])
    W.resize((W.width * 2, W.height * 2), Image.NEAREST).save(sys.argv[2])
