# Breaktail v2

**Companion Coreを脳幹に残し、Ollamaの `qwen2.5:14b` と会話するMVP。**
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

ログはUTF-8 JSONLで追記・flush・fsyncします。**同じログを複数プロセスで同時使用しないでください。**
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
元のMemory 2件（空検索・0件上限）、Emotion 4件（空入力・否定・引用・訂正時覚醒）を、既存の期待を変えず修正しました。
FakeModelAdapterによる18シナリオに加え、HTTP契約・失敗応答等を検証します。
Fakeの文面は配線テスト用の仮仕様であり、自然会話品質の正解・教師データではありません。
実モデルで雑談・未完了事項・訂正・再起動後の参照を確認しています。

外部人間データの過去サンプルはすべて**観測済み回帰データ**として再実行し、新しい未使用評価と呼びません。
元のfreeze・manifest・過去候補のREVISEは保持します。
Topicの分割・切替見逃し、有限ルールによる感情推定・完了解釈、曖昧な訂正対象の解決は残る制限です。
[既存実験](experiments/README.md) と [憲法](CONSTITUTION.md) も参照してください。
