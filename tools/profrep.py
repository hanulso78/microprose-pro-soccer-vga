import re, collections
L = open('_lines.txt').read().split('\n')
funcs = collections.Counter(); lines = collections.Counter()
for i in range(0, len(L) - 1, 2):
    funcs[L[i]] += 1; lines[L[i + 1]] += 1
tot = sum(funcs.values())
print('samples', tot)
for f, n in funcs.most_common(14):
    print('%5.1f%% %s' % (100 * n / tot, f))
src = open('soc_in.c', encoding='utf-8').read().split('\n')
acc = collections.Counter()
for l, n in lines.items():
    m = re.search(r'soc_in\.c:(\d+)', l)
    if not m:
        continue
    ln = int(m.group(1)) - 1
    c = None
    for k in range(ln, min(ln + 3, len(src))):
        c = re.search(r'/\* ([0-9a-f]{4}:[0-9a-f]{4})', src[k])
        if c:
            break
    acc[c.group(1)[:7] if c else '?'] += n
print('--- soc_in.c by 16-byte region')
for a, n in acc.most_common(20):
    print('%5.1f%% %s' % (100 * n / tot, a))
