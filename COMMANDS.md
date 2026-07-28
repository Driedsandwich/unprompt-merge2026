# COMMANDS — ユーザーが「!」で実行するコマンド集

すべて `outputs/dev/gyakumon/` をカレントディレクトリとして実行する。

## 1. Git 初期化と初回コミット

```sh
git init
git add .
git commit -m "chore: scaffold GYAKUMON killer-test harness (Day1)"
```

## 2. コミット規約

判断点を解決したコミットには `resolved:` タグを付ける。

```
resolved: <判断点> → <決定>
```

例:

```sh
git commit -m "resolved: 実行構成 → ビルドレス・ブラウザ直叩き(Nodeプロキシ廃止)"
git commit -m "resolved: レイテンシ計測 → クライアント側JSON収集"
```

通常コミットは Conventional Commits(feat / fix / docs / chore)を使う。

## 3. GitHub リポジトリ作成(private)

```sh
gh repo create gyakumon-merge2026 --private --source=. --push
```

## 4. キラーテスト実行(主経路: ヘッドレスCLI)

Claude Code サブスクリプションでログイン済みなら API キーは不要。

```sh
python3 killer_test/run.py --model sonnet
```

- 比較用に Fable でも実行する場合: `python3 killer_test/run.py --model fable`
- 内部で `claude -p "<プロンプト>" --model sonnet --output-format json` を1ブリーフずつ実行し、`result`(抽出JSON)と `duration_api_ms` / 壁時計時間を記録する。

## 5. キラーテスト実行(代替経路: ブラウザ版・APIキー保有者向け)

自分の Anthropic API キーを持つ場合のみ。

```sh
python3 -m http.server 8000
# ブラウザで http://localhost:8000/killer_test/index.html
```

停止は Ctrl+C。

## 6.(任意)codex による監査例

```sh
codex "outputs/dev/gyakumon/killer_test/index.html を読み、APIキーがsessionStorage以外に保存・送信されていないこと、fetch先が api.anthropic.com と相対パス2件のみであることを監査せよ"
```
