# 무작위 조작 대본: python tools/mkrand.py 앞대본 시작틱 끝틱 씨앗 [2p] > 결과
#   앞대본(메뉴 고르기) 뒤에 1P(와 2P) 방향/슛 키를 무작위로 누른다
import sys, random
pre, t0, t1, seed = sys.argv[1], int(sys.argv[2]), int(sys.argv[3]), int(sys.argv[4])
two = len(sys.argv) > 5
R = random.Random(seed)
P1 = [0x11, 0x12, 0x13, 0x1f, 0x21, 0x2d, 0x2e, 0x2f]
P2 = [0x47, 0x48, 0x49, 0x4b, 0x4d, 0x4f, 0x50, 0x51]
print(open(pre, encoding='utf-8').read().rstrip())
ev = []
for keys, fire in ((P1, 0x39),) + (((P2, 0x1c),) if two else ()):
    t = t0 + R.randint(0, 20)
    while t < t1:
        k = R.choice(keys)
        d = R.randint(10, 90)
        ev.append((t, k))
        ev.append((t + d, k | 0x80))
        if R.random() < 0.35:
            ft = t + R.randint(1, d)
            ev.append((ft, fire))
            ev.append((ft + R.randint(2, 30), fire | 0x80))
        t += d + R.randint(1, 15)
used = set()
for t, k in sorted(ev):
    while (t, ) in used:
        t += 1
    used.add((t, ))
    print('%d %02x' % (t, k))
