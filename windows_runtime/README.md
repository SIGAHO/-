# Breaktail 現行Windows会話ランタイム

Windowsで使われている `current/` のソースを、既存Companion Coreとは別フォルダーで管理します。
ローカルの現行インストールへも同じ機能修正を適用済みです。

## 実行

Python 3.12とローカルOllamaの `qwen2.5:14b` BASEを使用します。
このフォルダーには本番データ、重み、adapter、学習データ、ログ、Studio本体、ルートのSTART_ALLは含みません。

```powershell
# リポジトリのルートから、安全な独立データ領域でCLIを起動
python windows_runtime/current/breaktail_orchestrator.py --data-root ./evaluation_data --safe-mode chat
```

`--safe-mode` は長期記憶や教師登録等を抑止します。評価領域にはRaw・Trace・セッション状態と参照用レビュー待ちメタデータが残ります。学習は実行しません。
既存本番データをこのチェックアウトへコピーしないでください。

## テスト

```powershell
python -m unittest discover -s windows_runtime/current -p 'test_*.py'
$env:PYTHONPATH = (Resolve-Path windows_runtime/current).Path
python -m unittest discover -s windows_runtime/current/tests
```

現行280件とサブディレクトリ9件が成功しています。
既存Companion Coreの11件も、Windows用タイムゾーンデータ `tzdata` を作業専用領域へ追加して成功しました。
合成回帰テストと、本物のOllamaでの20往復は別々に実施しています。

## 文書

- [調査とプライバシー](docs/INVESTIGATION_20261102.md)
- [修正方針・残課題](docs/PLAN_20261102.md)
- [修正前後の検証結果](docs/VALIDATION_20261102.md)

公開用スナップショットはコードと小さい技術辞書だけです。個人パス、会話由来の長いテスト文、環境依存の旧版復旧スクリプトは除外・置換しています。
元の20往復の会話本文とTraceはローカル評価領域に保持し、公開していません。
検算と人物保持は対応する明示表現に限定されます。人格・口調・短さ・創作の意味には改善余地が残ります。
