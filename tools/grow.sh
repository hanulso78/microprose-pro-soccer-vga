#!/bin/sh
# 대본 하나로 커버리지 넓히기: 에뮬레이터로 돌려 새 블록이 나오면 다시 번역하고 대조한다
#   sh tools/grow.sh 대본 틱수 이름     (SOCGAME=in|out)
cd "$(dirname "$0")/.."
P=/c/python-3.12.10-embed-amd64/python.exe
export PYTHONIOENCODING=utf-8
for k in 1 2 3; do
    out=$($P tools/difftest.py "$1" "$2" "$3")
    echo "$out" | tail -4
    if echo "$out" | grep -q "cover: +"; then
        sh regen.sh | tail -3
    else
        break
    fi
done
