# Breaktail: ローカル会話モード (実験版)

目的: ChatGPT/APIに依存せず、キャラクター設定と会話履歴、ローカルの意味検索を組み合わせる。

## 準備

1. Ollamaをローカルに導入する。
2. `ollama pull qwen2.5:14b` （別のローカルモデルも指定可能）
3. `ollama pull bge-m3` （日本語を含む多言語の意味検索用モデル）
4. `ollama serve` （既にOllamaが起動していれば不要）
5. プロジェクトのルートで次を実行する。

```powershell
python run_local_chat.py --model qwen2.5:14b --semantic-model bge-m3
```

重ければ `--model` に導入済みの別モデルを指定する。意味検索モデルを使わない場合は `--semantic-model bge-m3` を省略できる。

キャラ設定: `characters/breaktail.json`。会話履歴: `data/conversation.jsonl`（ローカル保存）。`/diag` でローカル状態を表示、`/exit` で終了。

## 検証

```powershell
python -m unittest discover -s tests -v
```

テストには固定ベクトルと偽LLMを使うため、モデルの文章生成品質やネット接続に依存しない。実際の埋め込みモデルの精度評価はまだ別途必要。

## 制約

- OllamaへのHTTP通信は127.0.0.1のみ。
- 意味検索は関連性の判定であり、肯定/否定、時制、数値矛盾が正しく判定できる保証はまだない。
- 会話は自然さの改善を狙う実験段階で、テスト通過だけでは品質を保証しない。
- キャラカードはV2 JSONのテキスト要素だけを使用。PNGカードのメタデータ抽出には未対応。
- APIキー、クラウドLLM、追加学習は不要。
