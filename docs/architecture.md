# 宇宙開発Idleゲーム アーキテクチャ設計 v0.4.0

## 1. 文書の目的

本書は「宇宙開発Idleゲーム デザイン案」とSimulation Core実装の間に置くアーキテクチャ上の共有基準を定義する。

対象は個別の仮バランス数値ではなく、状態所有、Generic CoreとContentの分離、Spatial context・Operational Node・Surface Location、Environment、Facility、Capability / Service Capacity、Resource Claim / Resource Demand、建設・維持・物流・Vehicle・Research / Knowledge、Exploration・Surveyの関係、Application境界、Save/Load・Offline Progress、検証・拡張原則である。

現行の正準化対象実装はゲーム本体 `0.5` とする。ただしゲーム性評価段階では実装より本書とデザイン上の合意を優先する。本書で合意済みだが0.5時点で未実装の項目は次期developで実装する対象であり、旧API・旧データ・旧Saveとの後方互換を理由に不適切な構造を温存しない。

---

## 2. 全体構成

通常Runtimeの呼出経路は次とする。

```text
Web / PWA UI
    ↓
HTTP / WebSocket Adapter
    ↓
Application Layer
  Commands / Queries / DTOs
    ↓
Simulation Orchestrator
    ↓
Domain Services
  Spatial / Operational Node / Facility
  Inventory / Allocation / Power / Storage
  Industry / Construction / Maintenance
  Transport / Logistics / Vehicle
  Research / Knowledge / Exploration / Survey
```

Content、Persistence、Validationはこの縦列の下位Layerではなく、別の境界責務として接続する。

```text
Content Definitions ──→ Composition ──→ Domain Definitions / initial State
Persistence        ←──→ Application-owned Game State
Validation          ──→ Definitions / State / Domain invariants
```

UIやHTTP層はDomain Serviceへ直接アクセスしない。ApplicationはDomain契約を利用し、Simulation Orchestratorが時間進行上のphaseを統括する。Generic CoreはContent固有Definition、Persistence方式、UI、Earth、Moon、Mars、LLM等へ依存しない。ContentはGeneric Coreが定義したschemaへ具体値を供給し、Persistenceは可変Stateを保存・復元する。Runtime call flowとmodule dependencyを同じ上下図で表現しない。

---

## 3. 層の責務

### 3.1 Generic Core

世界で共通に成立する規則を担当する。

- Celestial Body / Surface Cell / non-surface Spatial Node / Operational Node / Surface Location
- Environment State / SiteRequirements
- Facility Definition / State / placement scope
- Capability / Service Capacity / allocation
- Facilityの資材維持需要と保守充足率
- Inventory / Reservation / Resource Claim / Storage
- Power配分
- Process / Industry
- Resource Potential / Extraction Opportunity / Extraction response
- Construction / Surface Development Project / Location Founding Deployment
- Transport Operation、Route、Transport Allocation、Transport Capacity、Cargo Flow、特殊Transport Mission
- Vehicle Definition / Fleet State / Production / Maintenance / Relocation
- Resource Demand / Logistics sourcing / Lane
- Research Point、Technology State、Research Project状態機械
- Operational Experience等のKnowledge State
- Scientific Exploration Campaign
- Resource Survey / Knowledge
- FundsとExternal Service利用Policyの共通契約
- 時間進行phase

Generic Coreへ `if location == MoonSouthPole`、`if vehicle_type == lunar_lander`、用途allowlist等を持ち込まない。必要条件はEnvironment Facet、Capability、Service Capacity、Operation、Vehicle性能、Resource等で表現する。

### 3.2 Content Layer

具体的な遊びを定義する。

- Celestial Body / Surface Cell topology / non-surface Spatial Node
- Static geology / Resource Potential / 初期Environment
- Resource Definition / analytics用Resource Group
- Facility Definition
- Process Definition
- Construction Recipe / maintenance rate
- Resource Potential / Extraction Definition
- Research Definition / Research Provider / Experience category
- Scientific Exploration Definition
- Survey Target / Survey Provider Definition / initial Surface Cell Knowledge
- Transport Operation / Route derivation rule / static non-surface connection / Vehicle
- External Transport / Procurement Service DefinitionとPolicy既定値
- Founding Package / initial Operational Node / initial Facility / Vehicle / Funds / Inventory
- 表示名

外部組織、Contract、Event等はContent / Application側の拡張として追加できるが、Research Point中心の成長ループや通常SimulationのGeneric Core必須Domainにはしない。

Content固有名は説明に使ってよいが、Generic Core内の分岐条件にはしない。

### 3.3 Application Layer

外部クライアントから見た正式な操作面とする。

- Commandをプレイヤー意図として受理する
- Domain呼び出しへ変換する
- Domain例外を安定したApplication Errorへ変換する
- QueryをJSON化可能なimmutable DTOへ変換する
- blocker、limiting factor、候補、必要条件、不足を返す

UIがCoreの可否判定や計算式を再実装しない。

### 3.4 Simulation Orchestrator

Simulation OrchestratorはDomainを固定順に逐次呼び出して競合を解決する場所ではなく、1tickの共通phase契約を統括する。各Domainが別Domainの登録順や偶然の呼出順へ依存しないようにする。

概念phase：

```text
1. Boundary settlement
   前tickまでに到着・完了時刻へ達したCargo、Fleet relocation、Project等を確定

2. Physical snapshot
   on-hand Inventory、既存Reservation、Funds、Environment、Facility / Fleet状態、
   Installed / Active Capability、Nominal Service Capacity等の配分前の物理状態を固定

3. Intent generation
   各DomainがResource Claim、Resource Demand、Service Capacity Request、
   Project work、Research / Survey / Exploration intent等を生成

4. Planning
   Resource Demandをsourcing / route Policyへ接続し、利用可能source、pathを選択する。
   発送候補はsource側Resource ClaimとLane / Transport Capacity requestへ解決する。
   Service supplyがResource、Funds、Fleet、Power、Maintenance、上流Service等を必要とする場合は、
   provider dependencyとして明示する

5. Allocation
   現地実行用Claimと物流発送用Claimを同じsource Inventory上で競合させる。
   Resource、Funds、Fleet、Service / Transport等の依存関係を一つの決定論的allocation graphとして解決し、
   上流Allocationでenableされた範囲からAvailable Service Capacityを確定した後、consumerへAllocated / Spareを求める

6. Domain execution
   Production、Extraction、Maintenance、Construction、Research、
   Exploration、Survey等を割当結果だけで進行

7. Logistics / movement progression
   割当済みTransport CapacityでCargo Flowをdispatchし、
   進行中Cargo / Fleet movementを進める

8. State transition / derived refresh
   Technology Unlock、Project completion、Founding等の状態遷移を確定し、
   派生Query状態を再導出してtickを進める
```

Boundary settlement後のPhysical snapshotを当tick配分の物理的な正本とする。前tickまでに到着時刻へ達したCargoはBoundary settlementで入庫判定された後にsnapshotへ反映する。snapshotで固定するのは配分前状態であり、最終Available Service Capacityではない。AvailableはPlanningで明示されたprovider dependencyと当tickAllocationの結果から確定する。Planningで選ばれた発送元Resourceもsource側Resource ClaimとしてAllocationへ参加させ、同じInventoryを現地実行と輸送が二重消費しない。これにより「どのDomainを先に呼んだか」で資源や能力の利用結果が変化することを防ぐ。

当tickのexecutionやmovementで新たに生産・到着したResource、完了によって新たに発生したCapacityはallocation graphのrootへ戻さず、次tickのBoundary settlement後snapshotまで利用しない。同tickallocation dependency graphに循環があるContent / DefinitionはConfiguration Validationでfail-closedとする。Domain固有の呼出順、自己供給、反復収束等の例外で循環を隠さず、循環自体をゲームルールとして必要とする場合は共通allocation契約を改訂する。

同priorityの連続量は比例配分を基本とし、Project成立等で最小成立量が必要な要求だけ明示的なatomic / minimum contractを持てる。phase間の例外的shortcutをDomainごとに追加せず、必要なら共通phase契約そのものを改訂する。

---

## 4. DefinitionとStateの分離

静的Definitionと可変Stateを分離する。

例：

```text
FacilityDef
  id
  display_name
  placement_scope: OPERATIONAL_NODE | SURFACE_CELL
  installation_environment
  operating_environment
  capability_supplies
  service_capacity_supplies

FacilityState
  entity_id
  definition_id
  operational_node_id
  site_cell_id?
  level
  paused
  allocation_priorities
```

同様にVehicle、Transport Allocation、Research、Scientific Exploration、Survey、Construction Recipe等でもDefinitionと可変Stateを分ける。

Vehicle Definitionは性能と製造・整備要件を持つ。通常運用するVehicleは同一Definition・所在Operational NodeごとのFleet Stateとして数量管理し、輸送、Scientific Exploration、再配置、回収中等の排他的配分をFleet Domainが所有する。

Technology UnlockはResearch DefinitionやFacility Stateへ複製せず、一つのTechnology Stateをauthoritative stateとする。Operational ExperienceもResearch Project個別の経過時間として重複保持せず、experience categoryごとのKnowledge Stateを正本とする。

Transport Service Plan、Transport Capacity、ロケーション産業自立・外部依存分析等は、保存済みStateとDefinitionから導出する派生状態とし、Save上の独立した正本にしない。

静的DefinitionはSaveへ複製しない。

---

## 5. Spatial / Operational Node / Environment / SiteRequirements

### 5.1 Celestial Body / Surface Cell / Spatial Node / Operational Node

物理的位置を表すSpatial modelと、経済・産業Stateを所有するOperational Nodeを分離する。

地表を `SurfaceCell` graphとして表現する。UIはヘックス主体で表示してよいが、Coreは完全六角格子、同一Cell面積、常時6隣接を仮定しない。Celestial BodyごとにCell数を変えてよい。

```text
CelestialBody
  id
  ...

SurfaceCellDef
  id
  body_id
  area
  geometry / centroid
  neighbor_ids
  terrain
  static_geology
  resource_potential_by_resource

SurfaceCellState / overlays
  dynamic_environment
```

Surface CellはInventory Nodeではなく、Facility一般の配置スロットでもない。資源、地形、可変Environment、Survey Knowledge、Surface Location開発領域の物理単位とする。

軌道・Lagrange領域・深宇宙上の運用位置等は `NonSurfaceSpatialNodeDef` として物理contextを表現できる。Spatial NodeだけではInventoryやFacilityを所有しない。

`OperationalNodeState` はInventory、Storage、Facility、Fleet、Power、Service Capacity、物流接続等の一般的な運用Stateの所有先とする。Operational Nodeは次のいずれかのSpatial contextへ結び付く。

- Surface Location
- non-surface Spatial Node

Surface LocationはOperational Nodeの一種として運用Stateを持つと同時に、追加でSurface Cell領域を所有する。

```text
OperationalNodeState
  id
  spatial_context
  ...

SurfaceLocationState
  operational_node_id
  body_id
  core_cell_id
  developed_cell_ids
  ...
```

`developed_cell_ids` を開発所属のauthoritative stateとし、Surface Cell側の「所属Location」はこの集合から導出する。二重正本を持たない。集合は同一天体上で連結することを基本とし、同一Cellを複数Locationへ同時所属させない。政治的主権と産業開発所属は同一概念とはしない。

Surface LocationのCell数はOperational Node数を増やさない。Inventory、Fleet、通常Facility、Laneの主要所有単位はOperational Nodeのままとする。

すべてのSpatial NodeをOperational Nodeへ昇格させない。未開発Surface Cellや単なる軌道位置はFounding / Mission等の物理targetにはなれても、通常Inventory / Logistics Nodeにはならない。

### 5.2 Environment

Surface Cellは静的地質・地形と可変Environmentを分離する。Static geology / Resource Potentialを通常の採掘で消費・減少させない。Dynamic Environmentは将来のテラフォーミング、局所環境改変、自然変化等によって更新可能とする。

Environment評価は必要に応じてCelestial Bodyのglobal state、Operational NodeのSpatial context、Surface Cell local stateを合成する。Location名やCell IDによる特殊分岐を作らない。

通常のOperational Node-scope Facilityは所属NodeのSpatial contextとInfrastructureが提供する運用環境を参照する。位置依存Facilityは所属Surface Location内の配置Surface Cellの現在Environmentを参照する。

### 5.3 SiteRequirements / Capability / Service Capacity

Facility設置・運転、Research Prototype / Demonstration、Route端点、Location設立・拡張等の可否は共通SiteRequirements / Environment Requirementを利用する。

`Capability` はcategoricalな資格・機能を表す。少なくともRequirement側で次を区別できる。

- Installed / Present Capability：物理設備・interface等が存在する。
- Active Capability：停止・故障・環境不適合等により無効化されておらず、現在利用可能な機能である。

量として競合するものを `Available Capability` と呼ばない。電力、建設work、Cargo Handling、Survey rate、Research execution等の有限flowは `Service Capacity` として別契約にする。

`ServiceCapacity` はservice type、Nominal、Available、Allocated、Spareを持てる。NominalはPhysical snapshotに固定する配分前supplyである。Power、Maintenance、Resource、Funds、Fleet、Environment、上流Infrastructure / Service等への依存はPlanningでprovider dependencyとして公開し、共通allocation graphで上流Allocationを解いた結果からAvailableを確定する。複数Domainが同じService Capacityを利用する場合はその後のAllocationを通し、各Domainが同じAvailable値を独立に全量使用しない。

### 5.4 Location development / Surface Infrastructure

Surface Locationは隣接Surface CellをDevelopment Projectで取り込む。Cell数に固定上限を設けず、Survey、Resource、Construction Service Capacity、時間、地形・Environment、Surface Infrastructure等を要求する。

Location内部で個別ResourceをCellごとにroutingしない。ただし共通Inventoryによる内部移動を無償・無限とも扱わない。開発領域の規模・広がり・遠隔Cell利用・Gateway接続から集約的なSurface Infrastructure / Local Distribution service demandを導出し、対応するService Capacityによって遠隔Resource Opportunity、Gateway荷役、Location内利用能力等を縮退させられる構造とする。

Surface Infrastructureを一つの万能fulfillment係数へ固定しない。Local haul / distribution、cargo handling、access等が別の意思決定・bottleneckになる場合は独立service typeとしてContent / Definitionで表現し、互いのCapacityを暗黙共有しない。

近接地域への別Location設立はCoreで禁止しない。新Locationは独立Operational NodeとしてFounding、Inventory、Storage、Power、Construction、Gateway / access、拠点間物流等の固定費を要求する。一つのLocationを拡大する場合の内部Infrastructure負荷と、複数Locationへ分割する場合の設立・Node間物流コストをtrade-offにする。同じSurface Cell、Resource Opportunity、Service CapacityをLocation分割で複製しない。

この集約能力はSurface CellをLogistics Lane Nodeへ昇格させるためのものではない。個々のCargo pathではなくLocation内部の運用負荷を表現する。

## 6. Facility / Maintenanceモデル

### 6.1 設置と運転

Installation EnvironmentとOperating Environmentを分離する。先行建設や将来の環境変化をLocation特例なしで扱えるようにする。

Facilityは同一Domainのまま配置種別を持つ。

- `OPERATIONAL_NODE`: Operational Nodeへ所属し、個別Surface Cellを指定しない通常Facility。Surface Locationとnon-surface Operational Nodeの双方へ配置できる。
- `SURFACE_CELL`: 物理的位置が性能、Route接続、局所Environment、環境改変等へ本質的に影響する位置依存Facility。

`SURFACE_CELL` Facilityだけ `site_cell_id` を要求し、所属Operational NodeはSurface Locationでなければならず、対象CellはそのLocationの開発済み領域でなければならない。別のSurface Installation Domainを作って建設・維持・Power・Capability / Service Capacityを重複実装しない。

ApplicationはOPERATIONAL_NODE FacilityのBuild OptionでCell選択を要求しない。SURFACE_CELL FacilityはMap上の候補Cellと可否・blockerをQueryし、空間操作として配置する。

### 6.2 Pause

PauseしてもFacilityは消滅しない。通常運転に伴うProcess、生産、採掘、発電、建設、Research、Survey等のService Capacityは停止する。Active Capabilityも運転を必要とするものは無効になるが、物理的なInstalled Capabilityまで失われたことにはしない。

一方、安全維持・保冷等のstandby loadと物理的維持要件は通常Pauseだけでは消滅しない。当tickに必要な維持Resource Claimと、その維持を継続するための補充Resource Demandは残る。将来のMothballはPauseとは別状態とする。

### 6.3 資材維持需要

Facilityは建造・Upgrade時に実際に投入されたResourceを基礎に維持需要を持つ。

```text
maintenance_demand(resource, period)
= cumulative_invested_resource × maintenance_fraction(period)
```

維持率はContent Definitionのバランス値とする。維持資材は特別な税処理ではなく通常Resourceとして扱う。当tickの消費はResource Claim、将来の補充はResource Demandとして同じInventory / Logistics契約へ接続する。

割当済みResource Claimが不足した場合はFacilityを即時破壊せず、maintenance fulfillmentを0..1で算出し、Service Capacity、生産率、Research Point生成等へ共通係数として反映できる構造を基本とする。categorical Capabilityの有無と、現在供給可能な量を同じ数値で表さない。

---

## 7. Inventory / Resource Allocation / Storage / Power

InventoryはOperational Nodeごとの所有Resourceを表し、on-hand、Reservation、利用可能量、輸送待ち、輸送中、到着待機を区別する。

Storageはある時点で保持できるstock上限として `Physical Storage Capacity` と `Usable Storage Capacity` を区別できる。Usableは電力・温調等の成立条件を反映して現在安全に保持できる量の上限であり、一定時間あたりのService Capacityではない。荷役・温調処理量等を有限flowとして競合させる場合はCargo Handling / Conditioning等の別Service Capacityとして定義する。輸送中Cargoは目的地Storageを事前予約せず、実到着時にだけ入庫判定する。入らない分はarrival waitingとしてLogistics Domain側へ残す。

PowerはOperational NodeごとのService Capacityとし、他の有限capacityと同様にpriority allocationを行う。部分稼働可能な需要は割当率に応じて縮退できる。

### 7.1 Resource Claim

Maintenance、Industry、Research Prototype、Construction、Vehicle Production等が同じInventory Resourceを必要とする場合、Domain処理順で先着消費させない。各Domainは実行phaseに必要なlocal Resourceを `ResourceClaim` として提出し、Inventory / Allocation責務がsnapshot上の利用可能量へ割り当てる。

Resource Claimは少なくとも次を持てる。

```text
ResourceClaim
  operational_node_id
  resource_id
  requested_amount
  minimum_amount / atomic?
  priority
  owner / purpose
```

player-configurable priorityまたはDomain既定priorityを利用できる。同priorityの連続量は比例配分を基本とし、最低成立量を満たさなければ意味がないProject等だけ明示的なminimum / atomic contractを使う。同順位結果をEntity登録順へ依存させない。

長期Project等で既に確保済みのResourceはReservation / commitmentとしてResource Claimと分離する。Claimを暗黙の永続予約へ変換しない。

`Resource Claim` は現在Node内の実行競合、`Resource Demand` は将来の補充・調達要求であり同一概念ではない。Claim不足をどのようなDemandへ変換するかは要求元Domainのpolicy / target在庫契約が決める。

### 7.2 Service Capacity Allocation

Power、Construction、Cargo Handling、Surface Infrastructure、Research execution、Survey等の有限flowはService Capacity Requestとして同様に配分する。Domain固有のcompatibility条件は各ServiceのDefinitionで評価してよいが、同じCapacityを複数Domainへ二重計上しない。

Operational Node内部のSurface Infrastructure / Local Distributionもこの仕組みを利用する。個別ResourceをCell間でroutingせず、遠隔Cell利用、Surface Gatewayとの受渡し、領域拡大等が要求するservice loadと割当済みcapacityを比較する。Surface CellをInventory Nodeへ分割しない。

---

## 8. Industry / Extractionモデル

### 8.1 Process

FacilityそのものとProcessを分離する。Processはinputs、outputs、基準処理能力、電力等を持つ。

Application Queryは設備ごとの選択Process、実効inputs / outputs、稼働率、limiting factorを返す。UIは「何を消費して何を作るか」をFacility画面から直接確認可能にする。

### 8.2 資源・能力競合

Processは必要ResourceをResource Claim、必要PowerやProcess CapacityをService Capacity Requestとして提出する。Industryだけの独自先着配分を持たず、Maintenance、Research、Construction等と同じAllocation契約で競合する。Application Queryはrequested / allocated / fulfillmentとlimiting factorを返す。

### 8.3 Extraction / Resource Potential

有限 `Deposit remaining` を採掘の正本にしない。地表資源はSurface Cellごとの静的 `Resource Potential` と、Locationに設置された採掘Facilityが供給するNominal Extraction Capacityから継続的なThroughputを導出する。

Resource Potentialは残量、Facility slot数、固定最大`t/day`のいずれでもなく、追加採掘能力をどの程度高い限界生産性で利用できる地域かを表す。Cell面積が天体間・Cell間で異なる可能性を考慮し、PotentialはCellの面積・地質を含んだ機会量として扱えるようにする。

同一Location・Resourceについて、開発済みCell群からEffective Resource Opportunityを集約する。Static Potentialに加えて現在Environment、Surface Infrastructure等の物理的利用可能性を反映してよいが、通常採掘によってStatic Potentialそのものを減らさない。Survey Knowledgeは物理的Throughputを変化させる係数ではなく、プレイヤーへ公開する推定値・候補・blockerを決める知識状態として分離する。

```text
EffectiveOpportunity(location, resource)
  <- developed Surface Cells
  <- static Resource Potential
  <- current environment / accessibility
  <- Surface Infrastructure availability

InstalledNominalCapacity(location, resource)
  <- active extraction Facilities

ActualExtraction
  = diminishing_response(
      InstalledNominalCapacity,
      EffectiveOpportunity
    )
    × operational fulfillment
```

`diminishing_response` は少なくとも次を満たす一般契約とする。

- Installed Capacity増加に対して総採掘量は単調非減少。
- 同じOpportunityに対する限界増産量は逓減する。
- Facility数のハード上限をResource Potentialから直接導出しない。
- 研究完了だけで既存FacilityのNominal Capacityを変更しない。

研究は新しいFacility Definition、Process、Construction / Modernization手段を解禁する。Throughput上昇には実際のFacility建設・Upgrade・更新が必要となる。

初期地球産業は開始時から高いResource Knowledgeを持つSurface CellをContentとして定義できる。Earthという固有名へのCore特例は作らない。

### 8.4 ロケーション産業自立・外部依存Analytics

ロケーション産業自立は保存Stateや特定天体固有のフラグではなく、Production、Consumption、Resource Demand、Import / Export、Unmet Demandから導出するAnalyticsとする。

単一Surface Location、単一Operational Node、または任意のOperational Node集合をanalysis scopeとして選べる。ここで『ロケーション』はanalysis scopeの概念名であり、Entity型としてのSurface Locationだけを意味しない。Resource単位を正本とし、表示上のResource GroupはContent Definitionで定義できる。Mass、Energy、Propellant、Machinery等の固定カテゴリをGeneric Coreへ埋め込まない。

少なくともlocal production、local consumption / demand、imports、exports、unmet demand、external inflow / dependency、critical dependencyをQuery可能にする。派生AnalyticsなのでSaveへ独立保存しない。

## 9. Constructionモデル

### 9.1 建設能力

Construction Service CapacityはOperational Node固定値ではなく、建設ヤード、施工設備、ロボット、移送可能な建設機械等から発生する有限flowとする。

複数Projectへ配分でき、一案件完了後の余剰能力は残案件へ再配分する。

### 9.2 Construction Recipe

建築物は原則2〜3種類の明示的な実Resourceを消費して建造する。

```text
ConstructionRecipe
  facility_definition_id
  resources: 2..3 kinds
  construction_work
  site_requirements
  prerequisite_technologies
```

簡易Facilityは2種類、高度Facilityは3種類程度を基本とする。抽象ComponentへLocalSubstitutionTierをぶら下げる方式は採用しない。

### 9.3 産地非依存

建造時の「現地代替」「現地材比率」「代替材選択」は廃止する。同じResource Definitionであれば産地はRecipeの意味に影響しない。

```text
Extraction
→ Process
→ Inventory
→ Logistics if needed
→ destination Inventory
→ Construction consumption
```

現地工業化の価値は通常の生産・物流だけから発生させる。

### 9.4 Build Project State

通常Build Projectは少なくともOperational Node、進捗、Resource commitment / allocation状態、sourcing constraint / policy reference、priority、pause状態を持つ。SURFACE_CELL Facilityだけは追加で配置Cellを持つ。Projectは通常物流の各Legや輸送方式をauthoritative stateとして所有しない。実行に必要なlocal ResourceはResource Claim、補充に必要な量はResource Demandとして生成し、Logistics / TransportがPlayer Policyの範囲でsource、Route、共有Transport Capacityを決める。

PauseとCancelを分離する。

### 9.5 Location founding / development

既存Locationの隣接Surface Cell開発は、Resource・Construction Service Capacity・時間・SiteRequirementsを消費する通常のDevelopment Projectとして扱う。既存Location拡張では原則として現在のdeveloped cell集合へ隣接する未所属Cellだけを対象とする。

最初の地表Location設立は、対象Locationがまだ存在せずDestination Inventoryも通常Route endpointも持てないため、通常Build Projectとは別のFounding Deployment Projectとして扱う。

```text
LocationFoundingProject
  staging_node_id
  target_body_id
  target_core_cell_id
  founding_package_id
  prepared_payload / resource commitments
  deployment transport requirement / assignment
  preparation_work
  status
```

Founding Deploymentはstaging node側でResourceと必要な準備能力を確保し、Transport Domainへ一回限りのDeployment Operationを要求する。target Surface CellはこのOperationの物理endpointにはなるが、Location成立前にInventory Nodeや通常Logistics Lane Nodeへ昇格しない。Landing / descent / access等のOperation要件はVehicle実性能とtarget Environment / SiteRequirementsから判定する。

成功時にSpatial / Operational Node責務がSurface Locationと対応するOperational Nodeを一度だけ生成し、Founding Package Definitionから初期Facility、必要ならFleet、Storage capacity、Inventory等を展開する。Packageが最低限どのCapability / Service Capacityを提供するかはContentで定義し、Location名や月面固有IDによるCore特例にしない。以後のFacility建設・Resource Claim / Demand・通常物流は生成済みOperational Nodeをdestinationとして通常モデルへ移行する。

Location developmentはFacility建設とは別の地理的投資であり、通常FacilityのCell配置へ読み替えない。

---

## 10. Logistics / Vehicleモデル

TransportはVehicle / FleetからOperational Node間の輸送能力を供給し、Logisticsはその能力をResource Demandへ配分する。通常物流で個体Vehicle Missionを繰り返し生成せず、Fleet Allocationから定常Transport Capacityを導出する。

### 10.1 Transport Operation / Route

Route可否は用途名でなくOperation要件と実性能から判定する。

- Powered Ascent
- Spaceflight
- Landing
- Atmospheric Entry

必要に応じてDelta-v、Thrust、Endurance、Atmosphere、Gravity、Landing、Docking / Refueling Infrastructure等を使う。Launch Vehicle / Spacecraft / Lander等の名称は表示に利用できるが、可否判定には使わない。

研究技術IDをRouteの直接解除条件にせず、研究で解禁されたVehicle、推進、補給、Infrastructure等の実能力から到達可能性を決める。

Operational Nodeは物流上のNodeであり、Surface Locationもその一種とする。ただし地表LocationのCore Cellや代表座標をRoute距離の固定正本にしない。位置が意味を持つRouteは、実際に利用するGateway / access interfaceとそのSurface Cellから物理距離、所要時間、Operation要件を導出する。

```text
RouteEndpoint
  operational_node_id
  locator:
    surface_interface_id | access_cell_id | non_surface_interface
```

Location拡大によって二つのLocationの開発圏やGatewayが接近した場合、旧Core Cell間の遠距離判定を保持しない。同一天体Surface Transportは実endpoint間geometryから評価する。`surface_interface_id` がSURFACE_CELL Facilityを参照する場合、そのCell位置はFacility Stateから導出し、Endpointへ重複保存しない。専用Gatewayを要求しないTransport Modeでは、開発済み境界Cell等を `access_cell_id` として利用できる。

Surface Cell自体をTransport Capacity Network Nodeにはしない。通常Routeは成立済みOperational Node間の契約を維持し、位置情報はService Plan導出の物理条件として利用する。Contentは将来プレイヤーが生成するLocation IDごとの静的Routeを列挙しない。既存NodeのSpatial relation、利用可能なaccess / Gateway interface、Operation要件からRoute Resolverが成立可能Routeを導出する。

Location設立前だけは `DeploymentEndpoint(surface_cell_id)` を一回限りのFounding / Deployment Operationで利用できる。このendpointはInventoryを所有せず、Logistics Laneや定常Transport CapacityのNodeにもならない。Founding完了後は生成されたLocationと展開済みaccess interfaceを通常Route導出の入力にする。

### 10.2 Vehicle Definition / Fleet State

Vehicle DefinitionはRoute適合と運用能力を導出する物理・運用性能を持ち、固定の`t/day`を持たない。必要に応じて以下を持つ。

- Dry Mass / Payload Capacity
- Propellant type / capacity / consumption model
- Operation capabilities / environment envelope
- Travel performance / Endurance
- Docking / refueling等のinterface
- minimum turnaround / servicing work / maintenance resources
- Production Capability / duration / resources

同じ性能モデルからRoute可否、運行cycle、方向別Payload、latency、推進剤需要、servicing需要を導出する。同一の物理制約をCapability上限とResource計算へ重複定義しない。

通常運用のVehicleは個体IDではなく、Vehicle Definition × Operational Node単位のFleet Stateとして管理する。Fleet Stateは少なくとも総数と、Transport Allocation、Scientific Exploration、relocation、releasing等への排他的配分を持つ。未配分数はそれらから導出する。

### 10.3 Vehicle Production / Fleet relocation

ロケットや宇宙船は外部Serviceだけでなくプレイヤーが建造できる。対応Capability、2〜3種類程度の実Resource、時間を消費してProduction Stateへ入り、完了後は建造Operational NodeのFleetへ数量を追加する。

地点間のFleet再配置はaggregateなFleet Relocationとして時間を要する。Transport Allocationを減らしたFleetも必要な回収時間中はreleasingとして拘束し、即座に別地点のfree Fleetへ戻さない。

ApplicationはVehicle Production Option、Fleet所在・総数・各用途配分、relocation / releasing、現在のblockerをQueryできるようにする。

### 10.4 Transport Allocation / Transport Capacity

プレイヤーはVehicle type、輸送する拠点間関係、経路・運用Policy、Allocation priorityを指定してFleetを輸送へ配分する。Corridor / Transport Serviceを別の管理対象として作成させない。

Transport Allocationは次のどちらか一方をauthoritative targetとして持つ。

- `UNITS`: 目標Fleet隻数を指定し、輸送能力を導出する。
- `CAPACITY`: 方向別の目標定常capacityを指定し、Nominalな1隻当たり能力から必要隻数を導出する。

両modeの値を同時に正本にしない。mode切替時は現在値から新modeの初期値を導出し、以後は新modeだけを保存する。CAPACITY modeのFleet必要数には一時的な燃料・整備不足を反映させず、不足を埋めるための自動増員を起こさない。

Fleet不足でtargetを満たせないAllocationは有効な設定として保持し、不足数をblockerとして返す。free Fleetが増えた場合はAllocation priorityに従って既存targetまで投入できる。同順位の結果を登録順に依存させない。

Transport DomainはAllocationごとに、Cargo輸送後もFleetが反復運用可能な状態へ戻る経路を含むTransport Service Planを導出する。往復Route、Vehicle固有のrecovery、turnaround、refueling、servicingを一般モデルとして組み合わせ、機種名による特殊分岐を置かない。

Service Planから方向別Transport Capacityを導出し、少なくとも次を区別する。

- Target: CAPACITY modeで指定した目標
- Nominal: Fleet数と通常運用条件から得られる設計能力
- Available: 現在のResource / Infrastructure / servicing制約を反映した能力
- Used: Logisticsが実際に利用した能力
- Spare: Available - Used

往復Serviceは同一cycleが両方向を担当するため、方向別capacityを加算してFleet負荷を二重計上しない。帰り荷がない場合は空荷回送を含め、帰り荷がある場合は同じ復路capacityを利用する。

推進剤・servicing等の可変運用需要はAllocation最大値ではなく実際のService利用率から発生させる。Available CapacityはPhysical snapshotのFleet / Infrastructure等と、Planningで明示した推進剤・servicing・上流Service等へのdependency allocationから当tickAllocation内で決める。同tick中に生産・到着したResourceで遡及的に増加させない。

External Transport ServiceはFleet Allocationを持たず、同じTransport Capacity interfaceへ直接能力を供給できる。ただしPlayerのExternal Service Policyが当該service / laneで明示的に利用を許可している場合だけallocation候補へ入れる。Policy未設定はdefault-denyとし、Content側に候補Serviceが存在することをPlayer authorizationとみなさない。

### 10.5 Logistics Lane / Resource Demand / Cargo Flow

定常物流の主要設計対象は品目別補充ルールではなく、Operational Node間輸送能力、方式、Fleet配分、sourcing / route Policy、Lane priorityとする。

Facility、Construction、Maintenance、Industry、Research等は、自分の成立条件から `ResourceDemand` を生成する。

```text
ResourceDemand
  demand_id / stable demand key
  destination_node_id
  resource_id
  requested / target amount or rate
  priority / urgency
  optional source constraints
  owner / purpose
```

Domainは必要量と戦略上必要なconstraintを所有するが、通常はsourceや各Legを固定しない。Logisticsは同じDemandへ既に割り当て済み・輸送中のCargoを未充足量から控除し、重複発送を防ぐ。輸送中CargoはDemand fulfillment見込みには数えてよいが、destination InventoryやStorage reservationへは変換しない。LogisticsはPlayerが設定したsourcing / route Policyから利用可能source集合を評価し、発送候補ごとにsource側Resource ClaimとLane / Transport Capacity requestを生成する。発送用Resource ClaimはMaintenanceやIndustry等の現地実行Claimと同じsource Inventory上でAllocationされ、割当済みResourceとTransport Capacityの範囲だけCargo Flowへdispatchできる。これによりLogistics sourcingがsource在庫を暗黙予約・二重消費しない。

Transport Allocation targetは「どれだけ輸送能力を用意するか」、Lane requested capacityは「その能力をどれだけ物流需要へ利用するか」を表す。Lane需要からFleetを暗黙に増員しない。Lane priorityとFleet Allocation priorityは別責務とする。

通常物流の実行は個体Vehicle MissionではなくCargo Flowとして表現する。利用したcapacityに応じてCargo Flow Batchを生成し、Service latency後に目的地Inventoryへ到着させる。輸送中Cargoは目的地Storageを事前予約せず、実到着時に入庫判定する。容量不足分はarrival waitingとしてLogisticsが保持する。

### 10.6 End-to-End / Special Mission

プレイヤーは原則として出発Nodeと最終目的Nodeを指定できる。経路未指定時は明示Policyに従ってTransport Capacity Network上のpathを選択し、中継Nodeごとの再発送Commandを要求しない。

End-to-End能力は経路上の共有capacityと競合需要から決まる。同じFleetが途中NodeでCargoを引き渡さず連続運行できる場合は一つのTransport Serviceとして扱い、別Fleetへ引き渡す地点だけをLogistics上のhandoffとする。

LEOやLunar OrbitはInventory / refueling / transfer / servicing Nodeとして利用できるが必須進行ゲートではない。プレイヤーが明示したVehicle / Service / pathが利用不能になった場合は、明示Policyがない限り別方式へ勝手にfallbackしない。

有限・状況依存の特殊輸送はTransport Missionとして別途扱ってよい。通常のLane物流をMissionへ戻さない。

### 10.7 External Economy / Funds

Fundsを扱う場合は組織全体の二次Stateとし、Operational Node Inventoryへ混在させない。External Procurement / External Transportは通常のResource / Transport interfaceへ供給を接続できるが、Playerが明示したPolicyの範囲内だけ自動利用する。物理Resourceの外部調達は通常の到着・Storage・latency契約を迂回せず、資金支払いだけで目的地Inventoryへ即時生成しない。

Policyは必要に応じてallowed service / provider、spending cap、period budget、minimum reserve funds等を持てる。複数のExternal Service候補が同じFundsを必要とする場合は、snapshot上のFundsとPolicy budgetに対するspending authorizationをPlanning / Allocationで競合解決し、DomainやLaneの処理順で先着支出しない。SimulationはPolicy内の反復選択を自動化してよいが、未許可の外部支出を「不足を解消するため」という理由で自動開始しない。

Contractや外部Eventを将来導入する場合はFundsやResource等への検証済みCommand / Eventとして接続できる。ただしContract state machineを通常産業・研究Simulationの必須Core Domainにはしない。

---

## 11. Research Point / Research / Knowledgeモデル

Research Pointは通常貨物Inventoryとは分離し、組織全体の共有Knowledge PoolとしてResearch Stateが所有する。Research ProviderはOperational Node上のFacility / Fleet等のDefinition-backed providerからRP生成量と貯蔵能力を供給できるが、生成したRPをprovider所在地専用pointにはしない。

Research ProviderはTierとLevelを持てる。

- Tier：研究手段の世代差・基礎効率差
- Level：同一世代設備への増設・拡張・改良

Research Point storage capacityは有効なprovider群から導出する。容量低下で既獲得RPを消去せず、新規生成を制限する。

### 11.1 Technology State

完了済みTechnology集合は単一のauthoritative `TechnologyState` が所有する。Facility、Process、Vehicle、Route等はprerequisite technologyを参照するだけで、各Domainへunlock flagを複製しない。

研究技術IDをRouteの直接解除キーにしない。研究はVehicle、Facility、Process、推進、補給方式等を解禁し、実際の到達可否はOperation要件・Vehicle性能・Infrastructureから決める。既存Facilityの性能もResearch完了時に暗黙変更しない。

### 11.2 Research Project / stage

Research Projectは複数を並行して進められる。固定の単一global queueを正準仕様にしない。並行性はRP、Research execution Service Capacity、必要Facility / Capability、Prototype Resource、Demonstration条件等から自然に制約する。複数Projectが同じResearch Point Poolを消費する場合はResearch priorityと明示的なminimum / atomic条件に従ってResearch Domain内で配分し、Project登録順を暗黙priorityにしない。

Research Definitionは必要なstageを組み合わせて持てる。

- `THEORY`: RPとResearch execution Service Capacityを利用する。
- `PROTOTYPE`: 選択Operational NodeでResource Claim / Demand、Facility、Environment、Service Capacityを要求する。
- `DEMONSTRATION`: 指定された実環境・Operation・Facility等で期間と実行条件を満たす。
- `OPERATIONAL_EXPERIENCE`: 対応categoryのKnowledge Stateが要求値へ到達することを要求する。

全研究を固定4段階へ強制せず、Definitionが不要stageを省略できる。Prototype / Demonstrationを特定Location IDへ固定せず、SiteRequirements、Capability、Service Capacity等から候補Operational Nodeを判定する。

### 11.3 Operational Experience / Knowledge State

Operational ExperienceはResearch Projectが時間経過だけで生成するpointではない。Transport、Extraction、Manufacturing、Crewed Operation等の実Domain activityが共通interfaceを通じてexperience contributionを報告し、Knowledge Stateがcategoryごとの蓄積を所有する。Researchはこのstateをrequirementとして参照する。

Domainごとに同じExperience値を重複保存しない。Experience categoryはContentで定義でき、特定Location名やVehicle名をGeneric Core categoryへ埋め込まない。

### 11.4 Human operation abstraction

現段階ではCrew個人・人口を独立Entity / Domainとして所有しない。有人運用はcrew-ratedなVehicle / Facility property、Habitation / Life Support等のCapability / Service Capacity、消耗Resource Claim / Demand、Environment Requirementから表現する。Crew自体が主要な配置・成長・リスク判断になった場合にだけ独立Domainへ昇格する。

---

## 12. Scientific Exploration / Resource Survey

科学探査と資源Surveyを別Domain状態として扱う。

### 12.1 Scientific Exploration

Scientific Exploration Campaignは必要性能を満たすFleet unitを一定期間拘束し、科学観測・近接探査・有人活動等から有限量のResearch Pointを得る。

Definitionは対象、必要Operation / Delta-v / Endurance、必要Payload / Capability、必要環境・Infrastructure、期間、RP報酬、消耗Resource等を持てる。

Exploration DomainはFleetの所有状態を直接変更せず、Fleet Domainへ必要unit数の排他的reservationを要求する。拘束中unitはTransport Allocationや別Explorationへ利用できない。適合判定は「探査船」という用途タグではなく実性能から行い、Enduranceは往路・活動・必要な帰還を含むCampaign運用計画全体に対して判定する。Campaign planは完了後Fleetをoriginへ戻すかdestination Operational Nodeへ残すか等のdispositionを明示し、完了時にFleetを暗黙テレポートさせない。

同一Campaignから無限RPを生成しないことを基本とする。

### 12.2 Resource Survey

地表Resource Surveyは `SurfaceCell × Resource` のKnowledgeを更新する。固定Location × ResourceをSurvey正本にはしない。

```text
Unknown
→ Presence Probability
→ Estimated Resource Potential
→ Measured Resource Potential
```

Survey providerは単なる `points/day` だけでなく、観測Capability、Spatial coverage、到達可能Knowledge Level、必要Operation / Infrastructureを定義する。Survey Serviceはproviderの現在Spatial contextとtarget Cellの関係からreachabilityを判定する。

```text
SurveyProviderDefinition
  provider reference / capability
  survey_rate
  coverage / reach model
  max_knowledge_level
  operation / infrastructure requirements
```

軌道Remote Survey providerは、対象天体にSurface Locationが存在しなくても広域Cellを観測できる。これを最初のLocation候補比較の正規経路とする。地表・近接Survey providerは既設Locationや展開Facility / Fleetから到達可能な範囲を対象とし、より高いKnowledge Levelまで更新できる。特定施設名ではなくprovider definitionとSpatial relationから差を表現する。

有限Reserveの残量段階は持たない。Survey KnowledgeはResource Potentialそのものとは分離し、未Surveyでも地質状態が変わるわけではない。

地質Knowledgeは基本的に恒久的な観測結果として扱える一方、Dynamic Environmentは別Stateとして更新され得る。将来のテラフォーミング等で環境由来の資源利用可能性が変わる場合も、Static Resource Potentialと現在Environmentを分離して再評価する。

完了Campaignは、そのproviderで到達可能な上限まで完了した対象を能力配分対象から外し、余剰Survey能力を未完了対象へ再配分する。より高いKnowledge Levelへ進むには必要に応じて別provider / observation modeを利用する。

科学探査のRP獲得とResource SurveyのKnowledge更新を同一状態機械へ混在させない。

## 13. Command / Query API

### 13.1 Command

主要カテゴリ：

- Time pause / resume / speed
- Surface Location founding deployment / adjacent Cell develop
- Build / Upgrade / Cancel / Pause / Resume
- Surface-cell Facility placement where required
- Resource / Service Capacity priority policy
- Facility pause / resume / process / power priority
- Vehicle produce / Fleet relocate
- Transport Allocation create / update / pause / resume / delete
- Logistics Lane / sourcing / route policy
- External Service allow / spending policy
- Manual Cargo / special Transport Mission
- Research start / pause / resume / priority / stage execution
- Scientific Exploration start / pause / resume / Fleet assignment / completion disposition
- Resource Survey start / pause / resume / allocation
- External event response where an extension provides one

現地材比率・代替材選択Commandは持たない。

### 13.2 Query

主要Query：

- Catalog / World / Celestial Body Surface Map / Operational Node / Surface Location
- Surface Cell / Survey Knowledge / Resource Potential / Environment / development affiliation
- Flow / Bottleneck
- Inventory / Resource Claims / allocations / unmet demand
- Capability / Service Capacity / requested / allocated / spare / limiting factor
- Facility / placement scope / Process inputs / outputs / utilization
- Maintenance demand / fulfillment
- Build Options / Projects
- Vehicle Production Options
- Logistics / physical Route endpoints / Fleet / Transport Allocations / Transport Capacity / Cargo Flow / Lanes / special Missions
- Location territory / Surface Infrastructure demand and fulfillment
- Funds / External Service Policy / spending
- Research Point / Technology State / Research Projects / Operational Experience
- Scientific Exploration
- Resource Survey
- ロケーション産業自立 / external dependency analytics for selected Operational Node scope
- External Events where an extension provides them

Query DTOはJSON化可能なimmutableデータとする。UI側が可否・維持率・経路適合・allocation・産業依存度等を再計算しない。

---

## 14. Save / Load / Offline Progress

SaveはApplication単位のversion付きSnapshotとする。静的Definitionは現在Contentから再構築し、可変Stateだけを復元する。

保存対象にはOperational Node、Surface LocationのCore Cell・developed cell affiliation、Facility（位置依存Facilityのsite cellを含む）、Inventory / Reservation、Resource / Service Capacity priority policy、通常Build / Development Project、進行中のLocation Founding Deployment、Vehicle Production、Fleet数量と用途配分、Transport Allocation target、Fleet Relocation / Releasing、Cargo Flow / arrival waiting、特殊Mission、Funds / External Service Policy、Research Point、Technology State、Research Project、Operational Experience Knowledge、Exploration、Survey Knowledge、Dynamic Environment Overlay等を含める。Static Surface Cell topology / geology / Resource PotentialはContentまたはworld definitionから再構築する。Transport Service Plan、Nominal / Available Transport Capacity、tick内Resource Claim、Service Capacity allocation結果、ロケーション産業自立Analytics等の派生・transient状態は保存せず、Load後または次snapshotで再導出する。

ゲーム性評価段階ではschema/content migrationを目的化しない。

Offline Progressは通常Simulationと別ルールにせず、実時間経過をゲーム時間へ換算して同じadvance経路を使う。

---

## 15. Validation / Test

Configuration Validation：

- 未定義Resource / Facility / Route / Vehicle参照
- 無効SiteRequirement
- 存在しないCapability / Service type
- 負の容量・率・期間
- Construction Recipeの不正Resource数・参照
- Vehicle Production / Maintenance定義不整合
- Transport Allocationの未定義Vehicle / Route / 不正control mode
- Research / Exploration / Survey参照不整合
- Surface Cell topology / area / Resource Potential不整合
- Operational NodeのSpatial context参照不整合
- Surface Locationのbody / core cell / developed cell参照不整合
- Founding Package / staging node / target Surface Cell / Deployment requirement参照不整合
- SURFACE_CELL FacilityのOperational Node / site cell参照不整合
- Research stage / Technology / Experience category参照不整合
- External Service Policyの未定義service参照
- Allocation dependency graphの循環

Runtime Validation：

- 在庫負値、予約超過
- Cargo質量不整合
- Fleet総数とTransport / Exploration / Relocation / Releasing配分の不整合
- Transport AllocationのUNITS / CAPACITY二重正本
- Resource Claim allocation超過・同一Resourceの二重消費
- Service Capacity allocation超過・二重消費
- Transport Capacityの二重消費
- Vehicle Production / Fleet Relocation状態不整合
- Facility maintenance demand / fulfillment不整合
- Research Point負値・容量処理不整合
- Technology State / Operational Experienceの重複正本
- 未許可External ServiceによるFunds消費
- 孤立Reservation / Entity参照
- Location領域の非連結・Cell重複所属
- Facility placement scopeとsite cellの不整合

ゲーム性評価段階で優先するテスト：

- 資源保存・物流会計
- Surface Locationとnon-surface Operational Nodeが同じInventory / Facility / Fleet所有契約を利用する
- Resource ClaimがDomain登録順ではなくpriority / proportional allocationで競合する
- Logisticsの発送用Resource Claimがsource側の現地用途Claimと同じInventory上で競合し、二重消費しない
- 同じResource Demandへ割当済み・輸送中のCargoを未充足量から控除し、重複発送しない
- Service Capacityが複数Domainへ二重割当されない
- 輸送中Cargoが目的地Storageを事前予約しない
- snapshot後に当tick中に到着・生成されたResource / Capacityが過去phaseのallocationを遡及変更しない
- Construction Recipeが2〜3種の実Resourceを直接消費する
- 産地代替層が建設可否へ介入しない
- 維持需要が累積建造投入量から決定論的に導出される
- 維持不足がFacility Service Capacity / outputへ一貫して反映され、categorical Capabilityと混同されない
- Vehicle建造がCapability・Service Capacity・Resource・時間を消費する
- Fleet unitがTransport / Exploration / Relocationへ二重割当されない
- Transport AllocationのUNITS / CAPACITY targetが単一正本である
- CAPACITY modeの必要Fleet数が一時的なResource不足で自動膨張しない
- Nominal / Available / Used capacityが同じService Planから一貫して導出される
- 複数Laneが共有Transport Capacityを二重消費しない
- Cargo Flowの資源保存とlatencyが成立する
- Operation適合が名称・用途タグに依存しない
- Research Pointの生成・貯蔵不変条件
- 複数Research ProjectのResearch Point消費がpriorityに従い、Project登録順へ依存しない
- 複数Research ProjectがResource / Service Capacityを共通allocationで競合する
- Technology Unlockが単一のTechnology Stateだけを更新する
- Operational Experienceが実Domain activityから蓄積され、Research tickだけで増えない
- Pause / Resume
- 登録順依存排除
- Save / Load後の将来進行同値性
- Offlineと通常進行の同値性
- Generic CoreへのLocation固有分岐侵入検知
- Celestial BodyごとのSurface Cell数・隣接数が可変でも成立する
- Location領域が連結し、同一Surface Cellを複数Locationが重複利用しない
- Extraction responseがInstalled Capacityに対して単調非減少かつ限界収益逓減である
- 通常採掘でStatic Resource Potentialが減少しない
- Research完了だけで既存FacilityのNominal Extraction Capacityが変化しない
- OPERATIONAL_NODE Facilityへ不要なCell指定を要求せず、SURFACE_CELL FacilityだけSurface Locationの有効なdeveloped cellを参照する
- Surface CellがInventory / Logistics Nodeへ自動昇格しない
- 対象天体にSurface Locationが存在しない状態からnon-surface Operational NodeのRemote Surveyを開始・進行できる
- Survey providerごとのcoverageとmax Knowledge Levelを越えてSurveyが進行しない
- Location Founding Deploymentが未成立CellのDestination Inventoryや通常Laneを要求しない
- Founding完了時にLocationとFounding Packageの初期運用基盤が一度だけ生成される
- 新規Locationの通常Routeが静的Location ID列挙ではなく成立後のaccess interfaceから導出される
- 地表Routeの距離・所要時間が実Gateway / access endpointから導出され、Location Core Cellへ固定されない
- Location拡大時のSurface Infrastructure負荷がCell routingなしで決定論的に導出される
- 近接Location分割でSurface Cell / Resource Opportunity / Service Capacityが複製されない
- External Transport / Procurementは明示PolicyなしにFundsを消費しない
- 複数External Service候補のFunds支出がPolicy budgetとpriorityに従い、処理順へ依存しない
- External Procurementの物理Resourceが通常のdelivery latency・到着・Storage契約を迂回しない
- ロケーション産業自立Analyticsが保存正本を持たず、同じResource flowからNode scopeごとに再導出できる
- Dynamic Environment変化とStatic geology / Resource Potentialの状態所有が分離される

暫定価格、日数、生産量等の仮バランス固定テストは避ける。

---

## 16. Web UI / Server / LLM

Web UI実装でもSimulation CoreへHTTP依存を追加しない。

```text
Browser / PWA
    ↓
HTTP / WebSocket Adapter
    ↓
GameApplication
    ↓
Simulation Core
```

UIは天体Surface MapでSurvey状態、Resource Potential、Environment、Location領域、初期Location候補・Founding Deployment blocker、隣接開発候補、位置依存Facilityの配置候補を表示する。Surface Locationがまだ存在しない天体でも、non-surface Operational NodeからのRemote Survey、候補Cell比較、staging nodeとFounding Packageを含む設立判断を同じMap上から追えるようにする。通常Facilityの建設・運用は設備一覧・Inspectorを中心とし、不要なCell選択を要求しない。設備一覧・InspectorではProcess inputs / outputs、Resource Claim / allocation、Service Capacity fulfillment、maintenance fulfillment、Vehicle production blocker等を安定配置で表示する。Fleet / Transport UIでは所在Operational Node・総数・用途配分、Allocation mode / target、必要・投入隻数、Nominal / Available / Used / Spare Capacity、運用Resource需要、external service policy、blocker / limiting factorをApplication Queryから表示する。Location / region分析ではlocal production、imports、unmet demand等のロケーション産業自立・外部依存状態を表示できる。必要情報を隠してUIを簡略化しない。

LLMはFAST PATHへ入れない。

FAST PATH：Resource / Service Capacity allocation、生産、建設、維持、物流、Research Point、Research / Knowledge、Exploration、Survey、Offline Progress。

SLOW PATH：外部組織要求、イベント、交渉、研究上の問題、状況依存Mission。

LLMはCore Stateを自由に書き換えず、検証可能なCommand / Eventへ変換して適用する。

---

## 17. 変更時に守るアーキテクチャ原則

1. 地点名で例外処理せず、条件をモデル化する。
2. DefinitionとStateを分離する。
3. Spatial contextとOperational Nodeを分離し、Surface Locationだけが地表領域を追加所有する。
4. Inventory、Facility、Fleet、Storage、Power等の一般状態所有先をOperational Nodeへ統一する。
5. Capabilityという資格と、配分可能な有限Service Capacityを分離する。
6. 所有在庫・Reservation・輸送中・到着待機・Storage占有を混同しない。
7. 複数DomainのResource競合はResource Claim allocationで解決し、Domain処理順をpriorityにしない。
8. Service CapacityはAllocationを通し、複数Domainが同じAvailable Capacityを二重利用しない。
9. Resource ClaimとResource Demandを分離し、現在消費競合と将来調達を同じ状態にしない。
10. 遠距離輸送中Cargoで目的地Storageを事前予約しない。
11. 自動化は反復処理を担当し、研究・物流・Resource priority・外部支出等の戦略判断を暗黙代行しない。
12. 自動選択には明示的で一貫したPolicyを持つ。
13. External Transport / ProcurementはPlayerが許可したPolicy内だけ利用する。
14. 同順位・同条件の結果をEntity登録順へ依存させない。
15. UIへDomain内部構造を公開せずCommand / Query境界を通す。
16. blocker / limiting factor / allocation resultはCore / Applicationが説明する。
17. Saveは可変Stateを保存し、派生・transient状態を再計算する。
18. Offline Progressは通常Simulationと同じphase契約を使う。
19. ゲーム性評価段階では後方互換を目的化しない。
20. 暫定バランス数値をテストで過度に固定しない。
21. 個別不具合を特殊分岐で塞ぐ前に共通モデル不足を疑う。
22. Transport可否はVehicle用途名ではなく実性能とOperation要件で判定する。
23. 発展段階や研究名を物流・航路の強制ゲートへ転用しない。
24. 建設は2〜3種類の実Resourceを直接消費し、現地代替レイヤーを持たない。
25. Facility維持は建造投入Resourceから導出し、当tick消費をResource Claim、補充をResource Demandとして扱い、Pauseだけで回避できない。
26. Vehicle建造はCapability・Service Capacity・実Resource・時間を消費する通常の資産生産として扱う。
27. Scientific ExplorationによるResearch Point獲得とResource SurveyによるKnowledge更新を分離する。
28. Process inputs / outputs、維持状態、Resource / Capacity allocation、Vehicle建造条件等の意思決定情報をApplication QueryからUIへ明示する。
29. 通常VehicleはOperational NodeごとのFleet数量として管理し、用途間の排他的配分をFleet Domainが所有する。
30. Transport Service PlanとTransport CapacityはFleet Allocation等から導出し、独立した保存正本にしない。
31. Transport AllocationのUNITS / CAPACITYは一方だけをauthoritative targetとする。
32. LogisticsはFleet Stateを直接操作せず、Transportが供給する共有Capacityを消費する。
33. 通常物流はCargo Flowとして扱い、個体Vehicle Missionを反復生成しない。
34. Fleet Allocation解除・地点間再配置には回収・移動時間を持たせ、aggregate Fleetを瞬間移動させない。
35. Surface Cellは物理地理の単位であり、通常Facility slot、Inventory Node、Logistics Nodeへ兼用しない。
36. 地表Locationは任意Cellへ設立し、隣接Cellを開発して連結領域として拡大する。標準月面進行では事前生成された月面Locationを設立前提にしない。
37. Celestial BodyごとのSurface Cell数、面積、隣接数をCore定数にしない。
38. Resource Potentialは有限Reserveではなく採掘Opportunityとして所有し、採掘Service Capacityとのsoft saturationでThroughputを導出する。
39. ResearchはTechnology Stateへ解禁を記録し、既存Facilityの性能を完了時に暗黙変更しない。
40. Operational Experienceは実運用DomainからKnowledge Stateへ蓄積し、Research Project内部の経過時間として生成しない。
41. Research Projectは複数並行可能とし、Resource / Service Capacityによって競合させる。
42. 位置依存FacilityもFacility Domainに統合し、placement scopeでCell配置要否を表す。
43. Location内部物流は集約Surface Infrastructure Service Capacityとして扱い、Cell単位Cargo routingを通常物流へ持ち込まない。
44. 地表Location間Routeの物理条件は実Gateway / access endpointから導出し、Location代表座標へ固定しない。
45. Location設立前のSurface Cellを通常Inventory / Logistics Nodeへ昇格させず、Founding Deploymentだけが一時的な物理targetとして参照する。
46. プレイヤー生成Locationへの通常Routeは静的Location ID列挙ではなく、成立後のSpatial relationとaccess interfaceから導出する。
47. 最初のSurface Location候補比較はSurface拠点を前提としないRemote Surveyで成立可能にする。
48. Static geology / Resource PotentialとDynamic Environmentを分離し、将来のテラフォーミングをState更新として接続可能にする。
49. 近接Location設立を禁止せず、単一Location拡張と複数Operational Node化を実コストのtrade-offにする。
50. ロケーション産業自立・外部依存はResource flowから導出するAnalyticsとし、特定天体や固定Resource GroupをCoreへ埋め込まない。
51. Crew個体Stateは主要な意思決定になるまで導入せず、有人要件をCapability / Service Capacity / Resource Claim・Demandで表現する。
52. 1tickの処理はphase contractに従い、snapshot後の状態変化で過去phaseを遡及更新しない。

---

## 18. 参考実装との対応（非正準）

この節はmigrationや監査時に責務の所在を追跡するための参考であり、ファイル名や現行module構成を正準Architectureとはしない。実装は上記Domain契約へ従って統廃合してよく、この表に実装を合わせるためにArchitectureを変更しない。

| 領域 | 参考責務 |
|---|---|
| `spatial.py` | Celestial Body、Surface Cell graph、Spatial context、Operational Node / Location territory、Environment State |
| `site.py` | SiteRequirements / Capability / Service Capacity Requirement |
| `facilities.py` | Facility Definition / State / placement scope / Capability / Service Capacity supply |
| `power.py` | Power配分 |
| `inventory.py` / `storage.py` | Inventory / Reservation / Resource Claim allocation / Storage |
| `industry.py` / `production/` | Process inputs / outputs / production flow / Resource Potential extraction response |
| `construction/` / `projects.py` | Construction Recipe、Project、調達、能力配分 |
| maintenance domain | Facility maintenance demand / fulfillment |
| `transport/` | Operation、Route、Vehicle Definition、Fleet State、Vehicle production、Transport Allocation、派生Service Plan / Capacity、Fleet relocation |
| `logistics.py` / logistics domain | Resource Demand、sourcing Policy、Lane、共有Transport Capacity配分、Cargo Flow / pipeline、arrival waiting |
| `research.py` | Research Point、Technology State、Research Project / stage、Operational Experience |
| exploration domain | Scientific Exploration Campaign / Fleet reservation / RP reward |
| `survey.py` | Surface Cell Resource Knowledge、Survey Campaign |
| `simulation.py` | tick phase orchestration / snapshot / allocation sequencing |
| `application*.py` | Command / Query / DTO |
| `persistence.py` | Snapshot / Load / Offline resume |
| `validation.py` | Configuration / Runtime invariant |
| `content/` | ゲーム固有Definition |
| `composition/` | DomainとContentの配線 |

現行実装が正準Domain契約と一致しない箇所は、この表や既存moduleを互換層として温存せず、変更単位ごとに正準責務へ統合する。

---

## 19. 現時点のアーキテクチャ定義

本作のCoreは、Research / Knowledgeの成長、物理的な産業拡大、空間的な拠点拡大、それを支えるResource / Service Capacity / Logisticsを一つの状態モデルへ接続する。

**「Spatial contextとOperational Nodeを分離し、Surface LocationはSurface Cell領域を追加所有するOperational Nodeとして扱う。Inventory、Facility、Fleet、Storage、Power等の一般StateはOperational Nodeへ集約する。各DomainはResource Claim、Resource Demand、Capability、Service Capacityという共通契約を通して資源・能力を競合し、Domain処理順を暗黙priorityにしない。VehicleはFleetとして用途配分し、Transport Allocationから定常Transport Capacityを導出し、LogisticsはPlayer Policyの範囲でsource / routeを選びCargo Flowへ共有Capacityを配分する。Research Pointは組織共有Knowledge Pool、Technology Unlockは単一Technology State、Operational Experienceは実運用から得るKnowledge Stateとして所有する。Surface LocationはRemote SurveyとFounding Deploymentで生成し、単一拠点拡張と複数拠点化を実Infrastructure / Logistics costのtrade-offにする。ロケーション産業自立は特定天体固有Stateではなく任意Operational Node集合のResource flowから導出する。Simulationはsnapshot → intent → planning → allocation → execution → movement → state transitionのphase契約で決定論的に進行し、Application Command / QueryがPlayerの戦略判断とblocker / allocation結果を外部へ公開する」**

として維持する。


ゲーム固有の面白さはEarth、Moon等の固有名をCoreへ埋め込むことで作るのではなく、Content DefinitionがGeneric Coreの組み合わせから異なる制約・産業構造・発展経路を形成することで作る。
