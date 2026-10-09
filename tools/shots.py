# hosttest.exe 로 대본을 돌려 틱마다 화면을 찍어 한 장으로: python tools/shots.py 대본 끝틱 간격 결과.png [시작틱] [in|out]
import sys, os, subprocess, glob
from PIL import Image
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import image
script, end, step, out = sys.argv[1], int(sys.argv[2]), int(sys.argv[3]), sys.argv[4]
start = int(sys.argv[5]) if len(sys.argv) > 5 else step
game = sys.argv[6] if len(sys.argv) > 6 else image.GAME
tmp = os.path.join(image.ROOT, '_shots')
os.makedirs(tmp, exist_ok=True)
for f in glob.glob(os.path.join(tmp, '*.bmp')):
    os.remove(f)
ts = list(range(start, end, step))
args = ['%d:_shots/%05d.bmp' % (t, t) for t in ts]
r = subprocess.run([os.path.join(image.ROOT, os.environ.get('HOSTEXE', 'hosttest.exe')), game, script, str(end), '-'] + args,
                   cwd=image.ROOT, capture_output=True, text=True)
print(r.stdout.strip())
ims = [(t, Image.open(os.path.join(tmp, '%05d.bmp' % t)).convert('RGB')) for t in ts if os.path.exists(os.path.join(tmp, '%05d.bmp' % t))]
cols = 4
W = Image.new('RGB', (cols * 322, max(1, (len(ims) + cols - 1) // cols) * 212), (40, 40, 40))
from PIL import ImageDraw
d = ImageDraw.Draw(W)
for k, (t, im) in enumerate(ims):
    x, y = (k % cols) * 322, (k // cols) * 212
    W.paste(im, (x, y + 10))
    d.text((x + 2, y), str(t), fill=(255, 255, 0))
W.save(out)
