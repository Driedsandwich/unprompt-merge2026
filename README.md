# GYAKUMON — Intent Compiler

曖昧な制作ブリーフを「後戻りコストの高い判断点(分岐)」に逆コンパイルし、選択肢つきで発注者に問い返すインテント・コンパイラ。

MERGE 2026 AI Designathon 提出用プロダクト。本ディレクトリは Day1 成果物「キラーテスト・ハーネス」(抽出品質をブラウザで実測する装置)。

## リポジトリ構成

```
gyakumon/
├── README.md              … 本ファイル
├── COMMANDS.md            … ユーザーが実行するコマンド集
├── PROCESS_LOG.md         … AI提案と人間判断のログ(3列表)
├── killer_test/
│   └── index.html         … キラーテスト・ハーネス本体(単一HTML、ビルドレス)
├── prompts/
│   └── extraction_v0.txt  … 抽出システムプロンプト(実行時に fetch で読込)
├── data/
│   └── briefs.json        … テストブリーフ11本(曖昧10 + 完全指定の対照)
└── docs/
    ├── ARCHITECTURE.md    … アーキテクチャ正式文書
    └── DISCLOSURE.md      … 開示リスト
```

## 実行方法

ビルド不要。npm / Node / バンドラは使わない。

killer_test/ の中ではなく、その親である gyakumon/ ディレクトリで起動する:

```sh
cd <このREADMEがある gyakumon/ ディレクトリ>
python3 -m http.server 8000
```

ブラウザで http://localhost:8000/killer_test/index.html を開く。

**注意: killer_test/ 内で http.server を起動しないこと。** `../prompts/` と `../data/` がサーバルート外を指して 404 になり、ハーネスが「読込エラー」で止まる。

**注意: `file://` で index.html を直接開かないこと。** ハーネスは `../prompts/extraction_v0.txt` と `../data/briefs.json` を `fetch()` で読み込むため、`file://` 直開きではブラウザのセキュリティ制約により fetch が失敗しうる。必ず `python3 -m http.server` 経由で配信する。

## APIキー

- 画面の password 入力欄に Anthropic API キーを入力する。sessionStorage にのみ保存(タブを閉じると消える)。
- キーをコードやリポジトリに書かない。
- ブラウザから Anthropic Messages API を直接呼ぶ(`anthropic-dangerous-direct-browser-access: true`)。自分のキーを自分のブラウザで使う前提の検証用構成。

## キラーテストの手順

1. サーバを起動しハーネスを開く(上記)。
2. APIキーを入力、モデルを選択(既定: claude-sonnet-5 / 代替: claude-fable-5)。
3. ブリーフ11本(曖昧10本 + 完全指定の対照1本、各曖昧ブリーフには対照ペアあり)を順に送信する(個別または一括)。
4. ハーネスは各応答について機械判定を表示する:
   - anchor_words が原文の連続部分文字列として実在するか
   - 分岐数・選択肢数がスキーマ制約内か
   - 送信→初回応答レイテンシ(合格線: 8秒以内)
   - 対照(完全指定)ブリーフで分岐を捏造していないか
5. 分岐の「有効性」(その判断点が本当に成果物を左右するか)の意味判定は人間(管制塔)が画面上で行う。

### 合格線

- 曖昧ブリーフ10本中8本で有効分岐率 70% 以上
- anchor_words がすべて原文に実在
- 各ブリーフに対照ペア1組以上
- 送信→初回応答 8秒以内
- 対照(完全指定)ブリーフで分岐を捏造しないこと

注: 本ハーネスは非ストリーミングのため、計測する ttfb_ms(送信→初回応答)は応答完了(全生成)時刻とほぼ同値であり、CORS プリフライト往復も含む。8秒線はこの保守的な定義で判定される。
