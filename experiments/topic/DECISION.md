# REVISE

8/11 cases passed (72.7%).

採用条件: 全ケース成功、実行エラー0件。critical は権限・訂正・曖昧性などの必須不変条件。
PASS はこの有限ケース集合での仮説支持であり、理論の普遍的正しさの証明ではない。

採用不可。失敗する振る舞いを修正し、同じケース集合で再実験すること。
本実験は既存本体を評価するだけで、本体の変更・新理論の統合は行わない。

## 失敗と理由

- `current-switch`: 長く話したCNCから明示的に時計へ移った直後はcurrentも時計
  - `steps.3.current`: 実測 0; 期待 `eq` 1
- `semantic-alias`: 字面が異なる同義の工作機械話題を継続
  - `steps.1.selected`: 実測 1; 期待 `eq` 0
- `no-overmerge`: 共通の作るという語だけで別製作物を統合しない
  - `steps.1.count`: 実測 1; 期待 `eq` 2

結果の入力・本体・評価器の SHA-256 は results.json に保存。source_commit は実行時 HEAD。
