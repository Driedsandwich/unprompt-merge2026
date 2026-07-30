# GYAKUMON ARCHITECTURE(Day1 キラーテスト・ハーネス)

旧称/コードネーム: GYAKUMON(逆問)= 現 Unprompt。本書は Day1 の歴史的装置の記録として旧称のまま残す(2026-07-30 改名、docs/DISCLOSURE.md #19)。

## 方針(拘束)

- **ビルドレス・サーバレス**: npm / Node / バンドラ禁止。バニラJS。`killer_test/index.html` 単一ファイルにインライン script。
- **配信**: ユーザーが `gyakumon/` 直下で `python3 -m http.server` を実行し、ブラウザで開く。`file://` 直開きは相対 `fetch` が失敗しうるため不可(README に明記)。
- **静的アセットの実行時読込**:
  - `../prompts/extraction_v0.txt` … 抽出システムプロンプト。ファイル分離により、プロンプト(可視タクソノミー設計)を審査員が直接読める。
  - `../data/briefs.json` … テストブリーフ11本。

## API 呼び出し

Anthropic Messages API をブラウザから直接呼ぶ。

```
POST https://api.anthropic.com/v1/messages
content-type: application/json
x-api-key: <画面のpassword入力値>
anthropic-version: 2023-06-01
anthropic-dangerous-direct-browser-access: true
```

- 非ストリーミング。
- 構造化出力は tool use で強制:
  `tools=[{name:'report_branches', input_schema:<抽出スキーマ>}]`,
  `tool_choice={type:'tool', name:'report_branches'}`, `max_tokens: 4000`。
- モデルは UI で2択: `claude-sonnet-5`(既定)/ `claude-fable-5`。

## 抽出スキーマ(順序固定)

```json
{
  "residual_ambiguity_assessment": "string",
  "missing_materials": ["string"],
  "branches": [
    {
      "question_point": "string",
      "anchor_words": ["string"],
      "downstream_impact": "string",
      "options": [
        { "label": "string", "thumbnail_description": "string", "px200_rationale": "string" }
      ],
      "default_if_unresolved": "string"
    }
  ]
}
```

制約: branches 最大5、options は2〜3。anchor_words は原文の連続部分文字列をそのまま・可能な限り最長フレーズで。missing_materials は「選択では解決できず情報提供が必要な欠落」。px200_rationale は「200pxサムネイルで判別できる根拠」。

## APIキーの扱い

画面の password 入力 → `sessionStorage` 保存のみ。コード・リポジトリ・localStorage・Cookie には書かない。第三者サーバを経由しない(送信先は api.anthropic.com のみ)。

## 証拠計画の変更(プロキシ廃止に伴う)

旧計画では Node プロキシがサーバ側でレイテンシ・応答ログを収集する想定だった。プロキシ廃止により、証拠収集は**クライアント側**に一本化する:

- ハーネスが各リクエストについて `performance.now()` 起点で送信→初回応答レイテンシを計測。
- ブリーフID・モデル・レイテンシ・機械判定結果(anchor実在、分岐数、対照捏造チェック)・生の抽出結果を、画面表示に加えて **レイテンシJSON としてエクスポート**(ダウンロード/コピー)できる。
- このJSONがキラーテスト合格線(8秒以内・10本中8本で有効分岐率70%以上 等)の一次証拠となる。有効分岐率の意味判定のみ人間(管制塔)が付与する。

## 開示事項

- 計測はクライアント時計依存であり、ネットワーク環境の影響を受ける(サーバ側の中立ログは存在しない)。
- `anthropic-dangerous-direct-browser-access` を用いたブラウザ直叩き構成である(自鍵・自ブラウザの検証用途に限定)。
- 詳細は `docs/DISCLOSURE.md` を参照。

## 実行エンジン改訂(7/29)

ユーザーが Anthropic API キーを用意できないため、実行エンジンを変更する。

- **主経路 = Claude Code サブスクリプションの headless CLI(`claude -p`)**。API キー不要。ログイン済みの Claude Code 環境で `claude -p "<プロンプト>" --model sonnet --output-format json` により1問1答実行する。出力 JSON の `result` フィールドに応答本文、`duration_ms` / `duration_api_ms` 等のメタが含まれる。比較用に `--model fable` も指定可能。
- **構造化出力**: ツール使用(`report_branches`)は用いない。`prompts/extraction_v0.txt` を「単一 JSON オブジェクトのみを出力(コードフェンス・前置き・後書き禁止)」方式に改訂し、スキーマ(フィールド順序固定)はプロンプト内に明記する。
- **localhost プロキシ**: Day2 で、`claude -p` を子プロセスとして呼ぶ Python 標準ライブラリのみのローカルサーバとして実装予定。ブラウザハーネスはこのプロキシ経由でも動作できるようにする。
- **ブラウザ直叩き(`killer_test/index.html` から api.anthropic.com へ直接 POST)は、API キー保有者(審査員等)向けの代替経路へ降格**。仕様は上記各節のとおり存置する。
