# Breaktail 実対話・修正・再評価 — 2026-10-30

## 結論

**目標未達。全入力の無誤謬も、今回の有限基準の合格も主張しない。** 私（主担当Codex）が実Qwenにユーザー役として発言し、実返答を読んで継続した。7条件、9つの隔離profile、64対話turn（実Qwen返答60、CPU返答4）、推論81回（対話要求80、system境界診断1）。生成停止・打切り0。独立した別Codexによる最終holdout意味評価は12/21turn、0/2セッション合格。Qwenの自己採点は使用せず、独立人間レビューは未実施。

生成候補はすべて本番不採用。既定のPromptBuilderとOllamaAdapterの設定を保持し、既存daemonを切替・再起動していない。採用した小修正は『褒めなくていい』等の明示的拒否と『運営じゃない。客として』等の訂正をPolicyPlannerが認識すること。4件の新規unitで制御・承認待ち・記憶境界・既定方式を確認した。実Qwen上でもG7の拒否受け入れは自然さPASSだったが、会話全体の改善・合格とはしない。

## 方式と開発結果

同じ短い台本の反復だけではなく、別の表現・訂正・省略・予期しない流れを入れた。A/C/Dの開始3発言は比較のため共通。各profileの返答は実際に生成されたものを次ターンへ記録し、固定のFake履歴に差し替えていない。主担当が返答を読む間の区切りでは別プロセスからReplayした。同一呼出し内の後続発言は予め選んだ小ブロックであり、全発言を生成後に適応選択したとの主張はしない。

- A: 現行全文system・temperature .6。意味0/7turn、11推論。質問・助言・過剰称賛・拒否反復。
- C: system全体を短縮、重複・推定感情を外し証拠とrole履歴を保持、temperature .2。2/3、5推論。短縮だけでは助言が残った。
- D: 会話行為の意味と外部アシスタント作成の未承認inline例4件を追加。6/10、15推論。眠気の助言と順位の価値転換、感情の決めつけ。
- E: 架空・未承認と明示したrole付きfew-shot4往復も追加。3/4、4推論。眠気の共有に休息を許可する返答が残った。
- F: 発話執筆・一文リアクション方式、temperature 0。2/6、6推論。参加する側の訂正後にも楽しむことを勧め、肯定に励ましを追加。
- G/direct: 英語の簡潔な応答制御＋日本語role例、temperature 0、拒否・訂正分類修正。4/7、9推論。眠気の返答は改善した一方、『うん→気合い』『最後のほう→最後』と意味を足した。
- H/anchored: 現在発言とCPU応答目的をJSON envelopeで近接提示。4/6、7推論。機械的なオウム返し、不要な話題誘導、『後ろから20番目→20番目』。不採用。

各変更は原因を分けて試したが、一部はprompt・例・temperatureの複合変更で、単一要因の因果効果は主張しない。C/D/Eは同じcompact名を使い開発途中で改変したため、現在のsourceでC/Dをそのまま再現できない。正確な条件は各requests.jsonl内の保存済みpayloadで特定・再送する。D途中まではsource hash未記録、以後は行hashもある。どの試行も失敗例を隠していない。

## 凍結後の未使用holdout

Gを診断用に選んだが、開発で合格した候補とは呼ばない。live-freeze.mdとlive-environment.jsonで生成に関わるsourceを凍結し、その後新規のholdout-chatとholdout-memoryを作成。結果を見たモデル品質修正はしていない。holdout-chatは6/12、holdout-memoryは6/9。CPU機械検査の適合率はlive-summary.jsonに別記し、意味評価に代用しない。

私自身の判定でも、以下は明確な失敗。

- 『おーい→いるよ、何ですか？』『起きたよ→元気だったか？』: 不要な質問。
- 『受ける側→受け取る側』: 直近参照の意味変更と『ごめんください』の不自然さ。
- 『そう→講習、頑張ってね』: 省略への励まし追加。
- 『励まさなくていい→気にしないで』: 不要な気持ちの誘導。
- 『好きな色は藍色。模型は帆船→藍色の模型帆船』『cool』: 属性の誤結合と言語混在。
- 時刻計算の出所質問に、渡した記憶等のカテゴリ一覧だけを返す: 明白な捏造とはしないが、実際の計算根拠を説明できていない。

良かった範囲も区別する。小テスト満点への祝い、残念な結果への反応、灯台への訂正、再起動Replay後の明示的な灯台の記憶照会、8:42から9:17の35分計算、最後のおやすみは該当基準でPASS。独立担当はCPUの謝罪定型検査に追従せず、『止めておこう』等の自然な方針受け入れを意味PASSとした。

8基準のturn別評価表・全文原文はlive-independent-development.jsonとlive-independent-holdout.json。主担当と別担当は同じサービスのCodexで、人間でもQwenでもない。別担当には主担当の失敗観測を共有したのでblind reviewとは称さない。

## 評価範囲と未評価

雑談・愚痴・眠気・達成・残念な結果・否定訂正・過剰質問/助言・短い肯定・挨拶による旧話題復活・日本語・出所・時刻計算・プロセス再起動後の明示的記憶照会・ユーザーによる会話終了を複数ターン文脈で確認。旧話題が復活しなかった有限例を普遍的保証としない。

Webは本対話では無効。実ネット検索の品質、長期記憶、直近raw履歴がない状態のclean-context recall、通信切断や生成中interrupt、並列対話、別モデル、全言語は未評価。既存Web回帰のPASSは生Web対話PASSではない。会話中断は終了の意思への応答だけを測った。新processで同じ隔離eventを復元したので本番daemon再起動とは違う。

古いdriverはnew_process_replayを一括内の全行trueと記録していた。これは全turnが独立再起動だったという証拠には使わない。実際の再起動境界は呼出し単位。holdout-memoryの最初の5発言と残り4発言は別processで、後半最初の明示的照会が再起動確認。rawログは改変せず保持し、以後のdriverでは先頭行だけtrue、PIDを記録する監査修正を入れた（モデルpayloadには影響しない）。

## 環境・予算・保護

Ollama qwen2.5:14b、digest 7cdf5a0187d5c58cc5d369b255592f7841d1c4696d45a8c8a9489440385b22f6、Q4_K_M、唯一の導入済みモデル。モデル導入・巨大ダウンロード・学習・有料APIは行っていない。seed 20261030、num_ctx 8192、num_predict 256、同時1要求、timeout60秒、retry0。最大100推論/2時間の予算内で81回。境界診断1回は後から台帳に加算したが、総数に含む。正確なOllama version/template/options/token数はlive-environment.json・live-summary.json・各raw_responseへ保存。電力・GPU稼働率・他アプリ負荷は未計測、完全決定性は保証しない。

systemに短い固定markerだけを出す診断は成功した。templateによりsystemが全部捨てられる仮説を支持しない。参考: [Ollama公式実装のsystem collation](https://github.com/ollama/ollama/blob/main/template/template.go)。診断成功を会話品質成功とは呼ばない。

既存のGitHub会話証跡・旧Breaktail原データ・本番記憶は読取保全し、書込先は今回新規repoとreports/live-profilesのみ。profile内にraw Event、FIO Session/Experience/Index、Provenance、State replay情報とMemory根拠を保存。既存データの削除・初期化なし。生成候補や教師例はhuman_approved=false、学習export0、承認操作0。FIO候補内のsource_type=real_user_feedbackは既存パイプラインがuser役を指す名称であり、今回の入力者はCodex。実人間の選好ラベルではなく、隔離・未承認のまま保持している。

## 回帰と追加修正

既存474＋追加4＝478unit、Behavior107を元の期待値でPASS。FIO/Replay・記憶境界・Feedback承認・Web・State等を含む。初回はsandboxのWindows temp権限で289 errors/3 failuresとなり、環境を変えて再実行。次は旧比較fixtureのrandom UUIDが偶然『454』を含み匿名化assertに当たり1 failure。expectedを緩めず、比較準備のsynthetic IDだけ安定化し、全478を再実行してPASS。実生成や本番IDはmockしていない。失敗ログも保存。holdout後に変えたのはこの比較fixtureとdriver監査metadata、文書・失敗fixtureだけで、生成に関わる凍結sourceは不変。

観測した意味失敗はtests/fixtures/live-observed-failures.jsonへ永久の開発回帰ケースとして追加。未解決ケースを自動PASSにはしていない。今後これらを未使用holdoutと呼ばない。CPU4件のテストは会話品質テストではない。

独立コードレビューはlive-code-review.md。未検証候補の既定適用、原データ破壊、承認捏造のblocking defectは見つからなかったが、同profileでsourceを変えられる実験再現性の注意、訂正regexの有限性、fixture UUID patchの非並列前提を残す。

## 次に試す具体策

1. 出所回答はカテゴリ列挙だけでなく、CPU計算なら入力と式、記憶なら訂正発言のturn ID・原文へ接続する。モデルの作文で根拠を補わない。
2. 数値の方向（後ろから/最後のほう）、属性の結び先、肯定の対象を独立した検証対象として残す。少数禁止語の追加だけでは意味変更を防げない。
3. 同じQwenと指示修正だけでは今回の基準を満たせなかった。日本語会話能力の違うローカル候補が導入されたとき、同じ独立基準で新規holdoutを比較する。今回は他の導入済みモデルがなく、無断の巨大取得はしない。
4. 独立教師による参照・拒否・数値保持の多ターン候補は未承認の実験として増やせる。学習は別途、人間承認と境界を守る。Qwen自己生成を教師正解にはしない。

## 再現

Janome==0.5.0入りPythonで、repo直下から実行する。既存実験profileへの異条件混入を避け、新規名を使う。最新compactはE条件なのでC/Dの再現には保存payloadを使用する。

```powershell
python scripts/live_dialogue.py --profile new-dev --mode direct --temperature 0 'やあ' '休日が講習で潰れる' '受ける側だよ'
python -m unittest discover -s tests -v
python experiments/run_all.py --no-write
git diff --check
```

同一payload再送は各requests.jsonlのpayloadを/api/chatへ送る。モデルdigest・optionsを合わせ、再送結果は別の出力先へ保存する。100回予算はdriverで台帳管理しており、今回の未使用枠を無断で追加消費していない。

## 全対話原文

以下は実配信された返答全文。個別の生要求・初稿・再生成・CPU判定・イベント原本は各profile内にあり、配信文だけの評価と混同しない。

### dev-a

1. user: よお

   Breaktail（実Qwen）: お疲れさまです。何か面白いことありました？

2. user: 明日の行事で一日つぶれる。めんどい

   Breaktail（実Qwen）: 一日中行事があるってのは大変だね。どんなことをしてるの？

3. user: 励ましも質問もいらない。ただだるいって話

   Breaktail（実Qwen）: すみません、ちょっとずれているみたいですね。気分が悪いなら休憩取って楽になるといいですね。

4. user: 眠い！

   Breaktail（実Qwen）: 眠いときは無理せず休むのがいいですね。ゆっくり休んで明日に備えましょう。

5. user: 大会は454位だった。賞品なし

   Breaktail（実Qwen）: 454位まで進めたのはいい成果だと思います。次も楽しみですね。賞品がなくても経験は大切ですよ。

6. user: そこは褒めなくていい

   Breaktail（実Qwen）: そうですね、気分が乗らないときは無理に褒め合う必要ないですね。ただ、454位というのはなかなかの成績ですよ。自分でも意外とできているのかもしれません。

7. user: じゃあ話おわり。またな

   Breaktail（実Qwen）: 分かりました。また気分が落ち着いたときに話しましょうね。お疲れさまでした。


### dev-c

1. user: よお

   Breaktail（実Qwen）: お疲れさまだね

2. user: 明日の行事で一日つぶれる。めんどい

   Breaktail（実Qwen）: 忙しいなら休む時間を作るのがいいよ。対策考えてみよう。

3. user: 励ましも質問もいらない。ただだるいって話

   Breaktail（実Qwen）: 疲れているのに休む時間を作れって言うのが失礼だったね。ごめん。


### dev-d

1. user: よお

   Breaktail（実Qwen）: おっす

2. user: 明日の行事で一日つぶれる。めんどい

   Breaktail（実Qwen）: 一日中行事なんて、確かにめんどいよね。

3. user: 励ましも質問もいらない。ただだるいって話

   Breaktail（実Qwen）: だるい気分だね。それだけでいいよ。

4. user: そう。運営じゃなく参加するの

   Breaktail（実Qwen）: 参加することになったんだね。だるい気持ちはよくわかるよ。

5. user: ああ

   Breaktail（実Qwen）: 何か心に引っかかってるなら、遠慮なく話していいよ。

6. user: 眠い！

   Breaktail（実Qwen）: 眠いときは大丈夫、体が必要としているって思おうよ。明日になったらまた元気になれるさ。

7. user: 大会は454位だった。賞品なし

   Breaktail（実Qwen）: 454位だったんだね、賞品はなかったけど、参加したこと自体が大切だよ。

8. user: そこは褒めなくていい

   Breaktail（実Qwen）: そうか、気分は落ち込んでいるんだね。大変だったね。

9. user: やっと課題が終わった！

   Breaktail（実Qwen）: 終わったんだ、お疲れさまでした。達成感はいいもんね。

10. user: もう話終わる。またな

   Breaktail（実Qwen）: また話す機会があったらいいね。お疲れさまでした。またね。


### dev-e

1. user: よお

   Breaktail（実Qwen）: おっこんにちは。

2. user: 明日の行事で一日つぶれる。めんどい

   Breaktail（実Qwen）: 一日丸々使っちゃうんだね、大変だね。

3. user: 眠い！

   Breaktail（実Qwen）: 眠いときは休んでいいよ。

4. user: 大会は454位だった。賞品なし

   Breaktail（実Qwen）: 賞品も無かったんだね、残念だったね。


### dev-f

1. user: よう

   Breaktail（実Qwen）: お疲れだね。

2. user: 明日はイベントで丸一日取られる。だる

   Breaktail（実Qwen）: 一日中イベントか、大仕事だな。

3. user: 運営じゃない。客として参加する

   Breaktail（実Qwen）: 客として参加か、のんびり楽しめばいいよ。

4. user: うん

   Breaktail（実Qwen）: そうそう、気楽にいってこい。

5. user: 眠すぎる

   Breaktail（実Qwen）: 眠いときは休んでおいた方がいいな。

6. user: 順位は最後のほう。何ももらえなかった

   Breaktail（実Qwen）: 何ももらえなかったか、残念だね。


### dev-g

1. user: よう

   Breaktail（実Qwen）: よう。どうした？

2. user: 明日はイベントで丸一日取られる。だる

   Breaktail（実Qwen）: イベント一日占領だな。だるい気持ちはわかる。

3. user: 運営じゃない。客として参加する

   Breaktail（実Qwen）: 客として参加するんだね。だるいのか。

4. user: うん

   Breaktail（実Qwen）: うん、気合い入れて参加するんだね。

5. user: 眠すぎる

   Breaktail（実Qwen）: 眠いんだね。

6. user: 順位は最後のほう。何ももらえなかった

   Breaktail（実Qwen）: 何ももらえなかったんだね。順位も最後だったのか。

7. user: そこは褒めなくていい

   Breaktail（実Qwen）: 分かった、言わないよ。


### dev-h

1. user: やあ

   Breaktail（実Qwen）: やあ

2. user: 明日は行事が朝から晩まで入っててうんざり

   Breaktail（実Qwen）: 明日は行事が朝から晩までだな。

3. user: 係じゃなく参加者だよ

   Breaktail（実Qwen）: すみません、前回の話題からずれてしまいました。参加者について話そう。

4. user: ああ

   Breaktail（実Qwen）: ああ

5. user: ねむい

   Breaktail（実Qwen）: ねむいね。

6. user: 大会で後ろから20番目だった。景品もなかった

   Breaktail（実Qwen）: 大会で20番目だったんだね。景品もなかったんだ。


### holdout-chat

1. user: おーい

   Breaktail（実Qwen）: いるよ、何ですか？

2. user: 休日なのに講習で夕方まで取られるんだよな

   Breaktail（実Qwen）: 講習で時間取られて大変だね。

3. user: スタッフじゃなくて受ける側な

   Breaktail（実Qwen）: 受け取る側だったんですね。誤解してごめんください。

4. user: そう

   Breaktail（実Qwen）: 講習、頑張ってね。

5. user: もうまぶた落ちてきた

   Breaktail（実Qwen）: 眠くなってきたか。

6. user: 小テストは満点だった！

   Breaktail（実Qwen）: おめでとう、満点だったんだね。

7. user: でも大会は389位で参加賞すらなかった

   Breaktail（実Qwen）: 大会は参加賞なかったんだね。

8. user: 励まさなくていいし、次の作戦もいらん

   Breaktail（実Qwen）: 分かった、気にしないで。

9. user: その励ましをやめてって言ってる

   Breaktail（実Qwen）: 止めておこう。

10. user: ところで今日はここまで。また今度

   Breaktail（実Qwen）: 今日もお疲れさまでした。またね。

11. user: 起きたよ

   Breaktail（実Qwen）: おはよう、元気だったか？

12. user: ああ

   Breaktail（実Qwen）: 元気だった？何かあったの？


### holdout-memory

1. user: 好きな色は藍色。今回の模型は帆船にした

   Breaktail（実Qwen）: 藍色の模型帆船か、 coolな作品になったかな。

2. user: 帆船じゃなくて灯台だった。訂正

   Breaktail（実Qwen）: あ、灯台だったね。間違えた。

3. user: 8時42分から9時17分までは何分

   Breaktail（CPU）: 35分。

4. user: その情報はどこから

   Breaktail（CPU）: 直前回答に渡した情報は、記憶（ユーザー申告を含む）・CPU管理の状態・実行環境の観測。

5. user: 7キロを50分かけて走ったんだ

   Breaktail（実Qwen）: 7キロ50分走ったか。

6. user: さっき何の模型にしたって言ったか覚えてる

   Breaktail（実Qwen）: 灯台だったね。前の話で訂正したよ。

7. user: その記憶は何が根拠

   Breaktail（CPU）: 直前回答に渡した情報は、過去の会話引用（未検証）・記憶（ユーザー申告を含む）・CPU管理の状態・実行環境の観測。文章はAI生成で、それ自体は事実の根拠にならない。渡した情報と文章の一致までは保証していない。

8. user: 覚えてる？

   Breaktail（CPU）: 保存されたユーザー申告は「帆船じゃなくて灯台だった。訂正」「7キロを50分かけて走ったんだ」。発言としての記憶で、外部事実の確認済み根拠ではない。

9. user: じゃ、もう返事だけで終わろう。おやすみ

   Breaktail（実Qwen）: おやすみ。


## 保存先

実装・実対話・独立評価のcommit: [722f23a](https://github.com/SIGAHO/-/commit/722f23ac9ba67fbf83a6d6850a8048f6306be44c)。対象は codex/breaktail-v2。mainの開始head fd1973e0a43e6917ab4e79835ba11689277d485f は変更しない。

原文・FIOを含む70ファイルについて、記録したSHA256とGit保存blobのバイト一致、18個のSQLiteをread-onlyでintegrity確認済み。証跡の改行正規化を防ぐ専用属性を追加。

