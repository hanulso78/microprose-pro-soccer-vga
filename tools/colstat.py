# 장면 그림(hostvga BMP + .kind)에서 (문맥 종류, EGA 색) 별 점 수
import sys, collections
from PIL import Image
NAMES = ['none', 'fill', 'tile', 'spr', 'big', 'char', 'noise', 'radar', 'rest', 'cursor']
for fn in sys.argv[1:]:
    im = Image.open(fn); px = list(im.getdata())
    k = open(fn + '.kind', 'rb').read()
    c = collections.Counter()
    for i in range(64000):
        kk = k[i]
        name = NAMES[kk & 15] if (kk & 15) < 10 else '?'
        if kk & 0x40: name = 'block'
        if name == 'char' and not kk & 0x80: name = 'charbg'
        c[(name, px[i] >> 4)] += 1
    print(fn, ' '.join('%s/%d:%d' % (a, b, n) for (a, b), n in sorted(c.items(), key=lambda x: -x[1])[:30]))
