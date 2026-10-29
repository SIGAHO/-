# Generation comparison — 2026-10-30

## 結論

短いDialogue Act指示Bを本番へ採用しない。実Qwenの新規推論は24回、生成成功24/24、停止0/24、出力上限到達0/24。CPU PolicyVerifier適合はA 0/12 (0%)、B 1/12 (8.3%)。独立した人間による自然さ評価は未実施であり、品質の合格率は算出しない。本番コード・禁止語・既存テスト期待値は変更していない。

対象はSIGAHO/- のcodex/breaktail-v2。開始時リモートheadは7ecf529571c1c24bd1e788441659c80e0c54eba2で、指定headと一致。mainは読み取り確認のみ（fd1973e0a43e6917ab4e79835ba11689277d485f）、更新しない。

## 旧失敗の分類

alignment-smoke.jsonの最終CPU判定では適合2/12、質問9件、励まし2件、拒否strategy反復1件（複数ラベルの重複あり）。旧レポートの「よお！」に過去の順位を持ち出す例、英単語混在、一見適合でも自然さを保証しない例も確認した。旧結果は23推論で再生成/ranking後の12返答であり、今回の単一候補24推論と適合率を直接比較しない。human評価・teacher正解・ground truthにはしない。

## 条件と再現性

- 既存smokeの12入力を使用し、順位を400位へ抽象化。個人名・学校名・実際の会話ログは取り込まない。最初の挨拶は履歴なし、残る11入力は固定された過去会話を持つ。同一系列を条件ごとに自由生成すると履歴が変わるため、過去のAI返答は未検証の固定履歴としてのみ利用する。旧Breaktail/FIOの学習資産は読み込まない。
- 実ChatSessionのprepare_replyでState/Memory/Policy/KnowledgeGate等のcontextを構築し、一時フォルダで固定履歴を準備。Webは無効。実Qwen出力はセッションやPreferenceへ書き戻さない。比較は実際の初回プロンプトに対する指示形式のablationであり、再生成・rankingを含むend-to-end比較ではない。
- A: 現行PromptBuilder出力そのまま。B: 役割分離/ResponseSpec説明段落とCPU_CONTEXT.response_specだけを短い日本語の会話行為指示に置換。他のsystem指示、CPU状態、履歴、現在入力は同一。Bも共通の長い基本system指示を保持しており、全systemを極短くした実験ではない。
- C: 独立した人間執筆・承認済み例がこの作業で利用可能な範囲に0件のため比較不能。AI例をfew-shotとして追加しない。human_approvedの付与操作0、学習export 0。既存の本番ledgerの内容や全体件数を推定して書き換えない。
- Ollama qwen2.5:14b、digest 7cdf5a0187d5c58cc5d369b255592f7841d1c4696d45a8c8a9489440385b22f6、Q4_K_M。temperature=0.6、seed=20261030、num_ctx=8192、num_predict=256を全要求で固定。モデル追加取得・学習・daemon再起動なし。A/Bの実行順を入力ごとに反転。
- 上限24要求、同時1要求、生成最大6144トークン、全体900秒、各要求60秒、再試行0。ローカルRTX 3060 / 12288 MiB、開始前使用1822 MiB。GPUメモリ割当は既存Ollamaに委ね、排他的なGPU確保やVRAM上限保証は行わない。オフライン/未導入なら未実行、通信失敗時はそこで停止、Fakeによる代替なし。クライアントtimeout後のサーバ側処理の即時取消は保証しない。
- JSON inputsに全メッセージ、State/Spec、履歴hashを保存。再実行は--inputsで時刻やIDを含む同一payloadを再生可能。seed固定でもランタイム/ハードウェアをまたぐ完全決定性は保証しない。

## 新規比較の機械的集計

- A: 適合0/12、停止0、質問9、助言2、励まし3、称賛1、positive reframe 2、拒否strategy反復1、ずれ認識未検出1、言語混在1、stance mismatch 1。
- B: 適合1/12、停止0、質問11、助言0、励まし2、称賛1、positive reframe 0、拒否strategy反復1、ずれ認識未検出1、言語混在1。
- 助言0等は有限の検出器による件数であり、意味的な不存在を保証しない。過剰称賛、拒否済み励まし反復、旧話題復活、直近参照喪失、日本語の自然さはJSONに原文と既存CPU判定を保存し、独立した人間の評価欄を未評価のまま残した。称賛検出だけで「過剰」と断定しない。拒否strategyは質問と検出されており、励まし拒否後の反復の改善はこの系列では測定できない。

## コスト

全体53.281秒。Aは34.265秒、prompt 27512 tokens / output 284 tokens。Bは18.907秒、prompt 23897 tokens / output 265 tokens。ローカル生成のためAPI料金は発生させていない。電力・GPU実稼働率・他アプリの負荷は未計測。A最初の要求にモデルloadを含むため単純な速度優劣は主張しない。要求ごとのOllama load/prompt_eval/eval時間をJSONのraw_responseに保存。

## 原文に残る問題と採否

- Bで唯一CPU適合した「眠い」への返答は「そうか、眠そうだね。ゆっくり休んで元気を取り戻そう。」。この表現に検出ラベルは付かなかった。CPU適合を人間の自然さ・要求適合の正解ラベルとして扱えない例として原文を残す。
- 拒否「そういうことじゃない」にはA/Bとも「そうだったね、誤解した。明日は何を予定しているの？」。質問と拒否strategy反復が残る。「誤解した」の認識表現も現在の謝罪heuristicには一致しないため、missing_misalignment_acknowledgmentは誤検出の可能性がある。
- 400位へのAには「お疲れさamas」「participation」、Bにも「お疲れさamas」が出たが、その行でlanguage_mixingは検出されなかった。行1の中国語は検出された。言語検査のcoverageに限界がある。
- Bの質問検出は11/12でAの9/12を上回った。短縮で遵守を改善できたという支持は弱く、事前承認例も人間の自然さ評価もないため採用しない。長い共通systemと履歴の影響は残り、指示短縮だけの原因切り分けには限界がある。禁止語を追加して数値を合わせない。

## 回帰検証

既存全unit 472/472を一括で一回実行（85.560秒）、既存Behavior107/107を一回実行。比較用の新規integrity 2/2は履歴・非policy context不変と明示助言許可を確認。最後の--inputs/上書き保護追加後に関連2件だけを再確認し、実モデルは追加実行していない。既存FIO/Web/State/Replay/Preference承認/fail-openの実装も期待値も変更なし。全unitの個別結果はgeneration-comparison-unit.log、Behaviorはgeneration-comparison-behavior.log、追加検証はgeneration-comparison-integrity.logに保存。

## 実行コマンド

```powershell
python -m pip install -r requirements.txt
# 実測は既存のJanome入りvenvのPythonを利用。学習資産は未使用。
python scripts/generation_comparison.py --run --output reports/generation-comparison-new.json
# 保存済みの時刻/履歴/CPU contextをそのまま再生（新しい出力先が必須）
python scripts/generation_comparison.py --inputs reports/generation-comparison.json --run --output reports/generation-comparison-rerun.json
# --runを省けば実推論なしで入力を準備する
python -m unittest discover -s tests -v
python experiments/run_all.py --no-write
python -m unittest discover -s tests -p test_generation_comparison.py -v
git diff --check
```

generation-comparison.jsonは実行時点のhead、モデルdigest、入力hash、原文24件、CPU判定、token/時間、未評価の人間評価欄を保持する。実行後の補助変更は正確なpayload再生と既存証跡の上書き保護のみで、実行版scriptのSHAも同JSONに記録した。再実行時は独立した結果として保存する。本番daemon・既存会話ログを削除/初期化していない。
