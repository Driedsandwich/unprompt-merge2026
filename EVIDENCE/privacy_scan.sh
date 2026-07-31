#!/bin/bash
# 個人情報スキャン(push・提出前に実行する再発防止装置)
# 検出対象: 実名入りローカルパス / 個人メールアドレス。ヒット0件で exit 0。
cd "$(dirname "$0")/.." || exit 2
PATTERNS='kishimotosatoshi|ksmt0516'
HITS=$(grep -rEl "$PATTERNS" . \
  --exclude-dir=.git --exclude-dir=raw \
  --include='*.py' --include='*.js' --include='*.json' --include='*.txt' \
  --include='*.md' --include='*.html' --include='*.sh' --include='*.css' 2>/dev/null)
if [ -n "$HITS" ]; then
  echo "NG: 個人情報が残っています:"; echo "$HITS"; exit 1
fi
echo "OK: 個人情報パターンの残存なし"
