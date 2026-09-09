# Shared project documents

このフォルダは、宇宙開発Idleゲームの共有設計基準を保持する。

- `design.md`: ゲームとして何を成立させるか。ゲームループ、プレイヤー判断、コンテンツ設計、UX上の目的。
- `architecture.md`: そのゲームをどのDomain、State、Application境界、Persistence、Simulation構造で表現するか。
- `development-principles.md`: 変更要求をどの順序で評価し、全体整合性を維持して実装・監査するか。

## 判断の基準

開発中の現行コード、既存テスト、fixture、暫定Content、既存UIは、それ自体を正準仕様とはしない。

変更時は、最新の合意されたゲームデザインとアーキテクチャから変更後の全体像を定め、必要なら既存構造を破壊的に更新する。`development-principles.md` は、その判断を局所修正へ縮退させないための実装手順を定める。

テスト・CI・Gameplay Scenarioは、これらの設計を検証するための手段であり、設計や実装方針を逆向きに決定する根拠にはしない。

文書間に不整合が見つかった場合は、現行実装へ合わせて解釈するのではなく、ゲーム上の目的、Domain責務、変更理由を再確認し、共有文書側を含めて整合する形へ正面から改訂する。
