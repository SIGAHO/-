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

## 口調の設定と出力検査

CPU側の `StyleProfile` は `formality=0.10`, `verbosity=0.25`, `energy=0.65`,
`teasing=0.30`, `directness=0.85`, `assistantese=0.02` が既定です。
各値は0〜1の有限数。順に丁寧さ、説明量、勢い、軽い冗談、直接さ、定型アシスタント表現の許容量です。
毎ターン、数値と明示的な口調ルールをPromptBuilderへ渡します。
普段の話し言葉、短文、ユーザーのテンポに少し寄せる、意味のある確認以外で質問を足さない、が基本です。
冗談や「ｗ」は必須ではありません。人物像を学習する処理ではなく、推論時の設定です。

PowerShellで起動前に設定できます。省略した軸は既定値を使います。

```powershell
$env:BREAKTAIL_STYLE = '{"formality":0.1,"verbosity":0.25,"energy":0.7,"teasing":0.3,"directness":0.85,"assistantese":0.02}'
.venv\Scripts\python daemon.py --interval 30
# daemon不在の単独利用なら同じ環境変数で chat.py を起動
```

daemon接続時は **daemonプロセスの設定** を使います。変更・コード更新後はdaemonを再起動してください。
ライブラリでは `ChatSession(adapter, event_path, style_profile=StyleProfile(...))` でも指定できます。
数値は指示として使い、定型句・過剰な丁寧語・長さはCPUでも検査します。
`assistantese` を高くしても、明示禁止した句は通しません。
低formalityでは丁寧語の連続使用（検出マーカー2個以上）を再生成対象にします。
通常の上限は `160 + 640 * verbosity` 文字、詳細・手順・コード等の明示依頼では1800文字です。
引用やコード内の文字も検査対象なので、正当な引用を厳しく判定する場合があります。

`StyleValidator` が禁止句・過剰な丁寧語・長さ違反を検出すると、短い書き直しを **最大1回** 要求します。
再生成後に残る既知の定型尾部だけを削り、途中の説明・数値・コードは切りません。
それでも違反、空応答、通信障害なら `ModelError`。入力は保存し、不適合な返答は会話ログへ記録しません。
無限再生成や、別の定型返答へのすり替えはありません。通常chatとdaemonは同じ経路を通ります。

## KnowledgeGateと信頼できる根拠

`MemoryEngine.has_reliable_context(query)` / `reliable_context(query)` は、単なる検索ヒットと根拠を分けます。
activeな `verified_memory` / `runtime` / `system` を対象に、対象名、質問の内容語、
作者・発売日・価格・意味等の要求属性の一致をCPUで保守的に調べます。
タイトルだけ、質問文、不確かな文、別属性、archived、AI生成文は根拠にしません。
ユーザー申告・ユーザー訂正は会話の申告として利用しますが、外部の客観的事実の確認済み根拠にはしません。
Memoryの類似文統合もsourceをまたがず、信頼済み記録が申告へ吸収されるのを防ぎます。

`KnowledgeGate` は引用された名前、英数字名、形態素上の固有名詞、未知のカタカナ、明示的な作品説明構文等を検出します。
質問・説明依頼で根拠がなければ `external_required=True`。
直前のユーザー側の対象を使い、「その作者は誰？」「歌手は？」の省略にも保守的に対応します。
同じ質問の反復やAI回答、Replayによって信頼度が上がることはありません。
Stateもsource/statusと同じ内容照合を通し、十分な根拠があれば `evidence` をPromptBuilderへ渡します。
たとえば信頼できる呼び出し元から `core.memory.add(確認済み資料, SourceType.VERIFIED_MEMORY)` で登録できます。
この低水準APIへの直接登録は永続化されません。今回、任意のユーザー文をverifiedにするCLIや自動昇格は追加していません。

**今回はWeb検索未接続です。** 外部確認が必要なら14Bを呼ばず、CPUが短い「未確認」の返答を返します。
検索要否の最終決定はモデルに委ねません。信頼できるMemoryがある場合は外部確認を要求せず推論へ進みます。
将来の検索結果も、出典を検証してから根拠へ入れる必要があります。

これは意味理解や完全な固有表現抽出ではありません。表記ゆれ・同義語・長い省略・同名異物には限界があり、
保守的に止めすぎる場合と検出を逃す場合があります。信頼済み文書内の矛盾検出や最新性判定も未実装です。
支持された回答でも、根拠から逸脱しないことの文章上の保証まではありません。
時計・残り時間の最終文章化も従来どおりモデル経由なので、口調改善とは別に誤答が残ります。

## 検証

```sh
python -m unittest discover -s tests -v
python experiments/run_all.py
python demo.py
```

結果と再現方法は [MVP検証記録](experiments/mvp/VALIDATION.md)。
口調・根拠判定の拡張と実14B比較は [Style / Knowledge検証記録](experiments/style_knowledge/VALIDATION.md)。
常駐拡張は [常駐MVP検証記録](experiments/resident/VALIDATION.md)。既存113件に常駐20件を追加し、計133件を実行しました。
元のMemory 2件（空検索・0件上限）、Emotion 4件（空入力・否定・引用・訂正時覚醒）を、既存の期待を変えず修正しました。
FakeModelAdapterによる18シナリオに加え、HTTP契約・失敗応答等を検証します。
Fakeの文面は配線テスト用の仮仕様であり、自然会話品質の正解・教師データではありません。
実モデルで雑談・未完了事項・訂正・再起動後の参照を確認しています。

外部人間データの過去サンプルはすべて**観測済み回帰データ**として再実行し、新しい未使用評価と呼びません。
元のfreeze・manifest・過去候補のREVISEは保持します。
Topicの分割・切替見逃し、有限ルールによる感情推定・完了解釈、曖昧な訂正対象の解決は残る制限です。
[既存実験](experiments/README.md) と [憲法](CONSTITUTION.md) も参照してください。
