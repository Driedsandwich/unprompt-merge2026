#!/bin/bash
# 個人情報スキャン(push・提出前に実行する再発防止装置)
# 検出対象: ①実ユーザー名入りローカルパス(/Users/USER 以外の /Users/xxx)
#           ②個人メールらしき文字列(example.com 系プレースホルダ以外の @gmail 等)
#           ③環境変数 PRIVACY_PATTERNS(実名等。公開ファイルに実名を書かないためここには載せない)
# ヒット0件で exit 0。
cd "$(dirname "$0")/.." || exit 2
INC=(--include='*.py' --include='*.js' --include='*.json' --include='*.txt' \
     --include='*.md' --include='*.html' --include='*.sh' --include='*.css')
EXC=(--exclude-dir=.git --exclude-dir=raw --exclude=privacy_scan.sh)
NG=0
H1=$(grep -rE '/Users/[A-Za-z0-9._-]+' "${INC[@]}" "${EXC[@]}" . 2>/dev/null | grep -v '/Users/USER' | cut -d: -f1 | sort -u)
[ -n "$H1" ] && { echo "NG: 実ユーザー名らしきパス:"; echo "$H1"; NG=1; }
H2=$(grep -rEl '[A-Za-z0-9._%+-]+@(gmail|yahoo|icloud|outlook|hotmail)\.' "${INC[@]}" "${EXC[@]}" . 2>/dev/null)
[ -n "$H2" ] && { echo "NG: 個人メールらしき文字列:"; echo "$H2"; NG=1; }
if [ -n "$PRIVACY_PATTERNS" ]; then
  H3=$(grep -rEl "$PRIVACY_PATTERNS" "${INC[@]}" "${EXC[@]}" . 2>/dev/null)
  [ -n "$H3" ] && { echo "NG: PRIVACY_PATTERNS ヒット:"; echo "$H3"; NG=1; }
fi
[ $NG -eq 0 ] && echo "OK: 個人情報パターンの残存なし"
exit $NG
