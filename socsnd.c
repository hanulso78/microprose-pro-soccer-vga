/* ============================================================================
 *  socsnd.c  -  개선판(SOCVGA): PC 스피커 소리를 애드립(OPL2) 으로
 * ----------------------------------------------------------------------------
 *  원판 소리는 순서기다.  게임이 101a:02f0 (AX = 채널, SI = 곡) 으로 곡을 올리면 원판은 스피커로
 *  내는데, 여기서는 tools/mksound.py 가 원판 순서기를 돌려 뽑은 멜로디에 코러스, 베이스, 리듬 모드
 *  드럼을 입혀 만든 OPL2 VGM (SOUND.DAT 의 S00..S15) 을 연주한다.
 *  게임은 늘 채널 0 에 곡을 하나씩만 올리므로 VGM 하나가 애드립을 통째로 쓴다 (새 곡이 오면 바꿔 낌).
 *  원판이 소리를 끈 동안([0080:00E5] = FF) 은 건반과 드럼을 누르지 않는다.
 *  덧붙인 효과음 (원판에는 없다):
 *    공 차기  공이 발을 떠나는 코드 (실내 03ab:23f3 / 실외 03ab:234a) 에서 socsnd_kick -> 사운드 블래스터가
 *             있으면 P01 (크게 합성한 "퍽"), 함성이 나오는 중이거나 없으면 애드립 목소리 5 (곡이 안 쓰는 목소리).
 *             한 번 찰 때 몇 프레임 이어 불리므로 10 틱 안은 한 번.
 *    골 함성  골 곡 (S14) 이 오르면 SOUND.DAT 의 P00 (합성한 휘슬 + 관중 함성 PCM) 을 사운드 블래스터 DMA 로
 *             곡과 함께 (BLASTER 환경 변수가 있을 때만).
 *    휘슬     킥오프 곡 (S06, 또는 줄 서기 S07 다음에 오는 S10) 이면 P02 한 번, 쿼터 끝 곡 (S09) 이면 P03 세 번,
 *             실내 판정 문구 (아웃 / 라인 위반 / 골키퍼 시간, 03ab:2fb1) 때 P02.
 *             킥오프는 곡과 첫 차기가 같은 틱이라, 휘슬이 먼저 들리게 socsnd_hold 로 화면을 0.45 초 세운다.
 *             실외 재개 (03ab:25ad, 종류 [253c]): 0..9 코너킥/골킥이면 휘슬, 12 이상은 스로인 -> 휘슬 없이
 *             다음 번 공이 손을 떠날 때 차기 소리를 내지 않는다.
 *    골 곡은 실내 S14, 실외 S08 (socsnd_game).
 *             사운드 블래스터가 없으면 애드립 목소리 5 로 높은 떨림 음.
 *    PCM 은 한 번에 하나: 휘슬/함성이 나오는 동안 차기는 애드립으로.
 *  애드립이 있고 SOUND.DAT 을 읽었으면 PC 스피커 쪽은 내지 않는다 (sys_dos.c plat_sound).
 * ========================================================================== */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <pc.h>
#include <dpmi.h>
#include <go32.h>
#include <sys/movedata.h>
#include "cpu.h"
#include "socsnd.h"

#define NSONG 16

int socsnd_on;                  /* 애드립 + SOUND.DAT 이 있어 소리를 이쪽에서 낸다 */
static uint8_t *songs[NSONG];
static uint32_t songlen[NSONG];

static const uint8_t *vgm;      /* 연주 중인 곡 (0 = 없음) */
static uint32_t vlen, vpos, vloop;
static long vwait;              /* 남은 기다림 (샘플 * 2) */
static uint8_t regb0[9];        /* B0..B8 에 쓴 값 (키 끄기, 소리 끔 풀 때) */
static int muted;
static uint32_t nt;             /* 1/120 초 세기 */
static uint32_t kick_last, kick_off;    /* 마지막 차기 부름, 목소리 5 떼는 때 */

/* ---- 사운드 블래스터 PCM (골 함성) ---- */
static int sb_base, sb_dma = -1, sb_found = -1;
#define NPCM 4
static uint32_t sb_phys[NPCM];  /* P00 함성, P01 차기, P02/P03 휘슬: DMA 버퍼 (64KB 경계를 넘지 않게) */
static uint32_t sb_len[NPCM];
static int sb_sel[NPCM];
static uint32_t pcm_end;        /* 나오는 PCM 이 끝나는 때 (nt) */
static int last_song = -1;
static int goal_song = 14;      /* 실내 14, 실외 8 */
int socsnd_hold;                /* 킥오프 휘슬: 플랫폼이 이만큼 (1/120 초) 세운다 */
static int throw_in;            /* 스로인 대기: 다음 차기는 던지기라 소리 없음 */

static void opl(uint8_t reg, uint8_t val)
{
    int i;
    outportb(0x388, reg);
    for (i = 0; i < 6; i++)
        inportb(0x388);
    outportb(0x389, val);
    for (i = 0; i < 35; i++)
        inportb(0x388);
}

static int detect(void)
{
    uint8_t s1, s2;
    int i;
    opl(4, 0x60);
    opl(4, 0x80);
    s1 = inportb(0x388);
    opl(2, 0xFF);
    opl(4, 0x21);
    for (i = 0; i < 200; i++)
        inportb(0x388);
    s2 = inportb(0x388);
    opl(4, 0x60);
    opl(4, 0x80);
    return (s1 & 0xE0) == 0 && (s2 & 0xE0) == 0xC0;
}

static void write_reg(uint8_t reg, uint8_t val)
{
    if (reg >= 0xB0 && reg <= 0xB8) {
        regb0[reg - 0xB0] = val;
        if (muted)
            val &= ~0x20;
    } else if (reg == 0xBD && muted)
        val &= ~0x1F;
    opl(reg, val);
}

static void all_off(void)
{
    int k;
    for (k = 0; k < 9; k++) {
        regb0[k] &= ~0x20;
        opl((uint8_t)(0xB0 + k), regb0[k]);
    }
    opl(0xBD, 0x00);
}

static int dsp_write(uint8_t v)
{
    int i;
    for (i = 0; i < 100000; i++)
        if (!(inportb(sb_base + 0xC) & 0x80)) {
            outportb(sb_base + 0xC, v);
            return 1;
        }
    return 0;
}

static int sb_detect(void)
{
    const char *b = getenv("BLASTER");
    int i;
    if (!b)
        return 0;
    for (; *b; b++) {
        if (*b == 'A' || *b == 'a')
            sb_base = (int)strtol(b + 1, 0, 16);
        else if (*b == 'D' || *b == 'd')
            sb_dma = (int)strtol(b + 1, 0, 10);
    }
    if (!sb_base || sb_dma < 0 || sb_dma > 3)
        return 0;
    outportb(sb_base + 6, 1);
    for (i = 0; i < 100; i++)
        inportb(sb_base + 6);
    outportb(sb_base + 6, 0);
    for (i = 0; i < 100000; i++)
        if (inportb(sb_base + 0xE) & 0x80)
            return inportb(sb_base + 0xA) == 0xAA;
    return 0;
}

/* SOUND.DAT 의 PCM 을 도스 메모리로 (DMA 는 1MB 아래, 64KB 경계 안) */
static void pcm_load(FILE *f, int k, uint32_t off, uint32_t len)
{
    static uint8_t buf[0x10000];
    long here = ftell(f);
    int seg;
    if (sb_found < 0)
        sb_found = sb_detect();
    if (!sb_found)
        return;
    seg = __dpmi_allocate_dos_memory((int)((len * 2 + 15) >> 4), &sb_sel[k]);
    if (seg == -1)
        return;
    sb_phys[k] = (uint32_t)seg << 4;
    if ((sb_phys[k] >> 16) != ((sb_phys[k] + len - 1) >> 16))
        sb_phys[k] = (sb_phys[k] + 0xFFFF) & ~0xFFFFu;
    fseek(f, (long)off, SEEK_SET);
    if (fread(buf, 1, len, f) == len) {
        dosmemput(buf, len, sb_phys[k]);
        sb_len[k] = len;
        dsp_write(0xD1);        /* 스피커 켜기 */
    }
    fseek(f, here, SEEK_SET);
}

static void pcm_play(int k)
{
    static const uint8_t page_port[4] = {0x87, 0x83, 0x81, 0x82};
    uint32_t n = sb_len[k] - 1, ph = sb_phys[k];
    if (!sb_len[k])
        return;
    dsp_write(0xD0);            /* 앞 소리 멈춤 */
    inportb(sb_base + 0xE);     /* 끝난 인터럽트 받기 */
    outportb(0x0A, (uint8_t)(4 | sb_dma));
    outportb(0x0C, 0);
    outportb(0x0B, (uint8_t)(0x48 | sb_dma));   /* 한 번, 메모리 -> 장치 */
    outportb((uint16_t)(sb_dma * 2), (uint8_t)ph);
    outportb((uint16_t)(sb_dma * 2), (uint8_t)(ph >> 8));
    outportb(page_port[sb_dma], (uint8_t)(ph >> 16));
    outportb((uint16_t)(sb_dma * 2 + 1), (uint8_t)n);
    outportb((uint16_t)(sb_dma * 2 + 1), (uint8_t)(n >> 8));
    outportb(0x0A, (uint8_t)sb_dma);
    dsp_write(0x40);
    dsp_write(165);             /* 256 - 1000000 / 11025 */
    dsp_write(0x14);
    dsp_write((uint8_t)n);
    dsp_write((uint8_t)(n >> 8));
    pcm_end = nt + sb_len[k] * 120u / 11025u + 1;
}

/* 공 차기 "퍽": 목소리 5 (곡들은 0..4 와 리듬 6..8 만 쓴다) */
static const uint8_t kick_patch[][2] = {
    {0x2A, 0x02}, {0x4A, 0x00}, {0x6A, 0xF7}, {0x8A, 0xF6}, {0xEA, 0x00},   /* 앞 연산자 (0Ah): 딸깍 (되먹임 7, 그대로 들림) */
    {0x2D, 0x01}, {0x4D, 0x00}, {0x6D, 0xF5}, {0x8D, 0xF5}, {0xED, 0x00},   /* 뒤 연산자 (0Dh): 쿵 */
    {0xC5, 0x0F},               /* 되먹임 7, 더하기 (두 연산자 다 소리) */
};

static void kick_setup(void)
{
    unsigned i;
    for (i = 0; i < sizeof kick_patch / sizeof kick_patch[0]; i++)
        opl(kick_patch[i][0], kick_patch[i][1]);
}

void socsnd_kick(void)
{
    uint32_t last = kick_last;
    if (!socsnd_on)
        return;
    kick_last = nt + 1;
    if (last && nt + 1 - last < 10)
        return;                 /* 같은 차기가 이어 불림 */
    if (throw_in) {
        throw_in = 0;           /* 스로인: 손으로 던짐 */
        return;
    }
    if (muted)
        return;
    if (sb_len[1] && nt >= pcm_end) {
        pcm_play(1);            /* 사운드 블래스터: 크게 */
        return;
    }
    kick_setup();
    opl(0xB5, 0x00);
    opl(0xA5, 0x60);
    opl(0xB5, 0x20 | (3 << 2) | 0x01);     /* 블록 3, fnum 0x160: 약 130 Hz */
    kick_off = nt + 14;
}

/* 휘슬: 사운드 블래스터면 P02/P03, 없으면 애드립 목소리 5 로 높은 떨림 음 (길이만 맞춰) */
static const uint8_t whistle_patch[][2] = {
    {0x2A, 0xE4}, {0x4A, 0x3F}, {0x6A, 0xF0}, {0x8A, 0x0F}, {0xEA, 0x00},   /* 앞: 쓰지 않음 (더하기라 조용히) */
    {0x2D, 0xE4}, {0x4D, 0x04}, {0x6D, 0xF0}, {0x8D, 0x06}, {0xED, 0x00},   /* 뒤: 트레몰로+비브라토, 곱 4 */
    {0xC5, 0x01},
};

static void whistle(int k)
{
    unsigned i;
    if (sb_len[k]) {
        pcm_play(k);
        return;
    }
    for (i = 0; i < sizeof whistle_patch / sizeof whistle_patch[0]; i++)
        opl(whistle_patch[i][0], whistle_patch[i][1]);
    opl(0xB5, 0x00);
    opl(0xA5, 0xAC);
    opl(0xB5, 0x20 | (5 << 2) | 0x01);     /* 블록 5, fnum 0x1AC (약 650 Hz) x 곱 4: 약 2.6 kHz */
    kick_off = nt + (k == 3 ? 150 : 80);
}

void socsnd_game(int out)
{
    goal_song = out ? 8 : 14;
    last_song = -1;
    socsnd_hold = 0;
    throw_in = 0;
}

/* 실외 재개 공 놓기: 종류 0..9 코너킥/골킥, 10/11 킥오프 (곡에서), 12.. 스로인 */
void socsnd_restart(int type)
{
    if (!socsnd_on)
        return;
    if (type >= 12) {
        throw_in = 1;
        return;
    }
    throw_in = 0;
    if (type < 10 && !muted)
        whistle(2);
}

/* 심판 판정 문구 (실내: 아웃 / 라인 위반 / 골키퍼 시간) */
void socsnd_foul(void)
{
    if (!socsnd_on || muted)
        return;
    whistle(2);
}

int socsnd_init(const char *fn)
{
    FILE *f;
    uint8_t hdr[10];
    uint16_t n, i;
    if (!detect())
        return 0;
    if (!(f = fopen(fn, "rb")))
        return 0;
    if (fread(hdr, 1, 10, f) != 10 || memcmp(hdr, "SOCSND1", 7)) {
        fclose(f);
        return 0;
    }
    n = (uint16_t)(hdr[8] | hdr[9] << 8);
    for (i = 0; i < n; i++) {
        uint8_t e[16];
        long here;
        uint32_t off, len;
        int id;
        if (fread(e, 1, 16, f) != 16)
            break;
        memcpy(&off, e + 8, 4);
        memcpy(&len, e + 12, 4);
        id = (e[1] - '0') * 10 + (e[2] - '0');
        if (e[0] == 'P' && id >= 0 && id < NPCM && len <= 0xFFF0u) {
            pcm_load(f, id, off, len);
            continue;
        }
        if (e[0] != 'S' || id < 0 || id >= NSONG)
            continue;
        here = ftell(f);
        songs[id] = malloc(len);
        fseek(f, (long)off, SEEK_SET);
        if (fread(songs[id], 1, len, f) != len) {
            free(songs[id]);
            songs[id] = 0;
        } else
            songlen[id] = len;
        fseek(f, here, SEEK_SET);
    }
    fclose(f);
    for (i = 1; i < 0xF6; i++)
        opl((uint8_t)i, 0);
    opl(0x01, 0x20);
    socsnd_on = 1;
    return 1;
}

void socsnd_stop(void)
{
    if (!socsnd_on)
        return;
    vgm = 0;
    all_off();
    if (sb_found > 0)
        dsp_write(0xD0);
    pcm_end = 0;
}

static uint32_t le32(const uint8_t *p)
{
    return (uint32_t)p[0] | (uint32_t)p[1] << 8 | (uint32_t)p[2] << 16 | (uint32_t)p[3] << 24;
}

/* 게임이 곡을 올릴 때 (101a:02f0): AX = 채널 (0..9: 곡 시작, 10: 모두 멈춤), SI = 곡 번호 */
void socsnd_trigger(int ax, int si)
{
    if (!socsnd_on)
        return;
    if (ax == 10) {
        socsnd_stop();
        return;
    }
    if (ax < 0 || ax > 9 || si < 0 || si >= NSONG || !songs[si])
        return;
    if (!muted) {
        if (si == goal_song)
            pcm_play(0);        /* 골: 휘슬 + 관중 함성 */
        else if (si == 6 || (si == 10 && last_song == 7)) {
            whistle(2);         /* 킥오프: 휘슬 먼저, 공은 그 다음 */
            socsnd_hold = 54;
        }
        else if (si == 9)
            whistle(3);         /* 쿼터 끝 */
    }
    last_song = si;
    all_off();
    vgm = songs[si];
    vlen = songlen[si];
    vpos = 0x34 + le32(vgm + 0x34);
    vloop = le32(vgm + 0x1C) ? 0x1C + le32(vgm + 0x1C) : 0;
    vwait = 0;
}

/* 1/120 초마다 (플랫폼 틱): VGM 을 367.5 샘플만큼 */
void socsnd_tick(void)
{
    int m, k;
    if (!socsnd_on)
        return;
    nt++;
    if (kick_off && nt >= kick_off) {
        opl(0xB5, 0x00);
        kick_off = 0;
    }
    m = M[(LOADSEG + 0x80) * 16 + 0xE5] == 0xFF;       /* 원판이 소리를 끈 동안 */
    if (m != muted) {
        muted = m;
        for (k = 0; k < 9; k++)
            opl((uint8_t)(0xB0 + k), muted ? (regb0[k] & ~0x20) : regb0[k]);
        if (muted)
            opl(0xBD, 0x20);
    }
    if (!vgm)
        return;
    vwait -= 735;               /* 샘플 * 2 : 44100 / 120 = 367.5 */
    while (vgm && vwait <= 0) {
        uint8_t c;
        if (vpos >= vlen) {
            socsnd_stop();
            break;
        }
        c = vgm[vpos];
        if (c == 0x5A) {
            write_reg(vgm[vpos + 1], vgm[vpos + 2]);
            vpos += 3;
        } else if (c == 0x61) {
            vwait += 2L * (vgm[vpos + 1] | vgm[vpos + 2] << 8);
            vpos += 3;
        } else if (c == 0x62) {
            vwait += 2L * 735;
            vpos++;
        } else if (c == 0x63) {
            vwait += 2L * 882;
            vpos++;
        } else if (c >= 0x70 && c <= 0x7F) {
            vwait += 2L * ((c & 15) + 1);
            vpos++;
        } else if (c == 0x66) {
            if (vloop)
                vpos = vloop;
            else
                socsnd_stop();
        } else
            vpos++;             /* 모르는 명령은 건너뛴다 */
    }
}

void socsnd_shutdown(void)
{
    if (!socsnd_on)
        return;
    socsnd_stop();
    opl(0xB5, 0x00);
    opl(0x01, 0x00);
    if (sb_found > 0) {
        int k;
        dsp_write(0xD3);        /* 스피커 끄기 */
        for (k = 0; k < NPCM; k++)
            if (sb_len[k]) {
                __dpmi_free_dos_memory(sb_sel[k]);
                sb_len[k] = 0;
            }
    }
}

int socsnd_pcm(void)
{
    return sb_len[0] != 0 || sb_len[1] != 0;
}
