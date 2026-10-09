# 원숭이 대본: 메뉴 키와 조작 키를 무작위로 (메뉴 여기저기, 경기, 이름 넣기까지 두루 다니게)
#   python tools/monkey.py 씨앗 끝틱 [시작대본] > 대본
import sys, random
seed, t1 = int(sys.argv[1]), int(sys.argv[2])
R = random.Random(seed)
out = []
t = 400
if len(sys.argv) > 3:
    for ln in open(sys.argv[3], encoding='utf-8'):
        if ln.split('#')[0].strip():
            out.append(ln.split('#')[0].strip())
            t = max(t, int(ln.split()[0]) + 40)
else:
    out.append('400 +enter')           # 조이스틱 0
    t = 460
MENU = [0x48, 0x50, 0x4B, 0x4D, 0x1C, 0x39]
GAME1 = [0x11, 0x12, 0x13, 0x1f, 0x21, 0x2d, 0x2e, 0x2f]
GAME2 = [0x47, 0x48, 0x49, 0x4b, 0x4d, 0x4f, 0x50, 0x51]
LETTERS = list(range(0x10, 0x1a)) + list(range(0x1e, 0x27)) + list(range(0x2c, 0x33)) + list(range(0x02, 0x0c)) + [0x0e, 0x19]
ev = []
while t < t1:
    r = R.random()
    if r < 0.35:
        k = R.choice(MENU); d = R.randint(4, 12); gap = R.randint(15, 70)
    elif r < 0.75:
        k = R.choice(GAME1 + GAME2); d = R.randint(10, 90); gap = R.randint(1, 20)
    elif r < 0.9:
        k = R.choice([0x39, 0x1c, 0x2a, 0x36]); d = R.randint(2, 30); gap = R.randint(5, 40)
    else:
        k = R.choice(LETTERS); d = R.randint(3, 10); gap = R.randint(10, 40)
    ev.append((t, k)); ev.append((t + d, k | 0x80))
    t += gap
used = set()
for x in out:
    used.add(int(x.split()[0]))
for tt, k in sorted(ev):
    while tt in used:
        tt += 1
    used.add(tt)
    out.append('%d %02x' % (tt, k))
print('\n'.join(out))
