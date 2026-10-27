# Conversation Alignment v1 実装報告

2026-10-27 / 対象: `SIGAHO/-`, `codex/breaktail-v2`。
開始点: `b3c52d3c40f0651d62c5358f33466b8c70854131`。mainの変更・mergeは行わない。

## 原因と構造

従来は生成モデルが会話行為と文章化を同時に決め、StyleValidatorが口調を後から修正していた。そのため「眠い」から助言、「不満」から励まし、結果報告から質問へ寄る癖を、方針として止められなかった。直近原文のpinning、FIO Session/Experience、Replay、Web/KnowledgeGateは既存の仕組みを保持した。

今回追加した経路は Memory / ConversationState / PolicyPlanner / Generator / PolicyVerifier / Feedback。Memoryは知識、Policyは行為、Qwenは文章化を担当する。Dialogue act、参照先のturn ID、stance、直前の実際の返答strategy、反応、riskをCPUで推定する。推定は事実や正解ラベルにしない。直近4往復を最優先し、省略発話は直前1〜3往復へ結び付ける。原文はrole付き履歴に置き、CPU JSONには重複コピーしない。

ResponseSpecはact、助言/励まし/称賛/質問/reframe許可、ずれの受け止め、stance、質問数、長さ、言語、参照対象に加え、repetition/specificity/relatednessを持つ。苦情・睡眠状態・低順位の報告・挨拶では頼まれていない会話行為を抑える。拒否/訂正の後は自分のずれを受け止め、前のstrategyを反復しない方針にする。個別の不適切返答を禁止語へ追加する構造にはしていない。

PolicyVerifierはspeech actの形・質問数・拒否strategy反復・明らかな参照喪失・言語混在を検査する。StyleValidatorは補助。lowではpolicy候補1件、medium/highで違反がある場合だけ2候補まで比較する。出力自体の言語/口調不良はriskをmediumへ上げ、その理由をtraceに残す。policyとstyleで別々に再生成せず、全体で最大1回。残存する非安全性違反はfail-open。通信timeout、空応答、不正Unicodeは従来の生成失敗として区別する。

## FIOとFeedback

Session JSONLの既存schemaを維持し、provenance内にalignment監査情報を追加。Experienceには不変のassistant_responseとnext_user_reactionを別イベントとして追記し、causation_idで結ぶ。生成文、policy_spec、verifier_result、次反応、explicit_feedback、rejected_strategy、session/turn IDを追跡できる。次反応が来る前のassistant_responseはnullを保持し、後続reactionイベントをjoinする。既存のheat冷却/参照後reinforce、truth revision、Session FTS5、failure recallは保持する。

明示的な拒否・訂正・「今の返答がいい」だけから、承認待ち選好候補を作る。「ああ」、単なる次発話、verifier PASSは承認にならない。assistant本文はassistant_generatedの引用で、State/Verified Memoryへ昇格しない。拒否時は関連する過去の失敗だけをrecallする。現在の反応を自分自身でrecallしない。

EventStoreの確定済みcommit envelopeからSession/Experience/preferenceのwritebackを冪等に回復する。原文userイベントのfsync後、準備前に落ちた最後の未応答feedbackも原文から回復するが、assistant応答は捏造しない。選好ledgerはflush/fsync、追記lock、他writer検知、破損時停止を持つ。

`training/preferences/schema-v1.json`、候補import/人間approve/trusted exportのCLI、学習readinessスクリプト、QLoRA設定scaffoldを追加。実ユーザーfeedback > 人間執筆例 > 外部teacher候補の優先順。全ソースで、候補hashに結び付いた独立の人間reviewがtrusted化の必要条件。外部teacher候補はteacher_generated=true、人間未承認を必須とし、target Qwen本体や別表記をteacherに使わない。同じsessionはSHA-256でtrain/dev/blindへgroup splitし、blindの学習/tuning exportを拒否する。

## 主要ファイル

- `src/companion_core/alignment.py`: ConversationState / ResponseSpec / PolicyPlanner / PolicyVerifier。
- `src/companion_core/chat.py`, `prompt.py`, `style.py`: shared chat/daemon経路への制御・bounded ranking・debug接続。
- `fio_memory.py`, `experience.py`, `preferences.py`: 因果イベント、失敗recall、承認待ち候補、回復と承認ゲート。
- `tests/test_alignment.py`, `tests/fixtures/conversation-policy-v1.jsonl`: 63 multi-turnケースを含む83新規テスト。
- `scripts/policy_suite.py`, `alignment_smoke.py`, `preferences.py`, `training_readiness.py`: 評価・12入力観測・承認/export・readiness。
- `training/preferences/`: versioned schema、adapter設定、利用手順。

## テスト結果

機械的検証の集計は既存unit 389 + 新規83 = 472、既存Behavior 107。新規63 multi-turn policyケースは83件に内包され、二重加算しない。

既存全unitを含む最初の一括実行は460件で、13 failure / 6 error。そのうちローカル通信制限によるdaemon/launcher失敗を通信可能な環境で再検証した。実装由来では、CPU JSONへの原文重複、追加Experience数、追加status項目、新しい方針検査によるscripted questionの再生成が既存wiringテストと衝突した。原文重複は本体を修正し、Experience/statusの期待は新フィールドを含む厳密な期待に拡張した。履歴・数量routerのテストでは旧質問fixtureを維持するため新verifierだけをmockし、元の原文・参照・要求回数のassertionは維持した。実際のverifierとrankingは新規統合テストで別に検証する。PASSのために許容率や内容期待を緩めていない。

以後は失敗/変更対象だけを再実行。最終変更対象137件PASS、新規83件PASS、FIO統合22件PASS、Hardening 80件PASS。daemonは20件中19件と、追加status schemaの1件を別途再確認して全てPASS。これは472件の二度目の一括PASSという意味ではなく、初回全件実行と対象再確認を合わせた結果。

- Behavior: state 25、correction 12、topic 21、open_loops 22、memory 14、emotion 13、計107/107 PASS。
- FIOのChatSession全経路500ターン: 13/13 checks PASS。500 Session、500 turn、500 assistant_response、499 next_user_reaction、合計1499 Experience。heat 1.0→0.5→0.75も確認。既存500件のstorage/restart unitも初回にPASS。
- 観測済みcorpus: 7000発話 / 638対話 / 638 Replay成功、既存不変条件failure 0。再実行1回のみ。これらは開発/回帰データで未使用blindとは呼ばない。
- policy suite: 63/63の正負controlが期待通り。recent_reference_resolution=1、response_spec_adherence=1、negative_control_detection=1、各違反rateとabort rate=0。これは工学的fixtureでの検査/配線結果で、実モデル品質の数値ではない。
- compileallとgit diff --checkも成功。

## 実Qwen2.5:14b: 12ターンのみ

生成成功12/12、会話停止0/12。CPU検査適合2/12、残存違反10/12。成功した会話品質とは報告しない。最大1回の再生成でも質問や励ましが残り、fail-openで継続した。原文と各State/Spec/検査は`alignment-smoke.json`に保存。

具体的な残存例:

- 「明日のイベントで一日潰れる」→「明日のイベント、どんなの？busyな感じなんだね。」質問を検出。英単語混在の一部は検出できていない。
- 「そういうことじゃない」→謝罪後も「明日のイベントはどのように過ごす予定？」。拒否済み質問strategyの反復を検出。
- 「眠い」→「休んで元気を取り戻せば、今日も一日頑張れるよ。」励ましを検出。
- 「454位！商品なし！」→「454位だったんだね。何かあったのか？気分はどう？」不要質問が残存。
- 「よお！」→過去の454位を持ち出して質問。質問は検出したが、旧話題復活の意味検出は不十分。
- 参照先turn IDと直近文脈の保持は動作したが、「ランナーとして」「ああ」の2件のCPU検査適合も自然さや関連性の合格を保証しない。

smoke後、最終のCPU原文重複除去、挨拶時の補助文脈抑制、styleによるrisk昇格の表示、crash回復等を機械テストで修正・確認した。ユーザー指定の実モデル予算を超えないため、最終差分で追加smokeは行っていない。実モデル12入力で23回の推論要求（各入力最大2回）を使用した。

## Datasetと学習へ進む条件

実preference dataset 0件 / human_approved 0件 / teacher_generated 0件 / trusted train/dev 0件。smokeのscripted拒否から機械的にできた候補1件はテスト環境ごと破棄し、実ユーザーデータや学習データへexportしていない。fixtureは工学的仮説であり、teacher正解やhuman承認例として使わない。旧資産の再利用なし。

承認済み単独good/bad主体なら[KTO](https://huggingface.co/docs/trl/kto_trainer)、chosen/rejected pair主体なら[DPO](https://huggingface.co/docs/trl/dpo_trainer)または[SimPO](https://github.com/princeton-nlp/SimPO)を候補にする。十分な多様性、ソース/ラベル比率、dev評価、未使用session holdoutを人間が監査してから手法を選ぶ。片側をtarget Qwenで生成してpairを埋めない。

GPU実測はRTX 3060 / 12288 MiB。Qwen常駐後の空きは838 MiB。現状態で学習を開始できるとは判断せず、学習は実行しなかった。HF base revision/tokenizer、対応CUDA/PyTorch/PEFT/bitsandbytesとtrainer版の固定、推論モデルを退避した状態での実activation/optimizerメモリ測定、保存容量が必要。12GBで14B QLoRAが収まる保証はない。Ollama GGUFは学習baseではない。baseを変更せず、adapterをbase revision / dataset SHA / run IDで版管理し、adapter unload/旧版選択でrollbackする。

## 残る問題と起動

このv1は失敗を観測・因果保存・承認待ちデータへつなぐ構造を完成させたが、Qwenの返答品質は未達。CPUのspeech-act/参照/言語検査は有限の言語的heuristicで、万能な意味判定ではない。言い換え、混合行為、間接的な助言、古い話題の自然な再導入、リスク分類の誤りには見逃し/誤検出があり得る。未知の冗談や否定範囲も未保証。現状のfixtureは開発用で、一般化の証明ではない。学習scaffoldはreadinessと設定までで、optimizer実行、adapter変換/配信、実rollback試験は未実施。

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
# Ollama起動・qwen2.5:14b導入済みなら
.venv\Scripts\python daemon.py --model qwen2.5:14b --interval 30
# 同じフォルダの別ターミナル
.venv\Scripts\python chat.py
# /statusで内部State / Spec / verifier / recall / candidateを確認
```

コード更新後は既存daemonを再起動する。モデル追加学習は起動条件ではない。
