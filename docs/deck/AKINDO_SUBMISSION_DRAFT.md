# AKINDO 提出ドラフト(2026-07-31)

提出フォーム記入用の文面。提出作法(YouTube動画URL方式・タグ・アイコン)は既存 1st Wave 提出の公開情報から確認した。

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
- 誠実性: 開示リスト22項・PROCESS_LOG(AIの提案/人の判断/採否の3列)・編集タイムライン全開示
- プロセスログ要約と時間短縮指標(実測): docs/PROCESS_METRICS.md(2時間でエンジン実測・レイテンシ約1/10・実質3日)

🎬 デモ動画(114秒): [YouTube URL]
📦 GitHub: https://github.com/Driedsandwich/unprompt-merge2026
📄 デック(PDF): リポジトリ docs/deck/unprompt_deck.pdf
```

## 提出前チェック(ユーザー実施)

- [ ] GitHub へ push(号令待ち)
- [ ] デモ動画を YouTube へアップ(限定公開でも可の作法)→ URL を本文へ
- [ ] フォームで isPublic を公開に
- [ ] Milestone 欄の実仕様を確認して記入
