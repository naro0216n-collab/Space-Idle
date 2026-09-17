# Shared project documents

このフォルダは、宇宙開発Idleゲームの共有設計基準を保持する。

- `design.md`: ゲームとして何を成立させるか。ゲームループ、プレイヤー判断、コンテンツ設計、UX上の目的。
- `architecture.md`: そのゲームをどのDomain、State、Application境界、Persistence、Simulation構造で表現するか。
- `development-principles.md`: 変更要求をどの順序で評価し、全体整合性を維持して実装・監査するか。
- `implementation-map.md`: 現行実装を正準Domainへ移行・監査するときだけ使う非正準の対応表。

## 読み方

作業開始時は本書と `development-principles.md` を読み、変更対象に対応する `design.md` と `architecture.md` の正準節を読む。`implementation-map.md` は正準仕様を理解した後、現行コード上の責務所在を探す場合だけ参照する。

全文を先頭から探索するより、次の索引から変更対象の正準位置を特定する。

## 正準仕様インデックス

| 関心領域 | `design.md` | `architecture.md` |
|---|---|---|
| 中心ループ・進行・初期範囲 | §1–4 | §1–3 |
| Resource / Inventory / Storage / Priority / Funds / External Resource Market | §5 | §7, §10.9 |
| Facility / Construction / Maintenance / Decommission | §6 | §6, §9 |
| Industry / Extraction / Resource Potential | §7 | §8 |
| Spatial / Surface Location / Environment | §8 | §5 |
| Movement / Transport / Logistics / Cargo / Fleet Retirement | §9–10 | §10 |
| Scientific Exploration / Research / Knowledge | §11–13 | §11–12 |
| Resource Survey | §14 | §12.2 |
| Operational Node Founding / Location development / external-dependency analytics | §8.1, §15 | §5.4, §8.4, §9.5 |
| Automation / canonical day / Offline | §16, §19 | §3.4, §14 |
| Application / UI | §18 | §3.3, §13, §16 |
| Save / Load / Validation / Test | §19 | §14–15 |
| World / Scenario / Initial Content / gameplay evaluation | §20, §22 | §3.2, §4, §14–15 |

一つの概念が複数節から参照される場合も、詳細規則を重複定義しない。ゲーム上の意味は `design.md`、State ownership・処理順・契約は `architecture.md` の対応節を正本とする。

## 判断の基準

開発中の現行コード、既存テスト、fixture、暫定Content、既存UIは、それ自体を正準仕様とはしない。

変更時は、最新の合意されたゲームデザインとアーキテクチャから変更後の全体像を定め、必要なら既存構造を破壊的に更新する。`development-principles.md` は、その判断を局所修正へ縮退させないための実装手順を定める。

テスト・CI・Gameplay Scenarioは、これらの設計を検証するための手段であり、設計や実装方針を逆向きに決定する根拠にはしない。

文書間に不整合が見つかった場合は、現行実装へ合わせて解釈するのではなく、ゲーム上の目的、Domain責務、変更理由を再確認し、共有文書側を含めて整合する形へ正面から改訂する。
