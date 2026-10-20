# Companion Core (model-less)

14BなどのLLMを接続する前に、CPU側だけで処理できる「相棒」の外部脳を実装した最小コアです。
生成モデルは不要です。日本語の話題判定には Janome 0.5.0 の形態素解析を使用します。

実装済み:
- Event Log / Replay
- State Engine / source gate / provenance
- Explicit Correction Engine
- Time Engine
- Topic Tracker (品詞・文法役割・文脈の継続証拠による決定論的判定)
- Open Loop Tracker
- Memory Engine (類似度 + recency + importance + reuse + redundancy penalty)
- Emotion / Relationship state (ルール + EMA)
- Context Assembler
- Trace
- unittest 回帰テスト

## 実行

```bash
python -m pip install -r experiments/requirements.txt
python -m unittest discover -s tests -v
python demo.py
```

## 理論検証

`experiments/` に state / correction / topic / open_loops / memory / emotion の
仮説・振る舞いケース・実測結果・採用判断を保存しています。
`python experiments/run_all.py` で全系統を評価します。
未達ケースがあれば結果を保存して終了コード1、実行エラーは2となります。
採用条件やWindowsの時刻データ準備は [実験ガイド](experiments/README.md) を参照してください。
話題の過分割修正と未使用対話での比較は [外部検証記録](experiments/topic_holdout_v3/README.md) に記録しています。

## 後でLLMを挿す場所

`CompanionCore.handle()` の返り値 `context` をLLMへ渡し、返答を生成するだけです。
LLM出力は `assistant_output` Event として記録しても、Stateへは昇格しません。
