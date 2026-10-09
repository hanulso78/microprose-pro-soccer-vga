/* socvga.h - 256색 개선판 (SOCVGA)
 *
 *  원판 드라이버(EGAIO)는 그대로 돌고 EGA 평면 흉내(vga.c)에 그린다.  그 옆에 점마다 '음영'(0..15)
 *  층을 하나 더 둔다.  옮긴 코드가 드라이버의 그리기 자리(tools/vhooks.txt)를 지날 때 socvga_hook 이
 *  '문맥'(경기장 타일 / 스프라이트 프레임 / 글자 / 채우기)과 원점을 정하고, EGA 에 점이 쓰일 때
 *  vga.c 가 그 점의 음영을 문맥에서 구해 적는다 (래치 복사면 음영도 복사).
 *  화면을 낼 때 색 = 원래 EGA 색 * 16 + 음영  ->  원래 색마다 16 단계 램프의 256 색.
 */
#ifndef SOCVGA_H
#define SOCVGA_H

#include <stdint.h>

extern int socvga_on;
extern void (*socvga_sound)(int ax, int si);
extern void (*socvga_kick)(void);
extern void (*socvga_foul)(void);
extern void (*socvga_restart)(int type);
extern uint8_t vsh[0x10000 * 8];        /* 점마다 음영 (평면 오프셋*8 + 점 0..7 왼쪽부터) */

/* vga.c 에서: 이 바이트(off)의 점 b(0=왼쪽) 가 새로 그려질 때의 음영 */
uint8_t socvga_shade(uint32_t off, int b);
/* 이 바이트의 점들 (aff 의 비트, 왼쪽 = 0x80) 음영을 한 번에.  chg = 색이 실제로 바뀐 점 */
void socvga_shade8(uint32_t off, uint8_t aff, uint8_t chg);
int socvga_kind(void);
/* 옮긴 코드의 갈고리 (tools/vhooks.txt 자리에서) */
void socvga_hook(uint32_t lin);
#ifdef SOCVGA
#define VH(a) socvga_hook(a)
#else
#define VH(a) ((void)0)
#endif

/* 플랫폼에서 */
int socvga_load(const char *fn);
void socvga_mode(int mode);
const uint8_t *socvga_palette(void);    /* 256*3, 0..255 */
uint32_t socvga_palgen(void);
int socvga_frame(uint8_t *dst);         /* 보이는 쪽을 256색으로 (바뀐 것이 없으면 0) */
void socvga_game(int game);             /* 0 실내, 1 실외 */

#endif
