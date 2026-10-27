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
Memory・OpenLoop・訂正Stateの派生IDと作成時刻はイベントから再現します。直接の `state.propose()` 呼び出しはログにないため復元対象外です。

会話経路は `user → CompanionCore.handle() → PromptBuilder → ModelAdapter → reply → record_assistant_output()`。
短い構造化CPU文脈と最近の履歴を渡します。直近4往復の原文は雑談・省略発話でも固定保持し、6000文字の目安より優先します。古い履歴だけを文字数枠で制限します。
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
`assistantese` を高くしても、明示禁止した句は再生成の対象です。
低formalityでは丁寧語の連続使用（検出マーカー2個以上）を再生成対象にします。
通常の上限は `160 + 640 * verbosity` 文字、詳細・手順・コード等の明示依頼では1800文字です。
引用やコード内の文字も検査対象なので、正当な引用を厳しく判定する場合があります。

`StyleValidator` が禁止句・過剰な丁寧語・長さ違反を検出すると、短い書き直しを **最大1回** 要求します。
再生成後に残る既知の定型尾部だけを削り、途中の説明・数値・コードは切りません。
口調違反だけが残る場合は、元文と再生成文から違反の少ない方、同数なら短い方を採用して会話を続けます。意味のある本文は文字数のために切りません。定型句だけの返答も空にはしません。
空応答、不正なUnicode、通信障害は引き続き `ModelError`。入力を保存し、失敗した応答は会話ログへ記録しません。
無限再生成や、別の定型返答へのすり替えはありません。通常chatとdaemonは同じ経路を通ります。

生成・口調再生成の両方で通常の本文は自然な日本語を指定します。既知の中国語文法を含む漢字のみの文、英語だけの文、観測された仮名＋英字＋壊れた語尾は再生成対象です。コード・引用・URLと明示的な他言語指定は除外します。書き直しで言語混在が増える場合は元文を優先します。有限の検出規則なので全種類の崩れを保証せず、残存時も本文を切らずfail-openします。

## KnowledgeGateと信頼できる根拠

`MemoryEngine.has_reliable_context(query)` / `reliable_context(query)` は、単なる検索ヒットと根拠を分けます。
activeな `verified_memory` / `runtime` / `system` を対象に、対象名、質問の内容語、
作者・発売日・価格・意味等の要求属性の一致をCPUで保守的に調べます。
タイトルだけ、質問文、不確かな文、別属性、archived、AI生成文は根拠にしません。
ユーザー申告・ユーザー訂正は会話の申告として利用しますが、外部の客観的事実の確認済み根拠にはしません。
Memoryの類似文統合もsourceをまたがず、信頼済み記録が申告へ吸収されるのを防ぎます。

`IntentRouter` が `external_knowledge` と判定した入力だけ、`KnowledgeGate` へ送ります。
`KnowledgeGate` は引用された名前、英数字名、形態素上の固有名詞、未知のカタカナ、明示的な作品説明構文等を検出します。
質問・説明依頼で根拠がなければ `external_required=True`。
直前のユーザー側の対象を使い、「その作者は誰？」「歌手は？」の省略にも保守的に対応します。
同じ質問の反復やAI回答、Replayによって信頼度が上がることはありません。
Stateもsource/statusと同じ内容照合を通し、十分な根拠があれば `evidence` をPromptBuilderへ渡します。
たとえば信頼できる呼び出し元から `core.memory.add(確認済み資料, SourceType.VERIFIED_MEMORY)` で登録できます。
この低水準APIへの直接登録は永続化されません。今回、任意のユーザー文をverifiedにするCLIや自動昇格は追加していません。

**Web検索は初期状態では無効です。** 下記の `BREAKTAIL_WEB=1` で有効にできます。外部確認が必要で取得できなければ14Bを呼ばず、CPUが短い「未確認」の返答を返します。
検索要否の最終決定はモデルに委ねません。信頼できるMemoryがある場合は外部確認を要求せず推論へ進みます。
検索結果は未検証のExternalEvidenceとして分離し、State/Verified Memoryには昇格しません。

これは意味理解や完全な固有表現抽出ではありません。表記ゆれ・同義語・長い省略・同名異物には限界があり、
保守的に止めすぎる場合と検出を逃す場合があります。信頼済み文書内の矛盾検出や最新性判定も未実装です。
支持された回答でも、根拠から逸脱しないことの文章上の保証まではありません。
対応する時刻・残り時間・四則演算はCPUで最終回答を確定し、モデルと文体の再生成を通しません。

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


## Hardening Phase（c827924以降）

### CPUで保証する境界

- `IntentRouter`: casual_chat / self_state_memory / external_knowledge / time_calculation / task_correction / ambiguous_followup の順序付き判定。KnowledgeGateはexternal_knowledge専用で、根拠なしならモデルを呼ばず未確認。既知の内部・雑談経路に一致しない疑問文も保守的に外部確認へ回す（「地球は丸い？」等、固有名詞がない場合も含む）。
- 「調子どう？」等の雑談では古いTopic・記憶・未完了事項と古い会話履歴を強く注入しない。内容のある話題では明示参照・一致・関連度で採用。「は？」「？？」は直前assistantへ結び、CPUが確認を返す。
- 「Breaktailの記憶に入ってる？」「記憶にある？」等の一般的な記憶照会はCPUが保存済みのユーザー申告を出所付きで提示する。内容を指定した記憶照会はモデルに申告とStateを渡すが、客観的な検証済み事実への昇格はしない。
- 「その情報どこから？」「どこからその情報を？」にはCPUのProvenanceResponderが返答。memory / state / runtime / external / assistant_generatedを回答ログへ保存し、再起動で復元。これは**生成に渡した情報の記録**であり、モデル文章の各主張がその情報から導けるとの証明ではない。旧ログに記録がなければ不明と返す。
- 時刻・日付・曜日・指定時刻までの残り・簡単な四則演算はCPUの確定文。例: `7:41→8:00` は19分、`0.1+0.2` は0.3。計算はevalを使わずASTとDecimalで制限。精度は28桁、長さ160文字、ノード60個、結果絶対値1e30以内。未対応式・不正時刻は確定不能と返す。
- `8時まであと何分？` は今日の8時。過ぎた場合は過去と明示し、明日へ黙って繰り越さない。`明日の8時まであと何分？` で明日指定。残りの秒もCPUで保持する。
- assistant出力はログ専用。State.propose / State.correct / Memory.addもassistant_generatedを拒否。runtimeのtime.*はユーザー訂正で上書き不可（ユーザー申告専用time.user_yearを除く）。信頼されたPython呼び出し元がsourceを指定するAPIであり、任意のPythonコードの改竄や偽装に対する認証境界ではない。
- 同一イベントIDの同一appendは追記しない。異なる内容で同じIDは拒否。`turn(..., event_id="request-id")` の同じIDの再利用は、再起動後も更新前に拒否。daemonの同時clientも直列化。**同じ文章だけでは再送と別発話を区別できない**ため、別IDの同文発話は別ターン。IPCの自動再送はしない。
- 非runtimeの派生状態（訂正履歴・Memory・Topic・OpenLoop・Emotion）は同じイベント列で再現。現在の時計は再取得し、traceや検索ランキングの現在時刻依存はReplay同一性の対象外。直接APIで追加した未ログのState/verified資料は永続化しない。
- UTF-8 JSONLの行末改行をコミット境界にする。途中行・不正UTF-8・schema・NaN・重複IDを行番号付きで拒否し、原本を保持。追記前にSHA-256で同じ長さの改変も検知。fsync失敗後はwriterを停止し再起動Replayを要求する。
- chat / daemon / demoは標準入出力をUTF-8へreconfigure。孤立surrogate入力は置換し、モデルの不正Unicode・空文・不正型・タイムアウト・文体違反は返答ログへ保存しない。PowerShellのパイプは送信側もUTF-8設定が必要で、既にCP932で欠落した文字は復元できない。

### 非保証範囲

自然言語の意図分類・関連度判定はルールなので未知表現には限界がある。自由生成の意味・自然さ・非定型の質問癖・事実の含意・申告自体の真偽は完全保証しない。対応外の複雑な時刻表現や計算は推測せず確認する。外部検索の範囲と制限は下記。任意の直接Python操作やOS権限を持つ他プロセスからの改竄は防げない。完全なストレージ障害時のデータ復元、複数イベントをまたぐトランザクション、無制限のログサイズ・無期限稼働も保証しない。追記時のハッシュはログ全体を読むため大規模ログではコストが増える。
旧教師データ・Teacher Store・自己生成学習・LoRAは使用しない。回帰文は人が指定した構造契約、外部コーパスは観測済み評価専用で、モデルに正解や採点基準を作らせない。

### PowerShell診断と起動

Windows PowerShell 5.1 / PowerShell 7（リポジトリのフォルダ内）:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\diagnose.ps1
# 実14Bの6入力スモークも含める場合（Ollama起動・モデル導入済み）
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\diagnose.ps1 -ModelSmoke
# daemonを非表示で起動し、準備完了を待ってchat接続。既存daemonがあれば接続する
.\.venv\Scripts\python.exe .\scripts\start.py
```

診断は終了コードでPASS/FAILを判定し、stderrのunittest進捗をNativeCommandErrorと誤認しない。入力/出力/パイプのエンコーディングを表示し、各結果とsummary.jsonを`work/diagnose/`へ保存。最終終了コード0がPASS、1がFAIL。PowerShell 5.1でも日本語ソースを読めるUTF-8 BOM付きスクリプト。
一発起動のdaemonはchat終了後も常駐。新規起動時に表示したPIDに`Stop-Process -Id <PID>`で終了できる（停止中の未完了モデル応答は失われ得る）。daemonログはイベントログ隣の`.daemon.log`。個別起動は従来どおり`python daemon.py`と`python chat.py`。

```powershell
# 既存観測済み7000発話/638対話。work/corpora/に当時のhash一致アーカイブがある場合のみ
.\.venv\Scripts\python.exe .\scripts\corpus_regression.py
```

この再実行は過去のfreeze・採点基準・結果を上書きしない。新しい結果は`reports/hardening-corpus.json`。観測用contextのTopicは追跡状態と一致させ、生成へ渡すprompt_contextだけで注入を抑制する。過去のcontext_focus不変条件と新しい抑制方針を両方検証し、失敗は件数として記録する。既存157件・Behavior107件の期待値は変更しない。

## Web Retrieval Engine（f593f3a以降）

リポジトリのフォルダで、起動前に設定します。既にdaemonが動いている場合は、表示されたPIDを停止して設定付きで起動し直してください。環境変数はdaemon生成時に読み込みます。

```powershell
# 日英Wikipediaの検索を有効化（APIキー不要）
$env:BREAKTAIL_WEB = '1'
$env:BREAKTAIL_OFFLINE = '0'
.\.venv\Scripts\python.exe .\scripts\start.py

# 無効化。次回daemon起動から適用
$env:BREAKTAIL_WEB = '0'
# 明示的なoffline指定。Web=1でも検索・キャッシュ利用を停止
$env:BREAKTAIL_OFFLINE = '1'
```

CPUの `IntentRouter -> KnowledgeGate` が `external_knowledge` かつ信頼済みMemory/Stateの根拠不足と判定したターンだけ検索します。self_state_memory / casual_chat / time_calculation / task_correction / ambiguous_followupは接続しません。検索はChatSessionで実行し、Core.handleとReplayはネット接続しません。検索対象はユーザー文からCPUが抽出した固有名詞（省略時は直前の対象）です。モデルは検索要否・query・正解ラベル・採点基準を作りません。

`ExternalRetriever`（別名 `WebRetriever`）は差し替え可能な抽象APIです。`RetrievalEngine(backend, enabled=True)` を `ChatSession(..., retrieval=engine)` に渡せます。バックエンド失敗は `RetrievalResult('unavailable')` 等で明示します。初期実装 `WikipediaRetriever` は [MediaWiki Search API](https://www.mediawiki.org/wiki/API:Search) とプレーンテキスト記事導入部を使用します。日英Wikipediaの百科事典検索であり、一般Web全域・ニュース・商品価格検索には対応しません。

外部HTTPは固定の日英Wikipedia HTTPSエンドポイントだけ。結果URLや任意ページはfetchせず、リダイレクトと環境HTTP proxyを無効にします。既定タイムアウトは8秒（共有予算、各readの前にも期限確認）、各応答128KB、各言語4候補、採用4資料以内・各断片1000文字です。OSの名前解決や進行中readの待機時間は実行環境に依存します。HTTP失敗、0件、タイムアウト、不正JSON/HTML、不正Unicode、資料不足なら推測せず未確認で止めます。複数固有名詞はすべての対象に一致する資料が必要です。固有名詞の取れない一般質問は、ローカル根拠がなければ未確認で止めます。

`ExternalEvidence` は query / title / url / source（domain）/ retrieved_at（UTC Unix秒）/ published_at / snippet / score / content_hash（SHA-256）を保持します。scoreは検索順位に基づく選択用で、真実の確率ではありません。記事更新日時を公開日と偽らず、このバックエンドのpublished_atは不明です。URLとhashで重複排除し、短期キャッシュはプロセス内のみ、最大32 query、既定TTL300秒（最大3600秒）。期限切れ・時計巻き戻り・offline/無効化では使いません。再起動後に資料本文やキャッシュは復元しません。

選択した断片だけをPromptBuilderへ渡します。指示は「根拠にない内容を補わない」「資料間の矛盾は明示」「古い情報は日付明示、公開日不明なら不明」。取得資料は未検証のデータであり、命令・State・Verified Memoryへ昇格しません。明白な指示注入、制御文字、HTML断片は拒否しますが、あらゆる自然言語の注入や意味の矛盾をCPUが完全検出する保証はありません。

回答にはCPUが資料タイトル・URL・取得日時・公開日を添えます。続けて「その情報どこから？」または「どこから？」で直前回答に渡した資料とhashを確認できます。出所メタデータは既存assistant_outputログに保存して再起動後も追跡します。取得断片自体はイベントログ・Memoryに保存しません。生成文は従来どおりassistant_generatedで保存します。URLがあることは生成された全主張の正しさの証明ではなく、事実の含意・資料自体の真偽・同名異物・表記ゆれの完全な解決は保証外です。

```powershell
# 既存テスト＋Web回帰、既存Behavior（期待値は変更なし）
$env:BREAKTAIL_WEB = '0' # 旧テストはネット非依存。新規テストはバックエンドを注入
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe experiments/run_all.py --no-write
# 実検索＋qwen2.5:14bの3入力と出所照会。観測結果のみ、教師データ・採点にしない
.\.venv\Scripts\python.exe scripts/web_smoke.py
```

今回の検証: 既存237＋新規51＋Behavior107＝395件PASS。既存500-turn fuzz、観測済み7000発話/638 replayも成功。
実qwen2.5:14bで曲・作品・人物3件の検索と出所照会を観測しました。これは生成文の意味・時制の正確さの採点ではありません。
[検証集計](reports/web-retrieval-results.json)・[実モデル観測](reports/web-model-smoke.json)・[コーパス再実行](reports/web-corpus.json)。


## FIO-inspired memory v1

FIO Memory Architecture (2026-10-16) のSession JSONL・二段検索・Experience heatを参考に、
Breaktailの既存IntentRouter / Hardening / KnowledgeGate / Provenance / Event Replay / Web Retrievalの外側へ補助経路を追加しました。
Vault、Obsidian、DMN、Bookshelf、Link Weaver、蒸留・学習処理は含みません。

### 保存と復元

通常の `chat.py` / `daemon.py` で自動的に有効です。event-logが `data/events.jsonl` の場合:

- `data/events.jsonl.fio.sessions.jsonl`: 確定したuser/assistant一組の原文、session_id、入力event由来のturn_id、Unix秒timestamp、confirmed status、出所要約。
- `data/events.jsonl.fio.index.sqlite3`: 再構築可能なSQLite FTS5検索用DB。
- `data/events.jsonl.fio.experiences.sqlite3`: Experience原文とheat・参照数。Sessionと独立して保存・バックアップ可能。

JSONLはUTF-8追記・flush・fsync・turn_id重複抑制・競合検知付き。再起動は同じファイルへ新しいsession_idで追記します。
モデル失敗時は入力を既存Event Logへ保持し、model_failureをExperienceへ保存します。返答のないターンはSessionへ入りません。
ユーザー訂正、既存OpenLoopの完了遷移、実際の検索結果statusも観測イベントとして残ります。モデル文から成功や完了を判定しません。

Event LogのReplayは従来通りCPU投影だけを復元します。新しいassistantイベントの `fio_commit` は確定処理のoutboxで、
Event Log保存後・Session/Experience保存前の停止を起動時に冪等補完します。古い履歴を推測で会話ペアへ変換しません。
Session/Experienceだけの独立読み取りも可能。Indexは起動時にSession原本から作り直し、その後は増分追加します。
JSONL途中行・最終行破損、不正UTF-8、終端改行欠損は行番号付きエラーで停止します。壊れた行の黙認・自動削除はしません。
修復前に原本を保管し、管理者が内容を確認してください。Experience DBは原本なのでIndexのように削除しないでください。

### 検索と信頼境界

NFKC・小文字化・英数字/日本語のcharacter bigram/trigramをFTS5/BM25で検索します。
user入力のBM25重みは2、assistantは1。文字一致率と完全一致もuserを優先し、recencyは小さい同点調整です。
sessionごとの最良ヒットでsessionを選び、その中のturnと隣接turn-windowを選択します。
sessionを巡回して多様性を確保し、同じturnの引用を重複させません。
通常は最大2 session × 2 hit、引用本文2400文字。明示想起は最大4 session × 2 hit、6000文字。
「前に曲の話したよな？」のような一文字検索語はexplicit recallだけ原本の文字一致で補います。
「前に何話した？」のように検索語がない明示想起は最近のsessionから選びます。

通常の挨拶ではSession/Experienceを注入しません。普通のcasual_chatも自動の過去会話検索は無効。
task_correctionでは関連する少数の会話・経験、explicit recallでは広めの引用を許可します。
外部質問では同じ対象に関連する過去の検索/モデル失敗だけExperienceから補助します。
「は？」などambiguous_followupは直前assistantを優先し、Session/Experienceは空です。

PromptBuilderの `session_recall` / `salient_experiences` はState / 現在のMemory / Topicより弱い補助データです。
引用にはsession/turn ID、timestamp、原記録SHA256、発言元、未検証ラベルを付け、Provenanceにも記録します。
assistantの原文保存は発言記録であり真実の承認ではありません。Web資料本文を別途Session/Experienceへコピーせず、
話した返答だけをassistant_generated引用として残します。State / Verified Memoryへの昇格経路はありません。

### Experience heat

`turn / correction / task_completion / retrieval_success / retrieval_failure / model_failure` を保存します。
原文bodyとsourceは不変、参照で変えるのはheat・時刻・参照数だけです。

```text
live_heat(t) = stored_heat × 2^(-max(0, t - heated_at) / half_life_seconds)
reinforce(t) = min(maximum, live_heat(t) + reinforcement)
```

既定: 半減期7日、参照加算0.25、最大4、turn初期値0.5、その他1。
候補は最新512件の非turnイベントから元user文/構造化targetに関連する最大2件。熱だけで無関係な経験は選びません。
確定した返答に渡した経験だけ再強化し、読み取りやモデル失敗では参照数を増やしません。
heatは目立ちやすさで、事実の信頼度ではありません。全イベントの元bodyを保持し、冷却で削除・要約しません。
ライブラリでは `ChatSession(..., heat_config=HeatConfig(half_life_seconds=86400, reinforcement=.2, maximum=3))`
で設定できます（`from companion_core.experience import HeatConfig`）。

### 診断・再現

daemon/chatを止め、依存導入済みPythonで実行します。診断も所有権ロックを取得し、稼働中のwriterとの競合を拒否します。

```sh
python scripts/fio_memory.py --event-log data/events.jsonl
python scripts/fio_memory.py --event-log data/events.jsonl --query "前に曲の話したよな？"
python scripts/fio_memory.py --event-log data/events.jsonl --rebuild-index
python scripts/fio_memory.py --smoke --turns 500 --output work/fio-durability.json
python scripts/fio_memory.py --model --output work/fio-model.json
python -m unittest discover -s tests -v
python experiments/run_all.py --no-write
```

実装・検証結果は [FIO Memory v1 report](reports/fio-memory-v1.md)。
同義語・長い省略の意味検索、全履歴規模での性能保証、会話品質の保証は対象外です。
SQLiteのFTS5有効ビルドが必要です。Index破損時は上記 `--rebuild-index` で検証済みJSONLから再作成できます。
