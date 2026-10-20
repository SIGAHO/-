# 過分割修正と未使用の日本語対話での検証

## 変更と採用範囲

新しい分野語・同義語・特定の発話パターンは追加していない。既存の互換辞書は保持するが、
辞書を無効化した比較も行う。0.18の類似度しきい値、0.82の減衰も変更しない。
Janome 0.5.0 の形態素・品詞を使い、名詞の対象と述語、格助詞・係助詞、代名詞、疑問、
進行中の叙述などの文法的証拠を区別する。単なる語彙不一致で分裂させず、
新対象の明示か独立した連続発話の支持を必要とする。保留中の語彙で既存アンカーを汚染しない。
係数探索・生成モデル・埋め込みモデルの学習は行っていない。

既存の21件のtopic実験と既存テストの期待は維持。追加の構造テストは任意識別子の置換、
省略応答、保留の取り消し、Replayなどの不変条件であり、会話コーパスや教師データではない。
新方式がデフォルトで、`TopicTracker(policy="legacy")` で旧判定を比較できる。

## 先に固定した採用条件と全試行

各段階で PROTOCOL.md・manifest.json・freeze.json を保存し、ソースを固定してから評価した。
採用条件は、JMultiWOZの同一分野内分裂率減少、厳密隣接境界F1改善、変更再現率50%以上、
辞書無効でも分裂改善、別コーパスでも分裂改善、不変条件とReplay維持。期待値は変更していない。

- 第1候補 `../topic_holdout/`：未使用test対話2000発話。分裂は改善したが境界検出が不足しREVISE。
- 第2候補 `../topic_holdout_v2/`：さらに別のdev対話2000発話。F1は改善したが再現率50%未達でREVISE。
- 最終候補（本ディレクトリ）：さらに別のtrain対話2000発話。全条件PASS。

train/dev/testは上流データセットの分割名にすぎず、ここではすべて評価専用。
対話IDの重複は前回1000件も含めて禁止。各候補の観測後、その標本で再調整・再評価していない。
第2候補の preflight_freeze.json は構造テスト中の暫定記録で、外部対話の採点前に破棄した記録。
実採点は freeze.json の候補で一度だけ行った。
第1候補は v1_snapshot/、第2候補は snapshot/ に当時のtopic.pyとtopic_evidence.pyを保存した。
古い候補の再現時は別チェックアウトでこれら2ファイルを復元する必要がある。

最終候補の実測（小数点以下は丸め）：

- JMultiWOZ 1000発話：同一分野内分裂96.6%→38.6%、境界F1 0.2724→0.3739。
- BSD日本語原作1000発話：同一場面内分裂97.4%→30.9%。
- 互換辞書無効でも同じ改善。不変条件・Replayは全対象で成功。

残る誤分裂・境界見逃しは results.json の混同行列と predictions.jsonl に残す。
元のドメイン注釈との不一致を隠したり、生成モデルで正解を書き換えたりしない。

## 出所・ライセンス・限界

JMultiWOZは [公式リポジトリ](https://github.com/nu-dialogue/jmultiwoz) の
人間によるWizard-of-Oz会話と原注釈を使用。固定版・アーカイブSHA-256はmanifestに記録。
ライセンスはCC BY-SA 4.0。BSDは [公式リポジトリ](https://github.com/tsuruoka-lab/BSD) の
人間が場面を設定して執筆した会話のうち `original_language == "ja"` のみ。
翻訳文は除外。BSDの場面ラベルtagをそのまま使う。
BSDは ©2020 The University of Tokyo、Matīss Rikters、Ryokan Ri、Tong Li、Toshiaki Nakazawa (2019),
[Designing the Business Conversation Corpus](https://aclanthology.org/D19-5204/)。
CC BY-NC-SA 4.0の非商用研究評価として使用し、
原文を製品・学習へ取り込まない。公開物はID・ハッシュ・原注釈・予測番号で、会話本文やプロフィールは含まない。
BSD由来のメタデータは同ライセンス、JMultiWOZ由来のメタデータは同データセットのライセンスに従う。
[Janome](https://janome.mocobeta.dev/ja/) はApache 2.0、内包辞書のライセンスにも従う。

分野・場面は人間による話題境界注釈ではない。同じ場面にも正当な小話題がありうるため、
BSDで分裂が減ったことだけで意味的な正しさは主張しない。最終候補も誤りは残り、
汎用的な意味理解やあらゆる会話での精度を証明したわけではない。
次は独立した人間による話題境界注釈で、残る誤分裂と真の切替見逃しを分けて測る必要がある。

## 再現

```bash
python -m pip install -r experiments/requirements.txt
python experiments/topic_holdout_v3/run.py --archive /path/to/JMultiWOZ_1.0.zip --bsd /path/to/BSD/train.json
python experiments/run_all.py
python -m unittest discover -s tests -v
```

入力はmanifest記載の固定版が必要。ソースや標本がfreezeと異なる場合は拒否する。
原注釈を予測器へ渡さず、原文だけを入力することはテストで確認する。
既存107件中memoryの2件、emotionの4件は従来からの未達のまま。
全系統ランナーの終了コード1を成功へ変更しない。
