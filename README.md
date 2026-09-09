# 宇宙開発Idle Simulation / WebUI v0.5

`v0.5` は、2026-09-09時点の `develop` 実装をユーザー承認に基づいて正準化したゲーム性評価用スナップショットです。ゲーム性評価段階では旧仕様・旧Saveとの後方互換を要件とせず、妥当なゲームモデル・責務境界への破壊的変更を許容します。仮の価格、所要日数、生産量等をテスト契約として固定することは目的にしません。

## 正準文書

- `docs/design.md` — ゲームデザイン、中心ループ、プレイヤー判断、評価対象
- `docs/architecture.md` — Generic Core、Content、Application、Domain、Persistence、Validationの責務境界
- `DEVELOPMENT.md` — branch、CI、検証、GitHub運用

デザイン文書・アーキテクチャ文書は、0.5実装の説明だけでなく、次期 `develop` で実装することが合意された設計も含みます。文書で合意済みだが0.5コードへ未反映の項目を、実装済みとみなしてはなりません。

## v0.5 実装スナップショット

現在のSimulation Coreには、少なくとも以下の基盤があります。

- 地表・軌道を分離したSpatial Nodeと型付きEnvironment Facet
- Facilityの設置条件・運転条件・Capability
- 地点別Inventory、Reservation、Storage physical/service capacity
- 電力の優先配分・部分稼働
- Process単位の投入・産出とIndustry flow
- Construction Project、建設能力配分、調達・物流連携
- Cargo、Route、複数Leg Mission、arrival waiting
- Powered Ascent / Spaceflight / Landing / Atmospheric Entryによる輸送適合判定
- 保有Vehicleの位置・推進剤・Production・Transit・Turnaround・Maintenance状態
- Vehicle製造Commandと製造Resource / Capability / 期間
- Logistics LaneとDomain Resource Demand
- Research Point、Research Provider、Tier / Level、Theory / Prototype / Demonstration
- Resource SurveyとExtraction
- 自動時間進行、速度変更、一時停止
- Save / Load、Offline Progress、Application Command / Query、Web UI

## 0.5正準化と同時に確定した次期設計

次の変更は `docs/design.md` と `docs/architecture.md` に正準化されていますが、0.5の既存コードへ遡及して実装したものではありません。以後の通常開発は `develop` でこれらを実装します。

- FacilityごとのProcess投入物・産出物・稼働率・limiting factorをUIへ明示
- 建築物を原則2〜3種類の明示Resourceで建造
- 建造時のLocal Substitution / local fraction / substitute materialレイヤーを廃止
- 建造・Upgrade投入Resourceの一定割合からFacility維持需要を生成
- 維持不足をmaintenance fulfillmentとしてFacility能力へ反映
- 初期地球に低効率の採掘・基礎生産設備を追加
- Vehicle建造候補、必要資材、建造期間、blockerをUIへ表示
- Vehicleを割り当てる有限Scientific Exploration CampaignからResearch Pointを獲得
- Scientific ExplorationとResource Surveyを別状態機械として維持

## 中核原則

- Generic CoreへEarth、Moon、特定Vehicle用途等の固有名分岐を持ち込まない。
- Facility、Route、Research等の可否はEnvironment、Capability、Resource、Vehicle性能、Transport Operation等の一般条件から決める。
- 輸送中Cargoは目的地Storageを事前予約せず、実到着時に入庫判定する。
- 打上げヴィークル、宇宙船、着陸船等の名称は表示分類であり、輸送可否の用途allowlistにはしない。
- 定常物流は品目別の反復設定より拠点間輸送能力、方式、優先度を主要判断とする。
- Idle自動化は反復処理を担当し、研究・産業・物流・Vehicle配分等の戦略判断を暗黙に代行しない。
- UIはSimulation Coreを直接操作せず、Application Command / Query境界を使用する。
- Saveは可変Stateを保存し、静的Definitionと派生状態は現在Contentから再構築する。

## 開発branch

- `main`: ユーザー承認済みの正準branch
- `develop`: 通常開発・統合・プレイテスト用の常設branch
- `temp`: 独立検証・大規模変更用。利用開始時に最新`develop`へ初期化し、独自の未統合状態を残さない

`develop` から `main` への統合とゲーム本体version変更は、ユーザーの明示的承認後にのみ行います。
