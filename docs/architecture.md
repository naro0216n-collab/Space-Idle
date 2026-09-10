# 宇宙開発Idleゲーム アーキテクチャ設計 v0.4.0

## 1. 文書の目的

本書は「宇宙開発Idleゲーム デザイン案」とSimulation Core実装の間に置くアーキテクチャ上の共有基準を定義する。

対象は個別の仮バランス数値ではなく、状態所有、Generic CoreとContentの分離、Location・環境・Facility・Capability・資源・建設・維持・物流・Vehicle・Research・Exploration・Surveyの関係、Application境界、Save/Load・Offline Progress、検証・拡張原則である。

現行の正準化対象実装はゲーム本体 `0.5` とする。ただしゲーム性評価段階では実装より本書とデザイン上の合意を優先する。本書で合意済みだが0.5時点で未実装の項目は次期developで実装する対象であり、旧API・旧データ・旧Saveとの後方互換を理由に不適切な構造を温存しない。

---

## 2. 全体構成

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
  Spatial / Facility / Power / Storage
  Inventory / Industry / Construction / Maintenance
  Logistics / Vehicle / Research / Exploration / Survey / Contracts
    ↓
Content Definitions
    ↓
Persistence / Validation
```

依存方向は原則として上から下とする。UIやHTTP層はDomain Serviceへ直接アクセスしない。Generic CoreはEarth、Moon、Mars、iPad、Web、LLM等の固有概念を知らない。

---

## 3. 層の責務

### 3.1 Generic Core

世界で共通に成立する規則を担当する。

- Spatial NodeとEnvironment Facet
- SiteRequirements
- Facility Definition / State
- Capability
- Facilityの資材維持需要と保守充足率
- Inventory、Reservation、Storage
- Power配分
- Process / Industry
- Extraction / Deposit
- Construction Project
- Transport Operation、Route、Transport Allocation、Transport Capacity、Cargo Flow、特殊Transport Mission
- Vehicle Definition / Fleet State / Production / Maintenance / Relocation
- Research Point、Research状態機械
- Scientific Exploration Campaign
- Resource Survey / Knowledge
- Contract状態機械
- 時間進行

Generic Coreへ `if location == MoonSouthPole`、`if vehicle_type == lunar_lander`、用途allowlist等を持ち込まない。必要条件は環境Facet、Capability、Operation、Vehicle性能、Resource等で表現する。

### 3.2 Content Layer

具体的な遊びを定義する。

- Celestial Body / Spatial Node
- 初期Environment
- Resource Definition
- Facility Definition
- Process Definition
- Construction Recipe / maintenance rate
- Deposit / Extraction Definition
- Research Definition / Research Provider
- Scientific Exploration Definition
- Survey Target
- Route / Vehicle / External Transport Service
- Contract / Event Definition
- 初期施設・Vehicle・資金・在庫
- 表示名

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

1ゲーム日の処理順序を統括する。各Domainが別Domainの登録順や暗黙の呼出順へ依存しないようにする。

概念順序：

```text
Power Snapshot
→ Storage Service
→ Production / Extraction
→ Research Point generation / Research
→ Scientific Exploration / Resource Survey
→ Facility maintenance demand / fulfillment
→ Construction procurement
→ Transport availability snapshot
→ Logistics lane allocation / Cargo Flow dispatch and progression
→ Construction execution
→ Storage refresh
→ Contracts / events
→ day update
```

順序がゲームルールとして意味を持つ場合はOrchestratorで明示する。

---

## 4. DefinitionとStateの分離

静的Definitionと可変Stateを分離する。

例：

```text
FacilityDef
  id
  display_name
  installation_environment
  operating_environment
  capability_supplies

FacilityState
  entity_id
  definition_id
  location_id
  level
  paused
  power_priority
```

同様にVehicle、Transport Allocation、Research、Scientific Exploration、Survey、Construction Recipe等でもDefinitionと可変Stateを分ける。

Vehicle Definitionは性能と製造・整備要件を持つ。通常運用するVehicleは同一Definition・所在地点ごとのFleet Stateとして数量管理し、輸送、Scientific Exploration、再配置、回収中等の排他的配分をFleet Domainが所有する。

Transport Service PlanとTransport Capacityは、Fleet Allocation、Route、Vehicle性能、Resource、Infrastructureから導出する派生状態とし、Save上の独立した正本にしない。

静的DefinitionはSaveへ複製しない。

---

## 5. Spatial / Environment / SiteRequirements

Celestial Bodyと、Inventory・Facility・Fleetが実際に存在するSpatial Nodeを分離する。

```text
Earth
├ Earth Surface
└ LEO

Moon
├ Lunar Orbit
├ South Polar Surface
├ Polar Cold Trap
└ Nearside Surface
```

Spatial NodeはGravity、Atmosphere、Illumination、Thermal、Surface、Orbital、Communication等のFacetを持つ。天体所属、移動関係、環境継承を同一視しない。

施設設置、Facility運転、Research Prototype / Demonstration、Route端点等の可否は共通SiteRequirementsを使用する。

Capability Requirementは少なくとも以下を区別する。

- Infrastructure Capability：設備として存在する能力
- Active Capability：停止されず環境適合している定格能力
- Available Capability：電力・保守充足率等を反映した現在利用可能な能力

---

## 6. Facility / Maintenanceモデル

### 6.1 設置と運転

Installation EnvironmentとOperating Environmentを分離する。先行建設や将来の環境変化をLocation特例なしで扱えるようにする。

### 6.2 Pause

PauseしてもFacilityは消滅しない。通常運転に伴う生産、採掘、発電、建設能力、研究能力、Survey能力、Available Capabilityは停止する。

一方、安全維持・保冷等のstandby loadと物理的維持に必要なResource Demandは通常Pauseだけでは消滅しない。将来のMothballはPauseとは別状態とする。

### 6.3 資材維持需要

Facilityは建造・Upgrade時に実際に投入されたResourceを基礎に維持需要を持つ。

```text
maintenance_demand(resource, period)
= cumulative_invested_resource × maintenance_fraction(period)
```

維持率はContent Definitionのバランス値とする。維持資材は特別な税処理ではなく通常Resource DemandとしてInventory / Logisticsへ流す。

資材不足時はFacilityを即時破壊せず、maintenance fulfillmentを0..1で算出し、Available Capability、生産率、Research Point生成等へ共通係数として反映できる構造を基本とする。

---

## 7. Inventory / Storage / Power

InventoryはLocationごとの所有資源を表し、在庫、予約、利用可能量、輸送待ち、輸送中、到着待機を区別する。

StorageはPhysical CapacityとService Capacityを分けられる。輸送中Cargoは目的地Storageを事前予約せず、実到着時にだけ入庫判定する。入らない分はarrival waitingとして物流Domain側へ残す。

PowerはLocationごとのフロー制約とする。同一優先度帯では登録順ではなく比例配分し、可能な設備は部分稼働させる。

---

## 8. Industry / Extractionモデル

### 8.1 Process

FacilityそのものとProcessを分離する。Processはinputs、outputs、基準処理能力、電力等を持つ。

Application Queryは設備ごとの選択Process、実効inputs / outputs、稼働率、limiting factorを返す。UIは「何を消費して何を作るか」をFacility画面から直接確認可能にする。

### 8.2 資源競合

複数Processが同一Resourceを要求する場合、Facility登録順で資源を奪わせない。電力、原料、Storage等を反映した配分を行う。

### 8.3 Extraction

ExtractionはDeposit / Knowledge / ExtractionSpecから成立させる。

月面等ではSurveyによってKnowledgeを段階的に得る。初期地球産業では開始時から既知のDepositをContentとして定義し、低効率の地球採掘Facilityを利用可能にできる。EarthというLocation名へのCore特例は作らない。

---

## 9. Constructionモデル

### 9.1 建設能力

Construction CapacityはLocation固定値ではなく、建設ヤード、施工設備、ロボット、移送可能な建設機械等から発生するフローとする。

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

Build Projectは少なくとも建設地点、進捗、調達状態、予約、調達元、経路、各Legの輸送方式、priority / allocation、pause状態を持つ。

PauseとCancelを分離する。

---

## 10. Logistics / Vehicleモデル

TransportはVehicle / Fleetから輸送能力を供給し、Logisticsはその能力をResource Demandへ配分する。通常物流で個体Vehicle Missionを繰り返し生成せず、Fleet Allocationから定常Transport Capacityを導出する。

### 10.1 Transport Operation / Route

Route可否は用途名でなくOperation要件と実性能から判定する。

- Powered Ascent
- Spaceflight
- Landing
- Atmospheric Entry

必要に応じてDelta-v、Thrust、Endurance、Atmosphere、Gravity、Landing、Docking / Refueling Infrastructure等を使う。Launch Vehicle / Spacecraft / Lander等の名称は表示に利用できるが、可否判定には使わない。

研究技術IDをRouteの直接解除条件にせず、研究で解禁されたVehicle、推進、補給、Infrastructure等の実能力から到達可能性を決める。

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

通常運用のVehicleは個体IDではなく、Vehicle Definition × Location単位のFleet Stateとして管理する。Fleet Stateは少なくとも総数と、Transport Allocation、Scientific Exploration、relocation、releasing等への排他的配分を持つ。未配分数はそれらから導出する。

### 10.3 Vehicle Production / Fleet relocation

ロケットや宇宙船は外部Serviceだけでなくプレイヤーが建造できる。対応Capability、2〜3種類程度の実Resource、時間を消費してProduction Stateへ入り、完了後は建造地点のFleetへ数量を追加する。

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

推進剤・servicing等の可変運用需要はAllocation最大値ではなく実際のService利用率から発生させる。Available Capacityはそのtick開始時点のResource / Infrastructure snapshotから決め、同tick中に到着したResourceで遡及的に増加させない。

External Transport ServiceはFleet Allocationを持たず、同じTransport Capacity interfaceへ直接能力を供給できる。

### 10.5 Logistics Lane / Cargo Flow

定常物流の主要設計対象は品目別補充ルールではなく、拠点間輸送能力、方式、Fleet配分、Lane priorityとする。

Facility、Construction、Maintenance、Industry等はResource Demandを生成する。Laneはrequested capacityとpriorityを持ち、Transport AllocationやExternal Serviceから生成された共有Transport Capacityへ需要を配分する。

Transport Allocation targetは「どれだけ輸送能力を用意するか」、Lane requested capacityは「その能力をどれだけ物流需要へ利用するか」を表す。Lane需要からFleetを暗黙に増員しない。

通常物流の実行は個体Vehicle MissionではなくCargo Flowとして表現する。利用したcapacityに応じてCargo Flow Batchを生成し、Service latency後に目的地Inventoryへ到着させる。輸送中Cargoは目的地Storageを事前予約せず、実到着時に入庫判定する。容量不足分はarrival waitingとしてLogisticsが保持する。

### 10.6 End-to-End / Special Mission

プレイヤーは原則として出発Nodeと最終目的Nodeを指定できる。経路未指定時は明示Policyに従ってTransport Capacity Network上のpathを選択し、中継Nodeごとの再発送Commandを要求しない。

End-to-End能力は経路上の共有capacityと競合需要から決まる。同じFleetが途中NodeでCargoを引き渡さず連続運行できる場合は一つのTransport Serviceとして扱い、別Fleetへ引き渡す地点だけをLogistics上のhandoffとする。

LEOやLunar OrbitはInventory / refueling / transfer / servicing Nodeとして利用できるが必須進行ゲートではない。プレイヤーが明示したVehicle / Service / pathが利用不能になった場合は、明示Policyがない限り別方式へ勝手にfallbackしない。

有限・状況依存の特殊輸送はTransport Missionとして別途扱ってよい。通常のLane物流をMissionへ戻さない。
---

## 11. Research Point / Researchモデル

Research Pointは通常貨物Inventoryとは分離した知識資源とする。

Research ProviderはTierとLevelを持てる。

- Tier：研究手段の世代差・基礎効率差
- Level：同一世代設備への増設・拡張・改良

研究源ごとに「この分野にしか使えないRP」という適用範囲は原則設けず、差は生成率、貯蔵容量、建造・維持要求で表現する。

Research Definitionは必要に応じてTheory、Prototype、Demonstration、Operational Experienceを持つ。

研究技術IDをRouteの直接解除キーにしない。研究はVehicle、設備、推進、補給、製法等を解禁し、実際の到達可否はOperation要件・Vehicle性能・Infrastructureから決める。

貯蔵容量低下で既獲得RPを消去せず、新規生成を制限する。

---

## 12. Scientific Exploration / Resource Survey

科学探査と資源Surveyを別Domain状態として扱う。

### 12.1 Scientific Exploration

Scientific Exploration Campaignは必要性能を満たすFleet unitを一定期間拘束し、科学観測・近接探査・有人活動等から有限量のResearch Pointを得る。

Definitionは対象、必要Operation / Delta-v / Endurance、必要Payload / Capability、必要環境・Infrastructure、期間、RP報酬、消耗Resource等を持てる。

Exploration DomainはFleetの所有状態を直接変更せず、Fleet Domainへ必要unit数の排他的reservationを要求する。拘束中unitはTransport Allocationや別Explorationへ利用できない。適合判定は「探査船」という用途タグではなく実性能から行い、Enduranceは往路・活動・必要な帰還を含むCampaign運用計画全体に対して判定する。

同一Campaignから無限RPを生成しないことを基本とする。

### 12.2 Resource Survey

Resource SurveyはLocation × ResourceのKnowledgeを更新する。

```text
Unknown
→ Presence Probability
→ Concentration
→ Reserve
→ fully surveyed
```

完了CampaignはSurvey能力配分対象から外し、余剰能力を未完了Campaignへ再配分する。

科学探査のRP獲得とResource SurveyのKnowledge更新を同一状態機械へ混在させない。

---

## 13. Command / Query API

### 13.1 Command

主要カテゴリ：

- Time pause / resume / speed
- Build / Upgrade / Cancel / Pause / Resume
- Construction priority / allocation / procurement route
- Facility pause / resume / process / power priority
- Vehicle produce / Fleet relocate
- Transport Allocation create / update / pause / resume / delete
- Logistics Lane create / update / pause / resume / delete
- Manual Cargo / special Transport Mission
- Research start / pause / resume / prototype / demonstration
- Scientific Exploration start / pause / resume / Fleet assignment
- Resource Survey start / pause / resume / allocation
- Contract / external event response

現地材比率・代替材選択Commandは持たない。

### 13.2 Query

主要Query：

- Catalog / World / Location
- Flow / Bottleneck
- Facility / Process inputs / outputs / utilization
- Maintenance demand / fulfillment
- Build Options / Projects
- Vehicle Production Options
- Logistics / Routes / Fleet / Transport Allocations / Transport Capacity / Cargo Flow / Lanes / special Missions
- Research Point / Research
- Scientific Exploration
- Resource Survey
- Contracts / Events

Query DTOはJSON化可能なimmutableデータとする。UI側が可否・維持率・経路適合等を再計算しない。

---

## 14. Save / Load / Offline Progress

SaveはApplication単位のversion付きSnapshotとする。静的Definitionは現在Contentから再構築し、可変Stateだけを復元する。

保存対象にはFacility、Inventory、Project、Vehicle Production、Fleet数量と用途配分、Transport Allocation target、Fleet Relocation / Releasing、Cargo Flow / arrival waiting、特殊Mission、Research、Exploration、Survey、Deposit remaining、Environment Overlay等を含める。Transport Service Plan、Nominal / Available Transport Capacity等の派生状態は保存せず、Load後に再導出する。

ゲーム性評価段階ではschema/content migrationを目的化しない。

Offline Progressは通常Simulationと別ルールにせず、実時間経過をゲーム時間へ換算して同じadvance経路を使う。

---

## 15. Validation / Test

Configuration Validation：

- 未定義Resource / Facility / Route / Vehicle参照
- 無効SiteRequirement
- 存在しないCapability
- 負の容量・率・期間
- Construction Recipeの不正Resource数・参照
- Vehicle Production / Maintenance定義不整合
- Transport Allocationの未定義Vehicle / Route / 不正control mode
- Research / Exploration / Survey参照不整合

Runtime Validation：

- 在庫負値、予約超過
- Cargo質量不整合
- Fleet総数とTransport / Exploration / Relocation / Releasing配分の不整合
- Transport AllocationのUNITS / CAPACITY二重正本
- Transport Capacityの二重消費
- Vehicle Production / Fleet Relocation状態不整合
- Facility maintenance demand / fulfillment不整合
- Research Point負値・容量処理不整合
- 孤立Reservation / Entity参照

ゲーム性評価段階で優先するテスト：

- 資源保存・物流会計
- 輸送中Cargoが目的地Storageを事前予約しない
- Construction Recipeが2〜3種の実Resourceを直接消費する
- 産地代替層が建設可否へ介入しない
- 維持需要が累積建造投入量から決定論的に導出される
- 維持不足がFacility能力へ一貫して反映される
- Vehicle建造がCapability・Resource・時間を消費する
- Fleet unitがTransport / Exploration / Relocationへ二重割当されない
- Transport AllocationのUNITS / CAPACITY targetが単一正本である
- CAPACITY modeの必要Fleet数が一時的なResource不足で自動膨張しない
- Nominal / Available / Used capacityが同じService Planから一貫して導出される
- 複数Laneが共有Transport Capacityを二重消費しない
- Cargo Flowの資源保存とlatencyが成立する
- Operation適合が名称・用途タグに依存しない
- Research Pointの生成・貯蔵不変条件
- Pause / Resume
- 登録順依存排除
- Save / Load後の将来進行同値性
- Offlineと通常進行の同値性
- Generic CoreへのLocation固有分岐侵入検知

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

UIは設備一覧・InspectorでProcess inputs / outputs、maintenance fulfillment、Vehicle production blocker等を安定配置で表示する。Fleet / Transport UIでは所在・総数・用途配分、Allocation mode / target、必要・投入隻数、Nominal / Available / Used / Spare Capacity、運用Resource需要、blocker / limiting factorをApplication Queryから表示する。必要情報を隠してUIを簡略化しない。

LLMはFAST PATHへ入れない。

FAST PATH：生産、建設、維持、物流、Research Point、Research、Exploration、Survey、Offline Progress。

SLOW PATH：外部組織要求、イベント、交渉、研究上の問題、状況依存Mission。

LLMはCore Stateを自由に書き換えず、検証可能なCommand / Eventへ変換して適用する。

---

## 17. 変更時に守るアーキテクチャ原則

1. 地点名で例外処理せず、条件をモデル化する。
2. DefinitionとStateを分離する。
3. 設備の存在と現在利用可能な能力を分離する。
4. 所有在庫・輸送中・到着待機・Storage占有を混同しない。
5. 遠距離輸送中Cargoで目的地Storageを事前予約しない。
6. 自動化は反復処理を担当し、研究・物流・産業配置等の戦略判断を暗黙代行しない。
7. 自動選択には明示的で一貫したPolicyを持つ。
8. 同順位・同条件の結果をEntity登録順へ依存させない。
9. UIへDomain内部構造を公開せずCommand / Query境界を通す。
10. blocker / limiting factorはCore / Applicationが説明する。
11. Saveは可変Stateを保存し、派生状態を再計算する。
12. Offline Progressは通常Simulationと同じ経路を使う。
13. ゲーム性評価段階では後方互換を目的化しない。
14. 暫定バランス数値をテストで過度に固定しない。
15. 個別不具合を特殊分岐で塞ぐ前に共通モデル不足を疑う。
16. Celestial BodyとSurface / Orbit等のSpatial Nodeを分離する。
17. Transport可否はVehicle用途名ではなく実性能とOperation要件で判定する。
18. 発展段階や研究名を物流・航路の強制ゲートへ転用しない。
19. 建設は2〜3種類の実Resourceを直接消費し、現地代替レイヤーを持たない。
20. Facility維持は建造投入Resourceから導出した通常Resource Demandとして扱い、Pauseだけで回避できない。
21. Vehicle建造はCapability・実Resource・時間を消費する通常の資産生産として扱う。
22. Scientific ExplorationによるResearch Point獲得とResource SurveyによるKnowledge更新を分離する。
23. Process inputs / outputs、維持状態、Vehicle建造条件等の意思決定情報をApplication QueryからUIへ明示する。
24. 通常Vehicleは所在地点ごとのFleet数量として管理し、用途間の排他的配分をFleet Domainが所有する。
25. Transport Service PlanとTransport CapacityはFleet Allocation等から導出し、独立した保存正本にしない。
26. Transport AllocationのUNITS / CAPACITYは一方だけをauthoritative targetとする。
27. LogisticsはFleet Stateを直接操作せず、Transportが供給する共有Capacityを消費する。
28. 通常物流はCargo Flowとして扱い、個体Vehicle Missionを反復生成しない。
29. Fleet Allocation解除・地点間再配置には回収・移動時間を持たせ、aggregate Fleetを瞬間移動させない。

---

## 18. 現行モジュールとの対応

| 領域 | 現行/想定責務 |
|---|---|
| `spatial.py` | Spatial Graph、Environment Facet |
| `site.py` | SiteRequirements / Capability Requirement |
| `facilities.py` | Facility Definition / State / Capability |
| `power.py` | Power配分 |
| `inventory.py` / `storage.py` | Inventory / Reservation / Storage |
| `industry.py` / `production/` | Process inputs / outputs / production flow |
| `construction/` / `projects.py` | Construction Recipe、Project、調達、能力配分 |
| maintenance domain（導入対象） | Facility maintenance demand / fulfillment |
| `transport/` | Operation、Route、Vehicle Definition、Fleet State、Vehicle production、Transport Allocation、派生Service Plan / Capacity、Fleet relocation |
| `logistics.py` / logistics domain | Resource Demand、Lane、共有Capacity配分、Cargo Flow / pipeline、arrival waiting |
| `research.py` | Research Point、Tier / Level、Research状態機械 |
| exploration domain | Scientific Exploration Campaign / Fleet reservation / RP reward |
| `survey.py` | Resource Knowledge、Survey Campaign、Extraction |
| `simulation.py` | 時間進行・処理順序 |
| `application*.py` | Command / Query / DTO |
| `persistence.py` | Snapshot / Load / Offline resume |
| `validation.py` | Configuration / Runtime invariant |
| `content/` | ゲーム固有Definition |
| `composition/` | DomainとContentの配線 |

現行実装がこの責務境界と一致しない箇所は、旧Mission / 個体Vehicle経路を互換層として温存せず、変更単位ごとに新しいFleet / Capacity契約へ置換する。

---

## 19. 現時点のアーキテクチャ定義

本作のCoreは、

**「天体と地表・軌道等のSpatial Nodeを分離し、環境・設備・能力・Vehicle性能・Transport Operation・資源・物流・維持需要・研究点生成を一般化された条件として組み合わせる。VehicleはFleetとして用途配分し、Transport Allocationから定常Transport Capacityを導出し、Logisticsは共有CapacityをCargo Flowへ配分する。静的Content Definition、可変State、派生状態を分離し、Application Command / Query境界を通して決定論的に進行するSimulation Core」**

として維持する。

ゲーム固有の面白さはEarth、Moon等の固有名をCoreへ埋め込むことで作るのではなく、Content DefinitionがGeneric Coreの組み合わせから異なる制約・産業構造・発展経路を形成することで作る。
