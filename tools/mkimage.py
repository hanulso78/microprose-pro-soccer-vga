# 합친 메모리 그림 (게임 + 드라이버, 재배치 끝낸 것) 을 C 배열로: socimg_<game>.c
import sys, os, struct
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import image

img = bytearray(image.IMG)
for r in image.RELOC:
    v = struct.unpack('<H', img[r:r + 2])[0]
    img[r:r + 2] = struct.pack('<H', (v + image.LOADSEG) & 0xFFFF)
n = len(img)
while n and img[n - 1] == 0:
    n -= 1
g = image.GAME
out = ['/* socimg_%s.c - %s + %s 를 LOADSEG(%04X) 에 올린 모습 (tools/mkimage.py 가 만든다) */' % (
    g, image.EXE, image.DRV, image.LOADSEG), '#include <stdint.h>',
    'const uint32_t soc_img_%s_len = %d;' % (g, n),
    'const uint16_t soc_img_%s_regs[4] = {0x%04x, 0x%04x, 0x%04x, 0x%04x};   /* CS IP SS SP (LOADSEG 기준) */' % (
        g, image.GH[11], image.GH[10], image.GH[7], image.GH[8]),
    'const uint8_t soc_img_%s[%d] = {' % (g, n)]
for k in range(0, n, 32):
    out.append(','.join(str(b) for b in img[k:min(k + 32, n)]) + ',')
out.append('};')
open(os.path.join(image.ROOT, 'socimg_%s.c' % g), 'w', newline='\n').write('\n'.join(out) + '\n')
print('socimg_%s.c %d bytes' % (g, n))
