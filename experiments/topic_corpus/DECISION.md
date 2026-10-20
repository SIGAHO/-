# REVISE

汎用Topic方式として採用不可。この評価で本体の辞書・係数・正解ラベルは変更していない。

人間由来のUSER発話 1000 件、128 対話。異なる本文は 916 件。
原データの6業務ドメインを代理指標として評価し、モデルが生成した教師文・教師ラベルは0件。訓練も0件。

- 遷移評価: 811/811 件。棄権 0 件。
- 同じ業務ドメインの 669 遷移中、637 件で別クラスタ。継続保持率 4.78%。
- 業務ドメイン変更 142 件中、139 件でクラスタ変更。
- 変更検出: precision 17.91% / recall 97.89% / F1 30.28%。
- 代理遷移の一致率 21.09%。常に継続する比較基準 82.49%。
- 元ラベル不明 61 発話。AIによるラベル補完なし。
- 復帰イベント 0 件。0件なら復帰性能は判定不能。
- 不変条件は各 1000 件中 one_active_fact_per_key=1000, no_assistant_fact_source=1000, memory_budget=1000, emotion_bounds=1000, context_focus=1000。
- Replay: 128/128 対話（時計Stateの復元は対象外）。

## 判断の限界

これは業務ドメイン遷移との整合性であり、雑談の意味的な話題境界についての人手正解率ではない。
同一ドメイン内に複数の話題があるため、これらの差分をすべて確定した意味理解の誤りと呼ばない。
ただし現在の21件の回帰PASSだけでは、この外部データ上の大きな分裂傾向を検出できていなかった。
不変条件の成功を意味理解の成功へ読み替えず、汎用性の採用判断はREVISEとする。

次に必要なのは、別の未使用分野に対する人間の話題境界注釈と、分野辞書に依存しない比較器の検証。
今回の評価済み1000発話を見て辞書・閾値を合わせず、教師データにも流用しない。

## 人手確認用の差分参照（原文は元データから照合）

- dialogue_4783AxcV / USER turn 2 / annotation turn 3: fp, 原ドメイン=attraction, cluster=1
- dialogue_4783AxcV / USER turn 6 / annotation turn 7: fp, 原ドメイン=weather, cluster=3
- dialogue_4783AxcV / USER turn 8 / annotation turn 9: fp, 原ドメイン=weather, cluster=4
- dialogue_0563MxBE / USER turn 2 / annotation turn 3: fp, 原ドメイン=restaurant, cluster=1
- dialogue_0563MxBE / USER turn 4 / annotation turn 5: fp, 原ドメイン=restaurant, cluster=2
- dialogue_4520PtgT / USER turn 2 / annotation turn 3: fp, 原ドメイン=hotel, cluster=1
- dialogue_4520PtgT / USER turn 4 / annotation turn 5: fp, 原ドメイン=hotel, cluster=2
- dialogue_4520PtgT / USER turn 6 / annotation turn 7: fp, 原ドメイン=hotel, cluster=3
- dialogue_4520PtgT / USER turn 8 / annotation turn 9: fp, 原ドメイン=hotel, cluster=4
- dialogue_4520PtgT / USER turn 10 / annotation turn 11: fp, 原ドメイン=hotel, cluster=5
