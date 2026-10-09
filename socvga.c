/* ============================================================================
 *  socvga.c  -  256색 개선판: 점 음영 층과 문맥, 팔레트 램프, 화면 합성
 * ----------------------------------------------------------------------------
 *  원판 드라이버가 EGA 에 그리는 것은 그대로 두고 (게임 상태가 원판과 한 바이트도 안 다르게),
 *  점마다 음영(0..15, 8 = 원래 색)을 더 적는다.  음영은 '지금 그리는 것'(문맥)에 따라:
 *    경기장 타일   경기장 전체 좌표 (타일 지도 위치로 안다) -> 잔디 깎은 줄무늬, 결, 선의 빛
 *    스프라이트    프레임 안 좌표 -> 입체감 (SOCVGA.DAT 의 음영 지도, 없으면 위아래 빛)
 *    글자          글자 안 줄 -> 금속 같은 세로 그러데이션
 *    채우기        사각형 안 줄 -> 위가 밝고 아래가 어두운 판
 *  화면 색 = EGA 색(0..15) * 16 + 음영.  팔레트는 지금 ATC 의 EGA 64 색을 다듬은 바탕색에서
 *  어두운 쪽은 차갑게, 밝은 쪽은 따뜻하게 16 단계로 편다.
 * ========================================================================== */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "cpu.h"
#include "vga.h"
#include "socvga.h"

int socvga_on;
int vga_movs;
void (*socvga_sound)(int ax, int si);   /* 소리 갈고리 (도스판: socsnd_trigger) */
void (*socvga_kick)(void);              /* 공이 발을 떠날 때 (도스판: socsnd_kick) */
void (*socvga_foul)(void);              /* 심판 판정 문구가 뜰 때 (도스판: socsnd_foul) */
void (*socvga_restart)(int type);       /* 실외 재개 공 놓기 (도스판: socsnd_restart) */
uint8_t vsh[0x10000 * 8] __attribute__((aligned(16)));

#define SPR_BASE 0               /* 음영 칸: 스프라이트 유니폼 0..3, 피부 4..6 */
#define SKIN_BASE 4
#define PIT_BASE 7               /* 경기장 7..11 */
#define UI_BASE 12               /* 화면 UI 12..15 */
#define SHADOW_DARK 5            /* 경기 중 검정 줄: 그늘진 잔디 (어두운 / 밝은 줄무늬).  검정 줄의 피부 칸 5, 6 은 */
#define SHADOW_LIGHT 6           /* 쓰이지 않는다 (피부 점은 검정이 아니다; 13 은 지운 화면의 기본 칸이라 안 됨) */
enum { K_NONE, K_FILL, K_TILE, K_SPR, K_BIG, K_CHAR, K_NOISE, K_RADAR, K_REST, K_CURSOR };

static struct {
    int kind;
    int ox, oy;                 /* 쪽 안 점 좌표의 원점 (상대 좌표 = 점 - 원점) */
    int w, h;
    uint32_t id;
    int slot;
} cx;

static int game;                /* 0 실내, 1 실외 */
static int scene_match;         /* 경기 화면 (경기장 타일을 그렸다): 화면 UI 색이 바뀐다 */
static uint32_t palgen_mine = 1, pal_atc_gen = 0xFFFFFFFF;
static uint8_t pal[768];

/* ---- 자료 (SOCVGA.DAT) -------------------------------------------------------------
 *  경기장 음영 지도 (실내/실외, 704 x 1112, 한 점 한 바이트: 0..15, 255 = 규칙대로)
 *  스프라이트 음영 지도 (프레임 번호마다 w, h, 점)
 * ---------------------------------------------------------------------------------- */
#define PW 704
#define PH 1112
static uint8_t *pitch_map[2];
#define NFRAME 512
static struct {
    uint8_t w, h;
    uint8_t *sh;
} frames[2][NFRAME], bigs[2][NFRAME];

int socvga_load(const char *fn)
{
    FILE *f = fopen(fn, "rb");
    char tag[4];
    socvga_on = 1;
    if (!f)
        return 0;
    while (fread(tag, 1, 4, f) == 4) {
        uint32_t n;
        int g;
        if (fread(&n, 4, 1, f) != 1)
            break;
        g = tag[3] - '0';
        if (!memcmp(tag, "PIT", 3) && (g == 0 || g == 1) && n == PW * PH) {
            pitch_map[g] = malloc(n);
            if (fread(pitch_map[g], 1, n, f) != n)
                break;
        } else if ((!memcmp(tag, "SPR", 3) || !memcmp(tag, "BIG", 3)) && (g == 0 || g == 1)) {
            /* 프레임 개수 2, 그 뒤 (번호 2, w 1, h 1, 점 w*h) */
            uint16_t cnt, k;
            int big = tag[0] == 'B';
            if (fread(&cnt, 2, 1, f) != 1)
                break;
            for (k = 0; k < cnt; k++) {
                uint16_t id;
                uint8_t wh[2];
                if (fread(&id, 2, 1, f) != 1 || fread(wh, 1, 2, f) != 2)
                    break;
                if (id < NFRAME) {
                    uint8_t *p = malloc((size_t)wh[0] * wh[1]);
                    if (fread(p, 1, (size_t)wh[0] * wh[1], f) != (size_t)wh[0] * wh[1])
                        break;
                    if (big) {
                        bigs[g][id].w = wh[0]; bigs[g][id].h = wh[1]; bigs[g][id].sh = p;
                    } else {
                        frames[g][id].w = wh[0]; frames[g][id].h = wh[1]; frames[g][id].sh = p;
                    }
                } else
                    fseek(f, (long)wh[0] * wh[1], SEEK_CUR);
            }
        } else
            fseek(f, (long)n, SEEK_CUR);
    }
    fclose(f);
    return 1;
}

void socvga_game(int g)
{
    game = g;
}

static void xy_init(void);

void socvga_mode(int mode)
{
    (void)mode;
    xy_init();
    memset(vsh, UI_BASE + 1, sizeof vsh);
    palgen_mine++;
}

/* ---- 문맥 ------------------------------------------------------------------------ */
#define DRV_DS 0x254F0u         /* 드라이버 자료 (DRVSEG + 34F) */
static uint32_t page_base(void)
{
    uint16_t s = (uint16_t)(M[DRV_DS + 4] | M[DRV_DS + 5] << 8);
    return (uint32_t)(uint16_t)(s - 0xA000) << 4;
}

static uint32_t hash2(int x, int y)
{
    uint32_t h = (uint32_t)x * 374761393u + (uint32_t)y * 668265263u;
    h = (h ^ (h >> 13)) * 1274126177u;
    return h ^ (h >> 16);
}

/* 채우는 부분(바탕, 막대, 글자 칸 바탕, 그림자)은 단색: 메뉴는 9 단계 램프(7..15)의 가운데 위, 경기는 UI 칸 */
#define SOLID() ((uint8_t)(scene_match ? UI_BASE + 2 : 12))

/* 그러데이션 계단을 없애는 4x4 Bayer 디더: t (0..3 실수, 16 배) -> 칸 */
static const uint8_t BAYER[4][4] = {{0, 8, 2, 10}, {12, 4, 14, 6}, {3, 11, 1, 9}, {15, 7, 13, 5}};
static int dith(int t16, int x, int y)
{
    int v = (t16 + BAYER[y & 3][x & 3]) >> 4;
    return v < 0 ? 0 : v > 3 ? 3 : v;
}
/* 화면 전체 세로 그러데이션 (위 밝음): 16 배 값 */
#define BG_T16(py) (44 - ((py) * 44) / 199)
/* 메뉴 장면: 칸 7..15 (9 단계) 를 한 줄기 램프로 쓴다 -> 단계 사이가 좁아 디더 점이 안 보인다 */
static int dith9(int t16, int x, int y)
{
    int v = (t16 + BAYER[y & 3][x & 3]) >> 4;
    return 7 + (v < 0 ? 0 : v > 8 ? 8 : v);
}
#define MBG_T16(py) (88 - ((py) * 40) / 199)       /* 5.5 -> 3.0 */

/* 드라이버 안 자리 (1209:xxxx) -> 선형 */
#define D(o) (0x12090u + (o))

static const uint16_t tile_sites[] = {
    0x0ac9, 0x0b42, 0x0bbb, 0x0c34, 0x0cad, 0x0d26, 0x0d9f, 0x0e18, 0x0e91, 0x0f0a, 0x0f83, 0x0ffc, 0x1075,
    0x10ee, 0x1167, 0x11e0, 0x1259, 0x12d2, 0x134b, 0x13c4, 0x143d, 0x14b6, 0x152f, 0x15a8, 0x1621, 0x169a,
    0x1713, 0x178c, 0x1805, 0x187e, 0x18f7, 0x1970, 0x19e9, 0x1a62, 0x1adb, 0x1b54, 0x1bcd, 0x1c46, 0x24b9,
    0x24f0, 0x2527, 0x255e, 0x2595};

static uint8_t rest_slot[16][64];

static uint32_t last_hook;
void socvga_hook(uint32_t lin)
{
    uint32_t o;
    unsigned k;
    if (lin == 0x0605Du) {                      /* 03ab:25ad (실외): 재개 공 놓기, [253c] = 종류 */
        if (socvga_restart)
            socvga_restart(M[LIN(DS_, 0x253c)]);
        return;
    }
    if (lin == 0x06A61u) {                      /* 03ab:2fb1 (실내): 판정 문구 (아웃 / 라인 위반 / 골키퍼 시간) */
        if (socvga_foul)
            socvga_foul();
        return;
    }
    if (lin == 0x05EA3u || lin == 0x05DFAu) {  /* 03ab:23f3 (실내) / 03ab:234a (실외): 공이 발을 떠남 */
        if (socvga_kick)
            socvga_kick();
        return;
    }
    if (lin == 0x10490u || lin == 0x0F900u) {  /* 101a:02f0 (실내) / 0f61:02f0 (실외): 곡 올리기 */
        if (socvga_sound)
            socvga_sound(AX, SI);
        return;
    }
    if (!socvga_on)
        return;
    last_hook = lin;
    switch (lin) {
    case D(0x01c8):             /* 글자 (API 4/29): SI = 글꼴 자리, DH = 줄, DL = 바이트 칸 */
    case D(0x0263):             /* 점수판 글자 (API 26) */
        cx.kind = K_CHAR;
        cx.id = SI;
        cx.ox = DL * 8;
        cx.oy = DH;
        /* 꽉 찬 블록 글자 (막대를 그릴 때 쓴다): 글자 그러데이션 대신 화면 세로 그러데이션 */
        {
            const uint8_t *g = M + DRV_DS + SI;
            cx.w = (g[0] & g[1] & g[2] & g[3] & g[4] & g[5] & g[6] & g[7]) == 0xFF;
        }
        return;
    case D(0x00f9):             /* 화면 지우기 (API 2) */
        scene_match = 0;
        cx.kind = K_FILL;
        cx.ox = cx.oy = 0;
        cx.w = 320;
        cx.h = 200;
        return;
    case D(0x012d):             /* 사각형 채우기 (API 15): DL 칸, DH 줄, CL 너비(바이트), CH 높이 */
    {
        /* 바로 위 채우기에 이어 붙으면 (같은 칸, 같은 너비) 한 막대로 본다: 그러데이션을 위에서 잇는다 */
        static int lx = -1, lw, ltop, lbot;
        int x = DL * 8, w = CL * 8, top = DH;
        if (x == lx && w == lw && top == lbot)
            top = ltop;
        lx = x;
        lw = w;
        ltop = top;
        lbot = DH + (CH ? CH : 1);
        cx.kind = K_FILL;
        cx.ox = x;
        cx.oy = top;
        cx.w = w;
        cx.h = lbot - top;
        return;
    }
    case D(0x2803):             /* 스프라이트 (API 9): BP 프레임, SI x, DI y */
    case D(0x312b): {           /* 큰 스프라이트 (API 18) */
        /* API 10/17 은 바이트에 걸친 나머지를 그리려고 SI+8 로 한 번 더 부른다 (복귀 27fa / 3122):
         * 그때도 원점은 처음 x */
        uint16_t ret = (uint16_t)(M[LIN(SS_, SP)] | M[LIN(SS_, (uint16_t)(SP + 1))] << 8);
        int second = ret == 0x27fa || ret == 0x3122;
        cx.kind = lin == D(0x2803) ? K_SPR : K_BIG;
        cx.id = BP;
        cx.ox = (int16_t)SI - (second ? 8 : 0);
        cx.oy = (int16_t)DI;
        return;
    }
    case D(0x3035):             /* 반짝이 점 (API 16) */
        cx.kind = K_NOISE;
        return;
    case D(0x0473):             /* 작은 지도 (API 23) */
        cx.kind = K_RADAR;
        return;
    case D(0x3218):             /* 8x8 덩어리 저장 + 표시 (API 27): SI 칸, DI 줄, BX 칸 번호 */
        o = page_base() + DI * 40u + SI;
        for (k = 0; k < 8; k++)
            memcpy(rest_slot[BX & 15] + k * 8, vsh + ((o + k * 40) & 0xFFFF) * 8, 8);
        cx.kind = K_CURSOR;
        cx.ox = SI * 8;
        cx.oy = DI;
        return;
    case D(0x332c):             /* 8x8 덩어리 되돌리기 (API 28) */
        cx.kind = K_REST;
        cx.slot = BX & 15;
        cx.ox = SI * 8;
        cx.oy = DI;
        return;
    }
    if (lin >= D(0x0ac9) && lin <= D(0x2595)) {
        int lo = 0, hi = (int)(sizeof tile_sites / sizeof tile_sites[0]) - 1;
        k = 0xFFFF;
        while (lo <= hi) {
            int mid = (lo + hi) / 2;
            if (D(tile_sites[mid]) == lin) {
                k = (unsigned)mid;
                break;
            }
            if (D(tile_sites[mid]) < lin)
                lo = mid + 1;
            else
                hi = mid - 1;
        }
        if (k != 0xFFFF) {
            /* 경기장 타일: BX = 지도 자리(바이트, 줄마다 88 칸), DI = 쪽 안 바이트 자리 */
            unsigned idx = BX >> 1, col = idx % 88, row = idx / 88;
            cx.kind = K_TILE;
            scene_match = 1;
            cx.ox = (DI % 40) * 8 - (int)col * 8;
            cx.oy = DI / 40 - (int)row * 8;
            return;
        }
    }
    /* 그 밖의 API 들어가기: 문맥 없음 */
    cx.kind = K_NONE;
}

#ifdef SOCDBG
extern uint8_t vkind[];
unsigned long socvga_nshade[16], socvga_nshade8[16];
#endif

static int logical(int v);

/* 공 그림자 점: 덮기 전 점이 잔디 (논리색 2/10/14, 경기장 칸 7..11) 이면 그 밝기에 맞춘 그늘진 잔디 칸
 * (검정 줄의 5/6: 피부 칸이라 검정 점에는 쓰이지 않는다, make_palette) */
static uint8_t shadow_slot(uint8_t old, int b)
{
    int sh_ = 7 - b, c, lc;
    if (!scene_match)
        return 1;
    c = (vga_oldw >> sh_ & 1) | (vga_oldw >> (8 + sh_) & 1) << 1 | (vga_oldw >> (16 + sh_) & 1) << 2 |
        (vga_oldw >> (24 + sh_) & 1) << 3;
    lc = logical(V.atc[c] & 63);
    if (lc == 0 && (old == SHADOW_DARK || old == SHADOW_LIGHT))
        return old;             /* 이미 그늘 (여러 번 칠함) */
    if ((lc == 2 || lc == 10 || lc == 14) && old >= PIT_BASE && old <= PIT_BASE + 4)
        return old <= PIT_BASE + 1 ? SHADOW_DARK : SHADOW_LIGHT;
    return 1;                   /* 선 위 등: 원래처럼 검은 그림자 */
}

/* 쪽 안 자리 (0..1FFF) -> 점 x (8 의 배수), 줄 y: 486 에서 나눗셈을 피하려고 표로 */
static int16_t xy_x[0x2000], xy_y[0x2000];

static void xy_init(void)
{
    int o;
    for (o = 0; o < 0x2000; o++) {
        xy_x[o] = (int16_t)((o % 40) * 8);
        xy_y[o] = (int16_t)(o / 40);
    }
}

void socvga_shade8(uint32_t off, uint8_t aff, uint8_t chg)
{
    uint8_t *sh = vsh + off * 8;
    uint32_t o = off & 0x1FFF;
    int px0 = xy_x[o], py = xy_y[o], b, s;
    int rx0 = px0 - cx.ox, ry = py - cx.oy;
#ifdef SOCDBG
    {
        static long w = -2;
        if (w == -2)
            w = getenv("WATCHOFF") ? strtol(getenv("WATCHOFF"), 0, 16) : -1;
        if ((long)off == w)
            fprintf(stderr, "watch %05X kind %d hook %05X aff %02X movs %d DI %04X ES %04X\n", (unsigned)off, cx.kind,
                    (unsigned)last_hook, aff, vga_movs, DI, ES_);
    }
    socvga_nshade8[cx.kind & 15]++;
    for (b = 0; b < 8; b++)
        if (aff & (0x80 >> b))
            vkind[off * 8 + b] = (uint8_t)(socvga_kind() | (vga_movs ? 0x80 : 0));
#endif
    if (!scene_match && (cx.kind == K_CHAR || cx.kind == K_CURSOR)) {   /* 글자 칸: 같은 색으로 덮으면 음영도 그대로 (채우기는 늘 새로) */
        aff &= chg;
        if (!aff)
            return;
    }
    switch (cx.kind) {
    case K_TILE:
        if (pitch_map[game] && rx0 >= 0 && ry >= 0 && rx0 + 8 <= PW && ry < PH) {
            const uint8_t *src = pitch_map[game] + ry * PW + rx0;
            if (aff == 0xFF) {
                ((uint32_t *)sh)[0] = ((const uint32_t *)src)[0];
                ((uint32_t *)sh)[1] = ((const uint32_t *)src)[1];
            } else
                for (b = 0; b < 8; b++)
                    if (aff & (0x80 >> b))
                        sh[b] = src[b];
            return;
        }
        s = PIT_BASE + 2;       /* 지도 밖 (다른 것이 쓰는 중) */
        goto fill;
    case K_SPR:
    case K_BIG: {
        int big = cx.kind == K_BIG;
        unsigned id = cx.id < NFRAME ? cx.id : 0;
        const uint8_t *m = big ? bigs[game][id].sh : frames[game][id].sh;
        int w = big ? bigs[game][id].w : frames[game][id].w, h = big ? bigs[game][id].h : frames[game][id].h;
        int def = ry < 4 ? 2 : 1;    /* 지도 없는 프레임: 위가 밝게 */
        if (m && ry >= 0 && ry < h) {
            const uint8_t *row = m + ry * w;
            for (b = 0; b < 8; b++)
                if (aff & (0x80 >> b)) {
                    int rx = rx0 + b;
                    int v = (rx >= 0 && rx < w) ? row[rx] : 255;
                    if (v == 8)         /* 공 그림자: 아래가 잔디면 그 잔디를 어둡게 (비쳐 보이게) */
                        sh[b] = shadow_slot(sh[b], b);
                    else
                        sh[b] = (uint8_t)(v < 7 ? v : def);
                }
        } else
            for (b = 0; b < 8; b++)
                if (aff & (0x80 >> b))
                    sh[b] = (uint8_t)def;
        return;
    }
    case K_FILL:
        s = SOLID();            /* 단색: 한 번에 (486 속도) */
        goto fill;
    case K_CHAR:
    case K_CURSOR:
        if (!vga_movs || (cx.kind == K_CHAR && cx.w))
            { s = SOLID(); goto fill; }     /* 바탕/막대: 단색을 한 번에 */
        /* 글자 획: 어두운 색 글자는 램프의 어두운 쪽, 밝은 색은 밝은 쪽 (막대와 대비가 나게) */
        {
            uint32_t w = V.vp[off];
            int lvl = 3 - (ry * 3) / 7;     /* 위가 밝은 금속 그러데이션 0..3 */
            if (lvl < 0)
                lvl = 0;
            if (lvl > 3)
                lvl = 3;
            for (b = 0; b < 8; b++)
                if (aff & (0x80 >> b)) {
                    int sh_ = 7 - b;
                    int c = (w >> sh_ & 1) | (w >> (8 + sh_) & 1) << 1 | (w >> (16 + sh_) & 1) << 2 |
                            (w >> (24 + sh_) & 1) << 3;
                    int lc = logical(V.atc[c] & 63);
                    int dark = lc < 8 && lc != 7 && lc != 3;
                    if (scene_match)
                        sh[b] = (uint8_t)(UI_BASE + (dark ? 0 : 3));   /* 경기 중(점수판): 단색 -> 두 쪽이 늘 같은 색 */
                    else        /* 메뉴: 9 단계 (7..15) 중 어두운 글자는 7..8, 밝은 글자는 12..15 */
                        sh[b] = (uint8_t)(dark ? 7 + lvl / 2 : 12 + lvl);
                }
            return;
        }
    case K_NONE:
    case K_RADAR:
        s = socvga_shade(off, 0);   /* 이 문맥들은 가로 자리와 상관없다 */
    fill:
        if (aff == 0xFF) {
            uint32_t v = (uint32_t)s * 0x01010101u;
            ((uint32_t *)sh)[0] = v;
            ((uint32_t *)sh)[1] = v;
        } else
            for (b = 0; b < 8; b++)
                if (aff & (0x80 >> b))
                    sh[b] = (uint8_t)s;
        return;
    }
#ifdef SOCDBG
    if (cx.kind == K_TILE && getenv("TILEDBG")) {
        static int nd;
        if (nd++ < 30)
            fprintf(stderr, "tile fallback off %05X px0 %d py %d ox %d oy %d rx0 %d ry %d aff %02X movs %d\n",
                    (unsigned)off, px0, py, cx.ox, cx.oy, rx0, ry, aff, vga_movs);
    }
#endif
    for (b = 0; b < 8; b++)
        if (aff & (0x80 >> b))
            sh[b] = socvga_shade(off, b);
}


int socvga_kind(void)
{
    return cx.kind | (cx.kind == K_CHAR && cx.w ? 0x40 : 0);
}

uint8_t socvga_shade(uint32_t off, int b)
{
#ifdef SOCDBG
    socvga_nshade[cx.kind & 15]++;
#endif
    uint32_t o = off & 0x1FFF;
    int px = xy_x[o] + b, py = xy_y[o];
    int rx = px - cx.ox, ry = py - cx.oy, s;
    switch (cx.kind) {
    case K_TILE:
        if (rx >= 0 && ry >= 0 && rx < PW && ry < PH && pitch_map[game]) {
            s = pitch_map[game][ry * PW + rx];
            if (s < 16)
                return (uint8_t)s;
        }
        return (uint8_t)(PIT_BASE + (((ry >> 4) & 1) ? 1 : 2));
    case K_SPR:
    case K_BIG: {
        int big = cx.kind == K_BIG;
        unsigned id = cx.id < NFRAME ? cx.id : 0;
        const uint8_t *sh = big ? bigs[game][id].sh : frames[game][id].sh;
        int w = big ? bigs[game][id].w : frames[game][id].w, h = big ? bigs[game][id].h : frames[game][id].h;
        if (sh && rx >= 0 && ry >= 0 && rx < w && ry < h && sh[ry * w + rx] < 7)
            return sh[ry * w + rx];
        return (uint8_t)(ry < 4 ? 2 : 1);
    }
    case K_CHAR:
    case K_CURSOR:
        if (!vga_movs || (cx.kind == K_CHAR && cx.w))  /* 글자 칸 바탕, 블록 글자 막대: 단색 */
            return SOLID();
        s = 3 - (ry * 3) / 7;   /* 글자 획: 위가 밝은 금속 그러데이션 */
        return (uint8_t)(UI_BASE + (s < 0 ? 0 : s > 3 ? 3 : s));
    case K_FILL:                /* 바탕, 막대, 그림자: 단색 (그러데이션/디더 없이) */
        return SOLID();
    case K_REST:
        if (rx >= 0 && ry >= 0 && rx < 8 && ry < 8)
            return rest_slot[cx.slot][ry * 8 + rx];
        return UI_BASE + 1;
    case K_NOISE:
        return (uint8_t)(UI_BASE + (hash2(px, py) & 3));
    }
    return UI_BASE + 1;
}

/* ---- 팔레트 ----------------------------------------------------------------------
 *  256 색 = EGA 색 16 개 x 16 칸.  한 EGA 색의 16 칸은 쓰임새로 나눈다:
 *    0..3   스프라이트 (선수, 공, 메뉴 그림)   : 유니폼/머리 색, 그늘 -> 빛
 *    4..6   스프라이트의 피부 (팀 색과 상관없이 늘 피부색; 유니폼과 피부가 같은 EGA 색이어도)
 *    7..11  경기장 타일                       : 잔디, 흰 선, 벽/트랙
 *    12..15 화면 UI (글자, 막대, 바탕, 점수판) : 장면(메뉴/경기)마다 다르게
 *  같은 EGA 색도 선수 위에서는 피부, 경기장에서는 붉은 선 ... 처럼 전혀 다른 색 계열이 된다.
 * ---------------------------------------------------------------------------------- */
typedef struct { uint8_t d[3], l[3]; } rampdef;

/* 스프라이트: EGA 논리색 0..15 */
static const rampdef R_SPR[16] = {    /* 원판 EGA 색과 같은 빛깔로, 채도를 살려 (옅은 회색빛이 끼지 않게) */
    {{8, 7, 8}, {50, 38, 32}},          /* 0 검정: 반바지, 신발, 테두리.  밝은 끝은 짙은 갈색 (머리카락, 옷 주름) */
    {{0, 6, 96}, {40, 72, 228}},        /* 1 파랑 유니폼 */
    {{0, 70, 16}, {40, 190, 70}},       /* 2 초록 유니폼 */
    {{0, 80, 90}, {30, 190, 200}},      /* 3 청록 */
    {{100, 0, 4}, {220, 34, 30}},       /* 4 빨강 */
    {{80, 0, 90}, {196, 60, 206}},      /* 5 보라 */
    {{110, 44, 0}, {226, 120, 24}},     /* 6 주황/갈색 유니폼 */
    {{110, 112, 118}, {214, 214, 220}}, /* 7 회색 (양말) */
    {{40, 40, 46}, {108, 108, 116}},    /* 8 짙은 회색 */
    {{30, 60, 170}, {100, 150, 255}},   /* 9 하늘색 유니폼 */
    {{30, 130, 20}, {120, 236, 80}},    /* 10 연두 유니폼 */
    {{20, 140, 160}, {110, 236, 250}},  /* 11 옅은 청록 */
    {{150, 40, 10}, {250, 120, 50}},    /* 12 주황 유니폼 (피부는 R_SKIN) */
    {{150, 40, 110}, {250, 110, 210}},  /* 13 분홍 */
    {{170, 120, 0}, {255, 230, 60}},    /* 14 노랑 유니폼 */
    {{150, 158, 176}, {255, 255, 255}}, /* 15 흰색 (유니폼, 공) */
};
/* 경기장 */
static const rampdef R_SKIN = {{70, 42, 28}, {246, 190, 150}};  /* 피부 (팀 색과 상관없이); 가장 어두운 칸은 머리카락 */
static const rampdef R_GRASS = {{30, 82, 24}, {108, 176, 62}};
static const rampdef R_PIT[16] = {
    {{6, 8, 6}, {44, 50, 44}},          /* 0 그늘, 바깥 어둠 */
    {{20, 30, 90}, {80, 110, 200}},
    {{0}, {0}},                         /* 2 잔디 (R_GRASS) */
    {{0, 70, 80}, {70, 180, 190}},
    {{92, 20, 14}, {184, 54, 36}},      /* 4 벽돌/트랙 */
    {{70, 20, 80}, {170, 80, 180}},
    {{90, 60, 30}, {170, 120, 70}},
    {{120, 124, 118}, {214, 218, 210}},
    {{50, 54, 50}, {130, 134, 128}},
    {{50, 90, 170}, {140, 190, 250}},
    {{0}, {0}},                         /* 10 잔디 */
    {{60, 150, 160}, {170, 240, 245}},
    {{150, 30, 24}, {238, 84, 62}},     /* 12 붉은 선 */
    {{150, 60, 120}, {240, 140, 210}},
    {{0}, {0}},                         /* 14 잔디 (실외) */
    {{176, 186, 176}, {255, 255, 246}}, /* 15 흰 선, 골대 */
};
/* 화면 UI: 경기 중 (점수판) / 메뉴 */
static const rampdef R_UI_MATCH[16] = {
    {{10, 12, 22}, {10, 12, 22}},       /* 0 점수판 판: 한 색 (글자 칸 바탕이 판과 같게) */
    {{24, 44, 130}, {96, 138, 236}},
    {{20, 100, 30}, {90, 200, 90}},
    {{0, 100, 120}, {80, 210, 230}},
    {{140, 26, 20}, {236, 86, 60}},
    {{110, 30, 120}, {220, 110, 230}},
    {{120, 70, 20}, {230, 150, 60}},
    {{150, 154, 166}, {196, 200, 212}},   /* 7 회색: 원판처럼 밝은 회색 (시계가 흰색과 번갈아 깜빡일 때 은은하게) */
    {{60, 62, 72}, {150, 152, 162}},
    {{50, 100, 200}, {140, 196, 255}},
    {{40, 140, 40}, {150, 240, 120}},
    {{40, 160, 180}, {170, 250, 255}},
    {{180, 44, 36}, {255, 124, 100}},
    {{160, 60, 140}, {255, 150, 230}},
    {{190, 130, 0}, {255, 232, 90}},
    {{206, 212, 226}, {255, 255, 255}},
};
static const rampdef R_UI_MENU[16] = {
    {{2, 3, 8}, {16, 20, 34}},          /* 0 그림자, 검은 글자 */
    {{6, 12, 42}, {44, 86, 178}},       /* 1 밤 경기장 남색 바탕 */
    {{16, 90, 30}, {86, 200, 86}},      /* 2 */
    {{0, 88, 110}, {84, 214, 232}},     /* 3 청록 막대 */
    {{150, 30, 22}, {240, 96, 70}},     /* 4 */
    {{90, 18, 112}, {226, 112, 236}},   /* 5 보라 막대 */
    {{130, 76, 20}, {236, 160, 70}},    /* 6 */
    {{64, 70, 86}, {158, 164, 182}},    /* 7 회색 막대: 흰 글자가 보이게 은회색 */
    {{50, 54, 70}, {140, 146, 164}},    /* 8 */
    {{28, 70, 168}, {126, 186, 255}},   /* 9 밝은 파랑 판 */
    {{40, 134, 40}, {156, 238, 122}},   /* 10 연두 글자/막대 */
    {{40, 160, 190}, {176, 250, 255}},  /* 11 */
    {{176, 40, 30}, {255, 126, 94}},    /* 12 */
    {{160, 50, 140}, {255, 150, 232}},  /* 13 */
    {{172, 112, 0}, {255, 228, 84}},    /* 14 금색 */
    {{206, 212, 226}, {255, 255, 255}}, /* 15 흰 글자: 아래 줄도 밝게 */
};


static void put_ramp(int base, int n, const rampdef *r, int lighten)
{
    int k, j;
    for (k = 0; k < n; k++) {
        double t = n > 1 ? (double)k / (n - 1) : 0.5;
        t = t * t * 0.35 + t * 0.65;        /* 밝은 쪽을 조금 넓게 */
        for (j = 0; j < 3; j++) {
            double v = r->d[j] + (r->l[j] - r->d[j]) * t;
            if (lighten && k == n - 1 && memcmp(r->d, r->l, 3))
                v = v + (255 - v) * 0.25;
            pal[(base + k) * 3 + j] = (uint8_t)(v < 0 ? 0 : v > 255 ? 255 : v);
        }
    }
}

static int logical(int v)
{
    /* ATC 값 (EGA 64 색) -> 논리색 0..15 (모드 0Dh 는 0..7, 16..23) */
    if (v < 8)
        return v;
    if (v >= 16 && v < 24)
        return v - 8;
    return (v & 7) | ((v & 0x38) ? 8 : 0);
}

static void make_palette(void)
{
    int c;
    for (c = 0; c < 16; c++) {
        int lc = logical(V.atc[c] & 63);
        const rampdef *pit = (lc == 2 || lc == 10 || lc == 14) ? &R_GRASS : &R_PIT[lc];
        put_ramp(c * 16 + 0, 4, &R_SPR[lc], lc == 15);
        put_ramp(c * 16 + 4, 3, &R_SKIN, 0);
        if (scene_match) {
            put_ramp(c * 16 + 7, 5, pit, 0);
            put_ramp(c * 16 + 12, 4, &R_UI_MATCH[lc], 1);
            if (lc == 0) {      /* 공 그림자: 잔디를 65% 로 (검정 줄의 피부 칸 자리) */
                static const uint8_t sd[3] = {24, 60, 18}, sl[3] = {54, 94, 32};
                memcpy(pal + (c * 16 + SHADOW_DARK) * 3, sd, 3);
                memcpy(pal + (c * 16 + SHADOW_LIGHT) * 3, sl, 3);
            }
        } else          /* 메뉴: 경기장 칸이 쓰이지 않으니 7..15 를 9 단계 UI 램프로 */
            put_ramp(c * 16 + 7, 9, &R_UI_MENU[lc], 1);
    }
}

static int pal_scene = -1;
const uint8_t *socvga_palette(void)
{
    if (pal_atc_gen != V.palgen || pal_scene != scene_match) {
        pal_scene = scene_match;
        make_palette();
        pal_atc_gen = V.palgen;
        palgen_mine++;
    }
    return pal;
}

uint32_t socvga_palgen(void)
{
    socvga_palette();
    return palgen_mine;
}

/* ---- 화면 합성 ------------------------------------------------------------------- */
static uint32_t shown_gen = 0xFFFFFFFF, shown_start = 0xFFFFFFFF;
static int shown_pan = -1;

/* 가로 미세 스크롤 (속성 레지스터 13h) 과 실외 경기의 좁은 표시 폭도 따른다: vga_frame 참고 */
int socvga_frame(uint8_t *dst)
{
    uint32_t start = vga_start();
    int y, xb, pan = V.pan & 7, full = pan || V.crtc[1] == 0x25;
    uint32_t line[41 * 2];
    if (shown_gen == V.gen && shown_start == start && shown_pan == pan)
        return 0;
    for (y = 0; y < 200; y++) {
        uint32_t *d = full ? line : (uint32_t *)(dst + y * 320);
        int nb = full ? 41 : 40;
        for (xb = 0; xb < nb; xb++) {
            uint32_t o = (start + (uint32_t)y * 40 + xb) & 0xFFFF, w = V.vp[o];
            const uint32_t *s0 = vga_sp8[0][w & 0xFF], *s1 = vga_sp8[1][(w >> 8) & 0xFF];
            const uint32_t *s2 = vga_sp8[2][(w >> 16) & 0xFF], *s3 = vga_sp8[3][w >> 24];
            const uint32_t *sh = (const uint32_t *)(vsh + o * 8);
            d[0] = s0[0] | s1[0] | s2[0] | s3[0] | (sh[0] & 0x0F0F0F0Fu);
            d[1] = s0[1] | s1[1] | s2[1] | s3[1] | (sh[1] & 0x0F0F0F0Fu);
            d += 2;
        }
        if (full)
            vga_line_map((uint8_t *)line, dst + y * 320, y, pan);
    }
    shown_gen = V.gen;
    shown_start = start;
    shown_pan = pan;
    return 1;
}
