# FIO-inspired Memory v1

対象: `SIGAHO/-` の `codex/breaktail-v2`、基点 `b62b3d457478382e56f1915cd66aca987a38c9ac`。
既存CoreとEvent Replayを維持し、補助的なSession/Experience経路を追加。mainは更新しない。

## 実装

- SessionRecorder: confirmedなuser/assistant原文のUTF-8 JSONL、session/turn ID・時刻・status・出所要約、重複抑制、競合/途中行破損検知。
- SessionIndex: SQLite FTS5、NFKC character bigram/trigram、user重み2/assistant1、session選択→turn-window選択、軽いrecency、session配分と重複除外。
- ExperienceStore: 原文bodyを保持する独立SQLite。turn、ユーザー訂正、既存OpenLoop完了遷移、検索結果、モデル例外を記録。
- Context: 通常最大2 session × 2 hit/2400本文文字、明示想起4 × 2/6000文字。挨拶・曖昧な反応は補助想起なし。State/Memory/Topicを優先。
- Provenance: 引用のID/時刻/原記録SHA256/発言元を保持。assistantと外部資料をState/Verified Memoryへ昇格しない。
- Recovery: Session JSONLとExperience DBは独立保存。Indexは原本から再構築。確定assistantイベントのoutboxで副保存前の停止を冪等補完。Core replay自身は副保存しない。

FIO資料のSession/二段検索/heat/復旧境界だけを参考にした。旧Breaktail/FIO学習資産、Teacher Store、LoRA、自己生成教師データ、Vault/Obsidian/DMN/Bookshelf/Link Weaverは未使用。
試験の短い固定文は機械的契約を試す入力であり、会話品質の正解ラベルや学習用データではない。

## 検証

- 既存unittest 288件 + Behavior 107件 = 既存395条件を維持。
- 新規unittest 71件。合計359 unittest、すべてPASS。実行時環境とソースSHA256は `fio-memory-v1.json`。
- Behavior: state 25/25、correction 12/12、topic 21/21、open_loops 22/22、memory 14/14、emotion 13/13。
- 観測済み人間会話7000発話、638/638 Replay一致、既存不変条件失敗0、Prompt policy 7000/7000。
- 500ターンをChatSession全経路で実行し、50ターンごとの再起動、Session 500件、Event 1000件、Experience 500件を確認。別途Session保存500件の単体耐久も実施。
- qwen2.5:14bで会話→再起動→「前に何話した？」を実行。元session引用あり。「調子どう？」は古い曲が文脈にも出力にもない。「前に曲の話したよな？」は正しい原文引用あり。「は？」は直前assistantをCPU経路で参照。
- ModelError、writeback障害、JSONL末尾破損、不正UTF-8、重複、外部writer、再起動、daemon/chat同一保存、検索成功/失敗の境界を検証。

全テストはWindows / Python 3.12で実行。Janomeとtzdataを作業用依存に追加。IPC・モデル接続検証はローカル接続可能な権限で実行した。
過去のfreeze/manifest/reportは書き換えず、新しい結果だけを別reportへ保存した。

詳細: [総合結果](fio-memory-v1.json)、[実14B文脈・応答](fio-memory-v1-model.json)、[500ターン](fio-memory-v1-durability.json)、[7000発話](fio-memory-v1-corpus.json)。

## Heat

`live_heat = stored_heat * 2^(-max(0, now-heated_at)/half_life_seconds)`。
参照時は `min(maximum, live_heat + reinforcement)`。
既定半減期7日、加算0.25、最大4。設定可能なHeatConfigを公開。
100秒半減期の試験では `1 → 0.5 → 参照後0.75`。原文不変、参照数だけ増加。
確定した応答に渡された経験だけreinforceし、モデル失敗・診断読み取りはreinforceしない。heatは真実度ではない。

## 残る制約

検索は文字一致なので同義語や長い省略には保証がない。旧Event Logのペアを推測してSessionへ自動移行しない。
大規模履歴でのIndex再構築/起動時outbox走査性能は未保証。破損JSONLは原本保管後に明示修復が必要。
モデルが「詳しく話した」など引用以上の言い回しを足す場合は残る。今回の合格条件は検索文脈と保存・信頼境界の機械的正しさで、自然さや出力の完全な忠実性ではない。
書き込み途中の障害は模擬したが、物理的な電源断による耐久試験はしていない。

## 起動・診断

```sh
python daemon.py --model qwen2.5:14b --event-log data/events.jsonl
python chat.py --event-log data/events.jsonl
# daemon/chatを停止して診断
python scripts/fio_memory.py --event-log data/events.jsonl --query "前に曲の話したよな？"
python scripts/fio_memory.py --event-log data/events.jsonl --rebuild-index
python scripts/fio_memory.py --smoke --turns 500 --output work/fio-durability.json
python scripts/fio_memory.py --model --output work/fio-model.json
python -m unittest discover -s tests -v
python experiments/run_all.py --no-write
python scripts/corpus_regression.py --output work/fio-corpus.json
```

コーパス再実行には既存manifestの固定ハッシュと一致する `work/corpora/JMultiWOZ_1.0.zip` と `test/dev/train.json` が必要。
