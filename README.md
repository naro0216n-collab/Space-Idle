# 宇宙開発Idle Simulation / WebUI v0.6

`v0.6` は、2026-09-12時点の Fleet / Transport Capacity 再設計を含むユーザー承認済み実装スナップショットです。開発初期段階では旧仕様・旧Saveとの後方互換を要件とせず、正準仕様に沿ったDomain境界とState所有を優先します。暫定的な価格、所要日数、Facility数、Vehicle数、攻略順をCore契約として固定しません。

## 正準文書

- `docs/README.md` — 正準文書の入口と読み順
- `docs/development-principles.md` — 開発原則
- `docs/design.md` — ゲームデザイン、中心ループ、プレイヤー判断
- `docs/architecture.md` — Domain、Application、Persistence、Simulation、UIの責務境界
- `DEVELOPMENT.md` — branch、CI、検証、GitHub運用

READMEは実装状況の要約です。仕様判断では上記`docs`を優先します。

## v0.6 実装スナップショット

現在のSimulation Coreには、少なくとも以下の基盤があります。

- 地表・軌道を分離したSpatial Nodeと型付きEnvironment Facet
- Facilityの設置条件・運転条件・Capability
- 地点別Inventory、Reservation、Storage physical/service capacity
- 電力の優先配分・部分稼働
- Process単位の投入・産出とIndustry flow
- Construction Project、建設能力配分、調達・物流連携
- Resource Survey、Extraction、Research Point、Research Provider、Tier / Level
- Vehicle DefinitionのMass / Propulsion / Mobility / Endurance / Interface / Maintenance / Production性能
- Vehicle Production完了による地点別Fleet Pool unit増加
- FleetのTransport / Scientific Exploration / relocation / releasing / その他予約間の排他的配分
- UNITS / CAPACITY control modeを持つTransport Allocationとpriority / routing policy
- Allocationから決定論的に導出するTransport Service Plan、cycle、latency、resource / infrastructure requirements
- Fleet数とService Planから導出するTarget / Nominal / Available / Used / Spare Transport Capacity
- 往復cycleの方向別capacity、空荷return、resource / servicing制約
- Logistics Laneによる共有Transport Capacityの需要配分
- 複数Transport ServiceをhandoffするEnd-to-End pathとCargo Flow
- Cargo Flowの輸送遅延、到着時Storage admission、arrival waiting
- Fleet relocation / releasingの有限状態遷移
- Vehicle性能要件に基づく有限Scientific Exploration CampaignとFleet reservation
- Fleetを持たず同じCapacity interfaceへ供給するExternal Transport Service
- Save / Load、Offline Progress、Application Command / Query、Web UI

通常物流は個体Vehicleのdispatch / Mission反復を正本にせず、Fleet Allocationから得られる定常Transport CapacityとCargo Flowで処理します。個体Vehicle ID、`default_disposition`、通常CargoごとのTransport Missionを前提とする旧経路は使用しません。

## Transport / Fleetの主要契約

- `FleetPool.total_units`を資産数量の正本とし、free unitsは排他的拘束から導出する。
- Transport Allocationのtargetと実際に拘束できたactive unitsを分離し、Fleet不足でもtargetを保持する。
- Allocation priorityはFleet配分、Lane priorityは得られたcapacityの物流需要配分にだけ使う。
- CAPACITY modeの必要Fleet数はNominal capacityから求め、一時的な燃料・整備不足で自動増員しない。
- Transport Service PlanとNominal / Available / Spare capacityは保存せず、Definitionと可変Stateから再導出する。
- operational resource需要はAllocation量ではなく実際のService utilizationから生じる。
- Transport Available Capacityはtick開始時状態で確定し、同tick後段に到着した燃料等を遡及利用しない。
- 輸送開始時に目的地Storageを予約せず、到着時に収容できないCargoはarrival waitingとして保持する。
- Offline Progressも通常のSimulation advance経路を使用する。

## UI / Application

Fleet / Logistics UIはApplication Queryから、Fleet総数・free・用途別拘束、Allocation target / active / unfilled、Service feasibility、Target / Nominal / Available / Used / Spare capacity、resource / infrastructure requirements、blocker / limiting factor、Lane requested / actual flow、Cargo Flow、relocation / releasingを取得します。

UIはRoute適合、必要Fleet数、capacity、燃料不足などのDomainルールを再計算しません。操作不能状態でも必要条件とblockerを表示し、定期同期時は編集中の入力を不用意に上書きしません。

## 中核原則

- Generic CoreへEarth、Moon、特定Vehicle用途等の固有名分岐を持ち込まない。
- Facility、Route、Research、Transport、Explorationの可否はEnvironment、Capability、Resource、Vehicle性能、Transport Operation等の一般条件から決める。
- Idle自動化は反復処理を担当し、研究・産業・物流・Fleet配分等の戦略判断を暗黙に代行しない。
- UIはSimulation Coreを直接操作せず、Application Command / Query境界を使用する。
- Saveは可変Stateを保存し、静的Definitionと派生状態は現在Contentから再構築する。

## 開発branch

- `main`: ユーザー承認済みの正準branch
- `develop`: 通常開発・統合・プレイテスト用の共有正本
- `temp`: ユーザー指定時、またはworkflow / publish経路そのものの隔離検証時だけ使用
- `publish`: Publish Gateway専用transport control branch

`develop` から `main` への統合とゲーム本体version変更は、ユーザーの明示的承認後にのみ行います。
