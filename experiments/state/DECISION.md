# REVISE

10/12 cases passed (83.3%).

採用条件: 全ケース成功、実行エラー0件。critical は権限・訂正・曖昧性などの必須不変条件。
PASS はこの有限ケース集合での仮説支持であり、理論の普遍的正しさの証明ではない。

採用不可。失敗する振る舞いを修正し、同じケース集合で再実験すること。
本実験は既存本体を評価するだけで、本体の変更・新理論の統合は行わない。

## 失敗と理由

- `same-value-history`: 同値再提案でも履歴にactiveが二重に残らない
  - `active_history_count.name`: 実測 2; 期待 `eq` 1
- `core-year-statement`: 今年は2026: 対象キーが指定された明示年訂正を反映
  - `values.year`: 実測 '2023'; 期待 `eq` '2026'

結果の入力・本体・評価器の SHA-256 は results.json に保存。source_commit は実行時 HEAD。
