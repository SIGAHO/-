# Breaktail v2 会話MVP 検証記録

実施日: 2026-10-22 JST。土台: b312aa861606d20bfd075fb10d31f630a5d751e4
（mainの初期版ではなく、最新Companion Core修正が保存されたcodex/topic-discourse-evidence）。

## 結果

- 全unittest: **113/113成功**。元の90件を含む。詳細はunit_tests.txt。
- FakeModelAdapter E2E: **18シナリオ成功**。雑談、訂正、話題継続・切替・復帰、完了・未完了、記憶、感情、AI誤情報排除、再起動、接続失敗、空入力、重複入力防止、訂正旧値アーカイブ、破損ログ、25ターン＋再起動、日本語CLIを含む。
- 追加: HTTP要求契約・不正応答・接続失敗・環境変数と引数の優先順位4件、感情の否定と引用1件。
- 既存6系統: **107/107 PASS**。state 25/25、correction 12/12、topic 21/21、open_loops 22/22、memory 14/14、emotion 13/13。期待条件・ケース本文は変更していない。
- demo.py、Fake CLI、実Ollama CLIの起動・日本語入出力を確認。
- 実モデル: **qwen2.5:14b / 7cdf5a0187d5**。4往復の会話と別途CLI起動を確認。会話本文は非公開。実行メタデータのみsmoke_summary.jsonに保存。雑談、未完了事項、明示対象訂正、再起動後の参照を確認。初回21.84秒、以後1.23〜3.80秒。短いローカルスモークであり、一般的な会話品質の合格率ではない。

## 全実験の再実行とデータ管理

1. 6系統の振る舞い実験を現行コードで再実行し、各results.json / DECISION.mdを更新。
2. 過去の外部実験4本（topic_corpus / topic_holdout / topic_holdout_v2 / topic_holdout_v3）を隔離したb312aa8チェックアウトで再実行。当時のtopic実装を既存snapshotから復元し、元のfreeze検査・期待条件を維持。初回corpusは3fad90fのtopicを使用。**全4本で元の指標・判定が完全一致**。詳細はhistorical_recheck.json。
3. 同じ4サンプルを**観測済み回帰データ**として現行Coreでも全件再実行。計7000発話、638対話。全7000発話で不変条件を維持、Replay 638/638一致。詳細はexternal_regression.json。新しい未使用データやブラインド評価とは呼ばない。

過去候補のREVISE / REVISE / PASSと初回corpusのREVISEは書き換えていない。
旧外部実験のfreeze.jsonが参照する、今回変更したCoreの4ソースをfrozen_core/へそのまま保存。
既存のハッシュ確認テストは変更前ソースを検証し、期待ハッシュ自体は変更していない。
これはCompanion Coreの再現用ソースで、旧Breaktailの教師データやモデル資産ではない。

外部データは既存manifest指定の固定版から取得し、アーカイブ・本文・BSDソースのハッシュを照合。
元の人間由来ラベルのみ使用。本文はリポジトリへ追加せず、モデルにも渡さず、学習していない。
出所とライセンスは各外部実験README参照。BSDはCC BY-NC-SA 4.0の研究評価用途に限定。

現行コードでの再現:

```sh
python -m unittest discover -s tests -v
python experiments/run_all.py
python demo.py
python experiments/mvp/replay_regression.py --archive PATH/JMultiWOZ_1.0.zip --bsd-dir PATH/BSD
```

BSDディレクトリには既存manifestの固定リビジョンのtest.json / dev.json / train.jsonを配置。
過去候補の再現はtopic_holdout_v3/README.mdのsnapshot復元手順を使用。

## 残る既知問題・適用範囲

- Topicの代理境界評価は最終サンプルでF1 0.3739495798、同分野内分割38.55%、切替126件中37件の見逃し。今回の統合でTopicの意味理解が完成したとは扱わない。
- 訂正対象の自動特定は未実装。確定したい訂正は `/correct キー 訂正文` を使う。未指定の訂正は会話履歴として扱う。
- 感情は有限ルールとEMAによる推定。複雑な否定、皮肉、引用の入れ子、任意の対象への感情帰属までは理解しない。
- Open Loopは既存の明示表現・類似度で判定する。複合文や複数候補の曖昧な完了は保留する。
- ログは単一プロセス用。破損行は起動エラーとして原本を保持。自動修復・同時書込みロック・ログ肥大化対策は未実装。
- Stateに入るのは明示訂正と実行環境情報。外部APIから直接変更した派生状態の永続化は提供しない。
- AI生成文は機械的にState/Memoryへ入れない。一方、モデルが過去の誤答を文章上で繰り返さないことはプロンプトだけで完全には保証できない。

途中の未達も記録: 初回は依存未導入、Windows一時領域権限、過去freezeと現行ソースの混同でテストが失敗した。
作業内依存・一時領域、元ソース保存で解決。新E2EではReplayの記憶順・時刻差を検出して修正。
最終CLI確認でcp932の文字出力エラーを検出し、標準入出力をUTF-8化して回帰テストを追加した。
最終実行では未達・実行エラーなし。過去外部実験のREVISEは既知の研究上の制限として残す。

公開時の自動承認レビューが会話本文の公開を拒否したため、スモークの本文は公開対象から除外し、モデル名・実行数・所要時間・確認結果だけを保存した。
