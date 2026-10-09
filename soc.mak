# ============================================================================
#  MICROPROSE SOCCER (Designer Software 1989 IBM 판) - djgpp 빌드
# ----------------------------------------------------------------------------
#      make -f soc.mak            SOCCER.EXE (원판을 옮긴 것 그대로, EGA 색)
#      make -f soc.mak vga        SOCVGA.EXE (256색 개선판, SOCVGA.DAT 필요)
#      make -f soc.mak clean
# ============================================================================

CC      = gcc
CFLAGS  = -O2 -march=i386 -mtune=i486 -Wall -Wno-unused-label -Wno-unused-variable -Wno-unused-but-set-variable -fno-strict-aliasing
# 옮긴 코드는 함수 하나가 커서 -O1 (hhmack: -O2 가 오히려 느렸다)
CODEFLAGS = -O1 -march=i386 -mtune=i486 -w -fno-strict-aliasing

ORIG    = soc_in.o soc_out.o socimg_in.o socimg_out.o socrt.o vga.o socfast.o sys_dos.o
VGA     = soc_in.vo soc_out.vo socimg_in.o socimg_out.o socrt.vo vga.vo socfast.vo sys_dos.vo socvga.vo socsnd.vo

.PHONY: all vga clean

all: soccer.exe

vga: socvga.exe

soccer.exe: $(ORIG)
	$(CC) $(CFLAGS) -o soccer.exe $(ORIG)
	strip soccer.exe

socvga.exe: $(VGA)
	$(CC) $(CFLAGS) -o socvga.exe $(VGA)
	strip socvga.exe

soc_in.o: soc_in.c cpu.h
	$(CC) $(CODEFLAGS) -c $< -o $@
soc_out.o: soc_out.c cpu.h
	$(CC) $(CODEFLAGS) -c $< -o $@
soc_in.vo: soc_in.c cpu.h socvga.h
	$(CC) $(CODEFLAGS) -DSOCVGA -c $< -o $@
soc_out.vo: soc_out.c cpu.h socvga.h
	$(CC) $(CODEFLAGS) -DSOCVGA -c $< -o $@

socimg_in.o: socimg_in.c
	$(CC) -O0 -c $< -o $@
socimg_out.o: socimg_out.c
	$(CC) -O0 -c $< -o $@

%.o: %.c cpu.h vga.h plat.h
	$(CC) $(CFLAGS) -c $< -o $@

%.vo: %.c cpu.h vga.h plat.h socvga.h socsnd.h
	$(CC) $(CFLAGS) -DSOCVGA -c $< -o $@

clean:
	-del *.o
	-del *.vo
	-del soccer.exe
	-del socvga.exe
