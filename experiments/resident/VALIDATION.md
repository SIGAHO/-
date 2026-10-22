# Breaktail v2 常駐MVP 検証記録

実施日: 2026-10-22 JST。実装前HEAD: e1f6bdbd2984d513dfbc1e7781287919d2917c01。

## 結果

- 既存113テスト＋常駐20テスト、計 **133/133成功**。既存テストと期待条件は未変更。実行出力は unit_tests.txt。
- 既存6系統の実験 **107/107 PASS**: state 25、correction 12、topic 21、open_loops 22、memory 14、emotion 13。
- Windows上で別プロセスのdaemon起動、chat CLI接続、`/status`、二重daemon拒否、強制終了後のロック解放とReplayを実行。
- 実Windows APIでuptimeと非空のプロセス名・数一覧を取得。タイトル取得は既定で無効。
- 実Ollama `qwen2.5:14b` へdaemon IPC経由で1ターン接続し、空でない応答を確認。終了後にPC観測のReplayとAI生成文のMemory昇格なしを確認。数値の会話品質採点はしていない。
- 会話本文・実PC観測値・接続トークンは公開しない。実モデルスモークの公開メタデータは smoke_summary.json。

## 追加20テストの範囲

初回runtimeイベント、時計とuptime経過の重複抑制、プロセス差分、タイトル差分と再起動検出、chat接続とCPU文脈、daemon不在フォールバックと単独排他、二重daemon拒否、再起動Replayと重複抑制、runtime source gateとAI昇格防止、statusの範囲と非書き込み、IPC認証、モデル障害時の入力保持、モデル応答待ち中の観測、複数chat直列化、不正間隔、OS観測スキーマ、古い接続情報からのフォールバック、稼働中daemonへの接続障害時の競合防止、低水準の古い書き込み元検知、別プロセスのdaemon/chat/強制終了/Replay。

これらはユーザー要求に基づく実装契約の検証。Fake応答は通信確認用で、教師データ・正解ラベル・自然会話品質の採点基準ではない。対象モデルにそれらの生成や自己採点を依頼していない。追加学習と旧Breaktail資産の流用はない。

## 再現

```powershell
.venv\Scripts\python -m unittest discover -s tests -v
.venv\Scripts\python experiments/run_all.py --no-write
.venv\Scripts\python daemon.py --interval 30
# 別ターミナル、同じフォルダから
.venv\Scripts\python chat.py
# /status で現在の状態を確認
```

本環境の初回テストではサンドボックスの一時フォルダ書き込みとlocalhost通信制限により実行エラーが発生した。書き込み可能なwork/test-tempをTEMP/TMPに指定し、localhost通信を許可した環境で同じテストを再実行して全件成功。期待条件や対象機能を省略していない。

## 制限

- ログオン時の自動起動・Windowsサービス・トレイUIは未実装。daemonプロセスを起動したまま利用する。
- 時刻とuptimeの自然な経過は永続ログを増やさない。現在時刻は照会時に再取得。最新の同一PC状態の観測時刻は稼働中だけ保持し、Replay時は最後の永続イベントへ戻る。
- OS情報はポーリング時点のスナップショット。観測間に終了したプロセスは検出できない。プロセス変化が頻繁ならログは増える。ローテーション・圧縮は未実装。
- Windows以外のOS観測は現在時刻以外null。ウィンドウタイトルは明示オプションであり、本検証で実ユーザーのタイトルは収集していない。
- IPC切断時は自動再送しない。既に入力が保存された可能性があるため、chatを再接続して状態を確認する。
- OSロックはCLI/daemonの所有権を保護。ライブラリ利用もconnect_session/LocalSessionで所有権を取得する。低水準APIでは追記排他とログサイズ変更検知で古い書き込みを拒否する。
- 会話ログの破損時は原本を保持して起動を止める。強制終了が書き込み途中の場合の自動修復は含まない。
- Topicの誤分割・切替見逃し、複雑な感情表現、曖昧な訂正対象など、既存の会話品質上の制限は継続。今回の107実験は既存の有限回帰集合であり、新しいブラインド評価ではない。
