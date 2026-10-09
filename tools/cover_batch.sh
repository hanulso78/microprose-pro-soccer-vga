#!/bin/sh
# 원숭이 대본 여러 개로 커버리지 모으기 (실내/실외), 끝나면 다시 번역
#   sh tools/cover_batch.sh 첫씨앗 끝씨앗 틱수 [in|out|both]
cd "$(dirname "$0")/.."
P=/c/python-3.12.10-embed-amd64/python.exe
export PYTHONIOENCODING=utf-8
games=${4:-both}
[ "$games" = both ] && games="in out"
for g in $games; do
    for s in $(seq $1 $2); do
        $P tools/monkey.py $s $3 > test/mk_${g}_$s.txt
        SOCGAME=$g $P tools/cover2.py test/mk_${g}_$s.txt $3
    done
done
sh regen.sh
