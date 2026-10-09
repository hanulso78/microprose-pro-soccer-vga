/* socsnd.h - 개선판: PC 스피커 소리를 애드립 VGM (SOUND.DAT) 으로 */
#ifndef SOCSND_H
#define SOCSND_H

extern int socsnd_on;
int socsnd_init(const char *fn);        /* 애드립 + SOUND.DAT 이 있으면 1 */
void socsnd_trigger(int ax, int si);    /* 게임이 곡을 올릴 때 (101a:02f0) */
void socsnd_tick(void);                 /* 1/120 초마다 */
void socsnd_stop(void);
void socsnd_kick(void);                 /* 공이 발을 떠날 때 */
void socsnd_foul(void);                 /* 심판 판정 문구가 뜰 때 */
void socsnd_restart(int type);          /* 실외 재개 공 놓기 (코너/골킥 휘슬, 스로인) */
void socsnd_game(int out);              /* 게임 시작 때: 0 실내, 1 실외 (골 곡이 다르다) */
extern int socsnd_hold;                 /* 킥오프 휘슬: 이만큼 (1/120 초) 화면을 세워 달라 */
int socsnd_pcm(void);                   /* 사운드 블래스터 함성이 준비됨 */
void socsnd_shutdown(void);

#endif
