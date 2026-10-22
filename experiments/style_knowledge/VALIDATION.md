# Breaktail v2 Style / Knowledge 検証

実施日: 2026-10-23 JST。開始HEAD: ac7fcca。
実行した本体のSHA-256は smoke_summary.json / external_regression.json に記録。
最終確認時、この2ファイルの全ソースハッシュと作業ツリーが一致。

## 実装

- Memoryのreliable context判定は、active・出典・対象名・質問の内容語・要求属性をCPUで照合。AI生成、単なるユーザー申告、質問や名前の反復を外部事実の根拠にしない。
- Memoryの重複統合を同一source内に制限。verified情報が似たユーザー文に吸収される問題を防止。
- KnowledgeGateが外部確認の要否と根拠を決定。検索機能は今回未接続。未確認ならモデルを呼ばずにCPUの返答を返す。根拠がある場合は根拠をプロンプトへ渡す。
- 6軸のStyleProfile、毎ターンの明示ルール、StyleValidatorを導入。1回だけ文体変換を要求し、既知の定型尾部だけ安全に削る。再生成に会話全体を渡さず、draftと設定だけを渡す。
- 検査を通せない応答はModelError。入力だけを保持し、不適合なモデル文は記録しない。daemonと単独chatで同じ経路を利用。

## 最終確認結果

- 既存133＋追加24、**157/157テスト成功**。出力は unit_tests.txt。既存のテスト・期待値は変更していない。
- 追加テストには喜び、ツッコミ、急ぎ、学校、課題、技術、訂正、雑談、興奮、短文、不要な質問の抑制、assistantese、丁寧語、長さ等の15方向のサブケースを含む。これらは毎ターンの設定・ルール配線の検証であり、実会話品質を15件の正解文で採点したものではない。
- Fakeによる再生成、再生成失敗、1回上限、尾部だけの削除、内容を含む文・画像記法の保全、空になった再生成から原文の安全な尾部削除への復帰、daemon経路を確認。
- 不明な英字名・日本語作品名、属性不足、類似する別名、複数対象、AI/申告/archived除外、Stateの出典、Memory有無、反復・Replay後の未確認維持を確認。
- 既存6系統 **107/107 PASS**。出力は experiments.txt。
- 既に観測済みの外部回帰 **7000発話 / 638対話** を再実行。不変条件7000/7000、Replay638/638、前回MVPの全指標と一致。external_regression.json に保存。新しい未使用評価とは呼ばない。
- 過去4実験は保存済み凍結候補でも再実行。topic_corpus / topic_holdout / topic_holdout_v2 は以前どおり REVISE・終了コード1、v3のみPASS・終了コード0。全指標が元記録と一致。historical_recheck.json。失敗をPASSへ変更していない。
- demo.pyも再実行し、AI出力のState昇格なしを確認。

## 実 qwen2.5:14b の観測

Ollama上の実モデルで、喜び、軽い訂正、時間、急ぎ、学校の発表、技術、終了報告の12往復を実行。
同じ入力列をac7fccaのPromptBuilderと新実装へ別々に渡した。
baselineは元のプロンプトを使用する比較であり、古いリポジトリ全体を起動したものではない。
追加で未知の曲名・その歌手の2往復と、検証用の架空作品をverified Memoryへ入れた1往復を確認した。
**新実装は合計15往復、うち13往復が実モデル応答、2往復がCPUの未確認応答。実モデル呼び出し17回（再生成4回を含む）、最終試行のエラー0。**

最終12往復の記述的な比較:

- 実装で明示した禁止句がある返答: **5/12 → 0/12**。新実装の初回生成だけでは1/12で、出力検査も必要だった。
- 丁寧語の検出マーカー総数: **42 → 4**。
- 平均返答長: **109.7 → 37.4文字**。
- 疑問符で終わる返答: **6/12 → 4/12**。意味のある確認も含むため、この数自体を会話品質の正解にしていない。
- 未知の曲と歌手は2件とも未確認。架空作品のverified Memoryがある場合は外部確認不要となり、モデルへ根拠を渡せた。

短く普段の話し言葉へ寄る変化は確認できた。ただし完全な人格制御には至っていない。
定型句の言い換えによる申し出、不必要な質問、急ぎへのちぐはぐな励まし、混ざった丁寧語・異言語断片が残る。
時間計算も、20分後の予定に13分と答える誤りが残った。今回は時刻の文章化・予定時刻の確定計算を修正していない。
禁止句検出0件は有限の検査表現についての結果であり、あらゆるassistanteseが消えたことを意味しない。

## 開発途中の試行と制限

最終試行だけを成功例として選別しないよう、先行試行もメタデータを保持:

- smoke_first_summary.json: 旧5/12→検査後0/12。ただし普通名詞の「テーマ」を作品と誤検出した。検出と文脈引き継ぎを修正。
- smoke_second_summary.json: 12往復チェックポイントのうち1件が口調で停止。後段のMemory有りプローブも口調で停止して、スクリプトが中断。チェックポイントから集計した記録。
- smoke_third_summary.json: 再生成後の違反で4件停止。安全な尾部削除を整備。
- smoke_fourth_summary.json: 同3件停止。再生成が会話を続け直してしまうため、短い文体変換専用呼び出しへ変更。
- smoke_summary.json: 最終ソースでの上記結果。途中で制約や既存期待値を緩めていない。

これらは開発中の観測済みスモークであり、独立したブラインド評価や統計的な品質保証ではない。
温度0.6の単一モデルの試行なので、再実行時の数値・文面は変動する。
先行試行後に修正しているため、最終結果を未使用データでの改善率と解釈しない。
生の生成履歴はGit対象外のwork/style-smoke-*.jsonに保存し、実ユーザー会話・PC観測値は公開していない。

KnowledgeGateは有限の形態素・文字列規則で、名前の見逃し・止めすぎ・同名異物・意味的矛盾・最新性に限界がある。
trusted Memoryへの登録元の検証は呼び出し元の責任。直接API登録の永続化は今回の範囲外。
StyleValidatorも有限規則で、正当な引用やコード内の禁止句を再生成対象にする場合がある。
再生成の内容の同値性をCPUで証明する機能はない。違反が残る場合は1回で停止するため、応答不能は今後も起こりうる。

## 再現

```powershell
# 書き込み可能な一時フォルダとlocalhost通信が必要
$env:TEMP = Join-Path $PWD 'work\test-temp'
$env:TMP = $env:TEMP
New-Item -ItemType Directory -Force -Path $env:TEMP | Out-Null
$env:PYTHONIOENCODING = 'utf-8'
.venv\Scripts\python -m unittest discover -s tests -v
.venv\Scripts\python experiments/run_all.py --no-write
$env:PYTHONPATH = Join-Path $PWD 'src'
.venv\Scripts\python experiments/mvp/replay_regression.py --archive work/corpora/JMultiWOZ_1.0.zip --bsd-dir work/corpora --output work/external-recheck.json
.venv\Scripts\python experiments/style_knowledge/smoke.py
.venv\Scripts\python demo.py
```

外部コーパスは既存manifestの固定版を使用。過去候補の再現は各実験READMEと保存snapshotに従う。
対象モデルには会話と一度だけの文体変換のみを依頼した。教師データ・正解ラベル・採点基準・自己採点の生成依頼はゼロ。
テストはユーザー指定の実装契約を検証する開発用仮説であり、自然会話の人間由来Ground Truthではない。
ユーザーの会話本文の教師データ化、追加学習、旧Breaktail学習資産の流用はない。

最初の通常sandbox実行では一時フォルダ権限とlocalhost制限により失敗した。許可された実行環境とworkspace内TEMP/TMPで同じ検証を再実行した。
