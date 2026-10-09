# DOSBox 에서 도스 판을 시험 모드(SOCTEST)로 돌려 찍은 화면을 한 장으로 모은다.
#   python tools/dosshot.py 대본.txt 결과.png [exe] [인자]
#   대본 줄: "틱 +키 [누름]" / "틱 스캔16진" / "틱 shot 이름" / "틱 quit"
#   환경: DOSSET="A=1 B=2" (도스 set 줄 더), CYCLES (기본 max), SOCDIR (다른 폴더, 예: release), KEEP=1 (BMP 남김), REAL=1 (시간 맞춤 켬)
import os, sys, subprocess, glob, tempfile
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.environ.get('SOCDIR') or os.path.abspath(os.path.join(HERE, '..'))
DOSBOX = os.path.abspath(os.path.join(HERE, '..', '..', '..', 'dosbox', 'dosbox.exe'))

script, out = sys.argv[1], sys.argv[2]
exe = sys.argv[3] if len(sys.argv) > 3 else 'soccer.exe'
arg = sys.argv[4] if len(sys.argv) > 4 else '1'
open(os.path.join(ROOT, 'SOCTEST.TXT'), 'w').write(open(script, encoding='utf-8').read().encode('ascii', 'ignore').decode())
for f in glob.glob(os.path.join(ROOT, '*.BMP')) + glob.glob(os.path.join(ROOT, 'SOCLOG.TXT')):
    os.remove(f)
conf = os.path.join(tempfile.gettempdir(), 'socrun.conf')
open(conf, 'w').write('''[dosbox]
machine=svga_s3
memsize=32
[speaker]
pcspeaker=false
tandy=off
[sblaster]
sbtype=%s
[gus]
gus=false
[mixer]
nosound=true
[cpu]
core=auto
cycles=%s
[autoexec]
mount C "%s"
C:
set SOCTEST=SOCTEST.TXT
%s
%s %s > SOCOUT.TXT
exit
''' % ('sb16' if os.environ.get('ADLIB') else 'none', os.environ.get('CYCLES', 'max'), ROOT,
       ('set SOCSNDTEST=1' if os.environ.get('ADLIB') else '') + ('\nset SOCREAL=1' if os.environ.get('REAL') else ''),
       exe, arg))
subprocess.run([DOSBOX, '-conf', conf, '-noconsole'], cwd=os.path.dirname(DOSBOX), timeout=900)
names = [ln.split()[2] for ln in open(script, encoding='utf-8') if len(ln.split()) >= 3 and ln.split()[1] == 'shot']
imgs = []
for n in names:
    fn = os.path.join(ROOT, n.upper() + '.BMP')
    if os.path.exists(fn):
        imgs.append(Image.open(fn).convert('RGB'))
        if not os.environ.get('KEEP'):
            os.remove(fn)
cols = 3
W = Image.new('RGB', (cols * 322, max(1, (len(imgs) + cols - 1) // cols) * 202), (60, 60, 60))
for i, im in enumerate(imgs):
    W.paste(im, ((i % cols) * 322, (i // cols) * 202))
W = W.resize((W.width * 2, W.height * 2), Image.NEAREST)
W.save(out)
print('%d shots' % len(imgs))
log = os.path.join(ROOT, 'SOCLOG.TXT')
if os.path.exists(log):
    print(open(log).read().strip())
out2 = os.path.join(ROOT, 'SOCOUT.TXT')
if os.path.exists(out2) and open(out2, 'rb').read().strip():
    print('stdout:', open(out2, 'rb').read().decode('latin1').strip()[-2000:])
