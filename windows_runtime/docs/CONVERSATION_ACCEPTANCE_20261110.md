# Breaktail Windows会話品質：2026-11-10 開発・検証記録

## 今回の変更

- `breaktail_conversation_state.py`: 「予算は5000円だったっけ？」等の確認質問が確定済み数値を上書きする不具合を修正。
- `breaktail_retry_context.py` と `breaktail_v02.py`: 返答契約の再試行で、元の会話履歴・確認済み事実・人格設定・原文記憶を維持する。無関係な過去ターンだけを文脈容量に応じて削る。
- `test_breaktail_conversation_numeric_questions.py` と `test_breaktail_retry_context.py`: モデルの気まぐれに依存しない10件の回帰検証。
- `evaluate_live_conversation.py`: 実ローカルモデルを使う5シナリオの評価器。全文と機械的判定をJSON保存する。コード内でも「自然な会話合格」は自動で出さない。

## 実際に確認したこと

- GitHub ActionsのWindowsランナーで `run_tests.ps1` を実行：**503件+9件の合計512件成功**。
- 同じ実行で実モデル会話評価器のPython構文検査に成功。
- 対応するログ: https://github.com/SIGAHO/-/actions/runs/42829374289

## 未確認・合格にしないこと

- 本人のWindows上で実稼働中のBreaktailへ、このGitHub更新が反映済みかは未確認。
- Ollamaの `qwen2.5:14b` に対する今回の新しい5シナリオの実会話出力は未取得。
- 自然な日本語、話題変更、訂正理解、複数質問への完全回答は、構造テストだけでは合格にしない。
- 記憶検索の一般性能が上がったという主張も未検証。

## ローカルモデルでの会話品質評価

PowerShellでリポジトリのWindows版ディレクトリから実行：

```powershell
cd windows_runtime/current
python evaluate_live_conversation.py --output evaluation/live-conversation.json
```

- Ollamaと既定モデルが起動していることが前提。
- このスクリプトは一時データ領域を使う。
- 回答全文と機械的チェックが指定のJSONへ残る。
- 確認できた実モデルの返答を読んで、意図の取り違え、唐突な励まし、無関係な質問、過去の訂正の無視がないか別途判定する。

## 現在の判断

**機能回帰テストは合格。自然会話は未合格（実モデル評価待ち）。**
