# Companion Core (model-less)

## 現行Windows版Breaktail

PC上のOllama版は [windows_runtime](windows_runtime/README.md) で管理します。
この `src/companion_core` はモデル非接続の別実装です。こちらだけの編集は現行Windows会話経路に反映されません。
[実会話を続けた追加修正・最新検証](windows_runtime/docs/FOLLOWUP_CONVERSATION_20261102.md)を参照してください。

14BなどのLLMを接続する前に、CPU側だけで処理できる「相棒」の外部脳を実装した最小コアです。
標準ライブラリのみで動きます。

実装済み:
- Event Log / Replay
- State Engine / source gate / provenance
- Explicit Correction Engine
- Time Engine
- Topic Tracker (文字n-gramによる決定論的類似度)
- Open Loop Tracker
- Memory Engine (類似度 + recency + importance + reuse + redundancy penalty)
- Emotion / Relationship state (ルール + EMA)
- Context Assembler
- Trace
- unittest 回帰テスト

## 実行

```bash
python -m unittest discover -s tests -v
python demo.py
```

## 後でLLMを挿す場所

`CompanionCore.handle()` の返り値 `context` をLLMへ渡し、返答を生成するだけです。
LLM出力は `assistant_output` Event として記録しても、Stateへは昇格しません。


## Windows版Breaktailの最新開発まとめ（2026-11-10）

[会話・記憶・作業エージェントの全変更と検証結果](windows_runtime/docs/DEVELOPMENT_SUMMARY_20261110.md)。
Windows版は `windows_runtime/`、既存Companion Coreは `src/companion_core/` で管理する。
