# 에뮬레이터만 폴 모델로 돌려 실행 블록을 커버리지 파일에 더한다 (대조 없이, 빠르게)
#   python tools/cover2.py 대본 틱수   -> 새 블록 수 출력
import sys, os, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import image, emu, cover
script, nt = sys.argv[1], int(sys.argv[2])
t0 = time.time()
blocks = set()
m = emu.Machine(keys=cover.load_script(script))
res = m.run_poll(nt, None, blocks=blocks)
cv = os.path.join(image.HERE, '_cover_%s.txt' % image.GAME)
old = set(open(cv).read().split()) if os.path.exists(cv) else set()
new = set('%04x:%04x' % (s, o) for s, o in blocks if s >= 0)
if new - old:
    open(cv, 'w').write('\n'.join(sorted(old | new)) + '\n')
print('%s: %s (%.0fs) new blocks %d total %d' % (os.path.basename(script), res, time.time() - t0, len(new - old), len(old | new)))
unk = [l for l in m.log if l.startswith('int') or 'failed' in l]
if unk:
    print('  log:', sorted(set(unk))[:20])
