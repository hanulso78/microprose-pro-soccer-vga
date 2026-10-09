#!/bin/sh
# 번역 다시 만들기 + 호스트 시험판 빌드
set -e
cd "$(dirname "$0")"
P=/c/python-3.12.10-embed-amd64/python.exe
export PYTHONIOENCODING=utf-8
for g in in out; do
    SOCGAME=$g $P tools/asm2c.py
done
sh build_host.sh | tail -1
