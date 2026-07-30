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
gh repo create gyakumon-merge2026(当時。現名 unprompt-merge2026) --private --source=. --push
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

## 7. Unprompt 本体(Intent Compiler。旧称 GYAKUMON)の起動

Claude Code サブスクリプションのヘッドレスCLI(`claude -p`)を使う。Anthropic APIキーは不要(claude CLI にログイン済みであること)。

```sh
python3 server.py --port 8321 --model sonnet --render-model haiku
```

ブラウザで http://127.0.0.1:8321/ を開く(起動時に標準出力へURLを表示する)。停止は Ctrl+C。
引数はすべて省略可(既定値は上記のとおり)。

| オプション | 既定 | 意味 |
|---|---|---|
| `--port` / `--host` | 8321 / 127.0.0.1 | 待受。localhost のみバインドする |
| `--model` | sonnet | `/api/explode` と `/api/compile` のモデル |
| `--render-model` | haiku | `/api/render` のモデル |
| `--compile-model` | (`--model` と同じ) | `/api/compile` だけ別モデルにする場合 |
| `--timeout` | 120 | claude 1呼び出しのタイムアウト秒 |
| `--max-concurrency` | 6 | claude 子プロセスの同時実行上限(超過はキュー) |
| `--claude-bin` | claude | claude CLI のパス |
| `--allow-api-key` | off | 既定では子プロセス env から `ANTHROPIC_API_KEY` を除去する(サブスクリプション認証が主経路) |

サーバは `app/` を `/` で静的配信し、`/api/*` で claude CLI を子プロセス実行する。子プロセスの cwd は
リポジトリ外の一時ディレクトリ(`CLAUDE.md` / `.claude` 設定の祖先探索を遮断)。

**レイテンシの実測(2026-07-29 このMac)**: `claude -p` は CLI 起動オーバーヘッドだけで 40〜60 秒かかる
(`claude -p "ping" --model haiku` で壁時計 45〜56 秒に対し CLI 自己申告 `duration_ms` は 5〜7 秒。
`--strict-mcp-config` を付けても改善しなかった)。実測値は explode が壁時計 111 秒 / api 81 秒、
render が壁時計 86〜115 秒 / api 25〜31 秒。6並列の render では 1 本が既定 120 秒のタイムアウトに達した。
デモ前に余裕を持たせるなら `--timeout 180`、あるいは `--max-concurrency 4` で CPU 競合を下げる。

```sh
python3 server.py --timeout 180 --max-concurrency 4
```

### ゴールデンパス(動作確認手順)

1. 初期画面のプロンプト箱にブリーフ文を入力し送信する(タイプするのはこの一文のみ)。
2. 「静寂」画面: 0.1秒刻みの経過秒カウンタと「x1.0 — 生成は、始まらない」の表示を確認する。
3. 「爆散」: 文が語スパンに分解され、判断点カード(最大5枚)が anchor 語とテザー線で結ばれて配置されるのを確認する。
4. 各カードで **決める**(ミニレンダをクリック→確定色)または **委ねる**(ボタン→委任グレー)を行い、判断点カウンタ N→0 を確認する。
5. N=0 でコンパイルボタンを押し、MD/JSON切替と非対称カウンタ「タイプした文字: 0 / 選択: N」、根拠文の表示を確認する。

### 証拠ログの確認

```sh
tail -f logs/session_*.jsonl
```

各行は `{ts, endpoint, model, wall_ms, api_ms, ok}`。`/api/explode` `/api/render` `/api/compile` すべての呼び出しが記録される。
