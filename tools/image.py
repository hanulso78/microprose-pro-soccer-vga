# 합친 메모리 그림: 게임 본체(EXEPACK 푼 것) + 그림 드라이버(EGAIO.EXE)
#   IMG[선형 - LOADSEG*16] 로 본다.  게임은 LOADSEG 에, 드라이버는 DRVSEG 에 올린다.
#   재배치 값은 모두 "LOADSEG 기준" 이다 -> 실제 세그먼트 = LOADSEG + 값 (SEG(x))
#   드라이버를 부르는 점프표(101a:0d40, jmp far 32 개)는 미리 채워 둔다 (게임이 실행 중 채우는 값과 같다)
#
#   SOCGAME=in  -> IN_UNP.EXE  (OPITCH.BIN, 실내 6인제)
#   SOCGAME=out -> OUT_UNP.EXE (IPITCHC.BIN, 실외 11인제)
import os, struct

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, '..'))
GAME = os.environ.get('SOCGAME', 'in')
EXE = {'in': 'IN_UNP.EXE', 'out': 'OUT_UNP.EXE'}[GAME]
DRV = os.environ.get('SOCDRV', 'EGAIO.EXE')

LOADSEG = 0x1000
PSP = LOADSEG - 0x10
DRVSEG = 0x2200             # 드라이버 자리 (int 21h 48h 가 돌려주는 값을 이것으로 맞춘다)
DRVREL = DRVSEG - LOADSEG
DRVPARAS = 0xA00


def load_mz(fn):
    d = open(fn, 'rb').read()
    h = struct.unpack('<14H', d[:28])
    size = (h[2] - 1) * 512 + h[1] if h[1] else h[2] * 512
    img = bytearray(d[h[4] * 16:size])
    rel = []
    for i in range(h[3]):
        o, s = struct.unpack('<HH', d[h[12] + 4 * i:h[12] + 4 * i + 4])
        rel.append(s * 16 + o)
    return h, img, rel


GH, GIMG, GREL = load_mz(os.path.join(ROOT, EXE))
DH, DIMG, DREL = load_mz(os.path.join(ROOT, DRV))

# 게임 코드 세그먼트 (재배치 값): 0080 = 자료(DS), 03ab = 본 코드, 101a = 시작/시스템 코드
GSEG_DATA = 0x0080
GSEG_CODE = 0x03AB
GSEG_SYS = GH[11]           # 시작 CS

IMG = bytearray(DRVREL * 16 + DRVPARAS * 16)
IMG[:len(GIMG)] = GIMG
RELOC = set(GREL)
for r in DREL:
    v = struct.unpack('<H', DIMG[r:r + 2])[0]
    DIMG[r:r + 2] = struct.pack('<H', (v + DRVREL) & 0xFFFF)
    RELOC.add(DRVREL * 16 + r)
IMG[DRVREL * 16:DRVREL * 16 + len(DIMG)] = DIMG

# 드라이버 진입표 (드라이버 첫머리 far 포인터들, FFFF:FFFF 로 끝)
DRV_API = []
k = 0
while True:
    o, s = struct.unpack('<HH', DIMG[k:k + 4])
    k += 4
    if o == 0xFFFF and s == 0xFFFF:
        break
    DRV_API.append((s, o))              # s 는 이미 DRVREL 더한 값

# 게임 쪽 점프표 채우기: 101a:0d40 부터 5 바이트씩 (ea oo oo ss ss)
JT = GSEG_SYS * 16 + 0x0D40
for n, (s, o) in enumerate(DRV_API):
    a = JT + n * 5
    assert IMG[a] == 0xEA, hex(a)
    IMG[a + 1:a + 5] = struct.pack('<HH', o, s)
    RELOC.add(a + 3)

CEND = len(IMG)


def w16(a):
    return struct.unpack('<H', IMG[a:a + 2])[0]
