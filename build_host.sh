#!/bin/sh
# 호스트(윈도우, MSYS2 mingw gcc) 시험판: hosttest.exe
#   sh build_host.sh
set -e
cd "$(dirname "$0")"
export PATH=/c/MSYS2/mingw64/bin:$PATH
CC="gcc -O1 -w"
mkdir -p obj_host
for f in soc_in soc_out socimg_in socimg_out socrt vga socfast; do
    if [ ! -f obj_host/$f.o ] || [ $f.c -nt obj_host/$f.o ] || [ cpu.h -nt obj_host/$f.o ]; then
        echo cc $f.c
        $CC -c $f.c -o obj_host/$f.o
    fi
done
$CC -o hosttest.exe tools/hosttest.c obj_host/soc_in.o obj_host/soc_out.o obj_host/socimg_in.o obj_host/socimg_out.o obj_host/socrt.o obj_host/vga.o obj_host/socfast.o
echo built hosttest.exe
# 256색 개선판 시험판: hostvga.exe
CV="gcc -O1 -w -DSOCVGA -DSOCDBG"
for f in soc_in soc_out vga socvga socrt socfast; do
    if [ ! -f obj_host/$f.vo ] || [ $f.c -nt obj_host/$f.vo ] || [ cpu.h -nt obj_host/$f.vo ] || [ socvga.h -nt obj_host/$f.vo ]; then
        echo cc -DSOCVGA $f.c
        $CV -c $f.c -o obj_host/$f.vo
    fi
done
$CV -o hostvga.exe tools/hosttest.c obj_host/soc_in.vo obj_host/soc_out.vo obj_host/socimg_in.o obj_host/socimg_out.o obj_host/socrt.vo obj_host/vga.vo obj_host/socvga.vo obj_host/socfast.vo
echo built hostvga.exe
