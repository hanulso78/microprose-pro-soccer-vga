/* hosttest.c - 옮긴 C 를 윈도우(호스트)에서 키 대본대로 돌려 폴마다 상태를 적는다 (tools/emu.py 와 대조)
 *
 *   hosttest in|out 대본.txt 최대틱 기록.txt [틱:이름.bmp ...]
 *   대본 줄: "틱 +키 [누름틱]"  또는 "틱 스캔16진"
 *   기록 줄 (폴마다): 폴번호 틱 irq AX BX CX DX SI DI BP SP CS DS ES SS 메모리CRC EGA CRC
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <direct.h>
#define mkdir(p) _mkdir(p)
#include "../cpu.h"
#include "../vga.h"
#include "../plat.h"
#ifdef SOCVGA
#include "../socvga.h"
#endif

char plat_datadir[260] = "orig/";
char plat_savedir[260] = "_save/";
static FILE *trace;
static uint32_t maxticks;
static struct {
    uint32_t t;
    int sc;
} ev[4096];
static int nev, evpos;
static struct {
    uint32_t t;
    char name[64];
} shots[256];
static int nshots;
static int every = 1;

static uint32_t crc_tab[256];
static void crc_init(void)
{
    uint32_t i, j, c;
    for (i = 0; i < 256; i++) {
        c = i;
        for (j = 0; j < 8; j++)
            c = (c & 1) ? 0xEDB88320u ^ (c >> 1) : c >> 1;
        crc_tab[i] = c;
    }
}
static uint32_t crc32(const uint8_t *p, uint32_t n, uint32_t c)
{
    c = ~c;
    while (n--)
        c = crc_tab[(c ^ *p++) & 0xFF] ^ (c >> 8);
    return ~c;
}

static void save_bmp(const char *name)
{
    static uint8_t px[320 * 200];
    uint8_t hdr[54 + 1024];
    FILE *f = fopen(name, "wb");
    int i, y;
    uint32_t sz = 54 + 1024 + 320 * 200;
    if (!f)
        return;
#ifdef SOCVGA
    if (socvga_on) {
        const uint8_t *p = socvga_palette();
        static uint8_t tmp[64000];
        uint32_t sz2 = 54 + 1024 + 64000;
        if (!socvga_frame(tmp)) {
            /* 바뀐 것이 없어도 찍는다 */
        }
        memcpy(px, tmp, 64000);
        memset(hdr, 0, sizeof hdr);
        hdr[0] = 'B'; hdr[1] = 'M';
        memcpy(hdr + 2, &sz2, 4);
        hdr[10] = (uint8_t)((54 + 1024) & 0xFF); hdr[11] = (uint8_t)((54 + 1024) >> 8);
        hdr[14] = 40;
        hdr[18] = 320 & 0xFF; hdr[19] = 320 >> 8;
        hdr[22] = 200;
        hdr[26] = 1; hdr[28] = 8;
        for (i = 0; i < 256; i++) {
            hdr[54 + i * 4] = p[i * 3 + 2];
            hdr[54 + i * 4 + 1] = p[i * 3 + 1];
            hdr[54 + i * 4 + 2] = p[i * 3];
        }
        fwrite(hdr, 1, sizeof hdr, f);
        for (y = 199; y >= 0; y--)
            fwrite(px + y * 320, 1, 320, f);
        fclose(f);
#ifdef SOCDBG
        {       /* 문맥 종류 지도: 이름.kind (320x200 바이트) */
            extern uint8_t vkind[];
            char kn[80];
            FILE *g;
            uint32_t st = vga_start(), yy, xx;
            snprintf(kn, sizeof kn, "%s.kind", name);
            if ((g = fopen(kn, "wb")) != 0) {
                for (yy = 0; yy < 200; yy++)
                    for (xx = 0; xx < 320; xx++)
                        fputc(vkind[((st + yy * 40 + xx / 8) & 0xFFFF) * 8 + (xx & 7)], g);
                fclose(g);
            }
        }
#endif
        return;
    }
#endif
    vga_frame(vga_start(), px);
    memset(hdr, 0, sizeof hdr);
    hdr[0] = 'B'; hdr[1] = 'M';
    memcpy(hdr + 2, &sz, 4);
    hdr[10] = (uint8_t)((54 + 1024) & 0xFF); hdr[11] = (uint8_t)((54 + 1024) >> 8);
    hdr[14] = 40;
    hdr[18] = 320 & 0xFF; hdr[19] = 320 >> 8;
    hdr[22] = 200;
    hdr[26] = 1; hdr[28] = 8;
    for (i = 0; i < 16; i++) {
        uint8_t rgb[3];
        ega_rgb(V.atc[i], rgb);
        hdr[54 + i * 4] = rgb[2];
        hdr[54 + i * 4 + 1] = rgb[1];
        hdr[54 + i * 4 + 2] = rgb[0];
    }
    fwrite(hdr, 1, sizeof hdr, f);
    for (y = 199; y >= 0; y--)
        fwrite(px + y * 320, 1, 320, f);
    fclose(f);
}

void plat_tick(uint32_t tick)
{
    int i;
    static int panlog = -1;
    if (panlog < 0)
        panlog = getenv("PANLOG") != 0;
    if (panlog) {
        static int lp = -1;
        static uint32_t ls = 0xFFFFFFFF;
        if (V.pan != lp || vga_start() != ls)
            fprintf(stderr, "pan %lu %d start %04lx lc %02x hde %02x ofs %02x\n", (unsigned long)tick, V.pan,
                    (unsigned long)vga_start(), V.crtc[0x18], V.crtc[1], V.crtc[0x13]);
        lp = V.pan;
        ls = vga_start();
    }
    for (i = 0; i < nshots; i++)
        if (shots[i].t == tick) {
            if (!strncmp(shots[i].name, "vram", 4)) {       /* 평면 메모리 통째로 (64KB x 4) */
                FILE *d = fopen(shots[i].name, "wb");
                static uint8_t pl[0x10000];
                int p;
                for (p = 0; p < 4; p++) {
                    vga_plane(p, pl);
                    fwrite(pl, 1, 0x10000, d);
                }
                fwrite(V.atc, 1, 16, d);
                fclose(d);
            } else
                save_bmp(shots[i].name);
        }
    if (tick >= maxticks) {
        if (trace)
            fclose(trace);
        printf("done: %lu ticks, %lu polls, %lu irqs, vga rb %lu wb %lu\n", (unsigned long)soc_ticks,
               (unsigned long)soc_npoll, (unsigned long)soc_nirq, vga_nrb, vga_nwb);
#ifdef SOCDBG
        {
            extern unsigned long socvga_nshade[16], socvga_nshade8[16], fspr_n[4];
            printf("fast_spr3 fast %lu slow %lu\n", fspr_n[1], fspr_n[0]);
            int k;
            for (k = 0; k < 10; k++)
            {
                extern unsigned long vga_wbk[16], vga_rbk[16];
                printf("kind %d: shade8 %lu, shade %lu, wb %lu, rb %lu\n", k, socvga_nshade8[k], socvga_nshade[k],
                       vga_wbk[k], vga_rbk[k]);
            }
        }
#endif
        exit(0);
    }
}

int plat_key(uint32_t tick)
{
    if (evpos < nev && ev[evpos].t <= tick)
        return ev[evpos++].sc;
    return -1;
}

static void hook(int irq)
{
    uint32_t c1, c2;
    static long dumpat = -2;
    if (dumpat == -2)
        dumpat = getenv("DUMPAT") ? atol(getenv("DUMPAT")) : -1;
    if (dumpat >= 0 && soc_npoll == (uint32_t)dumpat) {
        FILE *d = fopen("_host_dump.bin", "wb");
        static uint8_t pl[0x10000];
        int p;
        fwrite(M, 1, 0xA0000, d);
        for (p = 0; p < 4; p++) {
            vga_plane(p, pl);
            fwrite(pl, 1, 0x10000, d);
        }
        fclose(d);
    }
    if (!trace || soc_npoll % every)
        return;
    c1 = crc32(M, 0xA0000, 0);
    {
        static uint8_t pl[0x10000];
        int p;
        c2 = 0;
        for (p = 0; p < 4; p++) {
            vga_plane(p, pl);
            c2 = crc32(pl, 0x10000, c2);
        }
    }
    fprintf(trace, "%lu %lu %d %04X %04X %04X %04X %04X %04X %04X %04X %04X %04X %04X %04X %08X %08X\n",
            (unsigned long)soc_npoll, (unsigned long)soc_ticks, irq, AX, BX, CX, DX, SI, DI, BP, SP, CS_, DS_, ES_, SS_,
            (unsigned)c1, (unsigned)c2);
}

void plat_sound(uint16_t port, uint8_t v) { (void)port; (void)v; }
uint8_t plat_joy(void) { return 0xFF; }
void plat_mode(int mode)
{
#ifdef SOCVGA
    socvga_mode(mode);
#else
    (void)mode;
#endif
}

void plat_exit(int code)
{
    if (trace)
        fclose(trace);
    printf("exit %d at tick %lu\n", code, (unsigned long)soc_ticks);
    exit(0);
}

void plat_fatal(const char *msg)
{
    if (trace)
        fclose(trace);
    printf("FATAL %s\n", msg);
    exit(1);
}

static int keycode(const char *k)
{
    static const struct { const char *n; int sc; } T[] = {
        {"enter", 0x1C}, {"up", 0x48}, {"down", 0x50}, {"left", 0x4B}, {"right", 0x4D}, {"space", 0x39},
        {"esc", 0x01}, {"f1", 0x3B}, {"p", 0x19}, {"y", 0x15}, {"n", 0x31}, {"0", 0x0B}, {"1", 0x02}, {"2", 0x03}};
    unsigned i;
    for (i = 0; i < sizeof T / sizeof T[0]; i++)
        if (!strcmp(T[i].n, k))
            return T[i].sc;
    fprintf(stderr, "unknown key %s\n", k);
    exit(2);
}

static int cmpev(const void *a, const void *b)
{
    const uint32_t *x = a, *y = b;
    return *x < *y ? -1 : *x > *y;
}

#ifdef SOCVGA
static void sndlog(int ax, int si)
{
    fprintf(stderr, "snd %lu ax %d si %d\n", (unsigned long)soc_ticks, ax, si);
}

static void foullog(void)
{
    uint32_t ds = LIN(DS_, 0), a = ds + (M[ds + 0x42] | M[ds + 0x43] << 8) + 1;
    fprintf(stderr, "foul %lu ", (unsigned long)soc_ticks);
    while (M[a] && M[a] < 0x80)
        fputc(M[a++], stderr);
    fputc(10, stderr);
}

static void restartlog(int type)
{
    fprintf(stderr, "restart %lu %d\n", (unsigned long)soc_ticks, type);
}

static void kicklog(void)
{
    fprintf(stderr, "kick %lu\n", (unsigned long)soc_ticks);
}
#endif

int main(int argc, char **argv)
{
    FILE *f;
    char ln[256];
    int i;
    if (argc < 5) {
        fprintf(stderr, "usage: hosttest in|out script maxticks trace [tick:name.bmp...]\n");
        return 2;
    }
    crc_init();
#ifdef SAMPLER
    { extern void sampler_start(void); sampler_start(); }
#endif
    system("if exist _save rmdir /s /q _save");
    mkdir("_save");
    f = fopen(argv[2], "r");
    if (!f) {
        perror(argv[2]);
        return 2;
    }
    while (fgets(ln, sizeof ln, f)) {
        char *h = strchr(ln, '#'), k[64];
        unsigned t;
        int hold = 8;
        if (h)
            *h = 0;
        if (sscanf(ln, "%u %63s %d", &t, k, &hold) < 2)
            continue;
        if (k[0] == '+') {
            int sc = keycode(k + 1);
            ev[nev].t = t; ev[nev++].sc = sc;
            ev[nev].t = t + hold; ev[nev++].sc = sc | 0x80;
        } else {
            ev[nev].t = t; ev[nev++].sc = (int)strtol(k, 0, 16);
        }
    }
    fclose(f);
    qsort(ev, nev, sizeof ev[0], cmpev);
    maxticks = (uint32_t)atoi(argv[3]);
    if (strcmp(argv[4], "-"))
        trace = fopen(argv[4], "w");
    if (getenv("EVERY"))
        every = atoi(getenv("EVERY"));
    for (i = 5; i < argc && nshots < 256; i++) {
        char *c = strchr(argv[i], ':');
        if (!c)
            continue;
        shots[nshots].t = (uint32_t)atoi(argv[i]);
        snprintf(shots[nshots].name, sizeof shots[nshots].name, "%s", c + 1);
        nshots++;
    }
    soc_init(!strcmp(argv[1], "out"), 'E');
#ifdef SOCVGA
    if (!getenv("SOCEGA"))
        socvga_load(getenv("SOCVGADAT") ? getenv("SOCVGADAT") : "SOCVGA.DAT");
    socvga_game(!strcmp(argv[1], "out"));
    if (getenv("SNDLOG"))
    {
        socvga_sound = sndlog;
        socvga_kick = kicklog;
        socvga_foul = foullog;
        socvga_restart = restartlog;
    }
#endif
    soc_poll_hook = hook;
    soc_run();
    printf("returned at tick %lu\n", (unsigned long)soc_ticks);
    if (trace)
        fclose(trace);
    return 0;
}
