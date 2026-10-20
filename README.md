# Companion Core (model-less)

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
