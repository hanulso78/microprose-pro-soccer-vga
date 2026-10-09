#!/bin/sh
# 호스트 표본 프로파일: sh tools/prof.sh [vga]  -> 함수별, 원본 주소별 비율
cd "$(dirname "$0")/.."
export PATH=/c/MSYS2/mingw64/bin:$PATH
D=""; [ "$1" = vga ] && D="-DSOCVGA"
for f in soc_in soc_out vga socvga socrt socfast; do gcc -O1 -g -w $D -c $f.c -o obj_prof/$f.o & done; wait
gcc -O1 -g -w $D -DSAMPLER -Wl,--disable-dynamicbase -o hostprof.exe tools/hosttest.c tools/sampler.c obj_prof/*.o obj_host/socimg_in.o obj_host/socimg_out.o -lwinmm
rm -f _samp_all.txt
for k in 1 2 3 4 5 6; do SOCVGADAT=SOCVGA.DAT ./hostprof.exe in test/demo.txt 20000 - >/dev/null; cat _samples.txt >> _samp_all.txt; done
addr2line -e hostprof.exe -f < _samp_all.txt > _lines.txt
/c/python-3.12.10-embed-amd64/python.exe tools/profrep.py
