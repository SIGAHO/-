# Recent context / style fix

対象: `codex/breaktail-v2`、基点 `a124e2f2903920181131bf7ccfa2a840427ef26c`。新機能・学習経路の追加なし。

## 原因と修正

- PromptBuilderがambiguous_followupとTopic抑制済みcasual_chatで履歴を全除外していた。直近4 userターンと対応するassistant原文を常に保持する。6000文字は古い履歴の目安とし、固定部分は超過しても切らない。雑談・継続発話には固定範囲より古い原文を足さない。
- 「参加するの！」「ランナーとして」「ああ」「それ」等をcontinuationとして保守的に経路分類する。Topic更新と古い補助記憶の注入を抑制するだけで、意味やStateを確定しない。previous_assistantを通常生成にも渡し、解釈は直近原文を読むモデルに委ねる。
- 「は？」「？？」は既存の直前assistant参照CPU経路を維持し、PromptBuilderでも原文を保持する。
- 口調検査は最大1回再生成。違反が残った場合は元文/再生成文から違反数の少ない方、同数なら短い方を採用する。完全な末尾定型文のみ削除し、本文・数値・コードを長さだけで切らない。空になる場合は元文を保持する。
- timeout、空/型不正、不正Unicode等はModelErrorのまま。口調違反の残存はremaining_issues/fail_openとして記録し、model_failureにはしない。
- FIO JSONL/FTS5/heat、KnowledgeGate、Provenance、Web Retrieval、Replayの境界を維持。AI文をState/Verified Memoryへ昇格させない。

## 検証

- 新規15件: マラソン参加・役割・肯定の原文接続、直前質問、短い反応、古いTopic抑制、挨拶、再起動・明示的SessionRecall、文字数枠を超える4往復固定、KnowledgeGate維持、口調fail-open、本文/コード保持、実生成失敗の分離。15/15 PASS。
- 関連既存テスト: chat 23/23、style/knowledge 24/24、FIO 71/71 PASS。
- 全unitは最終コードで1回実行: **374/374 PASS（既存359 + 新規15）**、84.300秒。既存2件のhardening期待値は「原文全除外」から「補助Topic抑制＋直近原文保持」に更新。文体テスト1件は停止から継続へ更新。
- Behavior107は既存期待値を変更せず1回実行: State25 + Correction12 + Topic21 + OpenLoops22 + Memory14 + Emotion13 = **107/107 PASS**。合計 **481/481 PASS**。
- 全unitに含まれる500-turn fuzzとFIO durabilityも成功。continuation分類がTopic更新/ReplayとFIO確定処理に関わるため、既存unitからは外していない。7000発話/638 replayの追加コーパス再実行は省略。
- 初回の新規テストはWindows sandboxの一時領域権限で1件実行エラー。作業内TEMP/TMPへ変更後に全件成功。FIO単独実行にはPYTHONPATH=srcが必要。daemon/IPCを含む全unitと実Ollama確認はローカル通信可能な実行環境を使用。

実行:

```powershell
$env:PYTHONUTF8 = '1'
$env:PYTHONPATH = Join-Path $PWD 'src'
$env:TEMP = Join-Path $PWD 'work/tmp' # 作成済みの作業内一時領域
$env:TMP = $env:TEMP
.venv/Scripts/python -m unittest discover -s tests -v
.venv/Scripts/python experiments/run_all.py --no-write
.venv/Scripts/python scripts/recent_context_smoke.py
```

## 実 qwen2.5:14b（6ターン、1回のみ）

観測原文とmetadata: [recent-context-smoke.json](recent-context-smoke.json)。モデルに正解・採点基準・教師データを作らせていない。

1. 「今日はマラソン大会や！」→「マラソン大会か！参加するの？」
2. 「参加するの！」→「いいね！参加者として楽しみにしてるよ。準備は大丈夫？」。参加対象の聞き直しなし。
3. 「ランナーとして」→「ランナーとして参加するんだね！準備は順調かな？何か必要なものある？」。
4. 「ああ」→「準備は進んでる感じだね。他に何か手伝うことはある？」。再生成後assistanteseが残るがfail_open=trueで返答・保存が成功。
5. 「は？」→直前返答のどの部分かを尋ねる既存CPU応答。
6. 「？？」→同じCPU経路で直前返答を参照。

停止0件。モデル生成4ターン＋既存CPU応答2ターン。自然な文脈接続と実際の口調fail-openを確認したため、追加の実モデル反復なし。

## 未保証範囲

- 定型の申し出・余分な質問は残る。今回の実観測でもassistanteseが残存し、完全な口調遵守は保証しない。
- 省略の意味解釈・役割理解はモデル依存。4往復を超える照応、任意の長文/同義表現の品質保証はしていない。
- 固定原文が長い場合は6000文字を超える。モデル自体の入力枠まで無制限に保証するものではない。
- 既存StyleValidatorは文体検査で、安全性を判定する機能ではない。新たな安全判定器や外部事実の採用経路は追加していない。
- 既存daemonはコード更新後に再起動が必要。mainは変更しない。
