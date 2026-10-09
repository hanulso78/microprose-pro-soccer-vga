# 에뮬레이터(원판) 와 hosttest.exe(옮긴 C) 를 같은 키 대본으로 돌려 폴마다 상태를 견준다
#   python tools/difftest.py 대본.txt 틱수 [이름]
#   -> tools/_<이름>_emu.txt, tools/_<이름>_host.txt, 첫 차이
import sys, os, subprocess, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import image, emu, cover

script, nt = sys.argv[1], int(sys.argv[2])
name = sys.argv[3] if len(sys.argv) > 3 else 'd'
H = image.HERE
fe = os.path.join(H, '_%s_emu.txt' % name)
fh = os.path.join(H, '_%s_host.txt' % name)
t0 = time.time()
every = int(os.environ.get('EVERY', '1'))
env = dict(os.environ, EVERY=str(every))
r = subprocess.run([os.path.join(image.ROOT, 'hosttest.exe'), image.GAME, script, str(nt), fh],
                   cwd=image.ROOT, capture_output=True, text=True, env=env)
print('host:', r.stdout.strip(), '(%.1fs)' % (time.time() - t0))
t0 = time.time()
blocks = set()
m = emu.Machine(keys=cover.load_script(script))
print('emu :', m.run_poll(nt, fe, blocks=blocks, every=every), '(%.1fs)' % (time.time() - t0))
# 실행된 블록은 커버리지 파일에 더한다
cv = os.path.join(H, '_cover_%s.txt' % image.GAME)
old = set(open(cv).read().split()) if os.path.exists(cv) else set()
new = set('%04x:%04x' % (s, o) for s, o in blocks if s >= 0)
if new - old:
    open(cv, 'w').write('\n'.join(sorted(old | new)) + '\n')
    print('cover: +%d blocks (now %d) -> 다시 번역해야 함' % (len(new - old), len(old | new)))
A = open(fe).read().splitlines()
B = open(fh).read().splitlines()
for k, (x, y) in enumerate(zip(A, B)):
    if x != y:
        print('FIRST DIFF at line %d' % (k + 1))
        for j in range(max(0, k - 2), min(k + 2, len(A), len(B))):
            print(' emu ', A[j])
            print(' host', B[j])
        sys.exit(1)
print('same for %d lines (emu %d, host %d)' % (min(len(A), len(B)), len(A), len(B)))
