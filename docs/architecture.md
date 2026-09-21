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
- Construction / Surface Development Project / Operational Node Founding Deployment
- Movement Operation / Movement Plan、Transport Allocation、Transport Service / Capacity、Cargo Flow、one-shot Movement Execution
- Vehicle Definition / Fleet State / Fleet Commitment / Production / Maintenance / Relocation / Retirement
- Supply Requirement / Target Stock / Logistics auto-sourcing / routing hard constraint / end-to-end path
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
- World Definition / Scenario Definition / Deployment Recipe / Founding target spec
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
   purpose-specific Service、Inventory Admission等の有限constraintを必要とする場合は、通常Activityと同じconstraint key、
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
   Transport Capacity、必要なrouting hard constraintから当日dispatch量とsource / path候補を求める。
   hard constraintがない通常状態では成立済みNetwork内で正準評価によりsource / pathを決定論的に選ぶ。
   Service supplyがResource、Fleet、Power、Maintenance、上流Service等を必要とする場合は
   provider dependencyとして明示する。

5. Allocation
   Resource、Service、Stock / Pool admission、Transport Capacity等のexecution依存関係を
   一つの決定論的allocation graphとして解決する。
   Activity Priorityは5段階のordinal bandとして高いbandから解決し、
   同一band内の連続量Bundleはnormalized fulfillmentのprogressive max-minを基本とする。
   Fleet Commitmentは既存の排他的物理Stateとしてconstraintへ反映し、Activity Priorityだけで別ownerから奪わない。
   Transport Allocationへのfree Fleet provisioningは別のProvisioning Priority契約で解決し、
   Research Provider / Survey / Exploration等のcommand-time Fleet commitを日次Activity allocationへ読み替えない。
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
  installation_eligibility
  operating_eligibility
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
  selected_process_id?
  allocation_priorities
```

同様にVehicle、Transport Allocation、Research、Scientific Exploration、Survey、Construction Recipe等でもDefinitionと可変Stateを分ける。

Vehicle Definitionは性能と製造・整備要件を持つ。通常運用するVehicleは同一Definition・所在Operational NodeごとのFleet Stateとして数量管理し、Transport、Scientific Exploration、Fleet-backed Survey / Research Provider、Relocation、Release、Retirement等の排他的配分をFleet Domainが所有する。

Technology UnlockはResearch DefinitionやFacility Stateへ複製せず、一つのTechnology Stateをauthoritative stateとする。Operational ExperienceもResearch Project個別の経過時間として重複保持せず、experience categoryごとのKnowledge Stateを正本とする。

`WorldDefinition` はStar System、Celestial Body、Surface Cell topology、static geology / Resource Potential、基準Physical Environment等の静的世界を構成する。`ScenarioDefinition` は開始時Operational Node / Surface Location、Facility、Fleet、Inventory、Knowledge / Technology、Funds、Market Provider State / Market Interface、Scenario固有の戦略固定が必要な場合だけrouting hard constraint等の初期Stateを構成する。World Definitionの構築自体がPlayer-owned Operational Stateを生成しない。Scenarioはnew game生成時だけ適用し、Save Load時に再適用しない。

Movement Plan候補、Transport Service Plan、Transport Capacity、Projected Material Readiness、ロケーション産業自立・外部依存分析等は、保存済みStateとDefinitionから導出する派生状態とし、Save上の独立した正本にしない。

静的DefinitionはSaveへ複製しない。


### 4.1 共通Intent / Requirement / Commitment契約

Domain横断の再利用は、全Stateを一つの巨大base classへ統合するのではなく、同じ意味を持つ契約だけを共有する。

Requirementは少なくとも次の意味を分離する。

- `EligibilityRequirement`: 消費を伴わない成立条件。Technology、Spatial classification、Physical Environment、Installed / Active Capability、Knowledge threshold等。
- `AllocationRequirement`: 当tick execution量に比例して有限Resource / Service / Poolを競合利用する条件。
- `AdmissionRequirement`: outputをStock / Poolへ追加するためのheadroom。
- `ReservationAcquisitionRequirement`: 将来実行用にon-hand Stockを複数tickで確保する要求。

`SiteRequirements` はEligibilityRequirementのうち物理Siteに関係する条件集合とし、Construction work、Research execution、Power等の有限flowをSite条件へ混ぜない。Knowledge Requirementもtyped EligibilityとしてActivityへ合成できるが、Knowledge State自体の所有者はSurvey / Knowledge Domainに残す。

Commitmentは将来executionやAsset利用のために既に確保済みのauthoritative Stateである。Resource Reservation、Fleet Commitment、Market Buy Commitment等は意味の異なるtyped Stateとして各所有Domainが保持し、同じ量を複数Domainへ保存しない。新しい資産種別が実際に同じ排他所有問題を持つまでは、万能なAsset Provisioning frameworkへ一般化しない。

Player intentと運用自動化を分離する。Playerが成立させたResource、Service、Transport Network内の通常反復運用に必要なsource / path等の候補選択は、Coreが正準ルールで決定論的に導出できる。Playerがその自動選択を戦略的に制限する必要がある場合だけ、所有Domainがtyped hard constraintをauthoritative intentとして保持する。hard constraintが成立しない場合は別戦略へ暗黙fallbackしない。

### 4.2 共通Activity control

Pause可能なActivityではcontrol stateをDomain lifecycleとは分離する。Pauseは次のcanonical boundary以降に新しい裁量的execution / progress / dispatchを生成しないが、設定と成立済みprogressを保持する。

開始済みMovement、dispatch済みCargo、arrival waiting、Market Commitment、不可逆settlement等の物理obligationはPauseで巻き戻さない。ReservationやFleet Commitment等のreversible commitmentをPause中も保持するか、安全なreleaseへ移すかは所有Domainが明示的に定義する。PauseをCancel、Abort、Asset releaseと同一状態にしない。

Transport AllocationはPause時にtargetを保持したまま新規provisioning / dispatchを止め、運用中Fleetを必要なrecovery / release stateへ移してfree poolへ戻せる。Scientific Exploration等のone-shot CampaignはPauseだけでcommit Fleetを他用途へ解放せず、必要ならAbort / Return等の別transitionを利用する。

Application QueryはActivityごとに現在利用可能なtransitionとblockerを返し、UIがDomain固有の状態遷移を再実装しない。

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

Facility設置・運転、Researchの物理Stage、Movement Endpoint、Operational Node Founding / Surface Location開発等の物理適合性は共通SiteRequirementsを利用する。SiteRequirementsはSpatial classification、Physical Environment、Installed / Active Capability等の非消費Eligibilityを型として分離する。

Power、Construction work、Cargo Handling、Research execution等の有限flowは `Service Capacity` としてAllocation Requirementへ提出する。あるActivityが特定providerの存在自体を前提とする場合はCapability等のEligibilityで表し、実際に利用する有限量は別のService Requirementで競合させる。

`Capability` はcategoricalな資格・機能を表す。`ServiceCapacity` はservice type、scope、Nominal、Available、Allocated、Spareを持てる。scopeは少なくとも `OPERATIONAL_NODE` と `ORGANIZATION` を表現できる。

NominalはPhysical snapshotに固定する配分前supplyであり、Power、Maintenance、Resource、Fleet、Physical Environment、上流Infrastructure / Service等への依存をPlanningでprovider dependencyとして公開する。Organization-scope Serviceへ供給するproviderも、所在地でローカル依存条件を満たしたAvailable supplyだけを集約する。

PowerはOperational Node scopeのService Capacityとする。Energy Storageを導入する場合はPower Capacityへ暗黙統合せず、独立Stock Stateと充放電executionを定義する。Knowledge threshold等の非Site条件はtyped EligibilityとしてActivityへ合成し、SiteRequirements fieldへ押し込まない。

### 5.4 Location development / Surface Infrastructure

Surface Locationは隣接Surface CellをDevelopment Projectで取り込む。Cell数に固定上限を設けず、Knowledge Eligibility、Resource、Construction Service Capacity、時間、地形・Physical Environment、Surface Infrastructure等を要求する。

Location内部で個別ResourceをCellごとにroutingしない。ただし共通Inventoryによる内部移動を無償・無限とも扱わない。位置依存Facility / InfrastructureはSurface Cell上に `Surface Access Anchor` を供給できる。開発Cell、利用可能anchor、Surface geometry、Activityが利用するResource Opportunity / Movement endpointから、Core共通のLocal Distribution / Surface Infrastructure demand modelで必要Service量を導出する。

共通modelは少なくとも、Activity量や必要spread増加に対して需要が不自然に減少しないこと、有効anchor追加だけで最小需要が悪化しないこと、停止anchorへfallbackしないこと、同じ地理負荷をOpportunityとService fulfillmentへ二重適用しないことを保証する。Contentはanchor性能、Facility能力、Spatial / physical入力を定義するが、LocationやResourceごとの任意負荷関数をCore外へ持たせない。

`core_cell_id` はLocation設立起点とdeveloped-cell連結性のanchorであり、Environment、Movement、Resource Opportunity、Local Distributionの代表地点ではない。core cell自体に無料capacityや距離0特権を付与しない。

近接地域への別Location設立はCoreで禁止しない。新Locationは独立Operational NodeとしてFounding、Inventory、Storage、Power、Construction、Gateway / access、拠点間物流等の固定費を要求する。同じSurface Cell、Resource Opportunity、Service CapacityをLocation分割で複製しない。

## 6. Facility / Maintenanceモデル

### 6.1 設置と運転

Installation EligibilityとOperating Eligibilityを分離する。Spatial classification、Physical Environment、Capability等の非消費条件をSiteRequirements / Eligibilityとして表し、建設work、Power、Process Service等の有限flowはexecution時のAllocation Requirementとして扱う。

Facilityは同一Domainのまま配置種別を持つ。

- `OPERATIONAL_NODE`: Operational Nodeへ所属し、個別Surface Cellを指定しない通常Facility。
- `SURFACE_CELL`: 物理的位置が性能、Movement接続、局所Environment、環境改変等へ本質的に影響する位置依存Facility。

`SURFACE_CELL` Facilityだけ `site_cell_id` を要求し、所属Operational NodeはSurface Locationで、対象CellはそのLocationのdeveloped領域でなければならない。

Facility Definitionは互換Process集合を持てる。通常一Facility instanceが同時に実行するProcessは一つとする。互換Processが一つなら選択はDefinitionから導出でき、複数ある場合だけFacility Stateが `selected_process_id` をauthoritativeに所有する。登録順やID順で暗黙選択せず、Requirement不足時にも別Processへ自動切替しない。

複数Process同時実行が独立したゲーム上の判断として必要になった場合は、capacity共有・配分・Power・Maintenance・UIの意味論を定義してからFacility契約を拡張する。現在は一Facility instanceにつき一active Processを正本とする。

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

不可逆な解体開始前は取消可能とし、開始後はFacilityを通常operationへ戻さない。`DECOMMISSIONING` Facilityは通常のProcess、Active Capability、Service Capacity supply、Storage admission等の新規Activity向け能力を停止する。既存stockや開始済みcommitmentを安全にsettleするため解体中にも残す必要がある受動能力だけは明示契約として保持できるが、新規Activityの供給能力へ数えない。

既に開始済みでFacilityの現存を前提に安全にsettleする必要がある不可逆commitmentを破壊する場合はDecommission開始をblockする。Storage Facility除去後の残存Physical / Usable Capacityで既存Inventoryを保持できない場合も開始をblockする。これは既にPlayer-ownedなResourceの保存を守る契約であり、salvage admissionとは別に判定する。

Decommission完了時はFacility removalとsalvage settlementを同じcanonical transitionで確定する。salvageは累積投入ResourceとContent recovery定義からrecovery potentialを導出し、Facility removal後に残るcompatible Storage headroomを用いる全salvage Resourceのadmission requirementを一つのdisposal executionとして共通Allocationへ提出する。撤去対象Facility自身のStorage Capacityをsalvage受入余力へ数えない。Allocationは0..1の共通recoverable fractionを決め、そのfractionを全salvage outputへ比例適用する。実際にadmissionする量だけInventoryへResourceとして生成し、未回収potentialをauthoritative Resource Stateへしない。

recoverable fractionが1未満であることだけを理由にFacility removalをblockしない。Resource列挙順によって回収構成が変化しないことをinvariantとする。

## 7. Inventory / Allocation / Storage / Power

通常Inventoryに属する物理Resourceは必ず有限Storage accountingへ参加する。通常Resourceは共通のdefault storage poolを利用し、保管方式そのものが独立したゲーム上の意味を持つResourceだけContentがspecial storage pool / compatibilityを指定できる。Generic Coreは具体的なStorage分類一覧やResource名分岐を持たない。内部pool keyはcapacity poolを一意に参照する識別子であり、その名称自体をゲーム上の固定taxonomyにしない。

```text
StorageCapacityPool
  key
  physical_capacity
  usable_capacity
  capabilities[]

ResourceDefinition
  storage_pool_key?   # 未指定ならdefault storage pool
```

StorageCapacityPoolのcapacityはFacility / Infrastructure等の供給元から導出する集約projectionであり、供給元と別のauthoritative capacityを重複所有しない。Physical Storage Capacityは設備として保持可能なstock上限、Usable Storage CapacityはPower、保冷、Facility状態、必要Capability等を反映して現在安全に利用できる上限とする。一定時間あたりの有限処理flow自体が共有bottleneckになる場合だけ、目的を明示したService Capacityとして定義する。

InventoryはOperational Nodeごとの所有Resourceを表す。on-hand、Reservation、利用可能量、入庫・出庫flowを所有し、Logistics-ownedの輸送中Cargoやarrival waitingとはauthoritative ownershipを分離する。Application QueryではInventoryとInbound / outbound Cargoを統合表示してよいが、同じResource量を二つのDomain Stateへ重複保存しない。

PowerはOperational Nodeごとのflow型Service Capacityとし、他の有限capacityと同じActivity Priority / Allocation契約を利用する。Power capacity自体をtick間Stockとして扱わない。時間を跨いで保持するenergyを導入する場合は明示Stock / Pool Stateとcharge / discharge executionを追加し、Power Service Capacityへ暗黙の蓄電量を混在させない。

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

`Provisioning Priority` はfree Fleetを複数Transport Allocationへ配備する場合の優先度を表す。需要側のActivity PriorityがProvisioning PriorityやTransport Allocation targetを暗黙変更せず、Provisioning Priorityも別Activityへcommit済みFleetをpreemptしない。

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

Operational Nodeへ物理Resourceが増加するすべての経路は共通Inventory Admission契約を利用する。Industry output、Extraction output、Cargo unloading、Market buyによるownership transfer等をcompatible Storage poolのPhysical / Usable Capacity契約へ接続する。

Local executionからのoutput admissionはExecution Requirement Bundle内のStock admission requirementとして当tick Allocationへ参加する。すでに過去tickでdispatchされて到着したCargoはBoundary settlementで先にadmissionを試み、入庫不能量はarrival waitingとしてLogistics側へ残す。

Usable Storage Capacityが既存stock量を下回った場合は既存在庫を即時消去せずover-capacity stateとして保持する。新規admission可能量、成立していない保管条件やService、blocker等をApplicationへ公開する。

## 8. Industry / Extractionモデル

### 8.1 Process

FacilityそのものとProcessを分離する。Processはinputs、outputs、基準処理能力、Power等のRequirementを持つ。

一Facility instanceが通常同時に実行するProcessは一つとする。Facility Definitionに互換Processが一つしかなければProcess selectionはDefinitionから導出し、複数ある場合だけFacility Stateが `selected_process_id` をauthoritativeに所有する。登録順・ID順で暗黙選択せず、Requirement不足時に別Processへ自動切替しない。

Processは一単位executionに必要なResource、Power、Process Service、output admission等をExecution Requirement Bundleとして提出する。Application Queryは選択Process、候補、実効inputs / outputs、requested / allocated execution、稼働率、limiting factorを返す。

複数Process同時実行を導入する場合は、shared capacity、配分、Power、Maintenance、UIを含む新しいゲーム上の意味としてその時点でProcess契約を拡張する。

### 8.2 資源・能力競合

Processは一単位executionに必要なResource input、Power、Process Service、output Storage admission等をExecution Requirement Bundleとして提出する。Industryだけの独自先着配分を持たず、Maintenance、Research、Construction等と同じAllocation契約で競合する。

Allocation結果として確定したexecution fulfillmentだけProcessを進め、そのexecution量に対応するinputを消費し、許可済みadmission量の範囲でoutputを生成する。Application Queryはrequested execution / allocated execution / fulfillmentとlimiting factorを返す。

### 8.3 Extraction / Resource Potential

有限 `Deposit remaining` を採掘の正本にしない。地表資源はSurface Cellごとの静的 `Resource Potential` と、Locationに設置された採掘Facilityが供給するNominal Extraction Capacityから継続的なThroughputを導出する。

Resource Potentialは残量、Facility slot数、固定最大`t/day`のいずれでもなく、追加採掘能力をどの程度高い限界生産性で利用できる地域かを表す。各developed Surface CellについてStatic PotentialにPhysical Environment・地質accessibilityを適用して `Cell Effective Opportunity` を導出し、それらをLocation単位へ集約する。

```text
CellEffectiveOpportunity(cell, resource, method)
  <- static Resource Potential
  <- current Physical Environment
  <- geological / terrain accessibility

EffectiveOpportunity(location, resource, method)
  <- developed cellsのCellEffectiveOpportunity集約
```

Installed Nominal Extraction CapacityとEffective Opportunityから実効Throughputを求めるresponseはGeneric Coreの共通モデルとし、少なくとも次を保証する。

- Installed Capacityが0ならThroughputは0。
- Installed Capacity増加に対して総採掘量は単調非減少。
- 同じOpportunityに対する限界増産量は逓減。
- Opportunity改善だけで同じCapacityのThroughputが低下しない。
- Facility数のハード上限をResource Potentialから直接導出しない。
- 通常採掘でStatic Resource Potentialを減少させない。

ResourceやLocationごとの任意response関数をContentへ持たせない。方式差は共通responseへ入力するOpportunity、Facility性能、Environment / accessibility等で表す。

Surface Infrastructure / Local Distributionの有限能力はExtraction executionのService Requirementとして一度だけAllocationへ反映し、Resource Opportunityへ別係数として重ねない。Survey Knowledgeは物理Throughput係数ではなく、公開する推定値・候補・Knowledge blockerを決めるStateとして分離する。

研究は新しいFacility Definition、Process、Construction / Modernization手段を解禁する。Throughput上昇には実際のFacility建設・Upgrade・更新が必要となる。

### 8.4 ロケーション産業自立・外部依存Analytics

ロケーション産業自立は保存Stateや特定天体固有のフラグではなく、authoritativeなProduction、Consumption、Supply Requirement、Import / Export、Unmet Requirementから導出するAnalyticsとする。

単一Surface Location、単一Operational Node、任意のOperational Node集合をanalysis scopeとして選べる。Resource単位を正本とし、表示上のResource GroupはContent Definitionで定義できる。Mass、Energy、Propellant、Machinery等の固定カテゴリをGeneric Coreへ埋め込まない。

Queryは少なくとも `CURRENT` と `FORECAST` のtime basisを区別する。CURRENTはsnapshot時点のrate / unmet stateを返す。FORECASTはactive Project、Supply Requirement、Target Stock等が持つforecast time / consumption rateから、既に計画へ現れている将来依存を導出する。固定horizonはauthoritative Stateにせず、期間指定が必要ならQuery filterとして扱う。Power等のService Capacity dependencyをResource Groupへ混在させず、必要なら別projectionとして扱う。派生AnalyticsなのでSaveへ独立保存しない。

## 9. Constructionモデル

### 9.1 建設能力

Construction Service CapacityはOperational Node固定値ではなく、建設ヤード、施工設備、ロボット、移送可能な建設機械等から発生する有限flowとする。

複数Projectへ配分でき、一案件完了後の余剰能力は残案件へ再配分する。

### 9.2 Construction Recipe

Facility Build / Upgradeは有限個の明示ResourceとConstruction workを定義する。

```text
ConstructionRecipe
  target definition / work kind
  resources[]
  construction_work
  eligibility_requirements
  prerequisite_technologies
```

一般ContentではUI可読性と物流判断を保つため2〜3種類程度の主要Resourceを基準とするが、Generic CoreはResource種類数を固定上限としてValidationしない。追加Resourceが独立した判断を生む場合は明示Requirementとして定義する。

Construction workはFacility建設・UpgradeだけでなくFacility Decommissionにも共通Service Capacity / Project schedulingを利用できる。ただしFacility lifecycle transition自体はFacility Domainが所有する。Decommission recipeは必要work、補助Resource、salvage definitionをContentとして定義できる。抽象ComponentへLocalSubstitutionTierをぶら下げる方式は採用しない。

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

Construction系Projectはtarget kindを明示し、Build / Upgrade / Decommission等の異なるlifecycle intentを同じProject Schedulingへ接続できる。Build / Upgrade Projectは少なくともOperational Node、進捗、Resource commitment / Reservation状態、Activity Priority、pause状態を持ち、必要ResourceをSupply Requirementとして公開する。通常routingはProject destinationとResource需要からLogisticsが導出し、Project自体が物理的originをDomain意味として持つFounding等だけ、そのoriginをProject contractとして保持する。Projectが開始条件として複数tickにまたがる資材確保を必要とする場合はReservationAcquisitionRequirementで段階的にReservationを形成する。SURFACE_CELL Facilityだけは追加で配置Cellを持つ。Decommission Projectは対象Facility Entityを参照し、Facility Domainが公開する開始可否・不可逆境界・completion transitionを利用する。

Projectは通常物流のsourceや各Leg、Transport Serviceをauthoritative stateとして所有しない。現在のconstruction executionに必要なResource / Construction Service等はExecution Requirement Bundleとして生成する。Project進行から予測できる将来資材必要量はstableなSupply RequirementとしてLogisticsへ公開し、Project進捗が変化すればremaining quantity / forecast requirement timeを更新する。

PauseとCancelを分離する。Build / Upgrade ProjectのPauseは新規Construction executionと新規ReservationAcquisitionRequirement生成を止めるが、既取得Resource Reservationとprogressは保持する。Reservationを解放してProject intent自体を終了する処理はCancel側の明示transitionとする。

### 9.5 Operational Node founding / Surface development

新しいOperational Nodeを成立させる一回限りの処理は共通 `OperationalNodeFoundingProject` lifecycleとして扱う。targetの物理種別はtyped specで分離する。

```text
OperationalNodeFoundingProject
  staging_node_id
  target_spec
  deployment_recipe_id
  prepared_resource / fleet commitments
  deployment_movement_requirement
  preparation_work
  priority
  status

SurfaceLocationTargetSpec
  body_id
  core_cell_id

NonSurfaceOperationalNodeTargetSpec
  spatial_context_id
```

Founding前のtargetはphysical Movement endpointにはなれてもInventory / Logistics Nodeではない。Deployment Recipeはstaging側で実際に準備するResource、Fleet、workと、到着後に生成するOperational Node、Facility、Inventory等の対応を明示する。dispatch時にsource側Stateからone-shot Movement payload / commitmentへ移し、成功時だけtarget Stateへ一度settleする。Definitionだけを理由にResource、Fleet、Facilityを追加生成しない。dispatch前の取消は取得済みReservation / Fleet Commitmentを通常のrelease契約で解放する。dispatch後はpayloadやFleetを消去せず、Movement Executionが定義するreturn / recovery / failure dispositionを完了させてsettleする。

Surface Location Foundingは追加でKnowledge Eligibility、target Surface CellのPhysical Environment、Landing / access等を要求できる。Knowledge Requirementはtarget / knowledge subject / minimum levelを明示し、単一の「survey済み」flagや任意Resourceの最大Knowledge値へ縮退させない。

既存Locationの隣接Surface Cell開発はResource・Construction Service Capacity・時間・Eligibilityを消費するDevelopment Projectとして扱う。成功後はgenerated Operational Node / developed cellを通常Inventory / Facility / Logistics契約へ接続する。

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

Vehicle DefinitionはMovement適合性、Payload、Propellant、Endurance、Operation interface、turnaround / maintenance、Production Requirement等の性能・物理要件を持つ。Funds costは一般Vehicle要件へ含めない。

通常Vehicleは個体Entityではなく、同一Definition・所在Operational Nodeごとの `FleetPool` 数量として管理する。Fleet Domainは総数と排他的 `FleetCommitmentState` をauthoritativeに所有する。

```text
FleetCommitmentState
  commitment_id
  owner_activity_ref
  vehicle_definition_id
  operational_node_id / movement_state
  quantity
  completion_disposition?
```

`owner_activity_ref` はTransport、Scientific Exploration等の用途名をFleet Coreの閉じた分岐へ変換するためではなく、所有Activity / Provider Assignmentへstableに参照する。Fleet Domainは用途固有progressを所有せず、数量保存、排他性、所在、commit / release / Movement settlementを保証する。Transport Allocation、Scientific Exploration、Fleet-backed Research / Survey Provider Assignment、Retirement等は必要unitをこの契約へcommitし、各Domainへ同じunit数量をauthoritativeに複製しない。Survey CampaignのようにProvider Serviceを消費するActivityへFleet Commitmentを重複保持しない。

free Fleetを継続的に自動配備する `Provisioning Priority` はTransport Allocationのゲーム上の判断として定義し、すべてのFleet利用Activityへ一律一般化しない。他Activityは開始・割当Command等、自身の意味に沿ってcommitする。

Vehicleは任意Operational NodeでProduction requirementsを満たせば建造でき、完成unitはそのNodeのFleetPoolへ追加される。別Nodeへの配置換えはFleet Relocation / Movement Executionを通して物理移動し、sourceから減少したunitは到着完了までdestinationへ存在しない。

個体ごとの耐久、固有改修、履歴等が主要Stateにならない限り恒久Vehicle Entityを導入しない。同一状態unitをcohortとして表現できる場合はFleet集約を維持する。

### 10.3 Vehicle Production / Retirement / one-shot Movement Execution

Vehicle ProductionはOperational Nodeを実行地点として持ち、必要Resource、Production Capability / Service Capacity、SiteRequirements、時間を満たして進行する。完成時にそのNodeのFleetPoolへunitを追加する。

Fleet RetirementはTransport / Fleet Domainが所有する永続Intentとする。retirement対象unitは所在Operational Nodeのfree Fleetから排他的にcommitし、所在Nodeで通常のService Capacity / Resource Requirementとして表現されるworkを経て完了時にFleet総数を減らす。不可逆な解体開始前は取消可能、開始後は対象unitを他用途へ解放しない。

salvage量はVehicle Definitionのretirement recovery定義とunit数からrecovery potentialを導出する。Facility Decommissionと同じdisposal settlement契約を用い、全salvage Resourceのcompatible admissionを共通Allocationへ提出して0..1のrecoverable fractionを決め、全Resourceへ比例適用する。admission成立量だけInventoryへ生成し、recoverable fractionが1未満でもFleet unit removalを完了できる。Resource列挙順によって回収構成が変化してはならない。

Fleet Relocation、Scientific Exploration等の有限操作はone-shot Movement Executionを利用し、開始時にFleet unitをsourceのfree poolから外し、完了時に定義されたdispositionへsettleする。in-transit unitをsource / destination Fleetへ同時に計上しない。

### 10.4 Transport Allocation / Transport Service / Capacity

プレイヤーはVehicle type、origin / destination relation、方向別Target Capacity、Provisioning Priority、必要ならMovement hard constraintを指定してTransport Allocationを作る。

```text
TransportAllocationState
  allocation_id
  origin_node_id
  destination_node_id
  vehicle_definition_id
  target_capacity: DirectionalCapacity
    forward_t_per_day
    reverse_t_per_day
  provisioning_priority
  movement_hard_constraint?
  control_state
```

Target Capacityはforward / reverseを区別する方向別定常capacityであり、Transport Allocationの唯一のauthoritative targetとする。Fleet unit数はTarget Capacity、選択されたMovement / Service Plan、1unit当たりNominal Capacityから導出する。UIがFleet unit数を入力補助として受け取る場合はApplication境界でTarget Capacityへ変換し、Domain StateはTarget Capacityだけをauthoritativeに保持する。

Movement Plan候補が複数ある場合、hard constraintがなければlatency、Propellant等の運用Resource負担、service構成等を含む正準評価で決定論的に選ぶ。Playerが特定Gateway、Movement Plan、Service構成を戦略的に固定する場合だけhard constraintをauthoritative Stateとして保持する。

Provisioning Priorityは1〜5、標準値3とし、Transport Allocation間でfree Fleetをどこへ配備するかを決める。Activity Priorityとは別Stateであり、Priority変更だけでScientific Exploration等の別ownerへcommit済みFleetをpreemptしない。

必要Fleet数はNominalな1unit当たり能力から導出し、一時的な燃料・整備不足を埋めるため自動増員しない。Fleet不足でtarget未達でもAllocation設定を保持する。Pause時は必要active unitsを0として新規Provisioningを止め、運用中unitはrecovery / release lifecycleを経てfree poolへ戻すが、Allocation target自体は保持する。

Transport DomainはAllocationごとにMovement、recovery、turnaround、refueling、servicingを組み合わせてTransport Service Planを導出する。Service PlanからTarget、Nominal、Available、Used、Spare Capacityを区別する。往復Serviceの同一cycle負荷を方向別capacityで二重計上しない。可変運用需要は実際のService利用率から発生させる。

Transport Service Plan、Movement選択結果、Required Fleet Units、current Capacityはderived stateとし、dispatch済みCargo Flowや開始済みMovement Executionが保持するlatency等はdispatch / start時点で確定してState化する。

### 10.5 Supply Requirement / Target Stock / Supply Planning

各Domainは将来のResource補充・配置必要量を `SupplyRequirement` として公開できる。Supply RequirementはPlanning情報でありInventory ReservationやResource消費そのものではない。通常Facility / Project / Maintenance / Research需要はSupply Requirementから自動補給され、Target Stock設定を前提にしない。

Target Stockは、通常需要を超えてPlayerが特定Operational Nodeへ追加で保持したい備蓄量を表すPlayer intentとして同じSupply Planningへ接続する。Target StockはInventory Reservationではなく、現在stockを通常Activityから隔離しない。不足量だけを追加Supply Requirementとして扱う。

```text
TargetStockState
  target_stock_id
  destination_node_id
  resource_id
  target_quantity
  activity_priority
```

Logistics PlannerはSupply Requirement、Target Stock、Inventory、Reservation、Inbound Cargo、latency、Transport Capacity、Activity Priority、必要なrouting hard constraintを統合し、当日dispatch必要量・rateをactive shipping demandへ解決する。Activity Priorityが高くても、将来まで十分余裕があるRequirementは現在必要な低Priority活動を直ちに先取りしない。同一destination / Resourceの複数Requirementはlocal stock / inbound planning creditを共通配分し、同じ量を複数Requirementへ重複して充足済みと数えない。

通常状態では、現在成立しているsource InventoryとTransport Service graphからsource / end-to-end pathを正準評価で決定論的に選択する。Playerが自動選択を制限したい場合だけ、需要scopeに直接結び付く疎なrouting hard constraintをauthoritative intentとして保持する。

```text
SupplyRoutingConstraintState
  scope:
    owner_ref?
    destination_node_id
    resource_id?
  source_node_id?
  required_via_node_ids?
  required_transport_allocation_ids?
```

routing hard constraintは需要scopeへ直接所属する。constraintが存在しない需要は通常auto-routingを用いる。hard constraintが成立しない場合はblockerを返し、別source / pathへ戦略的fallbackしない。

PlanningはTransport Allocation target、Fleet provisioning、Trade Order、Facility、Target Stockを暗黙変更・生成しない。発送候補Resourceはsource側Execution Requirementとして現地用途と共通Allocationで競合する。routing constraint変更は未dispatch Planningへだけ作用し、dispatch済みCargo / Movement条件を遡及変更しない。

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

Logisticsは現在成立しているTransport Serviceをgraph edgeとして、destinationまでのend-to-end pathを導出する。SupplyRoutingConstraintがある場合はsource / via / Service等のhard constraintを満たす候補だけを残す。

constraintがない通常状態では、latency、Propellant等の運用Resource負担、handoff burden、利用可能Transport Capacity等の実際の物流特性を正準評価し、同一physical stateから同一pathを決定論的に選ぶ。各指標の単位差だけで一方が支配しないよう正規化等を用い、同評価の候補だけstable keyでtie-breakする。

同一Transport ServiceがCargoを保持したまま複数Movement Operationを継続する場合は一つのLogistics legとして扱える。別Serviceへ直接積替えするOperational Nodeだけhandoff pointとし、Spatial hierarchy上の中間contextを自動handoffにしない。

Routingは既存Transport Serviceの利用を解決する責務であり、Transport AllocationのVehicle / Capacity / Movement hard constraintやFleet provisioningを変更しない。dispatch時に選ばれた各LegのService identity / latency等はCargo Stateへ確定し、後のNetwork変更で遡及変更しない。

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

Facility-backed Research ProviderはFacility StateとDefinitionから供給を導出する。Fleet-backed Research ProviderはResearch Domainが `ResearchProviderAssignmentState` をauthoritativeなprovider-use intentとして所有し、そのStateがFleet Domainの排他的Fleet Commitmentを参照する。Fleet quantityと排他所有はFleet Domainだけが所有し、Research Domainへ複製しない。Player Commandはprovider用途へ配分する希望Fleet quantityを受け取る。

```text
ResearchProviderAssignmentState
  id
  provider_definition_id
  vehicle_definition_id
  operational_node_id
  priority
  paused
  fleet_commitment_ref
```

Assignmentは継続的な研究供給へFleetを使うPlayer intentであり、Transport AllocationのProvisioning Priorityを継承しない。割当unit数は参照先Fleet Commitmentのquantityから得る。Assignment作成・数量変更Commandは希望quantityを入力としてCommitmentを原子的に作成・resizeし、必要差分をfree Fleetから即時に確保できなければStateを変更せずblockerを返すため、自動補充待ちtargetは持たない。供給量はcommit quantityと所在地のPower / Maintenance / Environment等から導出する。PauseはRP generation / Research execution供給を停止するがFleet Commitmentを保持する。Fleetを他用途へ戻す場合はAssignment releaseでcommitmentを解放する。

### 11.1 Technology State

完了済みTechnology集合は単一のauthoritative `TechnologyState` が所有する。Facility、Process、Vehicle、Movement Operation等はprerequisite technologyを参照するだけで、各Domainへunlock flagを複製しない。

Research DefinitionはTechnology間のdirect prerequisiteをContentとして定義できる。Technology dependency graphはacyclicなDAGとし、研究開始可否は完了済みTechnologyと個別prerequisiteから判定する。表示上の研究段階区分や専門区分を暗黙のprerequisiteにしない。

研究段階区分はTechnologyの発展位置を可視化するContent metadataであり、Research Project内のStage種別とは別概念とする。Designは表示段階1〜8の基準名を定義し、第9段階以降も同じ原則で追加できる。Coreは段階数上限、区分ごとの研究数、特定区分の存在を固定しない。

Content validationはTechnology ID一意性、prerequisite参照、dependency cycle、表示段階とdependency方向の自己矛盾を検証する。

研究技術IDをMovementの直接解除キーにしない。研究は一般化可能な技術知識・工程・制御方法を表し、実際の到達可否はSpatial Relation・Operation要件・Vehicle性能・Infrastructureから決める。既存Facility性能もResearch完了時に暗黙変更しない。

### 11.2 Research Project / stage

Research Projectは複数を並行して進められる。並行性はRP、Research execution Service Capacity、Resource、Facility / Capability、Knowledge等の実Requirementから制約し、固定global queue数や登録順priorityを正準仕様にしない。Pause時はcurrent Stage / progressと取得済みResource Reservationを保持し、Reservation releaseをCancelとは別の暗黙副作用にしない。

Research Definitionは次のtyped Stage Specを一つ以上含むordered listを持つ。各Stage instanceはResearch Definition内で一意な `stage_id` を持ち、同じStage種別も異なる技術的目的・Requirementを持つ別instanceとして複数回配置できる。

- `THEORY`: RPとOrganization-scope Research executionを消費してprogressする。
- `PROTOTYPE`: 明示Execution ContextでResourceと有限Serviceを使ってprogressする。
- `DEMONSTRATION`: 明示Execution Contextでduration / work等をprogressする。
- `OPERATIONAL_EXPERIENCE`: 対応Knowledge categoryのthreshold到達をcompletion conditionとする。

```text
ResearchStageSpec =
  TheoryStageSpec
  | PrototypeStageSpec
  | DemonstrationStageSpec
  | OperationalExperienceStageSpec

# every typed Stage Spec includes
  stage_id

ResearchExecutionContext
  operational_node_id
  surface_cell_id?

ResearchProjectState
  research_definition_id
  current_stage_id
  stage_progress?  # only for progress-bearing Stage kinds
  priority
  paused
  execution_context?
  reservation_refs[]
```

Prototype / DemonstrationはOperational Nodeを基本Execution Contextとし、Cell-localなPhysical Environmentや位置そのものが必要な場合だけSurface Cellを追加する。EligibilityはSpatial / Environment / Capability / Knowledge等から判定し、有限Resource / ServiceはExecution Requirement Bundleで競合させる。Theory providerも所在地でローカル条件を満たしたAvailable Organization-scope capacityだけを供給する。

Theory / Prototype / Demonstration等のprogress-bearing Stageは確定Allocationだけでstage-local progressを進め、completionをcanonical boundaryで次Stageへsettleする。Prototype等でResource先行確保が必要な場合はReservationAcquisitionRequirementを利用する。最終Stage完了時だけTechnology Stateへunlockを記録する。

Operational ExperienceはProject時間やProject-owned progressとして複製せず、実Domain activityがKnowledge Stateへ蓄積した値をcompletion conditionとして参照する。新しいStage種別が異なるゲーム上の意思決定を追加する場合は、そのRequirement、progress ownership、completion、Application / UI契約を正準設計として追加する。

### 11.3 Operational Experience / Knowledge State

Operational ExperienceはResearch Projectが時間経過だけで生成するpointではない。Transport、Extraction、Manufacturing、Crewed Operation等の実Domain activityが共通interfaceを通じてexperience contributionを報告し、Knowledge Stateがcategoryごとの蓄積を所有する。Researchはこのstateをrequirementとして参照する。

Domainごとに同じExperience値を重複保存しない。Experience categoryはContentで定義でき、特定Location名やVehicle名をGeneric Core categoryへ埋め込まない。

### 11.4 Human operation abstraction

有人運用はcrew-ratedなVehicle / Facility property、Habitation / Life Support等のCapability / Service Capacity、消耗Execution Requirement / Supply Requirement、Environment Requirementから表現する。Crew個人・人口の配置、成長、リスクが独立したプレイヤー判断を構成する場合は、そのState ownershipと状態遷移を独立Domainとして定義する。

---

## 12. Scientific Exploration / Resource Survey

科学探査と資源Surveyを別Domain状態として扱う。

### 12.1 Scientific Exploration

Scientific Exploration Campaignは必要性能を満たすFleet unitをFleet Domainへ排他的にcommitし、one-shot Movement Executionとactive science executionを経て有限量のResearch Pointを得る。

Definitionは対象、必要Operation / Endurance / Payload、Capability / Environment、期間、有限RP総量 / 生成率、Resource / Service requirement、完了後Fleet disposition等を持てる。

Exploration DomainはFleet総数を直接所有せず、Fleet Domainのcommitmentを参照する。拘束中unitはTransport Allocationや別Exploration等へ同時利用できない。適合判定は用途タグではなくVehicle性能とMovement Planから行う。

active science executionはRP Pool admission headroomをExecution Requirement Bundleへ含める。Pool headroom不足分についてscience progressと`awarded RP`だけを進めず、有限Campaign rewardを暗黙消失させない。往路・帰路等のMovement progressはscience progressと分離する。

Pause中は新しいscience executionを進めないが、開始済みMovementはsettleする。Pauseだけでcommit Fleetをfreeへ戻さず、Abort / Return / Cancel等の明示transitionが必要な場合はCampaign lifecycleとして定義する。Campaign completion時はoriginへ戻す、destination Operational Nodeへ残す等のdispositionを明示し、Fleetを暗黙テレポートさせない。

### 12.2 Resource Survey

地表Resource Surveyは `SurfaceCell × Resource` のKnowledgeを更新する。固定Location × ResourceをSurvey正本にはしない。

```text
UNKNOWN
→ PRESENCE_PROBABILITY
→ ESTIMATED_RESOURCE_POTENTIAL
→ MEASURED_RESOURCE_POTENTIAL
```

各Levelは公開可能な情報schemaを持つ。Presenceは存在可能性、Estimatedは推定Potentialとuncertainty range、Measuredは投資判断に用いる測定済みPotentialを表す。具体的な精度はSurvey Provider / observation modeのContent parameterとする。

Survey Provider Definitionはsurvey rate、coverage / reach model、max Knowledge Level、observation precision、必要Operation / Infrastructure / source Capability、minimum source units等を持つ。Survey ServiceはproviderのSpatial contextとtarget Cellの関係からreachabilityを判定する。軌道Remote Survey providerは対象天体にSurface Locationが存在しなくても広域Cellを観測できる。

Fleet-backed Survey ProviderはSurvey Domainが `SurveyProviderAssignmentState` をauthoritativeなprovider-use intentとして所有し、そのStateがFleet Domainの排他的Fleet Commitmentを参照する。Fleet quantityと排他所有はFleet Domainだけが所有し、Survey Campaignへ複製しない。Player Commandはprovider用途へ配分する希望Fleet quantityを受け取り、Provider AssignmentからSurvey Service Capacityを導出してFacility providerの能力と同じExecution allocationへ供給する。

```text
SurveyProviderAssignmentState
  id
  provider_definition_id
  operational_node_id
  vehicle_definition_id
  fleet_commitment_ref
```

Survey Campaignは複数のSurface CellとResourceを一つのPlayer intentとして扱える。

```text
SurveyCampaignState
  target_cell_ids
  resource_ids
  goal_knowledge_level
  provider_constraint?
  observation_mode_constraint?
  activity_priority
  control_state
```

別の永続Region Entityを必須にせず、UIの地域選択はtarget_cell_idsへ解決する。CampaignはKnowledge Stateからscope内の未完了targetを導出し、完了済みtargetをactive allocationから外して余剰Survey Capacityを同じscopeの未完了targetへ再配分できる。scope外targetを追加せず、goal Knowledge Levelを越えて進行しない。同じKnowledge progressをCampaign Stateへ重複保存しない。

Provider / Observation Modeは物理的な能力差を表すDefinitionとして維持する。Campaignのscope / goalを満たす候補が一意、またはゲーム上同等ならCoreが決定論的に解決できる。必要Fleet拘束量、Resource消費、Reach、所要時間、Infrastructure Requirement、Knowledge上限等に戦略差がある候補が複数残る場合はApplicationへ候補差を返し、Playerがhard constraintを指定できる。登録順やID順だけで戦略的に異なる候補を暗黙選択しない。

PauseはCampaignのSurvey execution需要を停止するがProvider Assignmentを変更しない。Founding / Development等はSurvey内部Stateを直接読まず、typed Knowledge Eligibilityを通してtarget / subject / minimum levelを要求する。Survey KnowledgeはStatic Resource Potential自体とは分離し、Dynamic Physical Environmentも別Stateとして更新する。Scientific Exploration RPとSurvey Knowledgeを同一state machineへ混在させない。

## 13. Command / Query API

### 13.1 Command

主要カテゴリ：

- Time pause / resume / speed
- Operational Node founding deployment / Surface Location adjacent Cell develop
- Build / Upgrade / Cancel / Pause / Resume / Facility Decommission
- Surface-cell Facility placement where required
- Facility pause / resume / Process selection
- Activity Priority set (1..5)
- Vehicle produce / Fleet relocate / Fleet Retirement
- Transport Allocation create / update / pause / resume / delete
- Transport Allocation Directional Capacity target / Provisioning Priority / optional Movement hard constraint set
- Target Stock set / clear
- Supply routing hard constraint set / clear
- External Resource Market Buy / Sell Trade Order create / update / cancel
- Manual Cargo / special one-shot Movement
- Research start / pause / resume / Activity Priority / current `stage_id` Prototype or Demonstration Execution Context
- Fleet-backed Research Provider fleet quantity / Priority / pause / resume / release
- Scientific Exploration start / pause / resume / Fleet assignment / Abort / Return / completion disposition
- Fleet-backed Survey Provider fleet quantity / release
- Resource Survey start / update / pause / resume / target Cell scope / Resource scope / goal Knowledge Level / optional provider or observation-mode hard constraint
- External event response where an extension provides one

Command名は内部State名の変更を目的にせず、Player intentを一操作で表せることを優先する。Provider fleet quantity設定は内部的にAssignment create / resize / releaseへsettleしてよいが、その内部lifecycleを外部操作へ不必要に分解しない。

### 13.2 Query

主要Query：

- Catalog / World / Star System / Celestial Body Surface Map / Operational Node / Surface Location
- Surface Cell / Survey Knowledge / Resource Potential / Environment / development affiliation
- Inventory / Reservation / inbound / outbound / Storage / over-capacity
- Activity / Execution Requirement Bundle / requested execution / fulfillment / limiting factor
- Capability / Service Capacity / requested / allocated / spare
- Facility / placement scope / lifecycle / Decommission blocker / recovery potential / recoverable projection / selected Process / Process candidates / inputs / outputs / utilization
- Maintenance demand / fulfillment
- Build Options / Projects / Founding Options / Knowledge and Site blocker / future Supply Requirement / Projected Material Readiness
- Vehicle Production Options
- Spatial Relation / Movement Plan候補 / required Operation / latency
- Fleet / owner activity commitment / Transport Allocations / Provisioning Priority / Target・Nominal・Available・Used・Spare Capacity / Required Fleet Units / Retirement recovery projection
- Cargo Flow / handoff / arrival waiting / selected end-to-end path / routing hard constraint / Transport shortfall
- Target Stock / current stock / inbound amount / normal demand / additional stock demand
- Funds / Market Provider / Market Interface / buy-sell offer / Trade Order / commitment / settlement
- Research Point / Technology State / Research Provider Assignment / Fleet commitment / Research Projects / current typed Stage / Requirement / Operational Experience
- Scientific Exploration / Fleet commitment / RP admission blocker
- Resource Survey scope / goal / Knowledge distribution / resolved provider / observation mode / alternative strategic candidates / Survey Provider Assignment / Fleet commitment
- Location territory / Physical Environment summary / Surface Access Anchor / Surface Infrastructure demand and fulfillment
- external dependency analytics for selected Operational Node scope with CURRENT / FORECAST basis
- External Events where an extension provides them

Query DTOはJSON化可能なimmutableデータとする。UI側が可否・維持率・Movement適合・routing・provider selection・allocation・Projected Material Readiness・産業依存度等を再計算しない。

Queryは要求されたscopeを不必要に拡大しない。origin / destination、Operational Node、Entity ID等で対象が限定されている場合は、そのscopeから必要な派生状態を導出する。同一Application snapshot内で複数Queryが同じ派生状態を必要とする場合は同じprojection / indexを再利用し、各Query・各rowから全世界候補を再生成しない。read Queryはauthoritative Stateを変更せず、性能上の都合だけでDomain-owned derived indexを無条件にinvalidateしない。

## 14. Save / Load / Offline Progress

SaveはApplication単位のversion付きSnapshotとする。静的Definitionは `WorldDefinition` とContentから再構築し、可変Stateだけを復元する。Save metadataは `world_definition_id` と `scenario_id` を保持し、Load時にScenario初期化処理を再実行しない。

保存対象はdomain-owned authoritative StateをApplication snapshot内のdomain sectionとして保持する。少なくともOperational Node / Surface Location affiliation、Facility lifecycle / Process selection、Inventory / Reservation、Build / Development / Decommission / Founding Project、Vehicle Production、FleetPool / Fleet Commitment / Relocation / Releasing、Transport AllocationのDirectional Capacity target / Provisioning Priority / optional Movement hard constraint、Movement Execution、Target Stock、sparse Supply Routing Constraint、Cargo Flow / arrival waiting、Funds / Market State、Research Point / Technology / Research Project current Stage ID / Research Provider Assignment、Operational Experience、Exploration、Survey Knowledge / Survey Provider Assignment / Survey Campaign scope・goal・explicit constraint、Dynamic Physical Environment、canonical game day等を含む。

Static Star System / Celestial Body / Surface Cell topology / geology / Resource Potential / transport geometry / Market Provider DefinitionはWorld / Contentから再構築する。Movement Plan候補、Transport Service Plan、auto-selected source / end-to-end path、Required Fleet Units、Nominal / Available Capacity、auto-selected Survey provider / observation mode、Survey未完了target展開、salvage recoverable projection、Location Environment summary、Projected Material Readiness、tick内Requirement / allocation結果、external-dependency Analytics等の派生・transient状態は保存せず再導出する。

Offline Progressは通常Simulationと別ルールにせず、実時間経過をゲーム時間へ換算して同じ1 game dayのcanonical advance経路を使う。通常進行、高速進行、Offlineで同じgame timeを進めた結果が同じStateになることを不変条件とする。fast-forwardは日次tick列と同値な区間をまとめる実装最適化としてのみ利用する。

## 15. Validation / Test

Configuration Validationは、未定義Resource / Facility / Vehicle / Movement Operation参照、無効Eligibility / SiteRequirement、存在しないCapability / Service type、負の容量・率・期間、Priority範囲外、Facility Recipe / Maintenance / Decommission recovery、Vehicle Production、Transport Allocation、Spatial topology、Founding target / Deployment Recipe、Research Stage / Technology / Experience category、Survey Provider、Market Definition等の参照不整合を検出する。Research DefinitionではStage listが非空であること、`stage_id` の一意性、各typed Stage Specの必須fieldを検証する。Technology prerequisiteの未定義参照・自己参照・循環、表示段階とdependency方向の自己矛盾、Allocation dependency graphの循環もfail-closedとする。

Runtime Validationは、Inventory / Reservation / Cargo / Funds / Fleetの保存と二重所有、Execution / Admission / Reservation settlement超過、Transport Capacity二重消費、Facility / Project / Movement lifecycle不整合、Research Point Pool capacity、Technology / Knowledge重複正本、Market commitment、Facility Decommission、Fleet Retirement / Commitment、Location領域、Facility placement等を検査する。

ゲーム性評価段階で優先するテストは次の契約へ集中する。

- Resource / Cargo / Funds / Fleetの保存とauthoritative ownershipが一意である。
- Execution Requirement BundleがResource / Service / admissionを同じexecution fulfillmentでsettleする。
- Eligibility判定だけで有限Serviceを消費扱いにせず、同じServiceを複数Activityが共通Allocationで競合する。
- PriorityLevelが5段階ordinal bandとして機能し、同順位結果が登録順に依存しない。
- Supply Planningが現地用途と同じInventory / Transport Capacityを二重利用せず、Inbound Cargoを重複dispatchしない。
- 通常物理Resourceがdefaultまたは明示special Storage poolを通じて有限Storage accountingへ参加し、pool未指定を通常Resourceのunlimited escape hatchにしない。
- 通常Supply RequirementはTarget Stock未設定でも補給され、Target Stockは追加備蓄需要だけを生成しInventory ReservationとしてStockを隔離しない。
- routing hard constraintがない通常状態では、成立済みNetwork内のsource / pathをlatency・運用Resource・handoff・利用可能capacity等から決定論的に選択する。hard constraintが成立しない場合は別戦略へfallbackせず、auto-routingがTransport AllocationやFleet等を変更しない。
- Cargo arrival / direct handoff / Inventory admission / arrival waitingが有限constraintとResource ownershipを一貫して扱う。
- snapshot後の生成・到着・Commandが同tick過去phaseへ遡及しない。
- 通常進行 / 高速進行 / Offlineで同じgame timeの結果が一致する。
- Facility Processは複数候補時にPlayer選択を要求し、登録順で暗黙決定しない。
- Facility Build / Upgrade Recipeが有限個の明示Resourceを消費し、Resource種類数をGeneric Coreの固定上限にしない。
- 維持需要が累積投入Resourceとmaintenance fractionから決定論的に導出される。
- Extraction responseがCapacityに対して単調非減少・限界収益逓減で、Content固有任意関数へ分岐しない。
- Surface Infrastructure負荷をOpportunity等へ二重適用せず、core cellへ暗黙fallbackしない。
- Operational Node Foundingがprepared Resource / FleetをsourceからMovement payloadへ移し、target typeに応じたStateへ一度だけsettleする。
- Founding / DevelopmentのKnowledge Requirementが対象subjectとminimum levelを明示し、無関係なSurvey Knowledgeで満たされない。
- Fleet unitがowner activityを跨いで二重commitされず、Transport Allocationのauthoritative targetがDirectional CapacityでRequired Fleet Unitsを派生し、Transport Provisioning Priorityが別Activityのcommit Fleetをpreemptしない。
- Transport Pauseがtargetを保持しつつsafe releaseを行い、one-shot Campaign Pauseが開始済みMovementを巻き戻さない。
- Facility Decommission / Fleet Retirementで既存在庫を暗黙消去せず、salvageは全Resourceへ共通recoverable fractionを適用し、全量admission不能でもAsset removalを永久blockしない。
- Scientific ExplorationはRP Pool headroom不足時に有限RPを消失させず、science progress / RP settlementを整合させる。
- Research Definitionのtyped ordered StageとProject current stageが一致し、最終Stage完了時だけTechnology Stateを更新する。
- Prototype / DemonstrationのExecution ContextがOperational Node / optional Surface Cellを正しく検証し、有限ServiceはAllocationで競合する。
- Survey Knowledge levelごとの公開情報、provider coverage / max level、Remote Surveyが正しく成立し、multi-target Campaignが指定scope / goalだけを進める。Fleet-backed Survey Provider AssignmentのFleet ownershipとCampaignのService Capacity消費を分離し、戦略差のあるprovider / modeを登録順で暗黙選択しない。
- External-dependency AnalyticsがCURRENT / FORECASTを区別し、派生Stateとして再導出される。
- Save / Load後の将来進行が一致し、Scenario初期化を再適用しない。
- Generic CoreへLocation / Celestial Body / Vehicle用途名等のContent固有分岐が侵入しない。

暫定価格、日数、生産量、特定攻略順等の仮バランスを構造テストで固定しない。

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

UIは天体Surface MapでSurvey状態、Resource Potential、Environment、Location領域、初期Location候補・Founding Deployment blocker、隣接開発候補、位置依存Facilityの配置候補を表示する。Surface Locationがまだ存在しない天体でも、non-surface Operational NodeからのRemote Survey、候補Cell比較、staging node、typed Founding target、Deployment Recipeを含む設立判断を同じMap上から追えるようにする。通常Facilityの建設・運用は設備一覧・Inspectorを中心とし、不要なCell選択を要求しない。設備一覧・InspectorではProcess inputs / outputs、Activity Priority、Execution Requirement / allocation、Service Capacity fulfillment、maintenance fulfillment、Vehicle production blocker等を安定配置で表示する。Fleet / Transport UIでは所在Operational Node・総数・用途配分、Retirement commitment、Directional Capacity target、Provisioning Priority、必要・投入隻数、Nominal / Available / Used / Spare Capacity、Movement latency、運用Resource需要、Cargo Flow / arrival waiting、blocker / limiting factorをApplication Queryから表示する。通常auto-routingの選択結果と必要なhard constraintも確認可能にする。Market UIではFunds、Market Interface、buy / sell offer、availability、Trade Order target / commitment / settlement、物流blockerを表示する。Location / region分析ではlocal production、imports、unmet demand等のロケーション産業自立・外部依存状態を表示できる。Survey UIではMap上のCell scope、Resource scope、goal Knowledge Levelを主要操作とし、resolved provider / observation modeを表示する。provider / observation modeに戦略差がある場合だけ候補差とhard constraint操作を提示する。Asset disposalではrecovery potentialと見込回収量を区別して表示する。必要情報を隠してUIを簡略化しない。

Presentationの正本は `ui.md` とする。BrowserはNavigation / Decision Canvas / Context InspectorのDecision Contextを保持し、別Canvasへの遷移でも関連Entity、Resource、blocker等のContextを引き継げる。ApplicationはBlocker、limiting factor、Current / Target / Preview、候補差等を文字列解析に依存しない構造化DTOとして返し、UIにDomain判定の再実装を要求しない。

Fast Previewはauthoritative Stateを変更しないQueryとして扱い、要求scopeを不必要に拡大せず同一snapshotのprojection / indexを再利用する。Structured DecisionのDraftはPresentation側の一時状態であり、Commit時はbase revisionに対してPlayer intentをatomicに適用する。Planning Modeによるpause / speed制御はRuntime schedulingだけを制御し、canonical Simulation semanticsを変更しない。

LLMはFAST PATHへ入れない。

FAST PATH：Resource / Service Capacity allocation、生産、建設、維持、物流、Research Point、Research / Knowledge、Exploration、Survey、Offline Progress。

SLOW PATH：外部組織要求、イベント、交渉、研究上の問題、状況依存Mission。

LLMはCore Stateを自由に書き換えず、検証可能なCommand / Eventへ変換して適用する。

---

## 17. 横断Architecture invariant

この節は各Domain節の詳細規則を再掲する一覧ではなく、変更時に複数Domainへ同時適用する不変条件を示す。具体的な型、状態遷移、処理順は対応する正準節を参照する。

1. **State ownershipを一意にする。** Definition / State、Spatial context / Operational Node、Inventory-owned Resource / Logistics-owned Cargo、FleetPool / Fleet Commitment等を担当Domain間で重複所有しない。
2. **Content固有例外ではなく共通条件をモデル化する。** Location名、天体名、Vehicle用途名、研究名をGeneric Coreの分岐条件にせず、Environment、Capability、Service Capacity、Operation、Spatial Relation、typed Requirementで表す。
3. **Eligibilityと有限Allocationを分離する。** Site / Knowledge等の非消費条件と、Resource / Service / admissionの競合利用を同じ可否判定へ混在させない。
4. **有限Resource / Serviceの競合を共通Allocationで解く。** Activity Priority、Execution Requirement Bundle、Reservation、Stock / Pool admissionをDomain処理順から分離し、同順位結果を登録順へ依存させない。
5. **Transport Provisioningと需要利用を分離する。** Provisioning PriorityはTransport Allocation間のfree Fleet配備を所有し、Activity Priorityは既存Transport Capacity利用を順位付けする。別Activityへcommit済みFleetをpriorityだけでpreemptしない。
6. **MovementはSpatial relationと実能力から導出する。** 任意の成立済みOperational Node pairを一般則で評価し、静的OD列挙や技術IDによる直接航路解除を正本にしない。
7. **通常物流はaggregate serviceとして扱いながら物理保存を守る。** Transport Capacity、Cargo Flow、direct handoff、Inventory admission、arrival waitingを一つのCargo lifecycleへ接続する。
8. **Player戦略と運用自動化を分離する。** PlayerはAsset、Capacity、Priority、Target Stock、必要なhard constraintを所有し、Coreは成立済みNetwork内の通常source / path選択やSurvey scope内の能力配分を決定論的に行う。自動化は新しいAsset、Transport Capacity、Trade Order、Target Stockを暗黙生成せず、hard constraint不成立時に別戦略へfallbackしない。
9. **Pauseは物理Stateを巻き戻さない。** 設定・progressを保持しつつ、reversible commitmentの保持 / releaseは所有Domainの明示契約で決め、開始済みMovement / Cargo / Market settlementを消去しない。
10. **Surface Cellを万能Entityにしない。** Surface Cellは物理地理・資源・環境・開発領域の単位とし、通常Inventory / Logistics Nodeや一般Facility slotへ兼用しない。
11. **同じ効果を複数係数で適用しない。** Surface Infrastructure、Maintenance fulfillment等の共通bottleneckは所有Requirement / Serviceへ一度だけ反映する。
12. **派生状態を保存正本へ昇格させない。** Transport Service Plan、current Capacity、Analytics、Query projection等はauthoritative StateとDefinitionから再導出する。
13. **Application・Persistence・Validationまで同じ契約を貫く。** UIはDomain判定を再計算せず、Saveはdomain-owned authoritative Stateのみを保持し、Validationは不変条件とState ownershipを検査する。
14. **抽象化は共有される意味へ限定する。** 複数Domainや同種Contentが同じState ownership・保存則・Requirementを共有するときに共通契約を置く。新しいゲーム上の意味が必要になった場合は、その責務を正準設計へ追加してからCoreを拡張する。

## 18. アーキテクチャ定義の要約

本作のCoreは、Research / Knowledgeの成長、物理的な産業拡大、空間的な拠点拡大、それを支えるResource / Service Capacity / Movement / Logisticsを一つの状態モデルへ接続する。

World Definitionは静的宇宙・地理・物理基準を定義し、Scenario Definitionはnew game時のPlayer所有・運用Stateだけを構成する。Spatial contextとOperational Nodeを分離し、Surface Locationはconnected developed-cell領域を追加所有するOperational Nodeとして扱う。新しいOperational Nodeの成立は共通Founding lifecycleを利用し、Surface / non-surface targetの物理差はtyped target specで表す。

有限Resource / Serviceの競合は5段階Activity PriorityとExecution Requirement Bundleで解き、Eligibilityと有限Allocationを分離する。Research ProjectはTheory / Prototype / Demonstration / Operational Experienceのtyped ordered Stageから必要な組合せを持ち、Technology表示段階とは別概念とする。Vehicleは同一Definition・所在NodeごとのFleet数量と排他的Fleet Commitmentで管理し、TransportのProvisioning PriorityはTransport Allocation間のfree Fleet配備だけを扱う。

通常物流はTransport CapacityとCargo Flowで表し、Resource ownershipをInventory / Logistics間で一意に保つ。Logistics PlannerはPlayerが成立させたNetworkと必要なhard constraintの範囲でsource / end-to-end pathを正準評価により決定論的に選ぶ。Playerが経路を戦略的に固定する場合だけhard constraintを保持し、そのconstraintが成立しない場合は別戦略へfallbackしない。FundsはExternal Resource MarketにおけるResource ownership transfer専用の決済Stateとする。

Simulationは1 game dayのcanonical boundary → snapshot → intent → planning → allocation → execution → movement → state transitionで決定論的に進行し、通常速度・高速進行・Offlineで同じgame timeの結果を一致させる。Saveはdomain-owned authoritative Stateだけを保持し、派生状態は再導出する。

Generic CoreはEarth、Moon等の固有名や未要求の万能frameworkではなく、実際に複数Domainで共有されるState ownership、保存則、Requirement、Allocation、Movement、settlement契約を一般化する。
