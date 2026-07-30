#!/bin/bash
# Unprompt デモ動画 v1 ビルド (take1_full.mp4 → unprompt_demo_v1.mp4)
# クロップ: ブラウザ枠・デバッグバナー除外 / 静寂セグメントは等速 / 倍速はテロップ開示
set -e
S="/private/tmp/claude-501/-Users-kishimotosatoshi-Documents-MERGE2026-MERGE2026-FABLE5-AUTONOMOUS-DELIBERATION-v4-0-20260728/89c56fd4-883d-45e5-9bdc-87446ac8a2c9/scratchpad"
IN="$S/take1_full.mp4"
F="/System/Library/Fonts/ヒラギノ角ゴシック W4.ttc"
BASE="crop=2836:1595:104:291,scale=1920:1080"
TSTYLE="fontfile=$F:fontcolor=white:fontsize=40:box=1:boxcolor=0x15171C@0.72:boxborderw=18:x=(w-text_w)/2:y=h-130"

seg() { # id start end speed text(ignored; telop PNG t_$id.png を使用)
  local id=$1 st=$2 en=$3 sp=$4
  local dur=$(python3 -c "print($en-$st)")
  ffmpeg -y -ss $st -t $dur -i "$IN" -i "$S/telops/t_$id.png" \
    -filter_complex "[0:v]$BASE,setpts=PTS/$sp,fps=30[v];[v][1:v]overlay=0:860" \
    -an -c:v libx264 -preset medium -crf 18 -pix_fmt yuv420p "$S/seg_$id.mp4" 2>"$S/seg_$id.log"
  echo "seg_$id done"
}

seg A 3.0   17.5  1    '曖昧な一文を、そのままタイプする'
seg B 17.5  34.0  1    '生成しない。問いを組み立てる ― 静寂 17.8秒(実測・等速)'
seg C 34.0  146.0 14   '5つの判断点と見本を実生成中(×14倍速)'
seg D 146.0 159.0 1    '見本をクリックで「決める」。決めないなら「委ねる」'
seg E 159.0 179.0 4    '残りはAIのおすすめで(×4倍速)'
seg F 179.0 186.0 1    '未決 0 ― おすすめの理由も明示される'
seg G 205.0 210.0 1    '意図の指示書へコンパイル'
seg H 210.0 235.0 4    'コンパイル中(×4倍速)'
seg I 235.5 277.0 1.75 'タイプは最初の一文だけ。あとは選択5回・追加タイプ0字(×1.75倍速)'
seg J 277.0 299.5 1    '同じ指示書で作らせた実例 ― 一文だけ、との並置'

printf "file 'seg_A.mp4'\nfile 'seg_B.mp4'\nfile 'seg_C.mp4'\nfile 'seg_D.mp4'\nfile 'seg_E.mp4'\nfile 'seg_F.mp4'\nfile 'seg_G.mp4'\nfile 'seg_H.mp4'\nfile 'seg_I.mp4'\nfile 'seg_J.mp4'\n" > "$S/concat.txt"
ffmpeg -y -f concat -safe 0 -i "$S/concat.txt" -f lavfi -i anullsrc=r=48000:cl=stereo -shortest -c:v copy -c:a aac -b:a 96k -movflags +faststart "$S/unprompt_demo_v1.mp4" 2>"$S/concat.log"
ffprobe -v error -show_entries format=duration -of default=nw=1 "$S/unprompt_demo_v1.mp4"
