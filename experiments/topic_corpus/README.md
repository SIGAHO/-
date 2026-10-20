# 人間由来の日本語1000発話でTopicを外部評価

この実験は既存のモデル作成AIによる回帰ケースとは別に、外部の人間由来データで実行する。
モデルの訓練も、教師データや正解ラベルの生成も行わない。本体の変更はない。

## 出所・利用条件

- データ: [JMultiWOZ](https://github.com/nu-dialogue/jmultiwoz)、バージョン1.0。
- 著者: Atsumoto Ohashi, Ryu Hirai, Shinya Iizuka, Ryuichiro Higashinaka。
- 論文: [JMultiWOZ: A Large-Scale Japanese Multi-Domain Task-Oriented Dialogue Dataset](https://arxiv.org/abs/2403.17319)、2024、3.4・3.5節。
- 元データは2名の人間によるWizard-of-Oz対話。人間が操作した業務状態と追加の人手注釈を収録する。
- [公開仕様](https://github.com/nu-dialogue/jmultiwoz/blob/a78dd334b907e12318b76bb23d0a9ed1498b8d15/dataset/README.md)、[ライセンス](https://github.com/nu-dialogue/jmultiwoz/blob/a78dd334b907e12318b76bb23d0a9ed1498b8d15/LICENSE): CC BY-SA 4.0。
- 元アーカイブや本文はこのリポジトリへ再配布しない。原注釈を含む manifest.json / predictions.jsonl は上記データを抽出・整列した派生データとして CC BY-SA 4.0。変更内容は抽出・本文ハッシュ化・予測の付加。

## 再現

元リポジトリのコミット a78dd334b907e12318b76bb23d0a9ed1498b8d15 にある dataset/JMultiWOZ_1.0.zip を取得する。
アーカイブSHA-256を実行時に照合する。上流スクリプトやモデルコードは実行せず、zip内のJSONだけ読む。

```bash
python experiments/topic_corpus/run.py --archive PATH/TO/JMultiWOZ_1.0.zip --prepare
python experiments/topic_corpus/run.py --archive PATH/TO/JMultiWOZ_1.0.zip
python experiments/run_all.py --no-write
python -m unittest discover -s tests -v
```

--prepare はモデルを動かす前に本文ハッシュ・元ラベル・IDを固定する。
以降の評価ではこのmanifestと一致しないデータを拒否する。
終了コード1は一般化の採用許可を出さないREVISE、入力不整合や実行失敗も非ゼロで終了する。
既存6系統のrun_allとは別の外部評価で、既存のケースや期待条件を更新しない。

results.json に集計とソースハッシュ、predictions.jsonl に全発話のID・原注釈・予測・不変条件、
replay.json に対話単位の再生検証結果を保存する。原文は元データからIDで照合できる。
話者属性や個人プロフィールは読み込まず、USER発話以外はモデルへ渡さない。

旅行関連6ドメインのタスク会話であり、日常雑談全般や任意の言い換えの正解集合ではない。
特にactive_domainは、自然な話題境界の代わりとして使う代理指標である。
この1000件を後から正解へ合わせて修正・学習しない。次の評価は別の未使用データで行う。
