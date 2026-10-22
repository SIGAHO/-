# Breaktail v2

**Companion Coreを脳幹に残し、PC上で常駐してOllamaの `qwen2.5:14b` と会話する相棒MVP。**
CPUがState / Time / Topic / Open Loops / Memory / Emotionを管理し、モデルは応答を生成します。
既存Coreの研究記録・失敗候補・期待条件は保持しています。

## 起動

Python 3.10以上と [Ollama](https://ollama.com/) を使用します。

```sh
python -m venv .venv
# Windows
.venv\Scripts\python -m pip install -r requirements.txt
ollama pull qwen2.5:14b
ollama serve
# 別のターミナルから
.venv\Scripts\python chat.py
```

macOS/Linuxは `.venv/bin/python` を使用してください。
Ollamaが既に起動中なら `ollama serve` は不要です。初回のモデルロードには時間がかかります。
Janomeは既存Topicの形態素解析用、WindowsのtzdataはIANA時計用です。
**OllamaAdapter自体は標準ライブラリのみ**で [HTTP /api/chat](https://docs.ollama.com/api/chat) を呼びます。

```sh
python chat.py --model qwen2.5:14b --host http://127.0.0.1:11434 --event-log data/events.jsonl --timeout 180
python chat.py --fake --event-log data/fake-events.jsonl
```

上の `python` は依存導入済みの仮想環境のPythonです。
モデルは `--model` > `BREAKTAIL_MODEL` > `qwen2.5:14b` の順に選択。
接続先は `--host` > `OLLAMA_HOST` > `http://127.0.0.1:11434`。
ログは `--event-log` > `BREAKTAIL_EVENT_LOG` > `data/events.jsonl`。
`--fake` は配線確認用で、自然会話を生成するモデルではありません。

## 常駐とchatの連携

同じチェックアウトのフォルダで、先にdaemonを起動します。chatを閉じてもdaemonは観測と状態保持を続けます。

```powershell
.venv\Scripts\python daemon.py --interval 30
# 別のターミナルで、同じフォルダから
.venv\Scripts\python chat.py
# chat内で /status
```

`--event-log` は両方で同じパスを指定してください。既定は `data/events.jsonl`。
観測間隔は `--interval` > `BREAKTAIL_OBSERVE_INTERVAL` > 30秒。正の有限秒数のみ指定できます。
daemon側に `--model`, `--host`, `--timeout`, `--fake` を指定できます。接続中のchatのモデル設定は使いません。
daemon不在ならchatは従来の単独動作になり、その場合はchat側のモデル設定を使用します。
起動時に接続先を選び、会話の途中で自動的に接続先を切り替えません。

Windows標準APIから現在時刻、OS稼働秒数（uptime）、実行ファイル名ごとのプロセス数だけを取得します。
PID・コマンドライン・ファイル本文・ブラウザ履歴・ページ内容・キーログ・クリップボードは取得しません。
ウィンドウタイトルは既定で無効です。必要な場合だけdaemonに `--foreground` を付けます。
タイトルには文書名やページ名が含まれることがあります。有効にするとログとモデルのCPU文脈にも渡ります。
利用できないOS情報は `null`。Windows以外では現在時刻以外は未対応です。

`RuntimeObserver` の観測のみを `runtime_observation` / source=`runtime` として保存します。
時刻とuptimeの通常の経過は差分に数えず、プロセス名・数や任意のタイトル変更、uptime低下を記録します。
`/status` では現在時刻、未完了事項、話題、感情、最後のPC観測のみを表示します。
差分がない観測も実行中のメモリでは更新しますが、再起動直後のPC観測は最後の永続イベントから復元します。
プロセス変化が多いPCではログは増えます。ローテーション・圧縮は未実装です。

daemonが単一の書き込み元です。chatはランダムポートの `127.0.0.1` HTTP IPCとランダムトークンで接続します。
ログ隣の `.daemon.json` は接続情報です。ログと同様に自分のWindowsユーザーだけがアクセスできるフォルダに置いてください。
通信は外部インターフェースには公開しません。PC観測は会話時にOllama接続先へ渡るため、外部ホストの指定には注意してください。
同じログのdaemon二重起動、単独chatとの併用はOSロックで拒否します。複数chatはdaemon内で順番に処理します。
モデルの応答待ち中もPC観測・状態照会は続きます。モデル失敗時もユーザー入力は残り、AI応答を捏造しません。
IPC失敗時は自動再送しません。応答だけ失われた可能性があるため、再接続して状態を確認してください。

daemonの終了はCtrl+C。異常終了でもOSがロックを解放し、同じログで再起動するとReplayします。
ロック用ファイルが残るのは正常です。起動中にロック・接続情報・ログを削除しないでください。
ログオン時の自動起動登録、Windowsサービス化、トレイUI、自動操作は含みません。
コンソールを閉じずにdaemonを起動したまま使う方式です。

## 会話・訂正・再起動

普通に入力すると会話します。空行は無視、`/exit` またはCtrl+C / EOFで終了します。

```text
you> あとで机を片付ける
you> まだ終わってない
you> 終わった
you> /correct favorite.color 赤じゃなくて青
you> 好きな色を覚えてる？
```

訂正対象が明らかでない文を勝手にStateへ確定しません。
`/correct キー 訂正文` で対象を指定すると、明示訂正がStateと訂正記憶へ反映されます。
対象未指定の訂正も履歴へ残り、モデルに訂正を優先するよう伝えますが、Stateの確定は保証しません。

同じログで再起動すると自動Replayし、話題・未完了事項・ユーザー記憶・訂正State・感情を復元します。
時計は現在の実行環境から再取得します。記憶の作成時刻、話題と未完了事項の観測時刻は元イベントに基づきます。
内部の派生IDは再生成されます。直接の `state.propose()` 呼び出しはログにないため復元対象外です。

会話経路は `user → CompanionCore.handle() → PromptBuilder → ModelAdapter → reply → record_assistant_output()`。
短い構造化CPU文脈と最大6000文字の最近の履歴を渡します。
現在の入力は記憶へ追加する前に検索し、自分自身で検索枠を埋めません。
接続失敗・タイムアウトでは偽の返答を記録せず、入力とCPUの更新は保持します。次の入力で続けられます。

ログはUTF-8 JSONLで追記・flush・fsyncします。**複数chatはdaemon経由で同じログを共有できます。**
ライブラリから永続チャットを使う場合も `connect_session()` / `LocalSession` を使用し、終了時は `close()` してください。
低水準の `CompanionCore` / `EventStore` は追記単位の排他とサイズ変更検知を備えますが、会話全体の所有権は取得しません。
これらを同じログへ直接接続してdaemonと併用する構成は避けてください。競合を検知した古い書き込み元は停止します。
破損したログは黙って捨てず、行番号付きで起動を止めます。修復前に原本を保管してください。
`data/` はGit対象外です。会話はOllama接続先へ送ります。外部ホストの設定時は接続先を確認してください。

## 学習資産・事実の境界

- 旧Breaktailの教師データ、Teacher Store、自己生成学習データ、LoRA / adapter / checkpointは再利用しません。
- 学習経路はありません。対象モデルに教師文・正解ラベル・採点基準を作らせません。
- `ModelAdapter` は推論APIの抽象化であり、学習用adapter資産ではありません。
- AI応答は `assistant_generated` としてログにのみ保存し、State・Verified Memoryへ自動昇格させません。Replayでも同じ境界です。
- ユーザー申告の記憶は検証済みの客観的事実ではありません。訂正記憶の旧値はアーカイブします。
- 不明は不明と言う、CPUのState/時計を優先する、AI誤答を事実化しない、という指示を毎回渡します。文章上の遵守はモデルの性能に依存します。

## 検証

```sh
python -m unittest discover -s tests -v
python experiments/run_all.py
python demo.py
```

結果と再現方法は [MVP検証記録](experiments/mvp/VALIDATION.md)。
常駐拡張は [常駐MVP検証記録](experiments/resident/VALIDATION.md)。既存113件に常駐20件を追加し、計133件を実行しました。
元のMemory 2件（空検索・0件上限）、Emotion 4件（空入力・否定・引用・訂正時覚醒）を、既存の期待を変えず修正しました。
FakeModelAdapterによる18シナリオに加え、HTTP契約・失敗応答等を検証します。
Fakeの文面は配線テスト用の仮仕様であり、自然会話品質の正解・教師データではありません。
実モデルで雑談・未完了事項・訂正・再起動後の参照を確認しています。

外部人間データの過去サンプルはすべて**観測済み回帰データ**として再実行し、新しい未使用評価と呼びません。
元のfreeze・manifest・過去候補のREVISEは保持します。
Topicの分割・切替見逃し、有限ルールによる感情推定・完了解釈、曖昧な訂正対象の解決は残る制限です。
[既存実験](experiments/README.md) と [憲法](CONSTITUTION.md) も参照してください。
