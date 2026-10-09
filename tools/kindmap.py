# 시험판(hostvga, SOCDBG) 이 남긴 이름.kind 를 색 그림으로: python tools/kindmap.py 이름.bmp 결과.png
import sys
from PIL import Image
NAMES = ['none', 'fill', 'tile', 'spr', 'big', 'char', 'noise', 'radar', 'rest', 'cursor']
COL = [(40, 40, 40), (0, 90, 255), (0, 200, 0), (255, 60, 60), (255, 140, 0), (255, 255, 0), (200, 0, 200),
       (0, 255, 255), (128, 128, 255), (255, 255, 255)]
d = open(sys.argv[1] + '.kind', 'rb').read()
im = Image.new('RGB', (320, 200))
px = im.load()
for y in range(200):
    for x in range(320):
        k = d[y * 320 + x]
        c = COL[k & 15] if (k & 15) < len(COL) else (255, 255, 255)
        if k & 0x40:
            c = (160, 160, 0)
        if not k & 0x80:
            c = tuple(v // 2 for v in c)
        px[x, y] = c
a = Image.open(sys.argv[1]).convert('RGB')
W = Image.new('RGB', (644, 200))
W.paste(a, (0, 0)); W.paste(im, (324, 0))
W.resize((1288, 400), Image.NEAREST).save(sys.argv[2])
