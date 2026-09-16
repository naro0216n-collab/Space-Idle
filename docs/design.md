# 宇宙開発Idleゲーム デザイン案 v0.5.0

## 文書ナビゲーション

- §1–4: ゲーム目的、中心ループ、発展像、初期評価範囲
- §5–7: Resource / Inventory / Priority / Facility / Industry
- §8: Spatial / Surface Location / Environment
- §9–10: Movement / Transport / Logistics / Cargo / Vehicle
- §11–14: Scientific Exploration / Research / Knowledge / Survey
- §15–16: Location発展、外部依存、自動進行
- §17–19: LLM、Application / UI、Save / Offline / Test
- §20: World / Scenarioと初期Content
- §21: 全体へ横断適用するゲームデザイン原則
- §22–23: ゲーム性評価範囲と現時点の定義

ゲーム上の意味は担当節を正本とし、§21は詳細メカニクスを再定義しない。Domain責務・State ownership・処理順は `architecture.md` を参照する。

---

## 1. 目的

現代の地球から始まり、探査・実験・研究によって知識生産能力を拡大し、その成果で新技術、新しい生産設備、輸送方式、研究手段を成立させ、最終的に太陽系規模の産業圏へ発展するIdle型宇宙開発シミュレーションを目指す。

着想元の一つとしてCivIdleがあるが、その再現を目的とはしない。宇宙開発固有の「技術的困難さ」「研究手段の世代交代」「距離と輸送」「立地」「現地資源利用」「ロケーション産業自立」を中核に据える。

ゲームの成長軸は契約報酬として資金を稼ぐ経営ループではなく、人工衛星、有人活動、探査機、研究所、実証設備等からResearch Pointを獲得し、それをより高い桁で生産・保持できる研究基盤へ移行することである。産業拡大は高度な研究手段を建設・維持するために必要となり、研究成果はさらに高性能な産業・輸送・研究資産を成立させる。この相互強化をIdleゲームとしての中心ループにする。

プレイヤーの楽しみは、単なる数値増加ではなく、研究・産業・物流ネットワークのボトルネックを発見し、既存資産の高度化と新世代資産への更新を比較しながら、より困難な研究と大規模な宇宙産業を成立させることに置く。

---

## 2. 基本コンセプト

ゲームの基本循環は以下とする。

探査・実験・研究設備を運転する  
→ Research Pointを獲得・蓄積する  
→ 技術を研究する  
→ 新しい設備・製法・輸送能力・研究手段を利用可能にする  
→ 生産、採掘、電力、建設、物流を拡大する  
→ より高コスト・高効率な研究資産を建設・維持できるようになる  
→ 研究点生成量と貯蔵可能量の桁が上がる  
→ より技術的に困難な研究へ進む

この循環の途中で、電力不足、輸送能力不足、特定中間材不足、建設能力不足、維持資材不足、研究点貯蔵不足等のボトルネックが発生する。プレイヤーは既存施設のLevelアップ、新世代設備の新設、産業配置や物流能力の変更を比較して解消する。

Idle要素は「一度構築した仕組みが時間とともに自動で運転し続ける」ことを担当する。時間は通常状態で自動進行し、プレイヤーは速度変更と一時停止を行える。日数を都度選択して進める方式を通常UIの主要操作にはしない。

Idleだからといって、プレイヤーの判断まで自動化しない。研究対象、設備投資、施設Level、新地域への進出、産業構成、拠点間輸送能力、輸送方式、宇宙船の用途配分、電力・建設能力の配分などの主要判断はプレイヤー側に残す。

---

## 3. 進行の基本像

ゲーム開始時点は現代水準とする。ロケットそのものを発明するところからではなく、既に基礎的な宇宙開発能力を持つ組織を運営する。

プレイヤー主体は、初期段階では特定企業・国家機関そのものに固定しない「宇宙開発組織」とする。外部の企業、政府、研究機関等は協力相手、供給者、需要主体、イベント主体として世界側に残すが、契約をこなして資金を稼ぐことをゲーム進行の中心にはしない。

初期のResearch Point源は、地上研究設備、人工衛星による継続観測、有人宇宙活動、近接領域の科学探査等である。これらは比較的低コストで維持できる一方、研究点出力と貯蔵能力は小さい。

産業・輸送能力が拡大すると、より大型の軌道実験設備、無人地表探査、サンプル解析、高度な地上研究設備等を維持できるようになる。さらに月面等へ恒久研究所や大規模実証設備を建設する段階では、建設質量、電力、精密機器、中間材、保守物流等の要求が一段上がる代わりに、研究点出力と貯蔵能力も桁違いに増加する。

この成長段階は地球からの距離そのものではなく、必要な研究設備、実験環境、輸送、電力、精度、継続運転、試作・実証の技術的困難さによって決める。単純な月面観測より高度な地上大型研究設備の方が高いResearch Tierとなることもあり得る。Locationは研究Tierそのものではなく、特定環境や物流条件を提供する。

大まかな世界発展のイメージは以下とする。

現代地球宇宙産業  
→ 人工衛星・有人近接領域研究  
→ 高頻度打上げ・軌道実験  
→ 再使用輸送・軌道上補給  
→ 高度無人探査・地表実験  
→ 恒久的な月面研究・産業拠点  
→ 初期ISRU・現地材料加工  
→ 月面工業化と大型研究設備  
→ 地球圏・月圏の産業統合  
→ 火星・小惑星・外惑星圏  
→ 太陽系規模の研究・産業圏

これは代表的な発展像であり、研究解禁や輸送経路をこの順序へ固定するチェックリストではない。研究は車両、設備、推進、補給等の能力を解禁するが、「特定研究を完了したから特定航路が開く」という直接ゲートにはしない。実際に到達可能かどうかは、機体性能、必要Operation、補給、環境、インフラ等から決める。

---

## 4. 最初のプレイ可能範囲

初期評価では以下までを扱う。

現代地球産業・研究  
→ LEO研究・物流  
→ 月探査  
→ 月面ロボット拠点  
→ 水・酸素等の初期ISRU  
→ 月面構造材生産  
→ 月面建設の部分的現地化  
→ 一部機械部品の現地生産

この時点でも、半導体、精密電子機器、高性能材料、高度制御装置などは地球依存とする。

地球側にも資源採掘・基礎生産を置く。ただし開始時の地球産業は「何でも無限に購入できる市場」ではなく、低効率の採掘・生産設備と有限在庫から始まり、研究と設備投資によって改善する対象とする。

---

## 5. 資源・在庫・能力

### 5.1 資源

元素を過度に細分化せず、産業上意味のあるカテゴリとして扱う。研究施設や高度産業の発展に伴い資源・中間材の種類は増やしてよいが、品目数の増加をそのまま物流設定数の増加へ転嫁しない。

初期候補：

原料
- Regolith / Aggregate Feed
- Metal Ore / Metal Feedstock
- Volatile-bearing Material
- Water

基礎工業品
- Structural Material
- Ceramics / Glass
- Oxygen
- Hydrogen / Fuel
- Propellant

高度工業品
- Machinery
- Electronics
- Precision Components
- Experimental Hardware
- Specialized Materials

知識系（通常貨物Inventoryとは分離する）
- Research Point
- Survey Knowledge
- Operational Experience

Research Pointは組織全体で利用する知識資源として扱い、通常の貨物Inventoryや所在地別在庫とは分離する。Survey Knowledgeは地域・対象ごとの知識、Operational Experienceは実運用から得られる技術・運用系統ごとの経験として、それぞれ別のKnowledge Stateを持つ。

Fundsは組織全体のResource売買決済通貨とする。Research、Construction、Maintenance、Vehicle運用、Player-owned Transport、Facility operation、Technology Unlock等の一般的な活動コストには使用しない。Fundsの増減はExternal Resource MarketにおけるResource ownership transferとScenario初期残高だけから発生し、契約報酬、時間経過による収入、一般External Service料金等の別用途を持たせない。

物理資源は所在地を持つ。地球の水1000t、月面の水1000t、LEOの水1000tは同価値ではない。

### 5.2 在庫・倉庫

各Operational Nodeでは最低限、現在在庫、予約済み在庫、入庫フロー、出庫フロー、輸送待ち、輸送中、到着待機、保管容量を区別する。

保管設備は一般貨物、バルク、液体、極低温、精密部品等のStorage Classへ分けられる。ある時点で保持できる量は `Physical Storage Capacity` と、電力・温調等の成立条件を反映して現在安全に利用できる `Usable Storage Capacity` というStock Capacityとして扱う。荷役や温調処理量のように一定時間あたりの有限処理能力がゲーム上の競合になる場合だけ、Cargo Handling / Conditioning等の別Service Capacityとして表現する。

輸送中貨物は到着先倉庫容量を事前予約しない。実到着時に入庫判定し、容量不足分は物流側の到着待機として残す。

### 5.3 CapabilityとService Capacity

設備・Vehicle・Infrastructureが「何を実行可能にするか」と、ある時点で保持できる量の上限と、複数用途が競合する時間あたり有限処理能力を分離する。数量概念は `Capability`、`Stock / Pool Capacity`、`Service Capacity` の三種類を混同しない。

`Capability` は、建設、観測、有人運用、Docking、特定Process等を実行できるという資格・機能の存在を表す。SiteRequirementやOperation適合判定は原則としてCapabilityを参照する。

`Service Capacity` は、一定時間あたりに供給・配分できる有限flowを表す。例：

- 発電
- 採掘
- 選鉱・精錬・製造
- 建設
- 輸送・軌道投入
- Cargo Handling / Surface Infrastructure / Local Distribution
- Conditioning等の時間あたり保管関連処理
- 保守
- Research execution
- Survey / Observation

Service CapacityはOperational Node等へ固定値として付与するのではなく、Facility、Fleet、Infrastructure等から発生させる。Facility/Fleet状態等から得るNominal supplyと、Resource、Power、Maintenance、Fleet、上流Service等の依存Allocationによって当tickにenableされるAvailable capacityを区別する。依存関係はPlanningで明示し、有限Resource / Fleet / Service / Stock・Pool admissionを一つの決定論的allocation graphとして解決する。複数用途が同じService Capacityを要求する場合は共通の配分規則で競合させ、同じ能力を各Domainが独立に100%利用できる構造にしない。

Service Capacityは用途に応じたscopeを持てる。Cargo Handling、Construction、Vehicle servicing等はOperational Node scopeを基本とし、Theory研究に用いるResearch executionのように組織全体へ集約して利用すること自体がゲーム上の意味を持つ能力はOrganization scopeを定義できる。Organization scopeへ供給される場合も、provider所在地でPower、Maintenance、Environment等のローカル成立条件を満たしたAvailable supplyだけを集約する。

このallocation graphへ当tickのDomain executionやmovementで新たに生産・到着したResourceを戻さない。それらはBoundary settlement後の次tick snapshotから利用可能になる。同tick依存関係に循環を持つContent / DefinitionはValidationでfail-closedとし、Domain固有の実行順や自己供給例外で解決しない。

Research Point生成率のような有限flowと、Research Point貯蔵上限のようなPool Capacityも区別する。前者をService Capacityとして扱う場合でも、後者はある時点で保持できる量の上限でありService Capacityではない。輸送能力もVehicle自体へ固定の`t/day`を持たせず、Vehicle性能、Fleet配分、二地点間のMovement Plan、補給・整備InfrastructureからService Capacityとして導出する。

### 5.4 Priorityと活動の優先順位

プレイヤーが複数の活動間で限られたResource、Power、Service Capacity、Research Point、物流能力等を配分する場合、優先度は5段階で指定する。

```text
1  最低
2  低
3  標準
4  高
5  最優先
```

新しい設定の標準値は3とする。Priorityは割合や重みではなく、「どの活動を先に成立させるか」を表す順序尺度とする。同じPriorityに属する活動は、利用可能なResource / Serviceの範囲で公平に充足する。複数日にまたがってStockを確保するProjectは、その蓄積をatomic要求へ任せず、Activity Priorityを持つReservation acquisitionとして在庫を段階的に確保する。停止はPriorityの一段階として表現せず、Pause等の活動状態として扱う。

PriorityはResourceやPower等の個別Requirementへ別々に設定するのではなく、原則としてPlayerが優先したい活動へ設定する。Construction Project、Research Project、Facility operation、Maintenance、Target Stock等の活動がPriorityを持ち、それらを成立させるために同時利用するResource / Service /既存Transport Capacityへその優先度を引き継ぐ。

一方、限られたFleetをどのTransport Allocationへ配備するかは、輸送能力を用意する側の別判断とする。需要側のActivity Priorityと、Fleet配備側のProvisioning Priorityを分離することで、高Priorityの需要が既に用意された輸送能力を優先利用できる一方、別用途のFleetを需要側が暗黙に奪う構造にしない。Transport AllocationのProvisioning Priorityも1〜5、標準値3とする。

### 5.5 FundsとExternal Resource Market

External Resource Marketは、Playerが所有する物理ResourceとFundsを交換する外部境界である。MarketはResearch、Construction、Vehicle運用等を金銭で代替する一般サービスではない。

Market Providerは特定Operational Nodeの `Market Interface` を通じてのみPlayer物流網へ接続する。Market InterfaceはFacilityそのものではなく、Operational Nodeと外部Providerの接続Stateである。別Locationや別恒星系へ市場能力を自動追従させず、そこに市場が存在する場合は別Provider / InterfaceとしてContentで定義する。

Resourceごとにbuy offer / sell offerを持てる。現段階ではoffer価格はContent Definitionが定義する固定条件とし、Market Provider Stateは価格形成の正本を持たない。一方、現在のsupply / demand availabilityは有限のDynamic Stateとし、Content Definitionが定める決定論的なrate / interval等のreplenishment ruleで更新できる。必要ならlead timeを持たせる。Funds Stateは組織全体の残高だけをauthoritativeに所有し、Buy用予約額はBuy Commitmentから導出する。複数Orderが同じ有限availabilityを競合する場合はTrade OrderのActivity Priorityと同順位の決定論的公平性で配分する。内生的な市場価格形成は別の意思決定を導入する場合にのみ独立設計する。

Trade Orderは有限総量を取引する `QUANTITY` と、継続的な目標rateを維持する `RATE` のどちらか一方をauthoritative targetとして持てる。`QUANTITY` は未達量を翌tick以降へ保持する累積目標である。`RATE` は各tickの現在throughput目標であり、あるtickの未達分を翌tickの目標へbacklogとして累積しない。Buyは任意のmaximum buy price、Sellは任意のminimum sell priceをPlayer intentとして持て、現在offerが条件外なら新規commit / settlementを行わない。

Buy OrderはFundsとprovider supplyを `Buy Commitment` として予約する。CommitmentはOrder、Resource、未移転量、commit時buy価格、予約Funds、予約provider supplyをMarket Domainの単一Stateとして所有し、Provider StateやOrder Stateへ同じ予約量を重複保存しない。利用可能Fundsとprovider supplyはこのactive commitmentを控除して導出する。provider lead timeが満了したCommitmentは次のcanonical Boundary以降に受入対象となり、Market Interface所在Operational Nodeで必要なCargo HandlingとInventory Admissionが成立した量だけResource ownershipをMarketからPlayer Inventoryへ移す。そのownership transferと同時に対応Fundsを消費してcommitmentを減らし、入庫不能分は外部側のcommitmentとして保持する。取消可能な未settled commitmentはFundsとprovider supplyを解放する。

Sell Orderは遠隔Resourceのためにprovider demandを先行予約しない。Player所有ResourceをMarket Interface所在Operational Nodeへ通常物流で運び、canonical snapshot時点で取引可能なResourceが実際に提示されている場合だけ、そのResource利用と当日のprovider demand availabilityをSell OrderのActivity Priorityで同時に競合させる。同じInventoryを生産・建設等と売却が二重利用しない。成立量だけownershipをPlayerからMarketへ移し、そのownership transfer時点の有効sell offer価格でFundsを加算する。そのFundsは次tick以降の新規購入に利用できる。Orderは既dispatch / 提示済み量を未手配量から控除して二重dispatchを防ぐ。Orderを変更・取消しても既settlementを遡及変更せず、既にPlayer-owned Cargoとしてdispatch済みのResourceは通常Cargo lifecycleを継続し、到着後は別の有効Sell intentが成立しない限りPlayer Inventoryに残る。

Market取引は通常のCargo、Transport、Cargo Handling、Inventory Admission等の物理契約を迂回しない。Funds支払いだけで任意のOperational NodeへResourceを生成せず、Resource売却だけで遠隔Inventoryから物量を消去しない。

---

## 6. 建築物・建設・維持

### 6.1 建築物の生産とUI

FacilityそのものとProcessを分離する。一つのFacilityが複数工程を持てる場合、プレイヤーは工程を選択できる。

生産設備についてUIは最低限、以下を設備単位で表示する。

- 現在選択されているProcess
- 投入資源と実効消費量/日
- 産出資源と実効生産量/日
- 稼働率
- limiting factor / blocker

資源画面の地点合計フローだけで済ませず、「どの建築物が何を消費し何を作るか」を設備画面から直接確認できるようにする。

### 6.2 建造投入物

建築物は原則として2〜3種類の明示的な実Resourceを消費して建造する。

簡易設備は2種類、高度設備は3種類程度を基本とする。構造・機械・電子等の抽象Componentへ複数の代替材をぶら下げる方式は採用しない。Construction Recipeが実際に消費するResourceと量を直接定義する。

建設資材の産地はRecipeの条件にしない。要求Resourceが建設地点Inventoryへ存在すれば、地球産・月産・他拠点産を区別せず利用できる。

したがって建造時の「現地代替」「現地材比率」「代替材選択」は廃止する。現地生産の価値は通常の採掘・加工・Inventory・物流だけで表現する。

```text
採掘
→ 加工
→ 必要ResourceとしてInventoryへ存在
→ 必要なら物流
→ 建設地点Inventory
→ 建設で消費
```

### 6.3 維持コスト

建築物は建造時に投入したResourceの何%かを継続的な維持コストとして要求する。

Content側は設備ごと、または設備群ごとに維持率を持つ。具体的な割合はバランス調整対象とし、構造テストで固定しない。

概念式：

```text
年間維持需要(resource)
= 建造・Upgradeで累積投入した resource × 維持率
```

維持資材は特別な税として消去せず通常Resourceとして扱う。当tickの維持実行は必要Resource / ServiceをExecution Requirement Bundleとして他用途と競合させ、将来の補充必要量はSupply RequirementとしてLogisticsへ流す。維持executionのfulfillmentが不足した場合は設備を即時破壊せず、保守充足率を下げ、その設備が供給するService Capacity、生産、研究点生成等を一貫して縮退させる。Capabilityそのものの有無と、現在供給できる量を混同しない。

通常の手動停止だけで維持費をゼロにしない。将来、長期保管・Mothballを導入する場合はPauseとは別状態とする。

### 6.4 Upgrade

Levelアップは同一世代設備への増設・拡張・改良として扱う。Upgradeにも2〜3種類の実Resourceを投入し、その投入分も以後の維持需要へ反映する。

### 6.5 Decommission

Facilityは明示的なDecommission Projectによって撤去できる。PauseとDecommissionを同一状態にしない。解体作業が不可逆段階へ入るまではProjectを取消可能とし、不可逆段階へ入ったFacilityは `DECOMMISSIONING` 状態として通常のProcess、Capability、Service Capacity供給を停止する。

DecommissionはConstruction系のwork / Resource allocationを利用してよいが、Facility lifecycleのauthoritative stateはFacility Domainが所有する。不可逆な解体開始後は通常のProcess、Capability、Service Capacity、Storage admission等へ新規Activityを受け入れない。既存stockや開始済みcommitmentを安全にsettleするため解体中にも残す必要がある受動能力だけはContent Definitionで明示し、その保持能力を新規Activityの供給能力として利用しない。既に開始済みで、そのFacilityの現存を前提に安全にsettleしなければならないUpgradeやMovement等の不可逆commitmentを破壊する状態遷移は開始できず、Applicationは対象Facilityを撤去できない理由をblockerとして示す。一方、将来の反復Process、Transport Allocation等のintentがそのFacility能力へ依存するだけなら撤去自体を禁止せず、能力喪失後は通常のblockerとして扱う。Storage Facilityでは、不可逆解体開始後に通常利用できなくなる容量を除いた残存Physical Capacityで現在stockを安全保持できない場合、Inventoryを消去・宙づりにせず撤去開始をblockする。

解体でResourceを回収する場合は累積投入ResourceとContent側のrecovery定義から量を決め、通常Inventory Admissionを通す。撤去対象Facility自身が供給するStorage Capacityを、そのFacilityのsalvage受入余力として数えない。回収Resourceを失わずにadmissionできない間は最終removalをsettleせず、Decommission Projectを完了待ちとして保持する。完了時にlive Facility参照を除去するが、完了済みProject等の履歴的状態をFacilityの現存へ依存させない。

---

## 7. 地球初期産業と採掘

初期地球には低効率の資源採掘建造物を用意する。地球を「必要資材が自動で無限供給される背景市場」とせず、プレイヤーが初期産業を拡張・更新する対象にする。

初期候補：

- Surface Aggregate Quarry / Open-Pit Material Mine
- Metal Ore Mine
- Industrial Water Intake / Processing Facility
- Basic Structural Material Plant
- Basic Machinery Works

地表資源は有限埋蔵量を消費する方式ではなく、地域ごとの `Resource Potential` と、そこへ投入した採掘設備能力の組み合わせから継続的な採掘Throughputを得る。Resource Potentialは「残量」や「建設可能鉱山数」ではなく、その地域が追加採掘投資をどの程度高い限界生産性で受け入れられるかを表す地質的機会とする。

同一Location内の採掘Facilityが供給するNominal Extraction Capacityを合算し、開発済みSurface Cell群から得られるEffective Resource Opportunityに対して単調増加・限界収益逓減となる関係で実効採掘量を求める。設備を追加して総採掘量が通常減少する式にはせず、同じ地域へ過度に集中するほど追加投資1単位あたりの増産量が低下する構造とする。

```text
Developed Surface Cells
→ Resource Potential / Effective Opportunity

Extraction Facilities
→ Nominal Extraction Capacity

Opportunity × Capacity
→ diminishing returns
→ Actual Extraction Throughput
```

採掘設備数にハード上限を設けない。プレイヤーは、既存拠点へ設備を追加するか、資源Potentialの高い隣接地域を新たに開発するか、別地点へ新Locationを設立するかを限界収益で比較する。

研究完了だけで既存採掘FacilityのThroughputを直接上昇させない。研究はより高性能なFacility Definition、Process、Construction / Modernization手段を解禁し、実際の建設・更新投資が完了して初めてInstalled Capacityが変化する。

地球の一般鉱物等は開始時から高いSurvey Knowledgeを持たせてよい。これはEarthという固有Location IDへのCore特例ではなく、Surface Cellごとの初期Knowledge差として表現する。初期設備は低効率・高維持比率・大規模という性格を持たせ、後に高効率設備や宇宙資源利用へ置換する理由を作る。

## 8. 空間・Operational Node・天体表面開発

物理的な位置を表すSpatial modelと、Inventory・Facility・Fleet等を所有して経済活動を行うOperational Nodeを分離する。

- Star System：複数のCelestial Body / Spatial contextを含む恒星系上位context。
- Celestial Body：Star System内の天体そのもの。
- Surface Cell：地表の物理・地理・資源・環境・Surveyの単位。
- non-surface Spatial Node：軌道、Lagrange領域、深宇宙上の運用地点等の物理的context。
- Operational Node：Inventory、Facility、Fleet、Storage、Power等を所有し、産業・研究・物流活動の端点となる運用拠点。
- Surface Location：Surface Cell上にプレイヤーが設立・拡張するOperational Nodeであり、連結した開発領域を追加で持つ。

すべてのSpatial NodeがOperational Nodeである必要はない。単なる軌道上の位置や未開発Surface Cellは物理的targetにはなれても、Inventoryや通常物流のNodeにはならない。一方、軌道研究所・Depot・Service Station等が存在する地点はnon-surface Spatial contextに結び付いたOperational Nodeとして扱える。

地表をSurface Cellへ分割し、資源・地形・環境・Survey・開発領域の正準単位とする。UIではヘックス主体の天体マップとして表現してよいが、球面を完全な六角形だけで覆うことや、全Cellが同面積・常に6隣接であることをCore仕様にはしない。天体ごとにSurface Cell数を変えてよく、各Cellは面積、隣接関係、天体上の位置を持つ。

```text
Star System
└ Celestial Body
   └ Surface Cell graph
      ├ static geology / resource potential
      ├ terrain / area / adjacency
      ├ dynamic environment
      ├ survey knowledge
      └ derived development affiliation
```

Surface CellはFacility配置スロットでもOperational Nodeでもない。通常Facilityを建設するたびにCellを選択させず、地理的開発と産業設備投資を別判断として扱う。

### 8.1 プレイヤーによるLocation設立

地表LocationはContent側が候補地点を固定列挙する方式を基本とせず、プレイヤーがSurvey結果と地形・資源・環境条件を比較してSurface Cell上の任意地点へ設立する。標準の月面開発では、開始時からプレイヤー運営の月面Locationを与えず、月周回等の既存non-surface Operational Nodeから広域Surveyを行い、その結果を比較して最初の月面Locationを選ぶ。既設Surface Locationを持つScenarioも同じ一般契約で定義できる。

Location設立前のSurface CellはInventoryや通常物流のNodeではない。最初の拠点は、既存Operational Nodeをstaging originとしてSurvey済みCellへFounding / Deployment Operationを実施することで成立させる。必要Resource、展開Facility / Fleet、輸送・着陸能力、準備作業、所要時間、SiteRequirementsを一つの設立Projectとして満たし、成功時にSurface LocationとOperational Node状態を生成する。

Founding PackageはContentで定義し、設立直後に通常の建設・物流へ移行するための最小運用基盤を構成する。Packageはstaging nodeで準備すべき実Resource、展開設備、必要Fleet等のdeployable manifestを定義し、Deployment開始時にsource側の物理Stateから移動payloadへ移す。成功時にはそのpayloadを初期Storage、Surface access / cargo handling、電力、Survey、Construction等のFacility、必要なら初期Fleet、Inventoryへ一度だけ展開する。Package Definitionだけを根拠にtarget側へ物理ResourceやFleetを生成しない。これにより「Locationを作るにはLocation側の倉庫やGatewayが既に必要」という循環依存を作らず、同時にResource / Fleet保存を維持する。

Surface Locationは一点座標ではなく、Operational Nodeとしての経済・産業・物流機能と、連続して開発したSurface Cell群の双方を持つ。設立Cellは `core cell` として領域の成立起点・連結性のanchorになるが、Location全体の代表Environment、代表Movement endpoint、無料Surface Infrastructure endpoint、Resource Opportunity特権にはならない。

```text
Surface Location
├ Operational Node state
│  ├ Inventory / Storage
│  ├ Facilities / Power / Service Capacity
│  └ Fleet / logistics connections
├ core cell: founding / territory-connectivity anchor
└ contiguous developed cells
```

新たな開発Cellは既存領域へ隣接することを基本とし、離れた地域を同一Locationの飛び地として無償取得しない。遠隔地域を利用したい場合は領域を連続的に拡張するか、別Locationを設立する。同一Surface Cellは原則として一つのLocationの開発圏へ所属し、Resource Opportunityを複数Locationへ複製しない。

### 8.2 Location拡大と複数拠点化

Location拡大は隣接Surface CellをDevelopment Projectとして取り込むことで表現する。Cell数に固定のハード上限は置かず、Survey、建設資源、Construction Service Capacity、時間、地形・環境、Surface Infrastructure等の負担を通じてsoft constraintを作る。

Location内部で個別ResourceをCell単位にroutingしない。一方、領域が巨大化しても共通Inventoryによって内部物流が無償・無限になる構造にはしない。Surface Cargo Gateway、Distribution Hub、access point等の位置依存InfrastructureはSurface Cell上の明示的な `access anchor` を形成できる。開発Cellから利用可能anchorまでの地理的spread、領域規模、利用するResource Opportunity、Gateway荷役等からLocal Distribution / Surface Infrastructure demandを集約し、有限Service Capacityとして配分する。

Core Cellであること自体は内部物流コストを免除しない。設立直後にcore cell上へGatewayやDistribution Hubが存在すれば結果として近距離になるだけであり、Infrastructureを撤去・停止すればそのanchor能力も失われる。複数anchorがある場合は利用可能なanchor集合から負荷を導出し、特定の代表Cellへ固定しない。

近接・隣接地域へ別Locationを設立すること自体は禁止しない。新Locationには独立したFounding、Storage、Power、Construction、access / Gateway、物流接続等の投資が必要となり、Inventoryも別Operational Nodeとして分離される。したがってプレイヤーは、一つのLocationを拡大して内部Infrastructure負荷を引き受けるか、複数Locationへ分散して設立・拠点間物流の固定費を負担するかを比較する。Location分割によって同じSurface CellのResource OpportunityやService Capacityを複製してはならない。

これにより惑星開発を、建物配置パズルではなく、調査済み地域をどこまで一つの産業圏へ統合し、どこから別拠点網として接続するかという地理的・経済的判断として表現する。

### 8.3 FacilityとSurface Cell

通常FacilityはOperational Nodeへ所属し、地表Location上であっても個別Cell配置を要求しない。採掘FacilityもSurface Location全体へNominal Extraction Service Capacityを供給し、開発済みCell群のEffective Resource Opportunityと組み合わせて採掘量を決める。軌道研究所やDepot等も、non-surface Operational Nodeへ同じFacilityモデルで所属できる。

一方、Landing Site、Surface Cargo Gateway、Mass Driver、局所日照を利用する発電設備、局所環境を直接利用・改変する設備等、物理的位置そのものが性能・接続・環境効果へ本質的に影響するFacilityだけはSurface Cellへ配置する。同じOperational Node内でFacilityを別Cellへ置き換えたときに、局所Physical Environment、Movement接続、性能、効果のいずれも変化しないFacilityはOPERATIONAL_NODEを基本とし、Cell選択を要求しない。これらも通常Facilityと同じ建設・維持・Power・Capability / Service Capacityモデルを使う。

「地表である」「軌道である」等のSpatial classificationと、温度・日照・大気・放射線等のPhysical Environment Requirementを同一Facetで代用しない。Operational Node-scope Facilityは、そのNodeのSpatial classification、Celestial Body global Physical Environment、およびInfrastructureが供給するCapability / Service Capacityで運用可否を判定する。Surface Cell localなPhysical Environmentが必要なFacilityはCell placementを要求して、その配置CellのPhysical Environmentを評価する。

人工的な与圧、温調、放射線遮蔽等はPhysical Environmentを書き換えない。Infrastructureは `pressurized workspace`、`thermal control`、`radiation shelter` 等のCapability / Service Capacityを供給し、それを必要とする活動が有限能力として利用する。

### 8.4 環境変化と将来のテラフォーミング

Surface Cellは静的な地質・地形と、将来変化し得るPhysical Environment Stateを分離する。

```text
Static
  geology / resource potential
  terrain / elevation / area

Dynamic physical environment
  temperature
  atmospheric pressure / composition
  radiation
  water / volatile state
  illumination and other local conditions
```

Physical Environmentの各fieldは、天体全体で共通に評価する値、Surface Cell localでのみ評価する値、天体global値へCell local overlayを合成する値のいずれかとして定義する。Celestial Body全体に共通する環境変化とSurface Cell localな変化を、そのfieldのscope / composition規則に従って合成して現在のPhysical Environmentを得る。Surface Locationそのものには代表Cell由来の単一Environment値を持たせず、Cell-local値を必要とする活動は明示Surface Cellを要求する。UIがLocation概要を表示する場合は、developed cellsの範囲、extrema、分布、core cell値等を説明用summaryとして提示できるが、そのsummaryをSimulation判定の正本にはしない。

テラフォーミングや自然変化はPhysical Environmentを更新し、Facility、Resource Opportunity、Movement、Construction等へ一般則として作用する。人工的な建屋内環境や保護InfrastructureはPhysical EnvironmentではなくCapability / Service Capacityとして扱う。

地表以外の軌道・宇宙空間NodeはSurface Cellを要求しない。LEO、月周回等はそれぞれの物理・運用構造に適したSpatial Nodeとして扱い、Inventory・Facility・Fleet等を持つ場合だけOperational Nodeとして経済活動へ参加させる。

## 9. 輸送と物流

本作の物流は、任意の成立済みOperational Nodeから任意の成立済みOperational NodeへResourceを輸送できる一般モデルとする。地球、惑星、衛星、小惑星、軌道拠点、深宇宙拠点、将来の別恒星系は同じSpatial / Movement / Transport / Logistics契約を利用する。

責務を次のように分離する。

```text
Spatial
  位置と二地点間の空間的関係を表す

Movement
  二地点間で必要となるOperationと移動特性を導出する

Transport
  Vehicle / FleetとInfrastructureから反復可能な輸送能力を供給する

Logistics
  Resourceをどこからどこへ、どの需要のために運ぶかを計画する
```

通常物流の二地点関係をOperational Node IDごとの静的な航路一覧として正本化しない。各EndpointのSpatial context、利用可能なaccess / Gateway、二地点間のtransport geometry、Movement Operation、Vehicle性能、InfrastructureからMovement PlanとTransport Serviceを導出する。新しいCelestial BodyやLocationを追加するときに、既存全地点とのOD別Route Definitionを追加することを要求しない。

### 9.1 Spatial relationとMovement

同一Surface上では実際のSurface geometryとGateway / access pointを利用する。宇宙空間では各Spatial contextが持つ安定したtransport geometryから二地点間のcharacteristicな空間関係を導出する。別恒星系についても同じ考え方を一段上の空間関係へ適用する。

Movementは少なくとも次の要素へ分解できる。

```text
origin-side operation
+
space / surface movement
+
destination-side operation
```

Powered Ascent、Spaceflight、Landing、Atmospheric Entry、Surface Transport等はMovement Operationとして表現する。同じSpatial relationでも利用するVehicle、推進方式、Infrastructureによって所要時間、Payload、Resource消費、Endurance要求は変化する。Spatial側のgeometryをそのまま輸送日数や単一の万能性能値へ読み替えず、Movement OperationとVehicle性能の組み合わせから運用結果を導出する。

Surface Cell自体はInventory Nodeや通常物流Nodeにはしない。成立前のSurface CellはFounding / Deployment等の一回限りの物理targetにはなれるが、通常物流は成立済みOperational Nodeをorigin / destinationとする。Surface Locationでは実際に利用するGateway / access Surface CellをEndpoint条件へ反映する。

### 9.2 通常輸送の抽象化とFleet配分

通常物流では個別のVehicle便を主要な管理対象とせず、Fleetの反復運用から方向別の定常Transport Capacityを導出する。Transport Serviceは少なくともPayload / Transport Capacity、Cargo latency、往復・回収を含むcycle、Propellantやservicing等の運用要求を持つ。

長距離輸送の戦略性は、有限Fleet、有限capacity、大きなlatency、運用Resource、Storage、Cargo Handling、先行備蓄から生じる。Playerの主要判断は個々の出発時刻ではなく、どのVehicleをどの拠点間輸送へ投入するか、どの程度のcapacityを用意するか、どのResourceやProjectを優先するか、どこへ在庫を前置きするか、中継・補給・積替えInfrastructureを整備するかに置く。

Fleet Allocationは次のどちらか一方をauthoritative targetとして設定できる。

- Units：投入するFleet数を指定し、そのFleet数から輸送能力を導出する。
- Capacity：必要な定常輸送能力を指定し、Vehicle性能と通常運用条件から必要Fleet数を導出する。

Transport AllocationのProvisioning Priorityは1〜5、標準値3とする。これは限られたFleetを複数Transport Allocationへ配備するときの優先順位であり、Cargo需要のActivity Priorityとは別の判断とする。

Transport AllocationのCapacityは「どれだけ輸送能力を用意するか」を表し、物流需要からFleetを無条件に増員しない。Fleet不足、推進剤不足、整備能力不足、Infrastructure不足等は別々のlimiting factorとして示す。

Transport Capacityは少なくともTarget、Nominal、Available、Used、Spareを区別する。推進剤・整備等の運用需要はFleetを割り当てただけで最大量を常時消費させず、実際のService利用率から発生させる。

### 9.3 Supply Requirementと先行物流

Facility、Construction、Maintenance、Industry、Research等のDomainは、自分の成立条件から現在必要なResourceだけでなく、既に決定済みのProject進行等から予測できる将来必要量をLogisticsへ提示できる。PlayerはOperational NodeごとにTarget Stockを設定できる。

物流計画は少なくとも次の情報を扱う。

- 現在必要なResource
- Project等から予測される将来必要量・継続消費率と予測必要時期
- Playerが設定したTarget Stock
- 現地Inventory / Reservation
- 既に輸送中またはInboundのCargo
- end-to-end latencyと利用可能Transport Capacity
- Activity Priority
- sourcing / path Policy

将来必要量は、その時点でResourceを消費・予約するものではない。Logisticsは予測必要時期、継続消費率、輸送lead time、現在在庫、Inbound量、利用可能capacityから、現在発送を開始する必要がある量・rateを判断する。将来まで十分な余裕がある高Priority Requirementが、現在必要な低Priority活動のResourceやTransport Capacityを直ちに先取りしない。

Projectの進捗や物流条件が変化した場合はProjected Material Readinessを更新する。Playerが明示的な期日を設定する機能を将来持つ場合は、Project進行から得る予測必要時期とhard deadlineを同一概念にしない。

sourceから発送するResourceは現地用途と同じResource allocationへ参加し、Logisticsだけがsource Inventoryを先取りしない。調達元と経路はPlayerのsourcing / path Policyの範囲でLogisticsが選択する。

External Resource Marketを調達元として利用する場合も、Market InterfaceでPlayer ownershipへ移ったResourceだけを通常物流のsource候補とする。Market Order自体がTransport Capacityを生成したり、Funds支払いだけで任意destinationへResourceを即時生成したりしない。

### 9.4 Cargo lifecycleとhandoff

Resourceはsource Inventoryからdispatchされた時点でLogistics上の輸送中Cargoとなる。通常物流では大量の個別便を生成せず、同じsource、destination、Resource、Transport Service、latency、dispatch rate等の条件が続く期間をCargo Flowとしてまとめて扱う。

別Fleetへ直接積み替えられる場合は、Cargo Handling等の必要条件を満たした上でStorageへ一旦入庫せず次のTransport Serviceへhandoffできる。一旦中継Operational Nodeへ荷卸しする場合は、その時点で物理Resourceのauthoritative ownershipをInventoryへ戻してStorage Capacityを使用し、次Legへ確保する必要があれば通常のReservation / commitmentを利用する。

最終目的地でも同じInventory admission契約を利用する。到着時に荷役・Storage条件が成立していないCargoはarrival waitingとなり、輸送完了前の物理量としてLogistics側へ残る。arrival waitingはCargo Handling / arrival holdingと反復利用可能Transport Capacityへbackpressureを発生させ、無制限の無料Storageとして機能しない。

輸送中Cargoは目的地Storageを事前予約しない。既に同じSupply Requirementへ割り当て済み・輸送中のCargoは未充足見込みから控除し、重複発送を防ぐ。

### 9.5 End-to-End輸送

Playerはorigin Operational Nodeと最終destination Operational Nodeを指定できる。経路未指定時はPlayerの明示Policyに従い、現在成立しているMovement / Transport ServiceとOperational Nodeからend-to-end pathを選択する。中継Nodeごとの再発送Commandを通常操作として要求しない。

同一Vehicle / Transport Serviceが途中でCargoを保持したまま運行を継続できる場合、Movement上に複数Operationが存在していても一つの物流Legとして扱える。実在するOperational Nodeで別Fleet / Transport ServiceへCargoを引き渡す地点だけが物流上のhandoff pointとなる。Spatial hierarchy上の中間contextそれ自体はhandoff pointではない。

LEOや月周回軌道等は有力な補給・積替え・整備Nodeになり得るが必須進行ゲートではない。有限・状況依存のFounding、Fleet relocation、Scientific Exploration等は一回限りのMovementとして同じMovement評価契約を利用し、通常物流を個体Missionの反復へ戻さない。

## 10. ロケット・宇宙船の建造と保有

ロケットや宇宙船は外部サービスだけでなく、プレイヤーが建造・保有できる物理資産とする。通常運用では同型機と所在Operational NodeごとのFleet数量として管理し、個体識別そのものを主要なゲーム操作にはしない。

Vehicle Definitionは固定の`t/day`能力ではなく、任意のMovement Planについて適合性、Payload、latency、運用Resource、反復cycleを導出できる性能を持つ。必要に応じて以下を含む。

- Dry Mass / Payload Capacity
- Propellant種類・容量・消費モデル
- Operation Capabilityと環境適合範囲
- 移動性能・Endurance
- Docking / Refueling等のInterface
- 最小Turnaroundと整備work / 維持・交換資材
- Production Capability
- 建造期間
- 2〜3種類程度の実Resource投入量

Spatial relationのcharacteristic geometryやOperation要件をVehicle性能と組み合わせ、Movement可否、1cycle当たりPayload、所要時間、推進剤需要、整備需要を導出し、Fleet投入数から定常Transport Capacityへ変換する。Delta-v等は適用可能なOperationの評価指標として利用できるが、すべてのMovementを一つの性能尺度へ固定しない。用途名や機種名へ物流能力を直接結び付けない。

Vehicle Assembly Facility等へ建造を指示すると、製造Capabilityと資源を消費してProduction状態へ入り、完了後に建造Operational Nodeの該当Fleetへ1隻追加される。

Fleet relocationは一回限りのMovementとして実際の所要時間を持つ。出発したFleetはsource側free Fleetから除かれ、Movement完了後にdestination側Fleetへ加わる。Transport Allocation解除時も運用中Fleetを瞬時にfree Fleetへ戻さず、必要な回収・再配置時間を経て解放する。

Vehicleは地球外を含む任意のOperational Nodeで、Production Capability、必要Resource、Service Capacity、SiteRequirementsを満たせば建造できる。完成unitは建造NodeのFleetへ追加され、配置換えはFleet Relocationとして実際のMovementを通る。通常の同型Vehicleは個体Entityではなく `Vehicle Definition × Operational Node × commitment state × quantity` で管理する。

不要になったVehicleはFleet Retirementとして退役できる。退役対象はそのOperational Nodeでfreeなunitから排他的にcommitし、所在Operational Nodeで通常のService Capacity / Resource requirementとして表現される解体workを経てFleet総数を減らす。Fleet Core専用の特殊な解体capacityを必須にせず、ContentはVehicle Assembly等の既存workshop能力を再利用でき、独立した解体設備がゲーム上の意味を持つ場合だけ通常Service typeとして定義する。不可逆な解体開始前は取消可能とし、開始後は対象unitを他用途へ戻さない。salvage量はVehicle Definitionのretirement recovery定義からunit数に応じて決め、通常Inventory Admissionを通す。回収Resourceをadmissionできない間は対象unitをRetirement commitmentに保持し、Fleet総数減少とsalvage admissionを最終settlementで整合させる。個体ごとの耐久・改修・履歴が主要な意思決定にならない限り、恒久Vehicle Entityを導入しない。

UIでは建造候補に加えて、保有Fleetについて所在、総数、輸送配分、Scientific Exploration拘束、再配置・回収中、未配分数を確認できるようにする。Transport Allocationでは目標mode、目標値、Provisioning Priority、必要隻数、実際の投入隻数、Nominal / Available / Used / Spare Capacity、運用資源需要、blocker / limiting factorを表示する。

打上げヴィークル、軌道間輸送船、着陸船、統合型宇宙船等を用途名称だけで使用制限しない。実性能がMovement Operation要件を満たすかで判定する。

## 11. 科学探査とResearch Point

資源Surveyとは別にScientific Exploration Campaignを導入する。

Scientific Explorationは必要性能を満たすFleet unitを一定数割り当て、一定期間の科学観測、近接探査、有人活動等を行うことでResearch Pointを得るシステムとする。

Campaignは必要に応じて以下を持つ。

- 探査対象・科学目的
- 必要Operation / Delta-v / Endurance / Payload
- 必要環境・Infrastructure / Capability
- 所要期間
- Research Point総量または生成率と上限
- 消耗資源

探査へ拘束されたFleet unitは輸送能力や別Campaignへ同時に割り当てられない。適合判定は「探査船」タグではなくVehicle性能から行う。物流とScientific Explorationは同じFleet資産を競合するため、輸送capacityを維持するか研究獲得へ回すかが明示的な資産配分判断になる。

同じ科学探査を無期限に繰り返すだけで無限Research Pointを得る構造は避ける。基本は有限Campaignとし、継続観測型は明示的な逓減・上限・運用コストを持たせる。

これにより、

宇宙船Fleetを建造する
→ 輸送能力へ投入するか探査へ割り当てるか選ぶ
→ 探査でResearch Pointを得る  
→ 新技術を研究する  
→ より高性能なFleet・研究設備・探査手段を成立させる

という資産配分のループを作る。

---

## 12. 研究システム

研究は本作の中心的な成長システムとする。

Research Point源は、地上研究設備、人工衛星、有人実験、軌道研究設備、Scientific Exploration、地表研究所、実証設備等である。研究源ごとに「この研究にしか使えないRP」という適用範囲は原則設けず、生成したResearch Pointは組織全体の共有Knowledge Poolへ蓄積する。

研究資産の世代差はTierで表現し、Tierが上がるとResearch Point生成効率と貯蔵能力を明確に向上させる。技術的に高度な研究は必要Research Pointも大きく増えるため、初期研究源だけで後期研究を進めることは理論上可能でも極めて遅くなる。

研究施設・研究資産はLevelを持てる。

- Tier：研究手段そのものの世代差・基礎効率差
- Level：既存設備への増設、拡張、改良、運用成熟

一世代前の高Level資産と新世代の低Level資産が一定範囲で競合できる一方、十分な規模では新Tierが効率面で優位になるよう調整する。

Research Pointの貯蔵上限は研究基盤の規模を表す。容量低下で既獲得点を消滅させず、新規生成を停止または制限する。

Research Projectは複数を並行して進められる。並行性は固定queue数ではなく、Research Point、必要Facility / Capability、Research execution Service Capacity、Prototype Resource、Demonstration条件等の実際のボトルネックによって制約する。共有Research Pointを複数Projectが必要とする場合はActivity Priorityに従って配分し、Project処理順の先着消費にしない。

Theoryに用いるResearch executionはOrganization scopeのService Capacityとし、所在地の異なる有効な研究providerから供給されたAvailable capacityを組織全体で競合利用できる。各providerは所在地でPower、Maintenance、Environment等のローカル条件を満たさなければOrganization poolへ能力を供給しない。研究施設をRP generatorだけに縮退させず、RP生成とResearch execution供給を独立した能力として持たせる。

---

## 13. 研究進行

研究開始・完了条件はResearch Pointだけに統一しない。Research Definitionは、研究内容に応じて以下の段階を必要な組み合わせ・順序で持てる。すべての研究を固定4段階へ強制しない。

- Theory：Organization scopeのResearch PointとResearch execution能力を使って理論・設計を成立させる。
- Prototype：明示Execution Siteで実際の試作Resource、Facility、Environment、Service Capacityを要求する。
- Demonstration：明示Execution Siteと指定条件を満たした状態で一定期間の実証を要求する。
- Operational Experience：実際の運用から蓄積されたKnowledge Stateを要求する。

Prototype / DemonstrationのExecution Siteは `Operational Node` を基本とし、研究内容がSurface Cell localなPhysical Environmentや位置そのものを必要とするときだけ `Surface Cell` を追加指定する。実施場所は特定Location IDで固定せず、Spatial classification、Environment、Capability、Service Capacityから候補を判定する。試作資材は通常のResource allocation / Supply Requirement、物流、Inventoryを通して確保し、Researchだけが別会計で資材を消費しない。

Operational ExperienceはResearch Project自身が時間経過だけで生成するpointではない。輸送、採掘、製造、有人運用等の実Domain activityが対応するexperience categoryへ知識を蓄積し、Researchはその状態をrequirementとして参照する。

研究完了によるTechnology Unlockは一つのauthoritativeなTechnology Stateへ記録する。Facility、Process、Vehicle等の各Domainは解禁状態を重複保存せず、この状態を参照する。研究完了で既存設備を自動更新しない。

研究項目は単純な「生産量+10%」より、新しいFacility、Process、推進方式、輸送方式、探査方法、建設方法、運用方法を開放することを優先する。

技術名称は「月面○○」のような地域名だけの抽象名称を避け、具体的な原理、装置、工程、運用技術として表現する。

主要分野：

- Launch & Propulsion
- Spacecraft & Logistics
- Orbital Construction
- Power & Thermal
- Survey & Planetary Science
- ISRU & Chemical Processing
- Materials & Metallurgy
- Manufacturing & Construction
- Robotics & Automation
- Communications, Navigation & Computing
- Human Spaceflight

一本道にはせず、発電方式、物流方式、研究資産更新、有人・無人開発等で複数の合理的経路を持たせる。

現段階ではCrew個人を独立Entityとして管理するDomainは導入しない。有人運用はcrew-ratedなVehicle / Facility特性、Habitation / Life Support等のCapability・Service Capacity、消耗ResourceのExecution Requirement / Supply Requirementとして表現する。将来Crewそのものが主要な意思決定対象になる場合にだけ、個体・人口Stateを独立Domainへ昇格する。

---

## 14. 資源Survey

資源SurveyはResearch Point獲得用のScientific Explorationとは別状態とする。

Survey対象は固定Locationではなく、Surface Cell × Resourceを基本とする。有限埋蔵量を探索するのではなく、その地域に資源が存在する可能性と、継続的な採掘投資を支えられるResource Potentialを段階的に明らかにする。

```text
Unknown
→ Presence Probability
→ Estimated Resource Potential
→ Measured Resource Potential
```

初期の広域観測では粗い地域差を示し、より詳細なSurveyによって候補CellのPotential推定幅を狭められる。Survey手段は観測位置・方式ごとに到達範囲と到達可能なKnowledge深度を持つ。軌道Remote SurveyはSurface Locationが存在しなくても対象天体の広域Cellを観測でき、最初のLocation候補比較に必要な粗いKnowledgeを与える。地表Surveyや近接観測は既設Location、展開Facility / Fleet、到達可能範囲等を必要とする代わりに、より高いKnowledge Levelまで精査できる。Surveyは基地設立・領域拡張・新鉱業拠点投資の意思決定情報を提供する。

Survey開始条件を単なる「providerとtargetが同一天体」に縮退させない。ProviderのObservation / Sensor Capability、providerのSpatial context、target coverage、必要Operation、到達可能Knowledge Levelから可否と進行を決める。広域軌道SurveyはSurface物流Movementを要求せず、Surface Surveyは通常物流や現地運用条件と接続できる。

完了Campaignは能力配分対象から自動的に外し、余剰Survey能力を未完了対象へ再配分する。地球の一般鉱物等、開始時点で既知とする資源はSurface Cellごとの初期Knowledgeを高い状態で定義してよい。

地質的Knowledgeと現在Physical Environmentの観測は将来分離可能にする。地質的Resource PotentialのKnowledgeは基本的に恒久知識だが、温度・大気・水相等の可変Physical Environmentはテラフォーミングや世界変化によって更新され得る。

## 15. Location開発とロケーション産業自立

Locationの発展は「到達したか」「基地が存在するか」という一段階ではなく、Survey、Founding、領域開発、資源利用、加工、研究維持、現地製造、自己拡張能力を段階的に成立させる過程として扱う。

典型的には、次の判断が繰り返される。

1. 既存Operational Nodeから未開発地域をSurveyする
2. 有望Surface Cellを比較する
3. Founding / Deployment Operationで新Locationを設立する
4. 最小運用基盤から通常物流・建設へ接続する
5. Resource PotentialとExtraction Service Capacityを組み合わせて現地資源利用を成立させる
6. 基礎工業・Surface Infrastructure・Gateway・研究設備を増強する
7. 同一Locationを拡張するか、別Locationを設立して拠点網を形成するか比較する
8. 複数Operational Nodeの産業・研究・物流を統合する

初期Contentでは月面開発がこの進行を代表するが、Coreで扱う概念はロケーション産業自立であり、特定天体名へ結び付けない。火星、小惑星、軌道拠点その他の地域でも同じLocation / Operational Nodeモデルを利用する。

ロケーション産業自立はbinaryな達成状態や単一の自給率ではなく、選択したLocationまたはOperational Node集合について、外部依存構造を示すderived analyticsとする。ここでいうロケーションは分析scopeを指し、Entity型としてのSurface Locationだけに限定しない。既存のProduction、Consumption、Supply Requirement、Import / Export、Unmet Requirementから、ResourceまたはContent定義のResource Group単位で少なくとも以下を確認できるようにする。

- local production
- local consumption / demand
- imports / exports
- unmet demand
- external inflow / dependency
- critical dependency / limiting resource

Mass、Energy、Propellant、Machinery等の特定カテゴリをGeneric Coreへ固定しない。Contentは表示・分析用Resource Groupを定義できるが、実際のResource flowを正本とする。

同じ集計を単一Locationだけでなく、任意のOperational Node集合へ適用できるようにする。これにより、ある天体上の複数Location、地球圏・月圏等の地域経済、Player全体についても同じ仕組みで依存構造を比較できる。

同じ高Potential地点へ採掘設備を追加し続けるほど限界収益は低下するため、既存Locationの高密度化、隣接地域への拡張、別Locationの設立と物流投資を比較する。資源枯渇を強制移住の主因にはしない。

発展した拠点をPrestige等で操作不能にしない。新技術は古い拠点のFacility更新、Surface Infrastructure増強、これまで利用効率の低かった地域の再開発理由にもする。


## 16. 自動進行と自動化

ゲーム時間は通常状態で自動進行する。プレイヤーは一時停止と複数段階の速度変更を行う。

Simulationは1 game dayをcanonicalな状態更新単位とする。一日の開始時点で利用可能なInventory、Reservation、Facility、Fleet、Environment、Capability、Service Capacity等をPhysical snapshotとして固定し、その日のPlanning / Allocationを決める。その日に新たに生産・到着・完了したResourceやCapabilityは、次の日のsnapshotから新しいAllocationへ利用する。

この日次境界は、本作が日単位以上の産業・研究・物流を集約して扱うためのSimulation解像度である。通常速度、高速進行、Offline Progressはいずれも同じ日次Simulation semanticsを利用する。複数日を一括して計算できる区間は実装上まとめてよいが、同じ期間を日次Simulationで進めた結果と同じStateへ到達することを契約とする。

自動化対象：

- 定常生産・採掘
- 各DomainからのExecution Requirement / Supply Requirement生成
- 設定済みActivity Priorityに基づくResource / Service / Stock admission配分
- Research Point生成
- 設定済み研究・Survey・Scientific Explorationの進行
- Transport Allocation目標に対する利用可能Fleetの投入
- 将来Supply RequirementとTarget Stockを含む物流計画
- 利用可能Transport CapacityへのCargo allocation
- 輸送latencyを考慮した先行dispatch
- Cargo arrival / direct handoff / Inventory admission
- 設定済みExternal Resource Market Trade Orderの反復充足
- 建設進行
- 保守
- Offline Progress

プレイヤー判断として残すもの：

- 研究対象とActivity Priority
- 旧研究資産のLevelアップと新Tier資産建設の比較
- 新規産業配置
- Facility operation / Project / Maintenance / Target Stock等のActivity Priority
- 拠点間物流能力の増強
- Vehicle建造とFleet用途配分
- Transport AllocationのUnits / Capacity目標とProvisioning Priority
- Target Stock
- sourcing / path PolicyとExternal Resource MarketのBuy / Sell Order、価格・数量・Priority
- 輸送方式・輸送資産の選択
- 新地域への進出、Location拡張と別Location設立の比較
- 発電方式
- 技術経路
- Facility Decommission / Vehicle Retirement
- 大規模再開発

施設、建設案件、研究、Survey、Scientific Exploration、Transport Allocation等は必要に応じて停止・再開できる。停止は取消と区別し、設定と進捗を保持する。

## 17. LLM利用方針

LLMはプレイヤーの主要判断を代行させない。

「LLMによってプレイヤーが考える対象が増えるなら利用する。プレイヤーが考える必要を減らす用途には原則利用しない。」

候補用途：

- 外部組織の要求・提案
- 特殊イベント
- 組織間交渉
- 科学的不確実性
- 研究上の問題
- 状況依存Mission
- 世界側の反応やニュース

通常SimulationとLLMは分離し、LLM応答待ちでゲーム進行を止めない。

---

## 18. Simulation Core / Application / UI

ゲームルールはUI、HTTP、LLMから独立させる。UIはSimulation内部を直接操作せず、Application LayerのCommand / Query境界を利用する。

主要Command例：

- 時間一時停止・再開・速度変更
- 軌道Survey結果からのLocation設立Deployment・隣接Surface Cell開発
- 建設計画・停止・再開・取消
- Facility停止・再開・Levelアップ・Process選択・Decommission計画/取消
- Activity Priorityを1〜5で設定
- Vehicle建造・Fleet再配置・Fleet Retirement計画/取消
- Transport Allocation設定・停止・再開・Units / Capacity目標・Provisioning Priority設定
- Target Stock設定
- sourcing / path Policy設定
- External Resource Market Buy / Sell Order作成・変更・取消
- 手動Cargo / 特殊Movement
- Research開始・停止・再開・Activity Priority設定
- Scientific Exploration開始・停止・Fleet unit割当
- Resource Survey開始・停止・配分
- 位置依存FacilityのSurface Cell配置

主要Query例：

- 世界・天体Surface Map・Operational Node / Location概要
- Surface CellのSurvey / Resource Potential / Environment / 開発状態
- Inventory・Reservation・Inbound / outbound flow・Storage / over-capacity状態
- Facility / Level / 維持充足率 / 配置種別
- Capability / Service CapacityのNominal / Available / Allocated / Spare
- Activity Priority / Execution Requirement Bundle / requested execution / fulfillment / limiting factor
- Process投入・産出・稼働率・limiting factor
- 建設候補・案件・将来Supply Requirement・Projected Material Readiness
- Vehicle建造候補・必要資材・blocker
- Fleet / Transport Allocation / Provisioning Priority / Transport Capacity / Retirement状態
- end-to-end Movement / Transport Service候補・latency・必要Operation
- Cargo Flow / handoff / arrival waiting / transport capacity shortfall
- Target Stock / current stock / inbound amount
- Funds / Market Provider / Market Interface / buy-sell offer / Trade Order / committed-settled量
- Research Point生成量・保有量・上限 / Technology Unlock / Operational Experience
- Research / Scientific Exploration / Survey
- Location領域、developed-cell Environment summary、Surface Infrastructure負荷、Gateway / access anchor候補
- LocationまたはOperational Node集合のロケーション産業自立・外部依存分析
- Bottleneck / blocker

UIは建設可否、維持率、機体適合、Movement、研究条件、資源・能力配分等を独自再計算しない。Core/Applicationが判断材料、Priority、Allocation結果、予測準備時期、停止理由を返す。Priority UIは5段階の固定選択として表示し、標準値3を「標準」として提示する。

## 19. Save / Load / Offline / テスト

Saveはversion付きSnapshotを基本とし、静的World Definition / Content DefinitionはContentから再構築し、可変Stateだけを復元する。Saveは `world_definition_id` と `scenario_id` をmetadataとして保持し、Load時にScenario初期化処理を再実行しない。保存対象にはFleet数量と排他的commitment、Transport Allocation目標とProvisioning Priority、Fleet Retirement / Relocation / Releasing、Inventory / Reservation、Market Provider State / Market Interface / Trade Order / Buy Commitment / Funds残高、Target Stock Policy、Cargo Flow / arrival waiting、Facility lifecycle / Decommission Project、Research Project / Execution Site、Dynamic Physical Environment、canonical game day等を含める。Movement Plan候補、Transport Service Plan、現在のTransport Capacity、Location Environment summary、Projected Material Readiness等は保存済み正本と重複させず再導出する。

Offline Progressは通常Simulationと別ルールにせず、実時間をゲーム時間へ変換した上で同じ日次時間進行経路を利用する。通常進行、高速進行、Offlineで同じgame timeを進めた場合は同じSimulation Stateへ到達することを不変条件とする。複数日をまとめるfast-forwardは、この同値性を保つ実装最適化としてのみ利用する。

テストは暫定バランス数値を固定せず、以下の構造的不変条件を優先する。

- Resource / Cargo / Fundsが負にならない
- Market ownership transferとFunds settlementがatomicで、Trade Order / provider availability / Buy Commitmentを二重利用しない
- RATE Trade Orderの未達量を翌tickへbacklogとして累積せず、QUANTITYとのcontrol semanticsが分離される
- Market offer価格はDefinition-backedで、Dynamic Stateは有限availability / replenishmentを所有する
- FundsがExternal Resource Market以外の活動コスト・報酬に使われない
- Inventory / Reservation / Logistics-owned CargoのResource保存が成立する
- Storageへ荷卸し済みResourceをInventoryとLogisticsが同時にauthoritative ownershipしない
- 輸送中Cargoが目的地倉庫を事前予約しない
- 複数のCargo arrivalがStorage不足時にも決定論的にadmission / waitingへ分かれる
- Industry / Extraction等の同tick outputが共有Storage / Pool admission容量を二重利用しない
- Execution Requirement Bundleが同一executionに必要な複数入力・Service・output admissionを整合したfulfillmentでsettleする
- PriorityLevelが1〜5の順序尺度として機能し、標準値3である
- 同Priority結果がEntity登録順へ依存しない
- Activity PriorityとTransport AllocationのProvisioning Priorityが別責務である
- Fleet Retirementがfree unitだけを排他的にcommitし、地球外建造・Relocation後のFleetにも同じ数量契約を適用する
- 任意の成立済みOperational Node pairについてSpatial / Movement契約から到達可能性を評価できる
- Surface LocationのEnvironment / Movement / Surface Infrastructureをcore cellへ暗黙縮退させない
- Body-global Physical EnvironmentとSurface Cell-local Environmentを区別する
- 新規Location / Celestial Body追加時に既存全地点との静的OD Route追加を要求しない
- Cargo Flow State量が経過tick数そのものに比例して増加しない
- dispatch済みCargo / Movementのlatencyが後続のInfrastructure変更で遡及変更されない
- 建設Recipeが明示Resourceを消費する
- Facility Decommissionがdurable commitmentや保管中stockを破壊せず、salvageが通常Inventory Admissionを通る
- 建設資材の産地による代替特例が存在しない
- Save / Load後の将来進行が一致する
- 通常速度、高速進行、Offlineで同じgame timeを進めた結果が一致する
- 同tick Domain登録順・呼出順でAllocation結果が変化しない
- Organization-scope Research executionとPrototype / DemonstrationのExecution Site scopeが分離される
- World Definition構築とScenario初期State適用が分離され、LoadでScenarioを再適用しない
- Location固有IDやVehicle用途名によるGeneric Core分岐が存在しない

## 20. World / Scenarioと初期Content

静的な宇宙・天体・Surface Cell topology、Resource Potential、基準Physical Environment等を `World Definition` とし、ゲーム開始時のPlayer所有・運用状態を `Scenario Definition` として分離する。

Scenario Definitionは少なくとも、開始時Operational Node / Surface Location、Facility、Fleet、Inventory、Knowledge / Technology、Funds、Market Provider State / Market Interface等の初期Stateを構成する。開始時の具体的数量・価格・Facility数はContent balanceであり、Core仕様として固定しない。

標準Scenarioでは、地球側に基礎産業・研究・打上げ・Vehicle建造を開始できる運用基盤、Resource売買に利用できる地球側Market Interface、地球周辺から月をRemote Surveyして候補を比較し、通常のResource / Fleet / Founding契約だけで最初の月面Locationを設立できる軌道・Fleet能力を持たせる。一方、開始時からプレイヤー所有の月面Surface Locationや完全な月面Resource Knowledgeは与えない。これらは開始時Facility数、Fleet数、Funds額等の固定値ではなく、標準Scenarioが成立させるゲームループ上の能力として扱う。月面進出はRemote Survey → 候補比較 → Founding Deploymentという通常ゲームループを使う。

初期Content候補：

### 地球初期Location

- General Research Laboratory
- Surface Aggregate Quarry
- Metal Ore Mine
- Industrial Water Processing Facility
- Basic Structural Material Plant
- Basic Machinery Works
- High-Energy Propulsion Test Stand
- Vacuum Materials Laboratory
- Launch Vehicle Factory / Vehicle Assembly Facility
- Launch Complex
- Launch Vehicle Refurbishment Facility
- Satellite Factory
- Mission Control

### 軌道・近接領域

- Earth Observation Satellite
- Microgravity Experiment Platform
- Crewed Orbital Laboratory
- Orbital Service Station
- Propellant Depot
- Assembly Platform
- Maintenance Dock
- Cargo Terminal

### 月周回・深宇宙

- Multispectral Survey Orbiter
- Neutron Spectrometry Orbiter
- Cislunar Relay Constellation
- Sample Return Vehicle
- Deep-Space Experiment Platform

### 月面

- Robotic Geology Station
- Cargo Depot
- Surface Solar Power Grid
- Regolith Harvester
- Volatile Extractor
- Water Extraction / Electrolysis
- Regolith Sintering
- Ore Processing
- Metallurgy
- Fabrication Workshop
- Machine Shop
- Heavy Equipment Assembly
- Sample Analysis Laboratory
- Vacuum Regolith Process Laboratory

### 初期Vehicle候補

- Reusable Launch Vehicle
- Reusable Orbital Cargo Tug
- Reusable Surface Cargo Lander
- Survey / Experiment Spacecraft

名称は用途を説明するために利用できるが、Operation可否を名称だけで固定しない。

## 21. 横断的なデザイン原則

この節は各メカニクスの詳細を再掲せず、ゲーム全体で維持する判断軸だけを示す。具体的な仕様は対応節を正本とする。

1. **研究と産業を相互強化させる。** Research Point → Technology → 産業・物流・研究手段 → より大きなResearch Pointという中心ループを維持し、距離や資金だけを進行軸にしない。§1–4、§11–13参照。
2. **実際のボトルネックをPlayer判断にする。** Resource、Power、Service Capacity、Fleet、Storage、輸送latency等から制約を発生させ、Activity Priorityは5段階・標準3で「どの活動を先に成立させるか」を表す。§5–6、§9、§16参照。
3. **技術は新しい手段を成立させる。** Research完了だけで既存Assetを一律強化せず、Facility、Process、Vehicle、推進、建設・運用方法等を解禁して投資判断を生む。§6–7、§10、§12–13参照。
4. **空間を経済状態から分離しつつ、距離と立地を意味のある制約にする。** Surface Cell、Operational Node、Surface Locationを役割分離し、任意の成立済みNode間Movementを一般則で評価する。§8–10参照。
5. **宇宙物流は個別便ではなくnetwork capacityとして設計する。** Fleet配備、Transport Capacity、latency、Cargo lifecycle、Target Stock、将来Supply Requirementから、長距離開発に先行計画の意味を持たせる。§9–10、§16参照。
6. **現地産業化の価値を通常Resource flowから生む。** 建設材の産地特例や有限鉱床による強制移住ではなく、Resource Potential、加工、Maintenance、Storage、物流負担からLocation発展を成立させる。§6–9、§15参照。
7. **Location開発を地理的・産業的な選択にする。** 一つのLocation拡張と複数拠点化、Gateway、Surface Infrastructure、Resource Potentialのtrade-offを保ち、必要な情報を判断地点で提示する。§8、§15、§18参照。
8. **Idle自動化は反復処理を担う。** Research対象、Priority、Fleet provisioning、物流方式、Resource売買、新地域進出、Asset廃止等の戦略判断はPlayerに残す。§16、§18参照。
9. **日次Simulationを共通時間軸にする。** 1 game dayをcanonical state-update単位とし、通常進行・高速進行・Offlineで同じgame timeの結果を一致させる。§16、§19参照。
10. **拡張時にCoreの個別例外を増やさない。** 新しい天体、Vehicle、Facility、Research、ResourceをContentと共通能力モデルで追加できる状態を維持する。全節および `architecture.md` 参照。

---

## 22. ゲーム性評価段階

現在の評価では、最終仕様や全コンテンツを固定するのではなく、本作の中心的な判断構造が成立する程度までメカニクスを実装して比較する。

優先評価対象：

- 自動時間進行、速度変更、一時停止、日次canonical Simulation、Offline同値性
- Research Point生成・貯蔵・消費
- Scientific ExplorationによるFleet unit拘束とResearch Point獲得
- Research Tier / Level
- 複数Research Project、Activity Priority、Theory / Prototype / Demonstration / Operational Experience
- Technology Unlock / Operational Experienceの単一状態所有
- 建築物の2〜3資源建造Recipe
- 建築物の維持Execution Requirement / Supply Requirement
- Execution Requirement BundleによるDomain横断の複合Resource / Service競合
- 5段階Activity Priorityと同順位fair allocation
- Stock / Pool admissionを含む出力側capacity競合
- Capability / Service Capacity分離と共有capacity競合
- Process入出力とUI可視化
- 地球初期採掘・基礎産業
- Vehicle建造とFleet数量管理
- Fleet AllocationのUnits / CapacityとProvisioning Priority
- Fleet AllocationからのTransport Capacity自動生成
- Nominal / Available / Used / Spare Capacityとlimiting factor
- 発電・配電・部分稼働
- 在庫・倉庫・Usable Storage Capacity・荷役 / Conditioning Service
- Celestial Bodyごとに可変数のSurface Cellを持つ天体マップ
- Surface拠点なしの軌道Surveyから任意地点へ最初のLocationを設立し、隣接Cellを開発する一連の進行
- Resource Potential / soft saturation採掘
- Surface Infrastructureによる大規模Locationの集約内部物流負荷
- Operational NodeとSurface Location / non-surface Spatial contextの分離
- 任意Operational Node間のSpatial Relation / Movement Plan導出
- 通常物流のaggregate Transport CapacityとCargo Flow
- direct handoff / Storage経由handoff / arrival waiting
- Supply Requirement、Target Stock、future-aware sourcing / dispatch
- 長距離latency下でのProjected Material ReadinessとTransport shortfall表示
- External Resource Marketの有限buy / sell availability、Funds決済、通常Cargo lifecycle / Storage契約
- Facility Decommission / Fleet Retirementとsalvage admission
- 推進剤の実資源化
- Surface Cell単位のResource Survey
- 初期月面ContentでのISRU・現地加工
- Location / Operational Node集合のロケーション産業自立・外部依存分析
- Save/Load / Offline Progress
- Bottleneck表示

FundsはResource売買決済だけに用い、一般的な活動コストや報酬ループを進行軸にしない。

複数戦略を比較し、低Tier研究資産を長く育てる戦略と新Tierへ早期更新する戦略、輸送力増強と現地生産、Vehicleを物流へ使うか探査へ使うか、地球産業を拡張するか宇宙資源利用へ早期移行するか等に合理的なトレードオフが生まれることを確認する。

---

## 23. 現時点でのゲーム定義

本作は、

「探査・実験・研究設備からResearch PointとOperational Experienceを獲得し、その研究成果で産業・輸送・研究基盤を拡大し、Surface Locationと軌道等のOperational Nodeを産業・物流Networkとして発展させながら、5段階Activity PriorityによるResource / Service Capacity配分、建設・維持・資源利用、将来需要を見越した物流、Fleet配分・Transport Capacityのボトルネックを解消し、ロケーション産業自立を高めつつ、より高い桁の知識生産と技術的に困難な宇宙開発へ進むIdle型宇宙産業シミュレーション」

と定義する。

ゲームの成長感は、契約を繰り返して資金残高を増やすことではなく、

「地球の低効率産業と人工衛星・地上研究設備で基礎知識を得る段階」
から
「自前のロケット・宇宙船Fleetを建造し、任意拠点間の定常輸送能力と科学探査へ配分する段階」
へ、
さらに
「恒久研究所を遠隔地へ建設し、大量の電力・物資・維持物流を投入して高効率研究を行う段階」
へ、
さらに
「現地産業が建設資材と維持資材を供給し、複数地域の研究・産業圏が相互に強化される段階」
へ移行することで表現する。
