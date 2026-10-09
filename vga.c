/* ============================================================================
 *  vga.c  -  EGA 평면 메모리 흉내
 * ----------------------------------------------------------------------------
 *  원판 그림 드라이버(EGAIO.EXE)는 모드 0Dh (320x200 16색, 줄 40 바이트) 에서 그래픽
 *  제어기(3CEh)와 시퀀서(3C4h)를 직접 다룬다: 쓰기 방식 0/1/2, 비트마스크, 래치 복사.
 *  tools/emu.py 의 VGA 클래스와 한 동작씩 같다.  화면에 내보내는 일은 플랫폼 몫이다.
 *
 *  네 평면을 32비트 낱말 하나에 섞어 둔다 (바이트 p = 평면 p).  레지스터 값은 바뀔 때
 *  32비트 가면으로 미리 풀어 둔다 (지도 가면, 비트마스크, set/reset).
 * ========================================================================== */
#include <string.h>
#include "cpu.h"
#include "vga.h"
#ifdef SOCVGA
#include "socvga.h"
#define latch_off V.latch_off
#endif
#ifdef SOCDBG
uint8_t vkind[0x10000 * 8];     /* 시험판: 점마다 그린 문맥 종류 */
extern int socvga_kind(void);
#endif

vga_t V;
unsigned long vga_nrb, vga_nwb;
uint32_t vga_spread[256][2];
uint32_t vga_sp4[4][256][2], vga_sp8[4][256][2];
static uint32_t lanes4[16];     /* 4 비트 -> 평면마다 0x00/0xFF */

static void recalc(void)
{
    V.mm32 = lanes4[V.seq[2] & 15];
    V.bm32 = V.gc[8] * 0x01010101u;
    V.sr32 = lanes4[V.gc[0] & 15];
    V.esr32 = lanes4[V.gc[1] & 15];
    V.wmode = V.gc[5] & 3;
    V.rmode = (V.gc[5] >> 3) & 1;
    V.fn = (V.gc[3] >> 3) & 3;
    V.rot = V.gc[3] & 7;
    V.rmap = V.gc[4] & 3;
    V.fastw = V.wmode == 1 ? 1 :
              (V.wmode == 0 && V.fn == 0 && V.rot == 0 && (V.gc[1] & 15) == 0 && V.gc[8] == 0xFF) ? 2 : 0;
}

void vga_reset(void)
{
    int i, b, k;
    memset(&V, 0, sizeof V);
    for (i = 0; i < 16; i++)
        lanes4[i] = (i & 1 ? 0xFFu : 0) | (i & 2 ? 0xFF00u : 0) | (i & 4 ? 0xFF0000u : 0) | (i & 8 ? 0xFF000000u : 0);
    memset(vga_spread, 0, sizeof vga_spread);
    for (b = 0; b < 256; b++)
        for (k = 0; k < 8; k++)
            if (b >> (7 - k) & 1)
                vga_spread[b][k >> 2] |= 1u << ((k & 3) * 8);
    for (i = 0; i < 4; i++)
        for (b = 0; b < 256; b++)
            for (k = 0; k < 2; k++) {
                vga_sp4[i][b][k] = vga_spread[b][k] << i;
                vga_sp8[i][b][k] = vga_spread[b][k] << (i + 4);
            }
    V.seq[2] = 0xF;
    V.gc[8] = 0xFF;
    for (i = 0; i < 16; i++)
        V.atc[i] = (uint8_t)i;
    V.mode = 3;
    recalc();
}

void vga_setmode(int mode)
{
    static const uint8_t ATC0[16] = {0, 1, 2, 3, 4, 5, 20, 7, 56, 57, 58, 59, 60, 61, 62, 63};
    static const uint8_t ATCD[16] = {0, 1, 2, 3, 4, 5, 6, 7, 16, 17, 18, 19, 20, 21, 22, 23};
    V.mode = mode & 0x7F;
    memset(V.vp, 0, sizeof V.vp);
    memcpy(V.atc, V.mode == 0xD ? ATCD : ATC0, 16);
    V.crtc[0xC] = V.crtc[0xD] = 0;
    V.gen++;
    V.palgen++;
}

#ifdef SOCDBG
unsigned long vga_wbk[16], vga_rbk[16];
extern int socvga_kind(void);
#endif

uint8_t vga_rb(uint32_t off)
{
    uint32_t la = V.vp[off];
#ifdef VGACOUNT
    vga_nrb++;
#endif
#ifdef SOCDBG
    vga_rbk[socvga_kind() & 15]++;
#endif
    V.latch = la;
#ifdef SOCVGA
    latch_off = off;
#endif
    if (V.rmode) {              /* 읽기 방식 1: 색 비교 */
        uint8_t cc = V.gc[2], dc = V.gc[7], r = 0xFF;
        int p;
        for (p = 0; p < 4; p++)
            if (dc >> p & 1) {
                uint8_t lp = (uint8_t)(la >> (p * 8));
                r &= (uint8_t)((cc >> p & 1) ? lp : ~lp);
            }
        return r;
    }
    return (uint8_t)(la >> (V.rmap * 8));
}

uint32_t vga_oldw;
#ifdef SOCDBG
unsigned long vga_wbk[16], vga_rbk[16];
extern int socvga_kind(void);
#endif              /* 256색: 이번 쓰기 전의 평면 낱말 (그림자가 아래 색을 보려고) */

void vga_wb(uint32_t off, uint8_t v)
{
    uint32_t la = V.latch, d, mm = V.mm32, bm = V.bm32, old = V.vp[off];
#ifdef SOCVGA
    uint8_t aff = 0;            /* 이 쓰기가 건드린 점 (왼쪽 점 = 0x80) */
#endif
#ifdef VGACOUNT
    vga_nwb++;
#endif
    V.gen++;
#ifdef SOCDBG
    vga_wbk[socvga_kind() & 15]++;
#endif
    if (V.fastw == 2) {         /* 흔한 경우: 방식 0 단순 쓰기 */
        V.vp[off] = (old & ~mm) | (v * 0x01010101u & mm);
#ifdef SOCVGA
        if (socvga_on && mm) {
            uint32_t x = old ^ V.vp[off];
            vga_oldw = old;
            socvga_shade8(off, 0xFF, (uint8_t)(x | x >> 8 | x >> 16 | x >> 24));
        }
#endif
        return;
    }
    if (V.wmode == 1) {
        V.vp[off] = (old & ~mm) | (la & mm);
#ifdef SOCVGA
        if (socvga_on && mm) {
            { uint32_t *q_ = (uint32_t *)(vsh + off * 8); const uint32_t *r_ = (const uint32_t *)(vsh + latch_off * 8); q_[0] = r_[0]; q_[1] = r_[1]; }
#ifdef SOCDBG
            memcpy(vkind + off * 8, vkind + latch_off * 8, 8);
#endif
        }
#endif
        return;
    }
    if (V.rot)
        v = (uint8_t)((v >> V.rot) | (v << (8 - V.rot)));
    if (V.wmode == 0)
        d = (v * 0x01010101u & ~V.esr32) | (V.sr32 & V.esr32);
    else if (V.wmode == 2)
        d = lanes4[v & 15];
    else {                      /* 방식 3 */
        uint32_t bm2 = bm & v * 0x01010101u, res = (V.sr32 & bm2) | (la & ~bm2);
        V.vp[off] = (old & ~mm) | (res & mm);
#ifdef SOCVGA
        aff = mm ? (uint8_t)(bm2 & 0xFF) : 0;
        goto shade;
#else
        return;
#endif
    }
#ifdef SOCVGA
    if (mm) {
        uint32_t dm = d & mm, dn = ~d & mm;
        uint8_t orv = (uint8_t)(dm | dm >> 8 | dm >> 16 | dm >> 24);
        uint8_t andn = (uint8_t)(dn | dn >> 8 | dn >> 16 | dn >> 24);
        uint8_t b8 = (uint8_t)bm;
        aff = (uint8_t)(V.fn == 0 ? b8 : V.fn == 1 ? (b8 & andn) : (b8 & orv));
    }
#endif
    if (V.fn == 1)
        d &= la;
    else if (V.fn == 2)
        d |= la;
    else if (V.fn == 3)
        d ^= la;
    d = (d & bm) | (la & ~bm);
    V.vp[off] = (old & ~mm) | (d & mm);
#ifdef SOCVGA
shade:
    if (socvga_on && aff) {
        uint32_t x = old ^ V.vp[off];
        vga_oldw = old;
        socvga_shade8(off, aff, (uint8_t)(x | x >> 8 | x >> 16 | x >> 24));
    }
#endif
}

void vga_out(uint16_t port, uint8_t v)
{
    switch (port) {
    case 0x3C4: V.seqi = v & 7; break;
    case 0x3C5: V.seq[V.seqi] = v; recalc(); break;
    case 0x3CE: V.gci = v & 15; break;
    case 0x3CF: if (V.gci < 9) { V.gc[V.gci] = v; recalc(); } break;
    case 0x3D4: V.crtci = v & 31; break;
    case 0x3D5: V.crtc[V.crtci] = v; break;
    case 0x3C0:
        if (!V.atcflip) {
            V.atci = v & 0x3F;
            V.atcflip = 1;
        } else {
            if ((V.atci & 0x1F) == 0x13) {
                V.pan = v & 7;
                V.npan++;
            } else if (V.atci < 16) {
                V.atc[V.atci] = v & 0x3F;
                V.palgen++;
            }
            V.atcflip = 0;
        }
        break;
    }
}

uint32_t vga_start(void)
{
    return (uint32_t)V.crtc[0xC] << 8 | V.crtc[0xD];
}

/* 가로 미세 스크롤 (속성 레지스터 13h): 줄마다 41 바이트를 풀어 pan 점만큼 왼쪽으로 민다.
 * 실외 게임은 두 쪽을 번갈아 보이며 쪽마다 pan 을 바꾼다 (안 따르면 배경이 선수보다 0..7 점 뒤처져 보인다).
 * 실외 경기는 CRTC 1 (가로 표시 끝) 을 25h 로 줄여 38 바이트 (304 점) 만 보인다: 왼쪽 8 점은 검은 칸,
 * 오른쪽은 새 타일을 미리 그리는 숨은 칸.  그대로 보이면 좌우에 검은 띠가 생기므로 경기장 (0..175 줄) 은
 * 쓸 수 있는 296 점을 320 점으로 가로로 늘리고, 점수판 (176 줄 ~) 은 늘리지 않고 가운데로 (바탕이 검정) */
static int16_t run_d[64], run_s[64], run_n[64];      /* 늘이기: 이어진 토막 (dst, src, 길이) */
static int nrun;

void vga_line_map(const uint8_t *line, uint8_t *dst, int y, int pan)
{
    int x;
    if (V.crtc[1] != 0x25) {
        memcpy(dst, line + pan, 320);
        return;
    }
    if (!nrun) {                /* 점 x <- 8 + x * 296 / 320: 원본이 1 씩 느는 동안을 한 토막으로 */
        int prev = -2;
        for (x = 0; x < 320; x++) {
            int sx = 8 + x * 296 / 320;
            if (sx == prev + 1 && nrun)
                run_n[nrun - 1]++;
            else {
                run_d[nrun] = (int16_t)x;
                run_s[nrun] = (int16_t)sx;
                run_n[nrun++] = 1;
            }
            prev = sx;
        }
    }
    if (y < 176) {
        const uint8_t *l = line + pan;
        int r;
        for (r = 0; r < nrun; r++)
            memcpy(dst + run_d[r], l + run_s[r], (size_t)run_n[r]);
    } else {
        memset(dst, line[pan], 4);
        memcpy(dst + 4, line + pan, 316);
    }
}

void vga_frame(uint32_t start, uint8_t *dst)
{
    int y, xb, pan = V.pan & 7, full = pan || V.crtc[1] == 0x25;
    uint32_t line[41 * 2];
    for (y = 0; y < 200; y++) {
        uint32_t *d = full ? line : (uint32_t *)(dst + y * 320);
        int nb = full ? 41 : 40;
        for (xb = 0; xb < nb; xb++) {
            uint32_t w = V.vp[(start + (uint32_t)y * 40 + xb) & 0xFFFF];
            const uint32_t *s0 = vga_sp4[0][w & 0xFF], *s1 = vga_sp4[1][(w >> 8) & 0xFF];
            const uint32_t *s2 = vga_sp4[2][(w >> 16) & 0xFF], *s3 = vga_sp4[3][w >> 24];
            d[0] = s0[0] | s1[0] | s2[0] | s3[0];
            d[1] = s0[1] | s1[1] | s2[1] | s3[1];
            d += 2;
        }
        if (full)
            vga_line_map((uint8_t *)line, dst + y * 320, y, pan);
    }
}

void vga_plane(int p, uint8_t *dst)
{
    uint32_t i;
    for (i = 0; i < 0x10000; i++)
        dst[i] = PL(p, i);
}

void ega_rgb(int c, uint8_t *rgb)
{
    int r = ((c >> 2) & 1) * 2 + ((c >> 5) & 1);
    int g = ((c >> 1) & 1) * 2 + ((c >> 4) & 1);
    int b = (c & 1) * 2 + ((c >> 3) & 1);
    rgb[0] = (uint8_t)(r * 85);
    rgb[1] = (uint8_t)(g * 85);
    rgb[2] = (uint8_t)(b * 85);
}

/* 지도 가면 레지스터 (3C5, 색인 2) 에 쓴 것과 같게 (socfast.c) */
void vga_seq_mapmask(uint8_t v)
{
    V.seq[2] = v;
    recalc();
}
