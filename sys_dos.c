/* ============================================================================
 *  sys_dos.c  -  도스(djgpp) 플랫폼: 옮긴 MicroProse Soccer 를 진짜 PC 에서 돌린다
 * ----------------------------------------------------------------------------
 *  처음    SOCCER.COM 처럼 실내/실외 고르기 (글자 화면).  고른 게임을 돌리고, 게임이 끝나면
 *          다시 고르기로.  SOCCER.COM 이 넘기던 18 바이트(첫 실행 표시, 조이스틱 설정)는 이어 준다.
 *  화면    원판 드라이버는 EGA 모드 0Dh 평면에 그린다 (vga.c 가 흉내).  여기서 보이는 쪽
 *          (CRTC 시작 주소)을 VGA 모드 13h 로 풀어 보인다.  256색 개선판(SOCVGA)은 socvga.c.
 *  시계    원판은 PIT 120Hz 로 게임을 돌린다.  옮긴 코드는 폴 지점(대기 루프)에서 틱을
 *          하나씩 흘리는데, 여기서 그 틱이 실제 1/120 초에 맞도록 기다린다 (uclock).
 *  자판    IRQ1 을 직접 받아 스캔 코드(누름/뗌)를 모아 두었다가 폴 지점에서 게임의 int 9 로.
 *          Ctrl+Q : 게임을 끝내고 고르기 화면으로.
 *  소리    스피커 포트 42h/61h, 43h 의 채널 2 쪽만 그대로.  시험 모드이거나 SOCNOSND=1 이면 끈다.
 *          개선판은 애드립이 있고 SOUND.DAT 이 있으면 애드립 VGM 으로 (socsnd.c, SOCSPK=1 이면 스피커).
 *  시험    SOCTEST=대본 : "틱 +키 [누름틱]" / "틱 스캔16진" / "틱 shot 이름" / "틱 quit"
 *          (시간을 맞추지 않고 빨리 돈다 -> 호스트 시험판과 같은 결과).  SOCREAL=1 이면 실제 시간에 맞춰
 *          돌고 화면도 실제처럼 보인다 (느린 기계에서 제 속도가 나는지: 틱/초가 120 이고 behind 가 0 이면 됨)
 * ========================================================================== */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <signal.h>
#include <dpmi.h>
#include <go32.h>
#include <pc.h>
#include <conio.h>
#include <sys/farptr.h>
#include <sys/movedata.h>
#include <time.h>
#include <setjmp.h>
#include <sys/nearptr.h>
#include "cpu.h"
#include "vga.h"
#include "plat.h"
#ifdef SOCVGA
#include "socvga.h"
#include "socsnd.h"
#endif

char plat_datadir[260];
char plat_savedir[260];
static int gfx;
static uint8_t vbuf[64000];
static uclock_t t0;
static uint32_t shown_gen = 0xFFFFFFFF, shown_pal = 0xFFFFFFFF, shown_start = 0xFFFFFFFF;
static int shown_pan = -1;
static uclock_t last_present;
static long st_pres, st_behind;
static uint32_t st_btick[32];       /* 뒤처진 틱 (시험 기록용) */
static uclock_t st_prest;
static int quit_req;
static uclock_t t_run0;
static int no_sound;

/* ---- 자판 IRQ1 ---------------------------------------------------------------- */
#define KQ 256
static volatile uint8_t kq[KQ];
static volatile unsigned kq_head, kq_tail;
static volatile int k_ctrl;
static _go32_dpmi_seginfo old_kb, new_kb;
static int kb_on;

static void kb_isr(void)
{
    uint8_t sc = inportb(0x60);
    uint8_t v = inportb(0x61);
    outportb(0x61, v | 0x80);
    outportb(0x61, v);
    if ((sc & 0x7F) == 0x1D)
        k_ctrl = !(sc & 0x80);
    if (sc == 0x10 && k_ctrl)
        quit_req = 1;
    if (((kq_head + 1) & (KQ - 1)) != kq_tail) {
        kq[kq_head] = sc;
        kq_head = (kq_head + 1) & (KQ - 1);
    }
    outportb(0x20, 0x20);
}
static void kb_isr_end(void) {}

static void kb_install(void)
{
    if (kb_on)
        return;
    _go32_dpmi_lock_code((void *)kb_isr, (unsigned long)kb_isr_end - (unsigned long)kb_isr);
    _go32_dpmi_lock_data((void *)kq, sizeof kq);
    _go32_dpmi_lock_data((void *)&kq_head, sizeof kq_head);
    _go32_dpmi_lock_data((void *)&kq_tail, sizeof kq_tail);
    _go32_dpmi_lock_data((void *)&k_ctrl, sizeof k_ctrl);
    _go32_dpmi_lock_data((void *)&quit_req, sizeof quit_req);
    _go32_dpmi_get_protected_mode_interrupt_vector(9, &old_kb);
    new_kb.pm_offset = (unsigned long)kb_isr;
    new_kb.pm_selector = _go32_my_cs();
    _go32_dpmi_allocate_iret_wrapper(&new_kb);
    _go32_dpmi_set_protected_mode_interrupt_vector(9, &new_kb);
    kq_head = kq_tail = 0;
    kb_on = 1;
}

static void kb_remove(void)
{
    if (!kb_on)
        return;
    _go32_dpmi_set_protected_mode_interrupt_vector(9, &old_kb);
    _go32_dpmi_free_iret_wrapper(&new_kb);
    kb_on = 0;
    /* BIOS 자판 버퍼 비우기 */
    _farpokew(_dos_ds, 0x41A, _farpeekw(_dos_ds, 0x41C));
}

/* ---- 시험 대본 ------------------------------------------------------------------ */
static int test_on;
static int test_real;         /* SOCREAL=1: 대본을 쓰되 실제 시간에 맞춰 (486 속도 시험) */
static struct {
    uint32_t t;
    int what;           /* 'k' 키, 's' 찍기, 'q' 끝 */
    int sc;
    char name[16];
} tev[4096];
static int ntev, tpos;

static int keycode(const char *k)
{
    static const struct { const char *n; int sc; } T[] = {
        {"enter", 0x1C}, {"up", 0x48}, {"down", 0x50}, {"left", 0x4B}, {"right", 0x4D}, {"space", 0x39},
        {"esc", 0x01}, {"f1", 0x3B}, {"p", 0x19}, {"y", 0x15}, {"n", 0x31}, {"0", 0x0B}, {"1", 0x02}, {"2", 0x03}};
    unsigned i;
    for (i = 0; i < sizeof T / sizeof T[0]; i++)
        if (!strcmp(T[i].n, k))
            return T[i].sc;
    return 0;
}

static void test_init(const char *fn)
{
    FILE *f = fopen(fn, "r");
    char ln[128], a[32], b[32];
    unsigned t;
    int n, i, j;
    if (!f)
        return;
    while (ntev < 4000 && fgets(ln, sizeof ln, f)) {
        char *h = strchr(ln, '#');
        if (h)
            *h = 0;
        b[0] = 0;
        n = sscanf(ln, "%u %31s %31s", &t, a, b);
        if (n < 2)
            continue;
        if (!strcmp(a, "shot")) {
            tev[ntev].t = t;
            tev[ntev].what = 's';
            strncpy(tev[ntev].name, b, 15);
            ntev++;
        } else if (!strcmp(a, "quit")) {
            tev[ntev].t = t;
            tev[ntev++].what = 'q';
        } else if (a[0] == '+') {
            int sc = keycode(a + 1), hold = n > 2 ? atoi(b) : 8;
            tev[ntev].t = t; tev[ntev].what = 'k'; tev[ntev++].sc = sc;
            tev[ntev].t = t + hold; tev[ntev].what = 'k'; tev[ntev++].sc = sc | 0x80;
        } else {
            tev[ntev].t = t; tev[ntev].what = 'k'; tev[ntev++].sc = (int)strtol(a, 0, 16);
        }
    }
    fclose(f);
    /* 틱 차례로 (같은 틱은 적은 차례대로) */
    for (i = 1; i < ntev; i++)
        for (j = i; j > 0 && tev[j - 1].t > tev[j].t; j--) {
            tev[4095] = tev[j];
            tev[j] = tev[j - 1];
            tev[j - 1] = tev[4095];
        }
    test_on = 1;
    test_real = getenv("SOCREAL") != 0;
}

/* ---- 화면 ----------------------------------------------------------------------- */
static void set_vga(void)
{
    __dpmi_regs r;
    memset(&r, 0, sizeof r);
    r.x.ax = 0x0013;
    __dpmi_int(0x10, &r);
    gfx = 1;
    shown_gen = shown_pal = 0xFFFFFFFF;
}

static void text_mode(void)
{
    __dpmi_regs r;
    if (!no_sound)
        outportb(0x61, (uint8_t)(inportb(0x61) & 0xFC));
    if (!gfx)
        return;
    memset(&r, 0, sizeof r);
    r.x.ax = 0x0003;
    __dpmi_int(0x10, &r);
    gfx = 0;
}

static void set_palette(void)
{
    int i;
#ifdef SOCVGA
    if (socvga_on) {
        const uint8_t *p = socvga_palette();
        outportb(0x3C8, 0);
        for (i = 0; i < 768; i++)
            outportb(0x3C9, (uint8_t)(p[i] >> 2));
        shown_pal = socvga_palgen();
        return;
    }
#endif
    outportb(0x3C8, 0);
    for (i = 0; i < 16; i++) {
        uint8_t c[3];
        ega_rgb(V.atc[i], c);
        outportb(0x3C9, c[0] >> 2);
        outportb(0x3C9, c[1] >> 2);
        outportb(0x3C9, c[2] >> 2);
    }
    shown_pal = V.palgen;
}

/* VGA 메모리에 바로 쓴다 (nearptr 가 되면) */
static uint8_t *vram;
static uint8_t *frame_dst(void)
{
    if (!vram && __djgpp_nearptr_enable())
        vram = (uint8_t *)(0xA0000 + __djgpp_conventional_base);
    return vram ? vram : vbuf;
}
static void frame_done(uint8_t *d)
{
    if (d == vbuf)
        dosmemput(vbuf, 64000, 0xA0000);
}

static void present(void)
{
    uint32_t start;
    uclock_t a;
    if (!gfx)
        return;
    a = uclock();
#ifdef SOCVGA
    if (socvga_on) {
        if (shown_pal != socvga_palgen())
            set_palette();
        {
            uint8_t *d = frame_dst();
            if (!socvga_frame(d))
                return;
            frame_done(d);
        }
        goto done;
    }
#endif
    if (shown_pal != V.palgen)
        set_palette();
    start = vga_start();
    if (shown_gen == V.gen && shown_start == start && shown_pan == V.pan)
        return;
    {
        uint8_t *d = frame_dst();
        vga_frame(start, d);
        frame_done(d);
    }
    shown_gen = V.gen;
    shown_start = start;
    shown_pan = V.pan;
#ifdef SOCVGA
done:
#endif
    st_pres++;
    last_present = uclock();
    st_prest += last_present - a;
}

static void save_bmp(const char *name)
{
    uint8_t hdr[54];
    char fn[40];
    FILE *f;
    int y, i;
    uint32_t v;
    present();
    sprintf(fn, "%s.BMP", name);
    if (!(f = fopen(fn, "wb")))
        return;
    memset(hdr, 0, sizeof hdr);
    hdr[0] = 'B';
    hdr[1] = 'M';
    v = 54 + 1024 + 64000; memcpy(hdr + 2, &v, 4);
    v = 54 + 1024; memcpy(hdr + 10, &v, 4);
    v = 40; memcpy(hdr + 14, &v, 4);
    v = 320; memcpy(hdr + 18, &v, 4);
    v = 200; memcpy(hdr + 22, &v, 4);
    hdr[26] = 1;
    hdr[28] = 8;
    fwrite(hdr, 1, 54, f);
    outportb(0x3C7, 0);
    for (i = 0; i < 256; i++) {
        uint8_t q[4];
        q[2] = (uint8_t)(inportb(0x3C9) << 2);
        q[1] = (uint8_t)(inportb(0x3C9) << 2);
        q[0] = (uint8_t)(inportb(0x3C9) << 2);
        q[3] = 0;
        fwrite(q, 1, 4, f);
    }
    dosmemget(0xA0000, 64000, vbuf);
    for (y = 199; y >= 0; y--)
        fwrite(vbuf + y * 320, 1, 320, f);
    fclose(f);
}

/* ---- 플랫폼 ---------------------------------------------------------------------- */
static jmp_buf game_out;

void plat_mode(int mode)
{
    if (mode == 0x0D) {
        if (!gfx)
            set_vga();
#ifdef SOCVGA
        socvga_mode(mode);
#endif
    } else
        text_mode();
}

void plat_tick(uint32_t tick)
{
#ifdef SOCVGA
    socsnd_tick();
#endif
    if (test_on) {
        while (tpos < ntev && tev[tpos].t <= tick && tev[tpos].what != 'k') {
            if (tev[tpos].what == 's')
                save_bmp(tev[tpos].name);
            else {
                FILE *f = fopen("SOCLOG.TXT", "w");
                if (f) {
                    double el = (double)(uclock() - t_run0) / UCLOCKS_PER_SEC;
                    fprintf(f, "tick %lu in %.1f s (%.0f ticks/s, real game = 120), presents %ld avg %.2f ms, behind %ld\n",
                            (unsigned long)tick, el, el > 0 ? tick / el : 0.0, st_pres,
                            st_pres ? (double)st_prest * 1000.0 / UCLOCKS_PER_SEC / st_pres : 0.0, st_behind);
                    {
                        int q;
                        for (q = 0; q < st_behind && q < 32; q++)
                            fprintf(f, "%lu ", (unsigned long)st_btick[q]);
                        fputc('\n', f);
                    }
                    fclose(f);
                }
                text_mode();
                kb_remove();
                exit(0);
            }
            tpos++;
        }
        if (!test_real) {
            if ((tick & 1) == 0)
                present();
            return;
        }
    }
    if (quit_req) {
        quit_req = 0;
        longjmp(game_out, 1);
    }
#ifdef SOCVGA
    if (socsnd_hold) {          /* 킥오프 휘슬: 화면을 세운 채 휘슬이 먼저 들리게 */
        uclock_t d = (uclock_t)socsnd_hold * UCLOCKS_PER_SEC / 120, e = uclock() + d;
        socsnd_hold = 0;
        while (uclock() < e)
            ;
        t0 += d;
    }
#endif
    {
        uclock_t want = t0 + (uclock_t)((double)tick * UCLOCKS_PER_SEC / 120.0);
        uclock_t now = uclock();
        if (now > want + UCLOCKS_PER_SEC / 4) {        /* 너무 뒤처짐: 기준을 다시 잡는다 */
            if (st_behind < 32)
                st_btick[st_behind] = tick;
            st_behind++;
            t0 = now - (uclock_t)((double)tick * UCLOCKS_PER_SEC / 120.0);
            want = now;
        }
        /* 화면: 게임이 쪽을 넘기면 (CRTC 시작 주소가 바뀜 = 다 그린 쪽) 그때 보인다 -> 반쯤 그린 화면을
         * 합성하지 않아 빠르고 찢김도 없다.  뒤처졌으면 넘김을 건너뛰되 1/12 초에 한 장은.
         * 쪽을 넘기지 않는 화면 (메뉴 등, 0.3 초 넘게 넘김 없음) 은 1/30 초마다 */
        {
            static uint32_t seen_start = 0xFFFFFFFF;
            static uclock_t last_flip;
            static int pending;
            uint32_t st = vga_start();
            if (st != seen_start) {
                seen_start = st;
                last_flip = now;
                pending = 1;
            }
            if (pending) {
                if (now < want + UCLOCKS_PER_SEC / 60 || now - last_present > UCLOCKS_PER_SEC / 12) {
                    present();
                    pending = 0;
                }
            } else if (now - last_flip > UCLOCKS_PER_SEC * 3 / 10 && now - last_present > UCLOCKS_PER_SEC / 30)
                present();
        }
        while ((now = uclock()) < want)
            ;
    }
}

int plat_key(uint32_t tick)
{
    if (test_on) {
        if (tpos < ntev && tev[tpos].what == 'k' && tev[tpos].t <= tick)
            return tev[tpos++].sc;
        return -1;
    }
    if (kq_tail != kq_head) {
        int k = kq[kq_tail];
        kq_tail = (kq_tail + 1) & (KQ - 1);
        return k;
    }
    return -1;
}

void plat_sound(uint16_t port, uint8_t v)
{
    if (no_sound)
        return;
#ifdef SOCVGA
    if (socsnd_on)
        return;                 /* 소리는 애드립 쪽에서 (socsnd.c) */
#endif
    if (port == 0x43 && (v & 0xC0) != 0x80)
        return;                 /* 채널 0 은 우리가 쓰지 않는다 (시간은 uclock) */
    outportb(port, v);
}

uint8_t plat_joy(void)
{
    return inportb(0x201);
}

void plat_exit(int code)
{
    (void)code;
    longjmp(game_out, 2);
}

void plat_fatal(const char *msg)
{
    text_mode();
    kb_remove();
    printf("%s\n", msg);
    exit(1);
}

static void on_break(int sig)
{
    (void)sig;
    text_mode();
    kb_remove();
    exit(1);
}

/* ---- SOCCER.COM 처럼 고르기 ------------------------------------------------------ */
/* 80 칸 화면 가운데에 */
#define BOXW 60
static void box_line(int l, int m, int r, const char *text)
{
    int i, n = (int)strlen(text), x0 = (BOXW - n) / 2;
    gotoxy((80 - BOXW - 2) / 2 + 1, wherey());
    putch(l);
    for (i = 0; i < BOXW; i++)
        putch(i >= x0 && i < x0 + n ? text[i - x0] : m);
    putch(r);
    putch(13);
    putch(10);
}

static void center(const char *text)
{
    gotoxy((80 - (int)strlen(text)) / 2 + 1, wherey());
    cprintf("%s\r\n", text);
}

/* 여러 줄을 한 덩어리로 가운데 (왼쪽 끝을 맞춘다) */
static void block(const char *const *lines, int n, int gap)
{
    int i, w = 0, x;
    for (i = 0; i < n; i++)
        if ((int)strlen(lines[i]) > w)
            w = (int)strlen(lines[i]);
    x = (80 - w) / 2 + 1;
    for (i = 0; i < n; i++) {
        gotoxy(x, wherey());
        cprintf("%s\r\n", lines[i]);
        if (gap && i < n - 1)
            cprintf("\r\n");
    }
}

static int menu(void)
{
    static const char *const opts[] = {"1) Indoor Game", "2) Outdoor Game", "3) Exit to DOS"};
    static const char *const keys[] = {"Player 1 : W E R / S F / X C V, Space",
                                       "Player 2 : keypad, Enter"};
    int k;
    textmode(C80);
    textbackground(BLUE);
    clrscr();
    textcolor(WHITE);
    cprintf("\r\n");
    box_line(201, 205, 187, "");
    box_line(186, ' ', 186, "");
    box_line(186, ' ', 186, "Welcome to MicroProse Pro Soccer");
    box_line(186, ' ', 186, "");
    box_line(186, ' ', 186, "IBM version by Designer Software");
#ifdef SOCVGA
    box_line(186, ' ', 186, "256-colour VGA remaster");
    box_line(186, ' ', 186, "");
    box_line(186, ' ', 186, "VGA REMASTER BY IN-HAK MIN");
#else
    box_line(186, ' ', 186, "C port");
#endif
    box_line(186, ' ', 186, "");
    box_line(200, 205, 188, "");
    cprintf("\r\n");
    textcolor(YELLOW);
    center("Please select your favorite option");
    cprintf("\r\n");
    textcolor(LIGHTGRAY);
    block(opts, 3, 1);
    cprintf("\r\n");
    textcolor(LIGHTCYAN);
    block(keys, 2, 0);
    cprintf("\r\n");
    center("Ctrl+Q returns to this menu");
    _setcursortype(_NOCURSOR);
    if (getenv("SOCMENUSHOT")) {        /* 시험: 글자 화면을 파일로 떠 두고 끝 */
        FILE *f = fopen("MENU.TXT", "w");
        int y, x;
        for (y = 0; y < 25 && f; y++) {
            for (x = 0; x < 80; x++)
                fputc(_farpeekb(_dos_ds, 0xB8000 + (y * 80 + x) * 2), f);
            fputc('\n', f);
        }
        if (f)
            fclose(f);
        return -1;
    }
    for (;;) {
        k = getch();
        if (k == '1' || k == '2' || k == '3' || k == 27)
            break;
    }
    _setcursortype(_NORMALCURSOR);
    if (k == '1' || k == '2')
        return k - '1';
    return -1;
}

int main(int argc, char **argv)
{
    static uint8_t comm[32];
    int game = -1;
    const char *ts = getenv("SOCTEST");
    signal(SIGINT, on_break);
    uclock();
    if (ts)
        test_init(ts);
    /* 시험 모드이거나 SOCNOSND=1 이면 소리 없음 */
    no_sound = (ts != 0 && !getenv("SOCSNDTEST")) || getenv("SOCNOSND") != 0;   /* SOCSNDTEST: 시험 중에도 애드립 경로를 (믹서 무음으로) */
    if (argc > 1 && (argv[1][0] == '1' || argv[1][0] == 'i' || argv[1][0] == 'I'))
        game = 0;
    if (argc > 1 && (argv[1][0] == '2' || argv[1][0] == 'o' || argv[1][0] == 'O'))
        game = 1;
#ifdef SOCVGA
    if (!getenv("SOCEGA") && !socvga_load("SOCVGA.DAT"))
        printf("SOCVGA.DAT not found - running with EGA colours\n");
    /* 애드립이 있고 SOUND.DAT 이 있으면 원판 PC 스피커 소리를 애드립 VGM 으로 */
    if (!no_sound && !getenv("SOCSPK") && socsnd_init("SOUND.DAT"))
    {
        socvga_sound = socsnd_trigger;
        socvga_kick = socsnd_kick;
        socvga_foul = socsnd_foul;
        socvga_restart = socsnd_restart;
    }
    if (getenv("SOCSNDTEST"))
        printf("adlib %s, sb pcm %s\n", socsnd_on ? "on" : "off", socsnd_pcm() ? "on" : "off");
#endif
    for (;;) {
        int g = game >= 0 ? game : menu();
        if (g < 0)
            break;
        soc_init(g, 'E');
#ifdef SOCVGA
        socvga_game(g);
        socsnd_game(g);
#endif
        memcpy(M + 0xE000, comm, sizeof comm);
        kb_install();
        t0 = t_run0 = uclock();
        if (!setjmp(game_out))
            soc_run();
        memcpy(comm, M + 0xE000, sizeof comm);
#ifdef SOCVGA
        socsnd_stop();
#endif
        kb_remove();
        text_mode();
        if (game >= 0 || test_on)
            break;
    }
#ifdef SOCVGA
    socsnd_shutdown();
#endif
    textmode(C80);
    normvideo();
    clrscr();
    return 0;
}
