# 宇宙開発Idleゲーム アーキテクチャ設計 v0.4.0

## 文書ナビゲーション

- §1–4: 文書の役割、Layer責務、Simulation phase、Definition / State分離
- §5–6: Spatial / Operational Node / Environment / Facility / Maintenance
- §7–9: Inventory / Allocation / Storage / Industry / Construction
- §10: Movement / Transport / Logistics / Vehicle / Cargo
- §11–12: Research / Knowledge / Scientific Exploration / Resource Survey
- §13–16: Application API / Persistence / Validation / UI・Server・LLM
- §17: 全節へ横断適用するArchitecture invariant
- §18: Architecture定義の要約

詳細規則は各担当節を正本とし、§17はそれらを再定義しない。現行moduleとの対応は非正準の `implementation-map.md` を参照する。

---

## 1. 文書の目的

本書は「宇宙開発Idleゲーム デザイン案」とSimulation Core実装の間に置くアーキテクチャ上の共有基準を定義する。

対象は個別の仮バランス数値ではなく、状態所有、Generic CoreとContentの分離、Spatial context・Operational Node・Surface Location、Environment、Facility、Capability / Service Capacity、Execution Requirement / Supply Requirement、建設・維持・Movement・物流・Vehicle・Research / Knowledge、Exploration・Surveyの関係、Application境界、Save/Load・Offline Progress、検証・拡張原則である。

本書は特定versionの実装状態や作業順序を記録する文書ではない。ここに定義するDomain境界、State ownership、Simulation契約、Persistence / Application境界を、成立すべきArchitectureの正本とする。

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
World / Content Definitions ──→ Composition ←── Scenario Definition
                                  ↓
                         Domain Definitions / initial State
Persistence        ←──→ Application-owned Game State
Validation          ──→ Definitions / State / Domain invariants
```

UIやHTTP層はDomain Serviceへ直接アクセスしない。ApplicationはDomain契約を利用し、Simulation Orchestratorが時間進行上のphaseを統括する。Generic CoreはContent固有Definition、Persistence方式、UI、Earth、Moon、Mars、LLM等へ依存しない。ContentはGeneric Coreが定義したschemaへ具体値を供給し、Persistenceは可変Stateを保存・復元する。Runtime call flowとmodule dependencyを同じ上下図で表現しない。

---

## 3. 層の責務

### 3.1 Generic Core

世界で共通に成立する規則を担当する。

- Star System / Celestial Body / Surface Cell / non-surface Spatial Node / Operational Node / Surface Location / Spatial Relation
- Physical Environment State / SiteRequirements
- Facility Definition / State / placement scope
- Capability / Service Capacity / allocation
- Facilityの資材維持需要と保守充足率
- Inventory / Reservation / Execution Requirement / Stock admission / Storage
- Power配分
- Process / Industry
- Resource Potential / Extraction Opportunity / Extraction response
- Construction / Surface Development Project / Location Founding Deployment
- Movement Operation / Movement Plan、Transport Allocation、Transport Service / Capacity、Cargo Flow、one-shot Movement Execution
- Vehicle Definition / Fleet State / Production / Maintenance / Relocation
- Supply Requirement / Target Stock / Logistics sourcing / end-to-end path
- Research Point、Technology State、Research Project状態機械
- Operational Experience等のKnowledge State
- Scientific Exploration Campaign
- Resource Survey / Knowledge
- Funds / External Resource Market / Trade Order / Market Interfaceの共通契約
- 時間進行phase

Generic Coreへ `if location == MoonSouthPole`、`if vehicle_type == lunar_lander`、用途allowlist等を持ち込まない。必要条件はSpatial classification、Physical Environment、Capability、Service Capacity、Operation、Vehicle性能、Resource等で表現する。

### 3.2 Content Layer

具体的な遊びを定義する。

- Star System / Celestial Body / Surface Cell topology / non-surface Spatial Node / transport geometry
- Static geology / Resource Potential / 基準Physical Environment
- Resource Definition / analytics用Resource Group
- Facility Definition
- Process Definition
- Construction Recipe / maintenance rate / Facility decommission recovery definition
- Resource Potential / Extraction Definition
- Research Definition / Research Provider / Experience category
- Scientific Exploration Definition
- Survey Target / Survey Provider Definition / initial Surface Cell Knowledge
- Spatial transport geometry / Movement Operation / Vehicle / Vehicle retirement recovery / physical Infrastructure connection
- External Resource Market Provider / buy-sell offer / Market Interface Definition
- World Definition / Scenario Definition / Founding Package
- 表示名

外部組織、Contract、Event等はContent / Application側の拡張として追加できるが、FundsをResource売買以外の報酬・一般支払手段として変更しない。Research Point中心の成長ループや通常SimulationのGeneric Core必須Domainにも含めない。

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

Simulation OrchestratorはDomainを固定順に逐次呼び出して競合を解決する場所ではなく、1 game dayをcanonical quantumとする共通phase契約を統括する。各Domainが別Domainの登録順や偶然の呼出順へ依存しないようにする。

Applicationがtick間に受理したPlayer Commandは、次のPhysical snapshotを作る前にauthoritativeな設定・Project / Order Stateへ適用する。進行中tickの過去phaseをCommandで遡及変更しない。Pause / speedはRuntime schedulingを制御するが、Simulation上の状態変化はcanonical boundaryで確定する。

```text
1. Boundary settlement
   前tickまでの経過によって到着・完了条件を満たしたCargo、Movement Execution、Project、
   Market Provider availability / replenishment、成熟したBuy Commitment等を確定する。
   Cargo arrival / arrival waiting、成熟Buy Commitment等の既に発生済みの物理的obligationがCargo Handling、
   Conditioning、Inventory Admission等の有限constraintを必要とする場合は、通常Activityと同じconstraint key、
   Activity Priority、同順位fairness semanticsを使うBoundary obligation allocationとして先に解決する。
   成立した量だけhandoff / admission / Resource ownership transferと対応Funds消費をatomicにsettleし、
   成立しない量はarrival waitingまたは外部側commitmentとして保持する。

2. Physical snapshot
   on-hand Inventory、既存Reservation、Funds、Market availability / commitment、Environment、
   Facility / Fleet状態、Installed / Active Capability、Nominal Service Capacity、
   利用可能Stock / Pool headroom等の当日配分前状態を固定する。
   Boundary obligation allocationが当日に消費したService Capacity / admission headroomはここで残余量へ反映し、
   後続の通常Allocationが同じcapacityを再利用しない。

3. Intent generation
   各DomainがActivityごとのExecution Requirement Bundle、Supply Requirement、Project work、
   Research / Survey / Exploration intent、Trade Order需要等を生成する。

4. Planning
   Supply Requirement、Target Stock、在庫、Inbound Cargo、end-to-end latency、
   Transport Capacity、Player sourcing / path Policyから当日dispatch量とsource / path候補を求める。
   Service supplyがResource、Fleet、Power、Maintenance、上流Service等を必要とする場合は
   provider dependencyとして明示する。

5. Allocation
   Resource、Fleet、Service、Stock / Pool admission、Transport Capacity等の依存関係を
   一つの決定論的allocation graphとして解決する。
   Activity Priorityは5段階のordinal bandとして高いbandから解決し、
   同一band内の連続量Bundleはnormalized fulfillmentのprogressive max-minを基本とする。
   Trade Order間の有限Market supply / demand競合も同じPriority semanticsを使うが、
   Fundsを一般Execution Requirementへ混在させない。BuyのFunds / provider supply reservationは
   Market DomainのBuy Commitmentとして所有する。SellはInterface在庫のResourceRequirementと
   provider demand constraintを同じexecution量へ結合し、他用途とのInventory二重利用を防ぐ。

6. Domain execution
   Production、Extraction、Maintenance、Construction、Research、Exploration、Survey、
   Decommission / Retirement work等を確定したfulfillmentだけで進行する。
   MarketではAllocation済みbuy reservationからBuy Commitmentを生成し、Interfaceへ実際に提示済みの
   Sell Resourceは割当済みprovider demandの範囲でownership transferとFunds加算をsettleする。

7. Logistics / movement progression
   割当済みResourceとTransport Capacityの範囲でCargo Flowをdispatchし、
   進行中Cargo / one-shot Movement Executionを1 game day進める。

8. State transition / derived refresh
   Technology Unlock、Project completion、Founding、Asset removal等の状態遷移を確定し、
   派生Query状態を再導出してtickを進める。
```

Boundary settlement後のPhysical snapshotを当tick配分の物理的な正本とする。前tickまでに到着したCargoはBoundary settlementでhandoff / admission判定された後にsnapshotへ反映する。到着済みCargoは過去tickですでにdispatchされた物理的義務であるため、当日Productionより先にadmissionを試みる。ただし専用の無制限pre-passとして処理せず、同じ有限constraint modelを使うBoundary obligation allocationで競合を解き、その使用量を当日capacityから控除する。入庫できない量はLogistics-owned arrival waitingに残し、Storageへ荷卸し済みResourceはInventoryだけがauthoritative ownershipを持つ。

Market buyでは前tick以前に成立してlead timeを満たしたBuy CommitmentだけをBoundary settlementの対象とする。lead timeが0でも当tick snapshot後に新規作成したCommitmentを同tickの過去Boundaryへ遡及させない。Market sellではInterface所在Nodeにsnapshot時点で実際に存在する取引可能なPlayer Resourceだけを対象とし、そのResourceRequirementとprovider demand constraintを同じActivity executionとして当日Allocationへ参加させる。Domain executionでは確定量のownership transferと対応Funds加算をatomicにsettleする。成立しなかったResource / Funds / availabilityを消費した扱いにしない。

Planningで選ばれた発送元Resourceもsource側RequirementとしてAllocationへ参加させ、同じInventoryを現地実行と輸送が二重消費しない。Local Production / Extraction等が同じStorage / Pool headroomへoutputする場合は、output admissionをExecution Requirement Bundleの比例Requirementとして共通Allocationへ参加させ、各Domainが同じ空き容量を独立に全量利用しない。

当tickのexecutionやmovementで新たに生産・到着・完了したResource、Capability、Service Capacityや、Market sellで新たに加算されたFundsはallocation graphのrootへ戻さず、次tickのBoundary settlement後snapshotまで新しいAllocationへ利用しない。同tick dependency graphに循環があるContent / DefinitionはConfiguration Validationでfail-closedとする。

通常速度、高速進行、Offline Progressは同じ1 game dayのcanonical semanticsを利用する。複数tickを一括処理する最適化は、日次tickを逐次実行した場合と同じStateへ到達する区間に対してだけ利用できる。正のdurationはcanonical tick境界へ正規化し、通常進行・高速進行・Offlineで完了日が変化しないようにする。

## 4. DefinitionとStateの分離

静的Definitionと可変Stateを分離する。

例：

```text
FacilityDef
  id
  display_name
  placement_scope: OPERATIONAL_NODE | SURFACE_CELL
  installation_requirements
  operating_requirements
  capability_supplies
  service_capacity_supplies

FacilityState
  entity_id
  definition_id
  operational_node_id
  site_cell_id?
  level
  lifecycle: NORMAL | DECOMMISSIONING
  paused
  allocation_priorities
```

同様にVehicle、Transport Allocation、Research、Scientific Exploration、Survey、Construction Recipe等でもDefinitionと可変Stateを分ける。

Vehicle Definitionは性能と製造・整備要件を持つ。通常運用するVehicleは同一Definition・所在Operational NodeごとのFleet Stateとして数量管理し、輸送、Scientific Exploration、再配置、回収中等の排他的配分をFleet Domainが所有する。

Technology UnlockはResearch DefinitionやFacility Stateへ複製せず、一つのTechnology Stateをauthoritative stateとする。Operational ExperienceもResearch Project個別の経過時間として重複保持せず、experience categoryごとのKnowledge Stateを正本とする。

`WorldDefinition` はStar System、Celestial Body、Surface Cell topology、static geology / Resource Potential、基準Physical Environment等の静的世界を構成する。`ScenarioDefinition` は開始時Operational Node / Surface Location、Facility、Fleet、Inventory、Knowledge / Technology、Funds、Market Provider State / Market Interface等の初期Stateを構成する。World Definitionの構築自体がPlayer-owned Operational Stateを生成しない。Scenarioはnew game生成時だけ適用し、Save Load時に再適用しない。

Movement Plan候補、Transport Service Plan、Transport Capacity、Projected Material Readiness、ロケーション産業自立・外部依存分析等は、保存済みStateとDefinitionから導出する派生状態とし、Save上の独立した正本にしない。

静的DefinitionはSaveへ複製しない。

---

## 5. Spatial / Operational Node / Environment / SiteRequirements

### 5.1 Star System / Celestial Body / Surface Cell / Spatial Node / Operational Node

物理的位置を表すSpatial modelと、経済・産業Stateを所有するOperational Nodeを分離する。Spatial modelは多数の天体、小惑星、将来の別恒星系を同じ契約で扱えるよう、Star Systemとその内部Spatial contextを持つ。

```text
StarSystemDef
  id
  interstellar_transport_geometry

CelestialBodyDef
  id
  star_system_id
  parent_spatial_context?
  system_local_transport_geometry
  ...

NonSurfaceSpatialNodeDef
  id
  star_system_id
  parent_spatial_context?
  system_local_transport_geometry
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

`system_local_transport_geometry` は瞬間的な天体位置の時系列そのものではなく、任意二地点間Movementのcharacteristicな空間関係を一貫して導出するためのSpatial Definitionとする。別Star System間はStar System側のinterstellar transport geometryを利用する。具体的なMovement time、Payload、Resource消費はSpatialだけでは決めず、Movement OperationとVehicle性能を組み合わせて導出する。

地表を `SurfaceCell` graphとして表現する。UIはヘックス主体で表示してよいが、Coreは完全六角格子、同一Cell面積、常時6隣接を仮定しない。Celestial BodyごとにCell数を変えてよい。

Surface CellはInventory Nodeではなく、Facility一般の配置スロットでもない。資源、地形、可変Environment、Survey Knowledge、Surface Location開発領域の物理単位とする。

軌道・Lagrange領域・深宇宙上の運用位置等は `NonSurfaceSpatialNodeDef` として物理contextを表現できる。Spatial NodeだけではInventoryやFacilityを所有しない。

`OperationalNodeState` はInventory、Storage、Facility、Fleet、Power、Service Capacity、物流接続等の一般的な運用Stateの所有先とする。Operational NodeはSurface Locationまたはnon-surface Spatial NodeのSpatial contextへ結び付く。

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

Surface LocationのCell数はOperational Node数を増やさない。Inventory、Fleet、通常Facilityの主要所有単位はOperational Nodeのままとする。

すべてのSpatial NodeをOperational Nodeへ昇格させない。未開発Surface Cellや単なる軌道位置はFounding / Mission等の物理targetにはなれても、通常Inventory / Logistics Nodeにはならない。

### 5.2 Environment

Surface Cellは静的地質・地形と可変Physical Environmentを分離する。Static geology / Resource Potentialを通常の採掘で消費・減少させない。Dynamic Physical Environmentはテラフォーミング、自然変化、明示的な地表改変等によって更新可能とする。

Physical Environmentのfield definitionはscope / compositionを明示し、少なくとも `BODY_GLOBAL`、`SURFACE_CELL_LOCAL`、`BODY_WITH_CELL_OVERLAY` に相当する意味を表現できるようにする。Resolverは個別field名のallowlistでscopeを決めず、このDefinition contractからCelestial Body global stateとSurface Cell local stateを評価・合成する。Surface Locationそのものには単一の代表Physical Environmentを持たせず、`core_cell_id` をEnvironment lookupのfallbackにしない。Location向けEnvironment表示はdeveloped cellsの範囲・extrema・分布等から作るderived summaryであり、Simulation判定の正本にはしない。

Non-surface Operational Nodeは結び付いたSpatial contextのPhysical Environmentを評価する。Surface Location上のOPERATIONAL_NODE FacilityはBody-globalなPhysical Environment、Spatial classification、Infrastructure Capability / Service Capacityを利用できるが、Cell-localな日照・地形・局所温度等を暗黙の代表Cellから取得しない。Cell-localな物理条件が必要なFacility / Operationは明示Surface Cell contextを要求する。

与圧、温調、放射線遮蔽等の人工運用環境はPhysical Environment Stateを書き換えず、Infrastructureが供給するCapability / Service Capacityとして表現する。

### 5.3 SiteRequirements / Capability / Service Capacity

Facility設置・運転、Research Prototype / Demonstration、Movement Endpoint、Location設立・拡張等の可否は共通SiteRequirementsを利用する。SiteRequirementsはSpatial classification、Physical Environment、Capability、Service Capacity等の異なる条件を型として分離し、「surfaceである」ことをSurface Environment Facetで代用しない。

`Capability` はcategoricalな資格・機能を表す。Requirement側でInstalled / PresentとActiveを区別できる。量として競合するPower、Construction work、Cargo Handling、Survey rate、Research execution等は `Service Capacity` として扱う。

`ServiceCapacity` はservice type、scope、Nominal、Available、Allocated、Spareを持てる。scopeは少なくとも `OPERATIONAL_NODE` と `ORGANIZATION` を表現できる。NominalはPhysical snapshotに固定する配分前supplyであり、Power、Maintenance、Resource、Fleet、Physical Environment、上流Infrastructure / Service等への依存をPlanningでprovider dependencyとして公開する。

Organization-scope Service Capacityへ供給するproviderも、所在地でローカル依存条件を満たしたAvailable supplyだけを集約する。Research Theory等のconsumerはOrganization scopeを要求できる一方、Prototype / Demonstration、Cargo Handling等は明示Execution Site / Operational Node scopeを要求する。

### 5.4 Location development / Surface Infrastructure

Surface Locationは隣接Surface CellをDevelopment Projectで取り込む。Cell数に固定上限を設けず、Survey、Resource、Construction Service Capacity、時間、地形・Physical Environment、Surface Infrastructure等を要求する。

Location内部で個別ResourceをCellごとにroutingしない。ただし共通Inventoryによる内部移動を無償・無限とも扱わない。位置依存Facility / InfrastructureはSurface Cell上に `Surface Access Anchor` を供給できる。開発Cellから利用可能anchorまでのgeometry、領域規模、利用する遠隔Resource Opportunity、Gateway connection等からLocal Distribution / Surface Infrastructure demandを集約する。Local Distribution、Cargo Handling、surface access等が別の有限能力として意味を持つ場合は独立service typeとして表現し、Surface Infrastructureを一つの万能fulfillment係数へ固定しない。

`core_cell_id` はLocation設立起点とdeveloped-cell連結性のanchorであり、Environment、Movement、Resource Opportunity、Local Distributionの代表地点ではない。core cell自体に無料capacityや距離0特権を付与しない。設立Packageがcore cellへGateway / Distribution Hubを展開する場合も、そのFacilityがActiveなためaccess anchorになる。

Surface Access Anchorが停止・撤去される場合、依存するderived loadは残る有効anchor集合から再導出する。必要anchorが存在しない活動はblockerを持ち、core cellへ暗黙fallbackしない。

近接地域への別Location設立はCoreで禁止しない。新Locationは独立Operational NodeとしてFounding、Inventory、Storage、Power、Construction、Gateway / access、拠点間物流等の固定費を要求する。同じSurface Cell、Resource Opportunity、Service CapacityをLocation分割で複製しない。

## 6. Facility / Maintenanceモデル

### 6.1 設置と運転

Installation RequirementsとOperating Requirementsを分離する。どちらもSiteRequirementsとしてSpatial classification、Physical Environment、Capability / Service Capacity等を組み合わせ、先行建設や将来の環境変化をLocation特例なしで扱えるようにする。

Facilityは同一Domainのまま配置種別を持つ。

- `OPERATIONAL_NODE`: Operational Nodeへ所属し、個別Surface Cellを指定しない通常Facility。Surface Locationとnon-surface Operational Nodeの双方へ配置できる。同じOperational Node内でCellを変えても局所Environment、Movement接続、性能、効果が変化しないFacilityはこちらを基本とする。
- `SURFACE_CELL`: 物理的位置が性能、Movement接続、局所Environment、環境改変等へ本質的に影響する位置依存Facility。

`SURFACE_CELL` Facilityだけ `site_cell_id` を要求し、所属Operational NodeはSurface Locationでなければならず、対象CellはそのLocationの開発済み領域でなければならない。別のSurface Installation Domainを作って建設・維持・Power・Capability / Service Capacityを重複実装しない。

ApplicationはOPERATIONAL_NODE FacilityのBuild OptionでCell選択を要求しない。SURFACE_CELL FacilityはMap上の候補Cellと可否・blockerをQueryし、空間操作として配置する。

### 6.2 Pause

PauseしてもFacilityは消滅しない。通常運転に伴うProcess、生産、採掘、発電、建設、Research、Survey等のService Capacityは停止する。Active Capabilityも運転を必要とするものは無効になるが、物理的なInstalled Capabilityまで失われたことにはしない。

一方、安全維持・保冷等のstandby loadと物理的維持要件は通常Pauseだけでは消滅しない。当tickに必要な維持Execution Requirementと、その維持を継続するためのSupply Requirementは残る。将来のMothballはPauseとは別状態とする。

### 6.3 資材維持需要

Facilityは建造・Upgrade時に実際に投入されたResourceを基礎に維持需要を持つ。

```text
maintenance_demand(resource, period)
= cumulative_invested_resource × maintenance_fraction(period)
```

維持率はContent Definitionのバランス値とする。維持資材は特別な税処理ではなく通常Resourceとして扱う。当tickの維持実行はExecution Requirement Bundle、将来の補充はSupply RequirementとしてInventory / Logistics契約へ接続する。

割当済みmaintenance executionが不足した場合はFacilityを即時破壊せず、maintenance fulfillmentを0..1で算出し、Service Capacity、生産率、Research Point生成等へ共通係数として反映できる構造を基本とする。categorical Capabilityの有無と、現在供給可能な量を同じ数値で表さない。

### 6.4 Decommission lifecycle

Facility lifecycleは少なくとも `NORMAL` と `DECOMMISSIONING` を区別する。Decommission Projectの計画・work allocationはConstruction系の共通Project能力を利用できるが、Facility lifecycle stateの所有者はFacility Domainとする。

不可逆な解体開始前は取消可能とし、開始後はFacilityを通常operationへ戻さない。`DECOMMISSIONING` Facilityは通常のProcess、Active Capability、Service Capacity supply、Storage admission等の新規Activity向け能力を停止する。既存stockや開始済みcommitmentを安全にsettleするため解体中にも残す必要がある受動能力だけはFacility Definitionが `retained during decommission` に相当する明示契約として定義できる。その保持能力は安全settlement専用であり、新規ActivityのCapability / Service / admission supplyへ数えない。既に開始済みで、そのFacilityの現存を前提に安全にsettleする必要がある不可逆commitmentを破壊する場合はDecommission開始をblockする。一方、将来の反復Process、Transport Allocation等が能力へ依存するだけなら、それらは撤去後に通常blockerを持つ状態として残せるためDecommission blockerにはしない。

Storage Facilityは、不可逆解体開始後も安全保持用として明示的に残る容量を除いた残存Physical Storage Capacityが現在stockを下回る場合、Inventoryを消去・宙づりにせずDecommission開始をblockする。Usable Capacity低下による既存over-capacityとは区別する。

Decommission completionはFacility参照を原子的に整理し、Facilityをlive stateから除去する。完了済みConstruction / Upgrade履歴は対象Facilityの現存を要求しない。回収Resourceは通常Inventory Admissionを通し、撤去対象Facility自身が供給するStorage Capacityをsalvage受入headroomとして利用しない。回収Resourceを失わずにadmissionできない場合は最終removalをsettleせず、Projectを完了待ちとして保持する。

---

## 7. Inventory / Allocation / Storage / Power

InventoryはOperational Nodeごとの所有Resourceを表す。on-hand、Reservation、利用可能量、入庫・出庫flowを所有し、Logistics-ownedの輸送中Cargoやarrival waitingとはauthoritative ownershipを分離する。Application QueryではInventoryとInbound / outbound Cargoを統合表示してよいが、同じResource量を二つのDomain Stateへ重複保存しない。

Storageはある時点で保持できるstock上限として `Physical Storage Capacity` と `Usable Storage Capacity` を区別できる。Usableは電力・温調等の成立条件を反映して現在安全に保持できる量の上限であり、一定時間あたりのService Capacityではない。荷役・温調処理量等を有限flowとして競合させる場合はCargo Handling / Conditioning等の別Service Capacityとして定義する。

PowerはOperational NodeごとのService Capacityとし、他の有限capacityと同じActivity Priority / Allocation契約を利用する。

### 7.1 PriorityLevel

共通Priority型を次の5段階とする。

```text
PriorityLevel
  1 LOWEST
  2 LOW
  3 NORMAL
  4 HIGH
  5 HIGHEST
```

既定値は3とする。PriorityLevelはallocation weightではなくordinalなpriority bandである。Allocationは高いbandから順に供給を確定し、同一band内の競合を公平かつ決定論的に解決する。Pause / inactive等の状態はPriorityLevelから分離する。

`Activity Priority` はProcess、Construction、Research、Maintenance、Supply Requirement、Target Stock等が既存Resource / Service / Transport Capacityを競合利用するときの優先度を表す。同じroot activityを成立させるRequirementはActivity Priorityを継承する。

`Provisioning Priority` はFleet等の有限資産を複数Transport Allocationへ配備する場合の優先度を表す。需要側のActivity PriorityがProvisioning PriorityやTransport Allocation targetを暗黙変更しない。

### 7.2 Execution Requirement Bundle

同一tickの一単位executionに対して複数のResource、Service、Stock / Pool admission等が同時かつ比例して必要な場合は `ExecutionRequirementBundle` として提出する。

```text
ExecutionRequirementBundle
  owner_intent
  requested_execution
  priority
  requirements[]
    ResourceRequirement(scope / operational_node_id)
    ServiceCapacityRequirement(scope / site?)
    PoolRequirement(scope)
    StockOrPoolAdmissionRequirement(scope / operational_node_id)
  minimum_execution?
  atomic?
```

Bundle自体を必ず一つのOperational Nodeへ固定しない。各Requirementが必要なscope / siteを明示し、Organization-scope Research executionとOperational Node-scope Resource / Service requirement等を同じbundleで一貫して表現できるようにする。ただし一つのexecutionが物理的に一地点で行われる場合はExecution Siteをowner intent側で明示し、無関係なNodeのlocal capacityを混用しない。

Bundle fulfillmentは構成Requirementが共通して成立できるexecution量として決める。Allocationで確定したexecution量に対応するRequirementだけをsettleし、あるResourceだけ100%消費した後に別Service不足で40%しか実行できない状態を作らない。

FundsはResource Market settlement専用Stateであり、一般Execution Requirementへ含めない。

Facility / Capabilityの存在、SiteRequirement、長期Reservation、既に確保済みStock、Fleet配置等の開始条件・保存状態・capacity provisioningはそれぞれの所有Domain契約として評価する。

Production / Extraction / Research Point生成等でoutputをStock / Poolへ追加する場合、そのexecutionに必要なadmission headroomを`StockOrPoolAdmissionRequirement`としてBundleへ含める。複数Producerが同じStorage / Pool空き容量を二重利用しない。

同一Priority band内の連続量Bundleは、共有constraintに対するnormalized fulfillmentをprogressive max-min方式で解決する。minimum / atomic要求は永続Intentのfairness ageとstable keyで決定論的にadmissionし、transient Claim生成順をfairnessの正本にしない。

### 7.3 Reservation / commitment

長期Project等で既に物理的に確保済みのResourceはInventory Reservation / commitmentとしてExecution Requirementと分離する。Execution Requirementを暗黙の永続Reservationへ変換しない。

Project等がon-hand Resourceを将来実行用に段階的に確保する場合は、`ReservationAcquisitionRequirement` をActivity Priority付きでAllocationへ提出する。割当済み量だけをavailable stockからreserved stockへ移し、Reservationは以後のtickでもauthoritative Stateとして保持する。複数tickにまたがる資材蓄積はこの契約を利用する。

将来必要量を表すSupply RequirementもReservationではない。将来必要であるというPlanning情報だけではon-hand Inventoryを他用途から排除しない。Project Domainが到着済みResourceを確保する必要がある場合にだけReservationAcquisitionRequirementを生成する。

### 7.4 Inventory Admission / over-capacity

Operational Nodeへ物理Resourceが増加するすべての経路は共通Inventory Admission契約を利用する。Industry output、Extraction output、Cargo unloading、Market buyによるownership transfer等を同じStorage class / Physical / Usable Capacity契約へ接続する。

Local executionからのoutput admissionはExecution Requirement Bundle内のStock admission requirementとして当tick Allocationへ参加する。すでに過去tickでdispatchされて到着したCargoはBoundary settlementで先にadmissionを試み、入庫不能量はarrival waitingとしてLogistics側へ残す。

Usable Storage Capacityが既存stock量を下回った場合は既存在庫を即時消去せずover-capacity stateとして保持する。新規admission可能量、必要Conditioning、blocker等をApplicationへ公開する。

## 8. Industry / Extractionモデル

### 8.1 Process

FacilityそのものとProcessを分離する。Processはinputs、outputs、基準処理能力、電力等を持つ。

Application Queryは設備ごとの選択Process、実効inputs / outputs、稼働率、limiting factorを返す。UIは「何を消費して何を作るか」をFacility画面から直接確認可能にする。

### 8.2 資源・能力競合

Processは一単位executionに必要なResource input、Power、Process Service、output Storage admission等をExecution Requirement Bundleとして提出する。Industryだけの独自先着配分を持たず、Maintenance、Research、Construction等と同じAllocation契約で競合する。

Allocation結果として確定したexecution fulfillmentだけProcessを進め、そのexecution量に対応するinputを消費し、許可済みadmission量の範囲でoutputを生成する。Application Queryはrequested execution / allocated execution / fulfillmentとlimiting factorを返す。

### 8.3 Extraction / Resource Potential

有限 `Deposit remaining` を採掘の正本にしない。地表資源はSurface Cellごとの静的 `Resource Potential` と、Locationに設置された採掘Facilityが供給するNominal Extraction Capacityから継続的なThroughputを導出する。

Resource Potentialは残量、Facility slot数、固定最大`t/day`のいずれでもなく、追加採掘能力をどの程度高い限界生産性で利用できる地域かを表す。Cell面積が天体間・Cell間で異なる可能性を考慮し、PotentialはCellの面積・地質を含んだ機会量として扱えるようにする。各developed Surface Cellについて、Static PotentialにそのResource / extraction methodに関係するPhysical Environment・地質accessibilityを適用して `Cell Effective Opportunity` を導出し、それらをLocation単位へ集約する。

```text
CellEffectiveOpportunity(cell, resource, method)
  <- static Resource Potential
  <- current Physical Environment
  <- geological / terrain accessibility

EffectiveOpportunity(location, resource, method)
  <- developed cellsのCellEffectiveOpportunity集約
```

採掘Facilityを個別Cellへ配置しない場合でも、このcell-wise opportunity集約によって局所的な永久影・温度・地質差等を反映できる。Facility自身の物理位置が採掘性能へ本質的に影響する方式だけSURFACE_CELL placementを要求する。

Surface Infrastructure / Local Distributionの有限能力はResource Opportunityへ重ねて係数適用せず、Extraction executionのService Requirementとして一度だけAllocationへ反映する。core cell分のOpportunityだけを無条件にDistribution不要とする特例を作らない。Survey Knowledgeは物理Throughputを変化させる係数ではなく、プレイヤーへ公開する推定値・候補・blockerを決める知識状態として分離する。

Installed Nominal Extraction Capacityに対する実効Throughputは次の一般契約を満たす。

- Installed Capacity増加に対して総採掘量は単調非減少。
- 同じOpportunityに対する限界増産量は逓減する。
- Facility数のハード上限をResource Potentialから直接導出しない。
- 通常採掘でStatic Resource Potentialを減少させない。
- 研究完了だけで既存FacilityのNominal Capacityを変更しない。

研究は新しいFacility Definition、Process、Construction / Modernization手段を解禁する。Throughput上昇には実際のFacility建設・Upgrade・更新が必要となる。初期地球産業等は開始時から高いResource Knowledgeを持つSurface CellをContentとして定義できるが、Earth等の固有名へのCore特例は作らない。

### 8.4 ロケーション産業自立・外部依存Analytics

ロケーション産業自立は保存Stateや特定天体固有のフラグではなく、Production、Consumption、Supply Requirement、Import / Export、Unmet Requirementから導出するAnalyticsとする。

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
  target definition / work kind
  resources: 2..3 kinds where construction consumes material
  construction_work
  site_requirements
  prerequisite_technologies
```

Construction workはFacility建設・Upgradeだけでなく、Facility Decommissionの解体workにも共通のService Capacity / Project schedulingを利用できる。ただしFacilityの生成・Level・DECOMMISSIONING・removalというlifecycle transition自体はFacility Domainが所有し、Construction DomainがFacility stateを直接削除しない。Decommission recipeは投入Resource数2〜3という建設用制約を必須とせず、必要work、補助Resource、salvage definitionをContentとして定義できる。

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

Construction系Projectはtarget kindを明示し、Build / Upgrade / Decommission等の異なるlifecycle intentを同じProject Schedulingへ接続できる。Build / Upgrade Projectは少なくともOperational Node、進捗、Resource commitment / Reservation状態、sourcing constraint / policy reference、Activity Priority、pause状態を持つ。Projectが開始条件として複数tickにまたがる資材確保を必要とする場合はReservationAcquisitionRequirementで段階的にReservationを形成する。SURFACE_CELL Facilityだけは追加で配置Cellを持つ。Decommission Projectは対象Facility Entityを参照し、Facility Domainが公開する開始可否・不可逆境界・completion transitionを利用する。

Projectは通常物流のsourceや各Leg、Transport Serviceをauthoritative stateとして所有しない。現在のconstruction executionに必要なResource / Construction Service等はExecution Requirement Bundleとして生成する。Project進行から予測できる将来資材必要量はstableなSupply RequirementとしてLogisticsへ公開し、Project進捗が変化すればremaining quantity / forecast requirement timeを更新する。

PauseとCancelを分離する。

### 9.5 Location founding / development

既存Locationの隣接Surface Cell開発は、Resource・Construction Service Capacity・時間・SiteRequirementsを消費する通常のDevelopment Projectとして扱う。既存Location拡張では原則として現在のdeveloped cell集合へ隣接する未所属Cellだけを対象とする。

最初の地表Location設立は、対象Locationがまだ存在せずDestination Inventoryも通常Logistics Endpointも持てないため、通常Build Projectとは別のFounding Deployment Projectとして扱う。

```text
LocationFoundingProject
  staging_node_id
  target_body_id
  target_core_cell_id
  founding_package_id
  prepared_manifest / commitments
  deployment_movement_requirement
  preparation_work
  priority
  status
```

Founding Package Definitionは設立に必要なdeployable manifestと、到着後にどの初期Facility / Inventory / Fleet / Storage等へ展開されるかを定義する。staging nodeで実Resourceや対象Fleetを実際に準備し、dispatch時にsource側StateからDeployment Movement Executionのpayloadへ移す。成功時にはそのpayload / manifestから新Surface Locationと対応Operational Nodeの初期Stateを一度だけ生成する。Package Definitionを理由にtarget側へ物理ResourceやFleetを追加生成しない。

Location設立前のtarget Surface CellはDeployment Movementの物理endpointにはなるが、Inventory Nodeや通常Logistics Nodeにはならない。Landing / descent / access等のOperation要件はMovement ResolverがVehicle実性能とtarget Environment / SiteRequirementsから判定する。

成功後は生成されたOperational Nodeを通常Inventory / Facility / Logistics契約へ接続する。Location developmentはFacility建設とは別の地理的投資であり、通常FacilityのCell配置へ読み替えない。

---

## 10. Movement / Transport / Logistics / Vehicleモデル

Spatialは二地点間の物理的関係、Movementは移動の成立条件と結果、TransportはFleet / Infrastructureから反復可能なcapacityを供給する責務、LogisticsはSupply Requirementを満たすResource flowを計画する責務を持つ。通常物流で個体Vehicle Missionを反復生成しない。

### 10.1 Spatial Relation / Movement Plan

通常Movementの二地点関係をOD別の静的Route Definitionとして保存しない。Movement Resolverはorigin / destination Endpoint、Spatial Relation、利用可能Operation、Vehicle性能、InfrastructureからMovement Plan候補を導出する。

```text
MovementEndpoint
  operational_node_id?
  locator:
    surface_interface_id | access_cell_id | non_surface_interface | physical_target

SpatialRelation
  origin_spatial_context
  destination_spatial_context
  characteristic_geometry / separation
  origin_endpoint_conditions
  destination_endpoint_conditions
  movement_context

MovementPlan
  origin_endpoint
  destination_endpoint
  operations[]
  vehicle / movement requirements
  payload characteristics
  latency
  resource / servicing requirements
  endpoint requirements
```

Movement Operationには必要に応じてPowered Ascent、Spaceflight、Landing、Atmospheric Entry、Surface Transport等を利用する。Delta-v、Thrust、Endurance、Atmosphere、Gravity、Landing、Docking / Refueling Infrastructure等は適用可能なOperationの評価入力として利用できる。Launch Vehicle / Spacecraft / Lander等の名称は表示に利用できるが、可否判定には使わない。

Surface LocationではCore Cellや代表座標をMovement距離の固定正本にせず、実際に利用するGateway / access interfaceとSurface Cell geometryをEndpoint条件へ反映する。Location拡大によって開発圏やGatewayが接近した場合、新しいEndpoint geometryからMovement Planを再導出できる。

Surface Cell自体を通常Transport Capacity Network Nodeにはしない。Location設立前だけは `physical_target(surface_cell_id)` をFounding / Deployment等のone-shot Movementで利用できる。

Movement Planはauthoritative StateではなくSpatial / Facility / Definitionからの派生結果である。同一physical state内では、全候補、OD別候補、Plan ID参照等が同じ導出結果を再利用できる索引をTransport Domainが保持してよい。Plan ID参照のたびに全Operational Node pairを再列挙する方式をQuery契約にはしない。Spatial topology、Movement Endpointを構成するFacility、その他Plan内容へ影響するphysical stateが変化したときだけ派生索引を無効化し、必要時に再導出する。派生索引はSave対象にしない。

### 10.2 Vehicle Definition / Fleet State

Vehicle DefinitionはMovement適合性、Payload、Propellant、Endurance、Operation interface、turnaround / maintenance、Production Requirement等の性能・物理要件を持つ。Funds costはVehicle Definitionの一般運用・製造要件に含めない。

通常Vehicleは個体Entityではなく、同一Definition・所在Operational Nodeごとの `FleetPool` 数量として管理する。Fleet Domainは総数と、Transport、Scientific Exploration、Relocation、Release、Retirement等の排他的commitmentをauthoritativeに所有する。

Vehicleは地球外を含む任意Operational NodeでProduction requirementsを満たせば建造でき、完成unitはそのNodeのFleetPoolへ追加される。別Nodeへの配置換えはFleet Relocation / Movement Executionを通して物理的に移動し、sourceから減少したunitは到着完了までdestinationへ存在しない。

個体ごとの耐久、固有改修、履歴等が主要Stateにならない限り恒久Vehicle Entityを導入しない。個体差が必要になっても、同一状態のunit群をcohortとして表現できる場合はFleet集約を維持する。

### 10.3 Vehicle Production / Retirement / one-shot Movement Execution

Vehicle ProductionはOperational Nodeを実行地点として持ち、必要Resource、Production Capability / Service Capacity、SiteRequirements、時間を満たして進行する。完成時にそのNodeのFleetPoolへunitを追加する。

Fleet RetirementはTransport / Fleet Domainが所有する永続Intentとする。retirement対象unitは所在Operational Nodeのfree Fleetから排他的にreservationし、所在Nodeで通常のService Capacity / Resource Requirementとして表現されるworkを経て完了時にFleet総数を減らす。Fleet Core専用の特殊解体capacityを必須にせず、Contentは既存のVehicle Production / workshop系Serviceを再利用できる。独立解体設備が戦略的に意味を持つ場合だけ通常Service typeとして追加する。不可逆な解体開始前は取消可能、開始後は対象unitを他用途へ解放しない。salvage量はVehicle Definitionのretirement recovery定義とunit数から導出し、outputは通常Inventory Admissionを通す。回収Resourceをadmissionできない場合は対象unitをRetirement commitmentに保持し、Fleet総数減少とsalvage admissionを同じ最終settlementで確定する。

Fleet Relocation、Scientific Exploration等の有限操作はone-shot Movement Executionを利用し、開始時にFleet unitをsourceのfree poolから外し、完了時に定義されたdispositionへsettleする。in-transit unitをsource / destination Fleetへ同時に計上しない。

### 10.4 Transport Allocation / Transport Service / Capacity

プレイヤーはVehicle type、origin / destination関係、Movement / operation Policy、Provisioning Priorityを指定してFleetをTransport Allocationへ配分する。Transport Allocationは次のどちらか一方をauthoritative targetとして持つ。

- `UNITS`: 目標Fleet隻数を指定し、輸送能力を導出する。
- `CAPACITY`: 方向別の目標定常capacityを指定し、Nominalな1隻当たり能力から必要隻数を導出する。

Provisioning Priorityは1〜5、標準値3とする。CAPACITY modeのFleet必要数には一時的な燃料・整備不足を反映させず、不足を埋めるための自動増員を起こさない。Fleet不足でtargetを満たせないAllocationは有効な設定として保持し、free Fleetが増えた場合はProvisioning Priorityに従って既存targetまで投入できる。

Transport DomainはAllocationごとに、Cargo輸送後もFleetが反復運用可能な状態へ戻るMovement、recovery、turnaround、refueling、servicingを組み合わせてTransport Service Planを導出する。Service Planから方向別Transport Capacityを導出し、Target、Nominal、Available、Used、Spareを区別する。

往復Serviceは同一cycleが両方向を担当するため、方向別capacityを加算してFleet負荷を二重計上しない。推進剤・servicing等の可変運用需要はAllocation最大値ではなく実際のService利用率から発生させる。

Transport Service Planとcurrent Capacityはderived stateとし、Fleet / Infrastructure / Definitionから再導出する。ただしdispatch済みCargo Flowや開始済みMovement Executionが保持するlatency等の実行条件は、そのdispatch / start時点で確定してState化する。

### 10.5 Supply Requirement / Target Stock / Supply Planning

各Domainは将来のResource補充・配置必要量を `SupplyRequirement` として公開できる。

```text
SupplyRequirement
  stable_requirement_id
  destination_node_id
  resource_id
  remaining_quantity?
  expected_consumption_rate?
  forecast_requirement_time?
  priority
  owner / purpose
  optional source constraints
```

Supply RequirementはPlanning情報であり、Inventory ReservationやResource消費そのものではない。Project進捗や継続消費条件によって必要量・expected consumption rate・予測時期が変化した場合は同じstable requirementを更新する。

Target StockはPlayer Policyとして同じSupply Planningへ接続し、Activity Priorityを持つ。

Logistics PlannerはSupply Requirement、Target Stock、現在Inventory、Reservation、Inbound Cargo、end-to-end latency、利用可能Transport Capacity、Player sourcing / path Policyを統合し、当日dispatchを開始する必要がある量・rateをactive shipping demandへ解決する。Activity Priorityが高くても、将来まで十分な余裕があるRequirementは現在必要な低Priority活動を直ちに先取りしない。

発送候補はsource側Execution Requirementと既存Transport Capacity利用Requirementへ解決し、source InventoryやTransport Capacityを現地用途・他需要と共通Allocationで競合させる。Supply PlanningはTransport Allocation targetやFleet配備を変更しない。

### 10.6 Cargo Flow / ownership

通常物流のdispatch済みResourceはsource Inventoryから減算し、Logistics-owned Cargoとして保持する。同一条件が継続するdispatchはtickごとの個別BatchではなくCargo Flow Segmentとしてまとめる。

```text
CargoFlowSegment
  resource_id
  source_node_id
  destination / next_handoff
  transport_service_identity
  dispatch_start
  dispatch_end
  dispatch_rate
  latency
  activity_priority
```

source、destination、service、latency、rate、priority等の輸送意味論が変化した時点で新しいSegmentを開始し、同じ条件の隣接Segmentは結合可能とする。Cargo State量を経過tick数そのものに比例させない。

Cargo Flow Segmentのdispatch済み部分は、そのdispatch時点のTransport Service条件とlatencyを保持する。後続のInfrastructure / Technology / Fleet変更によって既にin-transitの到着時刻を遡及変更しない。

### 10.7 Arrival / handoff / Inventory admission

Cargoが目的地またはhandoff Operational Nodeへ到着した場合、Cargo HandlingとInventory Admissionを評価する。

別Transport Serviceへdirect handoffできる場合は、必要なtransfer Service Capacityを利用してStorageへ移さずLogistics-owned Cargoのまま次Legへ接続できる。一旦Storageへ荷卸しする場合は、その時点で物理Resourceのauthoritative ownershipをInventoryへ移し、次Leg向けの確保はInventory Reservation / commitmentとして表現する。

荷卸し条件が成立しないCargoはarrival waitingとしてLogistics側に残る。arrival waitingはCargo Handling / arrival holdingの物理制約を消費し、対応するTransport Serviceの再利用可能capacityへbackpressureを与える。個体Vehicleを通常物流へ生成せず、Service Planのpayload / cycleからaggregate occupancyとして扱う。

輸送中Cargoは目的地Storageを事前予約しない。

### 10.8 End-to-End path

通常物流では任意の成立済みOperational Nodeをorigin / destinationとして指定できる。Movement Resolverと現在成立しているTransport Service、Operational Node、Player path Policyからend-to-end pathを導出する。

Spatial hierarchy上の中間context自体は物流handoff pointにならない。同じFleetがCargoを保持したまま複数Movement Operationを連続実行できる場合は一つのTransport Serviceとして扱い、実在するOperational Nodeで別Transport ServiceへResourceを引き渡す場合だけhandoffとなる。

Playerが明示したVehicle / Service / pathが利用不能になった場合は、明示Policyがない限り戦略上異なる方式へ勝手にfallbackしない。

### 10.9 External Resource Market / Funds

Fundsは組織全体のResource売買決済Stateであり、Operational Node Inventoryへ混在させない。`FundsState` は総残高だけをauthoritativeに所有し、利用可能残高はactive Buy Commitmentのreserved Fundsを控除して導出する。FundsをResearch、Construction、Maintenance、Vehicle production / operation、Transport Capacity、一般Service等のExecution Requirementに利用しない。

`MarketProviderDef` はMarket identityとResourceごとのbuy / sell offer価格、有限availabilityのreplenishment rule、必要ならlead timeを定義する。現段階ではoffer価格はDefinition-backedな固定条件とし、`MarketProviderState` は内生的な価格Stateを持たない。有限の現在supply / demand availabilityと、決定論的なrate / interval等のreplenishmentに必要な可変値を `MarketProviderState` がauthoritativeに所有する。Player世界との物理接続はOperational Node上の `MarketInterfaceState` が所有し、Provider能力を他Nodeへ自動的に拡張しない。

`TradeOrderState` はdirection、resource、Market Interface、Activity Priority、price conditionと、`QUANTITY` / `RATE` のcontrol modeを持つ。QUANTITYはtarget quantity、RATEはtarget rateだけをauthoritative targetとし、両方を同時正本にしない。QUANTITYの未達量はremaining targetとして次tick以降へ保持する。RATEは各tickの現在throughput目標であり、そのtickの未達量を翌tickへbacklogとして加算しない。Buyのprice conditionはmaximum buy price、Sellはminimum sell priceとして評価し、条件外offerでは新規commit / settlementを行わない。Order Stateはsettled quantityと未手配・in-flight / presented量を区別できる進捗を持つ。Buyの予約は別の `BuyCommitmentState` がorder_id、resource、unsettled committed quantity、commit時buy価格、reserved Funds、reserved provider supplyをauthoritativeに所有する。同じ予約量をTradeOrderState、MarketProviderState、FundsStateへ重複保存しない。利用可能Fundsとprovider supplyはactive Buy Commitmentを控除して導出する。

Buyでは、maximum buy price条件を満たすOrderに対してFundsとprovider supplyを同じcommitment acquisitionとして競合解決し、両方が成立した量だけBuy Commitmentへ予約する。Fundsだけ、またはprovider supplyだけを片側commitしない。commit時のoffer価格をCommitmentへ固定するため、その後のOrder価格条件変更や市場価格変動は既commit lotの価格を遡及変更しない。provider lead timeが満了し、Market Interface所在Operational Nodeで必要なCargo HandlingとInventory Admissionが成立した量だけMarketからPlayer InventoryへResource ownershipを移し、そのownership transfer、対応Funds消費、commitment減少をatomicにsettleする。commit済み未settled supplyを別Orderへ二重割当せず、取消可能な未settled commitmentはFunds / provider supplyの双方を解放する。

Sellでは遠隔Resourceのためにprovider demandを先行予約しない。Player ResourceをMarket Interface所在Operational Nodeへ通常Cargo / Inventory契約で運び、snapshot時点で実際に取引可能なResourceが提示され、かつminimum sell price条件を満たす場合だけSell executionを共通Allocationへ提出する。Sell executionはInterface在庫のResourceRequirementとprovider demand constraintを同じexecution量へ結合し、Activity Priorityに従って他のInventory用途および他Sell Orderと競合する。確定量だけPlayerからMarketへownershipを移し、Sell価格はownership transfer時点の有効sell offerを適用して対応Fundsをatomicに加算する。TradeOrderStateは未手配量と既dispatch / 提示済み量を区別して二重dispatchを防ぐ。Order変更・取消は既settlementを遡及変更せず、既dispatchのPlayer-owned Cargoを消去・転送しない。Marketへ未到達の遠隔ResourceをFundsへ直接変換しない。

Market InterfaceへのResource輸送はPlayer-owned Fleet / Transport Capacityと通常Logisticsを利用する。External MarketはPlayerへ汎用Transport Serviceを供給せず、Resource取引以外の支出・収入経路を持たない。

## 11. Research Point / Research / Knowledgeモデル

Research Pointは通常貨物Inventoryとは分離し、組織全体の共有Knowledge PoolとしてResearch Stateが所有する。Research ProviderはOperational Node上のFacility / Fleet等のDefinition-backed providerからRP生成量と貯蔵能力を供給できるが、生成したRPをprovider所在地専用pointにはしない。

Research ProviderはTierとLevelを持てる。

- Tier：研究手段の世代差・基礎効率差
- Level：同一世代設備への増設・拡張・改良

Research Provider Tierはprovider Definitionの設備世代であり、Technologyの表示上の研究段階区分とは別概念とする。Technologyの表示段階変更や完了によってprovider Tierを暗黙更新しない。

Research Point storage capacityは有効なprovider群から導出する。容量低下で既獲得RPを消去せず、新規生成を制限する。

### 11.1 Technology State

完了済みTechnology集合は単一のauthoritative `TechnologyState` が所有する。Facility、Process、Vehicle、Movement Operation等はprerequisite technologyを参照するだけで、各Domainへunlock flagを複製しない。

Research DefinitionはTechnology間のdirect prerequisiteをContentとして定義できる。Technology dependency graphはacyclicなDAGとし、研究開始可否は完了済みTechnologyと個別prerequisiteから判定する。表示上の研究段階区分や専門区分を暗黙のprerequisiteにせず、「同段階を一定数完了」「前段階を全取得」等をGeneric Coreの進行条件にしない。

研究段階区分はTechnologyの発展位置を可視化するContent metadataとして扱い、Research Projectの `THEORY / PROTOTYPE / DEMONSTRATION / OPERATIONAL_EXPERIENCE` stageとは別概念とする。段階数は固定上限を持たず、段階1〜4のContentから第5段階以降へDAGを拡張できる。専門区分も表示・探索用metadataであり、dependencyは区分を跨いでよい。Coreは区分ごとの研究数、段階ごとの研究数、特定区分の存在を固定しない。

Content validationは少なくとも、Technology IDの一意性、prerequisite参照の存在、dependency cycle不存在、表示段階の自己矛盾を検証する。表示段階は依存関係を置き換えるルールではないが、後段階Technologyを前提として前段階Technologyを配置する等、可視化された発展方向とdependencyが逆転するContentはvalidation対象とする。

研究技術IDをMovementの直接解除キーにしない。研究は一般化可能な技術的知識・工程・制御方法を表し、実際の到達可否はSpatial Relation・Operation要件・Vehicle性能・Infrastructureから決める。既存Facilityの性能もResearch完了時に暗黙変更しない。

### 11.2 Research Project / stage

Research Projectは複数を並行して進められる。固定の単一global queueを正準仕様にしない。並行性はRP、Research execution Service Capacity、必要Facility / Capability、Prototype Resource、Demonstration条件等から自然に制約する。複数Projectが同じResearch Point PoolやService Capacityを消費する場合はActivity PriorityとExecution Requirement Bundleに従って共通Allocationで配分し、Project登録順を暗黙priorityにしない。

Research Definitionはstageごとにexecution scopeを持てる。

- `THEORY`: `ORGANIZATION` scope。共有RPとOrganization-scope Research execution Service Capacityを利用する。
- `PROTOTYPE`: `OPERATIONAL_NODE` を基本とするExecution Site。必要Resource、Facility、Physical Environment、Capability / Service Capacityを要求する。
- `DEMONSTRATION`: `OPERATIONAL_NODE` または `SURFACE_CELL` Execution Site。研究内容がCell-localな物理条件を要求するときだけSurface Cellを指定する。
- `OPERATIONAL_EXPERIENCE`: Execution Siteを持たず、対応categoryのKnowledge Stateが要求値へ到達することを要求する。

```text
ResearchExecutionSite
  operational_node_id
  surface_cell_id?
```

Prototype / Demonstrationを特定Location IDへ固定せず、SiteRequirementsから候補Siteを判定する。surface_cell_idを持つ場合、そのCellは指定Operational Nodeに対応するSurface Locationのdeveloped cellでなければならない。

Theory用Research executionを供給するproviderも、所在地でPower、Maintenance、Physical Environment等のローカル成立条件を満たしたAvailable supplyだけをOrganization scopeへ供給する。Organization scopeはprovider所在地の制約を消去する仕組みではない。

### 11.3 Operational Experience / Knowledge State

Operational ExperienceはResearch Projectが時間経過だけで生成するpointではない。Transport、Extraction、Manufacturing、Crewed Operation等の実Domain activityが共通interfaceを通じてexperience contributionを報告し、Knowledge Stateがcategoryごとの蓄積を所有する。Researchはこのstateをrequirementとして参照する。

Domainごとに同じExperience値を重複保存しない。Experience categoryはContentで定義でき、特定Location名やVehicle名をGeneric Core categoryへ埋め込まない。

### 11.4 Human operation abstraction

有人運用はcrew-ratedなVehicle / Facility property、Habitation / Life Support等のCapability / Service Capacity、消耗Execution Requirement / Supply Requirement、Environment Requirementから表現する。Crew個人・人口の配置、成長、リスクが独立したプレイヤー判断を構成する場合は、そのState ownershipと状態遷移を独立Domainとして定義する。

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

地質Knowledgeは基本的に恒久的な観測結果として扱える一方、Dynamic Physical Environmentは別Stateとして更新され得る。将来のテラフォーミング等で環境由来の資源利用可能性が変わる場合も、Static Resource Potentialと現在Physical Environmentを分離して再評価する。

完了Campaignは、そのproviderで到達可能な上限まで完了した対象を能力配分対象から外し、余剰Survey能力を未完了対象へ再配分する。より高いKnowledge Levelへ進むには必要に応じて別provider / observation modeを利用する。

科学探査のRP獲得とResource SurveyのKnowledge更新を同一状態機械へ混在させない。

## 13. Command / Query API

### 13.1 Command

主要カテゴリ：

- Time pause / resume / speed
- Surface Location founding deployment / adjacent Cell develop
- Build / Upgrade / Cancel / Pause / Resume / Facility Decommission
- Surface-cell Facility placement where required
- Facility pause / resume / process
- Activity Priority set (1..5)
- Vehicle produce / Fleet relocate / Fleet Retirement
- Transport Allocation create / update / pause / resume / delete
- Transport Allocation UNITS / CAPACITY target / Provisioning Priority set
- Target Stock set
- sourcing / path policy set
- External Resource Market Buy / Sell Trade Order create / update / cancel
- Manual Cargo / special one-shot Movement
- Research start / pause / resume / Activity Priority / stage execution
- Scientific Exploration start / pause / resume / Fleet assignment / completion disposition
- Resource Survey start / pause / resume / allocation
- External event response where an extension provides one

現地材比率・代替材選択Commandは持たない。

### 13.2 Query

主要Query：

- Catalog / World / Star System / Celestial Body Surface Map / Operational Node / Surface Location
- Surface Cell / Survey Knowledge / Resource Potential / Environment / development affiliation
- Inventory / Reservation / inbound / outbound / Storage / over-capacity
- Activity / Execution Requirement Bundle / requested execution / fulfillment / limiting factor
- Capability / Service Capacity / requested / allocated / spare
- Facility / placement scope / lifecycle / Decommission blocker / Process inputs / outputs / utilization
- Maintenance demand / fulfillment
- Build Options / Projects / future Supply Requirement / Projected Material Readiness
- Vehicle Production Options
- Spatial Relation / Movement Plan候補 / required Operation / latency
- Fleet / Transport Allocations / Provisioning Priority / Transport Capacity / Retirement state
- Cargo Flow / handoff / arrival waiting / end-to-end path / Transport shortfall
- Target Stock / current stock / inbound amount
- Funds / Market Provider / Market Interface / buy-sell offer / Trade Order / commitment / settlement
- Research Point / Technology State / Research Projects / Operational Experience
- Scientific Exploration
- Resource Survey
- Location territory / Physical Environment summary / Surface Access Anchor / Surface Infrastructure demand and fulfillment
- ロケーション産業自立 / external dependency analytics for selected Operational Node scope
- External Events where an extension provides them

Query DTOはJSON化可能なimmutableデータとする。UI側が可否・維持率・Movement適合・allocation・Projected Material Readiness・産業依存度等を再計算しない。

Queryは要求されたscopeを不必要に拡大しない。origin / destination、Operational Node、Entity ID等で対象が限定されている場合は、そのscopeから必要な派生状態を導出する。同一Application snapshot内で複数Queryが同じ派生状態を必要とする場合は同じprojection / indexを再利用し、各Query・各rowから全世界候補を再生成しない。read Queryはauthoritative Stateを変更せず、性能上の都合だけでDomain-owned derived indexを無条件にinvalidateしない。

## 14. Save / Load / Offline Progress

SaveはApplication単位のversion付きSnapshotとする。静的Definitionは `WorldDefinition` とContentから再構築し、可変Stateだけを復元する。Save metadataは `world_definition_id` と `scenario_id` を保持し、Load時にScenario初期化処理を再実行しない。

保存対象にはOperational Node、Surface Locationのcore cell / developed-cell affiliation、Facility lifecycleとsite cell、Inventory / Reservation、Activity Priority、Build / Development / Decommission Project、Location Founding Deployment、Vehicle Production、Fleet数量と用途commitment、Fleet Retirement / Relocation / Releasing、Transport Allocation target / Provisioning Priority、one-shot Movement Execution、Target Stock、Cargo Flow / arrival waiting、Funds残高、Market Provider State / Market Interface、Trade Order / Buy Commitment、Research Point、Technology State、Research Project / Execution Site、Operational Experience、Exploration、Survey Knowledge、Dynamic Physical Environment、canonical game dayと未消化のruntime game-time remainder等を含める。

Static Star System / Celestial Body / Surface Cell topology / geology / Resource Potential / transport geometry / Market Provider DefinitionはWorld / Contentから再構築する。Movement Plan候補、Transport Service Plan、Nominal / Available Capacity、Location Environment summary、Projected Material Readiness、tick内Execution Requirement / allocation結果、ロケーション産業自立Analytics等の派生・transient状態は保存せず再導出する。

Offline Progressは通常Simulationと別ルールにせず、実時間経過をゲーム時間へ換算して同じ1 game dayのcanonical advance経路を使う。通常進行、高速進行、Offlineで同じgame timeを進めた結果が同じStateになることを不変条件とする。fast-forwardは日次tick列と同値な区間をまとめる実装最適化としてのみ利用する。RuntimeやQueryの処理が重い場合も、経過実時間を意図的に破棄する等の時間意味論変更を性能対策に使わず、重複導出や探索範囲を先に是正する。

## 15. Validation / Test

Configuration Validation：

- 未定義Resource / Facility / Vehicle / Movement Operation参照
- 無効SiteRequirement
- 存在しないCapability / Service type
- 負の容量・率・期間
- PriorityLevel範囲外
- Facility Build / Upgrade Recipeの不正Resource数・参照、およびDecommission recovery定義不整合
- Vehicle Production / Maintenance定義不整合
- Transport Allocationの未定義Vehicle / endpoint / 不正control mode
- Spatial transport geometry / Star System / Celestial Body参照不整合
- Research / Exploration / Survey参照不整合
- Surface Cell topology / area / Resource Potential不整合
- Operational NodeのSpatial context参照不整合
- Surface Locationのbody / core cell / developed cell参照不整合
- Surface Access AnchorのOperational Node / site cell参照不整合
- Founding Package / staging node / target Surface Cell / Deployment requirement参照不整合
- SURFACE_CELL FacilityのOperational Node / site cell参照不整合
- Research stage / Technology / Experience category参照不整合
- Technology prerequisiteの未定義参照・自己参照・循環、および表示段階がdependency方向と逆転するContent
- Market Provider / Market Provider State / Market Interface / buy-sell offer / Trade Order参照不整合
- Research execution scope / Execution Site参照不整合
- Facility Decommission / Fleet Retirement Definition参照不整合
- Allocation dependency graphの循環

Runtime Validation：

- 在庫負値、Reservation超過
- Inventory / Logistics-owned CargoのResource保存不整合
- Storageへ荷卸し済みResourceの二重authoritative ownership
- Fleet総数とTransport / Exploration / Relocation / Releasing配分の不整合
- Transport AllocationのUNITS / CAPACITY二重正本
- Execution Requirement / Reservation acquisition settlement超過・同一Resource / Service / Stock admissionの二重消費
- Transport Capacityの二重消費
- Vehicle Production / Movement Execution / Fleet Relocation状態不整合
- Facility maintenance demand / fulfillment不整合
- Research Point負値・Pool capacity処理不整合
- Technology State / Operational Experienceの重複正本
- Funds負値・Buy Commitmentによる予約Funds超過・Resource Market以外からのFunds増減
- Trade OrderのQUANTITY / RATE二重target、RATE backlog混入、price condition、Buy Commitmentの二重commit / 二重settlement / provider supply予約不整合
- Facility Decommissionのdangling live reference / salvage admission不整合
- Fleet Retirementのfree-unit超過 / 排他的commitment不整合
- 孤立Reservation / Entity参照
- Location領域の非連結・Cell重複所属
- Facility placement scopeとsite cellの不整合

ゲーム性評価段階で優先するテスト：

- 資源保存・Inventory / Cargo / handoff / arrival waiting会計
- Surface Locationとnon-surface Operational Nodeが同じInventory / Facility / Fleet所有契約を利用する
- Execution Requirement Bundleが複数Resource / Service / output admissionを共通execution fulfillmentでsettleする
- Activity Priorityが5段階ordinal bandとして機能し、同Priorityの連続量がprogressive max-minで配分される
- minimum / atomic admissionが永続Intentのfairness age / stable keyにより登録順非依存となり、複数tickのStock蓄積はReservation acquisitionへ分離される
- Supply Planningのsource側Resource requirementが現地用途と同じInventory上で競合し、二重消費しない
- 同じSupply Requirementへ割当済み・輸送中のCargoを未充足見込みから控除し、重複dispatchしない
- 将来まで余裕がある高Priority Requirementが現在必要な低Priority需要を直ちに先取りしない
- Service Capacity / Stock admission / Pool admissionが複数Domainへ二重割当されない
- 輸送中Cargoが目的地Storageを事前予約しない
- Cargo arrival /成熟BuyがBoundary obligation allocationで同じ有限Cargo Handling / admission constraintを競合し、使用capacityを当日通常Allocationが再利用しない
- Cargo arrivalがBoundary settlementでadmissionされ、入庫不能分がarrival waitingに残る
- direct handoffとStorage経由handoffでResource ownershipが一貫する
- snapshot後に当tick中に到着・生成されたResource / CapacityやPlayer Commandが過去phaseのallocationを遡及変更しない
- 通常進行 / 高速進行 / Offlineで同じgame timeを進めた結果が一致する
- Facility Build / Upgrade Recipeが2〜3種の実Resourceを直接消費する
- 維持需要が累積建造投入量から決定論的に導出される
- Vehicle建造がCapability・Service Capacity・Resource・時間を消費する
- Fleet unitがTransport / Exploration / Relocation / Retirementへ二重割当されない
- Transport AllocationのUNITS / CAPACITY targetが単一正本である
- Provisioning PriorityとActivity Priorityが別State ownershipを持つ
- Nominal / Available / Used capacityが同じTransport Service Planから一貫して導出される
- 任意の成立済みOperational Node pairについてSpatial Relation / Movement Plan候補を評価できる
- 同一physical stateのMovement Plan全候補導出をPlan ID参照や複数Queryの各rowから反復せず、派生索引として再利用できる
- origin / destination等でscopeを限定したMovement Queryが無関係な全Operational Node pair導出へ拡大しない
- 新規Location / Celestial Body追加時に既存全地点との静的OD Route定義を要求しない
- Surface / Spaceflight / Landing等のOperation適合がVehicle名称に依存しない
- dispatch済みCargo /開始済みMovement Executionのlatencyが後続Definition / Infrastructure変更で遡及変更されない
- Cargo Flow Segment数が経過tick数そのものに比例して増加しない
- Location Founding Deploymentがprepared manifestをsourceからMovement payloadへ移し、完了時にtarget stateへ一度だけ変換する
- Research Pointの生成・貯蔵不変条件
- 複数Research ProjectがActivity Priority / Execution Requirementで共通Resource / Serviceを競合する
- Organization-scope Research executionはprovider所在地のPower / Maintenance / Physical Environment等を満たしたAvailable supplyだけを集約する
- Prototype / Demonstration Execution SiteがOperational Node / Surface Cell scopeを正しく検証する
- Technology Unlockが単一のTechnology Stateだけを更新する
- Operational Experienceが実Domain activityから蓄積される
- Pause / Resume
- Save / Load後の将来進行同値性
- Generic CoreへのLocation / Celestial Body固有分岐侵入検知
- Celestial BodyごとのSurface Cell数・隣接数が可変でも成立する
- Extraction responseがInstalled Capacityに対して単調非減少かつ限界収益逓減である
- Surface InfrastructureがExtraction Opportunityとoperational fulfillmentへ二重適用されない
- Extraction Opportunityがdeveloped cellごとのResource Potential / Physical Environment / accessibilityから導出される
- 通常採掘でStatic Resource Potentialが減少しない
- Research完了だけで既存FacilityのNominal Extraction Capacityが変化しない
- OPERATIONAL_NODE Facilityへ不要なCell指定を要求せず、SURFACE_CELL Facilityだけ有効なdeveloped cellを参照する
- Surface CellがInventory / Logistics Nodeへ自動昇格しない
- 対象天体にSurface Locationが存在しない状態からRemote Surveyを開始・進行できる
- Survey providerごとのcoverageとmax Knowledge Levelを越えてSurveyが進行しない
- Surface LocationのEnvironment lookupがcore cellへ暗黙fallbackしない
- Body-global Physical EnvironmentはOperational Nodeから評価でき、Cell-local Environmentは明示Surface Cellを要求する
- 地表Movementの距離・条件が実Gateway / access endpointから導出され、Location Core Cellへ固定されない
- core cellがMovement、Surface Infrastructure、Extraction Opportunityの無料代表地点にならない
- Location拡大時のSurface Infrastructure負荷がCell routingなしで決定論的に導出される
- Surface Access Anchor集合から内部負荷を導出し、anchor消失時にcore cellへ暗黙fallbackしない
- 近接Location分割でSurface Cell / Resource Opportunity / Service Capacityが複製されない
- Market buy / sellでResource ownership transferとFunds settlementがatomicである
- Sell executionがInterface Inventory Resourceとprovider demandを同じexecution量として競合させ、他用途とResourceを二重利用しない
- FundsがResource Market以外のExecution Requirementへ参加しない
- Trade OrderのQUANTITY / RATE targetが単一正本で、RATE未達量を翌tickへbacklog化せず、未手配・in-flight / presented量、Buy CommitmentのFunds / provider supplyを二重利用しない
- Buy commitmentはcommit時価格を保持し、Sellはownership transfer時点の有効offerでsettleする
- Market Resourceが通常Cargo / Transport / Inventory Admission契約を迂回しない
- ロケーション産業自立Analyticsが保存正本を持たず、同じResource flowからNode scopeごとに再導出できる
- Dynamic Physical Environment変化とStatic geology / Resource Potentialの状態所有が分離される
- Facility Decommissionがdurable commitmentを破壊せず、撤去対象Storage自身をsalvage admission headroomへ数えない
- Vehicleを地球外Operational Nodeで建造・Relocation・Retirementでき、aggregate Fleet数量保存を維持する
- World Definition構築がPlayer-owned initial Stateを生成せず、Scenario Definitionがnew game時だけ初期Stateを構成する

暫定価格、日数、生産量等の仮バランス固定テストは避ける。

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

UIは天体Surface MapでSurvey状態、Resource Potential、Environment、Location領域、初期Location候補・Founding Deployment blocker、隣接開発候補、位置依存Facilityの配置候補を表示する。Surface Locationがまだ存在しない天体でも、non-surface Operational NodeからのRemote Survey、候補Cell比較、staging nodeとFounding Packageを含む設立判断を同じMap上から追えるようにする。通常Facilityの建設・運用は設備一覧・Inspectorを中心とし、不要なCell選択を要求しない。設備一覧・InspectorではProcess inputs / outputs、Activity Priority、Execution Requirement / allocation、Service Capacity fulfillment、maintenance fulfillment、Vehicle production blocker等を安定配置で表示する。Fleet / Transport UIでは所在Operational Node・総数・用途配分、Retirement commitment、Allocation mode / target、Provisioning Priority、必要・投入隻数、Nominal / Available / Used / Spare Capacity、Movement latency、運用Resource需要、Cargo Flow / arrival waiting、blocker / limiting factorをApplication Queryから表示する。Market UIではFunds、Market Interface、buy / sell offer、availability、Trade Order target / commitment / settlement、物流blockerを表示する。Location / region分析ではlocal production、imports、unmet demand等のロケーション産業自立・外部依存状態を表示できる。必要情報を隠してUIを簡略化しない。

LLMはFAST PATHへ入れない。

FAST PATH：Resource / Service Capacity allocation、生産、建設、維持、物流、Research Point、Research / Knowledge、Exploration、Survey、Offline Progress。

SLOW PATH：外部組織要求、イベント、交渉、研究上の問題、状況依存Mission。

LLMはCore Stateを自由に書き換えず、検証可能なCommand / Eventへ変換して適用する。

---

## 17. 横断Architecture invariant

この節は各Domain節の詳細規則を再掲する一覧ではなく、変更時に複数Domainへ同時適用する不変条件を示す。具体的な型、状態遷移、処理順は対応する正準節を参照する。

1. **State ownershipを一意にする。** Definition / State、Spatial context / Operational Node、Inventory-owned Resource / Logistics-owned Cargo等を担当Domain間で重複所有しない。§4–7、§10参照。
2. **Content固有例外ではなく共通条件をモデル化する。** Location名、天体名、Vehicle用途名、研究名をGeneric Coreの分岐条件にせず、Environment、Capability、Service Capacity、Operation、Spatial Relation等で表す。§3、§5–6、§10–12参照。
3. **有限Resource / Serviceの競合を共通Allocationで解く。** Activity Priority、Execution Requirement Bundle、Reservation、Stock admissionをDomain処理順から分離し、同順位結果を登録順へ依存させない。§3.4、§7–9参照。
4. **需要と供給能力の意思決定を分離する。** Activity Priorityは既に存在するResource / Service / Transport Capacity利用を順位付けし、Provisioning PriorityはFleet等をcapacityへ配備する判断を所有する。§7、§10参照。
5. **MovementはSpatial relationと実能力から導出する。** 任意の成立済みOperational Node pairを一般則で評価し、静的OD列挙や技術IDによる直接航路解除を正本にしない。§5、§10参照。
6. **通常物流はaggregate serviceとして扱いながら物理保存を守る。** Transport Capacity、Cargo Flow Segment、direct handoff、Inventory admission、arrival waitingを同じCargo lifecycleへ接続し、Cargo massとStorage ownershipを二重計上しない。§7.4、§10参照。
7. **時間進行はcanonical daily phase contractを正本にする。** snapshot後の変化を当日の過去phaseへ戻さず、通常進行・高速進行・Offlineで同じgame timeの結果を一致させる。§3.4、§14参照。
8. **派生状態を保存正本へ昇格させない。** Transport Service Plan、current Capacity、Analytics、Query用状態等はauthoritative StateとDefinitionから再導出する。§4、§10、§14参照。
9. **Player判断を自動化の副作用で書き換えない。** sourcing、route、Fleet provisioning、Trade Order、Asset廃止等の自動処理はPlayerが設定したauthoritative intentの範囲で行い、blocker・limiting factor・projected readinessをApplicationから説明する。§3.3、§10、§13参照。
10. **Surface Cellを万能Entityにしない。** Surface Cellは物理地理・資源・環境・開発領域の単位とし、通常Inventory / Logistics Nodeや一般Facility slotへ兼用しない。§5、§9参照。
11. **同じ効果を複数係数で適用しない。** Surface Infrastructure、Maintenance fulfillment等の共通bottleneckは所有するRequirement / Serviceへ一度だけ反映し、別Domainで再乗算しない。§5.4、§6、§7、§8参照。
12. **Application・Persistence・Validationまで同じ契約を貫く。** UIはDomain判定を再計算せず、Saveはauthoritative Stateのみを保持し、Validationは不変条件とState ownershipを検査する。§13–16参照。

---

## 18. アーキテクチャ定義の要約

本作のCoreは、Research / Knowledgeの成長、物理的な産業拡大、空間的な拠点拡大、それを支えるResource / Service Capacity / Movement / Logisticsを一つの状態モデルへ接続する。

**「World Definitionは静的宇宙・地理・物理基準を定義し、Scenario Definitionはnew game時のPlayer所有・運用Stateだけを構成する。Star Systemを含むSpatial contextとOperational Nodeを分離し、Surface Locationはconnected developed-cell領域を追加所有するOperational Nodeとして扱う。core cellは設立・領域連結anchorに限定し、Environment・Movement・内部物流の代表地点にはしない。Physical EnvironmentはBody-global stateとSurface Cell local stateから導出し、人工運用環境はCapability / Service Capacityとして表す。有限Resource / Serviceの競合は5段階Activity PriorityとExecution Requirement Bundleで解き、Research TheoryはOrganization-scope Research execution、Prototype / Demonstrationは明示Execution Siteで進行する。Vehicleは同一Definition・所在NodeごとのFleet数量と排他的commitmentで管理し、地球外建造・Relocation・Retirementを同じFleet契約で扱う。通常物流はFleet Allocationから導出するTransport CapacityとCargo Flowで表し、Resource ownershipをInventory / Logistics間で一意に保つ。FundsはExternal Resource MarketにおけるResource ownership transfer専用の決済Stateとし、一般Execution Requirementへ用いない。Facility DecommissionとFleet Retirementは明示Project / commitmentとして進行し、salvageも通常Inventory Admissionへ接続する。Simulationは1 game dayのcanonical boundary → snapshot → intent → planning → allocation → execution → movement → state transitionで決定論的に進行し、通常速度・高速進行・Offlineで同じgame timeの結果を一致させる」**

として維持する。

ゲーム固有の面白さはEarth、Moon等の固有名をCoreへ埋め込むことで作るのではなく、Content DefinitionがGeneric Coreの組み合わせから異なる制約・産業構造・発展経路を形成することで作る。
