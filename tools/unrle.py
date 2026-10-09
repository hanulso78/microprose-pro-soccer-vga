# 드라이버가 읽는 RLE 파일 풀기: [길이 2][탈출 1] 다음 바이트들 (탈출, 값, 개수)
import sys, os
def unrle(d):
    n = d[0] | d[1] << 8
    esc = d[2]
    out = bytearray()
    i = 3
    while len(out) < n and i < len(d):
        b = d[i]; i += 1
        if b == esc:
            v = d[i]; c = d[i + 1]; i += 2
            out += bytes([v]) * c
        else:
            out.append(b)
    return bytes(out)
if __name__ == '__main__':
    for f in sys.argv[1:]:
        d = open(f, 'rb').read()
        if d[:2] == b'MZ':
            continue
        u = unrle(d)
        open(os.path.join('unpacked', os.path.basename(f)), 'wb').write(u)
        print(f, len(d), '->', len(u), 'hdr', d[:4].hex())
