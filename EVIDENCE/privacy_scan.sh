#!/bin/bash
# 個人情報スキャン(push・提出前に実行する再発防止装置)
# 検出対象: ①実ユーザー名入りローカルパス(/Users/USER 以外の /Users/xxx)
#           ②個人メールらしき文字列(example.com 系プレースホルダ以外の @gmail 等)
#           ③環境変数 PRIVACY_PATTERNS(実名等。公開ファイルに実名を書かないためここには載せない)
#
# 2026-08-03 改訂（本人承認のうえ差し替え。旧版=privacy_scan.backup_20260803_pre_raw_fix.sh）
#   ① --exclude-dir=raw を撤去。除外していた raw/ の中に、この木で最大の
#      demo_video/raw/take1_full.mp4 (約162MB・未編集の画面録画) が入っていたため、
#      「最大のリスクだけ検査していない」状態だった。
#   ② 全 grep の 2>/dev/null を撤去。エラーはファイルへ落とし、出ていたら exit 3 で止める。
#      旧版は grep が壊れても "OK: 個人情報パターンの残存なし" と表示できた。
#   ③ 陽性対照を先に走らせる。必ずヒットする文字列で grep が動くことを証明してから本走査へ入る。
#   ④ 走査したテキストファイル件数を出力する。
#   ⑤ grep できない媒体(動画・画像・音声・PDF)は「未走査」と明示する。検査済みに見せない。
#
# 終了コード: 0=クリーン / 1=ヒットあり / 2=起動失敗 / 3=検査自体が信用できない
cd "$(dirname "$0")/.." || exit 2

INC=(--include='*.py' --include='*.js' --include='*.json' --include='*.txt' \
     --include='*.md' --include='*.html' --include='*.sh' --include='*.css')
EXC=(--exclude-dir=.git --exclude=privacy_scan.sh)   # raw を除外しない
ERR="$(mktemp)"; NG=0

# --- ③ 陽性対照: grep が実際に動くことを先に証明する -------------------------
CANARY_DIR="$(mktemp -d)"; CANARY="$CANARY_DIR/canary.md"
printf '/Users/canaryuser\ncanary@gmail.com\n' > "$CANARY"
if ! grep -qE '/Users/[A-Za-z0-9._-]+' "$CANARY"; then
  echo "FATAL: 陽性対照が失敗した。grep が機能していないので、この後の結果は信用できない。"
  rm -rf "$CANARY_DIR" "$ERR"; exit 3
fi
if ! grep -qE '[A-Za-z0-9._%+-]+@(gmail|yahoo|icloud|outlook|hotmail)\.' "$CANARY"; then
  echo "FATAL: メール検出の陽性対照が失敗した。結果は信用できない。"
  rm -rf "$CANARY_DIR" "$ERR"; exit 3
fi
rm -rf "$CANARY_DIR"
echo "陽性対照: PASS (grep は動作している)"

# --- ④ 走査対象件数 ----------------------------------------------------------
SCANNED=$(grep -rl '' "${INC[@]}" "${EXC[@]}" . 2>>"$ERR" | wc -l | tr -d ' ')
echo "走査対象テキストファイル: ${SCANNED}件"

# --- ② 本走査（エラーを握りつぶさない）--------------------------------------
H1=$(grep -rE '/Users/[A-Za-z0-9._-]+' "${INC[@]}" "${EXC[@]}" . 2>>"$ERR" \
     | grep -v '/Users/USER' | cut -d: -f1 | sort -u)
[ -n "$H1" ] && { echo "NG: 実ユーザー名らしきパス:"; echo "$H1"; NG=1; }

H2=$(grep -rEl '[A-Za-z0-9._%+-]+@(gmail|yahoo|icloud|outlook|hotmail)\.' "${INC[@]}" "${EXC[@]}" . 2>>"$ERR")
[ -n "$H2" ] && { echo "NG: 個人メールらしき文字列:"; echo "$H2"; NG=1; }

if [ -n "$PRIVACY_PATTERNS" ]; then
  H3=$(grep -rEl "$PRIVACY_PATTERNS" "${INC[@]}" "${EXC[@]}" . 2>>"$ERR")
  [ -n "$H3" ] && { echo "NG: PRIVACY_PATTERNS ヒット:"; echo "$H3"; NG=1; }
else
  echo "WARN: PRIVACY_PATTERNS が未設定。実名チェックは実行されていない。"
fi

# --- ⑤ grep できない媒体を「検査済み」に見せない ------------------------------
MEDIA=$(find . -path ./.git -prune -o -type f \
        \( -name '*.mp4' -o -name '*.mov' -o -name '*.png' -o -name '*.jpg' \
           -o -name '*.jpeg' -o -name '*.gif' -o -name '*.m4a' -o -name '*.aiff' \
           -o -name '*.wav' -o -name '*.pdf' \) -print 2>>"$ERR")
if [ -n "$MEDIA" ]; then
  echo "WARN: 以下は本文走査していない。画面録画・画像・音声・PDFは目視確認が必要:"
  echo "$MEDIA" | while IFS= read -r f; do
    [ -n "$f" ] && echo "  $(du -h "$f" 2>/dev/null | cut -f1)	$f"
  done
fi

# --- ② エラーが出ていたら結果を信用しない ------------------------------------
if [ -s "$ERR" ]; then
  echo "FATAL: 走査中に grep/find がエラーを出した。結果は信用できない:"
  cat "$ERR"; rm -f "$ERR"; exit 3
fi
rm -f "$ERR"

[ $NG -eq 0 ] && echo "OK: テキストファイルに個人情報パターンの残存なし（メディアは未走査・上のWARN参照）"
exit $NG
