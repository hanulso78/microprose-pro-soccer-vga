/* ============================================================================
 *  socrt.c  -  옮긴 코드의 런타임: 메모리 초기화, BIOS/DOS 흉내, 포트, 폴 지점 IRQ
 * ----------------------------------------------------------------------------
 *  tools/emu.py 와 한 동작씩 같게 한다 (같은 키 대본이면 폴마다 레지스터와 메모리가 같다).
 *
 *  시계: 원판은 PIT 를 120Hz 로 맞추고 int 8 처리기에서 게임 시계와 소리를 돌린다.
 *  옮긴 C 는 인터럽트를 아무 때나 넣을 수 없으므로 '폴 지점' (인터럽트만이 풀 수 있는
 *  대기 루프) 에서만 넣는다:  넣을 것이 없으면 틱이 하나 흐르고 (plat_tick: 도스판은
 *  여기서 실제 시간을 맞춘다) 타이머 IRQ 가 대기가 된다.  자판 스캔 코드가 있으면 먼저 int 9.
 * ========================================================================== */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "cpu.h"
#include "vga.h"
#include "plat.h"

uint8_t M[MEMSIZE];
reg16_t cpu_a, cpu_b, cpu_c, cpu_d;
uint16_t SI, DI, BP, SP, CS_, DS_, ES_, SS_;
int CF, ZF, SF, OF, DF, IF_;

uint32_t soc_ticks, soc_npoll, soc_nirq;
int soc_game;
uint8_t soc_port60;
void (*soc_poll_hook)(int irq);

#define BIOSSEG 0xF000
#define MEMTOP 0x9FFF
#define DRVPARAS 0xA00

extern const uint8_t soc_img_in[], soc_img_out[];
extern const uint32_t soc_img_in_len, soc_img_out_len;
extern const uint16_t soc_img_in_regs[4], soc_img_out_regs[4];
void soc_run_in(void);
void soc_run_out(void);

static uint16_t memfree;
static int drv_given;
static FILE *handles[32];
static int tpend, kbuf = -1;
static int nint3da;
static int pit_lohi;
static uint8_t pit_lo;
static int vmode;

static void w16(uint32_t a, uint16_t v)
{
    M[a] = (uint8_t)v;
    M[a + 1] = (uint8_t)(v >> 8);
}

static uint16_t r16(uint32_t a)
{
    return (uint16_t)(M[a] | M[a + 1] << 8);
}

void soc_init(int game, int adapter)
{
    const uint8_t *img = game ? soc_img_out : soc_img_in;
    uint32_t len = game ? soc_img_out_len : soc_img_in_len;
    const uint16_t *rg = game ? soc_img_out_regs : soc_img_in_regs;
    static const char env[] = "PATH=C:\\\0COMSPEC=C:\\COMMAND.COM\0\0\x01\0C:\\SOCCER.EXE";
    int n;
    soc_game = game;
    memset(M, 0, sizeof M);
    memcpy(M + LOADSEG * 16, img, len);
    for (n = 0; n < 256; n++) {
        w16(n * 4, (uint16_t)(n * 4));
        w16(n * 4 + 2, BIOSSEG);
        M[BIOSSEG * 16 + n * 4] = 0xCD;
        M[BIOSSEG * 16 + n * 4 + 1] = (uint8_t)n;
        M[BIOSSEG * 16 + n * 4 + 2] = 0xCF;
        M[BIOSSEG * 16 + n * 4 + 3] = 0x90;
    }
    w16(0x410, 0x0021);
    w16(0x41A, 0x1E);
    w16(0x41C, 0x1E);
    w16(0x413, 640);
    M[0x449] = 3;
    w16(0x44A, 80);
    w16(0x463, 0x3D4);
    M[0x484] = 24;
    M[0x487] = 0x60;
    M[0x488] = 0x09;
    M[0x489] = 0x11;
    M[0xFFFFE] = 0xFC;
    /* PSP, 환경, 명령 꼬리 ([80]=6, " E", SOCCER.COM 자료 far 포인터 0E00:0000) */
    M[PSPSEG * 16] = 0xCD;
    M[PSPSEG * 16 + 1] = 0x20;
    w16(PSPSEG * 16 + 2, MEMTOP + 1);
    w16(PSPSEG * 16 + 0x2C, 0x0F00);
    memcpy(M + 0xF000, env, sizeof env);
    {
        uint8_t tail[8] = {6, 0x20, (uint8_t)adapter, 0, 0, 0x00, 0x0E, 0x0D};
        memcpy(M + PSPSEG * 16 + 0x80, tail, 8);
    }
    AX = BX = CX = DX = SI = DI = BP = 0;
    CS_ = SEG(rg[0]);
    SS_ = SEG(rg[2]);
    SP = rg[3];
    DS_ = ES_ = PSPSEG;
    CF = ZF = SF = OF = DF = IF_ = 0;
    memfree = DRVSEG + DRVPARAS + 1;
    drv_given = 0;
    memset(handles, 0, sizeof handles);
    tpend = 0;
    kbuf = -1;
    nint3da = 0;
    pit_lohi = 0;
    vmode = 3;
    soc_ticks = soc_npoll = soc_nirq = 0;
    soc_port60 = 0;
    vga_reset();
}

void soc_run(void)
{
    if (soc_game)
        soc_run_out();
    else
        soc_run_in();
}

/* ---- 잘못 ---- */
void soc_fault(uint32_t at, int why)
{
    char b[120];
    static const char *what[] = {"?", "divide error", "hlt", "fell into data"};
    sprintf(b, "soccer: %s at %05X (tick %lu)", what[why & 3], (unsigned)at, (unsigned long)soc_ticks);
    plat_fatal(b);
}

uint32_t soc_unknown(uint32_t key)
{
    char b[120];
    sprintf(b, "soccer: jump to unknown %04X:%04X (tick %lu)", (unsigned)(CS_), (unsigned)(key - (uint32_t)(uint16_t)(CS_ - LOADSEG) * 16),
            (unsigned long)soc_ticks);
    plat_fatal(b);
    return 0;
}

/* ---- 폴 지점 / IRQ ---- */
static int hooked(int n)
{
    return r16(n * 4 + 2) != BIOSSEG;
}

int soc_poll(void)
{
    soc_npoll++;
    if (kbuf < 0)
        kbuf = plat_key(soc_ticks);
    if (kbuf < 0 && !tpend) {
        soc_ticks++;
        tpend = 1;
        plat_tick(soc_ticks);
        kbuf = plat_key(soc_ticks);
    }
    if (soc_poll_hook)
        soc_poll_hook(kbuf >= 0 ? 9 : tpend ? 8 : 0);
    if (kbuf >= 0) {
        int k = kbuf;
        kbuf = -1;
        if (hooked(9)) {
            soc_port60 = (uint8_t)k;
            return 9;
        }
        return 0;
    }
    if (tpend) {
        tpend = 0;
        if (hooked(8))
            return 8;
    }
    return 0;
}

uint16_t irq_enter(int n, uint16_t ret_off)
{
    PUSH((uint16_t)(0x0002 | (IF_ << 9) | (DF << 10)));
    PUSH(CS_);
    PUSH(ret_off);
    IF_ = 0;
    soc_nirq++;
    CS_ = r16(n * 4 + 2);
    return r16(n * 4);
}

void irq_leave(void)
{
}

/* ---- 포트 ---- */
void io_out(uint16_t port, uint8_t v)
{
    switch (port) {
    case 0x43:
        if ((v & 0xC0) == 0)
            pit_lohi = 0;
        plat_sound(port, v);
        return;
    case 0x40:
        if (!pit_lohi) {
            pit_lo = v;
            pit_lohi = 1;
        } else
            pit_lohi = 0;
        return;
    case 0x42:
    case 0x61:
        plat_sound(port, v);
        return;
    }
    vga_out(port, v);
}

void io_outw(uint16_t port, uint16_t v)
{
    io_out(port, (uint8_t)v);
    io_out((uint16_t)(port + 1), (uint8_t)(v >> 8));
}

uint8_t io_in(uint16_t port)
{
    switch (port) {
    case 0x60: return soc_port60;
    case 0x61: return 0;
    case 0x201: return plat_joy();
    case 0x3DA:
    case 0x3BA:
        V.atcflip = 0;
        nint3da++;
        return (nint3da & 1) ? 0x09 : 0;
    case 0x21: return 0xB8;
    }
    return 0xFF;
}

/* ---- BIOS / DOS ---- */
static void int10(void)
{
    switch (AH) {
    case 0x00:
        vmode = AL & 0x7F;
        M[0x449] = (uint8_t)vmode;
        vga_setmode(AL);
        plat_mode(vmode);
        break;
    case 0x0F:
        AX = (uint16_t)(0x2800 | vmode);
        BX = 0;
        break;
    case 0x12:
        BX = 0x0003;
        CX = 0x0009;
        break;
    case 0x1A:
        AX = 0;
        break;
    case 0x10:
        if (AL == 0)
            V.atc[BX & 15] = BH;
        else if (AL == 2)
            memcpy(V.atc, M + LIN(ES_, DX), 16);
        V.palgen++;
        break;
    }
}

static void get_path2(uint16_t s, uint16_t o, char *out, const char *dir)
{
    char name[80];
    int n = 0;
    const char *p;
    while (n < 79 && M[LIN(s, (uint16_t)(o + n))]) {
        name[n] = (char)M[LIN(s, (uint16_t)(o + n))];
        n++;
    }
    name[n] = 0;
    p = strrchr(name, '\\');
    p = p ? p + 1 : name;
    sprintf(out, "%s%s", dir, p);
}

static int new_handle(FILE *f)
{
    int h;
    for (h = 5; h < 32 && handles[h]; h++)
        ;
    if (h >= 32) {
        fclose(f);
        return -1;
    }
    handles[h] = f;
    return h;
}

static void int21(void)
{
    int ok = 1;
    switch (AH) {
    case 0x25:
        w16(AL * 4, DX);
        w16(AL * 4 + 2, DS_);
        break;
    case 0x35:
        BX = r16(AL * 4);
        ES_ = r16(AL * 4 + 2);
        break;
    case 0x4A:
    case 0x49:
        break;
    case 0x48:
        if (BX == DRVPARAS && !drv_given) {
            drv_given = 1;
            AX = DRVSEG;
        } else {
            uint16_t seg = (uint16_t)(memfree + 1);
            if ((uint32_t)seg + BX > MEMTOP) {
                BX = (uint16_t)(MEMTOP > seg ? MEMTOP - seg : 0);
                AX = 8;
                ok = 0;
            } else {
                memfree = (uint16_t)(memfree + BX + 1);
                AX = seg;
            }
        }
        break;
    case 0x4B:
        /* AL=3 오버레이 (?GAIO.EXE): 이미 그림에 올려 두었다 */
        if (AL != 3 || r16(LIN(ES_, BX)) != DRVSEG)
            plat_fatal("soccer: unexpected exec");
        break;
    case 0x3C:                  /* 만들기 (컨트롤 패널 SAVE - DISK) -> 저장 폴더 */
    case 0x3D: {                /* 열기: 쓰기면 저장 폴더, 읽기면 저장 폴더 다음 자료 폴더 */
        char path[300];
        FILE *f;
        int h = -1;
        get_path2(DS_, DX, path, plat_savedir);
        if (AH == 0x3C)
            f = fopen(path, "w+b");
        else if (AL & 3) {
            /* 쓰기로 열기: 저장 폴더에 없으면 자료 폴더 것을 복사해 둔다 (원본은 그대로) */
            if (!(f = fopen(path, "r+b")) && strcmp(plat_savedir, plat_datadir)) {
                char src[300];
                FILE *g;
                get_path2(DS_, DX, src, plat_datadir);
                if ((g = fopen(src, "rb")) != 0) {
                    FILE *o = fopen(path, "wb");
                    int c;
                    if (o) {
                        while ((c = fgetc(g)) != EOF)
                            fputc(c, o);
                        fclose(o);
                    }
                    fclose(g);
                    f = fopen(path, "r+b");
                }
            }
        }
        else if (!(f = fopen(path, "rb"))) {
            get_path2(DS_, DX, path, plat_datadir);
            f = fopen(path, "rb");
        }
        if (f)
            h = new_handle(f);
        if (h < 0) {
            AX = 2;
            ok = 0;
        } else
            AX = (uint16_t)h;
        break;
    }
    case 0x40:
        if (BX < 32 && handles[BX]) {
            fseek(handles[BX], 0, SEEK_CUR);
            AX = (uint16_t)fwrite(M + LIN(DS_, DX), 1, CX, handles[BX]);
            fflush(handles[BX]);
        } else {
            AX = 6;
            ok = 0;
        }
        break;
    case 0x3E:
        if (BX < 32 && handles[BX]) {
            fclose(handles[BX]);
            handles[BX] = 0;
        }
        break;
    case 0x3F:
        if (BX < 32 && handles[BX]) {
            uint32_t a = LIN(DS_, DX);
            fseek(handles[BX], 0, SEEK_CUR);          /* 읽기/쓰기 바꿀 때 */
            AX = (uint16_t)fread(M + a, 1, CX, handles[BX]);
        } else {
            AX = 6;
            ok = 0;
        }
        break;
    case 0x42:
        if (BX < 32 && handles[BX]) {
            long off = (long)((uint32_t)CX << 16 | DX);
            long p;
            fseek(handles[BX], off, AL == 0 ? SEEK_SET : AL == 1 ? SEEK_CUR : SEEK_END);
            p = ftell(handles[BX]);
            AX = (uint16_t)p;
            DX = (uint16_t)(p >> 16);
        } else {
            AX = 6;
            ok = 0;
        }
        break;
    case 0x4C:
        plat_exit(AL);
        break;
    case 0x30:
        AX = 5;
        break;
    }
    CF = !ok;
}

void do_int(int n)
{
    switch (n) {
    case 0x10: int10(); break;
    case 0x11: AX = 0x21; break;
    case 0x16:
        if (AH == 0)
            AX = 0x1C0D;
        else
            ZF = 1;
        break;
    case 0x21: int21(); break;
    }
}
