/* plat.h - 옮긴 프로그램 런타임(socrt.c)이 플랫폼(도스판 sys_dos.c / 시험판 hosttest.c)에 바라는 것 */
#ifndef PLAT_H
#define PLAT_H

#include <stdint.h>

/* 폴 지점에서 틱 하나가 흐를 때 (도스판: 실제 시간 맞추기 + 화면 내보내기).  tick = 새 틱 번호 */
void plat_tick(uint32_t tick);
/* 지금 (tick 까지) 들어온 자판 스캔 코드 하나 (없으면 -1) */
int plat_key(uint32_t tick);
/* 스피커/PIT 포트 (42h, 43h, 61h), 조이스틱 (201h) */
void plat_sound(uint16_t port, uint8_t v);
uint8_t plat_joy(void);
/* 원판이 화면 모드를 바꿈 (int 10h AH=0) */
void plat_mode(int mode);
/* 자료 파일이 있는 곳 (끝에 / 포함, 비면 현재 디렉터리) */
extern char plat_datadir[260];
/* 게임이 쓰는 파일 (컨트롤 패널 저장) 이 가는 곳 */
extern char plat_savedir[260];
/* 프로그램 끝 / 치명적 오류 */
void plat_exit(int code);
void plat_fatal(const char *msg);

/* socrt.c */
void soc_init(int game, int adapter);   /* game 0 = 실내(in), 1 = 실외(out); adapter 'E' */
void soc_run(void);
extern uint32_t soc_ticks;              /* 폴 지점에서 흐른 틱 */
extern uint32_t soc_npoll;              /* 폴 지점 지난 횟수 */
extern uint32_t soc_nirq;
extern int soc_game;
extern uint8_t soc_port60;
/* 시험판이 폴마다 부르는 갈고리 (상태 기록) */
extern void (*soc_poll_hook)(int irq);

#endif
