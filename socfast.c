/* ============================================================================
 *  socfast.c  -  드라이버의 뜨거운 반복 덩어리를 C 로 한꺼번에 (486 에서 제 빠르기로)
 * ----------------------------------------------------------------------------
 *  번역기(tools/asm2c.py)가 덩어리 첫 명령에서 fast_xxx() 를 부른다.  조건이 맞으면
 *  원판과 똑같은 결과(레지스터, 메모리, EGA 평면, 래치, 플래그)를 내고 덩어리 다음 주소
 *  (dispatch 열쇠)를 돌려준다.  안 맞으면 0 -> 원래 번역 코드가 한 명령씩 돈다.
 *  에뮬레이터 대조(tools/difftest.py)로 바이트 단위로 같은지 확인한다.
 *
 *  fast_tile   경기장 타일 한 칸: mov si,[bx] / add bx,2 / 평면 1,2,4,8 마다 movsb 8 줄
 *  fast_scroll 스크롤 래치 복사 (1209:082c, jmp bx 로 movsb 목록 한가운데로 뛰는 되돌이)
 *  fast_spr3   스프라이트 줄 (mov al,es:[di] / movsb 세 번 / add di,cx) 21 줄
 * ========================================================================== */
#include <string.h>
#include "cpu.h"
#include "vga.h"
#ifdef SOCVGA
#include "socvga.h"
#endif

static int video(uint16_t seg)
{
    return seg >= 0xA000 && seg < 0xB000;
}

/* sub r16, imm 의 플래그 */
static void flags_sub16(uint16_t a, uint16_t b)
{
    unsigned r = (unsigned)a - b;
    CF = (r >> 16) & 1;
    ZF = (uint16_t)r == 0;
    SF = (r >> 15) & 1;
    OF = (((a ^ b) & (a ^ r)) >> 15) & 1;
}

static void flags_add16(uint16_t a, uint16_t b)
{
    unsigned r = (unsigned)a + b;
    CF = r > 0xFFFF;
    ZF = (uint16_t)r == 0;
    SF = (r >> 15) & 1;
    OF = (((a ^ r) & (b ^ r)) >> 15) & 1;
}

extern void vga_seq_mapmask(uint8_t v);

/* 경기장 타일 한 칸 (after = 덩어리 다음 선형 주소) */
uint32_t fast_tile(uint32_t after)
{
    uint32_t src, dst0;
    uint16_t si;
    int r;
    if (DX != 0x3C5 || V.seqi != 2 || BP != 0x27 || DF || !video(ES_) || video(DS_) || V.wmode != 0 ||
        V.fn != 0 || V.rot != 0 || (V.gc[1] & 15) || V.gc[8] != 0xFF)
        return 0;
    if ((uint32_t)DI + 7 * 40 + 1 > 0x10000u)
        return 0;
    si = RW(DS_, BX);
    src = LIN(DS_, si);
    if ((uint16_t)(si + 31) < si)
        return 0;
    dst0 = LIN(ES_, DI) - 0xA0000u;
    for (r = 0; r < 8; r++) {
        uint32_t off = (dst0 + (uint32_t)r * 40) & 0xFFFF;
        V.vp[off] = (uint32_t)M[src + r] | (uint32_t)M[src + 8 + r] << 8 | (uint32_t)M[src + 16 + r] << 16 |
                    (uint32_t)M[src + 24 + r] << 24;
#ifdef SOCVGA
        if (socvga_on)
            socvga_shade8(off, 0xFF, 0xFF);
#endif
    }
    V.gen++;
    BX += 2;
    SI = (uint16_t)(si + 32);
    AL = 8;
    vga_seq_mapmask(8);
    flags_sub16((uint16_t)(DI + 0x119), 0x118);        /* 마지막 sub di, 0x118 */
    DI = (uint16_t)(DI + 1);
    return after;
}

/* 스크롤 래치 복사: 1209:082c jmp bx.  bx = 082e + (28 - bp) -> movsb bp 번, add si,ax, add di,ax, loop */
uint32_t fast_scroll(uint32_t after)
{
    unsigned n = BP, rows = CX, k;
    uint32_t mm = V.mm32;
    if (BX != (uint16_t)(0x82e + 0x28 - BP) || n > 38 || !rows || DF || V.wmode != 1 || !video(ES_) || !video(DS_))
        return 0;
    for (; rows; rows--) {
        uint32_t s = LIN(DS_, SI) - 0xA0000u, d = LIN(ES_, DI) - 0xA0000u;
        if ((uint32_t)SI + n > 0x10000u || (uint32_t)DI + n > 0x10000u)
            return 0;           /* (처음 줄에서만 일어날 수 있다: 그때는 아직 아무것도 안 했다) */
        for (k = 0; k < n; k++) {
            uint32_t la = V.vp[s + k];
            V.vp[d + k] = (V.vp[d + k] & ~mm) | (la & mm);
#ifdef SOCVGA
            if (socvga_on && mm)
                { uint32_t *q_ = (uint32_t *)(vsh + (d + k) * 8); const uint32_t *r_ = (const uint32_t *)(vsh + (s + k) * 8); q_[0] = r_[0]; q_[1] = r_[1]; }
#endif
#ifdef SOCDBG
            { extern uint8_t vkind[]; memcpy(vkind + (d + k) * 8, vkind + (s + k) * 8, 8); }
#endif
        }
        if (n) {
            V.latch = V.vp[s + n - 1];
#ifdef SOCVGA
            V.latch_off = s + n - 1;
#endif
        }
        SI = (uint16_t)(SI + n);
        DI = (uint16_t)(DI + n);
        flags_add16(SI, AX);
        SI = (uint16_t)(SI + AX);
        flags_add16(DI, AX);
        DI = (uint16_t)(DI + AX);
    }
    V.gen++;
    CX = 0;
    return after;
}

/* 스프라이트 21 줄: (mov al,es:[di] / movsb) x3 / add di,cx  ... 마지막 줄 뒤 sub di,0x323 / ret
 *  after = ret 의 자리 (그대로 돌아가게) */
#ifdef SOCDBG
unsigned long fspr_n[4];
#endif
uint32_t fast_spr3(uint32_t after)
{
    int r, k;
    if (DF || !video(ES_) || video(DS_) || CX != 0x25)
        return 0;
    if ((uint32_t)DI + 20 * 40 + 3 > 0x10000u || (uint32_t)SI + 63 > 0x10000u)
        return 0;
    /* 486 속도: 쓰기 방식 0, set-reset 없음이면 줄 21 x 3 바이트를 함수 부름 없이.  드라이버는 회전 (점 단위
     * 밀기) 과 비트마스크 (반 바이트씩), 읽기 방식 1 (색 비교: 래치만 채우고 AL 은 마지막 것) 을 쓴다.
     * 결과는 vga_rb / vga_wb 를 부른 것과 같다 (tools/difftest.py 로 대조) */
#ifdef SOCDBG
    {
        extern unsigned long fspr_n[4];
        fspr_n[V.wmode == 0 && V.esr32 == 0]++;
    }
#endif
    if (V.wmode == 0 && V.esr32 == 0) {
        uint32_t mm = V.mm32, bm = V.bm32, off = 0, la = 0;
        uint32_t base = LIN(ES_, DI) - 0xA0000u, src = LIN(DS_, SI);
        int fn = V.fn, rot = V.rot;
        uint8_t b8 = (uint8_t)bm;
        for (r = 0; r < 21; r++) {
            for (k = 0; k < 3; k++) {
                uint32_t old, d;
                uint8_t v = M[src + r * 3 + k];
                off = (base + (uint32_t)r * 0x28 + (uint32_t)k) & 0xFFFF;
                old = la = V.vp[off];
                if (rot)
                    v = (uint8_t)((v >> rot) | (v << (8 - rot)));
                d = v * 0x01010101u;
#ifdef SOCVGA
                {
                    uint32_t dm = d & mm, dn = ~d & mm;
                    uint8_t aff = mm ? (uint8_t)(fn == 0 ? b8 : fn == 1 ? (b8 & (uint8_t)(dn | dn >> 8 | dn >> 16 | dn >> 24))
                                                                       : (b8 & (uint8_t)(dm | dm >> 8 | dm >> 16 | dm >> 24)))
                                     : 0;
#endif
                    if (fn == 1)
                        d &= la;
                    else if (fn == 2)
                        d |= la;
                    else if (fn == 3)
                        d ^= la;
                    d = (d & bm) | (la & ~bm);
                    V.vp[off] = (old & ~mm) | (d & mm);
#ifdef SOCVGA
                    if (socvga_on && aff) {
                        uint32_t x = old ^ V.vp[off];
                        vga_movs = 1;
                        vga_oldw = old;
                        socvga_shade8(off, aff, (uint8_t)(x | x >> 8 | x >> 16 | x >> 24));
                        vga_movs = 0;
                    }
                }
#endif
            }
        }
        V.gen += 63;
        V.latch = la;
#ifdef SOCVGA
        V.latch_off = off;
#endif
        if (V.rmode) {          /* 읽기 방식 1: 색 비교 (vga_rb 와 같게) */
            uint8_t cc = V.gc[2], dc = V.gc[7], rr = 0xFF;
            int p;
            for (p = 0; p < 4; p++)
                if (dc >> p & 1) {
                    uint8_t lp = (uint8_t)(la >> (p * 8));
                    rr &= (uint8_t)((cc >> p & 1) ? lp : ~lp);
                }
            AL = rr;
        } else
            AL = (uint8_t)(la >> (V.rmap * 8));
        SI = (uint16_t)(SI + 63);
        DI = (uint16_t)(DI + 20 * CX + 3 * 21);
        flags_sub16(DI, 0x323);
        DI = (uint16_t)(DI - 0x323);
        return after;
    }
    for (r = 0; r < 21; r++) {
        for (k = 0; k < 3; k++) {
            AL = VRB(LIN(ES_, DI) - 0xA0000u);
#ifdef SOCVGA
            vga_movs = 1;
#endif
            VWB(LIN(ES_, DI) - 0xA0000u, M[LIN(DS_, SI)]);
#ifdef SOCVGA
            vga_movs = 0;
#endif
            SI++;
            DI++;
        }
        if (r < 20)
            DI = (uint16_t)(DI + CX);
    }
    flags_sub16(DI, 0x323);
    DI = (uint16_t)(DI - 0x323);
    return after;
}
