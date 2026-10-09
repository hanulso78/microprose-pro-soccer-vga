/* ============================================================================
 *  cpu.h  -  옮긴 코드(soc_in.c / soc_out.c)가 쓰는 8086 상태와 메모리
 * ----------------------------------------------------------------------------
 *  원본은 손 어셈블리 (MicroProse Soccer, Designer Software 1989 IBM 판) 와 그림
 *  드라이버 EGAIO.EXE 이다.  옮긴 C 는 프로그램 전체가 함수 하나이고, 레지스터는 전역
 *  변수, 메모리는 실모드 주소 그대로인 평면 배열 M[] (1MB + 64KB) 이다.
 *  세그먼트:오프셋 계산, 16비트 넘침, 스택 내용까지 원본과 같아서 에뮬레이터
 *  (tools/emu.py)와 메모리를 통째로 대조할 수 있다.
 *
 *  A0000-AFFFF : EGA 평면 메모리 -> vga_rb / vga_wb
 *
 *  인터럽트: 타이머(int 8, 120Hz) 와 자판(int 9) 은 폴 지점(대기 루프가 다시 돌 때)
 *  에서만 넣는다 (POLL_POINT).  에뮬레이터도 같은 자리, 같은 규칙.
 * ========================================================================== */
#ifndef CPU_H
#define CPU_H

#include <stdint.h>
#include <string.h>

#define LOADSEG 0x1000
#define PSPSEG (LOADSEG - 0x10)
#define DRVSEG 0x2200
#define SEG(x) ((uint16_t)(LOADSEG + (x)))
#define MEMSIZE 0x110000
/* dispatch 열쇠: LOADSEG 기준 선형 주소 */
#define KEY(s, o) ((((uint32_t)(uint16_t)((s) - LOADSEG)) << 4) + (uint16_t)(o))

extern uint8_t M[MEMSIZE];

typedef union {
    uint16_t x;
    struct {
        uint8_t l, h;
    } b;
} reg16_t;

extern reg16_t cpu_a, cpu_b, cpu_c, cpu_d;
extern uint16_t SI, DI, BP, SP, CS_, DS_, ES_, SS_;
extern int CF, ZF, SF, OF, DF, IF_;

#define AX cpu_a.x
#define AL cpu_a.b.l
#define AH cpu_a.b.h
#define BX cpu_b.x
#define BL cpu_b.b.l
#define BH cpu_b.b.h
#define CX cpu_c.x
#define CL cpu_c.b.l
#define CH cpu_c.b.h
#define DX cpu_d.x
#define DL cpu_d.b.l
#define DH cpu_d.b.h

#define LIN(s, o) (((uint32_t)(uint16_t)(s) << 4) + (uint16_t)(o))

/* 플래그 낱말 (pushf): C Z S O I D 만 (에뮬레이터도 pushf 뒤 같은 가면을 씌운다) */
#define GETFLAGS() ((uint16_t)(0x0002 | CF | (ZF << 6) | (SF << 7) | (IF_ << 9) | (DF << 10) | (OF << 11)))
#define SETFLAGS(f) do { uint16_t f_ = (f); CF = f_ & 1; ZF = (f_ >> 6) & 1; SF = (f_ >> 7) & 1; \
        IF_ = (f_ >> 9) & 1; DF = (f_ >> 10) & 1; OF = (f_ >> 11) & 1; } while (0)

/* 런타임 (socrt.c) */
uint8_t vga_rb(uint32_t off);
void vga_wb(uint32_t off, uint8_t v);
void io_out(uint16_t port, uint8_t v);
void io_outw(uint16_t port, uint16_t v);
uint8_t io_in(uint16_t port);
void do_int(int n);
void soc_fault(uint32_t at, int why);
uint32_t soc_unknown(uint32_t key);
int soc_poll(void);
uint16_t irq_enter(int n, uint16_t ret_off);   /* 스택에 FLAGS/CS/IP, CS_ = 처리기, 처리기 오프셋 */
void irq_leave(void);

/* 폴 지점: 대기 루프가 다시 돌 때.  IRQ 가 있으면 처리기로 (돌아올 곳 = 루프 머리) */
#define POLL_POINT(off) do { if (IF_) { int n_ = soc_poll(); \
        if (n_) { uint16_t ip_ = irq_enter(n_, (off)); jkey = KEY(CS_, ip_); goto dispatch; } } } while (0)

#define IS_VGA(a) ((uint32_t)((a) - 0xA0000u) < 0x10000u)

/* EGA 읽기/쓰기 (vga.c: 흔한 경우를 먼저 보는 작은 함수) */
#define VRB(off) vga_rb(off)
#define VWB(off, v) vga_wb(off, v)

static inline __attribute__((always_inline)) uint8_t RB(uint16_t s, uint16_t o)
{
    uint32_t a = LIN(s, o);
    if (IS_VGA(a))
        return VRB(a - 0xA0000u);
    return M[a];
}

static inline __attribute__((always_inline)) uint16_t RW(uint16_t s, uint16_t o)
{
    uint32_t a = LIN(s, o);
    if (IS_VGA(a)) {
        uint8_t lo = VRB(a - 0xA0000u);
        uint8_t hi = RB(s, (uint16_t)(o + 1));
        return (uint16_t)(lo | (hi << 8));
    }
    return (uint16_t)(M[a] | (M[LIN(s, (uint16_t)(o + 1))] << 8));
}

static inline __attribute__((always_inline)) void WB(uint16_t s, uint16_t o, uint8_t v)
{
    uint32_t a = LIN(s, o);
    if (IS_VGA(a)) {
        VWB(a - 0xA0000u, v);
        return;
    }
    M[a] = v;
}

static inline __attribute__((always_inline)) void WW(uint16_t s, uint16_t o, uint16_t v)
{
    uint32_t a = LIN(s, o);
    if (IS_VGA(a)) {
        VWB(a - 0xA0000u, (uint8_t)v);
        WB(s, (uint16_t)(o + 1), (uint8_t)(v >> 8));
        return;
    }
    M[a] = (uint8_t)v;
    M[LIN(s, (uint16_t)(o + 1))] = (uint8_t)(v >> 8);
}

static inline __attribute__((always_inline)) void PUSH(uint16_t v)
{
    SP -= 2;
    WW(SS_, SP, v);
}

static inline __attribute__((always_inline)) uint16_t POP(void)
{
    uint16_t v = RW(SS_, SP);
    SP += 2;
    return v;
}

#define STEP(w) (DF ? (uint16_t)-(w) : (uint16_t)(w))

#ifdef SOCVGA
extern int vga_movs;            /* 256색판: 지금 쓰는 값이 메모리에서 온 것 (movs) 인가 */
#define MOVS_ON() (vga_movs = 1)
#define MOVS_OFF() (vga_movs = 0)
#else
#define MOVS_ON() ((void)0)
#define MOVS_OFF() ((void)0)
#endif

static inline __attribute__((always_inline)) void MOVSB(uint16_t sseg)
{
    MOVS_ON();
    WB(ES_, DI, RB(sseg, SI));
    MOVS_OFF();
    SI += STEP(1);
    DI += STEP(1);
}

static inline __attribute__((always_inline)) void MOVSW(uint16_t sseg)
{
    MOVS_ON();
    WW(ES_, DI, RW(sseg, SI));
    MOVS_OFF();
    SI += STEP(2);
    DI += STEP(2);
}

static inline __attribute__((always_inline)) void REP_MOVSB(uint16_t sseg)
{
    while (CX) {
        MOVSB(sseg);
        CX--;
    }
}

static inline __attribute__((always_inline)) void STOSB(void)
{
    WB(ES_, DI, AL);
    DI += STEP(1);
}

static inline __attribute__((always_inline)) void STOSW(void)
{
    WW(ES_, DI, AX);
    DI += STEP(2);
}

static inline __attribute__((always_inline)) void LODSB(uint16_t sseg)
{
    AL = RB(sseg, SI);
    SI += STEP(1);
}

static inline __attribute__((always_inline)) void LODSW(uint16_t sseg)
{
    AX = RW(sseg, SI);
    SI += STEP(2);
}

#endif
