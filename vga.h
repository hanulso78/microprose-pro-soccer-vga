/* vga.h - EGA 평면 메모리 흉내 (원판 드라이버 EGAIO 가 A000 과 3C4/3CE/3D4/3C0 을 직접 다룬다)
 *
 *  빠르게 하려고 네 평면을 한 32비트 낱말에 섞어 둔다: vp[off] 의 바이트 p = 평면 p.
 *  래치 읽기/쓰기, 쓰기 방식 0/1/2 가 모두 32비트 연산 몇 번이다 (486 에서도 가볍게).
 */
#ifndef VGA_H
#define VGA_H

#include <stdint.h>

typedef struct {
    uint32_t vp[0x10000];       /* 평면 0..3 을 섞은 것 */
    uint32_t latch;
    uint8_t seq[8], gc[9];
    uint8_t seqi, gci;
    uint8_t crtc[32], crtci;    /* CRTC (0C/0D = 화면 시작 주소) */
    uint8_t atc[16], atci, atcflip;     /* 팔레트: EGA 64 색 번호 (rgbRGB) */
    int mode;
    uint32_t gen;               /* 평면 메모리가 바뀔 때마다 는다 */
    uint32_t palgen;            /* ATC 가 바뀔 때마다 */
    /* 레지스터에서 미리 푼 값 (vga_out 이 고친다) */
    uint32_t mm32, bm32, sr32, esr32;
    int wmode, fn, rot, rmode, rmap;
    int fastw;                  /* 1: 쓰기 방식 1 (래치 복사), 2: 방식 0 단순 (함수 0, 회전/set-reset 없음, 비트마스크 FF) */
    uint32_t latch_off;
    uint8_t pan;                /* 속성 레지스터 13h: 가로 미세 스크롤 (0..7 점) */
    uint32_t npan;              /* 13h 를 쓴 횟수 (시험용) */
} vga_t;

extern vga_t V;
extern uint32_t vga_oldw;
void vga_line_map(const uint8_t *line, uint8_t *dst, int y, int pan);   /* 41 바이트 줄 -> 보이는 320 점 */

#define PL(p, off) ((uint8_t)(V.vp[off] >> ((p) * 8)))

void vga_reset(void);
void vga_setmode(int mode);
uint8_t vga_rb(uint32_t off);
void vga_wb(uint32_t off, uint8_t v);
void vga_out(uint16_t port, uint8_t v);
/* 지금 보이는 곳의 시작 주소 (CRTC 0C/0D) */
uint32_t vga_start(void);
/* 시작 주소 start 부터 320x200 을 색 번호(0..15)로 */
void vga_frame(uint32_t start, uint8_t *dst);
/* 평면 p 를 64KB 로 풀기 (시험판 대조용) */
void vga_plane(int p, uint8_t *dst);
/* EGA 64 색 번호 -> RGB 0..255 */
void ega_rgb(int c, uint8_t *rgb);
/* 바이트(8 점) -> 색 번호 8 개를 두 낱말로 펴는 표 */
extern uint32_t vga_spread[256][2];
/* 평면 p 의 바이트 -> 8 점의 색 번호 비트 (p 만큼, 그리고 256색판은 4 더 밀어 둔 것) */
extern uint32_t vga_sp4[4][256][2], vga_sp8[4][256][2];
extern unsigned long vga_nrb, vga_nwb;

#endif
