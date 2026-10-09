# MS EXEPACK 풀기: 눌린 MZ -> 재배치 복원된 일반 MZ (16/18 바이트 머리 둘 다)
import struct, sys

def unpack(d):
    h = list(struct.unpack('<14H', d[:28]))
    hdr = h[4] * 16
    img = bytearray(d[hdr:])
    cs = h[11]
    eo = cs * 16
    ip, rcs, mem, esz, sp, ss, dlen = struct.unpack('<7H', img[eo:eo + 14])
    sig = img[eo + 14:eo + 16]
    skip = 1
    if sig != b'RB':            # 18 바이트 머리 (skip_len 있음)
        skip = struct.unpack('<H', img[eo + 14:eo + 16])[0]
        sig = img[eo + 16:eo + 18]
    assert sig == b'RB', sig
    pk = bytearray(img[:eo - (skip - 1) * 16])
    out = bytearray(dlen * 16)
    out[:len(pk)] = pk
    src = len(pk) - 1
    while pk[src] == 0xff:
        src -= 1
    dst = dlen * 16 - 1
    while True:
        op = out[src]; src -= 1
        cnt = out[src] << 8 | out[src - 1]; src -= 2
        if op & 0xfe == 0xb0:
            b = out[src]; src -= 1
            for _ in range(cnt):
                out[dst] = b; dst -= 1
        elif op & 0xfe == 0xb2:
            for _ in range(cnt):
                out[dst] = out[src]; dst -= 1; src -= 1
        else:
            raise Exception('bad op %x' % op)
        if op & 1:
            break
    # 재배치 표: "Packed file is corrupt" 뒤
    k = img.find(b'Packed file is corrupt', eo) + 22
    rel = []
    for sec in range(16):
        n = struct.unpack('<H', img[k:k + 2])[0]; k += 2
        for i in range(n):
            o = struct.unpack('<H', img[k:k + 2])[0]; k += 2
            rel.append((o, sec * 0x1000))
    # 새 MZ 작성
    nh = 0x20 + ((len(rel) * 4 + 15) // 16) * 16
    hsz = nh
    total = hsz + len(out)
    mz = struct.pack('<14H', 0x5a4d, total % 512, (total + 511) // 512, len(rel),
                     hsz // 16, h[5], h[6], ss, sp, 0, ip, rcs, 0x20, 0)
    mz += b'\0' * 4
    body = b''.join(struct.pack('<HH', o, s) for o, s in rel)
    head = (mz + body).ljust(hsz, b'\0')
    return head + bytes(out), rel, (rcs, ip, ss, sp)

if __name__ == '__main__':
    d = open(sys.argv[1], 'rb').read()
    o, rel, regs = unpack(d)
    open(sys.argv[2], 'wb').write(o)
    print('relocs', len(rel), 'CS:IP %04x:%04x SS:SP %04x:%04x' % regs, 'size', len(o))
