# AKINDO 提出ドラフト(2026-07-31)

出典: 公開API `api.akindo.io/public/wave-hacks/QlDaGxoe9TNAQGBqg/products` から既存7件を全件取得して分析(ログイン不要で読めた。取得JSONはセッション作業領域に保存)。

## 既存7件の観測(事実)

| 名前 | 一行 | 公開 | GitHub | 特徴 |
|---|---|---|---|---|
| zk-liquidate | Polygon清算プロトコル | 非公開 | なし | 2行のみ・テーマ適合薄 |
| Warp | prompt→フルスタックappを一発生成 | 公開 | あり | 長文・AI設計判断を詳述(JSON Schema/Zod/GPT-4o) |
| ATQA | 日本語TTS誤読QAエージェント | 公開 | あり | 日本語・箇条書き・**YouTubeデモ動画+ピッチ資料+プロセスログ公開**・23.5hの実時間明記 |
| SignalFlow Agent | 市場シグナル→執行 | 公開 | あり | 実データ強調・web3色 |
| Spatial Canvas | 情報を1つのCanvasへ | 非公開 | なし | 日本語・抽象的な3文のみ |
| Conflux | **AI-Native Spatial Intent Canvas** | 非公開 | なし | マルチエージェント批評・意図の重み場。**「intent」を冠する最近接コンセプト** |
| VendorGuard | B2B調達交渉エージェント | 公開 | あり | Rust実装・APIクォータ切れの言い訳あり |

## 傾向と含意

1. **フォーマット**: name / tagline / タグ3個 / GitHubリンク / 「Updates in this Wave」自由記述 / Milestone / アイコン画像。デモ動画は本文にYouTube URLを貼る方式(ATQA)。→ **動画はYouTube(限定公開可)へアップしてURLを貼るのが既存の作法**。
2. **強い提出の型**(Warp・ATQA): 箇条書き+実測数値+リンク束(動画/リポジトリ/資料)。AIをどう統合したかの設計判断を書く。
3. **競合状況**: テーマ直球の「AIネイティブUX」枠は Spatial Canvas / Conflux の2件。特に Conflux は「Intent」を冠し、意図を扱う点で最近接。ただし両者とも**キャンバス上の空間配置**アプローチで、非公開・GitHubなし・実測値なし。
4. **差別化の押し出し方**(本文に書くべき固有点): ①成果物不執筆の憲法(タイプ0字) ②文そのものがUI(語アンカー) ③全数値が実測+開示リスト21項+PROCESS_LOG ④APIキー不要のclone+1コマンド再現 ⑤同一指示書での実例並置。空間キャンバス勢に対し「構造化を人の空間操作に頼らず、文から機械抽出する」対比が効く。
5. **見せ方**: 公開(isPublic)・GitHubリンク・アイコン(assets/icon_512.png 作成済み)を必ず設定。7件中3件が非公開でリンクなし — 検証可能性で差がつく。

## フォーム記入ドラフト

- **Product name**: Unprompt — Intent Compiler
- **Tagline**: 曖昧な一文を、実行可能な意図の指示書へ。AIはあなたの成果物を書かない。
- **タグ案**: AI / Developer Tools / Other(既存例準拠)
- **GitHub**: Driedsandwich/unprompt-merge2026
- **アイコン**: docs/deck/assets/icon_512.png

### Updates in this Wave(本文ドラフト・日本語)

```
初回提出。「AI Native Interface」への回答として、生成AIの手前に挟まる意図コンパイラを実装しました。

Unprompt は、曖昧な依頼文(例:「モダンだけど温かみのあるLPを作って。うちの会社のやつ。」)をそのまま受け取り、生成の代わりに問い返します。文中の語に係留された判断点と見本(実生成)が並び、ユーザーは〈決める〉か〈委ねる〉の2動詞だけで意図を確定。最初の一文以降、一度もタイプせずに「意図の指示書」(整形表示+機械可読JSON)が完成し、任意のAIへ手渡せます。

- 二重憲法: AIはユーザーの成果物を書かない/人間は選択だけ(本収録デモの実測: 追加タイプ0字・選択5回)
- 静寂も実測: 送信→最初の判断点 17.8秒をそのまま見せるUI(経過秒カウンタ)
- 抽出の信頼性: 判断点の係留語は「原文の連続部分文字列」であることを機械検証(22実行で違反0)
- 再現性: APIキー不要。Claude Code ログイン済み環境で clone+1コマンド
- 誠実性: 開示リスト21項・PROCESS_LOG(AIの提案/人の判断/採否の3列)・編集タイムライン全開示

🎬 デモ動画(114秒): [YouTube URL]
📦 GitHub: https://github.com/Driedsandwich/unprompt-merge2026
📄 デック(PDF): リポジトリ docs/deck/unprompt_deck.pdf
```

## 提出前チェック(ユーザー実施)

- [ ] GitHub へ push(号令待ち)
- [ ] デモ動画を YouTube へアップ(限定公開でも可の作法)→ URL を本文へ
- [ ] フォームで isPublic を公開に
- [ ] Milestone 欄の実仕様を確認して記入
